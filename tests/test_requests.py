import asyncio

import pytest

from py_ha_ws_client import HaConnectionError, HaError


async def test_call_service_returns_result(make_client, ha_server):
    client = make_client()
    await client.connect()

    result = await client.call_service(
        "media_player",
        "volume_set",
        target={"entity_id": "media_player.amplifier"},
        service_data={"volume_level": 0.5},
    )

    assert result["echo"]["domain"] == "media_player"
    assert result["echo"]["service"] == "volume_set"
    assert result["echo"]["target"] == {"entity_id": "media_player.amplifier"}
    assert result["echo"]["service_data"] == {"volume_level": 0.5}


async def test_concurrent_calls_are_correlated_by_id(make_client):
    client = make_client()
    await client.connect()

    a, b, c = await asyncio.gather(
        client.call_service("light", "turn_on"),
        client.call_service("switch", "toggle"),
        client.call_service("fan", "turn_off"),
    )

    assert a["echo"]["service"] == "turn_on"
    assert b["echo"]["service"] == "toggle"
    assert c["echo"]["service"] == "turn_off"


async def test_call_service_failure_raises_and_leaves_client_usable(make_client):
    client = make_client()
    await client.connect()

    with pytest.raises(HaError):
        await client.call_service("light", "boom")

    # the connection still works for the next call
    ok = await client.call_service("light", "turn_on")
    assert ok["echo"]["service"] == "turn_on"


async def test_call_while_disconnected_raises(make_client):
    client = make_client()
    with pytest.raises(HaConnectionError):
        await client.call_service("light", "turn_on")


async def test_get_states(make_client):
    client = make_client()
    await client.connect()

    states = await client.get_states()
    assert any(s["entity_id"] == "light.kitchen" for s in states)


async def test_get_state_filters_by_entity_id(make_client):
    client = make_client()
    await client.connect()

    assert (await client.get_state("light.kitchen"))["state"] == "on"
    assert await client.get_state("light.does_not_exist") is None
