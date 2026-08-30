import asyncio

import pytest

from py_ha_ws_client import HaConnectionError
from py_ha_ws_client import client as client_module


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr(client_module, "_BACKOFF_START", 0.01)
    monkeypatch.setattr(client_module, "_BACKOFF_CAP", 0.05)


async def test_reconnects_and_resubscribes_after_drop(make_client, ha_server):
    client = make_client(auto_reconnect=True)
    await client.connect()
    received = []

    sub = await client.subscribe_events("state_changed", received.append)
    original_id = sub.id

    await ha_server.close_client_sockets()

    await _wait_for(lambda: ha_server.connection_count == 2)
    await _wait_for(lambda: client.is_authenticated)
    # subscription was re-sent on the new connection
    await _wait_for(lambda: ha_server.subscriptions)

    await ha_server.push_event(sub.id, {"event_type": "state_changed", "data": {}})
    await _wait_for(lambda: received)
    assert received[0]["event_type"] == "state_changed"

    # the handle still works for unsubscribe even though its id was refreshed
    await sub.unsubscribe()
    assert sub.id not in ha_server.subscriptions
    assert original_id not in ha_server.subscriptions


async def test_disconnect_during_reconnect_backoff_is_clean(make_client, ha_server):
    client = make_client(auto_reconnect=True)
    await client.connect()

    # Stop the server so every reconnect attempt fails and the loop sits
    # in its backoff sleep.
    await ha_server.stop()
    await ha_server.close_client_sockets()
    await _wait_for(lambda: client._reconnect_task is not None)

    await client.disconnect()

    assert client._reconnect_task is None
    assert client.is_connected is False


async def test_no_reconnect_when_disabled(make_client, ha_server):
    client = make_client(auto_reconnect=False)
    await client.connect()

    pending = asyncio.ensure_future(client.get_states())
    await asyncio.sleep(0)
    await ha_server.close_client_sockets()

    with pytest.raises(HaConnectionError):
        await pending

    await _wait_for(lambda: not client.is_connected)
    await asyncio.sleep(0.1)
    assert ha_server.connection_count == 1
    assert client._reconnect_task is None
