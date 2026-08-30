# py-ha-ws-client

An **async** Python client for the [Home Assistant websocket API](https://developers.home-assistant.io/docs/api/websocket/).

Built on `aiohttp`. Requires **Python 3.12+**.

Version 1.0 is a full rewrite: every method is now a coroutine and the
transport is `aiohttp` instead of the unmaintained `ws4py`. See
[Migrating from 0.x](#migrating-from-0x) if you are upgrading.

## Install

```bash
pip install py_ha_ws_client
```

## Quickstart

```python
import asyncio

from py_ha_ws_client import HomeAssistantWsClient

TOKEN = "<long-lived access token from Home Assistant>"


async def main():
    async with HomeAssistantWsClient.with_host_and_port(TOKEN, "homeassistant.local") as client:
        # Fetch state
        states = await client.get_states()
        print(f"{len(states)} entities")
        print(await client.get_state("media_player.amplifier"))

        # React to changes
        async def on_change(event):
            trigger = event["variables"]["trigger"]
            new_state = trigger["to_state"]["state"]
            print(f"amplifier is now {new_state}")

        sub = await client.subscribe_trigger(
            {"platform": "state", "entity_id": "media_player.amplifier"},
            on_change,
        )

        # Call services
        await client.call_service(
            "media_player",
            "volume_set",
            target={"entity_id": "media_player.amplifier"},
            service_data={"volume_level": 0.5},
        )

        await asyncio.sleep(30)
        await sub.unsubscribe()


asyncio.run(main())
```

## API

### Constructors

```python
HomeAssistantWsClient.with_host_and_port(token, host, port=8123, **options)
HomeAssistantWsClient.with_url(token, url, **options)      # url like ws://host:8123/api/websocket
HomeAssistantWsClient.in_ha_addon(**options)               # uses $SUPERVISOR_TOKEN
```

**Options** (keyword-only):

| option | default | meaning |
| --- | --- | --- |
| `auto_reconnect` | `True` | reconnect, re-auth and re-subscribe after an unexpected disconnect |
| `connect_timeout` | `10.0` | seconds allowed for the open + auth handshake in `connect()` |
| `heartbeat` | `30.0` | websocket ping interval (aiohttp autoping); `None` disables |
| `session` | `None` | supply your own `aiohttp.ClientSession`; if omitted the client owns one and closes it on `disconnect()` |

### Lifecycle

```python
await client.connect()      # opens socket, runs auth handshake, starts the receive loop
await client.disconnect()   # cancels background tasks, closes socket (and owned session); idempotent

async with HomeAssistantWsClient.with_url(token, url) as client:
    ...
```

`connect()` returns only once authenticated and raises `HaAuthError`
(bad token or handshake timeout) or `HaConnectionError` (socket failure).

### Properties

- `client.is_connected` — the socket is open
- `client.is_authenticated` — the auth handshake completed on the current socket

### Requests

```python
result = await client.call_service(domain, service, target=None, service_data=None)
states = await client.get_states()
state  = await client.get_state("light.kitchen")   # None if unknown
await client.turn_on("light.kitchen")
await client.turn_off("light.kitchen")
```

Requests are correlated to their responses by message id. `call_service`
returns the result payload and raises `HaError` if Home Assistant reports
`success: false`. A request issued while disconnected raises
`HaConnectionError`.

### Subscriptions

```python
sub = await client.subscribe_events(event_type, callback)   # event_type=None -> all events
sub = await client.subscribe_trigger(trigger, callback)     # trigger is a raw HA trigger dict
await sub.unsubscribe()
# or:
await client.unsubscribe(sub.id)
```

`callback` may be a sync or async callable. It is invoked from the receive
loop with each matching event's `event` payload. A callback that raises is
logged and does not disturb the receive loop or other subscriptions.

`subscribe_*` returns a `Subscription` handle (`.id`, `await
.unsubscribe()`).

## Resilience

- **Auto-reconnect** (on by default): on an unexpected disconnect a
  background task retries with capped exponential backoff (1s → 30s),
  re-runs the auth handshake, and re-sends every active subscription. The
  `Subscription` handles you already hold keep working — their `id` is
  refreshed in place. In-flight requests fail with `HaConnectionError`.
- **Keepalive**: aiohttp sends websocket pings every `heartbeat` seconds
  and treats a missing pong as a disconnect.
- All background tasks are cancelled on `disconnect()` and on
  `async with` exit.

### Exceptions

- `HaError` — base class; also raised when a command returns `success: false`
- `HaConnectionError` — socket could not be opened / was lost / used while disconnected
- `HaAuthError` — token rejected, or the auth handshake timed out

## Migrating from 0.x

The 0.x client was synchronous and threaded (`ws4py`). 1.0 is
`asyncio`-native. Changes:

- **Everything is a coroutine.** `await` every call and run inside an
  event loop (`asyncio.run(...)`).
- **`connect()` now blocks until authenticated** and raises on failure.
  Delete `while not client.connected(): sleep(1)` loops.
- **`connected()` method → `is_connected` property.** New
  `is_authenticated` property.
- **`subscribe_to_trigger(entity_id=..., callback=...)` →
  `await subscribe_trigger(trigger={...}, callback=...)`.** Pass a raw HA
  trigger dict, e.g. `{"platform": "state", "entity_id": "light.x", "to": "on"}`.
  The callback signature changed from `callback(entity_id, message)` to
  `callback(event)`, where `event` is the HA event payload.
- **New `subscribe_events(event_type, callback)`** for raw event
  subscriptions.
- **`call_service(..., entity_id=...)` → `call_service(..., target={"entity_id": ...})`.**
  It now returns the result and raises `HaError` on `success: false`.
- **`get_states()` / `get_state()` are awaitable** and raise instead of
  logging a warning when disconnected.
- **Unsubscribe** is supported: `await sub.unsubscribe()` or
  `await client.unsubscribe(sub_id)`.
- **`async with` support** for guaranteed cleanup.
- **Transport is `aiohttp`.** Remove `ws4py` from your dependencies.
- The `turn_on` / `turn_off` helpers survive, now as `await client.turn_on(entity_id)`.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md). Run the tests with:

```bash
pip install -e ".[test]"
pytest
```
