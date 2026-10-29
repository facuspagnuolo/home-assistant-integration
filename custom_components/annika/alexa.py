"""Annika's side of Alexa: what a house needs for Annika's backend to relay Alexa's orders to it.

Home Assistant's own `alexa` integration already turns Alexa's Smart Home
directives into service calls and answers discovery and state requests. What it
does not offer is a way to switch it on without editing a configuration file,
and a filter that follows what the customer chose in Annika. Annika's backend
turns it on here, and from then on it is the one that talks to this house:

    Alexa --> Lambda --> Annika backend --> /api/alexa/smart_home (this file) --> device

Home Assistant protects the endpoint with its own token, which only the backend
holds. Alexa never reaches the house directly.

Which devices reach Alexa is the same choice Siri follows: the one the backend
keeps per house and hands to the HomeKit module (see homekit.py), which this
module reads every time the choice changes or a device appears.

The endpoint does not exist until the owner turns Alexa on, and from then on it
is registered again each time Home Assistant starts. The module the integration
brings (`alexa.smart_home`) is not documented as an API either, so it is loaded
only when Alexa is turned on and a failure is logged instead of raised.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entityfilter import generate_filter
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .homekit import DEFAULT_DOMAINS, NEW_ENTITY_DELAY, AnnikaHomeKit

_LOGGER = logging.getLogger(__name__)

DATA_ALEXA = f"{DOMAIN}_alexa"

ALEXA_DOMAIN = "alexa"

WS_TYPE_ALEXA_STATUS = f"{DOMAIN}/alexa_status"
WS_TYPE_ALEXA_ENABLE = f"{DOMAIN}/alexa_enable"

STORAGE_KEY = f"{DOMAIN}.alexa"
STORAGE_VERSION = 1

ALEXA_LOCALE = "es-MX"

STATE_DISABLED = "disabled"
STATE_ENABLED = "enabled"


def expose_nothing(_entity_id: str) -> bool:
    return False


class AnnikaAlexa:
    """Alexa's endpoint in this house: turning it on and keeping what it exposes right."""

    def __init__(self, hass: HomeAssistant, homekit: AnnikaHomeKit) -> None:
        self._hass = hass
        self._homekit = homekit
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._enabled = False
        self._config: Any = None
        self._serving = asyncio.Lock()
        self._reload_timer: Any = None

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._enabled = bool(stored.get("enabled", False))

    @callback
    def status(self) -> dict[str, str]:
        return {"state": STATE_ENABLED if self._enabled else STATE_DISABLED}

    async def async_enable(self) -> dict[str, str]:
        """Open the endpoint, if the house has none, and remember it so it opens again after a restart.

        Remembered only once the endpoint answers: a house where it could not be
        opened is not told it is enabled.
        """

        await self._async_serve()
        if not self._enabled:
            self._enabled = True
            await self._store.async_save({"enabled": True})
        return self.status()

    async def async_sync(self) -> None:
        """Open the endpoint of a house whose owner turned Alexa on, and bring what it exposes up to date.

        Runs once Home Assistant has started: until then the entities of the
        other integrations are not in the registry, and neither are Annika's, so
        the endpoint would expose what Annika manages. A house that never turned
        Alexa on has no endpoint and nothing happens.
        """

        if self._enabled:
            await self._async_serve()

    async def _async_serve(self) -> None:
        async with self._serving:
            if self._config is None:
                self._config = await self._async_open()
            self.refresh()

    async def _async_open(self) -> Any:
        integration = await async_get_integration(self._hass, ALEXA_DOMAIN)
        component = await integration.async_get_component()
        smart_home = component.smart_home

        class AnnikaAlexaConfig(smart_home.AlexaConfig):
            """Home Assistant's Alexa configuration, with a filter that can change while it runs."""

            _exposes = staticmethod(expose_nothing)

            def set_filter(self, entity_filter: Any) -> None:
                self._exposes = entity_filter

            @callback
            def should_expose(self, entity_id: str) -> bool:
                # Configuration and diagnostic entities (a camera's "record" or "status LED" switch) belong to
                # the device, not to the house: the list of devices to choose from never offers them, so none
                # of them reaches Alexa, whatever its domain says.
                entry = er.async_get(self.hass).async_get(entity_id)
                if entry is not None and entry.entity_category is not None:
                    return False
                return bool(self._exposes(entity_id))

        # Without a client id and secret Home Assistant does not report states to
        # Amazon: that is the backend's to do, with credentials this house never holds.
        config = AnnikaAlexaConfig(self._hass, component.SMART_HOME_SCHEMA({"locale": ALEXA_LOCALE}))
        await config.async_initialize()
        self._hass.http.register_view(smart_home.SmartHomeView(config))
        return config

    @callback
    def refresh(self) -> None:
        """Expose what Siri exposes: the default, with what the backend added and took away.

        Home Assistant reads an empty filter as "everything", so this one is
        always built with the default domains.
        """

        if self._config is None:
            return
        entity_filter = self._homekit.entity_filter()
        self._config.set_filter(
            generate_filter(
                entity_filter["include_domains"],
                entity_filter["include_entities"],
                [],
                entity_filter["exclude_entities"],
            )
        )

    @callback
    def async_watch_new_entities(self) -> None:
        """Update the filter when a new device shows up, so Alexa sees it, or not, without a restart."""

        @callback
        def refresh_later(_now: Any) -> None:
            self._reload_timer = None
            self.refresh()

        @callback
        def on_registry_update(event: Any) -> None:
            if event.data.get("action") != "create" or self._config is None:
                return
            if event.data["entity_id"].split(".", 1)[0] not in DEFAULT_DOMAINS:
                return
            if self._reload_timer is not None:
                self._reload_timer()
            self._reload_timer = async_call_later(self._hass, NEW_ENTITY_DELAY, refresh_later)

        self._hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, on_registry_update)


async def async_setup_alexa(hass: HomeAssistant, homekit: AnnikaHomeKit) -> AnnikaAlexa:
    """Register the commands Annika's backend uses to turn Alexa on and to know whether it is."""

    alexa = AnnikaAlexa(hass, homekit)
    await alexa.async_load()
    alexa.async_watch_new_entities()
    homekit.async_add_change_listener(alexa.refresh)
    hass.data[DATA_ALEXA] = alexa

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_ALEXA_STATUS})
    @callback
    def handle_status(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], alexa.status())

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_ALEXA_ENABLE})
    @websocket_api.async_response
    async def handle_enable(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], await alexa.async_enable())

    websocket_api.async_register_command(hass, handle_status)
    websocket_api.async_register_command(hass, handle_enable)
    return alexa
