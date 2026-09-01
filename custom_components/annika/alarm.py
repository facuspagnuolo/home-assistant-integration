"""Annika alarm layer.

Konnected (or any other integration) owns the physical truth: a PIR is on or
it is not. Annika adds one thing on top — whether that zone takes part in the
alarm right now — and exposes the combination as its own entity, so the groups
and automations downstream keep working the way they already do:

    binary_sensor.<zone>              physical, from the source integration
                +
    switch.<zone>_alarm_enabled       Annika, remembered across restarts
                ↓
    binary_sensor.<zone>_alarm        Annika, physical AND enabled
                ↓
    group planta baja / alta / exterior
                ↓
    alarm logic

Disabling a zone drops it out of the group immediately, even while its PIR is
still detecting, because the effective sensor recomputes on the switch flip
rather than waiting for the next physical change.

Configured entirely from YAML — Annika units are provisioned centrally, so
which devices are alarm sources is a deployment decision, not something the
person living in the house picks from a settings screen:

    annika:
      alarm_sensors:
        devices:
          - Alarm Panel Pro 1
          - Alarm Panel Pro 2
        entities:
          - binary_sensor.garage_door
          - entity: binary_sensor.service_door
            name: Puerta de service
        exclude:
          - binary_sensor.alarm_panel_pro_1_zone_16

Entities take the shared Annika shape — a bare id, or `{ entity, name }` when
the source entity's own name is not what the zone should be called. Listing a
zone that a device already brought in is also how to rename it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SOURCE_DOMAIN = "binary_sensor"
ATTR_SOURCE_ENTITY_ID = "source_entity_id"

# Set on hass.data so the platforms and the reload can reach the same objects.
DATA_ALARM = f"{DOMAIN}_alarm"


def slugify(value: str) -> str:
    """Loose key for matching a configured name against a registry name."""

    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def effective_is_on(source_state: str | None, enabled: bool | None) -> bool:
    """The zone's contribution to the alarm.

    `enabled` is None until the switch has restored its state after a restart.
    Until then the zone reports off: a few milliseconds of a zone not
    triggering is a far better failure than a zone the user had disabled
    reporting movement because its flag had not been read back yet.
    """

    if enabled is not True:
        return False
    return source_state == STATE_ON


def source_is_alive(source_state: str | None) -> bool:
    """Whether the physical sensor is reporting at all."""

    return source_state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE)


@dataclass
class AnnikaAlarmSensor:
    """One physical sensor plus Annika's participation flag.

    The switch and the effective binary sensor share this object rather than
    looking each other up by entity id, so a flip is visible to the sensor in
    the same tick.
    """

    source_entity_id: str
    unique_key: str
    name: str
    device_class: str | None = None
    # None means "not restored yet" — see effective_is_on.
    enabled: bool | None = None
    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for participation changes; returns the remover."""

        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def set_enabled(self, enabled: bool) -> None:
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self.notify()


class AnnikaAlarmSensors:
    """The set of zones Annika manages, resolved from the YAML config."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._config = config or {}
        self._sensors: dict[str, AnnikaAlarmSensor] = {}
        self._new_sensor_listeners: list[Callable[[list[AnnikaAlarmSensor]], None]] = []

    @property
    def sensors(self) -> list[AnnikaAlarmSensor]:
        return list(self._sensors.values())

    @callback
    def on_new_sensors(
        self, listener: Callable[[list[AnnikaAlarmSensor]], None]
    ) -> None:
        """Called when zones appear later — a panel added after startup."""

        self._new_sensor_listeners.append(listener)

    def _entity_overrides(self) -> dict[str, dict]:
        """The `entities` list, as { entity_id: { name? } }.

        Same shape every Annika card takes: a bare entity id, or an object
        with the keys that override what was resolved.
        """

        overrides: dict[str, dict] = {}
        for item in self._config.get("entities", []):
            if isinstance(item, str):
                overrides.setdefault(item, {})
            else:
                overrides[item["entity"]] = {
                    key: value for key, value in item.items() if key != "entity"
                }
        return overrides

    def _configured_device_keys(self) -> set[str]:
        return {slugify(name) for name in self._config.get("devices", [])}

    def _matches_device(self, device: dr.DeviceEntry, keys: set[str]) -> bool:
        if device.id in self._config.get("devices", []):
            return True
        names = {device.name_by_user, device.name}
        return any(name and slugify(name) in keys for name in names)

    def _resolve(self) -> list[AnnikaAlarmSensor]:
        """Find every source entity the config points at.

        Runs against the registries rather than entity-id patterns, so a
        renamed zone keeps working and nothing depends on the source
        integration's naming.
        """

        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        excluded = set(self._config.get("exclude", []))
        wanted: dict[str, er.RegistryEntry | None] = {}

        # Whole devices: every binary_sensor that belongs to them.
        keys = self._configured_device_keys()
        if keys or self._config.get("devices"):
            matched_devices = {
                device.id
                for device in device_registry.devices.values()
                if self._matches_device(device, keys)
            }
            missing = keys - {
                slugify(name)
                for device in device_registry.devices.values()
                if device.id in matched_devices
                for name in (device.name_by_user, device.name)
                if name
            }
            if missing:
                _LOGGER.warning(
                    "Annika alarm: no device matched %s — check the names in "
                    "Settings > Devices",
                    ", ".join(sorted(missing)),
                )
            for entry in entity_registry.entities.values():
                if entry.device_id not in matched_devices:
                    continue
                if entry.domain != SOURCE_DOMAIN:
                    continue
                if entry.disabled_by or entry.hidden_by or entry.entity_category:
                    continue
                wanted[entry.entity_id] = entry

        # Loose entities listed one by one. A device already brought some of
        # these in; listing them again only adds their overrides.
        overrides = self._entity_overrides()
        for entity_id in overrides:
            wanted.setdefault(entity_id, entity_registry.async_get(entity_id))

        added: list[AnnikaAlarmSensor] = []
        for entity_id, entry in wanted.items():
            if entity_id in excluded or entity_id in self._sensors:
                continue

            state = self.hass.states.get(entity_id)
            name = self._name_for(entity_id, entry, state, device_registry, overrides)
            # The effective sensor mirrors the source's device class: a panel
            # mixes PIRs with door and window contacts, and the groups and the
            # UI downstream care which is which.
            device_class = (
                (entry.device_class or entry.original_device_class if entry else None)
                or (state.attributes.get("device_class") if state else None)
            )
            # Registry id when there is one: survives the source being renamed.
            unique_key = entry.id if entry else entity_id

            sensor = AnnikaAlarmSensor(
                source_entity_id=entity_id,
                unique_key=unique_key,
                name=name,
                device_class=device_class,
            )
            self._sensors[entity_id] = sensor
            added.append(sensor)

        return added


    def _name_for(self, entity_id, entry, state, device_registry, overrides) -> str:
        """What to call this zone.

        A sensor that sets `has_entity_name` only names its own half — every
        one of them is called "Motion detection" — and the device carries what
        actually identifies it. Taking the entity's name verbatim there left
        two zones both called "Motion detection" and Home Assistant handing out
        a `_2` suffix. Panel zones are the opposite: they share one device, so
        their own name is the only thing that tells them apart.
        """

        override = overrides.get(entity_id, {}).get("name")
        if override:
            return override

        # A name the user typed in Home Assistant always wins.
        if entry and entry.name:
            return entry.name

        if entry and getattr(entry, "has_entity_name", False) and entry.device_id:
            device = device_registry.async_get(entry.device_id)
            if device and (device.name_by_user or device.name):
                return device.name_by_user or device.name

        if entry and entry.original_name:
            return entry.original_name
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return entity_id.split(".", 1)[1].replace("_", " ").title()

    @callback
    def async_refresh(self) -> list[AnnikaAlarmSensor]:
        """Resolve again and hand back only what is new."""

        added = self._resolve()
        if added:
            _LOGGER.debug(
                "Annika alarm: picked up %s new zone(s): %s",
                len(added),
                ", ".join(sensor.source_entity_id for sensor in added),
            )
            for listener in list(self._new_sensor_listeners):
                listener(added)
        return added
