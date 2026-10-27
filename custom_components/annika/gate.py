"""Annika gate: a motor driven by one pulse, with its position worked out from what it consumes.

The motor board of most gates has a single input: a pulse starts the gate, the
next one stops it, the next one starts it the other way. Nothing says which way
it is going or how far along it is, so Annika works that out from four things
the unit already has:

    annika:
      gate:
        name: Gate                      # optional
        pulse: switch.gate_pulse        # the relay wired to the board's pulse input
        power: sensor.gate_power        # the motor's consumption, in watts
        closed: binary_sensor.gate_closed
        open: binary_sensor.gate_open
        notify_view: gate               # optional: Annika events when it opens
                                        # and closes; the card's Notify tile turns
                                        # them on or off

* The motor is running while its consumption is over a threshold, whoever sent
  the pulse: Home Assistant, the remote, a wall button.
* A run goes the opposite way to the one before it, and always away from an end:
  from the closed sensor it can only open, from the open sensor only close.
* The position is the run's start plus the time it has been running over the
  time the whole way takes, which Annika measures (`button.gate_calibrate`) and
  the person can edit. The sensors are exact: every time one trips, the
  position is 0 or 100, so an estimate never drifts for more than one run.

`pulse_ms`, `power_threshold`, `settle_seconds`, `stop_latency` and
`travel_seconds` tune the above; their defaults suit most gates. The threshold
and the two travel times are entities, and what the person sets there wins from
then on and survives restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import voluptuous as vol

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_GATE = f"{DOMAIN}_gate"

OPENING = "opening"
CLOSING = "closing"
IDLE = "idle"

STATUS_CLOSED = "closed"
STATUS_OPENING = "opening"
STATUS_OPEN = "open"
STATUS_CLOSING = "closing"
STATUS_STOPPED = "stopped"
STATUS_CALIBRATING = "calibrating"
STATUSES = (
    STATUS_CLOSED,
    STATUS_OPENING,
    STATUS_OPEN,
    STATUS_CLOSING,
    STATUS_STOPPED,
    STATUS_CALIBRATING,
)

CALIBRATION_IDLE = "idle"
CALIBRATION_RUNNING = "running"
CALIBRATION_OK = "ok"
CALIBRATION_FAILED = "failed"

DEFAULT_THRESHOLD = 40.0
MAX_THRESHOLD = 5000.0
DEFAULT_TRAVEL_SECONDS = 18.0
MIN_TRAVEL_SECONDS = 2.0
MAX_TRAVEL_SECONDS = 300.0

# A target this close to where the gate is counts as already there.
POSITION_TOLERANCE = 2.0
# Pulses a command may spend getting the gate moving the right way: 1 from an
# end, 2 from a run the wrong way, 3 from a stop after a run the wrong way.
MAX_PULSES = 4
# How long a pulse may take to show in the consumption.
MOTION_TIMEOUT = 6.0
# A press that moves or stops the gate this soon after one of Annika's own pulses is Annika's.
OWN_PULSE_WINDOW = 6.0
# While calibrating, any draw above standby counts as the motor: the real threshold is what it finds.
CALIBRATION_THRESHOLD = 5.0
# The longest a run may last before it is taken as stuck.
MAX_RUN_SECONDS = 150.0


class GateError(Exception):
    """A command that could not finish. `key` says why, for the card and the logbook."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


# A Shelly Uni's inputs show up as binary sensors or as switches, depending on how they are set up: both say on or off.
END_SENSOR_DOMAINS = ["binary_sensor", "switch", "input_boolean"]


def _validate(config: dict) -> dict:
    entities = [config["pulse"], config["power"], config["closed"], config["open"]]
    if len(set(entities)) != len(entities):
        raise vol.Invalid("gate pulse, power, closed and open must be four different entities")
    return config


GATE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name", default="Gate"): cv.string,
            vol.Required("pulse"): cv.entity_domain("switch"),
            vol.Required("power"): cv.entity_domain("sensor"),
            vol.Required("closed"): cv.entity_domain(END_SENSOR_DOMAINS),
            vol.Required("open"): cv.entity_domain(END_SENSOR_DOMAINS),
            vol.Optional("closed_inverted", default=False): cv.boolean,
            vol.Optional("open_inverted", default=False): cv.boolean,
            vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
            vol.Optional("pulse_ms", default=700): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
            vol.Optional("power_threshold", default=DEFAULT_THRESHOLD): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=MAX_THRESHOLD)
            ),
            vol.Optional("settle_seconds", default=2.0): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=10)),
            vol.Optional("stop_latency", default=0.3): vol.All(vol.Coerce(float), vol.Range(min=0, max=3)),
            vol.Optional("travel_seconds", default=DEFAULT_TRAVEL_SECONDS): vol.All(
                vol.Coerce(float), vol.Range(min=MIN_TRAVEL_SECONDS, max=MAX_TRAVEL_SECONDS)
            ),
        }
    ),
    _validate,
)


@dataclass
class GateSettings:
    """What the person edits. `None` until the owning entity restored it."""

    open_seconds: float | None = None
    close_seconds: float | None = None
    threshold: float | None = None
    notify: bool | None = None
    closed_inverted: bool | None = None
    open_inverted: bool | None = None


TEXTS = {
    "en": {
        "opening": "{name} opening",
        "closing": "{name} closing",
        "opened": "{name} open",
        "closed": "{name} closed",
        "stopped": "{name} stopped at {percent}%",
        "remote_opening": "opened (remote control)",
        "remote_closing": "closed (remote control)",
        "remote_stopped": "stopped (remote control)",
        "calibrated": "{name} calibrated: {open_seconds} s opening, {close_seconds} s closing, {threshold} W threshold",
        "calibration_failed": "{name} calibration failed: {reason}",
        "reason_no_closed": "it never reached the closed sensor",
        "reason_no_motion": "the pulse did not move it",
        "reason_wrong_direction": "it went the wrong way",
        "reason_never_stopped": "it never stopped",
        "reason_stopped_early": "it stopped before the end sensor",
        "reason_too_short": "the run was too short to measure",
        "reason_no_power": "the motor drew no more than the board at rest",
        "reason_cancelled": "it was cancelled",
        "event_opened": "🚪 {name} open",
        "event_closed": "🚪 {name} closed",
    },
    "es": {
        "opening": "{name} abriendo",
        "closing": "{name} cerrando",
        "opened": "{name} abierto",
        "closed": "{name} cerrado",
        "stopped": "{name} detenido al {percent}%",
        "remote_opening": "abierto (control remoto)",
        "remote_closing": "cerrado (control remoto)",
        "remote_stopped": "detenido (control remoto)",
        "calibrated": "{name} calibrado: {open_seconds} s abriendo, {close_seconds} s cerrando, umbral de {threshold} W",
        "calibration_failed": "Falló la calibración de {name}: {reason}",
        "reason_no_closed": "no llegó al sensor de cerrado",
        "reason_no_motion": "el pulso no lo movió",
        "reason_wrong_direction": "fue en el sentido contrario",
        "reason_never_stopped": "nunca se detuvo",
        "reason_stopped_early": "se detuvo antes del sensor del extremo",
        "reason_too_short": "el recorrido fue muy corto para medirlo",
        "reason_no_power": "el motor no consumió más que la placa en reposo",
        "reason_cancelled": "se canceló",
        "event_opened": "🚪 {name} abierto",
        "event_closed": "🚪 {name} cerrado",
    },
}


class AnnikaGate:
    """The state of the gate and the commands that move it."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self.name: str = config["name"]
        self.pulse_switch: str = config["pulse"]
        self.power_sensor: str = config["power"]
        self.closed_sensor: str = config["closed"]
        self.open_sensor: str = config["open"]
        self.notify_view: str | None = config.get("notify_view")
        self.pulse_seconds: float = config["pulse_ms"] / 1000
        self.settle_seconds: float = config["settle_seconds"]
        self.stop_latency: float = config["stop_latency"]

        self.settings = GateSettings()
        # Where the gate is, 0 closed to 100 open. While it moves this is where the run began:
        # `position_now` has the live value.
        self.position: float = 0.0
        self.last_direction: str = CLOSING
        self.motion: str = IDLE
        self.moving_since: datetime | None = None
        self.start_position: float = 0.0
        self.last_move: dict | None = None
        self.calibration: dict = {"status": CALIBRATION_IDLE, "message": None, "at": None}

        self._started = False
        self._listeners: list[Callable[[], None]] = []
        self._position_listeners: list[Callable[[], None]] = []
        self._waiters: list[tuple[Callable[[], bool], asyncio.Future]] = []
        self._unsubscribers: list[Callable[[], None]] = []
        self._unsettle: Callable[[], None] | None = None
        self._below_since: datetime | None = None
        self._untick: Callable[[], None] | None = None
        self._task: asyncio.Task | None = None
        self._pulsed_at: datetime | None = None
        # Where the command being run is taking the gate. The board may have to be sent the wrong way first
        # (after a stop its next pulse reverses): that run is a correction, and nobody is shown it.
        self._command_direction: str | None = None
        # An end the last command was sent to. If the gate turns out to have gone to the other one (what it
        # believed about its direction was stale), the command is repeated once, with the sensors' word for where it is.
        self._goal: float | None = None
        self._goal_retried = False
        # Power readings while calibrating, tagged "idle" or "run": the threshold is found between them.
        self._samples: list[tuple[str, float]] | None = None
        self._phase: str | None = None

    # --- what the entities hold ----------------------------------------------

    @property
    def open_seconds(self) -> float:
        return self.settings.open_seconds or self.config["travel_seconds"]

    @property
    def close_seconds(self) -> float:
        return self.settings.close_seconds or self.config["travel_seconds"]

    @property
    def threshold(self) -> float:
        return self.settings.threshold or self.config["power_threshold"]

    def rate(self, direction: str) -> float:
        """Points of position per second."""

        seconds = self.open_seconds if direction == OPENING else self.close_seconds
        return 100 / max(seconds, MIN_TRAVEL_SECONDS)

    # --- change notification -------------------------------------------------

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def subscribe_position(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Called every second while the gate moves, for what shows the position."""

        self._position_listeners.append(listener)

        def remove() -> None:
            if listener in self._position_listeners:
                self._position_listeners.remove(listener)

        return remove

    @callback
    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()
        for predicate, future in list(self._waiters):
            if not future.done() and predicate():
                future.set_result(True)

    @callback
    def settings_changed(self) -> None:
        """An entity changed a setting: a new threshold may change what the motor is doing."""

        if self._started:
            self._sync_ends()
            self._apply_power(self.hass.states.get(self.power_sensor))
        self.notify()

    # --- what is known right now ---------------------------------------------

    def _now(self) -> datetime:
        return dt_util.utcnow()

    def _state(self, entity_id: str) -> State | None:
        return self.hass.states.get(entity_id)

    def _is_on(self, entity_id: str) -> bool:
        state = self._state(entity_id)
        return state is not None and state.state == STATE_ON

    def _is_known(self, entity_id: str) -> bool:
        state = self._state(entity_id)
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def closed_inverted(self) -> bool:
        inverted = self.settings.closed_inverted
        return self.config["closed_inverted"] if inverted is None else inverted

    @property
    def open_inverted(self) -> bool:
        inverted = self.settings.open_inverted
        return self.config["open_inverted"] if inverted is None else inverted

    def _is_at(self, entity_id: str, inverted: bool) -> bool:
        """Whether an end sensor says the gate is there, once its polarity is taken into account."""

        return self._is_known(entity_id) and self._is_on(entity_id) != inverted

    @property
    def closed_active(self) -> bool:
        return self._is_at(self.closed_sensor, self.closed_inverted)

    @property
    def open_active(self) -> bool:
        return self._is_at(self.open_sensor, self.open_inverted)

    @property
    def available(self) -> bool:
        return self._is_known(self.pulse_switch)

    @property
    def is_closed(self) -> bool:
        return self.motion == IDLE and self.closed_active

    @property
    def status(self) -> str:
        if self.calibration["status"] == CALIBRATION_RUNNING:
            return STATUS_CALIBRATING
        shown = self.shown_motion
        if shown == OPENING:
            return STATUS_OPENING
        if shown == CLOSING:
            return STATUS_CLOSING
        if self.closed_active:
            return STATUS_CLOSED
        if self.open_active:
            return STATUS_OPEN
        return STATUS_STOPPED

    def _estimate(self, direction: str, start: float, seconds: float) -> float:
        sign = 1 if direction == OPENING else -1
        return min(max(start + sign * seconds * self.rate(direction), 0.0), 100.0)

    @property
    def shown_motion(self) -> str:
        """What people are shown: where a command is taking the gate, not the detours the board makes on the way."""

        return self._command_direction or self.motion

    def _is_correction(self, direction: str) -> bool:
        return self._command_direction is not None and direction != self._command_direction

    def position_now(self) -> float:
        if self.motion == IDLE or self.moving_since is None:
            return self.position
        if self._is_correction(self.motion):
            return self.start_position
        if self.motion == CLOSING and self.closed_active:
            return 0.0
        if self.motion == OPENING and self.open_active:
            return 100.0
        seconds = (self._now() - self.moving_since).total_seconds()
        return self._estimate(self.motion, self.start_position, seconds)

    # --- lifecycle -----------------------------------------------------------

    @callback
    def restore(self, position: float | None, last_direction: str | None) -> None:
        """The status sensor hands back where the gate was when Home Assistant stopped."""

        if position is not None:
            self.position = min(max(float(position), 0.0), 100.0)
        if last_direction in (OPENING, CLOSING):
            self.last_direction = last_direction

    async def async_start(self) -> None:
        self._unsubscribers.append(
            async_track_state_change_event(self.hass, [self.power_sensor], self._power_changed)
        )
        self._unsubscribers.append(
            async_track_state_change_event(
                self.hass, [self.closed_sensor, self.open_sensor], self._end_changed
            )
        )
        self._started = True
        self._sync_ends()
        self._apply_power(self._state(self.power_sensor))
        self.notify()

    async def async_stop(self, _event: Event | None = None) -> None:
        self._started = False
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._cancel_settle()
        self._stop_ticking()
        await self._async_cancel()

    # --- the sensors ---------------------------------------------------------

    @callback
    def _sync_ends(self) -> None:
        """Take the position from the end sensors, which are exact."""

        if self.motion != IDLE:
            return
        if self.closed_active:
            self.position, self.last_direction = 0.0, CLOSING
        elif self.open_active:
            self.position, self.last_direction = 100.0, OPENING
        elif self._is_known(self.closed_sensor) and self._is_known(self.open_sensor):
            # Between the two ends: neither 0 nor 100 is a position the sensors can back.
            self.position = min(max(self.position, 1.0), 99.0)

    @callback
    def _end_changed(self, _event: Event) -> None:
        self._sync_ends()
        self.notify()

    @callback
    def _power_changed(self, event: Event) -> None:
        self._apply_power(event.data.get("new_state"))

    @callback
    def _apply_power(self, state: State | None) -> None:
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        try:
            watts = float(state.state)
        except ValueError:
            return
        if self._samples is not None and self._phase is not None:
            self._samples.append((self._phase, watts))
        if watts > self.threshold:
            self._cancel_settle()
            if self.motion == IDLE:
                self._motion_started()
        elif self.motion != IDLE and self._unsettle is None:
            # Only a power that stays low for a while is a motor that stopped.
            self._below_since = self._now()
            self._unsettle = async_call_later(self.hass, self.settle_seconds, self._settled)

    @callback
    def _cancel_settle(self) -> None:
        if self._unsettle is not None:
            self._unsettle()
            self._unsettle = None
        self._below_since = None

    @callback
    def _settled(self, _now: datetime) -> None:
        self._unsettle = None
        below_since, self._below_since = self._below_since, None
        if self.motion != IDLE:
            self._motion_stopped(below_since or self._now())

    # --- a run ----------------------------------------------------------------

    def _direction_on_start(self) -> str:
        if self.closed_active or self.position <= 0:
            return OPENING
        if self.open_active or self.position >= 100:
            return CLOSING
        return CLOSING if self.last_direction == OPENING else OPENING

    @callback
    def _motion_started(self) -> None:
        direction = self._direction_on_start()
        self.start_position = self.position
        self.moving_since = self._now()
        self.last_direction = direction
        self.motion = direction
        if self._untick is None:
            self._untick = async_track_time_interval(self.hass, self._tick, timedelta(seconds=1))
        if not self._is_correction(direction):
            self._logbook(direction)
            self._remote_press(direction)
        self.notify()

    @callback
    def _tick(self, _now: datetime) -> None:
        for listener in list(self._position_listeners):
            listener()

    @callback
    def _stop_ticking(self) -> None:
        if self._untick is not None:
            self._untick()
            self._untick = None

    @callback
    def _motion_stopped(self, at: datetime) -> None:
        direction = self.motion
        if self._is_correction(direction):
            # The detour the board made before it could go the right way: the gate is where it was.
            self.motion = IDLE
            self.moving_since = None
            self.position = self.start_position
            self._stop_ticking()
            self.notify()
            return
        since = self.moving_since or at
        seconds = max((at - since).total_seconds(), 0.0)
        if self.closed_active:
            position = 0.0
        elif self.open_active:
            position = 100.0
        else:
            position = min(max(self._estimate(direction, self.start_position, seconds), 1.0), 99.0)

        # The end sensor lets go a moment before the motor draws power: a run that began there began at the end.
        edge = POSITION_TOLERANCE
        complete = (direction == OPENING and self.start_position <= edge and position >= 100) or (
            direction == CLOSING and self.start_position >= 100 - edge and position <= 0
        )
        self.last_move = {
            "direction": direction,
            "seconds": round(seconds, 1),
            "from": round(self.start_position, 1),
            "to": round(position, 1),
            "complete": complete,
            "at": self._now().isoformat(),
        }
        self.position = position
        goal, self._goal = self._goal, None
        retry = goal is not None and not self._goal_retried and (
            (goal >= 100 and position <= 0) or (goal <= 0 and position >= 100)
        )
        if position <= 0:
            self.last_direction = CLOSING
        elif position >= 100:
            self.last_direction = OPENING
        self.motion = IDLE
        self.moving_since = None
        self._stop_ticking()

        if position >= 100:
            self._logbook("opened")
            self._announce("event_opened", position != self.start_position)
        elif position <= 0:
            self._logbook("closed")
            self._announce("event_closed", position != self.start_position)
        else:
            self._logbook("stopped", percent=round(position))
            self._remote_press("stopped")
        self.notify()
        if retry:
            _LOGGER.info("Annika gate %s went the other way: sending it to %s again", self.name, goal)
            self.hass.async_create_task(self.async_go_to(goal, retry=True), eager_start=False)

    # --- commands ------------------------------------------------------------

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _async_wait(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Wait for `predicate` to hold, as the gate notifies; False if `timeout` runs out first."""

        if predicate():
            return True
        future: asyncio.Future = self.hass.loop.create_future()
        waiter = (predicate, future)
        self._waiters.append(waiter)
        try:
            await asyncio.wait_for(future, timeout)
            return True
        except TimeoutError:
            return False
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def _async_switch(self, on: bool) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_on" if on else "turn_off", {"entity_id": self.pulse_switch}, blocking=True
            )
        except Exception:  # noqa: BLE001 — a failed relay must not take the gate down
            _LOGGER.exception(
                "Annika gate %s: could not turn %s %s", self.name, self.pulse_switch, "on" if on else "off"
            )

    async def _async_pulse(self) -> None:
        """One pulse on the board's input. The relay is released even if the command is cancelled."""

        self._pulsed_at = self._now()
        try:
            await self._async_switch(True)
            await self._sleep(self.pulse_seconds)
        finally:
            await self._async_switch(False)

    def _cancel_task(self) -> asyncio.Task | None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
        return task

    async def _async_cancel(self) -> None:
        task = self._cancel_task()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _async_run(self, coroutine) -> None:
        """Run a command in the background. The last command wins: it replaces the one still running."""

        await self._async_cancel()
        self._task = self.hass.async_create_background_task(
            self._guarded(coroutine), f"annika gate {self.name} command"
        )

    async def _guarded(self, coroutine) -> None:
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except GateError as error:
            _LOGGER.warning("Annika gate %s: %s", self.name, error.key)
        except Exception:  # noqa: BLE001 — a command that failed must not leave the gate unmanaged
            _LOGGER.exception("Annika gate %s: a command failed", self.name)

    async def async_go_to(self, position: float, retry: bool = False) -> None:
        """Take the gate to `position`, 0 closed to 100 open."""

        target = min(max(float(position), 0.0), 100.0)
        self._goal = target if target in (0.0, 100.0) else None
        self._goal_retried = retry
        await self._async_run(self._async_goto(target))

    async def async_open(self) -> None:
        await self.async_go_to(100)

    async def async_close(self) -> None:
        await self.async_go_to(0)

    async def async_calibrate(self) -> None:
        await self._async_run(self._async_calibrate())

    async def async_stop_movement(self) -> None:
        """Whatever is running ends, and so does the gate, wherever it is."""

        self._goal = None
        await self._async_cancel()
        if self.motion == IDLE and self._pulsed_at is not None:
            if (self._now() - self._pulsed_at).total_seconds() < MOTION_TIMEOUT:
                # A pulse just went out: wait to see whether the gate answered it.
                await self._async_wait(lambda: self.motion != IDLE, MOTION_TIMEOUT)
        if self.motion != IDLE:
            await self._async_pulse()

    def _already_at(self, target: float) -> bool:
        if self.motion != IDLE:
            return False
        if target <= 0:
            return self.closed_active
        if target >= 100:
            return self.open_active
        return abs(target - self.position) <= POSITION_TOLERANCE

    async def _async_goto(self, target: float) -> None:
        if self._already_at(target):
            return
        direction = OPENING if target > self.position_now() else CLOSING
        self._command_direction = direction
        self.notify()
        try:
            await self._async_start_moving(direction)
            if 0 < target < 100:
                await self._async_stop_at(direction, target)
        finally:
            self._command_direction = None
            self.notify()

    async def _async_start_moving(self, direction: str) -> None:
        """Pulse until the gate moves `direction`: 1 pulse from an end, 3 from a stop the other way."""

        for _ in range(MAX_PULSES):
            if self.motion == direction:
                return
            before = self.motion
            await self._async_pulse()
            await self._async_wait(lambda: self.motion != before, MOTION_TIMEOUT)
        if self.motion != direction:
            raise GateError("no_motion")

    async def _async_stop_at(self, direction: str, target: float) -> None:
        sign = 1 if direction == OPENING else -1
        remaining = (target - self.position_now()) * sign / self.rate(direction)
        await self._sleep(max(remaining - self.stop_latency, 0.0))
        if self.motion == direction:
            await self._async_pulse()

    # --- calibration ----------------------------------------------------------

    @callback
    def _set_calibration(self, status: str, message: str | None = None, **values) -> None:
        self.calibration = {"status": status, "message": message, "at": self._now().isoformat(), **values}
        if status == CALIBRATION_OK:
            self._logbook(
                "calibrated",
                open_seconds=values["open_seconds"],
                close_seconds=values["close_seconds"],
                threshold=values["threshold"],
            )
        elif status == CALIBRATION_FAILED:
            self._logbook("calibration_failed", reason=self._text(f"reason_{message}"))
        self.notify()

    async def _async_calibrate(self) -> None:
        """Take the gate to the closed sensor, then all the way open and all the way closed, timing both."""

        self._set_calibration(CALIBRATION_RUNNING, CLOSING)
        previous = self.settings.threshold
        self.settings.threshold = self._calibration_floor()
        self._samples, self._phase = [], None
        succeeded = False
        try:
            if not self.closed_active:
                await self._async_goto(0)
                if not await self._async_wait(
                    lambda: self.closed_active and self.motion == IDLE, MAX_RUN_SECONDS
                ):
                    raise GateError("no_closed")
            self._start_sampling()
            await self._sleep(1)
            opening = await self._async_measure(OPENING)
            await self._sleep(1)
            closing = await self._async_measure(CLOSING)
            threshold = self._found_threshold()
        except asyncio.CancelledError:
            self._set_calibration(CALIBRATION_FAILED, "cancelled")
            raise
        except GateError as error:
            self._set_calibration(CALIBRATION_FAILED, error.key)
            return
        else:
            succeeded = True
        finally:
            self._samples, self._phase = None, None
            if not succeeded:
                self.settings.threshold = previous
        self.settings.open_seconds = opening
        self.settings.close_seconds = closing
        self.settings.threshold = threshold
        self._set_calibration(
            CALIBRATION_OK, None, open_seconds=opening, close_seconds=closing, threshold=threshold
        )

    def _calibration_floor(self) -> float:
        """The draw above which anything counts as the motor while calibrating: clear of what the board reads at rest."""

        try:
            rest = float(self._state(self.power_sensor).state)
        except (AttributeError, TypeError, ValueError):
            rest = 0.0
        return max(CALIBRATION_THRESHOLD, 2 * rest + 2)

    def _start_sampling(self) -> None:
        """From here on the readings count: the one right now is the board at rest."""

        self._phase = "idle"
        state = self._state(self.power_sensor)
        try:
            self._samples.append(("idle", float(state.state)))
        except (AttributeError, TypeError, ValueError):
            pass

    def _found_threshold(self) -> float:
        """Halfway between what the board reads at rest and the lowest the motor draws while it runs."""

        samples = self._samples or []
        rest = max((watts for phase, watts in samples if phase == "idle"), default=0.0)
        runs = sorted(watts for phase, watts in samples if phase == "run")
        if not runs:
            raise GateError("no_power")
        # The run's own ends (the motor spinning up and winding down) are not what it draws.
        steady = [watts for watts in runs if watts >= 0.25 * runs[-1] and watts > 2 * rest]
        if not steady or steady[0] <= rest * 1.5 or steady[0] < 2 * CALIBRATION_THRESHOLD:
            raise GateError("no_power")
        return float(min(max(round(rest + (steady[0] - rest) / 2), 1), MAX_THRESHOLD))

    async def _async_measure(self, direction: str) -> float:
        """One pulse, one whole run from an end to the other: how long it took."""

        self._set_calibration(CALIBRATION_RUNNING, direction)
        self._phase = "run"
        await self._async_pulse()
        if not await self._async_wait(lambda: self.motion != IDLE, MOTION_TIMEOUT):
            raise GateError("no_motion")
        if self.motion != direction:
            raise GateError("wrong_direction")
        if not await self._async_wait(lambda: self.motion == IDLE, MAX_RUN_SECONDS):
            raise GateError("never_stopped")
        self._phase = "idle"
        move = self.last_move or {}
        if not move.get("complete"):
            raise GateError("stopped_early")
        if move["seconds"] < MIN_TRAVEL_SECONDS:
            raise GateError("too_short")
        return move["seconds"]

    # --- logbook and events ---------------------------------------------------

    def entity_id(self, domain: str, unique_id: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(domain, DOMAIN, unique_id)

    def _text(self, key: str, **values) -> str:
        language = str(self.hass.config.language or "en").split("-")[0].lower()
        texts = TEXTS.get(language, TEXTS["en"])
        return texts.get(key, TEXTS["en"][key]).format(name=self.name, **values)

    def _logbook(self, key: str, **values) -> None:
        entity_id = self.entity_id("sensor", unique_status(self))
        if entity_id is None:
            return
        self.hass.bus.async_fire(
            "logbook_entry",
            {"name": self.name, "message": self._text(key, **values), "entity_id": entity_id, "domain": DOMAIN},
        )

    def _pulsed_recently(self) -> bool:
        return self._pulsed_at is not None and (self._now() - self._pulsed_at).total_seconds() < OWN_PULSE_WINDOW

    @callback
    def _remote_press(self, key: str) -> None:
        """Say what a press that did not come from Annika did: the gate cannot tell which person or button, only the effect."""

        if self._pulsed_recently():
            return
        entity_id = self.entity_id("cover", unique_cover(self))
        if entity_id is None:
            return
        self.hass.bus.async_fire(
            "logbook_entry",
            {"name": self.name, "message": self._text(f"remote_{key}"), "entity_id": entity_id, "domain": DOMAIN},
        )

    @callback
    def _announce(self, key: str, changed: bool) -> None:
        if changed and self.notify_view and self.settings.notify is not False:
            self.hass.async_create_task(self._send_event(key))

    async def _send_event(self, key: str) -> None:
        try:
            await AnnikaEventClient(self.hass).async_send(
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "info",
                    "title": self._text(key),
                    "message": "",
                    "view": self.notify_view,
                }
            )
        except Exception:  # noqa: BLE001 — a missed notification must not stop the gate
            _LOGGER.warning("Annika gate %s: could not send the %s event", self.name, key)


# Unique ids of the entities this module's platforms create. The card finds
# them through the status sensor's attributes, so none is named in YAML.
def unique_status(gate: AnnikaGate) -> str:
    return "annika_gate"


def unique_cover(gate: AnnikaGate) -> str:
    return "annika_gate_cover"


def unique_moving(gate: AnnikaGate) -> str:
    return "annika_gate_moving"


def unique_open_seconds(gate: AnnikaGate) -> str:
    return "annika_gate_open_seconds"


def unique_close_seconds(gate: AnnikaGate) -> str:
    return "annika_gate_close_seconds"


def unique_threshold(gate: AnnikaGate) -> str:
    return "annika_gate_threshold"


def unique_calibrate(gate: AnnikaGate) -> str:
    return "annika_gate_calibrate"


def unique_notify(gate: AnnikaGate) -> str:
    return "annika_gate_notify"


def unique_auto_off(gate: AnnikaGate) -> str:
    return "annika_gate_auto_off"


def unique_closed_inverted(gate: AnnikaGate) -> str:
    return "annika_gate_closed_inverted"


def unique_open_inverted(gate: AnnikaGate) -> str:
    return "annika_gate_open_inverted"
