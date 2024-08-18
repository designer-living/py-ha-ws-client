import abc
from abc import ABC
from time import sleep
from ws4py.client.threadedclient import WebSocketClient
import logging
import json
import threading
import itertools
import os

latest_states = {}
include_by_default = True


class HomeAssistantWsClient:

    @staticmethod
    def in_ha_addon():
        """
        Creates a WS client that works in a Home Assistant Add On
        """
        url = "ws://supervisor/core/websocket"
        token = os.environ['SUPERVISOR_TOKEN']
        return HomeAssistantWsClient.with_url(token, url)

    @staticmethod
    def with_host_and_port(token, hostname, port=8123):
        """
        Creates a Websocket client for the passed in hostname / port and uses the
        default Home Assistant path.
        """
        url = f'ws://{hostname}:{port}/api/websocket'
        return HomeAssistantWsClient.with_url(token, url)

    @staticmethod
    def with_url(token, url):
        """
        Creates a Websocket client for the passed in url this needs to be a full URL starting with ws://
        e.g. "ws://<host>:<port>/<path>
        """
        return HomeAssistantWsClient(token, url)

    def __init__(self, token, url):
        self.logger = logging.getLogger(__name__)
        self.url = url
        self.token = token
        self.ws_client = None
        self._reconnection_thread = None
        self._triggers = []
        self._disconnecting = False

    def connect(self):
        """
        Connect to the Home Assistant Web Socket API
        :return:
        """
        self._disconnecting = False
        self._reconnection_thread = threading.Thread(target=self._connect, daemon=True)
        self._reconnection_thread.start()

    def disconnect(self):
        """Disconnet from Home Assistant Web Socket API"""
        self._disconnecting = True
        if self.ws_client:
            self.ws_client.close()

    def get_states(self):
        """
        Blocking call to get all states from Home Assistant
        https://developers.home-assistant.io/docs/api/websocket/#fetching-states
        :return:
        """
        if self.ws_client.authenticated:
            callback = BlockingCallback()
            self.ws_client.get_states(callback)
            return callback.get_result()
        else:
            self.logger.warning(f"Can't get states as we aren't connected to home assistant")


    def get_state(self, entity_id):
        """
        Blocking call to get a single entities state from Home Assistant
        https://developers.home-assistant.io/docs/api/websocket/#fetching-states
        :return:
        """
        states = self.get_states()
        if states:
           for state in states:

                if(state.get("entity_id", None) == entity_id):
                    return state
        self.logger.warning(f"{entity_id} not found in Home Assistant")
        return None


    def get_config(self):
        """
        https://developers.home-assistant.io/docs/api/websocket/#fetching-config
        :return:
        """
        # TODO implement this
        pass

    def get_services(self):
        """
        https://developers.home-assistant.io/docs/api/websocket/#fetching-services
        :return:
        """
        # TODO implement this
        pass

    def subscribe_to_events(self, event_type):
        """
        https://developers.home-assistant.io/docs/api/websocket/#subscribe-to-events
        :param event_type:
        :return:
        """
        # TODO implement this
        pass

    def unsubscribe_from_events(self):
        """
        https://developers.home-assistant.io/docs/api/websocket/#unsubscribing-from-events
        :return:
        """
        # TODO implement this
        pass

    def fire_an_event(self):
        """
        https://developers.home-assistant.io/docs/api/websocket/#fire-an-event
        :return:
        """
        # TODO implement this
        pass

    # TODO pass in a trigger not entity_id/from_state/to_state so we can be more flexible
    def subscribe_to_trigger(self, entity_id, callback, from_state=None, to_state=None):
        """
        Subscribe to a trigger
        https://developers.home-assistant.io/docs/api/websocket/#subscribe-to-trigger
        :param entity_id:
        :param callback:
        :param from_state:
        :param to_state:
        :return:
        """
        self._triggers.append(
            Subscription(
                entity_id,
                callback,
                from_state,
                to_state
            )
        )

        if self.ws_client.authenticated:
            self.ws_client.subscribe_to_trigger(entity_id, callback, from_state, to_state)

    def unsubscribe_from_trigger(self):
        """
        Need to test this, but I guess this is the same as unsubscribing from an event
        https://developers.home-assistant.io/docs/api/websocket/#unsubscribing-from-events
        :return:
        """
        # TODO implement this
        pass

    def call_service(self, domain, service, entity_id=None, service_data=None):
        """
        Call a service:
        https://developers.home-assistant.io/docs/api/websocket/#calling-a-service
        :param domain:
        :param service:
        :param entity_id:
        :param service_data:
        :return:
        """
        if self.ws_client.authenticated:
            self.ws_client.call_service(domain, service, entity_id, service_data)
        else:
            self.logger.warning(f"Can't call {domain}.{service} as we aren't connected to home assistant")

    def validate_config(self):
        """
        https://developers.home-assistant.io/docs/api/websocket/#validate-config
        :return:
        """
        # TODO implement this
        pass

    def turn_on(self, entity_id):
        if self.ws_client.authenticated:
            self.ws_client.turn_on(entity_id)
        else:
            self.logger.warning(f"Can't turn on {entity_id} as we aren't connected to home assistant")

    def turn_off(self, entity_id):
        if self.ws_client.authenticated:
            self.ws_client.turn_off(entity_id)
        else:
            self.logger.warning(f"Can't turn off {entity_id} as we aren't connected to home assistant")

    def _authenticated(self, auth_success):
        if auth_success:
            for trigger in self._triggers:
                self.ws_client.subscribe_to_trigger(
                    trigger.entity_id,
                    trigger.callback,
                    trigger.from_state,
                    trigger.to_state
                )

    def connected(self):
        if self.ws_client is None or self.ws_client.client_terminated:
            return False
        return True

    def _disconnected(self):
        if(self._disconnecting):
            self.logger.warning("Disconnected.")
        else:
            self.logger.warning("Disconnected will attempt to reconnect.")
            self._reconnection_thread = threading.Thread(target=self._reconnect, daemon=True)
            self._reconnection_thread.start()

    def _internal_connection(self):
        while not self.connected():
            self.logger.debug("Home Assistant WebSocket - Attempting to connect...")
            self._connect_if_required()
            self.logger.debug(f"Home Assistant WebSocket - connection work? {self.connected()}")
            sleep(5)  # Give a moment before reconnecting to ensure the socket has been closed.

    def _connect(self):
        self.logger.debug("Home Assistant WebSocket - Starting connection thread")
        self._internal_connection()
        self.logger.debug("Home Assistant WebSocket - connection complete - connection thread ending")

    def _connect_if_required(self):
        if not self.connected():
            try:
                self.ws_client = _HaWsClient(self.url)
                self.ws_client.set_token(self.token)
                self.ws_client.set_disconnect_callback(self._disconnected)
                self.ws_client.set_authenticated_callback(self._authenticated)
                self.ws_client.connect()
            except Exception as e:
                self.logger.exception("Error connecting to Home Assistant Websocket", e)
                self.ws_client = None

    def _reconnect(self):
        self.logger.info("Home Assistant WebSocket - Starting reconnection thread")
        sleep(5)  # Give a second before reconnecting to ensure the socket has been closed.
        self._internal_connection()
        self.logger.info("Home Assistant WebSocket - Reconnection complete - reconnection thread ending")


# TODO add pings to ensure connectivity
class _HaWsClient(WebSocketClient):
    logger = logging.getLogger(__name__)
    authenticated = False
    connected = False
    id_generator = itertools.count(start=1)
    id_to_type = {}
    id_to_entity_id = {}
    id_to_callback = {}
    _entity_id_to_trigger = {}
    reconnection_thread = None
    homeassistant_token = ""

    def __init__(self, url):
        super().__init__(url)
        self._disconnected_callback = self.do_nothing
        self._authenticated_callback = self.do_nothing

    def set_token(self, token):
        self.homeassistant_token = token

    def set_disconnect_callback(self, callback):
        self._disconnected_callback = callback

    def set_authenticated_callback(self, callback):
        self._authenticated_callback = callback

    def opened(self):
        self.logger.info("Home Assistant WebSocket Connection Opened")
        self.connected = True

    def closed(self, code, reason=None):
        self.logger.warning("Home Assistant WebSocket Connection Closed. Code: {} Reason {}".format(code, reason))
        self.connected = False
        self.authenticated = False

        self.id_to_type.clear()
        self.id_to_entity_id.clear()
        self._entity_id_to_trigger.clear()

        self._disconnected_callback()

    def subscribe_to_trigger(self, entity_id, callback, from_state=None, to_state=None):
        self.logger.info(f"Subscribing for trigger for {entity_id} from_state: {from_state}, to_state: {to_state}")
        trigger = {
            "platform": "state",
            "entity_id": entity_id,
        }
        if from_state:
            trigger['from'] = from_state
        if to_state:
            trigger['to'] = to_state

        payload = {
            "type": "subscribe_trigger",
            "trigger": trigger,
        }

        message_id = self._send_and_return_message_id(payload, "subscribe_trigger")
        self.id_to_entity_id[message_id] = entity_id

        self._entity_id_to_trigger[entity_id] = Subscription(entity_id, callback, from_state, to_state)

    def turn_on(self, entity_id):
        """
        Attempts to turn on a device by guessing the domain from the entity id name
        """
        self.logger.info(f"Turning on {entity_id}")
        split_entity_id = entity_id.split(".")
        if len(split_entity_id) != 2:
            self.logger.error(f"Couldn't get domain from entity_id - is the entity_id correct? {entity_id}")
        else:
            self.call_service(split_entity_id[0], "turn_on", entity_id=entity_id)

    def turn_off(self, entity_id):
        """
        Attempts to turn off a device by guessing the domain from the entity id name
        """
        self.logger.info(f"Turning off {entity_id}")
        split_entity_id = entity_id.split(".")
        if len(split_entity_id) != 2:
            self.logger.error(f"Couldn't get domain from entity_id - is the entity_id correct? {entity_id}")
        else:
            self.call_service(split_entity_id[0], "turn_off", entity_id=entity_id)

    def call_service(self, domain, service, entity_id=None, service_data=None):

        payload = {
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if service_data:
            payload["service_data"] = service_data
        if entity_id:
            payload["target"] = {
                "entity_id": entity_id
            }
        return self._send_and_return_message_id(payload, "call_service")

    def received_message(self, m):
        self.logger.debug("Received message: {}".format(m))
        message_text = m.data.decode(m.encoding)
        message = json.loads(message_text)
        message_type = message.get('type', None)
        if message_type == "auth_required":
            self._do_auth_required()
        elif message_type == "auth_ok":
            self._do_auth_complete()
        elif message_type == "auth_invalid":
            self._do_auth_invalid(message)
        elif message_type == "result":
            self._do_result(message)
        elif message_type == "event":
            self._do_event(message)
        elif message_type == "pong":
            self._do_pong(message)
        else:
            self.logger.warning(f"Unexpected message: {message}")

    def _do_auth_required(self):
        self.logger.info("Home Assistant Web Socket Authorisation required")
        payload = {
            'type': 'auth',
            'access_token': self.homeassistant_token
        }
        self.logger.debug(f"Sending {payload}")
        self._send(payload)

    def _do_auth_invalid(self, message):
        self.logger.error("Home Assistant Web Socket Authorisation invalid: {}".format(message))
        self.authenticated = False
        self._authenticated_callback(self.authenticated)

    def _do_auth_complete(self):
        self.logger.info("Home Assistant Web Socket Authorisation complete")
        self.authenticated = True
        self._authenticated_callback(self.authenticated)

    def get_states(self, callback):
        payload = {
            'type': 'get_states'
        }
        message_id = self._send_and_return_message_id(payload, "get_states")
        self.id_to_callback[message_id] = callback

    # def subscribe_for_updates(self):
    #     payload = {
    #         "type": "subscribe_events",
    #         "event_type": "state_changed"
    #     }
    #     self._send_with_id(payload, "subscribe")

    def _do_result(self, message):
        self.logger.debug(self.id_to_type)
        success = message['success']
        if success:
            if 'result' in message:
                message_type = self.id_to_type.pop(message['id'])
                self.logger.debug(f"Got message type {message_type}")
                if message_type == 'subscribe_trigger':
                    entity_id = self.id_to_entity_id.get(message['id'])
                    self.logger.info(f"Subscribed for {entity_id}")
                elif message_type == 'get_states':
                    callback = self.id_to_callback.pop(message['id'])
                    if callback is not None:
                        callback.set_result(message['result'])
                    self.logger.debug(f"Received all states for message id: {message['id']}")
            else:
                self.logger.warning(f"No result in message: {message}")
        else:
            self.logger.error(f"Error code: {message['error']['code']} message: {message['error']['message']}")

    def _do_event(self, message):
        message_id = message.get('id', -1)
        if message_id in self.id_to_entity_id.keys():
            entity_id = self.id_to_entity_id.get(message['id'])
            self.logger.debug(f"Found entity id {entity_id} in {self.id_to_entity_id}")
            subscription: Subscription = self._entity_id_to_trigger.get(entity_id)
            callback = subscription.callback
            self.logger.debug(f"Found callback {callback} in {self._entity_id_to_trigger}")
            callback(entity_id=entity_id, message=message)
        else:
            self.logger.debug(f"Didn't find message id {message_id} in {self.id_to_entity_id}")

    def _do_pong(self, message):
        message_id = message['id']
        self.logger.debug(f"Pong received with ID[{message_id}]")

    def _send_and_return_message_id(self, payload, type_of_call):
        message_id = self._get_next_message_id()
        payload['id'] = message_id
        self.logger.debug(f"Adding {message_id} as type {type_of_call}")
        self.id_to_type[message_id] = type_of_call
        self._send(payload)
        return payload['id']

    def _get_next_message_id(self):
        return next(self.id_generator)

    def _send(self, payload):
        json_payload = json.dumps(payload)
        self.logger.debug(f"Sending: {json_payload}")
        self.send(json_payload)

    def do_nothing(self, *args):
        pass


class Subscription:
    def __init__(self, entity_id, callback, from_state, to_state) -> None:
        self.entity_id = entity_id
        self.callback = callback
        self.from_state = from_state
        self.to_state = to_state


class Callback(ABC):

    @abc.abstractmethod
    def set_result(self, result):
        pass

    @abc.abstractmethod
    def get_result(self):
        pass


class BlockingCallback(Callback):

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.event = threading.Event()
        self.result = None

    def set_result(self, result):
        self.result = result
        self.event.set()

    def get_result(self):
        self.event.wait(self.timeout)
        return self.result
