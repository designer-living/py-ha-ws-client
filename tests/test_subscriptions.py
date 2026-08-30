import asyncio

STATE_EVENT = {
    "event_type": "state_changed",
    "data": {"entity_id": "light.kitchen", "new_state": {"state": "off"}},
}

TRIGGER_EVENT = {
    "variables": {"trigger": {"to_state": {"state": "playing"}}},
}


async def _wait_for(predicate, timeout=1.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_subscription_ids_are_distinct_ints(make_client):
    client = make_client()
    await client.connect()

    a = await client.subscribe_events("state_changed", lambda e: None)
    b = await client.subscribe_events("call_service", lambda e: None)

    assert isinstance(a.id, int) and a.id > 0
    assert isinstance(b.id, int)
    assert a.id != b.id


async def test_subscribe_events_delivers_to_sync_callback(make_client, ha_server):
    client = make_client()
    await client.connect()
    received = []

    sub = await client.subscribe_events("state_changed", received.append)
    assert sub.id in ha_server.subscriptions
    await ha_server.push_event(sub.id, STATE_EVENT)

    await _wait_for(lambda: received)
    assert received[0] == STATE_EVENT


async def test_subscribe_trigger_delivers_to_async_callback(make_client, ha_server):
    client = make_client()
    await client.connect()
    received = []

    async def on_event(event):
        received.append(event)

    trigger = {"platform": "state", "entity_id": "media_player.amplifier"}
    sub = await client.subscribe_trigger(trigger, on_event)
    await ha_server.push_event(sub.id, TRIGGER_EVENT)

    await _wait_for(lambda: received)
    assert received[0] == TRIGGER_EVENT


async def test_bad_callback_does_not_kill_receive_loop(make_client, ha_server):
    client = make_client()
    await client.connect()
    good = []

    def boom(event):
        raise RuntimeError("callback is broken")

    bad_sub = await client.subscribe_events("state_changed", boom)
    good_sub = await client.subscribe_events("other_event", good.append)

    await ha_server.push_event(bad_sub.id, STATE_EVENT)
    await ha_server.push_event(good_sub.id, STATE_EVENT)

    await _wait_for(lambda: good)
    assert good[0] == STATE_EVENT
    assert client.is_connected


async def test_unsubscribe_stops_delivery(make_client, ha_server):
    client = make_client()
    await client.connect()
    received = []

    sub = await client.subscribe_events("state_changed", received.append)
    await sub.unsubscribe()

    assert sub.id not in ha_server.subscriptions
    await ha_server.push_event(sub.id, STATE_EVENT)
    await asyncio.sleep(0.05)
    assert received == []

    # unsubscribing an unknown id is a no-op
    await client.unsubscribe(99999)
