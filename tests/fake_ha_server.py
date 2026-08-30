"""A minimal fake Home Assistant websocket server for tests.

It drives the ``auth_required`` -> ``auth`` -> ``auth_ok`` handshake, echoes
``result`` messages correlated by ``id``, and can push synthetic ``event``
messages to connected clients.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import WSMsgType, web

DEFAULT_STATES: list[dict[str, Any]] = [
    {"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 200}},
    {"entity_id": "media_player.amplifier", "state": "off", "attributes": {}},
]


class FakeHomeAssistant:
    def __init__(
        self,
        token: str = "test-token",
        *,
        send_auth_required: bool = True,
        ha_version: str = "test",
        states: list[dict[str, Any]] | None = None,
    ) -> None:
        self.token = token
        self.send_auth_required = send_auth_required
        self.ha_version = ha_version
        self.states = DEFAULT_STATES if states is None else states

        self.url: str | None = None
        self.connection_count = 0
        self.received_commands: list[dict[str, Any]] = []
        self.subscriptions: dict[int, dict[str, Any]] = {}

        self._sockets: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/api/websocket", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        port = self._runner.addresses[0][1]
        self.url = f"ws://127.0.0.1:{port}/api/websocket"
        return self.url

    async def stop(self) -> None:
        for ws in list(self._sockets):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # -- test instrumentation -------------------------------------------------

    async def push_event(self, sub_id: int, event: dict[str, Any]) -> None:
        """Send an ``event`` message tagged with ``sub_id`` to every client."""
        message = {"id": sub_id, "type": "event", "event": event}
        for ws in list(self._sockets):
            await ws.send_json(message)

    async def close_client_sockets(self) -> None:
        """Force every active client socket closed, as an unexpected drop."""
        for ws in list(self._sockets):
            await ws.close(code=1001, message=b"going away")

    @property
    def active_connections(self) -> int:
        return len(self._sockets)

    # -- request handling ------------------------------------------------------

    async def _handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(autoping=True)
        await ws.prepare(request)
        self.connection_count += 1
        self._sockets.add(ws)
        authed = False
        try:
            if self.send_auth_required:
                await ws.send_json(
                    {"type": "auth_required", "ha_version": self.ha_version}
                )
            conn_subs: set[int] = set()
            async for msg in ws:
                if msg.type is not WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if not authed:
                    authed = await self._handle_auth(ws, data)
                    if not authed:
                        break
                    continue
                await self._handle_command(ws, data, conn_subs)
        finally:
            self._sockets.discard(ws)
            # Home Assistant drops every subscription when the socket closes.
            for sub_id in conn_subs:
                self.subscriptions.pop(sub_id, None)
        return ws

    async def _handle_auth(self, ws: web.WebSocketResponse, data: dict) -> bool:
        if data.get("type") != "auth":
            return False
        if data.get("access_token") == self.token:
            await ws.send_json({"type": "auth_ok", "ha_version": self.ha_version})
            return True
        await ws.send_json({"type": "auth_invalid", "message": "bad token"})
        await ws.close()
        return False

    async def _handle_command(
        self, ws: web.WebSocketResponse, data: dict, conn_subs: set[int]
    ) -> None:
        self.received_commands.append(data)
        mid = data.get("id")
        mtype = data.get("type")

        if mtype == "get_states":
            await self._ok(ws, mid, self.states)
        elif mtype == "call_service":
            if data.get("service") == "boom":
                await self._err(ws, mid, "boom", "service exploded")
            else:
                await self._ok(
                    ws,
                    mid,
                    {
                        "context": {"id": f"ctx-{mid}"},
                        "echo": {
                            "domain": data.get("domain"),
                            "service": data.get("service"),
                            "target": data.get("target"),
                            "service_data": data.get("service_data"),
                        },
                    },
                )
        elif mtype in ("subscribe_events", "subscribe_trigger"):
            self.subscriptions[mid] = data
            conn_subs.add(mid)
            await self._ok(ws, mid, None)
        elif mtype == "unsubscribe_events":
            sub_id = data.get("subscription")
            self.subscriptions.pop(sub_id, None)
            conn_subs.discard(sub_id)
            await self._ok(ws, mid, None)
        elif mtype == "ping":
            await ws.send_json({"id": mid, "type": "pong"})
        else:
            await self._err(ws, mid, "unknown_command", str(mtype))

    @staticmethod
    async def _ok(ws: web.WebSocketResponse, mid: Any, result: Any) -> None:
        await ws.send_json(
            {"id": mid, "type": "result", "success": True, "result": result}
        )

    @staticmethod
    async def _err(ws: web.WebSocketResponse, mid: Any, code: str, message: str) -> None:
        await ws.send_json(
            {
                "id": mid,
                "type": "result",
                "success": False,
                "error": {"code": code, "message": message},
            }
        )
