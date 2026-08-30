import asyncio

from py_ha_ws_client import HomeAssistantWsClient


async def test_disconnect_is_idempotent(make_client):
    client = make_client()
    await client.connect()

    await client.disconnect()
    await client.disconnect()

    assert client.is_connected is False
    assert client.is_authenticated is False


async def test_disconnect_without_connect_is_safe(ha_server):
    client = HomeAssistantWsClient.with_url(ha_server.token, ha_server.url)
    await client.disconnect()
    assert client.is_connected is False


async def test_disconnect_cancels_background_tasks(make_client):
    client = make_client()
    await client.connect()
    recv_task = client._recv_task
    assert recv_task is not None

    await client.disconnect()
    await asyncio.sleep(0)

    assert recv_task.done()
    assert client._recv_task is None
    assert client._reconnect_task is None


async def test_caller_owned_session_is_not_closed(ha_server):
    import aiohttp

    session = aiohttp.ClientSession()
    try:
        client = HomeAssistantWsClient.with_url(
            ha_server.token, ha_server.url, session=session
        )
        await client.connect()
        await client.disconnect()
        assert session.closed is False
    finally:
        await session.close()
