import asyncio

import pytest

from py_ha_ws_client import HaAuthError, HomeAssistantWsClient
from tests.fake_ha_server import FakeHomeAssistant


async def test_connect_and_auth_ok(make_client, ha_server):
    client = make_client()
    await client.connect()

    assert client.is_connected is True
    assert client.is_authenticated is True
    assert ha_server.connection_count == 1


async def test_auth_failure_raises(make_client):
    client = make_client(token="wrong-token")

    with pytest.raises(HaAuthError):
        await client.connect()

    assert client.is_connected is False
    assert client.is_authenticated is False
    # the session the client created for itself must not leak
    assert client._session is None


async def test_failed_connect_closes_owned_session():
    server = FakeHomeAssistant(send_auth_required=False)
    await server.start()
    client = HomeAssistantWsClient.with_url(server.token, server.url, connect_timeout=0.2)
    try:
        with pytest.raises(HaAuthError):
            await client.connect()
        assert client._session is None
    finally:
        await client.disconnect()
        await server.stop()


async def test_connect_timeout_raises_auth_error():
    server = FakeHomeAssistant(send_auth_required=False)
    await server.start()
    client = HomeAssistantWsClient.with_url(server.token, server.url, connect_timeout=0.2)
    try:
        with pytest.raises(HaAuthError):
            await client.connect()
        assert client.is_connected is False
    finally:
        await client.disconnect()
        await server.stop()


async def test_context_manager_connects_and_disconnects(ha_server):
    async with HomeAssistantWsClient.with_url(ha_server.token, ha_server.url) as client:
        assert client.is_authenticated is True

    assert client.is_connected is False
    # background tasks are gone
    await asyncio.sleep(0)
    assert client._recv_task is None
    assert client._reconnect_task is None
