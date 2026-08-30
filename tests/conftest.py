import pytest_asyncio

from py_ha_ws_client import HomeAssistantWsClient

from .fake_ha_server import FakeHomeAssistant


@pytest_asyncio.fixture
async def ha_server():
    server = FakeHomeAssistant()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest_asyncio.fixture
async def make_client(ha_server):
    """Factory that builds clients against the running fake server and
    disconnects them all on teardown."""
    clients: list[HomeAssistantWsClient] = []

    def _make(*, token: str | None = None, url: str | None = None, **opts):
        opts.setdefault("connect_timeout", 2.0)
        client = HomeAssistantWsClient.with_url(
            token or ha_server.token, url or ha_server.url, **opts
        )
        clients.append(client)
        return client

    try:
        yield _make
    finally:
        for client in clients:
            await client.disconnect()
