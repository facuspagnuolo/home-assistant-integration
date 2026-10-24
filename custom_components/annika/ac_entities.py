"""The AC sensor, its general switch and the services annika-ac-card edits through."""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .ac import DATA_AC, AcError, AnnikaAc
from .const import DOMAIN
from .heating import ALL_DAYS

SERVICE_SET_AC_MANUAL = "set_ac_manual"
SERVICE_SET_AC_AUTO = "set_ac_auto"
SERVICE_SET_AC_SCHEDULE = "set_ac_schedule"
SERVICE_SET_AC_SEASON = "set_ac_season"

STATUSES = ["off", "standby", "idle", "running"]


def _error(error: AcError) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=f"ac_{error.key}",
        translation_placeholders={key: str(value) for key, value in error.placeholders.items()},
    )


async def async_setup_platform(
    hass: HomeAssistant, platform_name: str, async_add_entities: AddEntitiesCallback
) -> None:
    ac: AnnikaAc = hass.data[DATA_AC]
    if platform_name == "switch":
        async_add_entities([AcEnabledSwitch(ac)])
        return

    await ac.async_start()
    async_add_entities([AnnikaAcSensor(ac)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_AC_MANUAL,
        {
            vol.Optional("zone"): cv.string,
            vol.Optional("units"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("mode"): cv.string,
            vol.Optional("target"): vol.Coerce(float),
            vol.Optional("fan"): cv.string,
            vol.Optional("swing"): cv.string,
            vol.Optional("swing_horizontal"): cv.string,
        },
        "async_set_ac_manual",
    )
    platform.async_register_entity_service(
        SERVICE_SET_AC_AUTO,
        {
            vol.Optional("zone"): cv.string,
            vol.Optional("units"): vol.All(cv.ensure_list, [cv.entity_id]),
        },
        "async_set_ac_auto",
    )
    platform.async_register_entity_service(
        SERVICE_SET_AC_SCHEDULE,
        {
            vol.Required("zone"): cv.string,
            vol.Required("day"): vol.In(ALL_DAYS),
            vol.Required("slots"): vol.All(cv.ensure_list, [dict]),
        },
        "async_set_ac_schedule",
    )
    platform.async_register_entity_service(
        SERVICE_SET_AC_SEASON,
        {
            vol.Optional("enabled"): cv.boolean,
            vol.Optional("on_above"): vol.Coerce(float),
            vol.Optional("off_below"): vol.Coerce(float),
            vol.Optional("hours"): vol.Coerce(int),
        },
        "async_set_ac_season",
    )


class AnnikaAcSensor(SensorEntity):
    """State is what the AC is doing; attributes are everything the card shows."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:air-conditioner"
    _attr_translation_key = "ac_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _unrecorded_attributes = frozenset({"config", "state", "events"})

    def __init__(self, ac: AnnikaAc) -> None:
        self._ac = ac
        self._attr_name = ac.name
        self._attr_unique_id = f"{DOMAIN}_ac"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._ac.subscribe(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        return self._ac.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return copy.deepcopy(self._ac.attributes())

    async def async_set_ac_manual(self, **values) -> None:
        try:
            await self._ac.async_set_manual(
                zone=values.get("zone"),
                units=values.get("units"),
                mode=values.get("mode"),
                target=values.get("target"),
                fan=values.get("fan"),
                swing=values.get("swing"),
                swing_horizontal=values.get("swing_horizontal"),
            )
        except AcError as error:
            raise _error(error) from error

    async def async_set_ac_auto(self, **values) -> None:
        try:
            await self._ac.async_set_auto(zone=values.get("zone"), units=values.get("units"))
        except AcError as error:
            raise _error(error) from error

    async def async_set_ac_schedule(self, zone: str, day: str, slots: list) -> None:
        try:
            await self._ac.async_set_schedule(zone, day, slots)
        except AcError as error:
            raise _error(error) from error

    async def async_set_ac_season(self, **values) -> None:
        try:
            await self._ac.async_set_season(**values)
        except AcError as error:
            raise _error(error) from error


class AcEnabledSwitch(SwitchEntity, RestoreEntity):
    """Off: every AC is switched off and left alone. On: everything is in Auto."""

    _attr_should_poll = False
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, ac: AnnikaAc) -> None:
        self._ac = ac
        self._attr_unique_id = f"{DOMAIN}_ac_enabled"
        self._attr_name = f"{ac.name} Enabled"

    @property
    def is_on(self) -> bool:
        return self._ac.enabled

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._ac.subscribe(self.async_write_ha_state))
        self._ac.notify()

    async def async_turn_on(self, **kwargs) -> None:
        await self._ac.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._ac.async_set_enabled(False)
