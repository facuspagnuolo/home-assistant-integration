"""The motion sensors a rule can wait on: shared by the heating schedule and the alarm.

Both ask "has nobody moved for a while?", so both offer the same list: the
binary sensors that say motion, and the ones of the alarm zones.
"""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .alarm_panel import DATA_ALARM_PANEL

MOTION_CLASSES = ("motion", "occupancy", "presence")
CONTACT_CLASSES = ("door", "garage_door", "window", "opening", "lock", "vibration", "tamper", "safety")


def _alarm_parts(hass: HomeAssistant) -> dict[str, tuple[str, bool]]:
    """The motion sensors of the alarm zones: entity -> (the name the alarm gives it, whether
    that name covers several entities)."""
    panel = hass.data.get(DATA_ALARM_PANEL)
    rules = getattr(panel, "rules", None)
    found: dict[str, tuple[str, bool]] = {}
    for zone in getattr(rules, "zones", []):
        for sensor in zone.sensors:
            for entity_id in sensor.entities:
                if not entity_id.startswith("binary_sensor."):
                    continue
                state = hass.states.get(entity_id)
                kind = (state.attributes.get("device_class") if state else None) or sensor.detail
                if kind in CONTACT_CLASSES:
                    continue
                found[entity_id] = (sensor.name, len(sensor.entities) > 1)
    return found


def _friendly(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return (state.attributes.get("friendly_name") if state else None) or entity_id


def alarm_sensors(hass: HomeAssistant) -> dict[str, str]:
    """The motion sensors of the alarm zones, by entity, under the name the alarm gives them."""
    return {
        entity_id: f"{name} · {_friendly(hass, entity_id)}" if shared else name
        for entity_id, (name, shared) in _alarm_parts(hass).items()
    }


def motion_sensors(hass: HomeAssistant) -> list[dict[str, str]]:
    """What a rule can wait on: the sensors that say motion, and the ones of the alarm.

    The alarm's sensors (Kitchen, Living...) usually come from a panel that gives them no
    device class, so the class alone would leave out the ones the house is known by.
    """
    found: dict[str, str] = {}
    for state in _motion_states(hass):
        found[state.entity_id] = state.attributes.get("friendly_name") or state.entity_id
    for entity_id, name in alarm_sensors(hass).items():
        found[entity_id] = name
    return sorted(
        ({"entity": entity, "name": name} for entity, name in found.items()),
        key=lambda item: item["name"].lower(),
    )


def _motion_states(hass: HomeAssistant):
    for state in hass.states.async_all("binary_sensor"):
        if state.attributes.get("device_class") not in MOTION_CLASSES:
            continue
        # Annika's own twin of an alarm sensor goes quiet when the zone is disabled, which
        # would read as "no motion" for ever. The sensor it follows is listed instead.
        if state.attributes.get("source_entity_id"):
            continue
        yield state


def _readable(entity_id: str) -> str:
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def _natural(text: str) -> list:
    """"Camara 2" before "Camara 10"."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text.lower())]


def sensor_choices(hass: HomeAssistant) -> list[dict[str, str]]:
    """The same sensors for a card to list, every one under the same naming.

    A sensor of the alarm comes under the name the alarm gives it ("Camara 1"). So do the
    other motion sensors of the same device (the camera's motion and animal next to its
    person and vehicle), since they are the same thing to whoever looks at the list. When a
    name covers several entities it comes as `group`, apart from the entity's own name: the
    card writes that as it is when the card is drawn (never the id), so it does not go
    stale if the entities were not loaded yet when this was built.
    """
    parts = _alarm_parts(hass)
    registry = er.async_get(hass)

    def device_of(entity_id: str) -> str | None:
        entry = registry.async_get(entity_id)
        return entry.device_id if entry else None

    # The name each device goes by: the first alarm sensor that is one of its entities.
    groups: dict[str, str] = {}
    for entity_id, (name, _shared) in parts.items():
        device = device_of(entity_id)
        if device:
            groups.setdefault(device, name)

    def own_name(entity_id: str) -> str:
        state = hass.states.get(entity_id)
        return (state.attributes.get("friendly_name") if state else None) or _readable(entity_id)

    found: dict[str, dict[str, str]] = {}
    for state in _motion_states(hass):
        item = {"entity": state.entity_id, "name": own_name(state.entity_id)}
        device = device_of(state.entity_id)
        if device in groups:
            item["group"] = groups[device]
        found[state.entity_id] = item
    for entity_id, (name, shared) in parts.items():
        if shared:
            found[entity_id] = {"entity": entity_id, "name": own_name(entity_id), "group": name}
        else:
            found[entity_id] = {"entity": entity_id, "name": name}
    return sorted(
        found.values(),
        key=lambda item: (_natural(item.get("group") or item["name"]), _natural(item["name"])),
    )
