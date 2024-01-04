# py-ha-ws-client
A Python client to make it easy to connect and consume data from the [Home Assistant web socket API](https://developers.home-assistant.io/docs/api/websocket/).


## Example

```
from time import sleep
from py_ha_ws_client.client import HomeAssistantWsClient

hostname = "<Home Assistant IP>"
#token = "<from Home Assistant>"

client = HomeAssistantWsClient.with_host_and_port(token, hostname)
# Or if in use in a Home Assistant Add on
# client = HomeAssistantWsClient.in_ha_addon()

client.connect()

while not client.connected():
    sleep(1)

# Get all the states as a list
print("Get all States")
states = client.get_states()
print("Print one state as an example")
print(states[0])


entity_id = "media_player.amplifier"

# Define a call back
def my_callback(entity_id, message):
    print(entity_id, message)

# Get the state of a single entity
state = client.get_state(entity_id)
print(state)    

# Register for updates for a specfic entity
client.subscribe_to_trigger(
    entity_id="media_player.studio_amplifier",
    callback=my_callback,
)

sleep(10)

# Send a turn on command
client.turn_on(
    entity_id=entity_id
)

sleep(10)

# Send a change volume command
client.call_service(
    domain="media_player",
    service="volume_set",
    entity_id=entity_id,
    service_data={
        "volume_level" : "0.50"
    }
)

sleep(10)

# Send a turn off command
client.turn_off(
    entity_id=entity_id
)

sleep(60)

```

## TODO

This is a work in progress there are a lot of TODOs in the code.