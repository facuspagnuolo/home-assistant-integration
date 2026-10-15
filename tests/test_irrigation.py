"""Tests for the Annika irrigation schedule, against Home Assistant's real entity platforms."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON, SUN_EVENT_SUNRISE
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
    setup_test_component_platform,
)

from custom_components.annika import irrigation as irr
from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_IRRIGATION

ZONES = [
    "switch.west_drip",
    "switch.west_side",
    "switch.office_front",
    "switch.drip_east",
]

CONFIG = {
    "rain_sensor": "binary_sensor.rain",
    "rain_delay": "number.controller_rain_delay",
    "notify_view": "riego",
    "pause_seconds": 20,
    "start": {"time": "05:30"},
    "rain_delay_after_rain": 2,
    "groups": ["Goteo", "Aspersores"],
    "seasons": [
        {
            "name": "Verano",
            "months": [12, 1, 2],
            "days": ["tue", "fri"],
            "minutes": {"Goteo": 18, "Aspersores": 8},
        },
        {
            "name": "Invierno",
            "months": [6, 7, 8],
            "days": ["wed"],
            "minutes": {"Goteo": 12, "Aspersores": 4},
        },
    ],
    "zones": [
        {"entity": "switch.west_drip", "group": "Goteo", "name": "West drip"},
        {"entity": "switch.west_side", "group": "Aspersores"},
        {"entity": "switch.office_front", "group": "Aspersores"},
        {"entity": "switch.drip_east", "group": "Goteo"},
    ],
}

def local(*args: int) -> datetime:
    """A wall-clock time in the test instance's time zone (set up per test, not at import)."""
    return datetime(*args, tzinfo=dt_util.get_default_time_zone())


# Monday 15 December 2025, mid-morning: summer, and the next watering day is Tuesday.
MONDAY = (2025, 12, 15, 10, 0)


class FakeZone(SwitchEntity):
    """A valve: remembers what it was told."""

    _attr_should_poll = False

    def __init__(self, entity_id: str, log: list[tuple[str, str]]) -> None:
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self._attr_name = entity_id.split(".")[1]
        self._attr_is_on = False
        self._log = log

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._log.append(("on", self.entity_id))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._log.append(("off", self.entity_id))
        self._attr_is_on = False
        self.async_write_ha_state()


class FakeRainDelay(NumberEntity):
    """The controller's own rain delay, in days."""

    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_max_value = 14
    entity_id = "number.controller_rain_delay"
    _attr_unique_id = "controller_rain_delay"
    _attr_name = "controller_rain_delay"

    def __init__(self) -> None:
        self._attr_native_value = 0
        self.set_to: list[float] = []

    async def async_set_native_value(self, value: float) -> None:
        self.set_to.append(value)
        self._attr_native_value = value
        self.async_write_ha_state()


@pytest.fixture
def valves() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def waits(monkeypatch) -> dict:
    """Waits are recorded, not slept. `during` runs on a given wait to simulate the world moving."""

    record: dict = {"seconds": [], "during": {}}

    async def fake_wait(self, seconds: float) -> bool:
        record["seconds"].append(seconds)
        action = record["during"].get(len(record["seconds"]))
        if action is not None:
            await action()
        await asyncio.sleep(0)
        return self._abort.is_set()

    monkeypatch.setattr(irr.AnnikaIrrigation, "_wait", fake_wait)
    return record


@pytest.fixture
def annika_events():
    with patch.object(irr.AnnikaEventClient, "async_send", AsyncMock()) as send:
        yield send


@pytest.fixture
async def world(hass: HomeAssistant, valves, freezer):
    freezer.move_to(local(*MONDAY))
    rain_delay = FakeRainDelay()
    setup_test_component_platform(hass, "switch", [FakeZone(zone, valves) for zone in ZONES])
    setup_test_component_platform(hass, "number", [rain_delay])
    assert await async_setup_component(hass, "switch", {"switch": [{"platform": "test"}]})
    assert await async_setup_component(hass, "number", {"number": [{"platform": "test"}]})
    hass.states.async_set("binary_sensor.rain", STATE_OFF)
    await hass.async_block_till_done()
    return {"rain_delay": rain_delay}


async def start(hass: HomeAssistant, config: dict | None = None) -> irr.AnnikaIrrigation:
    irrigation = irr.AnnikaIrrigation(hass, irr.IRRIGATION_SCHEMA(config or CONFIG))
    hass.data[irr.DATA_IRRIGATION] = irrigation
    # The platforms come from the integration's setup; here they load without the rest of it.
    hass.config.components.add(DOMAIN)
    for platform in ("switch", "number", "select", "time", "button", "sensor"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_IRRIGATION}, {})
    await hass.async_block_till_done()
    await irrigation.async_start()
    await hass.async_block_till_done()
    return irrigation


def entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id


async def press(hass: HomeAssistant, unique_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity(hass, "button", unique_id)}, blocking=True
    )


async def until_idle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)


async def water_at(hass: HomeAssistant, freezer, when: datetime) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await until_idle(hass)


# --- configuration ----------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"seasons": [CONFIG["seasons"][0], {**CONFIG["seasons"][1], "months": [2, 3]}]}, "month 2"),
        ({"zones": [{"entity": "switch.x", "group": "Riego"}]}, "unknown group"),
        ({"seasons": [{**CONFIG["seasons"][0], "minutes": {"Riego": 3}}]}, "unknown group"),
        ({"seasons": [CONFIG["seasons"][0], {**CONFIG["seasons"][1], "name": "verano"}]}, "different names"),
        ({"start": {"time": "05:30", "sunrise_offset": "-02:00"}}, "start"),
        ({"seasons": [{**CONFIG["seasons"][0], "months": [13]}]}, "at most 12"),
    ],
)
def test_rejects_a_structure_that_cannot_water(change, message):
    with pytest.raises(vol.Invalid, match=message):
        irr.IRRIGATION_SCHEMA({**CONFIG, **change})


def test_reads_a_start_before_sunrise():
    config = irr.IRRIGATION_SCHEMA({**CONFIG, "start": {"sunrise_offset": "-02:00"}})
    irrigation = irr.AnnikaIrrigation(None, config)  # type: ignore[arg-type]

    assert irrigation.default_start_mode() == irr.START_SUNRISE
    assert irrigation.default_sunrise_offset_minutes() == -120


# --- entities -----------------------------------------------------------------


async def test_creates_the_schedule_entities_from_the_yaml_defaults(hass, world):
    await start(hass)

    verano = irr.IrrigationSeason("verano", "Verano", (12, 1, 2))
    goteo = irr.IrrigationGroup("goteo", "Goteo")
    assert hass.states.get(entity(hass, "switch", irr.unique_day(verano, "tue"))).state == STATE_ON
    assert hass.states.get(entity(hass, "switch", irr.unique_day(verano, "mon"))).state == STATE_OFF
    assert hass.states.get(entity(hass, "number", irr.unique_minutes(verano, goteo))).state == "18"
    assert hass.states.get(entity(hass, "select", irr.UNIQUE_START_MODE)).state == irr.START_TIME
    assert hass.states.get(entity(hass, "time", irr.UNIQUE_START_TIME)).state == "05:30:00"
    assert hass.states.get(entity(hass, "number", irr.UNIQUE_RAIN_DELAY_AFTER_RAIN)).state == "2"
    assert hass.states.get(entity(hass, "switch", irr.UNIQUE_ENABLED)).state == STATE_ON


async def test_the_status_sensor_maps_everything_the_card_needs(hass, world):
    await start(hass)

    status = hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS))
    assert status.state == irr.STATUS_IDLE
    assert [group["name"] for group in status.attributes["groups"]] == ["Goteo", "Aspersores"]
    verano = status.attributes["seasons"][0]
    assert verano["name"] == "Verano" and verano["months"] == [12, 1, 2]
    assert set(verano["days"]) == set(irr.WEEKDAYS)
    assert all(hass.states.get(entity_id) for entity_id in verano["days"].values())
    assert all(hass.states.get(entity_id) for entity_id in verano["minutes"].values())
    assert [zone["entity"] for zone in status.attributes["zones"]] == ZONES
    assert status.attributes["current_season"] == "verano"
    entities = status.attributes["entities"]
    for key in ("enabled", "start_mode", "sunrise_offset", "start_time", "rain_delay_after_rain", "run", "stop"):
        assert hass.states.get(entities[key]) is not None, key
    assert entities["rain_sensor"] == "binary_sensor.rain"


async def test_what_the_person_set_survives_a_restart(hass, world):
    number = {"native_unit_of_measurement": "min", "native_min_value": 0, "native_max_value": 120, "native_step": 1}
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State("switch.irrigation_verano_mon", STATE_ON), {}),
            (State("switch.irrigation_verano_tue", STATE_OFF), {}),
            (State("number.irrigation_verano_goteo_minutes", "25"), {**number, "native_value": 25}),
            (State("select.irrigation_start_mode", irr.START_SUNRISE), {}),
            (State("switch.irrigation_schedule", STATE_OFF), {}),
        ],
    )

    irrigation = await start(hass)

    assert irrigation.settings.days[("verano", "mon")] is True
    assert irrigation.settings.days[("verano", "tue")] is False
    assert irrigation.settings.minutes[("verano", "goteo")] == 25
    assert irrigation.settings.start_mode == irr.START_SUNRISE
    assert irrigation.settings.enabled is False


async def test_ignores_a_restored_value_out_of_range(hass, world):
    mock_restore_cache_with_extra_data(
        hass,
        [(State("number.irrigation_verano_goteo_minutes", "900"), {"native_value": 900, "native_unit_of_measurement": "min", "native_min_value": 0, "native_max_value": 900, "native_step": 1})],
    )

    irrigation = await start(hass)

    assert irrigation.settings.minutes[("verano", "goteo")] == 18


# --- the next run -------------------------------------------------------------


async def test_the_next_run_is_the_next_checked_day_at_the_start_time(hass, world):
    irrigation = await start(hass)

    assert dt_util.as_local(irrigation.next_run) == local(2025, 12, 16, 5, 30)


async def test_checking_a_day_moves_the_next_run(hass, world):
    irrigation = await start(hass)
    verano = irr.IrrigationSeason("verano", "Verano", (12, 1, 2))
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity(hass, "switch", irr.unique_day(verano, "tue"))}, blocking=True
    )

    assert dt_util.as_local(irrigation.next_run).date() == datetime(2025, 12, 19).date()


async def test_starts_relative_to_sunrise(hass, world):
    irrigation = await start(hass, {**CONFIG, "start": {"sunrise_offset": "-02:00"}})

    tuesday = datetime(2025, 12, 16).date()
    sunrise = dt_util.as_local(get_astral_event_date(hass, SUN_EVENT_SUNRISE, tuesday))
    assert irrigation.next_run == sunrise - timedelta(hours=2)


async def test_a_fixed_time_can_be_changed_from_its_entity(hass, world):
    irrigation = await start(hass)

    await hass.services.async_call(
        "time", "set_value", {"entity_id": entity(hass, "time", irr.UNIQUE_START_TIME), "time": "21:15"}, blocking=True
    )

    assert dt_util.as_local(irrigation.next_run).time() == time(21, 15)


async def test_nothing_is_scheduled_with_the_schedule_off(hass, world):
    irrigation = await start(hass)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity(hass, "switch", irr.UNIQUE_ENABLED)}, blocking=True
    )

    assert irrigation.next_run is None
    assert hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS)).state == irr.STATUS_DISABLED


async def test_a_month_no_season_covers_does_not_water(hass, world, freezer):
    freezer.move_to(local(2026, 3, 2, 10, 0))

    irrigation = await start(hass)

    assert irrigation.next_run is None


# --- a run ----------------------------------------------------------------------


async def test_waters_each_zone_in_order_with_its_group_minutes(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass)

    await water_at(hass, freezer, irrigation.next_run)

    assert valves == [
        ("on", "switch.west_drip"), ("off", "switch.west_drip"),
        ("on", "switch.west_side"), ("off", "switch.west_side"),
        ("on", "switch.office_front"), ("off", "switch.office_front"),
        ("on", "switch.drip_east"), ("off", "switch.drip_east"),
    ]
    # 18 / 8 / 8 / 18 minutes, 20 seconds between zones and none after the last.
    assert waits["seconds"] == [1080, 20, 480, 20, 480, 20, 1080]
    assert irrigation.last_result == "completed"
    assert hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS)).state == irr.STATUS_IDLE
    titles = [call.args[0]["title"] for call in annika_events.await_args_list]
    assert titles == ["🌱 Irrigation started", "🌱 Irrigation finished"]
    assert all(call.args[0]["view"] == "riego" and call.args[0]["type"] == "info" for call in annika_events.await_args_list)


async def test_the_logbook_and_the_events_follow_the_home_assistant_language(
    hass, world, waits, annika_events, freezer
):
    hass.config.language = "es-AR"
    logbook = async_capture_events(hass, "logbook_entry")
    irrigation = await start(hass)

    await water_at(hass, freezer, irrigation.next_run)

    sent = [(call.args[0]["title"], call.args[0]["message"]) for call in annika_events.await_args_list]
    assert sent == [("🌱 Riego iniciado", "Programa de Verano"), ("🌱 Riego terminado", "Programa de Verano")]
    assert [event.data["message"] for event in logbook] == ["Inicio del riego de Verano", "Riego de Verano terminado"]
    assert {event.data["name"] for event in logbook} == {"Riego"}


async def test_schedules_the_following_run_after_watering(hass, world, waits, annika_events, freezer):
    irrigation = await start(hass)

    await water_at(hass, freezer, irrigation.next_run)

    assert dt_util.as_local(irrigation.next_run) == local(2025, 12, 19, 5, 30)


async def test_waters_again_on_the_next_day(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass)
    await water_at(hass, freezer, irrigation.next_run)
    valves.clear()

    await water_at(hass, freezer, irrigation.next_run)

    assert [zone for action, zone in valves if action == "on"] == ZONES
    assert irrigation.last_result == "completed"


async def test_a_group_set_to_zero_minutes_is_skipped(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass)
    verano = irr.IrrigationSeason("verano", "Verano", (12, 1, 2))
    aspersores = irr.IrrigationGroup("aspersores", "Aspersores")
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": entity(hass, "number", irr.unique_minutes(verano, aspersores)), "value": 0},
        blocking=True,
    )

    await water_at(hass, freezer, irrigation.next_run)

    assert [zone for action, zone in valves if action == "on"] == ["switch.west_drip", "switch.drip_east"]


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda hass: hass.states.async_set("binary_sensor.rain", STATE_ON), "skipped:rain_sensor"),
        (lambda hass: hass.states.async_set("number.controller_rain_delay", "2"), "skipped:rain_delay"),
        (lambda hass: hass.states.async_set("switch.west_side", STATE_ON), "skipped:zone_running"),
    ],
)
async def test_does_not_water_when_it_should_not(hass, world, valves, waits, annika_events, freezer, setup, reason):
    irrigation = await start(hass)
    when = irrigation.next_run
    setup(hass)

    await water_at(hass, freezer, when)

    assert [action for action, _ in valves if action == "on"] == []
    assert irrigation.last_result == reason
    annika_events.assert_not_awaited()


async def test_rain_halfway_closes_the_open_zone_and_sets_the_controller_delay(
    hass, world, valves, waits, annika_events, freezer
):
    irrigation = await start(hass)

    async def it_rains():
        hass.states.async_set("binary_sensor.rain", STATE_ON)
        await hass.async_block_till_done()

    waits["during"][3] = it_rains  # while the second zone is open
    await water_at(hass, freezer, irrigation.next_run)

    assert valves[-1] == ("off", "switch.west_side")
    assert ("on", "switch.office_front") not in valves
    assert irrigation.last_result == irr.SKIP_RAIN
    assert world["rain_delay"].set_to == [2]
    assert annika_events.await_args_list[-1].args[0]["title"] == "🌧️ Irrigation stopped by rain"


async def test_the_stop_button_ends_the_run(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass)

    async def stop():
        await press(hass, irr.UNIQUE_STOP)

    waits["during"][1] = stop
    await water_at(hass, freezer, irrigation.next_run)

    assert valves == [("on", "switch.west_drip"), ("off", "switch.west_drip")]
    assert irrigation.last_result == "stopped"


async def test_turning_the_schedule_off_ends_the_run(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass)

    async def turn_off():
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity(hass, "switch", irr.UNIQUE_ENABLED)}, blocking=True
        )

    waits["during"][1] = turn_off
    await water_at(hass, freezer, irrigation.next_run)

    assert valves == [("on", "switch.west_drip"), ("off", "switch.west_drip")]
    assert irrigation.next_run is None


async def test_run_now_waters_the_current_season_on_any_day(hass, world, valves, waits, annika_events):
    await start(hass)

    await press(hass, irr.UNIQUE_RUN)
    await until_idle(hass)

    assert [zone for action, zone in valves if action == "on"] == ZONES


async def test_run_now_does_nothing_while_a_zone_is_running(hass, world, valves, waits, annika_events):
    await start(hass)
    hass.states.async_set("switch.west_side", STATE_ON)

    await press(hass, irr.UNIQUE_RUN)
    await until_idle(hass)

    assert valves == []


async def test_a_failing_valve_does_not_leave_the_run_marked_as_running(hass, world, waits, annika_events, freezer):
    irrigation = await start(hass)

    with patch.object(FakeZone, "async_turn_on", side_effect=RuntimeError("valve")):
        await water_at(hass, freezer, irrigation.next_run)

    assert irrigation.last_result == "failed"
    assert hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS)).state == irr.STATUS_IDLE


async def test_rain_bird_zones_run_on_the_controller_own_duration(hass, world, waits, annika_events, freezer):
    registry = er.async_get(hass)
    registry.async_get_or_create("switch", "rainbird", "zone-9", suggested_object_id="rb_front")
    hass.states.async_set("switch.rb_front", STATE_OFF)
    started: list[dict] = []

    async def start_irrigation(call: ServiceCall) -> None:
        started.append(dict(call.data))

    hass.services.async_register("rainbird", "start_irrigation", start_irrigation)
    config = {**CONFIG, "zones": [{"entity": "switch.rb_front", "group": "Goteo"}]}
    irrigation = await start(hass, config)

    await water_at(hass, freezer, irrigation.next_run)

    assert started == [{"entity_id": "switch.rb_front", "duration": 18}]


# --- rain delay -----------------------------------------------------------------


async def test_applies_the_rain_delay_when_the_rain_sensor_trips(hass, world):
    await start(hass)

    hass.states.async_set("binary_sensor.rain", STATE_ON)
    await hass.async_block_till_done()

    assert world["rain_delay"].set_to == [2]


async def test_applies_the_rain_delay_again_after_midnight_while_it_rains(hass, world, freezer):
    await start(hass)
    hass.states.async_set("binary_sensor.rain", STATE_ON)
    await hass.async_block_till_done()

    when = local(2025, 12, 16, 0, 5)
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()

    assert world["rain_delay"].set_to == [2, 2]


async def test_no_rain_delay_when_the_person_chose_none(hass, world):
    await start(hass)
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": entity(hass, "number", irr.UNIQUE_RAIN_DELAY_AFTER_RAIN), "value": 0},
        blocking=True,
    )

    hass.states.async_set("binary_sensor.rain", STATE_ON)
    await hass.async_block_till_done()

    assert world["rain_delay"].set_to == []


# --- the integration ----------------------------------------------------------


async def test_the_integration_wires_it_up_from_its_yaml(hass, world):
    from custom_components.annika import async_setup_irrigation

    hass.config.components.add(DOMAIN)  # as during the integration's own setup
    await async_setup_irrigation(hass, {DOMAIN: {"irrigation": irr.IRRIGATION_SCHEMA(CONFIG)}})
    await hass.async_block_till_done()

    status = hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS))
    assert len(status.attributes["seasons"]) == 2
    assert dt_util.as_local(hass.data[irr.DATA_IRRIGATION].next_run) == local(2025, 12, 16, 5, 30)


async def test_a_unit_without_irrigation_gets_none_of_it(hass, world):
    from custom_components.annika import async_setup_irrigation

    await async_setup_irrigation(hass, {DOMAIN: {}})
    await hass.async_block_till_done()

    assert irr.DATA_IRRIGATION not in hass.data
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, irr.UNIQUE_STATUS) is None


@pytest.mark.parametrize("language", ["en", "es"])
async def test_says_the_start_mode_and_status_in_words(hass, language):
    from homeassistant.helpers.translation import async_get_translations

    words = await async_get_translations(hass, language, "entity", {DOMAIN})

    for mode in irr.START_MODES:
        assert words.get(f"component.annika.entity.select.start_mode.state.{mode}"), mode
    for status in irr.STATUSES:
        assert words.get(f"component.annika.entity.sensor.irrigation_status.state.{status}"), status


# --- an automation of the house's own -------------------------------------------

WITH_AUTOMATION = {**CONFIG, "automation": "automation.riego"}


def test_only_an_automation_can_take_over():
    with pytest.raises(vol.Invalid):
        irr.IRRIGATION_SCHEMA({**CONFIG, "automation": "script.riego"})


async def test_with_an_automation_annika_does_not_water_on_its_own(hass, world, valves, waits, annika_events, freezer):
    irrigation = await start(hass, WITH_AUTOMATION)

    assert irrigation.next_run is None
    await water_at(hass, freezer, local(2025, 12, 16, 5, 30))

    assert valves == []
    annika_events.assert_not_awaited()


async def test_with_an_automation_every_entity_is_still_there_for_it(hass, world):
    await start(hass, WITH_AUTOMATION)

    status = hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS))
    entities = status.attributes["entities"]
    assert entities["automation"] == "automation.riego"
    for key in ("enabled", "start_mode", "sunrise_offset", "start_time", "run", "stop", "next_start"):
        assert hass.states.get(entities[key]) is not None, key
    assert status.attributes["automation"] == "automation.riego"


async def test_the_next_start_follows_the_card_whoever_waters(hass, world, freezer):
    await start(hass, WITH_AUTOMATION)
    next_start = entity(hass, "sensor", irr.UNIQUE_NEXT_START)

    assert dt_util.parse_datetime(hass.states.get(next_start).state) == local(2025, 12, 16, 5, 30)

    # Once that start has gone by, the sensor moves on to the next one.
    when = local(2025, 12, 16, 5, 30)
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()
    assert dt_util.parse_datetime(hass.states.get(next_start).state) == local(2025, 12, 19, 5, 30)


async def test_the_automation_can_read_what_today_waters(hass, world, freezer):
    freezer.move_to(local(2025, 12, 16, 4, 0))  # a Tuesday, checked in summer

    await start(hass, WITH_AUTOMATION)

    status = hass.states.get(entity(hass, "sensor", irr.UNIQUE_STATUS))
    assert status.attributes["waters_today"] is True
    assert status.attributes["program"] == [
        {"entity": "switch.west_drip", "minutes": 18},
        {"entity": "switch.west_side", "minutes": 8},
        {"entity": "switch.office_front", "minutes": 8},
        {"entity": "switch.drip_east", "minutes": 18},
    ]


async def test_with_an_automation_run_now_still_waters_by_hand(hass, world, valves, waits, annika_events):
    await start(hass, WITH_AUTOMATION)

    await press(hass, irr.UNIQUE_RUN)
    await until_idle(hass)

    assert [zone for action, zone in valves if action == "on"] == ZONES


async def test_without_an_automation_the_next_start_is_the_next_run(hass, world):
    irrigation = await start(hass)

    next_start = hass.states.get(entity(hass, "sensor", irr.UNIQUE_NEXT_START)).state
    assert dt_util.parse_datetime(next_start) == irrigation.next_run
