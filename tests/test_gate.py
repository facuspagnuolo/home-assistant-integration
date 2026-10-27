"""Tests for the Annika gate, against Home Assistant's real entity platforms and a simulated gate board."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
    setup_test_component_platform,
)
from homeassistant.core import State

from custom_components.annika import async_setup_gate
from custom_components.annika import gate as gate_module
from custom_components.annika import gate_entities, gate_relay
from custom_components.annika.const import DOMAIN
from custom_components.annika.gate import (
    CLOSING,
    DATA_GATE,
    GATE_SCHEMA,
    IDLE,
    OPENING,
    AnnikaGate,
    unique_auto_off,
    unique_calibrate,
    unique_closed_inverted,
    unique_close_seconds,
    unique_cover,
    unique_moving,
    unique_notify,
    unique_open_seconds,
    unique_status,
    unique_threshold,
)

PULSE = "switch.porton"
POWER = "sensor.gate_pm_power"
CLOSED = "binary_sensor.gate_closed"
OPEN = "binary_sensor.gate_open"

CONFIG = {
    "name": "Gate",
    "pulse": PULSE,
    "power": POWER,
    "closed": CLOSED,
    "open": OPEN,
    "travel_seconds": 20,
}


class Clock:
    """The gate's idea of now. Home Assistant's own timers keep real time: freezing it would stall every wait."""

    def __init__(self) -> None:
        self.now = dt_util.utcnow()

    def tick(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Board:
    """The gate's motor board: one pulse starts it, stops it, or sends it the other way."""

    def __init__(self, hass: HomeAssistant, clock: Clock) -> None:
        self.hass = hass
        self.clock = clock
        self.pulses = 0
        self.moving: str | None = None
        self.position = 0.0
        self.last = CLOSING
        self.travel = 20.0
        self.responds = True
        self.run_watts = 130.0
        self.task: asyncio.Task | None = None

    def set_ends(self) -> None:
        self.hass.states.async_set(CLOSED, STATE_ON if self.position <= 0 else STATE_OFF)
        self.hass.states.async_set(OPEN, STATE_ON if self.position >= 100 else STATE_OFF)

    def at(self, position: float, last: str | None = None) -> None:
        """The gate rests at `position`, whatever the last direction was."""

        self.position = position
        self.last = last or (OPENING if position >= 50 else CLOSING)
        self.moving = None
        self.set_ends()
        self.hass.states.async_set(POWER, "0.0")

    def pulse(self) -> None:
        self.pulses += 1
        if not self.responds:
            return
        if self.moving:
            self.stop()
            return
        if self.position <= 0:
            direction = OPENING
        elif self.position >= 100:
            direction = CLOSING
        else:
            direction = CLOSING if self.last == OPENING else OPENING
        self.start(direction)

    def start(self, direction: str) -> None:
        self.moving = direction
        self.last = direction
        self.hass.states.async_set(CLOSED, STATE_OFF)
        self.hass.states.async_set(OPEN, STATE_OFF)
        self.hass.states.async_set(POWER, str(self.run_watts))

    def stop(self) -> None:
        if self.moving:
            # Stopped on the way: somewhere between the ends.
            self.position = 50.0
        self.moving = None
        self.hass.states.async_set(POWER, "0.0")
        self.hass.async_create_task(self._settle_soon())

    async def _settle_soon(self) -> None:
        # The gate takes a power that stays low for a while as a stop: let that while pass.
        await asyncio.sleep(0.01)
        self.clock.tick(2.5)
        async_fire_time_changed(self.hass, dt_util.utcnow() + timedelta(seconds=5))

    async def travel_to_end(self) -> None:
        """Let the motor run until it reaches the end, as it would on its own."""

        direction = self.moving
        assert direction is not None
        self.clock.tick(self.travel)
        self.position = 100.0 if direction == OPENING else 0.0
        self.moving = None
        self.set_ends()
        self.hass.states.async_set(POWER, "0.0")
        await self.settle()

    async def settle(self) -> None:
        await self.hass.async_block_till_done()
        async_fire_time_changed(self.hass, dt_util.utcnow() + timedelta(seconds=5))
        await self.hass.async_block_till_done()


class FakePulse(SwitchEntity):
    """The Shelly relay wired to the board's input."""

    _attr_should_poll = False
    _attr_unique_id = "porton"
    _attr_name = "porton"
    entity_id = PULSE

    def __init__(self, board: Board) -> None:
        self._attr_is_on = False
        self._board = board

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        self._board.pulse()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(AnnikaGate, "_now", lambda self: clock.now)
    return clock


@pytest.fixture
def sleeps(monkeypatch, clock) -> list[float]:
    """Waits are not slept: the clock moves by what the gate would have waited."""

    recorded: list[float] = []

    async def fake_sleep(self, seconds: float) -> None:
        recorded.append(seconds)
        clock.tick(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(AnnikaGate, "_sleep", fake_sleep)
    monkeypatch.setattr(gate_module, "MOTION_TIMEOUT", 0.3)
    return recorded


@pytest.fixture
def annika_events():
    with patch.object(gate_module.AnnikaEventClient, "async_send", AsyncMock()) as send:
        yield send


@pytest.fixture
async def board(hass: HomeAssistant, clock: Clock, sleeps) -> Board:
    board = Board(hass, clock)
    setup_test_component_platform(hass, "switch", [FakePulse(board)])
    assert await async_setup_component(hass, "switch", {"switch": [{"platform": "test"}]})
    board.at(0)
    await hass.async_block_till_done()
    return board


async def start(hass: HomeAssistant, config: dict | None = None) -> AnnikaGate:
    hass.config.components.add(DOMAIN)
    await async_setup_gate(hass, {DOMAIN: {"gate": config or CONFIG}})
    await hass.async_block_till_done()
    return hass.data[DATA_GATE]


def entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id


async def idle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)


# --- configuration ----------------------------------------------------------


def test_schema_defaults() -> None:
    config = GATE_SCHEMA({k: v for k, v in CONFIG.items() if k != "travel_seconds"})
    assert config["name"] == "Gate"
    assert config["pulse_ms"] == 700
    assert config["power_threshold"] == 40
    assert config["travel_seconds"] == 18


def test_end_sensors_can_be_switches() -> None:
    # A Shelly Uni's inputs often come as switches.
    config = GATE_SCHEMA({**CONFIG, "closed": "switch.uni_input_0", "open": "input_boolean.open"})
    assert config["closed"] == "switch.uni_input_0"
    with pytest.raises(vol.Invalid):
        GATE_SCHEMA({**CONFIG, "closed": "sensor.not_on_or_off"})


async def test_switch_end_sensors_are_read(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass, {**CONFIG, "closed": "switch.uni_input_0", "open": "switch.uni_input_1"})
    hass.states.async_set("switch.uni_input_0", STATE_ON)
    hass.states.async_set("switch.uni_input_1", STATE_OFF)
    await hass.async_block_till_done()
    assert gate.status == "closed"
    hass.states.async_set("switch.uni_input_0", STATE_OFF)
    hass.states.async_set("switch.uni_input_1", STATE_ON)
    await hass.async_block_till_done()
    assert gate.status == "open"


def test_schema_needs_four_different_entities() -> None:
    with pytest.raises(vol.Invalid):
        GATE_SCHEMA({**CONFIG, "open": CLOSED})
    with pytest.raises(vol.Invalid):
        GATE_SCHEMA({k: v for k, v in CONFIG.items() if k != "power"})


async def test_invalid_config_starts_nothing(hass: HomeAssistant) -> None:
    await async_setup_gate(hass, {DOMAIN: {"gate": {"pulse": PULSE}}})
    assert DATA_GATE not in hass.data


# --- what the entities are ---------------------------------------------------


async def test_entities_are_generated_from_the_four(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    registry = er.async_get(hass)
    for domain, unique_id in (
        ("cover", unique_cover(gate)),
        ("sensor", unique_status(gate)),
        ("binary_sensor", unique_moving(gate)),
        ("number", unique_open_seconds(gate)),
        ("number", unique_close_seconds(gate)),
        ("number", unique_threshold(gate)),
        ("button", unique_calibrate(gate)),
    ):
        assert registry.async_get_entity_id(domain, DOMAIN, unique_id) is not None
    # No notify_view, no notifications switch.
    assert registry.async_get_entity_id("switch", DOMAIN, unique_notify(gate)) is None


async def test_status_sensor_maps_its_entities(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    state = hass.states.get(entity(hass, "sensor", unique_status(gate)))
    assert state.state == "closed"
    entities = state.attributes["entities"]
    assert entities["cover"] == entity(hass, "cover", unique_cover(gate))
    assert entities["power"] == POWER
    assert entities["closed"] == CLOSED
    assert entities["open"] == OPEN
    assert entities["pulse"] == PULSE
    assert entities["notify"] is None
    assert entities["calibrate"] == entity(hass, "button", unique_calibrate(gate))
    assert state.attributes["open_seconds"] == 20
    assert state.attributes["threshold"] == 40


async def test_notifications_switch_with_notify_view(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass, {**CONFIG, "notify_view": "porton"})
    switch = hass.states.get(entity(hass, "switch", unique_notify(gate)))
    assert switch.state == STATE_ON
    status = hass.states.get(entity(hass, "sensor", unique_status(gate)))
    assert status.attributes["entities"]["notify"] == switch.entity_id


# --- reading the motor ---------------------------------------------------------


async def test_status_follows_the_end_sensors(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    assert gate.status == "closed"
    board.at(100)
    await hass.async_block_till_done()
    assert gate.status == "open"
    assert gate.position == 100
    board.at(40)
    await hass.async_block_till_done()
    assert gate.status == "stopped"
    # Nothing moved it that the gate saw: between the ends, it is somewhere in the middle.
    assert 1 <= gate.position <= 99


async def test_remote_control_opening_is_seen(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    assert gate.motion == OPENING
    assert gate.status == "opening"
    assert hass.states.get(entity(hass, "binary_sensor", unique_moving(gate))).state == STATE_ON

    clock.tick(10)
    assert 45 <= gate.position_now() <= 55
    cover = hass.states.get(entity(hass, "cover", unique_cover(gate)))
    assert cover.state == "opening"


async def test_remote_control_closing_from_open(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.at(100)
    await hass.async_block_till_done()
    board.start(CLOSING)
    await hass.async_block_till_done()
    assert gate.motion == CLOSING


async def test_a_dip_in_power_is_not_a_stop(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    hass.states.async_set(POWER, "2.0")
    await hass.async_block_till_done()
    clock.tick(1)
    hass.states.async_set(POWER, "130.0")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert gate.motion == OPENING


async def test_stopping_midway_records_the_move(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    clock.tick(10)
    board.stop()
    await board.settle()
    assert gate.motion == IDLE
    assert gate.status == "stopped"
    assert 45 <= gate.position <= 55
    assert gate.last_move["direction"] == OPENING
    assert gate.last_move["complete"] is False
    assert gate.last_direction == OPENING


async def test_a_full_run_ends_on_the_sensor(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    await board.travel_to_end()
    assert gate.status == "open"
    assert gate.position == 100
    assert gate.last_move["complete"] is True
    assert gate.last_move["seconds"] == pytest.approx(20, abs=0.5)


async def test_direction_after_a_stop_is_the_opposite(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    clock.tick(5)
    board.stop()
    await board.settle()
    board.start(CLOSING)
    await hass.async_block_till_done()
    assert gate.motion == CLOSING


# --- commands ------------------------------------------------------------------


async def test_open_from_closed_is_one_pulse(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    await hass.services.async_call("cover", "open_cover", {"entity_id": entity(hass, "cover", unique_cover(gate))}, blocking=True)
    await idle(hass)
    assert board.pulses == 1
    assert gate.motion == OPENING
    assert hass.states.get(PULSE).state == STATE_OFF


async def test_closing_after_stopping_while_opening_takes_three_pulses(
    hass: HomeAssistant, board: Board
) -> None:
    gate = await start(hass)
    board.at(50, last=CLOSING)
    await hass.async_block_till_done()
    # The next pulse would open it: it has to be stopped, then sent back.
    await gate.async_close()
    await idle(hass)
    assert board.pulses == 3
    assert board.moving == CLOSING
    assert gate.motion == CLOSING


async def test_going_to_a_position_stops_there(hass: HomeAssistant, board: Board, sleeps: list[float]) -> None:
    gate = await start(hass)
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": entity(hass, "cover", unique_cover(gate)), "position": 50},
        blocking=True,
    )
    await idle(hass)
    await board.settle()
    # One pulse to start, one to stop, the wait in between sized to the travel time.
    assert board.pulses == 2
    assert board.moving is None
    assert any(abs(seconds - (10 - gate.stop_latency)) < 0.5 for seconds in sleeps)
    assert 45 <= gate.position <= 55


async def test_already_there_does_nothing(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    await gate.async_close()
    await idle(hass)
    assert board.pulses == 0


async def test_the_last_command_wins(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    await gate.async_go_to(50)
    await gate.async_go_to(100)
    await idle(hass)
    assert board.moving == OPENING
    assert hass.states.get(PULSE).state == STATE_OFF


async def test_stop_pulses_a_moving_gate_once(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    await hass.services.async_call("cover", "stop_cover", {"entity_id": entity(hass, "cover", unique_cover(gate))}, blocking=True)
    await board.settle()
    assert board.pulses == 1
    assert gate.motion == IDLE


async def test_stop_does_nothing_when_it_is_not_moving(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.at(100)
    await hass.async_block_till_done()
    await gate.async_stop_movement()
    assert board.pulses == 0


async def test_a_gate_that_does_not_answer_is_reported_by_no_motion(
    hass: HomeAssistant, board: Board, caplog
) -> None:
    gate = await start(hass)
    board.responds = False
    await gate.async_open()
    await idle(hass)
    assert board.pulses == gate_module.MAX_PULSES
    assert hass.states.get(PULSE).state == STATE_OFF
    assert "no_motion" in caplog.text


# --- calibration -----------------------------------------------------------------


async def _run_both_ways(board: Board) -> None:
    """Each pulse from an end sends the motor across: let it arrive."""

    for _ in range(2):
        async with asyncio.timeout(5):
            while board.moving is None:
                await asyncio.sleep(0.005)
        await board.travel_to_end()


async def test_calibration_measures_both_ways(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.travel = 17.0
    runner = hass.async_create_task(_run_both_ways(board))
    await hass.services.async_call(
        "button", "press", {"entity_id": entity(hass, "button", unique_calibrate(gate))}, blocking=True
    )
    await idle(hass)
    await runner

    assert gate.calibration["status"] == "ok"
    # Halfway between the board at rest (0 W) and the motor (130 W).
    assert gate.threshold == 65
    assert float(hass.states.get(entity(hass, "number", unique_threshold(gate))).state) == 65
    assert gate.open_seconds == pytest.approx(17, abs=1)
    assert gate.close_seconds == pytest.approx(17, abs=1)
    opening = hass.states.get(entity(hass, "number", unique_open_seconds(gate)))
    assert float(opening.state) == pytest.approx(17, abs=1)


async def test_calibration_finds_the_threshold_for_a_small_motor(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.run_watts = 24.0
    runner = hass.async_create_task(_run_both_ways(board))
    await gate.async_calibrate()
    await idle(hass)
    await runner
    assert gate.calibration["status"] == "ok"
    assert gate.threshold == 12


async def test_calibration_ignores_what_the_board_reads_at_rest(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    # A board that idles at a few watts must not look like a motor to the calibration's own low threshold.
    hass.states.async_set(POWER, "5.4")
    await hass.async_block_till_done()
    assert gate.motion == IDLE
    runner = hass.async_create_task(_run_both_ways(board))
    await gate.async_calibrate()
    await idle(hass)
    await runner
    assert gate.calibration["status"] == "ok"
    assert gate.threshold > 30


async def test_calibration_fails_if_the_motor_draws_like_the_board_at_rest(
    hass: HomeAssistant, board: Board
) -> None:
    gate = await start(hass)
    board.run_watts = 8.0
    runner = hass.async_create_task(_run_both_ways(board))
    await gate.async_calibrate()
    await idle(hass)
    await runner
    assert gate.calibration["status"] == "failed"
    assert gate.calibration["message"] == "no_power"
    assert gate.threshold == 40


async def test_calibration_says_why_it_failed(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.responds = False
    await gate.async_calibrate()
    await idle(hass)
    assert gate.calibration["status"] == "failed"
    assert gate.calibration["message"] == "no_motion"
    state = hass.states.get(entity(hass, "sensor", unique_status(gate)))
    assert state.attributes["calibration"]["message"] == "no_motion"


# --- settings ----------------------------------------------------------------------


async def test_settings_change_the_rate(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity(hass, "number", unique_open_seconds(gate)), "value": 10},
        blocking=True,
    )
    assert gate.open_seconds == 10
    assert gate.rate(OPENING) == pytest.approx(10)


async def test_threshold_decides_what_is_moving(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    hass.states.async_set(POWER, "60.0")
    await hass.async_block_till_done()
    assert gate.motion == OPENING
    board.at(0)
    await board.settle()
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity(hass, "number", unique_threshold(gate)), "value": 100},
        blocking=True,
    )
    hass.states.async_set(POWER, "60.0")
    await hass.async_block_till_done()
    assert gate.motion == IDLE


async def test_settings_are_restored(hass: HomeAssistant, board: Board) -> None:
    gate_id = "number.gate_opening_time"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(gate_id, "13.5"),
                {
                    "native_max_value": 300,
                    "native_min_value": 2,
                    "native_step": 0.1,
                    "native_unit_of_measurement": "s",
                    "native_value": 13.5,
                },
            )
        ],
    )
    gate = await start(hass)
    assert gate.open_seconds == 13.5
    assert gate.close_seconds == 20


async def test_position_is_restored(hass: HomeAssistant) -> None:
    gate = AnnikaGate(hass, GATE_SCHEMA(CONFIG))
    gate.restore(37.0, OPENING)
    assert gate.position == 37.0
    assert gate.last_direction == OPENING
    gate.restore(500.0, "sideways")
    assert gate.position == 100.0
    assert gate.last_direction == OPENING


# --- events -------------------------------------------------------------------------


async def test_opening_sends_an_event_when_it_has_a_view(hass: HomeAssistant, board: Board, annika_events) -> None:
    await start(hass, {**CONFIG, "notify_view": "porton"})
    board.start(OPENING)
    await hass.async_block_till_done()
    await board.travel_to_end()
    annika_events.assert_awaited()
    assert annika_events.await_args.args[0]["view"] == "porton"


async def test_no_event_without_a_view(hass: HomeAssistant, board: Board, annika_events) -> None:
    await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    await board.travel_to_end()
    annika_events.assert_not_awaited()


async def test_notifications_switch_silences_events(hass: HomeAssistant, board: Board, annika_events) -> None:
    gate = await start(hass, {**CONFIG, "notify_view": "porton"})
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity(hass, "switch", unique_notify(gate))}, blocking=True
    )
    board.start(OPENING)
    await hass.async_block_till_done()
    await board.travel_to_end()
    annika_events.assert_not_awaited()


# --- sensor polarity ---------------------------------------------------------------


async def test_an_inverted_closed_sensor_reads_the_other_way(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass, {**CONFIG, "closed_inverted": True})
    # Wired the other way round: off is what "closed" looks like.
    hass.states.async_set(CLOSED, STATE_OFF)
    hass.states.async_set(OPEN, STATE_OFF)
    await hass.async_block_till_done()
    assert gate.status == "closed"
    assert gate.position == 0
    hass.states.async_set(CLOSED, STATE_ON)
    await hass.async_block_till_done()
    assert gate.status == "stopped"


async def test_unavailable_sensor_is_not_an_end_even_when_inverted(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass, {**CONFIG, "closed_inverted": True})
    hass.states.async_set(CLOSED, "unavailable")
    await hass.async_block_till_done()
    assert gate.closed_active is False


async def test_the_inversion_switches_flip_the_reading(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    assert gate.status == "closed"
    switch = entity(hass, "switch", unique_closed_inverted(gate))
    assert hass.states.get(switch).state == STATE_OFF
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert gate.closed_inverted is True
    assert gate.status == "stopped"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert gate.status == "closed"


async def test_the_inversion_is_restored(hass: HomeAssistant, board: Board) -> None:
    mock_restore_cache(hass, [State("switch.gate_invert_open_sensor", STATE_ON)])
    gate = await start(hass)
    assert gate.open_inverted is True
    assert gate.closed_inverted is False


# --- the relay's auto-off ------------------------------------------------------------


class FakeRelay:
    def __init__(self, seconds: float = 0.0) -> None:
        self.seconds = seconds
        self.fail = False

    async def async_get_auto_off(self) -> float:
        if self.fail:
            raise gate_relay.RelayError("unreachable")
        return self.seconds

    async def async_set_auto_off(self, seconds: float) -> None:
        self.seconds = seconds


async def test_auto_off_is_read_from_the_relay(hass: HomeAssistant, board: Board) -> None:
    relay = FakeRelay(1.5)
    with patch.object(gate_entities, "find_relay", return_value=relay):
        gate = await start(hass)
        auto_off = entity(hass, "number", unique_auto_off(gate))
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        assert float(hass.states.get(auto_off).state) == 1.5


async def test_auto_off_is_set_on_the_relay(hass: HomeAssistant, board: Board) -> None:
    relay = FakeRelay(0)
    with patch.object(gate_entities, "find_relay", return_value=relay):
        gate = await start(hass)
        auto_off = entity(hass, "number", unique_auto_off(gate))
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        await hass.services.async_call("number", "set_value", {"entity_id": auto_off, "value": 1.2}, blocking=True)
        assert relay.seconds == 1.2
        assert float(hass.states.get(auto_off).state) == 1.2


async def test_auto_off_is_unavailable_when_the_relay_is_not_a_shelly(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    assert hass.states.get(entity(hass, "number", unique_auto_off(gate))).state == "unavailable"
    state = hass.states.get(entity(hass, "sensor", unique_status(gate)))
    assert state.attributes["entities"]["auto_off"] == entity(hass, "number", unique_auto_off(gate))
    assert state.attributes["pulse_seconds"] == 0.7


async def test_auto_off_unreachable_relay_is_unavailable(hass: HomeAssistant, board: Board) -> None:
    relay = FakeRelay(1)
    relay.fail = True
    with patch.object(gate_entities, "find_relay", return_value=relay):
        gate = await start(hass)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        assert hass.states.get(entity(hass, "number", unique_auto_off(gate))).state == "unavailable"


async def test_the_relay_is_found_through_the_shelly_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="shelly", data={"host": "10.0.0.5", "gen": 3})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch", "shelly", "AABBCC-switch:1", suggested_object_id="porton", config_entry=entry
    )
    relay = gate_relay.find_relay(hass, "switch.porton")
    assert relay is not None
    assert (relay._host, relay._generation, relay._channel) == ("10.0.0.5", 3, 1)
    assert gate_relay.find_relay(hass, "switch.other") is None


async def test_shelly_gen2_auto_off_over_http(hass: HomeAssistant, aioclient_mock) -> None:
    relay = gate_relay.ShellyRelay(hass, "10.0.0.5", 3, 0)
    aioclient_mock.get("http://10.0.0.5/rpc/Switch.GetConfig", json={"auto_off": True, "auto_off_delay": 1.5})
    assert await relay.async_get_auto_off() == 1.5
    aioclient_mock.clear_requests()
    aioclient_mock.get("http://10.0.0.5/rpc/Switch.GetConfig", json={"auto_off": False, "auto_off_delay": 60})
    assert await relay.async_get_auto_off() == 0
    aioclient_mock.clear_requests()
    aioclient_mock.get("http://10.0.0.5/rpc/Switch.SetConfig", json={"restart_required": False})
    await relay.async_set_auto_off(1.2)
    query = aioclient_mock.mock_calls[0][1].query
    assert query["id"] == "0"
    assert json.loads(query["config"]) == {"auto_off": True, "auto_off_delay": 1.2}


async def test_shelly_gen1_auto_off_over_http(hass: HomeAssistant, aioclient_mock) -> None:
    relay = gate_relay.ShellyRelay(hass, "10.0.0.6", 1, 0)
    aioclient_mock.get("http://10.0.0.6/settings/relay/0", json={"auto_off": 2.0})
    assert await relay.async_get_auto_off() == 2.0
    await relay.async_set_auto_off(0)
    assert aioclient_mock.mock_calls[-1][1].query["auto_off"] == "0"


async def test_shelly_errors_become_relay_errors(hass: HomeAssistant, aioclient_mock) -> None:
    relay = gate_relay.ShellyRelay(hass, "10.0.0.5", 3, 0)
    aioclient_mock.get("http://10.0.0.5/rpc/Switch.GetConfig", status=401)
    with pytest.raises(gate_relay.RelayError, match="auth"):
        await relay.async_get_auto_off()
    aioclient_mock.clear_requests()
    aioclient_mock.get("http://10.0.0.5/rpc/Switch.GetConfig", exc=TimeoutError())
    with pytest.raises(gate_relay.RelayError):
        await relay.async_get_auto_off()


# --- the detour the board makes is not shown --------------------------------------------


async def test_opening_after_a_stop_never_shows_closing(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.at(50, last=OPENING)
    await hass.async_block_till_done()
    gate.last_direction, gate.position = OPENING, 50.0
    cover = entity(hass, "cover", unique_cover(gate))
    moving = entity(hass, "binary_sensor", unique_moving(gate))
    status = entity(hass, "sensor", unique_status(gate))
    seen: list[tuple[str, str, float | None]] = []

    def record(event) -> None:
        state = event.data["new_state"]
        if state is not None:
            seen.append((state.entity_id, state.state, state.attributes.get("current_position")))

    hass.bus.async_listen("state_changed", record)
    # The next pulse would close it: the board is sent that way first, stopped, then pulsed again.
    await hass.services.async_call("cover", "open_cover", {"entity_id": cover}, blocking=True)
    await idle(hass)
    await board.settle()

    assert board.pulses == 3
    assert board.moving == OPENING
    states = [(entity_id, state) for entity_id, state, _ in seen]
    assert (cover, "closing") not in states
    assert (status, "closing") not in states
    # It reads as opening, without a gap in which the gate looks idle.
    assert (cover, "opening") in states
    assert (moving, STATE_OFF) not in states
    positions = [position for entity_id, _, position in seen if entity_id == cover and position is not None]
    assert min(positions) >= 49
    # And the detour leaves nothing behind.
    assert gate.last_move is None


async def test_a_gate_that_never_answers_stops_looking_busy(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.responds = False
    await gate.async_open()
    await idle(hass)
    assert gate.shown_motion == IDLE
    assert hass.states.get(entity(hass, "cover", unique_cover(gate))).state == "closed"


# --- the remote control and the app on the same gate ---------------------------------------


async def test_the_app_can_reverse_a_run_started_with_the_remote(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    assert gate.motion == OPENING
    await gate.async_close()
    await idle(hass)
    await board.settle()
    # One pulse to stop it, one to send it back: the state followed the motor, not the commands.
    assert board.pulses == 2
    assert board.moving == CLOSING
    assert gate.motion == CLOSING


async def test_the_remote_can_stop_what_the_app_started(
    hass: HomeAssistant, board: Board, monkeypatch, sleeps: list[float]
) -> None:
    gate = await start(hass)
    original = AnnikaGate._sleep

    async def sleep_then_remote(self, seconds: float) -> None:
        await original(self, seconds)
        if seconds > 5 and board.moving:
            # Somebody presses the remote while the app waits to stop the gate at 50%.
            board.stop()
            await board.settle()

    monkeypatch.setattr(AnnikaGate, "_sleep", sleep_then_remote)
    await gate.async_go_to(50)
    await idle(hass)
    # The app sees it already stopped and does not pulse again (that would start it).
    assert board.pulses == 1
    assert board.moving is None
    assert gate.motion == IDLE


async def test_the_app_after_the_remote_stopped_it_halfway(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    clock.tick(9)
    board.stop()
    await board.settle()
    assert 40 <= gate.position <= 60
    # Its next pulse would close it; asking for "open" must still end up opening.
    await gate.async_open()
    await idle(hass)
    assert board.moving == OPENING
    assert gate.motion == OPENING


async def test_a_stale_direction_is_corrected_when_it_reaches_the_wrong_end(hass: HomeAssistant, board: Board) -> None:
    gate = await start(hass)
    # The gate was left halfway while Home Assistant was down: what it remembers is wrong.
    board.at(50, last=OPENING)
    await hass.async_block_till_done()
    gate.position, gate.last_direction = 50.0, CLOSING
    await gate.async_open()
    await idle(hass)
    # Believing it was opening, it was really closing: nothing in the power says which way.
    assert board.moving == CLOSING
    await board.travel_to_end()
    await idle(hass)
    # It reached the closed end instead: the sensors say so and the command is sent again.
    assert gate.status in ("opening", "open")
    assert board.moving == OPENING


# --- what the remote did, in the logbook -------------------------------------


def presses(hass: HomeAssistant, gate: AnnikaGate) -> list[str]:
    """The lines written on the cover for presses that did not come from the app."""

    cover = entity(hass, "cover", unique_cover(gate))
    return [event.data["message"] for event in lines if event.data.get("entity_id") == cover]


async def test_remote_presses_are_logged_with_what_they_did(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    global lines
    hass.config.language = "es"
    lines = async_capture_events(hass, "logbook_entry")
    gate = await start(hass)
    board.start(OPENING)
    await hass.async_block_till_done()
    clock.tick(10)
    board.stop()
    await board.settle()
    board.start(CLOSING)
    await hass.async_block_till_done()
    assert presses(hass, gate) == ["abierto (control remoto)", "detenido (control remoto)", "cerrado (control remoto)"]


async def test_presses_from_the_app_are_not_called_remote(hass: HomeAssistant, board: Board, clock: Clock) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    global lines
    lines = async_capture_events(hass, "logbook_entry")
    gate = await start(hass)
    cover = entity(hass, "cover", unique_cover(gate))
    await hass.services.async_call("cover", "open_cover", {"entity_id": cover}, blocking=True)
    await idle(hass)
    clock.tick(5)
    await hass.services.async_call("cover", "stop_cover", {"entity_id": cover}, blocking=True)
    await idle(hass)
    await board.settle()
    assert presses(hass, gate) == []
