"""Tests for Annika's AC: schedules, manual control, the season and the services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.discovery import async_load_platform
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.annika.ac import AC_SCHEMA, DATA_AC, AcError, AnnikaAc
from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_AC

MAIN = "climate.main_bedroom"
KIDS = "climate.kids_bedroom"
OFFICE = "climate.office"
WEATHER = "weather.home"
WORKDAY = "binary_sensor.today_working_day"

MON = datetime(2026, 10, 19, tzinfo=timezone.utc)
SAT = datetime(2026, 10, 24, tzinfo=timezone.utc)

SLOTS = [
    {"time": "07:00", "name": "Day", "mode": "off"},
    {"time": "21:30", "name": "Night", "mode": "cool", "target": 24, "fan": "low", "units": [MAIN]},
]


def config(**overrides):
    values = {
        "weather": WEATHER,
        "day_mode": WORKDAY,
        "zones": [
            {"name": "First Floor", "units": [MAIN, {"entity": KIDS, "name": "Kids"}], "schedule": {"workday": SLOTS}},
            {"name": "Ground Floor", "units": [OFFICE]},
        ],
    }
    values.update(overrides)
    return AC_SCHEMA(values)


def unit(hass, entity, mode="off", target=None, fan="auto", action="idle"):
    attributes = {
        "hvac_action": action,
        "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "fan_modes": ["auto", "low", "medium", "high"],
        "fan_mode": fan,
        "swing_modes": ["off", "vertical"],
        "friendly_name": entity.split(".")[1].replace("_", " ").title() + " AC",
    }
    if target is not None:
        attributes["temperature"] = target
    hass.states.async_set(entity, mode, attributes)


@pytest.fixture
async def utc(hass):
    await hass.config.async_set_time_zone("UTC")


@pytest.fixture
def calls(hass):
    return SimpleNamespace(
        temperature=async_mock_service(hass, "climate", "set_temperature"),
        mode=async_mock_service(hass, "climate", "set_hvac_mode"),
        fan=async_mock_service(hass, "climate", "set_fan_mode"),
        swing=async_mock_service(hass, "climate", "set_swing_mode"),
    )


async def start(hass, freezer, at, **overrides) -> AnnikaAc:
    freezer.move_to(at)
    for entity in (MAIN, KIDS, OFFICE):
        unit(hass, entity)
    hass.states.async_set(WORKDAY, "on" if at.weekday() < 5 else "off")
    hass.states.async_set(WEATHER, "sunny", {"temperature": 30})
    ac = AnnikaAc(hass, config(**overrides))
    ac.season["active"] = True
    await ac.async_start()
    await hass.async_block_till_done()
    return ac


async def advance(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def test_schema_defaults():
    parsed = config()
    assert parsed["season"] == {"enabled": True, "on_above": 26.0, "off_below": 22.0, "hours": 12}
    assert parsed["adopt_manual"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"zones": [{"name": "A", "units": [MAIN]}, {"name": "A", "units": [KIDS]}]},
        {"zones": [{"name": "A", "units": [MAIN]}, {"name": "B", "units": [MAIN]}]},
        {"zones": [{"name": "A", "units": [MAIN], "schedule": {"workday": [{"time": "07:00", "mode": "cool"}]}}]},
        {"zones": [{"name": "A", "units": [MAIN], "schedule": {"workday": [{"time": "07:00", "mode": "off", "units": [KIDS]}]}}]},
        {"season": {"on_above": 20, "off_below": 24}},
        {"zones": [{"name": "A", "units": ["light.x"]}]},
    ],
)
def test_schema_rejects(overrides):
    with pytest.raises(vol.Invalid):
        config(**overrides)


async def test_slot_sets_units(hass, utc, freezer, calls):
    await start(hass, freezer, MON.replace(hour=22))
    assert [(c.data["entity_id"]) for c in calls.temperature] == [MAIN]
    assert calls.temperature[0].data["temperature"] == 24
    assert calls.temperature[0].data["hvac_mode"] == "cool"
    assert calls.fan[0].data["fan_mode"] == "low"
    assert calls.mode == []  # KIDS is already off


async def test_slot_turns_off(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=8))
    unit(hass, MAIN, "cool", 24)
    await advance(hass, freezer, 6)
    assert calls.mode[0].data == {"entity_id": MAIN, "hvac_mode": "off"}
    assert ac.attributes()["state"]["first_floor"]["slot"]["name"] == "Day"


async def test_no_slot_means_off(hass, utc, freezer, calls):
    await start(hass, freezer, MON.replace(hour=8))
    unit(hass, OFFICE, "cool", 22)
    await advance(hass, freezer, 6)
    assert any(c.data["entity_id"] == OFFICE and c.data["hvac_mode"] == "off" for c in calls.mode)


async def test_manual_is_hands_off_until_auto(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    await ac.async_set_manual(zone="first_floor", mode="heat", target=21)
    assert {MAIN, KIDS} == ac.manual
    unit(hass, MAIN, "heat", 21)
    unit(hass, KIDS, "heat", 21)
    calls.mode.clear()
    calls.temperature.clear()
    await advance(hass, freezer, 10)
    assert calls.mode == [] and calls.temperature == []
    await ac.async_set_auto(zone="first_floor")
    assert not ac.manual
    assert any(c.data["entity_id"] == KIDS for c in calls.mode)


async def test_manual_unknown(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    with pytest.raises(AcError):
        await ac.async_set_manual(zone="nope", target=21)
    with pytest.raises(AcError):
        await ac.async_set_manual(units=["climate.x"], target=21)
    with pytest.raises(AcError):
        await ac.async_set_manual(target=21)


async def test_manual_fan_and_swing(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    await ac.async_set_manual(units=[KIDS], fan="high", swing="vertical")
    assert calls.fan[-1].data == {"entity_id": KIDS, "fan_mode": "high"}
    assert calls.swing[-1].data == {"entity_id": KIDS, "swing_mode": "vertical"}


async def test_external_change_is_adopted(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=8))
    await advance(hass, freezer, 5)
    unit(hass, KIDS, "cool", 23)
    await hass.async_block_till_done()
    assert KIDS in ac.manual
    assert ac.events[0]["kind"] == "manual"


async def test_adopt_can_be_disabled(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=8), adopt_manual=False)
    await advance(hass, freezer, 5)
    unit(hass, KIDS, "cool", 23)
    await hass.async_block_till_done()
    assert not ac.manual


async def test_master_off_and_on(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    unit(hass, MAIN, "cool", 24)
    await ac.async_set_manual(units=[KIDS], mode="cool", target=22)
    unit(hass, KIDS, "cool", 22)
    calls.mode.clear()
    await ac.async_set_enabled(False)
    assert {c.data["entity_id"] for c in calls.mode} == {MAIN, KIDS}
    calls.mode.clear()
    await advance(hass, freezer, 10)
    assert calls.mode == []
    await ac.async_set_enabled(True)
    assert not ac.manual


async def test_season_off_turns_units_off(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    unit(hass, MAIN, "cool", 24)
    await hass.async_block_till_done()
    hass.states.async_set(WEATHER, "rainy", {"temperature": 15})
    await advance(hass, freezer, 1)
    assert ac.season["active"] is True
    await advance(hass, freezer, 12 * 60 + 1)
    assert ac.season["active"] is False
    assert ac.status == "standby"
    assert any(c.data["entity_id"] == MAIN and c.data["hvac_mode"] == "off" for c in calls.mode)


async def test_season_starts(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    ac.season["active"] = False
    await advance(hass, freezer, 1)
    await advance(hass, freezer, 12 * 60 + 1)
    assert ac.season["active"] is True


async def test_day_types(hass, utc, freezer, calls):
    ac = await start(hass, freezer, SAT.replace(hour=22))
    assert ac.attributes()["config"]["day_type"] == "non_workday"
    assert ac.attributes()["state"]["first_floor"]["slot"]["since"].startswith("2026-10-23")  # yesterday's night carries over


async def test_set_schedule(hass, utc, freezer, calls):
    ac = await start(hass, freezer, SAT.replace(hour=12))
    await ac.async_set_schedule("first_floor", "non_workday", [{"time": "10:00", "name": "Chill", "mode": "cool", "target": 25}])
    assert ac.attributes()["state"]["first_floor"]["slot"]["name"] == "Chill"
    with pytest.raises(AcError):
        await ac.async_set_schedule("first_floor", "non_workday", [{"time": "10:00", "mode": "cool"}])
    with pytest.raises(AcError):
        await ac.async_set_schedule("first_floor", "monday", [])
    with pytest.raises(AcError):
        await ac.async_set_schedule("first_floor", "workday", [{"time": "10:00", "mode": "off", "units": [OFFICE]}])


async def test_set_season_validates(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    await ac.async_set_season(on_above=28, off_below=24, hours=6)
    assert ac.season["on_above"] == 28 and ac.season["hours"] == 6
    with pytest.raises(AcError):
        await ac.async_set_season(on_above=20)


async def test_persistence(hass, utc, freezer, calls):
    ac = await start(hass, freezer, MON.replace(hour=22))
    await ac.async_set_schedule("first_floor", "workday", [{"time": "09:00", "name": "Only", "mode": "off"}])
    await ac.async_set_manual(units=[KIDS], mode="cool", target=23)
    saved = ac._saved()
    again = AnnikaAc(hass, config())
    again._apply(saved)
    assert again.manual == {KIDS}
    assert [s["name"] for s in again._zones["first_floor"].schedule["workday"]] == ["Only"]


async def test_entities_and_services(hass, utc, freezer, calls):
    freezer.move_to(MON.replace(hour=22))
    for entity in (MAIN, KIDS, OFFICE):
        unit(hass, entity)
    ac = AnnikaAc(hass, AC_SCHEMA({"zones": [{"name": "First Floor", "units": [MAIN, KIDS]}]}))
    hass.data[DATA_AC] = ac
    hass.config.components.add(DOMAIN)
    for platform in ("sensor", "switch"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_AC}, {})
    await hass.async_block_till_done()

    sensor = hass.states.get("sensor.annika_ac")
    assert sensor is not None and sensor.state in ("idle", "running", "standby")
    assert hass.states.get("switch.annika_ac_enabled").state == "on"
    assert sensor.attributes["config"]["entities"]["master"] == "switch.annika_ac_enabled"

    await hass.services.async_call(
        DOMAIN, "set_ac_manual", {"entity_id": "sensor.annika_ac", "zone": "first_floor", "mode": "cool", "target": 23}, blocking=True
    )
    assert {c.data["entity_id"] for c in calls.temperature} == {MAIN, KIDS}
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN, "set_ac_manual", {"entity_id": "sensor.annika_ac", "zone": "nope", "target": 21}, blocking=True
        )
    assert error.value.translation_key == "ac_unknown_zone"
    await hass.services.async_call(DOMAIN, "set_ac_auto", {"entity_id": "sensor.annika_ac"}, blocking=True)
    await hass.services.async_call(DOMAIN, "set_ac_season", {"entity_id": "sensor.annika_ac", "hours": 6}, blocking=True)
    await hass.services.async_call(
        DOMAIN,
        "set_ac_schedule",
        {"entity_id": "sensor.annika_ac", "zone": "first_floor", "day": "workday", "slots": [{"time": "07:00", "mode": "off"}]},
        blocking=True,
    )
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.annika_ac_enabled"}, blocking=True)
    assert hass.states.get("sensor.annika_ac").state == "off"
