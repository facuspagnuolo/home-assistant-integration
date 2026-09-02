"""Annika last-action sensor.

`sensor.annika_last_action` — the most recent action an Annika app user
performed on this unit, so a template can name the person:

    {% set s = 'sensor.annika_last_action' %}
    {% set at = state_attr(s, 'at') | as_datetime %}
    {% set fresh = at is not none and (now() - at).total_seconds() < 10 %}
    {% set mine = states(s) == 'alarm_control_panel.alarma' %}
    {{ state_attr(s, 'actor_name') if fresh and mine else 'alguien' }}

Both guards matter, and for different reasons. The entity guard because the
last action may well be about something else — someone turned a light on after
disarming. The freshness guard because an action taken *outside* the app (a
physical keypad, an automation, another Home Assistant client) records nothing
at all, so without it a keypad disarm would read back whoever last used the
app, however long ago that was.

An automation that triggers on the action itself rather than on the resulting
state does not need this sensor: `annika_action` carries the actor in the
event, with no correlation in between. It only ever fires for actions taken
through the app, which is exactly why the two exist side by side — see
actor.py.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .actor import (
    ATTR_ACTOR_ID,
    ATTR_ACTOR_NAME,
    ATTR_ACTOR_VERIFIED,
    ATTR_AT,
    DATA_ACTOR,
    AnnikaLastAction,
)

# What a restored state may hand back. Home Assistant also stores the entity's
# own presentation attributes (`friendly_name`, `icon`) alongside these, and
# returning those from `extra_state_attributes` would fight the entity itself
# over them.
RESTORED_ATTRIBUTES = (
    ATTR_ACTOR_NAME,
    ATTR_ACTOR_ID,
    ATTR_ACTOR_VERIFIED,
    "domain",
    "service",
    "entity_id",
    "entity_ids",
    ATTR_AT,
)


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the last-action sensor."""

    if discovery_info is None:
        return

    last_action: AnnikaLastAction = hass.data[DATA_ACTOR]["last_action"]
    async_add_entities([AnnikaLastActionSensor(last_action)])


class AnnikaLastActionSensor(SensorEntity, RestoreEntity):
    """Who last did something from the Annika app, and to what."""

    _attr_should_poll = False
    _attr_name = "Annika Last Action"
    _attr_unique_id = "annika_last_action"
    _attr_icon = "mdi:account-clock"

    def __init__(self, last_action: AnnikaLastAction) -> None:
        self._last_action = last_action
        # Restored on startup so templates read a real value instead of
        # `unknown` from the first boot onwards. The timestamp comes back with
        # it, so the freshness guard correctly rejects a record from before
        # the restart rather than presenting it as something that just
        # happened.
        self._restored_state: str | None = None
        self._restored_attributes: dict | None = None

    @property
    def native_value(self) -> str | None:
        action = self._last_action.action
        return action.state if action else self._restored_state

    @property
    def extra_state_attributes(self) -> dict:
        action = self._last_action.action
        if action:
            return action.attributes
        return self._restored_attributes or {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            self._restored_state = last_state.state
            self._restored_attributes = {
                key: last_state.attributes[key]
                for key in RESTORED_ATTRIBUTES
                if key in last_state.attributes
            }

        self.async_on_remove(self._last_action.subscribe(self.async_write_ha_state))
