"""The doorbells status sensor and the services annika-doorbell-card edits through."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .doorbells import DATA_DOORBELLS, TARGETS, AnnikaDoorbells

SERVICE_SET_DOORBELL_NOTIFICATION = "set_doorbell_notification"
SERVICE_SET_DOORBELL_PRESENCE = "set_doorbell_presence"
SERVICE_SET_DOORBELL_TALK = "set_doorbell_talk"
SERVICE_SET_DOORBELL_RECORDING = "set_doorbell_recording"
SERVICE_DELETE_DOORBELL_CLIP = "delete_doorbell_clip"
SERVICE_TEST_DOORBELL_NOTIFICATION = "test_doorbell_notification"


async def async_setup_platform(
        hass: HomeAssistant, platform_name: str, async_add_entities: AddEntitiesCallback
) -> None:
    doorbells: AnnikaDoorbells = hass.data[DATA_DOORBELLS]
    await doorbells.async_start()
    async_add_entities([AnnikaDoorbellsSensor(doorbells)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_DOORBELL_NOTIFICATION,
        {
            vol.Required("target"): vol.In(TARGETS),
            vol.Optional("home"): cv.boolean,
            vol.Optional("away"): cv.boolean,
        },
        "async_set_doorbell_notification",
    )
    platform.async_register_entity_service(
        SERVICE_SET_DOORBELL_PRESENCE,
        {vol.Required("people"): vol.All(cv.ensure_list, [cv.entity_id])},
        "async_set_doorbell_presence",
    )
    platform.async_register_entity_service(
        SERVICE_SET_DOORBELL_TALK,
        {
            vol.Optional("mute_speaker"): cv.boolean,
            vol.Optional("auto_off"): cv.boolean,
            vol.Optional("auto_off_seconds"): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
        },
        "async_set_doorbell_talk",
    )
    platform.async_register_entity_service(
        SERVICE_SET_DOORBELL_RECORDING,
        {
            vol.Optional("home"): cv.boolean,
            vol.Optional("away"): cv.boolean,
            vol.Optional("keep_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        },
        "async_set_doorbell_recording",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_DOORBELL_CLIP, {vol.Required("clip_id"): cv.string}, "async_delete_doorbell_clip"
    )
    platform.async_register_entity_service(
        SERVICE_TEST_DOORBELL_NOTIFICATION,
        {vol.Required("target"): vol.In(TARGETS)},
        "async_test_doorbell_notification",
    )


def _unknown(target: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_target",
        translation_placeholders={"target": target},
    )


class AnnikaDoorbellsSensor(SensorEntity):
    """State is when it last rang; attributes are everything the card shows."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:doorbell"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset({"config", "clips", "media_base", "image_base"})

    def __init__(self, doorbells: AnnikaDoorbells) -> None:
        self._doorbells = doorbells
        self._attr_name = doorbells.name
        self._attr_unique_id = f"{DOMAIN}_doorbells"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._doorbells.subscribe(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        return self._doorbells.last_ring

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # A copy: the settings are edited in place, and a state that shares them
        # with the live data looks unchanged to Home Assistant, which then fires
        # no event and keeps serving the old values.
        return copy.deepcopy(self._doorbells.attributes())

    async def async_set_doorbell_notification(self, target: str, home: bool | None = None, away: bool | None = None) -> None:
        try:
            self._doorbells.set_notification(target, home=home, away=away)
        except ValueError as error:
            raise _unknown(target) from error

    async def async_set_doorbell_presence(self, people: list[str]) -> None:
        try:
            self._doorbells.set_presence(people)
        except ValueError as error:
            raise _unknown(", ".join(people)) from error

    async def async_set_doorbell_talk(self, **values) -> None:
        self._doorbells.set_talk(**values)

    async def async_set_doorbell_recording(self, **values) -> None:
        self._doorbells.set_recording(**values)

    async def async_delete_doorbell_clip(self, clip_id: str) -> None:
        try:
            await self._doorbells.async_delete_clip(clip_id)
        except ValueError as error:
            raise _unknown(clip_id) from error

    async def async_test_doorbell_notification(self, target: str) -> None:
        try:
            await self._doorbells.async_test(target)
        except ValueError as error:
            raise _unknown(target) from error
