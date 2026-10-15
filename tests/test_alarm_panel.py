"""Tests for Annika's alarm panel, against Home Assistant's real alarm_control_panel platform."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from homeassistant.core import State

from custom_components.annika.alarm_panel import (
    ALARM_SCHEMA,
    DATA_ALARM_PANEL,
    AnnikaAlarmPanel,
)
from custom_components.annika.const import DOMAIN

ENTITY = "alarm_control_panel.home_alarm"
CONFIG = ALARM_SCHEMA(
    {
        "name": "Home Alarm",
        "code": "1234",
        "modes": {
            "away": {"arming": 30, "pending": 20},
            "night": {"arming": 0, "pending": 0},
            "vacation": {"arming": 10, "pending": 10},
        },
    }
)


async def setup_panel(hass: HomeAssistant, config=CONFIG) -> AnnikaAlarmPanel:
    assert await async_setup_component(hass, "alarm_control_panel", {})
    panel = AnnikaAlarmPanel(hass, config)
    hass.data[DATA_ALARM_PANEL] = panel
    # The platform loads without the rest of the integration's setup.
    hass.config.components.add(DOMAIN)
    await async_load_platform(hass, "alarm_control_panel", DOMAIN, {}, {})
    await hass.async_block_till_done()
    return panel


async def call(hass, service, **data):
    await hass.services.async_call(
        "alarm_control_panel", service, {"entity_id": ENTITY, **data}, blocking=True
    )


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def state(hass):
    return hass.states.get(ENTITY).state


async def test_schema_defaults_and_rejects_bad_codes():
    config = ALARM_SCHEMA({"code": "4321"})
    assert config["name"] == "Home Alarm"
    assert config["modes"]["away"] == {"arming": 30, "pending": 30}
    for bad in ("12", "abcd", "123456789"):
        with pytest.raises(Exception):
            ALARM_SCHEMA({"code": bad})


async def test_arming_counts_down_then_arms(hass, freezer):
    await setup_panel(hass)
    assert state(hass) == "disarmed"
    await call(hass, "alarm_arm_away", code="1234")
    assert state(hass) == "arming"
    assert hass.states.get(ENTITY).attributes["mode"] == "away"
    await advance(hass, freezer, 29)
    assert state(hass) == "arming"
    await advance(hass, freezer, 2)
    assert state(hass) == "armed_away"


async def test_mode_without_arming_time_arms_at_once(hass):
    await setup_panel(hass)
    await call(hass, "alarm_arm_night", code="1234")
    assert state(hass) == "armed_night"


async def test_wrong_or_missing_code_does_not_arm_or_disarm(hass):
    await setup_panel(hass)
    with pytest.raises(ServiceValidationError):
        await call(hass, "alarm_arm_night", code="0000")
    with pytest.raises(ServiceValidationError):
        await call(hass, "alarm_arm_night")
    assert state(hass) == "disarmed"
    await call(hass, "alarm_arm_night", code="1234")
    with pytest.raises(ServiceValidationError):
        await call(hass, "alarm_disarm", code="0000")
    assert state(hass) == "armed_night"
    await call(hass, "alarm_disarm", code="1234")
    assert state(hass) == "disarmed"


async def test_disarming_while_arming_cancels_it(hass, freezer):
    await setup_panel(hass)
    await call(hass, "alarm_arm_away", code="1234")
    await call(hass, "alarm_disarm", code="1234")
    await advance(hass, freezer, 60)
    assert state(hass) == "disarmed"


async def test_trigger_goes_pending_then_triggered_until_disarmed(hass, freezer):
    panel = await setup_panel(hass)
    await call(hass, "alarm_arm_vacation", code="1234")
    await advance(hass, freezer, 11)
    assert state(hass) == "armed_vacation"
    panel.trigger()
    assert state(hass) == "pending"
    await advance(hass, freezer, 11)
    assert state(hass) == "triggered"
    await advance(hass, freezer, 3600)
    assert state(hass) == "triggered"
    await call(hass, "alarm_disarm", code="1234")
    assert state(hass) == "disarmed"


async def test_disarming_during_pending_stops_the_trigger(hass, freezer):
    panel = await setup_panel(hass)
    await call(hass, "alarm_arm_vacation", code="1234")
    await advance(hass, freezer, 11)
    panel.trigger()
    await call(hass, "alarm_disarm", code="1234")
    await advance(hass, freezer, 60)
    assert state(hass) == "disarmed"


async def test_mode_without_pending_time_triggers_at_once(hass):
    panel = await setup_panel(hass)
    await call(hass, "alarm_arm_night", code="1234")
    panel.trigger()
    assert state(hass) == "triggered"


async def test_trigger_does_nothing_unless_armed(hass):
    panel = await setup_panel(hass)
    panel.trigger()
    assert state(hass) == "disarmed"
    await call(hass, "alarm_arm_away", code="1234")
    panel.trigger()
    assert state(hass) == "arming"


async def test_engine_can_arm_and_disarm_without_code(hass):
    panel = await setup_panel(hass)
    panel.arm("night", skip_code=True)
    assert state(hass) == "armed_night"
    panel.disarm(skip_code=True)
    assert state(hass) == "disarmed"


async def test_five_wrong_codes_lock_the_keypad_for_five_minutes(hass, freezer):
    await setup_panel(hass)
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await call(hass, "alarm_arm_night", code="0000")
    assert hass.states.get(ENTITY).attributes["locked_until"] is not None
    with pytest.raises(ServiceValidationError):
        await call(hass, "alarm_arm_night", code="1234")
    assert state(hass) == "disarmed"
    await advance(hass, freezer, 301)
    assert hass.states.get(ENTITY).attributes["locked_until"] is None
    await call(hass, "alarm_arm_night", code="1234")
    assert state(hass) == "armed_night"


async def test_a_right_code_resets_the_wrong_count(hass):
    await setup_panel(hass)
    for _ in range(4):
        with pytest.raises(ServiceValidationError):
            await call(hass, "alarm_arm_night", code="0000")
    await call(hass, "alarm_arm_night", code="1234")
    await call(hass, "alarm_disarm", code="1234")
    for _ in range(4):
        with pytest.raises(ServiceValidationError):
            await call(hass, "alarm_arm_night", code="0000")
    assert hass.states.get(ENTITY).attributes["locked_until"] is None


async def test_change_code_needs_the_current_one_and_replaces_it(hass):
    await setup_panel(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "change_code",
            {"entity_id": ENTITY, "current_code": "0000", "new_code": "5678"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "change_code",
            {"entity_id": ENTITY, "current_code": "1234", "new_code": "12"},
            blocking=True,
        )
    await hass.services.async_call(
        DOMAIN, "change_code",
        {"entity_id": ENTITY, "current_code": "1234", "new_code": "5678"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError):
        await call(hass, "alarm_arm_night", code="1234")
    await call(hass, "alarm_arm_night", code="5678")
    assert state(hass) == "armed_night"


async def test_changed_code_survives_a_restart_and_beats_the_yaml(hass, hass_storage):
    panel = await setup_panel(hass)
    await panel.async_change_code("1234", "5678")
    saved = hass_storage[f"{DOMAIN}.alarm_panel"]["data"]
    assert "5678" not in str(saved) and saved["initial"] is False

    other = AnnikaAlarmPanel(hass, CONFIG)
    await other.async_load()
    other.check_code("5678")


async def test_code_still_from_the_yaml_follows_the_yaml(hass, hass_storage):
    first = AnnikaAlarmPanel(hass, CONFIG)
    await first.async_load()
    changed = ALARM_SCHEMA({"code": "9999"})
    second = AnnikaAlarmPanel(hass, changed)
    await second.async_load()
    second.check_code("9999")


async def test_restart_keeps_armed_and_finishes_passed_deadlines(hass, freezer):
    now = dt_util.utcnow()
    mock_restore_cache_with_extra_data(
        hass,
        [(State(ENTITY, "pending", {"mode": "away", "deadline": (now - timedelta(seconds=5)).isoformat()}), {})],
    )
    await setup_panel(hass)
    assert state(hass) == "triggered"


async def test_restart_resumes_a_deadline_still_ahead(hass, freezer):
    now = dt_util.utcnow()
    mock_restore_cache_with_extra_data(
        hass,
        [(State(ENTITY, "arming", {"mode": "away", "deadline": (now + timedelta(seconds=10)).isoformat()}), {})],
    )
    await setup_panel(hass)
    assert state(hass) == "arming"
    await advance(hass, freezer, 11)
    assert state(hass) == "armed_away"


async def test_restart_keeps_an_armed_panel_armed(hass):
    mock_restore_cache_with_extra_data(
        hass, [(State(ENTITY, "armed_night", {"mode": "night"}), {})]
    )
    await setup_panel(hass)
    assert state(hass) == "armed_night"


# --- automatic arming and disarming ------------------------------------------

from datetime import datetime

from custom_components.annika.const import DISCOVERY_KIND, KIND_ALARM

SENSORS = ["binary_sensor.hall", "binary_sensor.kitchen"]
NIGHT_NOW = {"night": {"arming": 0, "pending": 0}}
AUTO = ALARM_SCHEMA(
    {
        "code": "1234",
        "modes": NIGHT_NOW,
        "auto_arm": {"mode": "night", "time": "23:00", "quiet_minutes": 10, "sensors": SENSORS},
        "auto_disarm": {"time": "07:00"},
    }
)


def at(freezer, hour, minute, second=0, day=14):
    # Local time: the panel's clocks are the house's wall clock.
    freezer.move_to(datetime(2026, 10, day, hour, minute, second, tzinfo=dt_util.DEFAULT_TIME_ZONE))


async def setup_auto(hass, freezer, config=AUTO, active=()):
    at(freezer, 22, 50)
    for sensor in SENSORS:
        hass.states.async_set(sensor, "on" if sensor in active else "off")
    panel = await setup_panel(hass, config)
    for platform in ("switch", "time", "number", "select"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_ALARM}, {})
    await hass.async_block_till_done()
    return panel


async def tick_to(hass, freezer, hour, minute, second=0, day=14):
    at(freezer, hour, minute, second, day)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def auto_entity(hass, domain, key):
    from homeassistant.helpers import entity_registry as er
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{DOMAIN}_alarm_{key}")


async def test_no_auto_entities_without_auto_config(hass):
    await setup_panel(hass)
    for platform in ("switch", "time", "number"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_ALARM}, {})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["auto"] == {}
    assert auto_entity(hass, "switch", "auto_arm_enabled") is None


async def test_auto_arm_waits_for_a_quiet_house_then_arms_without_a_code(hass, freezer):
    await setup_auto(hass, freezer)
    await tick_to(hass, freezer, 23, 0)
    assert state(hass) == "disarmed"  # quiet for 0 minutes so far
    await tick_to(hass, freezer, 23, 9, 59)
    assert state(hass) == "disarmed"
    await tick_to(hass, freezer, 23, 10, 1)
    assert state(hass) == "armed_night"


async def test_movement_restarts_the_quiet_time(hass, freezer):
    await setup_auto(hass, freezer)
    await tick_to(hass, freezer, 23, 0)
    await tick_to(hass, freezer, 23, 8)
    hass.states.async_set("binary_sensor.hall", "on")
    await hass.async_block_till_done()
    await tick_to(hass, freezer, 23, 12)
    assert state(hass) == "disarmed"
    hass.states.async_set("binary_sensor.hall", "off")
    await hass.async_block_till_done()
    await tick_to(hass, freezer, 23, 21)
    assert state(hass) == "disarmed"
    await tick_to(hass, freezer, 23, 23)
    assert state(hass) == "armed_night"


async def test_arm_time_with_an_active_sensor_waits_for_it_to_clear(hass, freezer):
    await setup_auto(hass, freezer, active=["binary_sensor.kitchen"])
    await tick_to(hass, freezer, 23, 0)
    await tick_to(hass, freezer, 23, 30)
    assert state(hass) == "disarmed"
    hass.states.async_set("binary_sensor.kitchen", "off")
    await hass.async_block_till_done()
    await tick_to(hass, freezer, 23, 41)
    assert state(hass) == "armed_night"


async def test_zero_quiet_minutes_arms_at_the_time(hass, freezer):
    config = ALARM_SCHEMA({"code": "1234", "modes": NIGHT_NOW, "auto_arm": {"time": "23:00", "sensors": SENSORS}})
    await setup_auto(hass, freezer, config)
    await tick_to(hass, freezer, 23, 0)
    assert state(hass) == "armed_night"


async def test_without_a_sensor_group_it_arms_at_the_time(hass, freezer):
    config = ALARM_SCHEMA({"code": "1234", "auto_arm": {"time": "23:00", "mode": "away"}})
    await setup_auto(hass, freezer, config)
    await tick_to(hass, freezer, 23, 0)
    assert state(hass) == "arming"
    assert hass.states.get(ENTITY).attributes["mode"] == "away"


async def test_arming_by_hand_while_waiting_ends_the_wait(hass, freezer):
    panel = await setup_auto(hass, freezer)
    await tick_to(hass, freezer, 23, 0)
    assert panel.auto_arm_waiting
    await call(hass, "alarm_arm_away", code="1234")
    assert not panel.auto_arm_waiting
    await call(hass, "alarm_disarm", code="1234")
    await tick_to(hass, freezer, 23, 30)
    assert state(hass) == "disarmed"


async def test_auto_arm_switched_off_does_nothing(hass, freezer):
    await setup_auto(hass, freezer)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": auto_entity(hass, "switch", "auto_arm_enabled")}, blocking=True
    )
    await tick_to(hass, freezer, 23, 0)
    await tick_to(hass, freezer, 23, 30)
    assert state(hass) == "disarmed"


async def test_auto_arm_does_not_touch_an_armed_panel(hass, freezer):
    panel = await setup_auto(hass, freezer)
    await call(hass, "alarm_arm_vacation", code="1234")
    await tick_to(hass, freezer, 23, 0)
    assert not panel.auto_arm_waiting
    assert hass.states.get(ENTITY).attributes["mode"] == "vacation"


async def test_auto_disarm_at_its_time_even_when_triggered(hass, freezer):
    panel = await setup_auto(hass, freezer)
    panel.arm("night", skip_code=True)
    panel.trigger()
    await tick_to(hass, freezer, 6, 59, day=15)
    assert state(hass) in ("pending", "triggered")
    await tick_to(hass, freezer, 7, 0, day=15)
    assert state(hass) == "disarmed"


@pytest.mark.parametrize("mode", ["away", "vacation"])
async def test_auto_disarm_leaves_other_modes_alone(hass, freezer, mode):
    panel = await setup_auto(hass, freezer)
    panel.arm(mode, skip_code=True)
    await tick_to(hass, freezer, 7, 0, day=15)
    assert state(hass) == f"armed_{mode}"


async def test_auto_disarm_mode_is_a_select_and_decides_what_it_disarms(hass, freezer):
    panel = await setup_auto(hass, freezer)
    select = auto_entity(hass, "select", "auto_disarm_mode")
    assert hass.states.get(select).state == "night"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": select, "option": "away"}, blocking=True
    )
    assert panel.auto_disarm_mode == "away"
    assert hass.states.get(ENTITY).attributes["auto"]["disarm"]["mode"] == "away"
    panel.arm("away", skip_code=True)
    await tick_to(hass, freezer, 7, 0, day=15)
    assert state(hass) == "disarmed"


async def test_auto_disarm_mode_is_restored_and_defaults_to_night(hass, freezer):
    mock_restore_cache_with_extra_data(hass, [(State("select.home_alarm_auto_disarm_mode", "vacation"), {})])
    panel = await setup_auto(hass, freezer)
    assert panel.auto_disarm_mode == "vacation"
    assert ALARM_SCHEMA({"code": "1234", "auto_disarm": {"time": "07:00"}})["auto_disarm"]["mode"] == "night"


async def test_auto_disarm_switched_off_does_nothing(hass, freezer):
    panel = await setup_auto(hass, freezer)
    panel.arm("night", skip_code=True)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": auto_entity(hass, "switch", "auto_disarm_enabled")}, blocking=True
    )
    await tick_to(hass, freezer, 7, 0, day=15)
    assert state(hass) == "armed_night"


async def test_editing_the_time_and_minutes_from_entities_retimes_it(hass, freezer):
    await setup_auto(hass, freezer)
    await hass.services.async_call(
        "time", "set_value", {"entity_id": auto_entity(hass, "time", "auto_arm_time"), "time": "22:55:00"}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": auto_entity(hass, "number", "auto_arm_quiet_minutes"), "value": 2}, blocking=True
    )
    await tick_to(hass, freezer, 22, 55)  # the new time, not 23:00
    assert state(hass) == "disarmed"
    await tick_to(hass, freezer, 22, 57, 1)  # two quiet minutes
    assert state(hass) == "armed_night"
    attrs = hass.states.get(ENTITY).attributes["auto"]["arm"]
    assert attrs["time"] == auto_entity(hass, "time", "auto_arm_time")


async def test_auto_settings_are_restored(hass, freezer):
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State("switch.home_alarm_auto_arm", "off"), {}),
            (State("time.home_alarm_auto_arm_time", "21:30:00"), {}),
            (State("number.home_alarm_auto_arm_quiet_minutes", "25"),
             {"native_max_value": 240, "native_min_value": 0, "native_step": 1,
              "native_unit_of_measurement": "min", "native_value": 25}),
        ],
    )
    panel = await setup_auto(hass, freezer)
    assert panel.auto_arm_enabled is False
    assert panel.auto_arm_time.hour == 21 and panel.auto_arm_time.minute == 30
    assert panel.auto_arm_quiet == 25


async def test_the_auto_arm_mode_is_a_select_and_decides_what_it_arms(hass, freezer):
    config = ALARM_SCHEMA({"code": "1234", "modes": NIGHT_NOW, "auto_arm": {"time": "23:00", "mode": "night"}})
    await setup_auto(hass, freezer, config)
    select = auto_entity(hass, "select", "auto_arm_mode")
    assert hass.states.get(select).state == "night"
    assert hass.states.get(ENTITY).attributes["auto"]["arm"]["mode_entity"] == select
    await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "vacation"}, blocking=True)
    await tick_to(hass, freezer, 23, 0)
    assert hass.states.get(ENTITY).attributes["mode"] == "vacation"


async def test_the_auto_arm_mode_is_restored(hass, freezer):
    mock_restore_cache_with_extra_data(hass, [(State("select.home_alarm_auto_arm_mode", "away"), {})])
    panel = await setup_auto(hass, freezer)
    assert panel.auto_arm_mode == "away"


async def test_arming_and_delay_seconds_are_edited_per_mode_and_stored(hass, freezer, hass_storage):
    panel = await setup_panel(hass)
    await hass.services.async_call(
        DOMAIN, "set_timing", {"entity_id": ENTITY, "mode": "away", "arming": 5, "pending": 7}, blocking=True
    )
    assert hass.states.get(ENTITY).attributes["modes"]["away"] == {"arming": 5, "pending": 7}
    assert hass.states.get(ENTITY).attributes["modes"]["night"] == {"arming": 0, "pending": 0}
    await call(hass, "alarm_arm_away", code="1234")
    await advance(hass, freezer, 6)
    assert state(hass) == "armed_away"
    panel.trigger()
    assert state(hass) == "pending"
    await advance(hass, freezer, 8)
    assert state(hass) == "triggered"
    await panel._store.async_save(panel._data())
    assert hass_storage[f"{DOMAIN}.alarm_panel"]["data"]["modes"]["away"] == {"arming": 5, "pending": 7}
    other = AnnikaAlarmPanel(hass, CONFIG)
    await other.async_load()
    assert other.modes["away"] == {"arming": 5, "pending": 7}
    other.check_code("1234")  # the code is kept too


async def test_one_of_the_two_times_can_change_alone_and_limits_hold(hass):
    await setup_panel(hass)
    await hass.services.async_call(
        DOMAIN, "set_timing", {"entity_id": ENTITY, "mode": "vacation", "pending": 0}, blocking=True
    )
    assert hass.states.get(ENTITY).attributes["modes"]["vacation"] == {"arming": 10, "pending": 0}
    for bad in ({"arming": -1}, {"pending": 601}, {"mode": "party"}):
        with pytest.raises(Exception):
            await hass.services.async_call(
                DOMAIN, "set_timing", {"entity_id": ENTITY, "mode": "away", **bad}, blocking=True
            )


async def test_disarm_without_code_is_off_unless_the_config_allows_it(hass):
    await setup_panel(hass)
    await call(hass, "alarm_arm_away", code="1234")
    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "disarm_without_code", {"entity_id": ENTITY}, blocking=True)
    assert state(hass) != "disarmed"


async def test_disarm_without_code_when_allowed_disarms_even_when_locked(hass):
    panel = await setup_panel(hass, ALARM_SCHEMA({**CONFIG, "allow_disarm_without_code": True}))
    await call(hass, "alarm_arm_night", code="1234")
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await call(hass, "alarm_disarm", code="0000")
    assert panel.locked
    await hass.services.async_call(DOMAIN, "disarm_without_code", {"entity_id": ENTITY}, blocking=True)
    assert state(hass) == "disarmed"


async def test_arm_without_code_is_off_unless_the_config_allows_it(hass):
    await setup_panel(hass)
    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN, "arm_without_code", {"entity_id": ENTITY, "mode": "night"}, blocking=True
        )
    assert state(hass) == "disarmed"


async def test_arm_without_code_when_allowed_arms_even_when_locked(hass):
    panel = await setup_panel(hass, ALARM_SCHEMA({**CONFIG, "allow_arm_without_code": True}))
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await call(hass, "alarm_arm_night", code="0000")
    assert panel.locked
    await hass.services.async_call(
        DOMAIN, "arm_without_code", {"entity_id": ENTITY, "mode": "night"}, blocking=True
    )
    assert state(hass) == "armed_night"
    # Only arming was opened up: disarming still needs the code.
    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "disarm_without_code", {"entity_id": ENTITY}, blocking=True)


async def test_a_bad_alarm_block_is_logged_and_skipped_not_fatal(hass, caplog):
    from custom_components.annika import DOMAIN as D, async_setup_alarm_panel

    await async_setup_alarm_panel(hass, {D: {"alarm": {"code": "abcd"}}})
    assert DATA_ALARM_PANEL not in hass.data
    assert "Annika alarm not started" in caplog.text
