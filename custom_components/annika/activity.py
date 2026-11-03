"""Readable logbook lines for actions taken from the Annika app.

actor.py knows who pressed what, but Home Assistant's logbook does not show
`annika_action` in the place people look for it. A Logbook card filtered to an
entity only queries the events of the integration that *owns* that entity (its
config entry), so an event described by Annika never reaches a card targeting
the Tuya siren or the gate script.

What every entity-filtered logbook does query is `logbook_entry`, the event
behind the `logbook.log` action, matched by the `entity_id` in its data. So
for each attributed action actor.py also fires one of those, carrying the line
we want people to read: "Sirena · activado por Facu".

The stock Logbook card cannot show these on a script: the frontend renders any
line about a `script.*` or `automation.*` entity as a bare "Ran" and drops the
message, whatever the line says. annika-activity-card reads the same lines
through the same logbook API and shows them as written.

This only covers actions from the moment it is installed. `annika_action`
events already in the database stay as they are; they were never logbook
entries and the logbook will not show them on an entity card.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

# homeassistant.components.logbook.EVENT_LOGBOOK_ENTRY. Spelled out rather
# than imported because importing the logbook package pulls in the recorder,
# and this module is loaded on every unit whether or not either is set up.
EVENT_LOGBOOK_ENTRY = "logbook_entry"

# What happened, as a participle that reads after the entity name: "Living ·
# encendido por Facu". Keyed by service; DOMAIN_VERBS overrides it where the
# same service means something else for a particular domain.
SERVICE_VERBS = {
    "turn_on": "encendido",
    "turn_off": "apagado",
    "toggle": "accionado",
    "open_cover": "abierto",
    "close_cover": "cerrado",
    "stop_cover": "detenido",
    "toggle_cover": "accionado",
    "set_cover_position": "movido",
    "open_cover_tilt": "abierto",
    "close_cover_tilt": "cerrado",
    "set_cover_tilt_position": "movido",
    "lock": "cerrado con llave",
    "unlock": "abierto con llave",
    "open": "abierto",
    "alarm_arm_away": "armado ausente",
    "alarm_arm_home": "armado presente",
    "alarm_arm_night": "armado noche",
    "alarm_arm_vacation": "armado vacaciones",
    "alarm_arm_custom_bypass": "armado",
    "alarm_disarm": "desarmado",
    "alarm_trigger": "disparado",
    "press": "presionado",
    "trigger": "ejecutado",
    "select_option": "cambiado",
    "set_value": "cambiado",
    "set_temperature": "temperatura cambiada",
    "set_hvac_mode": "modo cambiado",
    "set_fan_mode": "ventilación cambiada",
    "set_preset_mode": "modo cambiado",
    "volume_set": "volumen cambiado",
    "volume_mute": "silencio cambiado",
    "media_play": "reproducido",
    "media_pause": "pausado",
    "media_play_pause": "reproducido / pausado",
    "media_stop": "detenido",
    "media_next_track": "siguiente",
    "media_previous_track": "anterior",
    "select_source": "fuente cambiada",
    "start": "iniciado",
    "stop": "detenido",
}

DOMAIN_VERBS = {
    ("script", "turn_on"): "ejecutado",
    ("script", "toggle"): "ejecutado",
    ("automation", "turn_on"): "habilitado",
    ("automation", "turn_off"): "deshabilitado",
    ("switch", "turn_on"): "activado",
    ("switch", "turn_off"): "desactivado",
    ("siren", "turn_on"): "activado",
    ("siren", "turn_off"): "desactivado",
}


# `set_cover_position` is how the app's slider moves a gate or a blind. "Movido"
# says nothing: the call carries the target and the cover still reports where it
# is, so the line can say which way it went.
NO_CHANGE = ""  # a position call that asked for where the cover already is

POSITION_SERVICES = {
    "set_cover_position": ("position", "current_position"),
    "set_cover_tilt_position": ("tilt_position", "current_tilt_position"),
}


def _percent(value: Any) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def describe_position_move(
    hass: HomeAssistant,
    service: str,
    entity_id: str | None,
    service_data: dict[str, Any] | None,
) -> str | None:
    """"abierto", "cerrado", "abierto hasta el 60%"... or None when it cannot tell.

    Read before the call runs (the call_service event fires first), so the
    entity's position is where it was, not where it is going.
    """

    keys = POSITION_SERVICES.get(service)
    if keys is None or not entity_id or not service_data:
        return None
    target = _percent(service_data.get(keys[0]))
    if target is None:
        return None
    target = max(0, min(100, target))
    state = hass.states.get(entity_id)
    current = _percent(state.attributes.get(keys[1])) if state else None
    if current is not None and current == target:
        # Already there: nothing moved, so there is nothing to write down.
        return NO_CHANGE
    if target >= 100:
        return "abierto"
    if target <= 0:
        return "cerrado"
    if current is None:
        return f"movido al {target}%"
    return f"{'abierto' if target > current else 'cerrado'} hasta el {target}%"


def describe_action(domain: str, service: str) -> str:
    """What the call did, in words."""

    verb = DOMAIN_VERBS.get((domain, service)) or SERVICE_VERBS.get(service)
    return verb or f"acción {domain}.{service}"


def logbook_entry(
    hass: HomeAssistant,
    actor_name: str,
    domain: str,
    service: str,
    entity_id: str | None,
    service_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Data for the `logbook_entry` event describing one attributed action.

    None when the call changed nothing and so has no line to write.
    """

    if not entity_id and domain == "script" and service not in SERVICE_VERBS:
        # A script called directly (`script.porton_pulso`) rather than through
        # `script.turn_on`: the service *is* the script, so name it — that is
        # also what lets a card filtered to the script find this line.
        entity_id = f"script.{service}"
        action = "ejecutado"
    else:
        action = describe_position_move(hass, service, entity_id, service_data)
        if action == NO_CHANGE:
            return None
        action = action or describe_action(domain, service)

    data: dict[str, Any] = {
        "message": f"{action} por {actor_name}",
        "domain": DOMAIN,
    }
    if entity_id:
        state = hass.states.get(entity_id)
        data["name"] = state.name if state else entity_id
        data["entity_id"] = entity_id
    else:
        data["name"] = "Annika"
    return data
