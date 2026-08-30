"""Exception types raised by :mod:`py_ha_ws_client`."""


class HaError(Exception):
    """Base class for all py-ha-ws-client errors."""


class HaConnectionError(HaError):
    """The websocket could not be opened, was lost unexpectedly and could
    not be re-established, or a request was made while disconnected."""


class HaAuthError(HaError):
    """Home Assistant rejected the access token (``auth_invalid``), or the
    auth handshake did not complete before ``connect_timeout``."""
