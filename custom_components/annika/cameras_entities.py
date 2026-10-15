"""The cameras status sensor and the services annika-cameras-card edits through."""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .cameras import ACTIONS, DATA_CAMERAS, DETECTIONS, MODES, AnnikaCameras
from .const import DOMAIN

SERVICE_SET_CAMERA_RULE = "set_camera_rule"
SERVICE_SET_RECORDING = "set_recording"
SERVICE_SET_RECORDING_WHEN = "set_recording_when"
SERVICE_DELETE_CLIP = "delete_clip"


async def async_setup_platform(
        hass: HomeAssistant, platform_name: str, async_add_entities: AddEntitiesCallback
) -> None:
    cameras: AnnikaCameras = hass.data[DATA_CAMERAS]
    await cameras.async_start()
    async_add_entities([AnnikaCamerasSensor(cameras)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_CAMERA_RULE,
        {
            vol.Required("camera"): cv.string,
            vol.Required("type"): vol.In(DETECTIONS),
            # None gives the detection back to the camera's group.
            vol.Required("action"): vol.Any(None, vol.In(ACTIONS)),
        },
        "async_set_camera_rule",
    )
    platform.async_register_entity_service(
        "set_group_rule",
        {
            vol.Required("group"): cv.string,
            vol.Required("type"): vol.In(DETECTIONS),
            vol.Required("action"): vol.In(ACTIONS),
        },
        "async_set_group_rule",
    )
    platform.async_register_entity_service(
        SERVICE_SET_RECORDING,
        {
            vol.Optional("before"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
            vol.Optional("after"): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
            vol.Optional("cooldown"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
            vol.Optional("keep_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        },
        "async_set_recording",
    )
    platform.async_register_entity_service(
        SERVICE_SET_RECORDING_WHEN,
        {
            vol.Optional("always"): cv.boolean,
            vol.Optional("armed"): cv.boolean,
            vol.Optional("armed_modes"): vol.All(cv.ensure_list, [vol.In(MODES)]),
            vol.Optional("time"): cv.boolean,
            vol.Optional("from"): cv.time,
            vol.Optional("to"): cv.time,
        },
        "async_set_recording_when",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_CLIP, {vol.Required("clip_id"): cv.string}, "async_delete_clip"
    )


def _unknown(target: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_target",
        translation_placeholders={"target": target},
    )


class AnnikaCamerasSensor(SensorEntity):
    """State is how many clips there are; attributes are everything the card shows."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:cctv"
    _attr_native_unit_of_measurement = "clips"
    _unrecorded_attributes = frozenset({"config", "clips", "media_base", "image_base"})

    def __init__(self, cameras: AnnikaCameras) -> None:
        self._cameras = cameras
        self._attr_name = cameras.name
        self._attr_unique_id = f"{DOMAIN}_cameras"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._cameras.subscribe(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self._cameras.clips)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # A copy: the rules and clips are edited in place, and a state that shares
        # them with the live data looks unchanged to Home Assistant, which then
        # fires no event and keeps serving the old values.
        return copy.deepcopy(self._cameras.attributes())

    async def async_set_camera_rule(self, camera: str, type: str, action: str) -> None:  # noqa: A002
        try:
            self._cameras.set_rule(camera, type, action)
        except ValueError as error:
            raise _unknown(f"{camera}/{type}") from error

    async def async_set_group_rule(self, group: str, type: str, action: str) -> None:  # noqa: A002
        try:
            self._cameras.set_group_rule(group, type, action)
        except ValueError as error:
            raise _unknown(f"{group}/{type}") from error

    async def async_set_recording(self, **values) -> None:
        self._cameras.set_recording(**values)

    async def async_set_recording_when(self, **values) -> None:
        self._cameras.set_when(**values)

    async def async_delete_clip(self, clip_id: str) -> None:
        try:
            await self._cameras.async_delete_clip(clip_id)
        except ValueError as error:
            raise _unknown(clip_id) from error
