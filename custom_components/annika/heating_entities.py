"""The heating sensor, its general switch and the services annika-heating-card edits through."""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .heating import ALL_DAYS, DATA_HEATING, AnnikaHeating, HeatingError

SERVICE_SET_HEATING_MANUAL = "set_heating_manual"
SERVICE_SET_HEATING_AUTO = "set_heating_auto"
SERVICE_SET_HEATING_SCHEDULE = "set_heating_schedule"
SERVICE_SET_HEATING_SEASON = "set_heating_season"

STATUSES = ["off", "standby", "idle", "heating"]


def _error(error: HeatingError) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=f"heating_{error.key}",
        translation_placeholders={key: str(value) for key, value in error.placeholders.items()},
    )


async def async_setup_platform(
    hass: HomeAssistant, platform_name: str, async_add_entities: AddEntitiesCallback
) -> None:
    heating: AnnikaHeating = hass.data[DATA_HEATING]
    if platform_name == "switch":
        async_add_entities([HeatingEnabledSwitch(heating)])
        return

    await heating.async_start()
    async_add_entities([AnnikaHeatingSensor(heating)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_HEATING_MANUAL,
        {
            vol.Optional("zone"): cv.string,
            vol.Optional("thermostats"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("target"): vol.Coerce(float),
            vol.Optional("off", default=False): cv.boolean,
        },
        "async_set_heating_manual",
    )
    platform.async_register_entity_service(
        SERVICE_SET_HEATING_AUTO,
        {
            vol.Optional("zone"): cv.string,
            vol.Optional("thermostats"): vol.All(cv.ensure_list, [cv.entity_id]),
        },
        "async_set_heating_auto",
    )
    platform.async_register_entity_service(
        SERVICE_SET_HEATING_SCHEDULE,
        {
            vol.Required("zone"): cv.string,
            vol.Required("day"): vol.In(ALL_DAYS),
            vol.Required("slots"): vol.All(cv.ensure_list, [dict]),
        },
        "async_set_heating_schedule",
    )
    platform.async_register_entity_service(
        SERVICE_SET_HEATING_SEASON,
        {
            vol.Optional("enabled"): cv.boolean,
            vol.Optional("on_below"): vol.Coerce(float),
            vol.Optional("off_above"): vol.Coerce(float),
            vol.Optional("hours"): vol.All(vol.Coerce(int)),
        },
        "async_set_heating_season",
    )


class AnnikaHeatingSensor(SensorEntity):
    """State is what the heating is doing; attributes are everything the card shows."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:radiator"
    _attr_translation_key = "heating_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _unrecorded_attributes = frozenset({"config", "state", "events"})

    def __init__(self, heating: AnnikaHeating) -> None:
        self._heating = heating
        self._attr_name = heating.name
        self._attr_unique_id = f"{DOMAIN}_heating"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._heating.subscribe(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        return self._heating.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return copy.deepcopy(self._heating.attributes())

    async def async_set_heating_manual(self, **values) -> None:
        try:
            await self._heating.async_set_manual(
                zone=values.get("zone"),
                thermostats=values.get("thermostats"),
                target=values.get("target"),
                off=values.get("off", False),
            )
        except HeatingError as error:
            raise _error(error) from error

    async def async_set_heating_auto(self, **values) -> None:
        try:
            await self._heating.async_set_auto(zone=values.get("zone"), thermostats=values.get("thermostats"))
        except HeatingError as error:
            raise _error(error) from error

    async def async_set_heating_schedule(self, zone: str, day: str, slots: list) -> None:
        try:
            await self._heating.async_set_schedule(zone, day, slots)
        except HeatingError as error:
            raise _error(error) from error

    async def async_set_heating_season(self, **values) -> None:
        try:
            await self._heating.async_set_season(**values)
        except HeatingError as error:
            raise _error(error) from error


class HeatingEnabledSwitch(SwitchEntity, RestoreEntity):
    """Off: the heating is switched off and left alone. On: everything is in Auto."""

    _attr_should_poll = False
    _attr_icon = "mdi:radiator"

    def __init__(self, heating: AnnikaHeating) -> None:
        self._heating = heating
        self._attr_unique_id = f"{DOMAIN}_heating_enabled"
        self._attr_name = f"{heating.name} Enabled"

    @property
    def is_on(self) -> bool:
        return self._heating.enabled

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._heating.subscribe(self.async_write_ha_state))
        # The sensor's attributes name this entity: refresh them now that it exists.
        self._heating.notify()

    async def async_turn_on(self, **kwargs) -> None:
        await self._heating.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._heating.async_set_enabled(False)
