from time import sleep

from py_ha_ws_client.client import HomeAssistantWsClient, Callback
import logging

logging.basicConfig(level=logging.INFO)

hostname = "192.168.1.22"
token = "<from Home Assistant>"

client = HomeAssistantWsClient.with_host_and_port(token, hostname)
client.connect()

while not client.connected():
    sleep(1)

states = client.get_states()
print(states[0])


entity_id = "media_player.studio_amplifier"

def my_callback(entity_id, message):
    print(entity_id)
    to_state = message.get("event", {}).get("variables", {}).get("trigger", {}).get("to_state", None)
    if(to_state):
        state = to_state.get("state")
        attributes = to_state.get("attributes", {})
        volume = attributes.get("volume_level", "NOT SET")
        source = attributes.get("source", "NOT SET")
        print(f"{state} - {volume}, - {source}")
    


client.subscribe_to_trigger(
    entity_id="media_player.amplifier",
    callback=my_callback,
)

sleep(10)

client.turn_on(
    entity_id=entity_id
)

sleep(10)

# Change Volume
client.call_service(
    domain="media_player",
    service="volume_set",
    entity_id=entity_id,
    service_data={
        "volume_level" : "0.50"
    }
)

sleep(10)

# Change Source
client.call_service(
    domain="media_player",
    service="select_source",
    entity_id=entity_id,
    service_data={
        "source" : "AUX"
    }
)

sleep(10)

client.turn_off(
    entity_id=entity_id
)


sleep(60)
