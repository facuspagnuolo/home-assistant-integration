"""Tests for the alarm rules: what a detection means, and what answers it."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.annika import alarm_rules
from custom_components.annika.alarm_panel import ALARM_SCHEMA, AnnikaAlarmPanel
from custom_components.annika.alarm_rules import AnnikaAlarmRules
from custom_components.annika.const import DOMAIN

from .test_alarm_panel import (
    ENTITY,
    advance,
    call,
    setup_panel,
    state,
)

CAM1, CAM2, OFFICE, DOOR = (
    "binary_sensor.cam1_person",
    "binary_sensor.cam2_person",
    "binary_sensor.office_motion",
    "binary_sensor.garage_door",
)
INSTANT = {mode: {"arming": 0, "pending": 0} for mode in ("away", "night", "vacation")}

CONFIG = {
    "code": "1234",
    "modes": INSTANT,
    "warning": {"limit": 3, "window_minutes": 30},
    "notification": {"view": "alarm"},
    "outputs": [
        {"name": "Sirens", "entities": ["switch.sirenas"], "warning": {"enabled": True, "seconds": 3}},
        {
            "name": "Floodlights",
            "entities": ["switch.reflectores", "light.flood_1"],
            "warning": {"enabled": True, "seconds": 60},
        },
        {"name": "Garden", "entities": ["light.garden"]},
    ],
    "zones": [
        {
            "name": "Exterior",
            "rules": {"away": "warning", "night": "warning", "vacation": "warning"},
            "sensors": [
                {"name": "Camera 1", "entities": [CAM1], "detail": "person"},
                {"name": "Camera 2", "entities": [CAM2], "rules": {"night": "off"}},
            ],
        },
        {
            "name": "Interior",
            "rules": {"away": "trigger", "vacation": "trigger"},
            "sensors": [{"name": "Office", "entities": [OFFICE]}],
        },
        {
            "name": "Perimeter",
            "rules": {"away": "trigger", "night": "trigger", "vacation": "trigger"},
            "sensors": [{"name": "Garage door", "entities": [DOOR]}],
        },
    ],
}


@pytest.fixture
def events():
    with patch.object(alarm_rules.AnnikaEventClient, "async_send", AsyncMock()) as send:
        yield send


async def setup_rules(hass, config=CONFIG, language="en"):
    hass.config.language = language
    for sensor in (CAM1, CAM2, OFFICE, DOOR):
        hass.states.async_set(sensor, "off")
    turn_on = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")
    parsed = ALARM_SCHEMA(config)
    # setup_panel builds the panel itself; give it the rules before the platform loads.
    from custom_components.annika import alarm_panel

    original = alarm_panel.AnnikaAlarmPanel.__init__

    def with_rules(self, hass_, cfg):
        original(self, hass_, cfg)
        self.rules = AnnikaAlarmRules(hass_, self, cfg)

    with patch.object(alarm_panel.AnnikaAlarmPanel, "__init__", with_rules):
        panel = await setup_panel(hass, parsed)
    return panel, turn_on, turn_off


def detect(hass, sensor):
    hass.states.async_set(sensor, "off")
    hass.states.async_set(sensor, "on")


def entities(calls):
    return [entity for c in calls for entity in c.data["entity_id"]]


def decisions(hass):
    return [d["text"] for d in hass.states.get(ENTITY).attributes["decisions"]]


async def armed(hass, mode="away"):
    await call(hass, f"alarm_arm_{mode}", code="1234")


async def test_a_warning_switches_the_outputs_on_for_their_time_and_logs_it(hass, freezer):
    panel, on, off = await setup_rules(hass)
    await armed(hass)
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert sorted(entities(on)) == ["light.flood_1", "switch.reflectores", "switch.sirenas"]
    assert state(hass) == "armed_away"
    assert decisions(hass)[0] == "Camera 1 · away · warning 1 of 3 · Sirens, Floodlights on"
    assert panel.rules.count == 1
    await advance(hass, freezer, 4)
    assert entities(off) == ["switch.sirenas"]
    await advance(hass, freezer, 60)
    assert "switch.reflectores" in entities(off)


async def test_past_the_limit_the_next_warning_triggers_until_disarmed(hass, freezer):
    panel, on, off = await setup_rules(hass)
    await armed(hass)
    for _ in range(3):
        detect(hass, CAM1)
        await hass.async_block_till_done()
        await advance(hass, freezer, 5)
    assert state(hass) == "armed_away"
    on.clear()
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"
    assert decisions(hass)[1] == "Camera 1 · away · warning limit reached, trigger"
    # Trigger outputs: sirens and floodlights (trigger on by default), not the garden's... all default on.
    assert "switch.sirenas" in entities(on)
    off.clear()
    await advance(hass, freezer, 10 * 60)  # less than the window: the count is still 3
    assert off == [] and panel.rules.count == 3
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert "switch.sirenas" in entities(off)
    assert panel.rules.count == 0
    assert "Disarmed: counter reset, outputs off" in decisions(hass)[0]


async def test_a_quiet_window_starts_the_count_over(hass, freezer):
    panel, on, off = await setup_rules(hass)
    await armed(hass)
    for _ in range(3):
        detect(hass, CAM1)
        await hass.async_block_till_done()
    assert panel.rules.count == 3
    assert hass.states.get(ENTITY).attributes["config"]["warning"]["resets_at"] is not None
    await advance(hass, freezer, 31 * 60)
    assert panel.rules.count == 0
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert state(hass) == "armed_away"
    assert decisions(hass)[0].startswith("Camera 1 · away · warning 1 of 3")


async def test_the_count_also_resets_when_the_window_passed_between_detections(hass, freezer):
    panel, *_ = await setup_rules(hass)
    await armed(hass)
    for _ in range(3):
        detect(hass, CAM1)
    await hass.async_block_till_done()
    panel.rules._cancel_expiry()  # as if the timer had been missed
    panel.rules._cancel_expiry = None
    freezer.tick(timedelta(minutes=31))
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert state(hass) == "armed_away"
    assert panel.rules.count == 1


async def test_a_sensor_off_in_the_mode_is_ignored_but_logged(hass):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "night")
    detect(hass, CAM2)
    await hass.async_block_till_done()
    assert on == [] and state(hass) == "armed_night"
    assert decisions(hass)[0] == "Camera 2 · night · ignored: off in night"


async def test_a_sensor_inherits_the_zone_rule_and_its_own_wins(hass):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "away")
    detect(hass, CAM2)  # inherits Exterior: warning
    await hass.async_block_till_done()
    assert panel.rules.count == 1
    detect(hass, OFFICE)  # Interior: trigger in away
    await hass.async_block_till_done()
    assert state(hass) == "triggered"


async def test_a_trigger_rule_trips_the_panel_and_switches_trigger_outputs(hass):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "night")
    detect(hass, DOOR)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"
    assert decisions(hass)[1] == "Garage door · night · trigger"
    assert sorted(entities(on)) == ["light.flood_1", "light.garden", "switch.reflectores", "switch.sirenas"]


async def test_trigger_goes_through_pending_when_the_mode_gives_time(hass, freezer):
    modes = {**INSTANT, "away": {"arming": 0, "pending": 20}}
    panel, on, off = await setup_rules(hass, {**CONFIG, "modes": modes})
    await armed(hass, "away")
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    assert state(hass) == "pending" and on == []
    await advance(hass, freezer, 21)
    assert state(hass) == "triggered" and entities(on)


async def test_detections_do_nothing_unless_armed(hass, freezer):
    panel, on, off = await setup_rules(hass)
    detect(hass, DOOR)
    await hass.async_block_till_done()
    assert state(hass) == "disarmed" and on == [] and decisions(hass) == []


async def test_detections_while_arming_are_ignored(hass):
    modes = {**INSTANT, "away": {"arming": 30, "pending": 0}}
    panel, on, off = await setup_rules(hass, {**CONFIG, "modes": modes})
    await call(hass, "alarm_arm_away", code="1234")
    assert state(hass) == "arming"
    detect(hass, DOOR)
    await hass.async_block_till_done()
    assert state(hass) == "arming" and on == [] and decisions(hass) == []


async def test_only_a_real_off_to_on_counts(hass):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "night")
    hass.states.async_set(DOOR, "unavailable")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert state(hass) == "armed_night"
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert state(hass) == "triggered"


async def test_a_siren_a_trigger_turned_on_is_not_cut_by_the_warning_timer(hass, freezer):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    await advance(hass, freezer, 1)
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"
    off.clear()
    await advance(hass, freezer, 120)
    assert off == []


async def test_a_warning_timer_does_not_switch_off_an_output_a_trigger_keeps_off_the_list(hass, freezer):
    config = {
        **CONFIG,
        "outputs": [{"name": "Sirens", "entities": ["switch.sirenas"],
                     "warning": {"enabled": True, "seconds": 3}, "trigger": {"enabled": False}}],
    }
    panel, on, off = await setup_rules(hass, config)
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    await advance(hass, freezer, 4)
    assert entities(off) == ["switch.sirenas"]


async def test_editing_a_rule_changes_behaviour_and_is_stored(hass, hass_storage):
    panel, on, off = await setup_rules(hass)
    await hass.services.async_call(
        DOMAIN, "set_rule",
        {"entity_id": ENTITY, "target": "zone", "id": "exterior", "mode": "away", "rule": "trigger"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "set_rule",
        {"entity_id": ENTITY, "target": "sensor", "id": "exterior.camera_1", "mode": "away", "rule": "off"},
        blocking=True,
    )
    config = hass.states.get(ENTITY).attributes["config"]
    zone = config["zones"][0]
    # The card lights a sensor up from the entities it watches.
    assert zone["sensors"][0]["entities"] == [CAM1]
    assert zone["rules"]["away"] == "trigger" and zone["sensors"][0]["rules"]["away"] == "off"
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert state(hass) == "armed_away" and on == []  # the sensor's own rule: off
    detect(hass, CAM2)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"  # inherits the zone's new rule
    await panel.rules.async_stop()
    saved = hass_storage[f"{DOMAIN}.alarm_rules"]["data"]
    assert saved["rules"]["zone:exterior"]["away"] == "trigger"


async def test_stored_settings_win_over_the_yaml(hass, hass_storage):
    hass_storage[f"{DOMAIN}.alarm_rules"] = {
        "version": 1,
        "data": {
            "warning": {"limit": 1, "window_minutes": 5},
            "outputs": {"sirens": {"warning_seconds": 9, "warning_enabled": False}},
            "rules": {"zone:exterior": {"away": "off"}, "sensor:exterior.camera_2": {"away": "trigger"}},
        },
    }
    panel, on, off = await setup_rules(hass)
    config = hass.states.get(ENTITY).attributes["config"]
    assert config["warning"]["limit"] == 1
    sirens = config["outputs"][0]
    assert sirens["warning_seconds"] == 9 and sirens["warning_enabled"] is False
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert on == []  # exterior is off in away
    detect(hass, CAM2)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"


async def test_output_and_warning_settings_can_be_edited(hass, freezer):
    panel, on, off = await setup_rules(hass)
    await hass.services.async_call(
        DOMAIN, "set_output",
        {"entity_id": ENTITY, "output": "sirens", "warning_seconds": 10, "trigger_enabled": False},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "set_output", {"entity_id": ENTITY, "output": "garden", "warning_enabled": True}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "set_warning", {"entity_id": ENTITY, "limit": 1, "window_minutes": 5}, blocking=True
    )
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert "light.garden" in entities(on)
    await advance(hass, freezer, 4)
    assert "switch.sirenas" not in entities(off)  # sirens now last 10 s
    await advance(hass, freezer, 7)
    assert "switch.sirenas" in entities(off)
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"  # limit is 1 now


async def test_unknown_targets_are_refused(hass):
    await setup_rules(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_rule",
            {"entity_id": ENTITY, "target": "zone", "id": "nowhere", "mode": "away", "rule": "off"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "test_output", {"entity_id": ENTITY, "output": "nothing"}, blocking=True
        )


async def test_notifications_follow_their_switches(hass, events):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    sent = [c.args[0] for c in events.call_args_list]
    assert sent[0]["title"] == "⚠️ Alarm warning" and sent[0]["view"] == "alarm"
    assert sent[0]["message"] == "Camera 1 - warning 1 of 3"
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    assert events.call_args_list[-1].args[0]["title"] == "🚨 Alarm triggered"
    assert events.call_args_list[-1].args[0]["message"] == "Reminder #1"
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    events.reset_mock()
    await hass.services.async_call(
        DOMAIN, "set_notification", {"entity_id": ENTITY, "warning": False, "trigger": False}, blocking=True
    )
    await armed(hass, "away")
    detect(hass, CAM1)
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    events.assert_not_called()


async def test_without_a_view_nothing_is_sent(hass, events):
    config = {**CONFIG, "notification": {}}
    await setup_rules(hass, config)
    await armed(hass, "away")
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    events.assert_not_called()


async def test_testing_an_output_runs_it_and_a_notification_sends_one(hass, freezer, events):
    panel, on, off = await setup_rules(hass)
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "sirens"}, blocking=True
    )
    assert entities(on) == ["switch.sirenas"]
    await advance(hass, freezer, 4)
    assert entities(off) == ["switch.sirenas"]
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "garden"}, blocking=True
    )
    await advance(hass, freezer, 4)  # garden has no warning time: a test lasts 3 s
    assert "light.garden" in entities(off)
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "notification"}, blocking=True
    )
    await hass.async_block_till_done()
    assert events.call_args.args[0]["title"] == "Alarm notification test"


async def test_testing_does_nothing_while_the_alarm_is_triggered(hass):
    panel, on, off = await setup_rules(hass)
    await armed(hass, "night")
    detect(hass, DOOR)
    await hass.async_block_till_done()
    on.clear()
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "sirens"}, blocking=True
    )
    assert on == []


async def test_decisions_and_the_logbook_speak_the_house_language(hass):
    from homeassistant.components.logbook import EVENT_LOGBOOK_ENTRY
    from pytest_homeassistant_custom_component.common import async_capture_events

    lines = async_capture_events(hass, EVENT_LOGBOOK_ENTRY)
    panel, on, off = await setup_rules(hass, language="es-AR")
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    assert decisions(hass)[0] == "Camera 1 · afuera · aviso 1 de 3 · Sirens, Floodlights encendido"
    assert lines[-1].data["name"] == "Alarma" and lines[-1].data["entity_id"] == ENTITY


async def test_decisions_keep_only_the_latest_ones(hass):
    panel, *_ = await setup_rules(hass)
    await armed(hass, "night")
    for _ in range(alarm_rules.MAX_DECISIONS + 5):
        detect(hass, CAM2)  # ignored in night, one line each
        await hass.async_block_till_done()
    assert len(hass.states.get(ENTITY).attributes["decisions"]) == alarm_rules.MAX_DECISIONS


async def test_a_restored_armed_panel_still_reacts_and_disarming_resets(hass):
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import mock_restore_cache_with_extra_data

    mock_restore_cache_with_extra_data(hass, [(State(ENTITY, "armed_away", {"mode": "away"}), {})])
    panel, on, off = await setup_rules(hass)
    assert state(hass) == "armed_away"
    detect(hass, OFFICE)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert "switch.sirenas" in entities(off)


async def test_schema_defaults_and_validation():
    parsed = ALARM_SCHEMA({"code": "1234"})
    assert parsed["zones"] == [] and parsed["outputs"] == []
    assert parsed["warning"] == {"limit": 3, "window_minutes": 30}
    with pytest.raises(Exception):
        ALARM_SCHEMA({"code": "1234", "zones": [{"name": "X", "rules": {"away": "loud"}, "sensors": []}]})
    with pytest.raises(Exception):
        ALARM_SCHEMA({"code": "1234", "outputs": [{"name": "X", "entities": []}]})


def test_an_unquoted_off_in_yaml_means_off():
    import yaml
    from custom_components.annika.alarm_rules import ZONE_SCHEMA

    zone = yaml.safe_load(
        "name: Z\nrules: {night: off, away: warning}\nsensors:\n  - {name: S, entities: [binary_sensor.s], rules: {vacation: off}}"
    )
    parsed = ZONE_SCHEMA(zone)
    assert parsed["rules"] == {"night": "off", "away": "warning"}
    assert parsed["sensors"][0]["rules"] == {"vacation": "off"}


async def test_testing_a_running_output_again_stops_it(hass, freezer):
    panel, on, off = await setup_rules(hass)

    def running():
        outputs = hass.states.get(ENTITY).attributes["config"]["outputs"]
        return {o["id"]: o["on"] for o in outputs}["sirens"]

    assert running() is False
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "sirens"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entities(on) == ["switch.sirenas"]
    assert running() is True  # the card turns play into stop from this
    await hass.services.async_call(
        DOMAIN, "test_output", {"entity_id": ENTITY, "output": "sirens"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entities(off) == ["switch.sirenas"]  # stopped right away, not after its timer
    assert running() is False
    on.clear()
    await advance(hass, freezer, 60)
    assert entities(off) == ["switch.sirenas"]  # the old timer is gone: no second turn_off


def _triggered_titles(events):
    return [c.args[0]["title"] for c in events.call_args_list if c.args[0]["title"] == "🚨 Alarm triggered"]


async def test_the_trigger_notification_repeats_while_triggered_and_stops_on_disarm(hass, freezer, events):
    config = {**CONFIG, "notification": {"view": "alarm", "trigger_repeat": 5}}
    await setup_rules(hass, config)
    await armed(hass, "away")
    detect(hass, OFFICE)
    detect(hass, DOOR)
    await hass.async_block_till_done()
    assert state(hass) == "triggered"
    assert len(_triggered_titles(events)) == 1
    await advance(hass, freezer, 5)
    await advance(hass, freezer, 5)
    assert len(_triggered_titles(events)) == 3
    await call(hass, "alarm_disarm", code="1234")
    await advance(hass, freezer, 30)
    assert len(_triggered_titles(events)) == 3


async def test_the_trigger_notification_is_sent_once_without_a_repeat(hass, freezer, events):
    await setup_rules(hass)
    await armed(hass, "away")
    detect(hass, OFFICE)
    detect(hass, DOOR)
    await hass.async_block_till_done()
    await advance(hass, freezer, 60)
    assert len(_triggered_titles(events)) == 1


async def test_the_repeat_is_edited_from_the_card_and_stored(hass, freezer, events, hass_storage):
    panel, _on, _off = await setup_rules(hass)
    await hass.services.async_call(
        DOMAIN, "set_notification", {"entity_id": ENTITY, "trigger_repeat": 5}, blocking=True
    )
    assert hass.states.get(ENTITY).attributes["config"]["notification"]["trigger_repeat"] == 5
    await armed(hass, "away")
    detect(hass, OFFICE)
    detect(hass, DOOR)
    await hass.async_block_till_done()
    await advance(hass, freezer, 5)
    assert len(_triggered_titles(events)) == 2


def _messages(events, title):
    return [c.args[0]["message"] for c in events.call_args_list if c.args[0]["title"] == title]


async def test_the_reminders_are_numbered(hass, freezer, events):
    config = {**CONFIG, "notification": {"view": "alarm", "trigger_repeat": 5}}
    await setup_rules(hass, config)
    await armed(hass, "away")
    detect(hass, OFFICE)
    detect(hass, DOOR)
    await hass.async_block_till_done()
    await advance(hass, freezer, 5)
    await advance(hass, freezer, 5)
    assert _messages(events, "🚨 Alarm triggered") == ["Reminder #1", "Reminder #2", "Reminder #3"]


async def test_disarming_says_who_when_the_app_stamped_the_call(hass, events):
    from custom_components.annika.actor import Actor, async_setup_actor

    await setup_rules(hass)
    async_setup_actor(hass)
    stamps = hass.data["annika_actor"]["stamps"]
    await armed(hass, "away")
    events.reset_mock()
    stamps.stamp(Actor(name="Delfi"), "alarm_control_panel", "alarm_disarm", [ENTITY])
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert _messages(events, "🔓 Alarm disarmed") == ["Disarmed by Delfi"]


async def test_disarming_without_a_name_just_says_disarmed(hass, events):
    await setup_rules(hass)
    await armed(hass, "away")
    events.reset_mock()
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert _messages(events, "🔓 Alarm disarmed") == ["Disarmed"]


async def test_disarming_is_not_announced_when_the_config_says_no(hass, events):
    config = {**CONFIG, "notification": {"view": "alarm", "disarm": False}}
    await setup_rules(hass, config)
    await armed(hass, "away")
    events.reset_mock()
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert _messages(events, "🔓 Alarm disarmed") == []


async def test_the_spanish_texts(hass, events):
    await setup_rules(hass, language="es")
    await armed(hass, "away")
    detect(hass, CAM1)
    await hass.async_block_till_done()
    sent = events.call_args_list[0].args[0]
    assert sent["title"] == "⚠️ Aviso de alarma" and sent["message"] == "Camera 1 - aviso 1 de 3"
    await call(hass, "alarm_disarm", code="1234")
    await hass.async_block_till_done()
    assert _messages(events, "🔓 Alarma desactivada") == ["Desactivada"]
