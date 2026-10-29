"""Annika's side of Siri: what a household needs to add the HomeKit bridge to Apple Home.

Home Assistant's own `homekit` integration already speaks the protocol, does the
pairing and turns Siri's orders into service calls. What it does not offer is a
way for anyone but its own frontend to ask for the setup code. Annika's backend
asks for it here, so the customer can read it in the Annika app:

    Annika app --> backend --> annika/homekit_pairing (this file) --> HomeKit bridge

Nothing about Siri's orders goes through Annika: once the bridge is added to
Apple Home, Siri talks to Home Assistant directly on the local network.

The bridge is the `homekit` entry named `Annika`. Annika creates it itself, when
the owner turns Siri on from the app, so nobody has to know Home Assistant has a
HomeKit integration or edit a configuration file. By default the bridge exposes everything
in the house a person can control, except what Annika already manages (its own entities
and any entity its configuration names — the gate, the heating, the irrigation
zones). Those keep their own logic and are not handed to Siri raw.

Which devices reach Siri is decided in Annika's backend, which keeps one list per
house for every voice assistant. It does not send the whole list: it sends how
the choice differs from the default, as the devices to add (`expose`) and the
ones to take away (`hide`). So a device installed later follows the default
without anyone choosing it. The house stores the choice, so it still applies
after a restart without the backend being reachable.

Its pairing state lives on `entry.runtime_data.homekit.driver`, which Home
Assistant does not document as an API. This module is the only place that reads
it, and it answers `unavailable` rather than raising when that shape changes.
"""

from __future__ import annotations

import asyncio
import re
import socket
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.loader import Integration, async_get_integrations

from .const import DOMAIN

DATA_HOMEKIT = f"{DOMAIN}_homekit"

HOMEKIT_DOMAIN = "homekit"
HOMEKIT_BRIDGE_NAME = "Annika"

WS_TYPE_HOMEKIT_PAIRING = f"{DOMAIN}/homekit_pairing"
WS_TYPE_HOMEKIT_ENABLE = f"{DOMAIN}/homekit_enable"
WS_TYPE_HOMEKIT_UNPAIR = f"{DOMAIN}/homekit_unpair"
WS_TYPE_VOICE_ENTITIES = f"{DOMAIN}/voice_entities"
WS_TYPE_HOMEKIT_CONFIGURE = f"{DOMAIN}/homekit_configure"

STORAGE_KEY = f"{DOMAIN}.homekit"
STORAGE_VERSION = 2

# A new device usually arrives with its siblings; one reload covers them all.
NEW_ENTITY_DELAY = 10.0

HOMEKIT_FIRST_PORT = 21063

# Everything in a house that a person can switch, open, set or lock, and that
# HomeKit knows how to show. Sensors, buttons, scripts and scenes are left out.
DEFAULT_DOMAINS = (
    "light",
    "switch",
    "cover",
    "fan",
    "climate",
    "humidifier",
    "water_heater",
    "lock",
    "alarm_control_panel",
    "media_player",
    "valve",
    "vacuum",
    "lawn_mower",
)

# Annika's locks feature adds codes and a record on top of a lock, but opening
# the door by voice is the point of putting locks on the bridge, so the locks it
# names stay on it. Everything else Annika names has logic of its own (the gate's
# timers, the heating schedules) that a raw command would fight.
EXPOSED_EVEN_IF_MANAGED = ("lock",)

# Everything else HomeKit knows how to show. Nothing here reaches Siri unless
# someone chooses it: a sensor only shows up for the device classes HomeKit
# understands, and a camera needs streaming that Annika's own cameras feature
# already takes care of.
OPTIONAL_DOMAINS = (
    "automation",
    "binary_sensor",
    "button",
    "camera",
    "device_tracker",
    "input_boolean",
    "input_button",
    "input_select",
    "person",
    "remote",
    "scene",
    "script",
    "select",
    "sensor",
)
EXPOSABLE_DOMAINS = DEFAULT_DOMAINS + OPTIONAL_DOMAINS

_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

# How long turning Siri on waits for the new bridge to start answering.
BRIDGE_START_TIMEOUT = 15.0
BRIDGE_START_POLL = 0.5

STATE_DISABLED = "disabled"
STATE_UNAVAILABLE = "unavailable"
STATE_UNPAIRED = "unpaired"
STATE_PAIRED = "paired"


class HomeKitStore(Store):
    """What the backend chose, kept by the house."""

    async def _async_migrate_func(self, old_major_version: int, old_minor_version: int, old_data: dict) -> dict:
        if old_major_version < 2:
            # Version 1 only knew what to leave out.
            return {"expose": [], "hide": list(old_data.get("exclude", []))}
        return old_data


def entity_ids_in(value: Any) -> set[str]:
    """Every entity id written anywhere in a piece of configuration."""

    if isinstance(value, str):
        return {value} if _ENTITY_ID.match(value) else set()
    if isinstance(value, dict):
        found = entity_ids_in(list(value.keys()))
        for item in value.values():
            found |= entity_ids_in(item)
        return found
    if isinstance(value, (list, tuple, set)):
        found: set[str] = set()
        for item in value:
            found |= entity_ids_in(item)
        return found
    return set()


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("", port))
        except OSError:
            return False
    return True


class AnnikaHomeKit:
    """The `Annika` HomeKit bridge: turning it on, keeping it right, and its pairing state."""

    def __init__(self, hass: HomeAssistant, annika_config: dict) -> None:
        self._hass = hass
        self._annika_config = annika_config
        self._store: Store = HomeKitStore(hass, STORAGE_VERSION, STORAGE_KEY)
        self._expose: set[str] = set()
        self._hide: set[str] = set()
        self._reload_timer: Any = None

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._expose = set(stored.get("expose", []))
        self._hide = set(stored.get("hide", []))

    @callback
    def _entry(self) -> ConfigEntry | None:
        for entry in self._hass.config_entries.async_entries(HOMEKIT_DOMAIN):
            if entry.data.get("name") == HOMEKIT_BRIDGE_NAME:
                return entry
        return None

    @callback
    def _managed(self) -> set[str]:
        """What Annika runs itself, and so keeps away from Siri."""

        managed = {
            entry.entity_id
            for entry in er.async_get(self._hass).entities.values()
            if entry.platform == DOMAIN
        }
        managed |= {
            entity_id
            for entity_id in entity_ids_in(self._annika_config)
            if entity_id.split(".", 1)[0] not in EXPOSED_EVEN_IF_MANAGED
        }
        return managed

    @callback
    def _is_default(self, entity_id: str, managed: set[str]) -> bool:
        """Whether a device reaches Siri when nobody chose anything for it."""

        return entity_id.split(".", 1)[0] in DEFAULT_DOMAINS and entity_id not in managed

    @callback
    def _entity_filter(self) -> dict[str, list[str]]:
        """What the bridge exposes: the default, with what the backend added and took away.

        Home Assistant includes an entity listed in `include_entities` whatever
        else says, which is what lets a device outside the default be added.
        """

        expose = self._expose - self._hide
        left_out = (self._managed() | self._hide) - expose
        return {
            "include_domains": list(DEFAULT_DOMAINS),
            "include_entities": sorted(expose),
            "exclude_entities": sorted(
                entity_id for entity_id in left_out if entity_id.split(".", 1)[0] in DEFAULT_DOMAINS
            ),
        }

    async def async_voice_entities(self) -> list[dict[str, Any]]:
        """Every device a voice assistant could be given, and what it gets without anyone choosing.

        Each one says which integration it comes from, so the backend can offer
        the list by integration as well as by kind of device.
        """

        registry = er.async_get(self._hass)
        managed = self._managed()
        found = []
        for state in self._hass.states.async_all():
            entity_id = state.entity_id
            if entity_id.split(".", 1)[0] not in EXPOSABLE_DOMAINS:
                continue
            entry = registry.async_get(entity_id)
            # Configuration and diagnostic entities are never shown to a voice assistant.
            if entry is not None and entry.entity_category is not None:
                continue
            found.append((state, entry.platform if entry is not None else None))

        integrations = await async_get_integrations(self._hass, {platform for _, platform in found if platform})
        entities = []
        for state, platform in found:
            integration = integrations.get(platform) if platform else None
            entities.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.name or state.entity_id,
                    "default": self._is_default(state.entity_id, managed),
                    "managed": state.entity_id in managed,
                    "integration": platform,
                    "integration_name": integration.name if isinstance(integration, Integration) else platform,
                }
            )
        return sorted(entities, key=lambda entity: (entity["name"].casefold(), entity["entity_id"]))

    async def async_configure(self, expose: list[str], hide: list[str]) -> dict[str, list[str]]:
        """Store how the choice differs from the default and apply it to the bridge, if the house has one."""

        self._hide = set(hide)
        self._expose = set(expose) - self._hide
        await self._store.async_save({"expose": sorted(self._expose), "hide": sorted(self._hide)})
        await self.async_sync()
        return {"expose": sorted(self._expose), "hide": sorted(self._hide)}

    @callback
    def async_watch_new_entities(self) -> None:
        """Reload the bridge when a new device shows up, so Siri sees it without a restart."""

        @callback
        def reload_later(_now: Any) -> None:
            self._reload_timer = None
            self._hass.async_create_task(self.async_sync(force=True))

        @callback
        def on_registry_update(event: Any) -> None:
            if event.data.get("action") != "create" or self._entry() is None:
                return
            if event.data["entity_id"].split(".", 1)[0] not in DEFAULT_DOMAINS:
                return
            if self._reload_timer is not None:
                self._reload_timer()
            self._reload_timer = async_call_later(self._hass, NEW_ENTITY_DELAY, reload_later)

        self._hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, on_registry_update)

    async def _free_port(self) -> int:
        taken = {
            entry.data.get("port") for entry in self._hass.config_entries.async_entries(HOMEKIT_DOMAIN)
        }
        port = HOMEKIT_FIRST_PORT
        while port in taken or not await self._hass.async_add_executor_job(port_is_free, port):
            port += 1
        return port

    async def async_sync(self, force: bool = False) -> None:
        """Bring the filter of an existing bridge up to date with what Annika manages now.

        `force` reloads the bridge even when the filter is the same, which is how
        it picks up a device that did not exist when it started.

        Runs once Home Assistant has started: until then the entities of the
        other integrations are not in the registry, and neither are Annika's.
        A house that never turned Siri on has no bridge and nothing happens.
        """

        entry = self._entry()
        if entry is None:
            return

        entity_filter = self._entity_filter()
        # An entry Home Assistant has not set up yet still carries its filter in `data`.
        if not force and entry.options.get("filter", entry.data.get("filter")) == entity_filter:
            return

        # An imported entry is not reloaded by Home Assistant when its options change.
        self._hass.config_entries.async_update_entry(entry, options={**entry.options, "filter": entity_filter})
        await self._hass.config_entries.async_reload(entry.entry_id)

    async def async_enable(self) -> dict[str, str | None]:
        """Create the bridge, if the house has none, and answer once it can be paired."""

        if self._entry() is None:
            await self._hass.config_entries.flow.async_init(
                HOMEKIT_DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    "name": HOMEKIT_BRIDGE_NAME,
                    "port": await self._free_port(),
                    "filter": self._entity_filter(),
                },
            )

        deadline = self._hass.loop.time() + BRIDGE_START_TIMEOUT
        while self._bridge() is None and self._hass.loop.time() < deadline:
            await asyncio.sleep(BRIDGE_START_POLL)
        return self.pairing()

    @callback
    def _bridge(self) -> Any | None:
        """The running bridge, or None when it is not configured or has not started."""

        entry = self._entry()
        bridge = getattr(getattr(entry, "runtime_data", None), "homekit", None)
        return bridge if getattr(bridge, "driver", None) is not None else None

    @callback
    def pairing(self) -> dict[str, str | None]:
        """What the customer needs, and only when they need it.

        The code and the QR content only exist while the bridge waits to be
        added: once somebody has paired it they have no use, and nobody
        should be handed a setup code for a bridge that is already taken.
        """

        if self._entry() is None:
            return {"state": STATE_DISABLED, "pin": None, "uri": None}

        bridge = self._bridge()
        if bridge is None:
            return {"state": STATE_UNAVAILABLE, "pin": None, "uri": None}

        driver = bridge.driver
        if driver.state.paired:
            return {"state": STATE_PAIRED, "pin": None, "uri": None}

        return {
            "state": STATE_UNPAIRED,
            "pin": driver.state.pincode.decode(),
            "uri": driver.accessory.xhm_uri(),
        }

    @callback
    def unpair(self) -> dict[str, str | None] | None:
        """Forget every Apple Home that has the bridge, so it can be added again.

        Returns the new pairing, or None when there is no bridge to reset.
        """

        bridge = self._bridge()
        if bridge is None:
            return None
        bridge.async_unpair()
        return self.pairing()


async def async_setup_homekit(hass: HomeAssistant, annika_config: dict) -> AnnikaHomeKit:
    """Register the commands Annika's backend uses to turn Siri on, choose its devices, show its code and reset it."""

    homekit = AnnikaHomeKit(hass, annika_config)
    await homekit.async_load()
    homekit.async_watch_new_entities()
    hass.data[DATA_HOMEKIT] = homekit

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_HOMEKIT_PAIRING})
    @callback
    def handle_pairing(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], homekit.pairing())

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_HOMEKIT_ENABLE})
    @websocket_api.async_response
    async def handle_enable(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], await homekit.async_enable())

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_HOMEKIT_UNPAIR})
    @callback
    def handle_unpair(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        pairing = homekit.unpair()
        if pairing is None:
            connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "The Annika HomeKit bridge is not running")
            return
        connection.send_result(msg["id"], pairing)

    @websocket_api.require_admin
    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_VOICE_ENTITIES})
    @websocket_api.async_response
    async def handle_voice_entities(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], await homekit.async_voice_entities())

    @websocket_api.require_admin
    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_TYPE_HOMEKIT_CONFIGURE,
            vol.Required("expose"): [cv.entity_id],
            vol.Required("hide"): [cv.entity_id],
        }
    )
    @websocket_api.async_response
    async def handle_configure(hass: HomeAssistant, connection: ActiveConnection, msg: dict) -> None:
        connection.send_result(msg["id"], await homekit.async_configure(msg["expose"], msg["hide"]))

    websocket_api.async_register_command(hass, handle_pairing)
    websocket_api.async_register_command(hass, handle_voice_entities)
    websocket_api.async_register_command(hass, handle_configure)
    websocket_api.async_register_command(hass, handle_enable)
    websocket_api.async_register_command(hass, handle_unpair)
    return homekit
