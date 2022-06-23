from time import sleep

from py_ha_ws_client.client import HomeAssistantWsClient
import logging

logging.basicConfig(level=logging.INFO)

hostname = "192.168.1.22"
token = "<from Home Assistant>"

client = HomeAssistantWsClient(token, hostname)
client.connect()

while not client.connected():
    sleep(1)

states = client.get_states()
print(states[0])

sleep(60)
