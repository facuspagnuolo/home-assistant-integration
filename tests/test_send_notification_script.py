"""The send_notification script the integration installs forwards what it is given to annika.send_event."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict

from custom_components.annika import SEND_EVENT_SCHEMA

SCRIPT = (
    Path(__file__).parent.parent
    / "custom_components/annika/resources/scripts/send_notification.yaml"
)


@pytest.fixture
async def sent(hass: HomeAssistant) -> list[dict]:
    calls: list[dict] = []

    async def send_event(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("annika", "send_event", send_event, schema=SEND_EVENT_SCHEMA)
    assert await async_setup_component(hass, "script", load_yaml_dict(str(SCRIPT)))
    await hass.async_block_till_done()
    return calls


async def run(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call("script", "send_notification", data, blocking=True)


async def test_brings_the_view_up_on_the_tablets_when_asked(hass, sent):
    await run(hass, message="Someone is at the door", title="Doorbell", view="doorbell", navigate=True)

    assert sent[0]["navigate"] is True
    assert sent[0]["view"] == "doorbell"


async def test_only_notifies_by_default(hass, sent):
    await run(hass, message="Alarma desactivada", view="alarm")

    assert sent[0]["navigate"] is False


async def test_devices_only_needs_navigate(hass, sent):
    await run(hass, message="Doorbell", view="doorbell", actor="devices", navigate=True)
    assert sent[0]["actor"] == "devices" and sent[0]["navigate"] is True

    with pytest.raises(Exception):
        await run(hass, message="Doorbell", view="doorbell", actor="devices")
