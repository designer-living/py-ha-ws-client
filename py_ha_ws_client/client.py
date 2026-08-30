"""Async client for the Home Assistant websocket API."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
from collections.abc import Callable
from typing import Any, Self

import aiohttp

from .exceptions import HaAuthError, HaConnectionError, HaError

_LOGGER = logging.getLogger(__name__)

_BACKOFF_START = 1.0
_BACKOFF_CAP = 30.0

EventCallback = Callable[[dict[str, Any]], Any]


class Subscription:
    """Handle for an active event or trigger subscription.

    Returned by :meth:`HomeAssistantWsClient.subscribe_events` and
    :meth:`HomeAssistantWsClient.subscribe_trigger`. ``id`` is the message id
    Home Assistant tags matching ``event`` messages with; it is updated in
    place if the subscription is re-established after a reconnect.
    """

    def __init__(
        self,
        sub_id: int,
        callback: EventCallback,
        *,
        event_type: str | None = None,
        trigger: dict[str, Any] | None = None,
    ) -> None:
        self.id = sub_id
        self.callback = callback
        self.event_type = event_type
        self.trigger = trigger
        self._client: HomeAssistantWsClient | None = None

    async def unsubscribe(self) -> None:
        if self._client is not None:
            await self._client.unsubscribe(self.id)


class HomeAssistantWsClient:
    def __init__(
        self,
        token: str,
        url: str,
        *,
        auto_reconnect: bool = True,
        connect_timeout: float = 10.0,
        heartbeat: float | None = 30.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self._auto_reconnect = auto_reconnect
        self._connect_timeout = connect_timeout
        self._heartbeat = heartbeat
        self._session = session
        self._owns_session = session is None

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._recv_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._closing = False
        self._authenticated = False

        self._id_gen = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subscriptions: dict[int, Subscription] = {}
        self._callback_tasks: set[asyncio.Task] = set()

    # -- constructors --------------------------------------------------------

    @classmethod
    def with_url(cls, token: str, url: str, **opts: Any) -> HomeAssistantWsClient:
        """Create a client for a full websocket URL, e.g.
        ``ws://homeassistant.local:8123/api/websocket``."""
        return cls(token, url, **opts)

    @classmethod
    def with_host_and_port(
        cls, token: str, host: str, port: int = 8123, **opts: Any
    ) -> HomeAssistantWsClient:
        """Create a client for a host/port using the default HA websocket path."""
        return cls(token, f"ws://{host}:{port}/api/websocket", **opts)

    @classmethod
    def in_ha_addon(cls, **opts: Any) -> HomeAssistantWsClient:
        """Create a client for use inside a Home Assistant add-on, using the
        supervisor websocket proxy and ``$SUPERVISOR_TOKEN``."""
        return cls(
            os.environ["SUPERVISOR_TOKEN"], "ws://supervisor/core/websocket", **opts
        )

    # -- properties --------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated and self.is_connected

    # -- lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Open the socket, run the auth handshake, and start the receive
        loop. Returns only once authenticated. Raises :class:`HaAuthError` or
        :class:`HaConnectionError` on failure."""
        self._closing = False
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            await asyncio.wait_for(
                self._open_and_auth(), timeout=self._connect_timeout
            )
        except TimeoutError as exc:
            await self._cleanup_failed_connect()
            raise HaAuthError("auth handshake timed out") from exc
        except BaseException:
            await self._cleanup_failed_connect()
            raise
        self._recv_task = asyncio.create_task(
            self._receive_loop(self._ws), name="ha-ws-recv"
        )

    async def _cleanup_failed_connect(self) -> None:
        await self._close_ws()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def disconnect(self) -> None:
        """Cancel background tasks, close the socket, and (if owned) the
        session. Idempotent."""
        self._closing = True
        for task in list(self._callback_tasks):
            task.cancel()
        self._callback_tasks.clear()
        await self._cancel_tasks()
        await self._close_ws()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
        self._fail_pending(HaConnectionError("client disconnected"))
        self._authenticated = False

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.disconnect()

    # -- handshake --------------------------------------------------------

    async def _open_and_auth(self) -> None:
        try:
            self._ws = await self._session.ws_connect(
                self.url, heartbeat=self._heartbeat
            )
        except (aiohttp.ClientError, OSError) as exc:
            raise HaConnectionError(f"could not connect to {self.url}: {exc}") from exc

        msg = await self._recv_handshake_json()
        if msg.get("type") != "auth_required":
            raise HaConnectionError(f"unexpected handshake message: {msg}")

        await self._ws.send_json({"type": "auth", "access_token": self.token})

        msg = await self._recv_handshake_json()
        mtype = msg.get("type")
        if mtype == "auth_ok":
            self._authenticated = True
        elif mtype == "auth_invalid":
            raise HaAuthError(msg.get("message", "auth invalid"))
        else:
            raise HaConnectionError(f"unexpected auth response: {msg}")

    async def _recv_handshake_json(self) -> dict[str, Any]:
        try:
            return await self._ws.receive_json()
        except (TypeError, ValueError, aiohttp.ClientError) as exc:
            raise HaConnectionError("connection closed during auth handshake") from exc

    # -- receive loop --------------------------------------------------------

    async def _receive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    try:
                        self._dispatch(json.loads(msg.data))
                    except Exception:
                        _LOGGER.exception("error handling message: %s", msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        finally:
            self._authenticated = False

        if self._closing:
            return
        if not self._auto_reconnect:
            _LOGGER.warning("Home Assistant websocket connection lost")
            self._fail_pending(HaConnectionError("connection lost"))
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            # A reconnect attempt is already running (its own socket just
            # dropped); let it notice via the failed pending requests.
            self._fail_pending(HaConnectionError("connection lost during reconnect"))
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name="ha-ws-reconnect"
        )

    def _dispatch(self, message: dict[str, Any]) -> None:
        mtype = message.get("type")
        if mtype == "result":
            self._handle_result(message)
        elif mtype == "event":
            self._handle_event(message)
        elif mtype == "pong":
            _LOGGER.debug("pong received id=%s", message.get("id"))
        else:
            _LOGGER.warning("unexpected message: %s", message)

    def _handle_result(self, message: dict[str, Any]) -> None:
        mid = message.get("id")
        fut = self._pending.pop(mid, None)
        if fut is None or fut.done():
            _LOGGER.warning("result for unknown message id=%s", mid)
            return
        if message.get("success"):
            fut.set_result(message.get("result"))
        else:
            error = message.get("error", {})
            fut.set_exception(
                HaError(
                    f"{error.get('code', 'error')}: {error.get('message', message)}"
                )
            )

    def _handle_event(self, message: dict[str, Any]) -> None:
        sub = self._subscriptions.get(message.get("id"))
        if sub is None:
            _LOGGER.debug("event for unknown subscription id=%s", message.get("id"))
            return
        self._invoke_callback(sub.callback, message.get("event"))

    def _invoke_callback(self, callback: EventCallback, event: Any) -> None:
        try:
            result = callback(event)
        except Exception:
            _LOGGER.exception("event callback %r raised", callback)
            return
        if asyncio.iscoroutine(result):
            task = asyncio.create_task(self._run_async_callback(result))
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)

    async def _run_async_callback(self, coro: Any) -> None:
        try:
            await coro
        except Exception:
            _LOGGER.exception("async event callback raised")

    # -- reconnect --------------------------------------------------------

    async def _reconnect_loop(self) -> None:
        self._fail_pending(HaConnectionError("connection lost, reconnecting"))
        delay = _BACKOFF_START
        while not self._closing:
            try:
                await self._open_and_auth()
                # Start the receive loop before resubscribing so the
                # subscribe acks are correlated and resolved.
                self._recv_task = asyncio.create_task(
                    self._receive_loop(self._ws), name="ha-ws-recv"
                )
                await self._resubscribe_all()
            except (HaError, aiohttp.ClientError, OSError, TimeoutError) as exc:
                await self._cancel_recv_task()
                await self._close_ws()
                level = logging.ERROR if isinstance(exc, HaAuthError) else logging.WARNING
                _LOGGER.log(level, "reconnect failed (%s); retrying in %.0fs", exc, delay)
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                delay = min(delay * 2, _BACKOFF_CAP)
                continue
            _LOGGER.info("Home Assistant websocket reconnected")
            return

    async def _resubscribe_all(self) -> None:
        # Rebuild into a fresh dict and only swap it in once every
        # subscription has been re-established, so a mid-way failure leaves
        # the full set intact for the next reconnect attempt.
        rebuilt: dict[int, Subscription] = {}
        for sub in list(self._subscriptions.values()):
            if sub.trigger is not None:
                payload: dict[str, Any] = {
                    "type": "subscribe_trigger",
                    "trigger": sub.trigger,
                }
            else:
                payload = {"type": "subscribe_events"}
                if sub.event_type is not None:
                    payload["event_type"] = sub.event_type
            new_id = await self._send_command(payload)
            sub.id = new_id
            rebuilt[new_id] = sub
        self._subscriptions = rebuilt

    # -- request plumbing --------------------------------------------------------

    async def _send_command(self, payload: dict[str, Any]) -> Any:
        if not self.is_connected:
            raise HaConnectionError("not connected to Home Assistant")
        mid = next(self._id_gen)
        payload["id"] = mid
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[mid] = fut
        try:
            await self._ws.send_json(payload)
        except (aiohttp.ClientError, OSError) as exc:
            self._pending.pop(mid, None)
            raise HaConnectionError(f"failed to send command: {exc}") from exc
        return await fut

    def _fail_pending(self, exc: Exception) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)

    async def _cancel_recv_task(self) -> None:
        task, self._recv_task = self._recv_task, None
        await self._cancel_and_wait(task)

    async def _cancel_tasks(self) -> None:
        tasks = [t for t in (self._reconnect_task, self._recv_task) if t is not None]
        self._recv_task = None
        self._reconnect_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            await self._cancel_and_wait(task)

    @staticmethod
    async def _cancel_and_wait(task: asyncio.Task | None) -> None:
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("background task raised while shutting down")

    async def _close_ws(self) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:  # pragma: no cover - best effort
                _LOGGER.debug("error closing websocket", exc_info=True)
        self._ws = None

    # -- requests --------------------------------------------------------

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, Any] | None = None,
        service_data: dict[str, Any] | None = None,
    ) -> Any:
        """Call a Home Assistant service and await its result. Raises
        :class:`HaError` if Home Assistant reports ``success: false``."""
        payload: dict[str, Any] = {
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if target is not None:
            payload["target"] = target
        if service_data is not None:
            payload["service_data"] = service_data
        return await self._send_command(payload)

    async def get_states(self) -> list[dict[str, Any]]:
        """Return the current state of every entity."""
        return await self._send_command({"type": "get_states"})

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """Return the state of a single entity, or ``None`` if unknown.

        Home Assistant has no single-entity fetch, so this performs one
        ``get_states`` round-trip and filters the result.
        """
        for state in await self.get_states():
            if state.get("entity_id") == entity_id:
                return state
        return None

    async def turn_on(self, entity_id: str) -> Any:
        return await self.call_service(
            _domain_of(entity_id), "turn_on", target={"entity_id": entity_id}
        )

    async def turn_off(self, entity_id: str) -> Any:
        return await self.call_service(
            _domain_of(entity_id), "turn_off", target={"entity_id": entity_id}
        )

    # -- subscriptions --------------------------------------------------------

    async def subscribe_events(
        self, event_type: str | None, callback: EventCallback
    ) -> Subscription:
        """Subscribe to Home Assistant events. ``event_type`` of ``None``
        subscribes to all events. ``callback`` may be sync or async and is
        called with each event's ``event`` payload."""
        payload: dict[str, Any] = {"type": "subscribe_events"}
        if event_type is not None:
            payload["event_type"] = event_type
        sub_id = await self._send_command(payload)
        return self._register_subscription(
            Subscription(sub_id, callback, event_type=event_type)
        )

    async def subscribe_trigger(
        self, trigger: dict[str, Any], callback: EventCallback
    ) -> Subscription:
        """Subscribe to a Home Assistant trigger (a raw trigger dict, e.g.
        ``{"platform": "state", "entity_id": "light.x", "to": "on"}``)."""
        sub_id = await self._send_command(
            {"type": "subscribe_trigger", "trigger": trigger}
        )
        return self._register_subscription(
            Subscription(sub_id, callback, trigger=trigger)
        )

    async def unsubscribe(self, sub_id: int) -> None:
        """Cancel a subscription by id. A no-op for unknown ids."""
        if sub_id not in self._subscriptions:
            _LOGGER.debug("unsubscribe for unknown subscription id=%s", sub_id)
            return
        await self._send_command(
            {"type": "unsubscribe_events", "subscription": sub_id}
        )
        self._subscriptions.pop(sub_id, None)

    def _register_subscription(self, sub: Subscription) -> Subscription:
        sub._client = self
        self._subscriptions[sub.id] = sub
        return sub


def _domain_of(entity_id: str) -> str:
    domain, _, obj = entity_id.partition(".")
    if not domain or not obj:
        raise ValueError(f"expected 'domain.object' entity_id, got {entity_id!r}")
    return domain
