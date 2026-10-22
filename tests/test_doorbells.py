"""Tests for Annika's doorbells: who a ring is told to, depending on who is home."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_DOORBELLS
from custom_components.annika.doorbells import (
    DATA_DOORBELLS,
    DEBOUNCE_SECONDS,
    DOORBELLS_SCHEMA,
    AnnikaDoorbells,
)

VISITOR = "binary_sensor.front_visitor"
GOLF = "person.golf"
DELFI = "person.delfina"


def config(**overrides):
    values = {
        "notify_view": "alarm",
        "presence": [GOLF, DELFI],
        "doorbells": [{"name": "Front door", "entity": "camera.front", "visitor": VISITOR}],
    }
    values.update(overrides)
    return DOORBELLS_SCHEMA(values)


@pytest.fixture
def services(hass):
    return SimpleNamespace(snapshot=async_mock_service(hass, "camera", "snapshot"))


@pytest.fixture
def sent():
    with patch("custom_components.annika.doorbells.AnnikaEventClient") as client:
        client.return_value.async_send = AsyncMock()
        yield client.return_value.async_send


async def start(hass, **overrides) -> AnnikaDoorbells:
    doorbells = AnnikaDoorbells(hass, config(**overrides))
    hass.states.async_set(VISITOR, "off")
    hass.states.async_set(GOLF, "not_home")
    hass.states.async_set(DELFI, "not_home")
    await doorbells.async_start()
    return doorbells


async def ring(hass, doorbells=None):
    hass.states.async_set(VISITOR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(VISITOR, "off")
    await hass.async_block_till_done()
    if doorbells is not None:
        # Let the next ring through the debounce.
        for key in doorbells._last:
            doorbells._last[key] -= timedelta(seconds=DEBOUNCE_SECONDS + 1)


def test_schema_defaults():
    values = config()
    assert values["talk"] == {"mute_speaker": True, "auto_off": True, "auto_off_seconds": 60}
    assert values["notifications"] == {}


def test_schema_rejects_non_person_presence():
    with pytest.raises(vol.Invalid):
        config(presence=["light.kitchen"])


async def test_default_notifications(hass, services, sent):
    doorbells = await start(hass)
    assert doorbells.notifications == {
        "devices": {"home": True, "away": True},
        "users": {"home": False, "away": True},
    }


async def test_away_tells_devices_and_users(hass, services, sent):
    doorbells = await start(hass)
    await ring(hass)
    sent.assert_awaited_once()
    event = sent.await_args.args[0]
    assert event["view"] == "alarm"
    assert event["navigate"] is True
    assert "actor" not in event
    assert event["message"] == "Front door"
    assert len(services.snapshot) == 1
    assert doorbells.last_ring is not None


async def test_home_tells_only_devices(hass, services, sent):
    await start(hass)
    hass.states.async_set(DELFI, "home")
    await ring(hass)
    event = sent.await_args.args[0]
    assert event["navigate"] is True
    assert event["actor"] == "devices"
    assert "imageUrl" not in event
    assert services.snapshot == []


async def test_users_only_does_not_navigate(hass, services, sent):
    doorbells = await start(hass)
    doorbells.set_notification("devices", away=False)
    await ring(hass)
    event = sent.await_args.args[0]
    assert "navigate" not in event
    assert "actor" not in event


async def test_nobody_selected_sends_nothing(hass, services, sent):
    doorbells = await start(hass)
    doorbells.set_notification("devices", away=False)
    doorbells.set_notification("users", away=False)
    await ring(hass)
    sent.assert_not_awaited()


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
async def test_unknown_presence_counts_as_away(hass, services, sent, state):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, state)
    hass.states.async_set(DELFI, state)
    assert doorbells.anyone_home() is False
    await ring(hass)
    assert "actor" not in sent.await_args.args[0]


async def test_missing_person_counts_as_away(hass, services, sent):
    doorbells = await start(hass, presence=["person.ghost"])
    assert doorbells.people() == [{"entity": "person.ghost", "name": "person.ghost", "home": False}]
    assert doorbells.anyone_home() is False


async def test_one_person_home_is_enough(hass, services, sent):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, "home")
    assert doorbells.anyone_home() is True


async def test_empty_group_is_always_away(hass, services, sent):
    doorbells = await start(hass, presence=[])
    assert doorbells.anyone_home() is False


async def test_debounce(hass, services, sent):
    await start(hass)
    await ring(hass)
    await ring(hass)
    assert sent.await_count == 1


async def test_rings_after_the_debounce_count(hass, services, sent):
    doorbells = await start(hass)
    await ring(hass, doorbells)
    await ring(hass)
    assert sent.await_count == 2


async def test_only_off_to_on_rings(hass, services, sent):
    await start(hass)
    hass.states.async_set(VISITOR, "unavailable")
    hass.states.async_set(VISITOR, "on")
    await hass.async_block_till_done()
    sent.assert_not_awaited()


async def test_no_notify_view_sends_nothing(hass, services, sent):
    values = config()
    values.pop("notify_view")
    doorbells = AnnikaDoorbells(hass, values)
    hass.states.async_set(VISITOR, "off")
    await doorbells.async_start()
    await ring(hass)
    sent.assert_not_awaited()


async def test_snapshot_failure_still_notifies(hass, sent):
    async def broken(call):
        raise RuntimeError("no picture")

    hass.services.async_register("camera", "snapshot", broken)
    await start(hass)
    await ring(hass)
    event = sent.await_args.args[0]
    assert "imageUrl" not in event
    sent.assert_awaited_once()


async def test_send_failure_does_not_raise(hass, services, sent):
    sent.side_effect = RuntimeError("down")
    await start(hass)
    await ring(hass)


async def test_test_notification(hass, services, sent):
    doorbells = await start(hass)
    await doorbells.async_test("devices")
    event = sent.await_args.args[0]
    assert event["actor"] == "devices"
    assert event["navigate"] is True
    assert "test" in event["title"].lower()
    with pytest.raises(ValueError):
        await doorbells.async_test("nobody")


async def test_settings_persist_and_notify_listeners(hass, services, sent):
    doorbells = await start(hass)
    calls = []
    unsubscribe = doorbells.subscribe(lambda: calls.append(1))
    doorbells.set_notification("users", home=True)
    doorbells.set_presence([GOLF, GOLF])
    doorbells.set_talk(auto_off_seconds=90, mute_speaker=False)
    assert doorbells.notifications["users"]["home"] is True
    assert doorbells.presence == [GOLF]
    assert doorbells.talk["auto_off_seconds"] == 90
    assert doorbells.talk["mute_speaker"] is False
    assert len(calls) == 3
    unsubscribe()
    doorbells.set_talk(auto_off=False)
    assert len(calls) == 3
    await doorbells.async_stop()

    again = await start(hass)
    assert again.notifications["users"]["home"] is True
    assert again.presence == [GOLF]
    assert again.talk["auto_off_seconds"] == 90


def test_set_validation():
    doorbells = AnnikaDoorbells.__new__(AnnikaDoorbells)
    with pytest.raises(ValueError):
        doorbells.set_notification("nobody", home=True)
    with pytest.raises(ValueError):
        doorbells.set_presence(["light.kitchen"])


async def test_presence_change_updates_the_card(hass, services, sent):
    doorbells = await start(hass)
    calls = []
    doorbells.subscribe(lambda: calls.append(1))
    hass.states.async_set(GOLF, "home")
    await hass.async_block_till_done()
    assert calls


async def test_attributes(hass, services, sent):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, "home", {"friendly_name": "Golf"})
    config_attr = doorbells.attributes()["config"]
    assert config_attr["notification"] is True
    assert config_attr["presence"]["home"] == 1
    assert config_attr["presence"]["people"][0] == {"entity": GOLF, "name": "Golf", "home": True}
    assert config_attr["doorbells"][0]["entity"] == "camera.front"
    assert config_attr["talk"]["auto_off_seconds"] == 60
    assert dt_util.utcnow()


async def test_the_sensor_reports_the_config_and_the_services_edit_it(hass, services, sent):
    assert await async_setup_component(hass, "sensor", {})
    doorbells = AnnikaDoorbells(hass, config())
    hass.data[DATA_DOORBELLS] = doorbells
    hass.config.components.add(DOMAIN)
    hass.states.async_set(VISITOR, "off")
    hass.states.async_set(GOLF, "not_home")
    hass.states.async_set(DELFI, "home")
    await async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_DOORBELLS}, {})
    await hass.async_block_till_done()

    entity = "sensor.annika_doorbells"
    state = hass.states.get(entity)
    assert state is not None
    assert state.attributes["config"]["presence"]["home"] == 1

    call = lambda service, **data: hass.services.async_call(  # noqa: E731
        DOMAIN, service, {"entity_id": entity, **data}, blocking=True
    )
    await call("set_doorbell_notification", target="users", home=True)
    await call("set_doorbell_presence", people=[GOLF])
    await call("set_doorbell_talk", auto_off_seconds=120)
    config_attr = hass.states.get(entity).attributes["config"]
    assert config_attr["notifications"]["users"]["home"] is True
    assert [person["entity"] for person in config_attr["presence"]["people"]] == [GOLF]
    assert config_attr["presence"]["home"] == 0
    assert config_attr["talk"]["auto_off_seconds"] == 120

    await call("test_doorbell_notification", target="devices")
    assert sent.await_args.args[0]["actor"] == "devices"

    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await call("set_doorbell_presence", people=["light.kitchen"])
    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await call("set_doorbell_talk", auto_off_seconds=5)
