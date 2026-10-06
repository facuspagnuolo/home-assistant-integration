"""Tests for the logbook lines of Annika app actions, against Home Assistant's real logbook."""

from datetime import timedelta

import pytest
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.annika.activity import describe_action
from custom_components.annika.actor import DATA_ACTOR, Actor, async_setup_actor
from custom_components.annika.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Overrides the conftest one so the recorder starts before `hass`, as the logbook needs."""
    yield


@pytest.fixture
async def stamps(hass: HomeAssistant):
    """The actor layer and the logbook running, with services the app would call."""

    async_setup_actor(hass)
    assert await async_setup_component(hass, "logbook", {})

    async def noop(call: ServiceCall) -> None:
        return None

    for domain, service in (("switch", "turn_on"), ("script", "turn_on"), ("script", "porton_pulso")):
        hass.services.async_register(domain, service, noop)

    hass.states.async_set("switch.siren", "off", {"friendly_name": "Sirena"})
    hass.states.async_set("script.porton_pulso", "off", {"friendly_name": "Portón pulso"})
    hass.states.async_set("light.living", "off", {"friendly_name": "Living"})
    await hass.async_block_till_done()
    return hass.data[DATA_ACTOR]["stamps"]


async def annika_lines(hass: HomeAssistant, hass_ws_client, entity_ids=None):
    """What the logbook returns for Annika, as a Logbook card targeting `entity_ids` would ask."""

    await async_wait_recording_done(hass)
    client = await hass_ws_client()
    message = {
        "id": 1,
        "type": "logbook/get_events",
        "start_time": (dt_util.utcnow() - timedelta(hours=1)).isoformat(),
    }
    if entity_ids is not None:
        message["entity_ids"] = entity_ids
    await client.send_json(message)
    response = await client.receive_json()
    assert response["success"], response
    return [entry for entry in response["result"] if entry.get("domain") == DOMAIN]


async def test_app_action_shows_who_on_the_entity_card(hass, stamps, hass_ws_client):
    stamps.stamp(Actor(name="Facu"), "switch", "turn_on", ["switch.siren"])
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.siren"}, blocking=True)

    lines = await annika_lines(hass, hass_ws_client, ["switch.siren"])
    assert len(lines) == 1
    assert lines[0]["name"] == "Sirena"
    assert lines[0]["message"] == "activado por Facu"
    assert lines[0]["entity_id"] == "switch.siren"


async def test_gate_script_through_turn_on(hass, stamps, hass_ws_client):
    """The gate button: `script.turn_on` targeting the script, as the app's shared user."""

    stamps.stamp(Actor(name="Delfi"), "script", "turn_on", ["script.porton_pulso"])
    await hass.services.async_call(
        "script",
        "turn_on",
        {"entity_id": "script.porton_pulso"},
        blocking=True,
        context=Context(user_id="shared-app-user"),
    )

    lines = await annika_lines(hass, hass_ws_client, ["script.porton_pulso"])
    assert [(line["name"], line["message"]) for line in lines] == [("Portón pulso", "ejecutado por Delfi")]


async def test_script_called_directly_lands_on_the_script_card(hass, stamps, hass_ws_client):
    stamps.stamp(Actor(name="Facu"), "script", "porton_pulso", [])
    await hass.services.async_call("script", "porton_pulso", {}, blocking=True)

    lines = await annika_lines(hass, hass_ws_client, ["script.porton_pulso"])
    assert [(line["name"], line["message"]) for line in lines] == [("Portón pulso", "ejecutado por Facu")]


async def test_entity_card_keeps_other_entities_out(hass, stamps, hass_ws_client):
    stamps.stamp(Actor(name="Facu"), "switch", "turn_on", ["switch.siren"])
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.siren"}, blocking=True)

    assert await annika_lines(hass, hass_ws_client, ["light.living"]) == []


async def test_unattributed_calls_add_no_line(hass, stamps, hass_ws_client):
    """A keypad, an automation or another HA client: nothing to say about who."""

    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.siren"}, blocking=True)

    assert await annika_lines(hass, hass_ws_client) == []


@pytest.mark.parametrize(
    ("domain", "service", "expected"),
    [
        ("light", "turn_on", "encendido"),
        ("light", "turn_off", "apagado"),
        ("switch", "turn_on", "activado"),
        ("switch", "turn_off", "desactivado"),
        ("script", "turn_on", "ejecutado"),
        ("cover", "open_cover", "abierto"),
        ("alarm_control_panel", "alarm_disarm", "desarmado"),
        ("vacuum", "return_to_base", "acción vacuum.return_to_base"),
    ],
)
def test_describe_action(domain, service, expected):
    assert describe_action(domain, service) == expected
