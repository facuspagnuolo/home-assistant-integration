"""Annika alarm panel: the unit's own alarm, with a code and three modes.

Home Assistant's `manual` panel needs a YAML block per house and keeps its code
in plain text. This one is Annika's: the YAML only says what the panel is
called, the code it starts with and how long each mode takes to arm and to
sound once something trips it. The person changes the code from
annika-alarm-card.

    annika:
      alarm:
        name: Home Alarm              # alarm_control_panel.home_alarm
        code: !secret alarm_code      # where the code starts; the card can replace it
        modes:
          away:     {arming: 30, pending: 30}
          night:    {arming: 10, pending: 15}
          vacation: {arming: 30, pending: 30}

Only the modes listed under `modes` exist: leave one out and the card shows no
button, timing, rule column or choice for it, and it cannot be armed. Listing
none gives all three with their default timings. `away:` with nothing under it
is a mode with the defaults.

It can also arm and disarm itself:

        auto_arm:
          mode: night                 # away | night | vacation
          time: "23:00"
          quiet_minutes: 10           # then wait for this long without movement...
          sensors:                    # ...in these sensors (the group); none = arm at `time`
            - binary_sensor.living_room_motion
        auto_disarm:
          mode: night                 # only disarms what is armed in this mode
          time: "07:00"

From `auto_arm.time` on, the panel arms as soon as none of the sensors has been
active for `quiet_minutes` in a row, so nobody gets locked in the dark while
still walking around. The times, the minutes and whether each runs are plain
entities, restored across restarts and editable from the card; the YAML is
only where they start.

States: disarmed, arming (counting down to a mode), armed_away / armed_night /
armed_vacation, pending (tripped, the person still has time to disarm) and
triggered (sounding until somebody disarms).

Arming and disarming ask for the code. The rules engine arms and triggers the
panel on its own, without one. Wrong codes are counted: five in a row lock the
keypad for five minutes.

Deadlines (end of arming, end of pending) are times the panel remembers rather
than sleeps, so a restart in the middle of one finishes it on the way back up.
The code is stored salted and hashed, never in plain text.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Callable

from datetime import time as dt_time

import voluptuous as vol

from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alarm_rules import RULES_SCHEMA
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_ALARM_PANEL = f"{DOMAIN}_alarm_panel"

MODES = ("away", "night", "vacation")

STATE_DISARMED = "disarmed"
STATE_ARMING = "arming"
STATE_PENDING = "pending"
STATE_TRIGGERED = "triggered"
ARMED_PREFIX = "armed_"

MAX_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=5)
CODE_MIN_LENGTH = 4
CODE_MAX_LENGTH = 8

STORE_VERSION = 1
MAX_SECONDS = 600

MODE_DEFAULTS = {
    "away": {"arming": 30, "pending": 30},
    "night": {"arming": 10, "pending": 15},
    "vacation": {"arming": 30, "pending": 30},
}


def _mode_schema(mode: str) -> vol.Schema:
    defaults = MODE_DEFAULTS[mode]
    return vol.Schema(
        {
            vol.Optional("arming", default=defaults["arming"]): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_SECONDS)
            ),
            vol.Optional("pending", default=defaults["pending"]): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_SECONDS)
            ),
        }
    )


def _code(value) -> str:
    code = str(value).strip()
    if not code.isdigit() or not CODE_MIN_LENGTH <= len(code) <= CODE_MAX_LENGTH:
        raise vol.Invalid(
            f"the code is {CODE_MIN_LENGTH} to {CODE_MAX_LENGTH} digits"
        )
    return code


def _clock(value) -> dt_time:
    return cv.time(value)


AUTO_ARM_SCHEMA = vol.Schema(
    {
        vol.Optional("mode"): vol.In(MODES),
        vol.Required("time"): _clock,
        vol.Optional("quiet_minutes", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=240)
        ),
        vol.Optional("sensors", default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
    }
)

AUTO_DISARM_SCHEMA = vol.Schema(
    {
        vol.Optional("mode"): vol.In(MODES),
        vol.Required("time"): _clock,
    }
)

def _mode_block(mode: str):
    """`away:` with nothing under it is a mode with the default timings."""

    return vol.All(lambda value: {} if value is None else value, _mode_schema(mode))


def _enabled_modes(config: dict) -> dict:
    """Keep the modes the YAML lists (all three when it lists none), and check the
    automatic arming and disarming use one of them."""

    if not config["modes"]:
        config["modes"] = {mode: _mode_schema(mode)({}) for mode in MODES}
    enabled = [mode for mode in MODES if mode in config["modes"]]
    for key, label in (("auto_arm", "auto_arm"), ("auto_disarm", "auto_disarm")):
        block = config.get(key)
        if block is None:
            continue
        if "mode" not in block:
            block["mode"] = "night" if "night" in enabled else enabled[0]
        elif block["mode"] not in enabled:
            raise vol.Invalid(
                f"{label}.mode is {block['mode']}, which is not one of the alarm's modes ({', '.join(enabled)})"
            )
    return config


ALARM_SCHEMA = vol.All(vol.Schema(
    {
        vol.Optional("name", default="Home Alarm"): cv.string,
        vol.Required("code"): _code,
        vol.Optional("auto_arm"): AUTO_ARM_SCHEMA,
        vol.Optional("auto_disarm"): AUTO_DISARM_SCHEMA,
        # Off by default: lets an automation or a script disarm with no code,
        # through annika.disarm_without_code. Anyone who can call services
        # (a dashboard button included) can then disarm without the keypad.
        vol.Optional("allow_disarm_without_code", default=False): cv.boolean,
        # Same for arming: annika.arm_without_code takes a mode and no code.
        vol.Optional("allow_arm_without_code", default=False): cv.boolean,
        **RULES_SCHEMA,
        # Only the modes listed here exist: the card shows no button, column or choice
        # for the others. Listing none gives all three, with their default timings.
        vol.Optional("modes", default={}): vol.Schema(
            {vol.Optional(mode): _mode_block(mode) for mode in MODES}
        ),
    }
), _enabled_modes)


class CodeError(Exception):
    """The code was wrong or the keypad is locked. `reason` is the translation key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def hash_code(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120_000).hex()


class AnnikaAlarmPanel:
    """State machine, code and deadlines of the panel. The entity only mirrors it."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.allow_disarm_without_code: bool = config["allow_disarm_without_code"]
        self.allow_arm_without_code: bool = config["allow_arm_without_code"]
        self._initial_code: str = config["code"]
        # The modes that exist, with their timings and whether the person left them
        # enabled from the card. A disabled mode cannot be armed and the card hides it.
        self.modes: dict[str, dict] = {
            mode: {**config["modes"][mode], "enabled": True}
            for mode in MODES
            if mode in config["modes"]
        }
        auto_arm = config.get("auto_arm")
        auto_disarm = config.get("auto_disarm")
        self.has_auto_arm = auto_arm is not None
        self.has_auto_disarm = auto_disarm is not None
        self.auto_arm_mode: str = auto_arm["mode"] if auto_arm else "night"
        self.auto_arm_sensors: list[str] = auto_arm["sensors"] if auto_arm else []
        self.auto_arm_enabled = self.has_auto_arm
        self.auto_arm_time: dt_time = auto_arm["time"] if auto_arm else dt_time(23, 0)
        self.auto_arm_quiet: int = auto_arm["quiet_minutes"] if auto_arm else 0
        self.auto_disarm_enabled = self.has_auto_disarm
        self.auto_disarm_time: dt_time = auto_disarm["time"] if auto_disarm else dt_time(7, 0)
        self.auto_disarm_mode: str = auto_disarm["mode"] if auto_disarm else "night"
        # Past the arming time and waiting for the house to go quiet.
        self.auto_arm_waiting = False
        self._quiet_since: datetime | None = None
        self._cancel_quiet: Callable[[], None] | None = None
        self._cancel_arm_clock: Callable[[], None] | None = None
        self._cancel_disarm_clock: Callable[[], None] | None = None
        self._cancel_sensors: Callable[[], None] | None = None
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.alarm_panel")

        self.state: str = STATE_DISARMED
        self.restoring = False
        # The mode being armed, or armed; kept through pending and triggered so
        # the card can say what was tripped and disarming knows what to clear.
        self.mode: str | None = None
        # Who last armed or disarmed: "auto" for the panel's own schedule, else None.
        self.last_source: str | None = None
        self.deadline: datetime | None = None
        self.failed_attempts = 0
        self.locked_until: datetime | None = None

        self._salt = ""
        self._hash = ""
        self._code_is_initial = True
        self._cancel_deadline: Callable[[], None] | None = None
        self._cancel_lockout: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._triggers: list[Callable[[str], None]] = []
        self._ready = False
        # Set by the entity (the rules log to its logbook) and by the setup.
        self.entity_id: str | None = None
        self.rules = None

    # --- lifecycle ----------------------------------------------------------

    async def async_load(self) -> None:
        """Read the stored code. Called before the entity is added."""

        data = await self._store.async_load() or {}
        # What the person set from the card wins over the YAML.
        for mode, timing in data.get("modes", {}).items():
            if mode in self.modes:
                for key in ("arming", "pending"):
                    if isinstance(timing.get(key), int) and 0 <= timing[key] <= MAX_SECONDS:
                        self.modes[mode][key] = timing[key]
        stored_enabled = {
            mode: timing["enabled"]
            for mode, timing in data.get("modes", {}).items()
            if mode in self.modes and isinstance(timing.get("enabled"), bool)
        }
        # Never leave the panel with nothing to arm in.
        if any(stored_enabled.get(mode, True) for mode in self.modes):
            for mode, value in stored_enabled.items():
                self.modes[mode]["enabled"] = value
        self._fix_auto_modes()
        stored = data.get("hash")
        self._code_is_initial = data.get("initial", True)
        if stored and not self._code_is_initial:
            self._salt, self._hash = data["salt"], data["hash"]
        else:
            # Still the code from the YAML: follow it when the YAML changes.
            await self._async_set_code(self._initial_code, initial=True)
        self._schedule_clocks()
        if self.auto_arm_sensors:
            self._cancel_sensors = async_track_state_change_event(
                self.hass, self.auto_arm_sensors, self._sensor_changed
            )

    async def async_stop(self, _event=None) -> None:
        if self.rules is not None:
            await self.rules.async_stop()
        self._cancel_timers()
        for cancel in (self._cancel_arm_clock, self._cancel_disarm_clock, self._cancel_sensors):
            if cancel is not None:
                cancel()
        self._cancel_arm_clock = self._cancel_disarm_clock = self._cancel_sensors = None

    def restore(
        self,
        state: str | None,
        mode: str | None,
        deadline: datetime | None,
    ) -> None:
        """Take back what the entity remembered, finishing any deadline that passed."""

        self._ready = True
        if state is None:
            return
        if state == STATE_DISARMED:
            self.state = STATE_DISARMED
        elif mode in self.enabled_modes:
            self.mode = mode
            self.state = state
            self.deadline = deadline
            if state in (STATE_ARMING, STATE_PENDING):
                if deadline is None or deadline <= dt_util.utcnow():
                    self._finish_deadline(dt_util.utcnow())
                else:
                    self._schedule_deadline(deadline)
        # The rules take the restored state as where they start from.
        self.restoring = True
        try:
            for trigger in list(self._triggers):
                trigger(self.state)
        finally:
            self.restoring = False

    # --- reading ------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self.state.startswith(ARMED_PREFIX)

    @property
    def active(self) -> bool:
        """Anything but disarmed: what the card's Disarm button hangs on."""

        return self.state != STATE_DISARMED

    @property
    def locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > dt_util.utcnow()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def on_change(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Listen for the state changing, with the new state. For the rules engine."""

        self._triggers.append(listener)

        def unsubscribe() -> None:
            if listener in self._triggers:
                self._triggers.remove(listener)

        return unsubscribe

    # --- code ---------------------------------------------------------------

    def check_code(self, code: str | None) -> None:
        """Raise CodeError unless `code` is right and the keypad is not locked."""

        now = dt_util.utcnow()
        if self.locked:
            raise CodeError("locked")
        if code is not None and hmac.compare_digest(
            hash_code(str(code), self._salt), self._hash
        ):
            self.failed_attempts = 0
            self.locked_until = None
            return
        self.failed_attempts += 1
        if self.failed_attempts >= MAX_ATTEMPTS:
            self.failed_attempts = 0
            self.locked_until = now + LOCKOUT
            self._cancel_lock_timer()
            self._cancel_lockout = async_track_point_in_time(
                self.hass, self._unlock, self.locked_until
            )
            self._notify()
            raise CodeError("locked")
        self._notify()
        raise CodeError("invalid_code")

    async def async_change_code(self, current: str | None, new: str) -> None:
        self.check_code(current)
        try:
            new = _code(new)
        except vol.Invalid as err:
            raise CodeError("invalid_new_code") from err
        await self._async_set_code(new, initial=False)

    async def _async_set_code(self, code: str, *, initial: bool) -> None:
        self._salt = secrets.token_hex(16)
        self._hash = hash_code(code, self._salt)
        self._code_is_initial = initial
        await self._store.async_save(self._data())

    def _data(self) -> dict:
        return {
            "salt": self._salt,
            "hash": self._hash,
            "initial": self._code_is_initial,
            "modes": self.modes,
        }

    @property
    def enabled_modes(self) -> list[str]:
        """The modes that can be armed, in the usual order."""

        return [mode for mode in MODES if mode in self.modes and self.modes[mode]["enabled"]]

    def _fix_auto_modes(self) -> None:
        """Automatic arming and disarming only name an enabled mode."""

        enabled = self.enabled_modes
        fallback = "night" if "night" in enabled else enabled[0]
        if self.auto_arm_mode not in enabled:
            self.auto_arm_mode = fallback
        if self.auto_disarm_mode not in enabled:
            self.auto_disarm_mode = fallback

    def set_mode_enabled(self, mode: str, enabled: bool) -> None:
        """Turn a mode on or off. The last enabled mode cannot be turned off; a panel
        armed in a mode being turned off is disarmed."""

        if mode not in self.modes:
            raise CodeError("invalid_mode")
        if not enabled and self.enabled_modes == [mode]:
            raise CodeError("last_mode")
        self.modes[mode]["enabled"] = enabled
        if not enabled:
            self._fix_auto_modes()
            if self.mode == mode and self.state != STATE_DISARMED:
                self.disarm(skip_code=True)
        self._store.async_delay_save(self._data, 1)
        self.notify_listeners()

    def set_timing(self, mode: str, arming: int | None = None, pending: int | None = None) -> None:
        """How long a mode takes to arm and how long the person has once it trips.

        Takes effect from the next arming or trigger; one already counting
        down keeps the deadline it was given.
        """

        if mode not in self.modes:
            raise CodeError("invalid_mode")
        if arming is not None:
            self.modes[mode]["arming"] = arming
        if pending is not None:
            self.modes[mode]["pending"] = pending
        self._store.async_delay_save(self._data, 1)
        self.notify_listeners()

    @callback
    def _unlock(self, _now) -> None:
        self.locked_until = None
        self._cancel_lockout = None
        self._notify()

    # --- commands -----------------------------------------------------------

    def arm(
        self, mode: str, code: str | None = None, *, skip_code: bool = False, source: str | None = None
    ) -> None:
        if mode not in self.enabled_modes:
            raise CodeError("invalid_mode")
        if not skip_code:
            self.check_code(code)
        self.last_source = source
        self._cancel_deadline_timer()
        self.mode = mode
        arming = self.modes[mode]["arming"]
        if arming > 0:
            self._set(STATE_ARMING, dt_util.utcnow() + timedelta(seconds=arming))
        else:
            self._set(f"{ARMED_PREFIX}{mode}", None)

    def disarm(self, code: str | None = None, *, skip_code: bool = False, source: str | None = None) -> None:
        if not skip_code:
            self.check_code(code)
        self.last_source = source
        self._cancel_deadline_timer()
        self.mode = None
        self._set(STATE_DISARMED, None)

    def trigger(self) -> None:
        """Something tripped an armed panel. Pending first when the mode gives time."""

        if not self.armed:
            return
        pending = self.modes[self.mode]["pending"]
        if pending > 0:
            self._set(STATE_PENDING, dt_util.utcnow() + timedelta(seconds=pending))
        else:
            self._set(STATE_TRIGGERED, None)

    # --- automatic arming and disarming ------------------------------------

    def configure_auto(self, **settings) -> None:
        """Change the automatic settings (what the entities do) and re-time them."""

        for name, value in settings.items():
            setattr(self, name, value)
        self._schedule_clocks()
        if not self.auto_arm_enabled:
            self._stop_waiting()
        else:
            self._evaluate_quiet()
        self._notify()

    def _schedule_clocks(self) -> None:
        for cancel in (self._cancel_arm_clock, self._cancel_disarm_clock):
            if cancel is not None:
                cancel()
        self._cancel_arm_clock = self._cancel_disarm_clock = None
        if self.has_auto_arm:
            t = self.auto_arm_time
            self._cancel_arm_clock = async_track_time_change(
                self.hass, self._arm_time_reached, hour=t.hour, minute=t.minute, second=0
            )
        if self.has_auto_disarm:
            t = self.auto_disarm_time
            self._cancel_disarm_clock = async_track_time_change(
                self.hass, self._disarm_time_reached, hour=t.hour, minute=t.minute, second=0
            )

    @callback
    def _arm_time_reached(self, _now) -> None:
        if not self.auto_arm_enabled or self.state != STATE_DISARMED:
            return
        self.auto_arm_waiting = True
        self._quiet_since = None
        self._evaluate_quiet()
        self._notify()

    @callback
    def _disarm_time_reached(self, _now) -> None:
        self._stop_waiting()
        # Only the mode it is for: a house armed away or on vacation is not
        # waking up at seven.
        if self.auto_disarm_enabled and self.active and self.mode == self.auto_disarm_mode:
            self.disarm(skip_code=True, source="auto")

    @callback
    def _sensor_changed(self, _event: Event) -> None:
        self._evaluate_quiet()

    def _any_sensor_active(self) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None and state.state == STATE_ON
            for entity_id in self.auto_arm_sensors
        )

    def _evaluate_quiet(self) -> None:
        """Arm once no sensor has been active for `quiet_minutes` in a row."""

        if not self.auto_arm_waiting:
            return
        if self.state != STATE_DISARMED:
            self._stop_waiting()
            return
        if self._cancel_quiet is not None:
            self._cancel_quiet()
            self._cancel_quiet = None
        if self._any_sensor_active():
            self._quiet_since = None
            return
        now = dt_util.utcnow()
        if self._quiet_since is None:
            self._quiet_since = now
        due = self._quiet_since + timedelta(minutes=self.auto_arm_quiet)
        if due <= now:
            self._stop_waiting()
            self.arm(self.auto_arm_mode, skip_code=True, source="auto")
        else:
            self._cancel_quiet = async_track_point_in_time(
                self.hass, self._quiet_elapsed, due
            )

    @callback
    def _quiet_elapsed(self, _now) -> None:
        self._cancel_quiet = None
        self._evaluate_quiet()

    def _stop_waiting(self) -> None:
        was = self.auto_arm_waiting
        self.auto_arm_waiting = False
        self._quiet_since = None
        if self._cancel_quiet is not None:
            self._cancel_quiet()
            self._cancel_quiet = None
        if was:
            self._notify()

    # --- deadlines ----------------------------------------------------------

    def _set(self, state: str, deadline: datetime | None) -> None:
        self.state = state
        self.deadline = deadline
        if state != STATE_DISARMED:
            self._stop_waiting()
        self._cancel_deadline_timer()
        if deadline is not None:
            self._schedule_deadline(deadline)
        self._notify()

    def _schedule_deadline(self, deadline: datetime) -> None:
        self._cancel_deadline_timer()
        self._cancel_deadline = async_track_point_in_time(
            self.hass, self._deadline_reached, deadline
        )

    @callback
    def _deadline_reached(self, now) -> None:
        self._cancel_deadline = None
        self._finish_deadline(now)

    def _finish_deadline(self, _now) -> None:
        if self.state == STATE_ARMING:
            self._set(f"{ARMED_PREFIX}{self.mode}", None)
        elif self.state == STATE_PENDING:
            self._set(STATE_TRIGGERED, None)

    def _cancel_deadline_timer(self) -> None:
        if self._cancel_deadline is not None:
            self._cancel_deadline()
            self._cancel_deadline = None

    def _cancel_lock_timer(self) -> None:
        if self._cancel_lockout is not None:
            self._cancel_lockout()
            self._cancel_lockout = None

    def _cancel_timers(self) -> None:
        self._cancel_deadline_timer()
        self._cancel_lock_timer()

    def notify_listeners(self) -> None:
        """Tell the entity something it shows changed, without it being a state change."""

        for listener in list(self._listeners):
            listener()

    def _notify(self) -> None:
        self.notify_listeners()
        for trigger in list(self._triggers):
            trigger(self.state)
