# py-ha-ws-client 1.0.0 — async rewrite design

## Goal

Replace the synchronous, `ws4py`-threaded client with a fully async
`asyncio` client built on `aiohttp`'s websocket client. This is a
breaking change: the entire public API becomes coroutine-based. Ship as
**1.0.0**, targeting **Python 3.12+**.

## Non-goals

- No backward-compatible sync shim. 0.x users migrate (README section).
- No new HA WS API coverage beyond what 0.x had plus what the task
  requires (events + triggers). The `pass` stubs (`get_config`,
  `get_services`, `fire_an_event`, `validate_config`) are dropped and
  can be added later.
- No public typed models for HA payloads — states/events/results are
  passed through as plain `dict` / `list[dict]`, as in 0.x.

## Package layout

```
py_ha_ws_client/
  __init__.py      # re-exports public API
  client.py        # HomeAssistantWsClient + internal machinery
  exceptions.py    # HaError, HaConnectionError, HaAuthError
tests/
  conftest.py      # fake HA server fixture
  fake_ha_server.py# aiohttp-based fake Home Assistant WS server
  test_*.py
pyproject.toml     # PEP 621, replaces setup.py + setup.cfg
```

`__init__.py` exports: `HomeAssistantWsClient`, `Subscription`,
`HaError`, `HaConnectionError`, `HaAuthError`.

`setup.py` and `setup.cfg` are deleted. `requirements.txt` is deleted
(deps live in `pyproject.toml`).

## Exceptions (`exceptions.py`)

```python
class HaError(Exception):
    """Base class for all py-ha-ws-client errors."""

class HaConnectionError(HaError):
    """The websocket could not be opened, or was lost unexpectedly and
    could not be re-established, or a request was made while
    disconnected."""

class HaAuthError(HaError):
    """Home Assistant rejected the access token (auth_invalid), or the
    auth handshake did not complete before connect_timeout."""
```

## Public API (`client.py`)

### Construction (unchanged signatures, still classmethods)

```python
HomeAssistantWsClient.with_host_and_port(token, host, port=8123, **opts)
HomeAssistantWsClient.with_url(token, url, **opts)
HomeAssistantWsClient.in_ha_addon(**opts)
```

- `with_host_and_port` builds `ws://{host}:{port}/api/websocket`.
- `in_ha_addon` uses `ws://supervisor/core/websocket` and
  `os.environ["SUPERVISOR_TOKEN"]`.
- `**opts` forwards to `__init__` keyword-only options:
  - `auto_reconnect: bool = True`
  - `connect_timeout: float = 10.0` — max seconds for the
    open + `auth_required`→`auth`→`auth_ok` handshake.
  - `heartbeat: float | None = 30.0` — passed to
    `session.ws_connect(heartbeat=...)`; aiohttp sends WS pings and
    treats a missing pong as a disconnect. `None` disables.
  - `session: aiohttp.ClientSession | None = None` — optional
    caller-owned session; if `None` the client creates and owns one,
    closing it on `disconnect()`.

The raw `__init__(token, url, *, auto_reconnect=..., ...)` stays public
and usable directly.

### Lifecycle

```python
async def connect(self) -> None
```
1. Create session if needed.
2. `ws = await session.ws_connect(url, heartbeat=heartbeat)`.
3. Run the auth handshake inline (see below), bounded by
   `connect_timeout` via `asyncio.wait_for`.
4. On `auth_ok`: start the receive loop as an `asyncio.Task`, resend
   any tracked subscriptions (none on first connect), return.
5. On failure: close the socket/session, raise `HaAuthError`
   (bad token / timeout) or `HaConnectionError` (socket failure).
   `connect()` never starts the auto-reconnect loop on its own initial
   failure — the caller gets the exception.

```python
async def disconnect(self) -> None
```
Idempotent. Sets a `_closing` flag so the receive loop and any
reconnect task exit without triggering reconnect. Cancels the receive
task and the reconnect task (if any), awaiting their completion.
Closes `ws`. Closes the session if owned. Resolves all pending request
futures with `HaConnectionError`. Safe to call when never connected.

```python
async def __aenter__(self): await self.connect(); return self
async def __aexit__(self, *exc): await self.disconnect()
```

### Properties

```python
is_connected      -> bool   # ws is open (not closing/closed)
is_authenticated  -> bool   # handshake completed on the current socket
```

### Requests (id-correlated)

Shared helper: `_send_command(payload) -> dict` —
assigns `payload["id"] = next(self._id_gen)`, registers
`fut = loop.create_future()` in `self._pending: dict[int, Future]`,
sends JSON, `return await fut`. The receive loop resolves the future
when the matching `result` arrives:
- `success is True`  → `fut.set_result(message.get("result"))`
- `success is False` → `fut.set_exception(HaError(code + message))`

A request issued while `not is_connected` raises `HaConnectionError`
immediately (no queueing).

```python
async def call_service(domain, service, target=None, service_data=None) -> Any
```
Payload: `{"type": "call_service", "domain", "service"}` plus
`"target": target` if given (raw dict, e.g. `{"entity_id": "..."}`)
and `"service_data": service_data` if given. Returns the `result`
payload (HA returns a context/response object). Raises `HaError` on
`success: false`.

```python
async def get_states() -> list[dict]          # type: "get_states"
async def get_state(entity_id) -> dict | None # get_states() then filter
```
`get_state` does one `get_states()` round-trip and returns the first
element whose `entity_id` matches, else `None`. (HA has no
single-entity fetch.)

Convenience wrappers (kept from 0.x, now async):
```python
async def turn_on(entity_id)   # call_service(domain_from(entity_id), "turn_on",  target={"entity_id": entity_id})
async def turn_off(entity_id)  # call_service(domain_from(entity_id), "turn_off", target={"entity_id": entity_id})
```
`domain_from` splits on `.`; raises `ValueError` if not `domain.object`.

### Subscriptions

```python
async def subscribe_events(event_type, callback)  -> Subscription
async def subscribe_trigger(trigger, callback)    -> Subscription
async def unsubscribe(sub_id) -> None
```

- `subscribe_events` sends `{"type": "subscribe_events",
  "event_type": event_type}` (omit `event_type` if `None` → all
  events). `subscribe_trigger` sends `{"type": "subscribe_trigger",
  "trigger": trigger}` where `trigger` is a raw HA trigger dict, e.g.
  `{"platform": "state", "entity_id": "media_player.amp",
  "to": "on"}`.
- The subscribe command is itself id-correlated: we `await` the
  `result` ack. The command `id` becomes the subscription id — HA tags
  every subsequent `event` message with that same `id`.
- On ack, record `Subscription(id, kind, params, callback)` in
  `self._subscriptions: dict[int, Subscription]` and return it.
- `callback` may be sync or async. The receive loop, on an `event`
  message, looks up the subscription by `message["id"]` and invokes
  `callback(message["event"])` — the HA `event` object (for triggers
  that contains `variables.trigger.{to_state,from_state}`). Async
  callbacks are scheduled with `asyncio.create_task`; sync callbacks
  are called directly. Every invocation is wrapped in
  `try/except Exception` with `logger.exception(...)` so one bad
  callback cannot kill the loop.
- `unsubscribe(sub_id)` sends `{"type": "unsubscribe_events",
  "subscription": sub_id}`, awaits the ack, drops it from
  `self._subscriptions`. `Subscription.unsubscribe()` is a bound
  coroutine calling back into `client.unsubscribe(self.id)`.
  Unknown/already-removed id is a no-op (debug log).

```python
class Subscription:
    id: int
    event_type: str | None      # for subscribe_events
    trigger: dict | None        # for subscribe_trigger
    callback: Callable
    async def unsubscribe(self) -> None
```

`Subscription` objects survive reconnect: their `id` is reused when the
subscription is re-established (HA assigns ids from our counter, and we
re-send with fresh ids — see Reconnect). The handle's `id` is updated
in place on resubscribe so `await handle.unsubscribe()` keeps working.

## Receive loop

One `asyncio.Task` (`self._recv_task`), started after a successful
handshake:

```
async for msg in ws:
    if msg.type is TEXT:      dispatch(json.loads(msg.data))
    elif msg.type in (CLOSE, CLOSING, CLOSED, ERROR): break
```

`dispatch` by `message["type"]`:
- `result`  → resolve `self._pending[id]` (success → result,
  failure → `HaError`). Unknown id: warn.
- `event`   → look up subscription, invoke callback (guarded).
- `pong`    → debug log (only relevant if we later add manual ping).
- `auth_*`  → ignored here; only seen during the handshake, which runs
  before the loop starts.
- anything else → warning.

When the loop exits (socket closed):
- set `is_authenticated = False`.
- if `self._closing` → return quietly (disconnect() drives cleanup).
- else if `auto_reconnect` → spawn `_reconnect_loop` task.
- else → resolve pending futures with `HaConnectionError`, log warning.

## Reconnect

`_reconnect_loop` (single `asyncio.Task`, only one at a time):

```
delay = 1.0
while not self._closing:
    try:
        await self._open_and_auth()          # new ws + handshake
        await self._resubscribe_all()
        start receive loop
        logger.info("reconnected")
        return
    except (HaError, aiohttp.ClientError, OSError, asyncio.TimeoutError):
        logger.warning("reconnect failed, retrying in %ss", delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)
```

- `_resubscribe_all` iterates `self._subscriptions.values()`, re-sends
  each subscribe command with a **fresh id**, awaits the ack, then
  re-keys the dict and updates `sub.id` in place. Pending (pre-drop)
  request futures were already failed with `HaConnectionError` when the
  old socket closed.
- `disconnect()` during backoff: `_closing` breaks the loop; the
  `asyncio.sleep` is cancelled by task cancellation.
- A `HaAuthError` during reconnect (token now invalid) is **not**
  retried forever silently — it is retried with backoff like other
  failures, but logged at `error` level each time. (Rationale: token
  may be rotated back; caller can `disconnect()` to stop.)

## Auth handshake (`_open_and_auth`)

Shared by `connect()` and `_reconnect_loop`. Bounded by
`connect_timeout` (only in `connect()`; reconnect relies on its own
backoff + `heartbeat`).

```
msg = await ws.receive_json()          # expect {"type": "auth_required"}
await ws.send_json({"type": "auth", "access_token": token})
msg = await ws.receive_json()
if msg["type"] == "auth_ok":      is_authenticated = True
elif msg["type"] == "auth_invalid":  raise HaAuthError(msg.get("message"))
else:                                 raise HaConnectionError(...)
```

Socket/JSON errors → `HaConnectionError`. `asyncio.TimeoutError` from
`wait_for` → `HaAuthError("auth handshake timed out")`.

## Concurrency / correctness notes

- All state (`_pending`, `_subscriptions`, `_id_gen`) is touched only
  from the loop that ran `connect()` and from the receive/reconnect
  tasks on that same loop — no locks needed, single-threaded asyncio.
- `_id_gen = itertools.count(1)` — never reset, so ids stay unique
  across reconnects (avoids stale `result`/`event` collisions).
- Sending is `await ws.send_json(...)`; concurrent `call_service`
  calls are fine (aiohttp serialises frames).
- Cancellation: `disconnect()` cancels `_recv_task` / `_reconnect_task`
  and awaits them, swallowing `CancelledError`.

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "py_ha_ws_client"
version = "1.0.0"
description = "Async Python client for the Home Assistant websocket API."
readme = "README.md"
license = { text = "Apache-2.0" }
requires-python = ">=3.12"
authors = [{ name = "foxy82", email = "foxy82.github@gmail.com" }]
keywords = ["Home Assistant", "Websocket", "asyncio"]
dependencies = ["aiohttp>=3.9"]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Framework :: AsyncIO",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Home Automation",
]

[project.urls]
Homepage = "https://github.com/designer-living/py-ha-ws-client"

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio>=0.24"]

[tool.setuptools]
packages = ["py_ha_ws_client"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

## GitHub Actions — PyPI publish

Keep `.github/workflows/python-publish.yml` (triggers on
`release: published`, builds with `python -m build`, publishes with
`pypa/gh-action-pypi-publish` using `secrets.PYPI_API_TOKEN`). Refresh:
`actions/checkout@v4`, `actions/setup-python@v5` with
`python-version: '3.12'`, pinned publish action bumped to current.
Add a separate `ci.yml` (push / PR) that installs `.[test]` and runs
`pytest` on 3.12 and 3.13 — so releases aren't the first time tests run
in CI.

## Tests

`tests/fake_ha_server.py` — `FakeHomeAssistant`, an `aiohttp.web`
app with one `GET /api/websocket` handler:
- sends `{"type": "auth_required", "ha_version": "test"}` on connect;
- expects `{"type": "auth"}`; if `access_token == expected_token` →
  `{"type": "auth_ok"}`, else `{"type": "auth_invalid",
  "message": "bad token"}` then close;
- after auth, reads commands:
  - `get_states` → `result` with a canned list;
  - `call_service` → `result` with `success` echoing back
    `domain`/`service` (or `success: false` when
    `service == "boom"`, to test the error path);
  - `subscribe_events` / `subscribe_trigger` → `result` ack; records
    `id`; test helper `push_event(sub_id, event)` sends an `event`
    message with that id;
  - `unsubscribe_events` → `result` ack; forgets the id.
- helpers: `close_client_sockets()` (force a disconnect to exercise
  reconnect), `connection_count`, `received_commands`.

`conftest.py` — `ha_server` fixture (aiohttp `TestServer`, yields the
running server + its `ws://` URL), `make_client` factory fixture.

Test cases (pytest-asyncio, `asyncio_mode = auto`):

| test | asserts |
|---|---|
| `test_connect_and_auth_ok` | `connect()` returns; `is_connected` and `is_authenticated` True |
| `test_auth_failure_raises` | wrong token → `HaAuthError`; socket + session closed; `is_authenticated` False |
| `test_connect_timeout` | server that never sends `auth_required` → `HaAuthError` after `connect_timeout` |
| `test_context_manager` | `async with` connects then disconnects; tasks gone afterwards |
| `test_call_service_result_correlation` | two concurrent `call_service` calls get their own results (ids not crossed) |
| `test_call_service_failure` | `service="boom"` → `HaError` raised, other calls unaffected |
| `test_get_states` / `test_get_state` | list returned; `get_state` filters; missing entity → `None` |
| `test_subscribe_events_delivers` | pushed event → callback invoked with the `event` payload |
| `test_subscribe_trigger_delivers` | trigger event delivered; sync + async callbacks both work |
| `test_bad_callback_does_not_kill_loop` | callback raises → logged, later events still delivered |
| `test_unsubscribe` | `await sub.unsubscribe()` → server forgets id; later pushes ignored; `unsubscribe` unknown id is a no-op |
| `test_disconnect_idempotent` | double `disconnect()` fine; `disconnect()` with no `connect()` fine |
| `test_reconnect_and_resubscribe` | `auto_reconnect=True`; server drops socket; client reconnects (backoff shrunk to ~0 via monkeypatched cap), re-auths, re-sends every tracked subscription; events flow again; `sub.id` still valid for `unsubscribe` |
| `test_no_reconnect_when_disabled` | `auto_reconnect=False`; dropped socket → `is_connected` False, pending futures fail with `HaConnectionError`, no reconnect task |

Reconnect tests keep wall time low by monkeypatching the backoff
constants (`_BACKOFF_START`, `_BACKOFF_CAP`) to small values.

## README rewrite

- One-paragraph intro: async client for the HA websocket API,
  Python 3.12+.
- Install: `pip install py_ha_ws_client`.
- Quickstart using `async with` + `asyncio.run`:
  `get_states`, `call_service`, `subscribe_trigger` with an async
  callback, clean exit.
- API reference: the constructors, `connect`/`disconnect`,
  `is_connected`/`is_authenticated`, `call_service`, `get_states`/
  `get_state`, `turn_on`/`turn_off`, `subscribe_events`/
  `subscribe_trigger`/`unsubscribe`, `Subscription`.
- "Resilience" section: auto-reconnect + backoff, heartbeat,
  re-subscription, the exception types.
- "Migrating from 0.x" section:
  - every method is now a coroutine — `await` it, run inside an event
    loop;
  - `connect()` now blocks until authenticated and raises on failure;
    delete `while not client.connected(): sleep(1)` loops;
  - `connected()` method → `is_connected` property; new
    `is_authenticated`;
  - `subscribe_to_trigger(entity_id=..., callback=...)` →
    `await subscribe_trigger(trigger={"platform": "state",
    "entity_id": ...}, callback=...)`; callback signature changed from
    `callback(entity_id, message)` to `callback(event)`;
  - `call_service(..., entity_id=...)` → `call_service(...,
    target={"entity_id": ...})`; now returns the result and raises on
    failure;
  - new `subscribe_events`, `unsubscribe`, `async with` support;
  - transport is aiohttp, not ws4py — drop `ws4py` from your deps.
- Delete the "TODO" section.

`main.py` at repo root is rewritten as a runnable async example
mirroring the README quickstart (or deleted if you'd rather not keep a
loose script — default: rewrite it).

## Open risks

- aiohttp `ws_connect` `heartbeat` sends WS-protocol pings, not HA
  `{"type":"ping"}`. HA's server responds to WS pings at the protocol
  level, so this is sufficient for liveness. If a deployment proxies
  in a way that answers WS pings without HA being alive, a manual HA
  ping could be added later behind the same `heartbeat` knob.
- `get_state` cost: a full `get_states` per call. Acceptable and matches
  0.x behaviour; documented in the docstring.
