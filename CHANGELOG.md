Change Log
=======================

v1.0.0
------------

Full rewrite to a fully async asyncio client. **Breaking change.**

* Transport moved from `ws4py` (thread-based, unmaintained) to
  `aiohttp`'s websocket client. Requires Python 3.12+.
* Every public method is now a coroutine.
* `connect()` runs the auth handshake and returns only once
  authenticated; raises `HaAuthError` / `HaConnectionError` on failure.
* `disconnect()` cancels all background tasks and closes the socket;
  idempotent. `async with` is supported.
* `call_service`, `get_states`, `get_state` are id-correlated
  request/response coroutines; `call_service` returns the result and
  raises on `success: false`.
* New `subscribe_events` / `subscribe_trigger` with sync-or-async
  callbacks invoked from the receive loop, returning a `Subscription`
  handle; `unsubscribe` / `await sub.unsubscribe()` supported.
* Auto-reconnect with capped exponential backoff (1s-30s), re-auth and
  automatic re-subscription; toggleable via `auto_reconnect`.
* Optional websocket keepalive via the `heartbeat` option.
* `is_connected` / `is_authenticated` properties.
* Packaging moved to `pyproject.toml`; `ws4py` dependency dropped,
  `aiohttp` added.

See the "Migrating from 0.x" section in the README.

v0.7
------------

Fix logging error

v0.6
------------

Implement disconnect method

v0.5
------------

Fix a couple of errors in log messages.

v0.4
------------

Move to github organisation - no code changes

v0.3
------------

Fix import error.

v0.2
------------

Allow us to use any URL so we can use this lib in a Home Assistant Addon.
Also added static methods for easy initialization
* HomeAssistantWsClient.with_host_and_port(token, hostname, port)
* HomeAssistantWsClient.with_url(token, url)
* HomeAssistantWsClient.in_ha_addon()

v0.1
------------

Initial Release
