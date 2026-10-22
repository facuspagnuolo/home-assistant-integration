"""Tests for Annika's locks: codes and their emergency codes, who opened, the rule, lock when closed."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.annika.alarm_panel import DATA_ALARM_PANEL
from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_LOCKS
from custom_components.annika.locks import (
    CODE_MAX_LENGTH,
    DATA_LOCKS,
    LOCKS_SCHEMA,
    ZWAVE_WAIT,
    AnnikaLocks,
    CodeError,
    emergency_code,
    random_code,
)

FRONT = "lock.front_door_lock"
KITCHEN = "lock.kitchen_door_lock"
DOOR = "binary_sensor.front_door_contact"
DEVICES = {FRONT: "dev_front", KITCHEN: "dev_kitchen"}


def config(**overrides):
    values = {
        "notify_view": "locks",
        "locks": [
            {"name": "Front Door", "entity": FRONT, "sensor": DOOR},
            {"name": "Kitchen Door", "entity": KITCHEN},
        ],
    }
    values.update(overrides)
    return LOCKS_SCHEMA(values)


@pytest.fixture
def zwave(hass):
    return SimpleNamespace(
        set=async_mock_service(hass, "zwave_js", "set_lock_usercode"),
        clear=async_mock_service(hass, "zwave_js", "clear_lock_usercode"),
        lock=async_mock_service(hass, "lock", "lock"),
    )


@pytest.fixture
def sent():
    with patch("custom_components.annika.locks.AnnikaEventClient") as client:
        client.return_value.async_send = AsyncMock()
        yield client.return_value.async_send


def panel(state="armed_away", mode="away"):
    stub = SimpleNamespace(state=state, mode=mode, armed=state.startswith("armed_"), last_source=None)

    def disarm(code=None, *, skip_code=False, source=None):
        stub.state, stub.mode, stub.armed, stub.last_source = "disarmed", None, False, source

    stub.disarm = MagicMock(side_effect=disarm)
    stub.enabled_modes = ["away", "night", "vacation"]  # a property of the real panel
    return stub


async def start(hass, **overrides) -> AnnikaLocks:
    locks = AnnikaLocks(hass, config(**overrides))
    locks._device_id = lambda lock: DEVICES[lock.entity]
    hass.states.async_set(FRONT, "locked")
    hass.states.async_set(KITCHEN, "locked")
    hass.states.async_set(DOOR, "off")
    await locks.async_start()
    return locks


def zwave_event(hass, lock, event, user_id=None):
    data = {"device_id": DEVICES[lock], "label": "Access Control", "event": event}
    if user_id is not None:
        data["parameters"] = {"userId": user_id}
    hass.bus.async_fire("zwave_js_notification", data)


@pytest.fixture
def clock(hass, freezer):
    """Move time forward and let what was scheduled for then run."""

    async def tick(seconds):
        await hass.async_block_till_done()  # what was just set has been seen and its timers started
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    return tick


# --- schema ------------------------------------------------------------------


def test_schema_defaults():
    values = config()
    assert values["slots"] == 10
    assert values["emergency_offset"] == 200
    assert values["disarm_alarm"]["enabled"] is False


def test_schema_rejects_an_offset_inside_the_slots():
    with pytest.raises(vol.Invalid):
        config(slots=50, emergency_offset=20)


def test_schema_rejects_a_non_lock():
    with pytest.raises(vol.Invalid):
        config(locks=[{"name": "x", "entity": "switch.x"}])


def test_emergency_code_is_the_same_with_a_zero():
    assert emergency_code("482915") == "482910"


def test_a_random_code_never_ends_in_zero():
    for _ in range(200):
        code = random_code()
        assert len(code) == 6 and not code.endswith("0")
    assert len(random_code(CODE_MAX_LENGTH)) == CODE_MAX_LENGTH


# --- codes -------------------------------------------------------------------


def slots_in_locks(hass, contents):
    """Make `zwave_js.get_lock_usercode` answer from {lock: {slot: code}}."""

    async def handler(call):
        entity, slot = call.data["entity_id"], call.data["code_slot"]
        code = contents.get(entity, {}).get(slot)
        return {entity: {str(slot): {"in_use": code is not None, "usercode": code or ""}}}

    hass.services.async_register("zwave_js", "get_lock_usercode", handler, supports_response=SupportsResponse.ONLY)


async def test_the_codes_the_locks_already_hold_are_imported(hass, zwave, sent):
    slots_in_locks(hass, {FRONT: {1: "482915", 3: "112233"}, KITCHEN: {1: "482915", 2: "556677"}})
    locks = await start(hass)
    assert await locks.async_import_codes() == 3
    by_slot = {item["slot"]: item for item in locks.codes}
    assert by_slot[1]["locks"] == ["front_door", "kitchen_door"] and by_slot[1]["code"] == "482915"
    assert by_slot[2]["locks"] == ["kitchen_door"]
    assert by_slot[3]["locks"] == ["front_door"]
    assert by_slot[1]["name"] == "Code in slot 1" and by_slot[1]["type"] == "fixed"
    programmed = {(c.data["entity_id"], c.data["code_slot"], c.data["usercode"]) for c in zwave.set}
    assert (FRONT, 201, "482910") in programmed and (KITCHEN, 201, "482910") in programmed
    assert (KITCHEN, 202, "556670") in programmed and (FRONT, 203, "112230") in programmed
    assert not any(c.data["code_slot"] <= 10 for c in zwave.set)  # the codes themselves are never rewritten


async def test_an_emergency_code_that_is_already_there_is_left_alone(hass, zwave, sent):
    slots_in_locks(hass, {FRONT: {1: "482915", 201: "482910"}})
    locks = await start(hass)
    assert await locks.async_import_codes() == 1
    assert zwave.set == []


async def test_importing_twice_adds_nothing(hass, zwave, sent):
    slots_in_locks(hass, {FRONT: {1: "482915"}})
    locks = await start(hass)
    assert await locks.async_import_codes() == 1
    assert await locks.async_import_codes() == 0
    assert len(locks.codes) == 1


async def test_a_slot_that_differs_between_locks_is_not_imported(hass, zwave, sent):
    slots_in_locks(hass, {FRONT: {1: "482915"}, KITCHEN: {1: "111222"}})
    locks = await start(hass)
    assert await locks.async_import_codes() == 0
    assert locks.codes == []


async def test_a_code_annika_cannot_keep_is_not_imported(hass, zwave, sent):
    slots_in_locks(hass, {FRONT: {1: "482910"}})  # ends in 0
    locks = await start(hass)
    assert await locks.async_import_codes() == 0


async def test_a_code_is_renamed(hass, zwave, sent):
    locks = await start(hass)
    item = await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    await locks.async_rename_code(item["id"], "  Mamá ")
    assert locks.codes[0]["name"] == "Mamá"
    with pytest.raises(CodeError):
        await locks.async_rename_code(item["id"], " ")
    with pytest.raises(CodeError):
        await locks.async_rename_code("nope", "x")


async def test_a_code_is_programmed_with_its_emergency_code(hass, zwave, sent):
    locks = await start(hass)
    item = await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    assert item["slot"] == 1
    assert item["locks"] == ["front_door"]
    assert [(call.data["entity_id"], call.data["code_slot"], call.data["usercode"]) for call in zwave.set] == [
        (FRONT, 1, "482915"),
        (FRONT, 201, "482910"),
    ]


async def test_the_next_code_takes_the_next_slot_in_every_lock(hass, zwave, sent):
    locks = await start(hass)
    await locks.async_add_code("Facu", code="482915")
    second = await locks.async_add_code("Delfi", code="730284")
    assert second["slot"] == 2
    assert {call.data["entity_id"] for call in zwave.set} == {FRONT, KITCHEN}
    assert (KITCHEN, 202, "730280") in [
        (call.data["entity_id"], call.data["code_slot"], call.data["usercode"]) for call in zwave.set
    ]


async def test_a_code_is_made_when_none_is_given(hass, zwave, sent):
    locks = await start(hass)
    item = await locks.async_add_code("Guest")
    assert len(item["code"]) == 6 and not item["code"].endswith("0")


@pytest.mark.parametrize("code", ["123", "123456789", "12ab56", "482910"])
async def test_a_bad_code_is_refused(hass, zwave, sent, code):
    locks = await start(hass)
    with pytest.raises(CodeError):
        await locks.async_add_code("Facu", code=code)
    assert zwave.set == []


async def test_a_code_too_close_to_another_is_refused(hass, zwave, sent):
    locks = await start(hass)
    await locks.async_add_code("Facu", code="482915")
    for clash in ("482915", "482910"):
        # the same code, and the emergency code of the first one
        with pytest.raises(CodeError):
            await locks.async_add_code("Other", code=clash)
    # and a code whose own emergency code is another's code
    await locks.async_add_code("Third", code="555551")
    with pytest.raises(CodeError):
        await locks.async_add_code("Fourth", code="555550")
    # and a code that differs from another only in its last digit: they would share an emergency code
    with pytest.raises(CodeError):
        await locks.async_add_code("Fifth", code="555552")


async def test_no_free_slot(hass, zwave, sent):
    locks = await start(hass, slots=2)
    await locks.async_add_code("A", code="111111")
    await locks.async_add_code("B", code="222222")
    with pytest.raises(CodeError) as error:
        await locks.async_add_code("C", code="333333")
    assert error.value.key == "no_free_slot"


async def test_a_failing_lock_takes_back_what_was_programmed(hass, sent):
    async_mock_service(hass, "zwave_js", "set_lock_usercode")
    clear_calls = async_mock_service(hass, "zwave_js", "clear_lock_usercode")
    locks = await start(hass)
    original = locks._call

    async def flaky(service, **data):
        if service == "set_lock_usercode" and data["entity_id"] == KITCHEN:
            raise HomeAssistantError("unreachable")
        await original(service, **data)

    locks._call = flaky
    with pytest.raises(HomeAssistantError):
        await locks.async_add_code("Facu", code="482915")
    assert locks.codes == []
    assert {(call.data["entity_id"], call.data["code_slot"]) for call in clear_calls} == {(FRONT, 1), (FRONT, 201)}


async def test_deleting_a_code_clears_both_slots(hass, zwave, sent):
    locks = await start(hass)
    item = await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    await locks.async_delete_code(item["id"])
    assert locks.codes == []
    assert [(call.data["entity_id"], call.data["code_slot"]) for call in zwave.clear] == [(FRONT, 1), (FRONT, 201)]
    with pytest.raises(CodeError):
        await locks.async_delete_code(item["id"])


async def test_a_code_that_cannot_be_cleared_stays_in_the_list(hass, sent):
    async_mock_service(hass, "zwave_js", "set_lock_usercode")
    async_mock_service(hass, "zwave_js", "clear_lock_usercode")
    locks = await start(hass)
    item = await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    locks._call = AsyncMock(side_effect=HomeAssistantError("unreachable"))
    with pytest.raises(HomeAssistantError):
        await locks.async_delete_code(item["id"])
    assert len(locks.codes) == 1


async def test_a_temporary_code_expires_and_is_removed(hass, zwave, sent, clock):
    locks = await start(hass)
    await locks.async_add_code("Plumber", "temporary", code="286641", lock_ids=[FRONT], hours=1)
    await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    await clock(3601)
    assert [code["name"] for code in locks.codes] == ["Facu"]
    assert (FRONT, 1) in [(call.data["entity_id"], call.data["code_slot"]) for call in zwave.clear]
    assert locks.events[0]["kind"] == "expired" and locks.events[0]["who"] == "Plumber"


async def test_an_expired_code_is_removed_on_start(hass, zwave, sent):
    locks = await start(hass)
    item = await locks.async_add_code("Plumber", "temporary", code="286641", lock_ids=[FRONT], hours=1)
    item["expires"] = (dt_util.utcnow() - timedelta(minutes=1)).isoformat()
    await locks._async_expire(None)
    assert locks.codes == []


async def test_a_temporary_code_needs_a_future_time(hass, zwave, sent):
    locks = await start(hass)
    with pytest.raises(CodeError):
        await locks.async_add_code("Plumber", "temporary", code="286641")
    with pytest.raises(CodeError):
        await locks.async_add_code("Plumber", "temporary", code="286641", until="2001-01-01T00:00:00+00:00")


async def test_the_codes_survive_a_restart(hass, zwave, sent, hass_storage):
    locks = await start(hass)
    await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    await locks.async_stop()
    again = await start(hass)
    assert [code["name"] for code in again.codes] == ["Facu"]
    assert again.codes[0]["code"] == "482915"


# --- who opened ---------------------------------------------------------------


async def test_a_keypad_unlock_names_the_code(hass, zwave, sent):
    locks = await start(hass)
    await locks.async_add_code("Delfi", code="730284", lock_ids=[FRONT])
    zwave_event(hass, FRONT, 6, 1)
    await hass.async_block_till_done()
    event = locks.events[0]
    assert (event["kind"], event["how"], event["who"], event["lock"]) == ("unlock", "keypad", "Delfi", "front_door")
    assert locks.last_open is not None
    sent.assert_not_awaited()


async def test_the_emergency_code_sends_a_security_notification(hass, zwave, sent):
    locks = await start(hass)
    await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    zwave_event(hass, FRONT, 6, 201)
    await hass.async_block_till_done()
    event = locks.events[0]
    assert (event["kind"], event["who"], event["notified"]) == ("emergency", "Facu", True)
    sent.assert_awaited_once()
    payload = sent.await_args.args[0]
    assert payload["type"] == "security"
    assert payload["actor"] == "Facu"
    assert payload["view"] == "locks"
    assert "Front Door" in payload["message"]


async def test_the_emergency_code_works_for_any_code(hass, zwave, sent):
    locks = await start(hass)
    await locks.async_add_code("Facu", code="482915")
    await locks.async_add_code("Plumber", "temporary", code="286641", hours=2)
    zwave_event(hass, KITCHEN, 6, 202)
    await hass.async_block_till_done()
    assert locks.events[0]["kind"] == "emergency" and locks.events[0]["who"] == "Plumber"


async def test_no_notify_view_means_no_emergency_notification(hass, zwave, sent):
    locks = await start(hass, notify_view=None) if False else AnnikaLocks(hass, LOCKS_SCHEMA({"locks": config()["locks"]}))
    locks._device_id = lambda lock: DEVICES[lock.entity]
    await locks.async_start()
    await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    zwave_event(hass, FRONT, 6, 201)
    await hass.async_block_till_done()
    sent.assert_not_awaited()
    assert locks.events[0]["kind"] == "emergency" and locks.events[0]["notified"] is False


async def test_an_unknown_code_is_not_the_emergency_one(hass, zwave, sent):
    locks = await start(hass)
    zwave_event(hass, FRONT, 6, 4)
    await hass.async_block_till_done()
    assert (locks.events[0]["kind"], locks.events[0]["who"], locks.events[0]["slot"]) == ("unknown", None, 4)
    sent.assert_not_awaited()


@pytest.mark.parametrize(
    ("event", "kind", "how"),
    [(1, "lock", "manual"), (2, "unlock", "manual"), (5, "lock", "keypad"), (9, "lock", "auto")],
)
async def test_the_other_ways_a_lock_says_it_moved(hass, zwave, sent, event, kind, how):
    locks = await start(hass)
    zwave_event(hass, FRONT, event)
    await hass.async_block_till_done()
    assert (locks.events[0]["kind"], locks.events[0]["how"]) == (kind, how)


async def test_the_event_label_is_enough_when_there_is_no_number(hass, zwave, sent):
    locks = await start(hass)
    hass.bus.async_fire(
        "zwave_js_notification",
        {"device_id": DEVICES[FRONT], "label": "Access Control", "event_label": "Keypad unlock operation"},
    )
    await hass.async_block_till_done()
    assert (locks.events[0]["kind"], locks.events[0]["how"]) == ("unlock", "keypad")


async def test_a_lock_that_is_not_ours_is_ignored(hass, zwave, sent):
    locks = await start(hass)
    hass.bus.async_fire("zwave_js_notification", {"device_id": "other", "event": 6, "parameters": {"userId": 1}})
    await hass.async_block_till_done()
    assert locks.events == []


async def test_a_state_change_that_zwave_described_is_one_event(hass, zwave, sent, clock):
    locks = await start(hass)
    await locks.async_add_code("Delfi", code="730284", lock_ids=[FRONT])
    zwave_event(hass, FRONT, 6, 1)
    hass.states.async_set(FRONT, "unlocked")
    await clock(ZWAVE_WAIT + 1)
    assert len([event for event in locks.events if event["lock"] == "front_door"]) == 1


async def test_a_change_nobody_described_is_an_opening_of_nobody_in_particular(hass, zwave, sent, clock):
    locks = await start(hass)
    hass.states.async_set(FRONT, "unlocked")
    await clock(ZWAVE_WAIT + 1)
    event = locks.events[0]
    assert (event["kind"], event["how"], event["who"]) == ("unlock", "unknown", None)


async def test_the_app_is_named_for_the_doors_it_opens(hass, zwave, sent, clock):
    locks = await start(hass)
    action = SimpleNamespace(
        domain="lock", service="unlock", entity_ids=[FRONT], at=dt_util.utcnow(), actor=SimpleNamespace(name="Facu")
    )
    hass.data["annika_actor"] = {"last_action": SimpleNamespace(action=action)}
    hass.states.async_set(FRONT, "unlocked")
    await clock(ZWAVE_WAIT + 1)
    event = locks.events[0]
    assert (event["how"], event["who"]) == ("app", "Facu")


# --- the alarm ------------------------------------------------------------------


async def test_the_rule_is_off_until_it_is_turned_on(hass, zwave, sent):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel()
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_not_called()
    assert locks.rule["enabled"] is False


async def test_an_unlock_disarms_the_alarm_and_says_so(hass, zwave, sent, clock):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel()
    locks.set_rule(enabled=True)
    await locks.async_add_code("Delfi", code="730284", lock_ids=[FRONT])
    zwave_event(hass, FRONT, 6, 1)
    hass.states.async_set(FRONT, "unlocked")
    await clock(ZWAVE_WAIT + 1)
    stub.disarm.assert_called_once_with(skip_code=True, source="locks")
    event = locks.events[0]
    assert event["who"] == "Delfi" and event["disarmed"] is True
    # The alarm says it was disarmed itself: the rule sends nothing of its own.
    sent.assert_not_awaited()


async def test_a_fingerprint_disarms_too(hass, zwave, sent, clock):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel()
    locks.set_rule(enabled=True)
    hass.states.async_set(KITCHEN, "unlocked")
    await clock(ZWAVE_WAIT + 1)
    stub.disarm.assert_called_once()
    assert locks.events[0]["how"] == "unknown" and locks.events[0]["disarmed"] is True



async def test_it_disarms_while_the_alarm_counts_down(hass, zwave, sent):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel(state="pending")
    locks.set_rule(enabled=True)
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_called_once()


@pytest.mark.parametrize("state", ["disarmed", "arming"])
async def test_it_leaves_a_quiet_alarm_alone(hass, zwave, sent, state):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel(state=state, mode=None)
    locks.set_rule(enabled=True)
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_not_called()


async def test_only_the_chosen_modes(hass, zwave, sent):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel(state="armed_night", mode="night")
    locks.set_rule(enabled=True, modes=["away"])
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_not_called()
    locks.set_rule(modes=["away", "night"])
    hass.states.async_set(FRONT, "locked")
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_called_once()


async def test_only_the_chosen_locks(hass, zwave, sent):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel()
    locks.set_rule(enabled=True, locks=[FRONT])
    hass.states.async_set(KITCHEN, "unlocked")
    await hass.async_block_till_done()
    stub.disarm.assert_not_called()


async def test_no_alarm_panel_is_not_an_error(hass, zwave, sent):
    locks = await start(hass)
    locks.set_rule(enabled=True)
    hass.states.async_set(FRONT, "unlocked")
    await hass.async_block_till_done()


async def test_the_test_only_logs_and_touches_nothing(hass, zwave, sent):
    locks = await start(hass)
    stub = hass.data[DATA_ALARM_PANEL] = panel()
    locks.set_rule(enabled=True)
    locks.test_rule()
    await hass.async_block_till_done()
    sent.assert_not_awaited()
    stub.disarm.assert_not_called()
    assert locks.events[0]["kind"] == "test"


def test_the_rule_validates(hass):
    locks = AnnikaLocks(hass, config())
    with pytest.raises(CodeError):
        locks.set_rule(modes=["panic"])
    with pytest.raises(CodeError):
        locks.set_rule(locks=["lock.unknown"])


# --- lock when closed ----------------------------------------------------------


async def close_the_door(hass):
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()


async def test_the_lock_locks_itself_after_its_door_closes(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], close_enabled=True, close_seconds=20)
    hass.states.async_set(FRONT, "unlocked")
    await close_the_door(hass)
    await clock(19)
    assert zwave.lock == []
    await clock(2)
    assert [call.data["entity_id"] for call in zwave.lock] == [FRONT]
    hass.states.async_set(FRONT, "locked")
    await clock(ZWAVE_WAIT + 1)
    event = locks.events[0]
    assert (event["kind"], event["how"]) == ("lock", "close")


async def test_a_door_that_opens_again_cancels_it(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], close_enabled=True, close_seconds=20)
    hass.states.async_set(FRONT, "unlocked")
    await close_the_door(hass)
    hass.states.async_set(DOOR, "on")
    await clock(30)
    assert zwave.lock == []


async def test_locking_by_hand_cancels_it(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], close_enabled=True, close_seconds=20)
    hass.states.async_set(FRONT, "unlocked")
    await close_the_door(hass)
    hass.states.async_set(FRONT, "locked")
    await clock(30)
    assert zwave.lock == []


async def test_it_does_nothing_when_it_is_off_or_the_lock_is_locked(hass, zwave, sent, clock):
    locks = await start(hass)
    hass.states.async_set(FRONT, "unlocked")
    await close_the_door(hass)
    await clock(60)
    assert zwave.lock == []
    locks.set_lock_settings(locks.locks[0], close_enabled=True, close_seconds=20)
    hass.states.async_set(FRONT, "locked")
    await close_the_door(hass)
    await clock(60)
    assert zwave.lock == []


async def test_turning_it_off_cancels_a_countdown(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], close_enabled=True, close_seconds=20)
    hass.states.async_set(FRONT, "unlocked")
    await close_the_door(hass)
    locks.set_lock_settings(locks.locks[0], close_enabled=False)
    await clock(30)
    assert zwave.lock == []


def test_the_seconds_are_kept_inside_their_limits(hass):
    locks = AnnikaLocks(hass, config())
    locks.set_lock_settings(locks.locks[0], close_seconds=1)
    assert locks.locks[0].close_seconds == 5
    locks.set_lock_settings(locks.locks[0], close_seconds=100000)
    assert locks.locks[0].close_seconds == 600


async def open_the_door(hass):
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()


async def test_a_door_left_open_is_told_after_its_seconds(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], open_enabled=True, open_seconds=30)
    await open_the_door(hass)
    await clock(29)
    sent.assert_not_awaited()
    await clock(2)
    sent.assert_awaited_once()
    payload = sent.await_args.args[0]
    assert payload["type"] == "info" and payload["view"] == "locks"
    assert "Front Door" in payload["message"] and "30 s" in payload["message"]
    event = locks.events[0]
    assert (event["kind"], event["lock"], event["notified"]) == ("left_open", "front_door", True)
    await clock(300)
    sent.assert_awaited_once()


async def test_a_door_that_closes_in_time_is_not_told(hass, zwave, sent, clock):
    locks = await start(hass)
    locks.set_lock_settings(locks.locks[0], open_enabled=True, open_seconds=30)
    await open_the_door(hass)
    await clock(20)
    hass.states.async_set(DOOR, "off")
    await clock(60)
    sent.assert_not_awaited()
    assert locks.events == []


async def test_it_says_nothing_when_it_is_off_and_stops_when_turned_off(hass, zwave, sent, clock):
    locks = await start(hass)
    await open_the_door(hass)
    await clock(300)
    sent.assert_not_awaited()
    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()
    locks.set_lock_settings(locks.locks[0], open_enabled=True, open_seconds=30)
    await open_the_door(hass)
    locks.set_lock_settings(locks.locks[0], open_enabled=False)
    await clock(60)
    sent.assert_not_awaited()


async def test_turning_it_on_with_the_door_already_open_starts_the_count(hass, zwave, sent, clock):
    locks = await start(hass)
    await open_the_door(hass)
    locks.set_lock_settings(locks.locks[0], open_enabled=True, open_seconds=30)
    await clock(31)
    sent.assert_awaited_once()


async def test_a_door_left_open_without_a_view_is_only_logged(hass, zwave, sent, clock):
    locks = AnnikaLocks(hass, LOCKS_SCHEMA({"locks": config()["locks"]}))
    locks._device_id = lambda lock: DEVICES[lock.entity]
    hass.states.async_set(FRONT, "locked")
    hass.states.async_set(DOOR, "off")
    await locks.async_start()
    locks.set_lock_settings(locks.locks[0], open_enabled=True, open_seconds=30)
    await open_the_door(hass)
    await clock(31)
    sent.assert_not_awaited()
    assert locks.events[0]["kind"] == "left_open" and locks.events[0]["notified"] is False


def test_the_open_seconds_are_kept_inside_their_limits(hass):
    locks = AnnikaLocks(hass, config())
    locks.set_lock_settings(locks.locks[0], open_seconds=1)
    assert locks.locks[0].open_seconds == 10
    locks.set_lock_settings(locks.locks[0], open_seconds=100000)
    assert locks.locks[0].open_seconds == 3600


# --- what the card reads --------------------------------------------------------


async def test_attributes(hass, zwave, sent):
    locks = await start(hass)
    hass.data[DATA_ALARM_PANEL] = panel()
    await locks.async_add_code("Facu", code="482915", lock_ids=[FRONT])
    attrs = locks.attributes()
    assert attrs["config"]["slots"] == 10 and attrs["config"]["offset"] == 200
    assert attrs["config"]["rule"]["available"] is True
    assert attrs["config"]["modes"] == ["away", "night", "vacation"]
    front = attrs["config"]["locks"][0]
    assert front["entity"] == FRONT and front["sensor"] == DOOR
    assert front["settings"] == {
        "hold": True, "close": False, "seconds": 30, "open": False, "open_seconds": 60,
    }
    assert attrs["codes"][0]["code"] == "482915"


async def test_the_sensor_the_settings_and_the_services(hass, zwave, sent):
    assert await async_setup_component(hass, "sensor", {})
    assert await async_setup_component(hass, "switch", {})
    assert await async_setup_component(hass, "number", {})
    locks = AnnikaLocks(hass, config())
    locks._device_id = lambda lock: DEVICES[lock.entity]
    hass.data[DATA_LOCKS] = locks
    hass.config.components.add(DOMAIN)
    hass.states.async_set(FRONT, "locked")
    hass.states.async_set(KITCHEN, "locked")
    hass.states.async_set(DOOR, "off")
    for platform in ("sensor", "switch", "number"):
        await async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_LOCKS}, {})
    await hass.async_block_till_done()

    entity = "sensor.annika_locks"
    state = hass.states.get(entity)
    assert state is not None
    # The settings are entities, and the sensor names them for the card.
    entities = state.attributes["config"]["locks"][0]["entities"]
    assert entities == {
        "hold": "switch.front_door_hold_to_unlock",
        "close": "switch.front_door_lock_when_closed",
        "seconds": "number.front_door_lock_when_closed_after",
        "open": "switch.front_door_notify_when_left_open",
        "open_seconds": "number.front_door_notify_when_left_open_after",
    }
    assert hass.states.get(entities["hold"]).state == "on"
    assert hass.states.get(entities["close"]).state == "off"
    assert float(hass.states.get(entities["seconds"]).state) == 30

    call = lambda service, **data: hass.services.async_call(  # noqa: E731
        DOMAIN, service, {"entity_id": entity, **data}, blocking=True
    )
    await hass.services.async_call("switch", "turn_off", {"entity_id": entities["hold"]}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": entities["close"]}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entities["seconds"], "value": 45}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": entities["open"]}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entities["open_seconds"], "value": 90}, blocking=True
    )
    settings = hass.states.get(entity).attributes["config"]["locks"][0]["settings"]
    assert settings == {"hold": False, "close": True, "seconds": 45, "open": True, "open_seconds": 90}

    await call("add_lock_code", name="Facu", code="482915", locks=[FRONT])
    await call("add_lock_code", name="Plumber", type="temporary", hours=2, locks=[KITCHEN])
    codes = hass.states.get(entity).attributes["codes"]
    assert [code["name"] for code in codes] == ["Facu", "Plumber"]
    assert codes[1]["type"] == "temporary" and codes[1]["expires"]

    await call("set_lock_rule", enabled=True, modes=["away"], locks=[FRONT])
    rule = hass.states.get(entity).attributes["config"]["rule"]
    assert rule["enabled"] is True and rule["modes"] == ["away"] and rule["locks"] == ["front_door"]

    await call("test_lock_rule")
    assert hass.states.get(entity).attributes["events"][0]["kind"] == "test"

    await call("delete_lock_code", id=codes[0]["id"])
    assert [code["name"] for code in hass.states.get(entity).attributes["codes"]] == ["Plumber"]

    with pytest.raises(ServiceValidationError):
        await call("add_lock_code", name="Bad", code="482910")
    with pytest.raises(ServiceValidationError):
        await call("delete_lock_code", id="nope")
    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await call("set_lock_rule", modes=["panic"])


async def test_the_codes_are_not_recorded_in_the_history():
    from custom_components.annika.locks_entities import AnnikaLocksSensor

    assert {"codes", "config", "events"} <= AnnikaLocksSensor._unrecorded_attributes
