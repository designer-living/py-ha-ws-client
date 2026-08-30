"""Runnable example for py-ha-ws-client. Fill in TOKEN and HOST and run:

    python main.py
"""

import asyncio
import logging

from py_ha_ws_client import HomeAssistantWsClient

logging.basicConfig(level=logging.INFO)

HOST = "192.168.1.22"
TOKEN = "<long-lived access token from Home Assistant>"

ENTITY_ID = "media_player.amplifier"


def on_trigger(event):
    to_state = event.get("variables", {}).get("trigger", {}).get("to_state")
    if not to_state:
        return
    attributes = to_state.get("attributes", {})
    print(
        f"{ENTITY_ID}: {to_state.get('state')} "
        f"volume={attributes.get('volume_level', 'n/a')} "
        f"source={attributes.get('source', 'n/a')}"
    )


async def main():
    async with HomeAssistantWsClient.with_host_and_port(TOKEN, HOST) as client:
        states = await client.get_states()
        print(f"{len(states)} entities; example: {states[0]}")
        print(await client.get_state(ENTITY_ID))

        await client.subscribe_trigger(
            {"platform": "state", "entity_id": ENTITY_ID}, on_trigger
        )

        await client.turn_on(ENTITY_ID)
        await asyncio.sleep(5)

        await client.call_service(
            "media_player",
            "volume_set",
            target={"entity_id": ENTITY_ID},
            service_data={"volume_level": 0.5},
        )
        await asyncio.sleep(5)

        await client.call_service(
            "media_player",
            "select_source",
            target={"entity_id": ENTITY_ID},
            service_data={"source": "AUX"},
        )
        await asyncio.sleep(5)

        await client.turn_off(ENTITY_ID)
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
