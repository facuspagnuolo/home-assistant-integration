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
    "alarm_arm_away": "armado (ausente)",
    "alarm_arm_home": "armado (en casa)",
    "alarm_arm_night": "armado (noche)",
    "alarm_arm_vacation": "armado (vacaciones)",
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
) -> dict[str, Any]:
    """Data for the `logbook_entry` event describing one attributed action."""

    if not entity_id and domain == "script" and service not in SERVICE_VERBS:
        # A script called directly (`script.porton_pulso`) rather than through
        # `script.turn_on`: the service *is* the script, so name it — that is
        # also what lets a card filtered to the script find this line.
        entity_id = f"script.{service}"
        action = "ejecutado"
    else:
        action = describe_action(domain, service)

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
