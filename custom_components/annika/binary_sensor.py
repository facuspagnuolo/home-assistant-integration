"""Annika effective alarm sensors.

One per configured zone: the physical sensor ANDed with Annika's
participation flag. This is what the alarm groups should contain — see
alarm.py for the shape of the whole thing.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .alarm import (
    ATTR_SOURCE_ENTITY_ID,
    DATA_ALARM,
    AnnikaAlarmSensor,
    AnnikaAlarmSensors,
    effective_is_on,
    source_is_alive,
)
from .const import DOMAIN


def alarm_device_info() -> DeviceInfo:
    """Annika's own device.

    Deliberately not attached to the source integration's device: a device
    belongs to the integration that created it, and Annika only reads those
    sensors — it does not own the panel.

    Note that Home Assistant only registers a device for entities that belong
    to a config entry, and this integration is set up from YAML, so today this
    is ignored and the entities show up ungrouped. It is kept because it costs
    nothing and starts working the day Annika grows a config flow; grouping
    them in the meantime is what areas are for.
    """

    return DeviceInfo(
        identifiers={(DOMAIN, "alarm")},
        name="Annika Alarm",
        manufacturer="Annika",
        model="Alarm Logic",
    )


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the effective sensors from the YAML config."""

    if discovery_info is None:
        return

    sensors: AnnikaAlarmSensors = hass.data[DATA_ALARM]
    async_add_entities(
        AnnikaAlarmBinarySensor(sensor) for sensor in sensors.sensors
    )

    @callback
    def add_new(added: list[AnnikaAlarmSensor]) -> None:
        async_add_entities(AnnikaAlarmBinarySensor(sensor) for sensor in added)

    sensors.on_new_sensors(add_new)


class AnnikaAlarmBinarySensor(BinarySensorEntity):
    """Physical sensor AND enabled."""

    _attr_should_poll = False

    def __init__(self, sensor: AnnikaAlarmSensor) -> None:
        self._sensor = sensor
        # Named apart from the source on purpose. Copying the source's name
        # verbatim left two entities both called "Cocina" — one the physical
        # sensor, one this — indistinguishable in the entity picker, the
        # logbook and the history, and one collision away from HA handing out
        # a `_2` suffix. The suffix also gives the entity id its meaning:
        # binary_sensor.cocina_alarm.
        self._attr_name = f"{sensor.name} Alarm"
        self._attr_unique_id = f"{sensor.unique_key}_alarm"
        self._attr_device_class = sensor.device_class
        self._attr_device_info = alarm_device_info()

    def _source_state(self) -> str | None:
        state = self.hass.states.get(self._sensor.source_entity_id)
        return state.state if state else None

    @property
    def is_on(self) -> bool:
        return effective_is_on(self._source_state(), self._sensor.enabled)

    @property
    def extra_state_attributes(self) -> dict:
        # `source_entity_id` is also what the Annika alarm card matches on to
        # find the switch for a sensor, so the dashboard YAML does not have to
        # name it.
        return {
            ATTR_SOURCE_ENTITY_ID: self._sensor.source_entity_id,
            # The zone's own name, without the " Alarm" suffix this entity
            # carries. This is what a notification wants to say: "Cocina",
            # not "Cocina Alarm".
            "zone": self._sensor.name,
            "alarm_enabled": self._sensor.enabled,
            # A source that stopped reporting is a fault worth alerting on, so
            # it is surfaced as an attribute instead of making this entity
            # unavailable and silently dropping it out of its group.
            "source_available": source_is_alive(self._source_state()),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def source_changed(_event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._sensor.source_entity_id],
                source_changed,
            )
        )
        # Flipping the switch has to land here in the same tick, so a zone
        # that is currently detecting leaves its group the moment it is
        # disabled instead of waiting for the next physical change.
        self.async_on_remove(self._sensor.subscribe(self.async_write_ha_state))
