"""Tests for Annika's heating: the schedule, manual targets, the season, the boilers and the services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.discovery import async_load_platform
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_HEATING
from custom_components.annika.heating import DATA_HEATING, HEATING_SCHEMA, AnnikaHeating, HeatingError

KITCHEN = "climate.kitchen_thermostat"
LIVING = "climate.living_thermostat"
PATIO = "climate.patio_thermostat"
BOILER = "switch.heating"
WEATHER = "weather.home"
WORKDAY = "binary_sensor.today_working_day"
MOTION = "binary_sensor.ground_motion"

# A Monday (workday) and a Saturday.
MON = datetime(2026, 10, 19, tzinfo=timezone.utc)
SAT = datetime(2026, 10, 24, tzinfo=timezone.utc)

WORKDAY_SLOTS = [
    {"time": "04:30", "name": "Morning", "target": 20},
    {"time": "17:00", "name": "Afternoon", "target": 22},
    {"time": "22:00", "name": "Night", "target": 16, "motion": {"sensors": [MOTION], "minutes": 60}},
]


def config(**overrides):
    values = {
        "weather": WEATHER,
        "day_mode": WORKDAY,
        "boilers": [{"name": "Boiler", "entity": BOILER}],
        "zones": [
            {
                "name": "Ground Floor",
                "thermostats": [KITCHEN, {"entity": LIVING, "name": "Living"}],
                "schedule": {"workday": WORKDAY_SLOTS, "non_workday": [{"time": "08:00", "name": "Late", "target": 19}]},
            },
            {"name": "Patio", "thermostats": [PATIO]},
        ],
    }
    values.update(overrides)
    return HEATING_SCHEMA(values)


def climate(hass, entity, mode="off", target=None, action="idle"):
    attributes = {"hvac_action": action, "friendly_name": entity.split(".")[1].replace("_", " ").title()}
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
        on=async_mock_service(hass, "homeassistant", "turn_on"),
        off=async_mock_service(hass, "homeassistant", "turn_off"),
    )


async def start(hass, freezer, at, **overrides) -> AnnikaHeating:
    freezer.move_to(at)
    for entity in (KITCHEN, LIVING, PATIO):
        climate(hass, entity)
    hass.states.async_set(BOILER, "off")
    hass.states.async_set(WORKDAY, "on" if at.weekday() < 5 else "off")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    heating = AnnikaHeating(hass, config(**overrides))
    heating.season["active"] = True
    await heating.async_start()
    await hass.async_block_till_done()
    return heating


async def advance(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# --- configuration ---------------------------------------------------------------


def test_schema_defaults():
    parsed = config()
    assert parsed["season"] == {"enabled": True, "on_below": 14.0, "off_above": 18.0, "hours": 12}
    assert parsed["adopt_manual"] is True
    assert parsed["zones"][0]["schedule"]["workday"][2]["motion"] == {"sensors": [MOTION], "minutes": 60}


@pytest.mark.parametrize(
    "overrides",
    [
        {"zones": [{"name": "A", "thermostats": [KITCHEN]}, {"name": "A", "thermostats": [LIVING]}]},
        {"zones": [{"name": "A", "thermostats": [KITCHEN]}, {"name": "B", "thermostats": [KITCHEN]}]},
        {"zones": [{"name": "A", "boiler": "Nope", "thermostats": [KITCHEN]}]},
        {"season": {"on_below": 20, "off_above": 10}},
        {"zones": [{"name": "A", "thermostats": [KITCHEN], "schedule": {"workday": [{"time": "08:00", "target": 20, "thermostats": [LIVING]}]}}]},
        {"zones": [{"name": "A", "thermostats": [KITCHEN], "schedule": {"workday": [{"time": "08:00", "target": 90}]}}]},
        {"zones": [{"name": "A", "thermostats": ["light.kitchen"]}]},
    ],
)
def test_schema_rejects(overrides):
    with pytest.raises(vol.Invalid):
        config(**overrides)


def test_single_boiler_is_the_default(hass):
    heating = AnnikaHeating(hass, config())
    assert {zone.id: zone.boiler for zone in heating.zones} == {"ground_floor": "boiler", "patio": "boiler"}


# --- the schedule --------------------------------------------------------------------


async def test_slot_sets_the_target(hass, freezer, utc, calls):
    await start(hass, freezer, MON.replace(hour=18))
    assert {call.data["entity_id"] for call in calls.temperature} == {KITCHEN, LIVING}
    assert all(call.data["temperature"] == 22 and call.data["hvac_mode"] == "heat" for call in calls.temperature)
    # The patio has no schedule: it is off already, nothing to say.
    assert not calls.mode


async def test_thermostat_without_slot_is_turned_off(hass, freezer, utc, calls):
    heating = AnnikaHeating(hass, config())
    freezer.move_to(MON.replace(hour=18))
    for entity in (KITCHEN, LIVING, PATIO):
        climate(hass, entity, "heat", 21)
    hass.states.async_set(BOILER, "off")
    heating.season["active"] = True
    await heating.async_start()
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls.mode] == [PATIO]


async def test_yesterdays_last_slot_covers_the_early_morning(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=3))
    # Sunday's night slot does not exist: Sunday is a non-workday with only "Late" at 08:00.
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Late"
    assert heating.attributes()["state"]["ground_floor"]["target"] == 19


async def test_non_workday_uses_its_own_schedule(hass, freezer, utc, calls):
    heating = await start(hass, freezer, SAT.replace(hour=9))
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Late"
    assert {call.data["temperature"] for call in calls.temperature} == {19}


async def test_workday_sensor_decides_the_day(hass, freezer, utc, calls):
    heating = await start(hass, freezer, SAT.replace(hour=9))
    hass.states.async_set(WORKDAY, "on")
    await hass.async_block_till_done()
    await heating._async_evaluate()
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Morning"


async def test_motion_condition_falls_back_to_the_previous_slot(hass, freezer, utc, calls):
    hass.states.async_set(MOTION, "on")
    heating = await start(hass, freezer, MON.replace(hour=22, minute=5))
    state = heating.attributes()["state"]["ground_floor"]
    assert state["slot"]["name"] == "Afternoon" and state["target"] == 22
    hass.states.async_set(MOTION, "off")
    await hass.async_block_till_done()
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Afternoon"
    await advance(hass, freezer, 61)
    state = heating.attributes()["state"]["ground_floor"]
    assert state["slot"]["name"] == "Night" and state["slot"]["conditional"] and state["target"] == 16
    assert calls.temperature[-1].data["temperature"] == 16


async def test_motion_unavailable_is_not_met(hass, freezer, utc, calls):
    hass.states.async_set(MOTION, "unavailable")
    heating = await start(hass, freezer, MON.replace(hour=23))
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Afternoon"


async def test_slot_for_some_thermostats_only(hass, freezer, utc, calls):
    schedule = {"workday": [{"time": "06:00", "name": "Kitchen", "target": 21, "thermostats": [KITCHEN]}]}
    heating = await start(
        hass, freezer, MON.replace(hour=7), zones=[{"name": "Ground Floor", "thermostats": [KITCHEN, LIVING], "schedule": schedule}]
    )
    values = heating.attributes()["state"]["ground_floor"]["thermostats"]
    assert values[KITCHEN]["value"] == 21 and values[LIVING]["value"] == "off"


async def test_plan_and_next(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    state = heating.attributes()["state"]["ground_floor"]
    assert state["next"]["name"] == "Night" and state["next"]["conditional"] and state["next"]["minutes"] == 60
    assert [item["name"] for item in state["plan"]] == ["Night"]


# --- manual ----------------------------------------------------------------------------


async def test_manual_holds_until_auto(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    calls.temperature.clear()
    await heating.async_set_manual(thermostats=[KITCHEN], target=24)
    assert calls.temperature[-1].data == {"entity_id": KITCHEN, "temperature": 24.0, "hvac_mode": "heat"}
    climate(hass, KITCHEN, "heat", 24)
    # The next slot starts, the manual one stays.
    await advance(hass, freezer, 5 * 60)
    assert heating.attributes()["state"]["ground_floor"]["thermostats"][KITCHEN]["source"] == "manual"
    assert heating.attributes()["state"]["ground_floor"]["manual"] == [KITCHEN]
    await heating.async_set_auto(thermostats=[KITCHEN])
    assert heating.manual == {}
    assert heating.attributes()["state"]["ground_floor"]["thermostats"][KITCHEN]["source"] != "manual"


async def test_manual_off_and_zone(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    for entity in (KITCHEN, LIVING):
        climate(hass, entity, "heat", 22)
    await heating.async_set_manual(zone="ground_floor", off=True)
    assert {call.data["entity_id"] for call in calls.mode} == {KITCHEN, LIVING}
    assert heating.attributes()["state"]["ground_floor"]["target"] is None


async def test_manual_without_a_schedule_heats_to_the_target(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_manual(thermostats=[PATIO], target=21)
    assert calls.temperature[-1].data["entity_id"] == PATIO


async def test_manual_errors(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    with pytest.raises(HeatingError) as error:
        await heating.async_set_manual(zone="nope", target=20)
    assert error.value.key == "unknown_zone"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_manual(zone="patio")
    assert error.value.key == "target_required"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_manual(thermostats=["climate.nope"], target=20)
    assert error.value.key == "unknown_thermostat"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_manual(target=20)
    assert error.value.key == "unknown_target"


async def test_external_change_is_adopted_as_manual(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    climate(hass, KITCHEN, "heat", 22)
    await hass.async_block_till_done()
    await advance(hass, freezer, 2)  # past the grace after our own command
    climate(hass, KITCHEN, "heat", 25)
    await hass.async_block_till_done()
    assert heating.manual == {KITCHEN: 25.0}
    assert heating.events[0]["kind"] == "manual" and heating.events[0]["external"] is True


async def test_external_change_is_ignored_when_it_matches_or_is_ours(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    climate(hass, KITCHEN, "heat", 22)  # the thermostat answering our command
    await hass.async_block_till_done()
    assert heating.manual == {}
    await advance(hass, freezer, 2)
    climate(hass, KITCHEN, "heat", 22.1)
    await hass.async_block_till_done()
    assert heating.manual == {}


async def test_adoption_can_be_disabled(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18), adopt_manual=False)
    await advance(hass, freezer, 2)
    climate(hass, KITCHEN, "heat", 25)
    await hass.async_block_till_done()
    assert heating.manual == {}


async def test_thermostat_that_drifts_is_told_again_after_a_while(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18), adopt_manual=False)
    calls.temperature.clear()
    await advance(hass, freezer, 2)
    assert not calls.temperature  # rate limited
    await advance(hass, freezer, 5)
    assert {call.data["entity_id"] for call in calls.temperature} == {KITCHEN, LIVING}


# --- the general switch --------------------------------------------------------------------


async def test_master_off_switches_everything_off_once_and_leaves_it(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    for entity in (KITCHEN, LIVING):
        climate(hass, entity, "heat", 22, "heating")
    hass.states.async_set(BOILER, "on")
    calls.mode.clear()
    await heating.async_set_enabled(False)
    assert {call.data["entity_id"] for call in calls.mode} == {KITCHEN, LIVING}
    assert [call.data["entity_id"] for call in calls.off] == [BOILER]
    assert heating.status == "off"
    calls.mode.clear()
    calls.temperature.clear()
    climate(hass, KITCHEN, "heat", 25)
    await advance(hass, freezer, 10)
    assert not calls.mode and not calls.temperature and heating.manual == {}


async def test_master_on_clears_manual_and_evaluates(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_manual(thermostats=[KITCHEN], target=26)
    await heating.async_set_enabled(False)
    calls.temperature.clear()
    await heating.async_set_enabled(True)
    assert heating.manual == {}
    assert {call.data["temperature"] for call in calls.temperature} == {22}


async def test_a_manual_target_works_with_the_master_off_and_the_boiler_follows(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_enabled(False)
    calls.temperature.clear()
    calls.on.clear()
    await heating.async_set_manual(thermostats=[KITCHEN], target=24)
    assert [(call.data["entity_id"], call.data["temperature"]) for call in calls.temperature] == [(KITCHEN, 24)]
    climate(hass, KITCHEN, "heat", 24, "heating")
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls.on] == [BOILER]
    # Back to Auto with nothing running the schedule: it is off again, and so is the boiler.
    hass.states.async_set(BOILER, "on")
    calls.mode.clear()
    calls.off.clear()
    await heating.async_set_auto(thermostats=[KITCHEN])
    assert [call.data["entity_id"] for call in calls.mode] == [KITCHEN]
    climate(hass, KITCHEN, "off", None, "idle")
    await hass.async_block_till_done()
    assert {call.data["entity_id"] for call in calls.off} == {BOILER}


async def test_a_manual_target_works_out_of_season(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    heating.season["active"] = False
    calls.temperature.clear()
    await heating.async_set_manual(thermostats=[KITCHEN], target=23)
    assert [(call.data["entity_id"], call.data["temperature"]) for call in calls.temperature] == [(KITCHEN, 23)]
    climate(hass, KITCHEN, "heat", 23, "heating")
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls.on] == [BOILER]
    assert heating.attributes()["state"]["ground_floor"]["thermostats"][KITCHEN]["source"] == "manual"


# --- the boilers --------------------------------------------------------------------------


async def test_boiler_follows_demand(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    climate(hass, KITCHEN, "heat", 22, "heating")
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls.on] == [BOILER]
    hass.states.async_set(BOILER, "on")
    assert heating.status == "heating"
    climate(hass, KITCHEN, "heat", 22, "idle")
    await hass.async_block_till_done()
    assert {call.data["entity_id"] for call in calls.off} == {BOILER}
    assert any(event["kind"] == "boiler" for event in heating.events)


async def test_boiler_stays_on_while_another_zone_asks(hass, freezer, utc, calls):
    await start(hass, freezer, MON.replace(hour=18))
    hass.states.async_set(BOILER, "on")
    climate(hass, KITCHEN, "heat", 22, "idle")
    climate(hass, PATIO, "heat", 22, "heating")
    await hass.async_block_till_done()
    assert not calls.off


async def test_each_boiler_serves_its_zones(hass, freezer, utc, calls):
    zones = [
        {"name": "Up", "boiler": "B2", "thermostats": [KITCHEN]},
        {"name": "Down", "boiler": "B1", "thermostats": [LIVING]},
    ]
    boilers = [{"name": "B1", "entity": BOILER}, {"name": "B2", "entity": "switch.heating_2"}]
    hass.states.async_set("switch.heating_2", "off")
    await start(hass, freezer, MON.replace(hour=18), zones=zones, boilers=boilers)
    climate(hass, KITCHEN, "heat", 22, "heating")
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls.on] == ["switch.heating_2"]


# --- the season --------------------------------------------------------------------------


async def test_season_ends_after_the_hours_above(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    hass.states.async_set(WEATHER, "sunny", {"temperature": 20})
    await heating._async_evaluate()
    assert heating.season["active"] is True and heating.season["warm_since"]
    climate(hass, KITCHEN, "heat", 22)
    await advance(hass, freezer, 12 * 60)
    assert heating.season["active"] is False
    assert heating.status == "standby"
    assert any(call.data["entity_id"] == KITCHEN for call in calls.mode)
    assert heating.attributes()["state"]["ground_floor"]["thermostats"][KITCHEN]["source"] == "season"
    hass.states.async_set(WEATHER, "rain", {"temperature": 10})
    await advance(hass, freezer, 1)
    await advance(hass, freezer, 12 * 60)
    assert heating.season["active"] is True


async def test_season_timers_reset_in_between(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    hass.states.async_set(WEATHER, "sunny", {"temperature": 20})
    await heating._async_evaluate()
    hass.states.async_set(WEATHER, "sunny", {"temperature": 16})
    await heating._async_evaluate()
    assert heating.season["warm_since"] is None and heating.season["cold_since"] is None


async def test_manual_survives_the_end_of_the_season(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_manual(thermostats=[KITCHEN], target=21)
    heating.season["active"] = False
    state = heating.attributes()["state"]["ground_floor"]["thermostats"]
    assert state[KITCHEN]["source"] == "manual" and state[LIVING]["source"] == "season"


async def test_first_run_decides_from_the_temperature(hass, freezer, utc, calls):
    freezer.move_to(MON.replace(hour=18))
    hass.states.async_set(WEATHER, "sunny", {"temperature": 25})
    heating = AnnikaHeating(hass, config())
    heating._update_season(MON.replace(hour=18))
    assert heating.season["active"] is False


async def test_no_weather_means_always_in_season(hass, freezer, utc, calls):
    heating = AnnikaHeating(hass, HEATING_SCHEMA({**config(), "weather": None} if False else {k: v for k, v in config().items() if k != "weather"}))
    heating._update_season(MON)
    assert heating.season["active"] is True


async def test_set_season(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_season(on_below=12, off_above=16, hours=6)
    assert (heating.season["on_below"], heating.season["off_above"], heating.season["hours"]) == (12, 16, 6)
    with pytest.raises(HeatingError) as error:
        await heating.async_set_season(on_below=20, off_above=10)
    assert error.value.key == "invalid_season"
    await heating.async_set_season(enabled=False)
    assert heating.season["active"] is True


# --- editing the schedule -------------------------------------------------------------------


async def test_set_schedule_sorts_validates_and_applies(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_schedule(
        "ground_floor",
        "workday",
        [
            {"time": "19:00", "name": "Evening", "target": 23, "thermostats": [KITCHEN]},
            {"time": "06:00", "name": "Early", "target": 18},
        ],
    )
    slots = heating.attributes()["config"]["zones"][0]["schedule"]["workday"]
    assert [slot["name"] for slot in slots] == ["Early", "Evening"] and all(slot["id"] for slot in slots)
    values = heating.attributes()["state"]["ground_floor"]["thermostats"]
    assert values[KITCHEN]["value"] == 18


async def test_set_schedule_errors(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    with pytest.raises(HeatingError) as error:
        await heating.async_set_schedule("nope", "workday", [])
    assert error.value.key == "unknown_zone"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_schedule("ground_floor", "workday", [{"time": "25:00", "target": 20}])
    assert error.value.key == "invalid_slot"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_schedule("ground_floor", "workday", [{"time": "08:00", "target": 20, "thermostats": [PATIO]}])
    assert error.value.key == "unknown_thermostat"
    with pytest.raises(HeatingError) as error:
        await heating.async_set_schedule("ground_floor", "monday", [])
    assert error.value.key == "invalid_slot"


async def test_motion_sensors_are_tracked_when_the_schedule_changes(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=23))
    await heating.async_set_schedule("ground_floor", "workday", [])
    assert heating._sensors == frozenset()
    await heating.async_set_schedule(
        "ground_floor", "workday", [{"time": "08:00", "target": 20, "motion": {"sensors": ["binary_sensor.other"], "minutes": 5}}]
    )
    assert heating._sensors == frozenset({"binary_sensor.other"})


async def test_the_slot_can_wait_on_motion_sensors_and_the_ones_of_the_alarm(hass, freezer, utc, calls):
    hass.states.async_set("binary_sensor.hall_pir", "off", {"device_class": "motion", "friendly_name": "Hall PIR"})
    hass.states.async_set("binary_sensor.front_door", "off", {"device_class": "door", "friendly_name": "Front door"})
    # What the alarm calls Kitchen has no device class; Annika's twin of it follows the zone's switch.
    hass.states.async_set("binary_sensor.kitchen_motion_sensor", "off", {"friendly_name": "Kitchen Motion Sensor"})
    hass.states.async_set("binary_sensor.kitchen_alarm", "off", {"device_class": "motion", "source_entity_id": "binary_sensor.kitchen_motion_sensor"})
    zones = [
        SimpleNamespace(sensors=[
            SimpleNamespace(name="Kitchen", detail="motion", entities=["binary_sensor.kitchen_motion_sensor"]),
            SimpleNamespace(name="Front", detail="door", entities=["binary_sensor.front_door"]),
            SimpleNamespace(name="Hall", detail="motion", entities=["binary_sensor.hall_pir"]),
        ])
    ]
    hass.data["annika_alarm_panel"] = SimpleNamespace(rules=SimpleNamespace(zones=zones))
    heating = await start(hass, freezer, MON.replace(hour=23))
    assert heating.attributes()["config"]["motion_sensors"] == [
        {"entity": "binary_sensor.hall_pir", "name": "Hall"},
        {"entity": "binary_sensor.kitchen_motion_sensor", "name": "Kitchen"},
    ]


# --- persistence ------------------------------------------------------------------------------


async def test_state_is_saved_and_restored(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    await heating.async_set_manual(thermostats=[KITCHEN], target=24)
    await heating.async_set_schedule("patio", "workday", [{"time": "07:00", "name": "Patio", "target": 18}])
    await heating.async_set_season(on_below=10, off_above=15, hours=4)
    await heating.async_set_enabled(False)
    await heating.async_stop()

    again = AnnikaHeating(hass, config())
    again._apply(await again._store.async_load())
    assert again.enabled is False
    assert again.manual == {KITCHEN: 24.0}
    assert again.season["on_below"] == 10 and again.season["hours"] == 4
    assert [slot["name"] for slot in again._zones["patio"].schedule["workday"]] == ["Patio"]
    assert any(event["kind"] == "master" for event in again.events)


async def test_events_are_capped(hass, freezer, utc, calls):
    heating = await start(hass, freezer, MON.replace(hour=18))
    for index in range(80):
        heating._log("auto", zone="patio", thermostat=None, n=index)
    assert len(heating.events) == 50


# --- the integration -----------------------------------------------------------------------------


async def test_integration_creates_the_entities_and_services(hass, freezer, utc, calls):
    freezer.move_to(MON.replace(hour=18))
    for entity in (KITCHEN, LIVING, PATIO):
        climate(hass, entity)
    hass.states.async_set(BOILER, "off")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    heating = AnnikaHeating(
        hass,
        HEATING_SCHEMA(
            {
                "weather": WEATHER,
                "boilers": [{"name": "Boiler", "entity": BOILER}],
                "zones": [{"name": "Ground Floor", "thermostats": [KITCHEN, LIVING]}],
            }
        ),
    )
    hass.data[DATA_HEATING] = heating
    hass.config.components.add(DOMAIN)
    for platform in ("sensor", "switch"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_HEATING}, {})
    await hass.async_block_till_done()

    sensor = hass.states.get("sensor.annika_heating")
    assert sensor is not None and sensor.state in ("idle", "heating", "standby")
    assert sensor.attributes["config"]["zones"][0]["id"] == "ground_floor"
    assert hass.states.get("switch.annika_heating_enabled").state == "on"
    assert sensor.attributes["config"]["entities"]["master"] == "switch.annika_heating_enabled"

    await hass.services.async_call(
        DOMAIN, "set_heating_manual", {"entity_id": "sensor.annika_heating", "zone": "ground_floor", "target": 21}, blocking=True
    )
    assert {call.data["entity_id"] for call in calls.temperature} >= {KITCHEN, LIVING}
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN, "set_heating_manual", {"entity_id": "sensor.annika_heating", "zone": "nope", "target": 21}, blocking=True
        )
    assert error.value.translation_key == "heating_unknown_zone"
    await hass.services.async_call(
        DOMAIN,
        "set_heating_schedule",
        {"entity_id": "sensor.annika_heating", "zone": "ground_floor", "day": "workday", "slots": [{"time": "07:00", "target": 20}]},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "set_heating_auto", {"entity_id": "sensor.annika_heating"}, blocking=True)
    await hass.services.async_call(DOMAIN, "set_heating_season", {"entity_id": "sensor.annika_heating", "hours": 6}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.annika_heating_enabled"}, blocking=True)
    assert hass.states.get("sensor.annika_heating").state == "off"


# --- telling the days apart -----------------------------------------------------------------


def test_day_mode_is_a_sensor_weekend_or_days():
    from custom_components.annika.heating import _mode_of

    assert _mode_of(config()) == "sensor"
    assert config()["day_mode"] == WORKDAY
    assert _mode_of({"zones": []}) == "weekend"
    assert _mode_of(config(day_mode="weekend")) == "weekend"
    assert _mode_of(config(day_mode="days", zones=[{"name": "A", "thermostats": [KITCHEN]}])) == "days"
    with pytest.raises(vol.Invalid):
        config(day_mode="every other day")


async def test_weekend_mode_ignores_the_sensor(hass, freezer, utc, calls):
    heating = await start(hass, freezer, SAT.replace(hour=9), day_mode="weekend")
    hass.states.async_set(WORKDAY, "on")  # a holiday the other way round: ignored
    assert heating._day_type(SAT.date()) == "non_workday"
    assert heating.attributes()["config"]["day_keys"] == ["workday", "non_workday"]


async def test_sensor_mode_without_a_sensor_uses_the_week(hass, freezer, utc, calls):
    raw = {k: v for k, v in config().items() if k != "day_mode"}
    heating = AnnikaHeating(hass, HEATING_SCHEMA({**raw}))
    assert heating.day_mode == "weekend"


async def test_days_mode_has_a_schedule_per_day(hass, freezer, utc, calls):
    zones = [
        {
            "name": "Ground Floor",
            "thermostats": [KITCHEN],
            "schedule": {
                "monday": [{"time": "06:00", "name": "Mon", "target": 21}],
                "saturday": [{"time": "09:00", "name": "Sat", "target": 19}],
            },
        }
    ]
    heating = await start(hass, freezer, MON.replace(hour=7), day_mode="days", zones=zones)
    assert heating.attributes()["config"]["day_keys"][0] == "monday"
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Mon"
    # Tuesday has nothing: it is off, even though Monday has a slot.
    await advance(hass, freezer, 24 * 60)
    assert heating.attributes()["state"]["ground_floor"]["slot"]["name"] == "Mon"  # Monday's slot still reaches into Tuesday's early hours
    assert heating._day_type(SAT.date()) == "saturday"
    await heating.async_set_schedule("ground_floor", "tuesday", [{"time": "05:00", "target": 20}])
    assert heating.attributes()["config"]["zones"][0]["schedule"]["tuesday"][0]["target"] == 20
    with pytest.raises(HeatingError) as error:
        await heating.async_set_schedule("ground_floor", "workday", [])
    assert error.value.key == "invalid_slot"


def test_schedule_for_a_day_the_mode_does_not_use_is_rejected():
    with pytest.raises(vol.Invalid):
        config(day_mode="days", zones=[{"name": "A", "thermostats": [KITCHEN], "schedule": {"workday": [{"time": "08:00", "target": 20}]}}])
    with pytest.raises(vol.Invalid):
        config(zones=[{"name": "A", "thermostats": [KITCHEN], "schedule": {"monday": [{"time": "08:00", "target": 20}]}}])
    with pytest.raises(vol.Invalid):
        config(day_mode="nope")
