"""Annika alarm participation switches.

One per configured zone: whether that sensor takes part in the alarm. The
state is remembered across restarts, so a zone the user excluded stays
excluded.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .alarm import ATTR_SOURCE_ENTITY_ID, DATA_ALARM, AnnikaAlarmSensor, AnnikaAlarmSensors


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the participation switches from the YAML config."""

    if discovery_info is None:
        return

    sensors: AnnikaAlarmSensors = hass.data[DATA_ALARM]
    async_add_entities(AnnikaAlarmEnabledSwitch(sensor) for sensor in sensors.sensors)

    @callback
    def add_new(added: list[AnnikaAlarmSensor]) -> None:
        async_add_entities(AnnikaAlarmEnabledSwitch(sensor) for sensor in added)

    sensors.on_new_sensors(add_new)


class AnnikaAlarmEnabledSwitch(SwitchEntity, RestoreEntity):
    """Whether a zone takes part in the alarm."""

    _attr_should_poll = False
    _attr_entity_category = None

    def __init__(self, sensor: AnnikaAlarmSensor) -> None:
        self._sensor = sensor
        # Matches the effective sensor's name, so the pair reads together and
        # neither collides with the source entity. See binary_sensor.py.
        self._attr_name = f"{sensor.name} Alarm Enabled"
        self._attr_unique_id = f"{sensor.unique_key}_alarm_enabled"

    @property
    def is_on(self) -> bool:
        return self._sensor.enabled is True

    @property
    def extra_state_attributes(self) -> dict:
        # What the Annika alarm card matches on to pair this switch with its
        # sensor, so the dashboard YAML does not have to name it.
        return {ATTR_SOURCE_ENTITY_ID: self._sensor.source_entity_id}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Until this runs the shared flag is None and the effective sensor
        # reports off; see effective_is_on in alarm.py.
        last_state = await self.async_get_last_state()
        enabled = True if last_state is None else last_state.state == STATE_ON
        self._sensor.set_enabled(enabled)
        # set_enabled only notifies on a change, and the flag went from None
        # to a boolean either way, so make sure this entity writes its state.
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self._sensor.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._sensor.set_enabled(False)
        self.async_write_ha_state()
