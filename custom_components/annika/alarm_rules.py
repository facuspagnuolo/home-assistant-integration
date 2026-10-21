"""Annika alarm rules: what each sensor does in each mode, and what answers it.

The panel (alarm_panel.py) knows if the house is armed. These rules say what a
detection means once it is. Every sensor belongs to a zone (Exterior, Interior,
Perimeter...) and for each mode — away, night, vacation — a zone, or one of its
sensors, is either `off`, a `warning` or a `trigger`:

    annika:
      alarm:
        warning: {limit: 3, window_minutes: 30}
        notification: {view: alarm, warning: true, trigger: true, trigger_repeat: 5}
        outputs:
          - name: Sirens
            entities: [switch.sirenas]
            warning: {enabled: true, seconds: 3}
            trigger: {enabled: true}              # until disarmed
          - name: Floodlights
            entities: [switch.reflectores, light.rp_pcb8m_floodlight]
            warning: {enabled: true, seconds: 60}
        zones:
          - name: Exterior
            rules: {away: warning, night: warning, vacation: warning}
            sensors:
              - {name: Camera 1, detail: person, entities: [binary_sensor.cam1_person]}
              - name: Camera 2
                entities: [binary_sensor.cam2_person]
                rules: {night: off}               # this sensor's own rule
          - name: Interior
            rules: {away: trigger, vacation: trigger}
            sensors:
              - {name: Office, entities: [binary_sensor.office_motion]}

A warning switches on the outputs that have a warning duration, for that long,
and counts toward `limit`. When the count is past the limit — within `window`
minutes of the last detection, so a quiet half hour starts it over — the next
warning is a trigger. A trigger trips the panel (pending, then triggered), and
the outputs with a trigger switch on until somebody disarms. Disarming resets
the count and switches off whatever the rules switched on.

A warning can ask for more than one detection first. `confirm` is a gate in
front of the warning: a detection becomes a signal, and the warning only goes
once `count` signals of a zone arrive within `window_seconds`. Cameras are the
use case: one flying insect makes one short blip, a person makes several
detections or stays in view.

    warning:
      confirm: {count: 2, window_seconds: 60, min_seconds: 2, recount_seconds: 10}

`min_seconds` is how long a sensor has to stay on for its detection to count
(a shorter blip is dropped). `recount_seconds` counts it again every that many
seconds for as long as the sensor stays on, so a person who stands in front of
a camera keeps adding up (and so does a sensor stuck on: when something fails
the alarm sounds, it does not stay quiet). A zone, or one of its sensors, can
set its own `confirm` and the rest of its values come from the level above.
The defaults (count 1, min 0, recount 0) leave every detection as an
immediate warning, as it always was. Trigger rules never go through the gate.
Each warning needs its own `count` signals. Detections that are still waiting
for the rest are not decisions: they are not logged.

Every detection that is handled, ignored or escalated is a line in the
decisions list and in the logbook, so "why did the siren sound?" has an answer.

The YAML is where the rules start. What the person edits from annika-alarm-card
(rules, durations, limits, notifications) is stored and wins from then on.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

import voluptuous as vol

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .send_event import AnnikaEventClient

if TYPE_CHECKING:  # pragma: no cover
    from .alarm_panel import AnnikaAlarmPanel

_LOGGER = logging.getLogger(__name__)

MODES = ("away", "night", "vacation")
RULES = ("off", "warning", "trigger")

STORE_VERSION = 1
MAX_DECISIONS = 50
TEST_SECONDS = 3
MAX_SECONDS = 24 * 3600

DEFAULT_LIMIT = 3
DEFAULT_WINDOW_MINUTES = 30
DEFAULT_CONFIRM = {"count": 1, "window_seconds": 60, "min_seconds": 0, "recount_seconds": 0}
CONFIRM_FIELDS = tuple(DEFAULT_CONFIRM)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _off(value):
    # YAML reads an unquoted `off` as False.
    return "off" if value is False else value


_RULE = vol.All(_off, vol.In(RULES))
_MODE_RULES = vol.Schema({vol.Optional(mode): _RULE for mode in MODES})
_ENTITIES = vol.All(cv.ensure_list, [cv.entity_id], vol.Length(min=1))

_CONFIRM_VALUES = {
    "count": vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    "window_seconds": vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
    "min_seconds": vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
    "recount_seconds": vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
}
# The global one starts from the defaults; a zone or a sensor only says what it changes.
CONFIRM_SCHEMA = vol.Schema({vol.Optional(k, default=DEFAULT_CONFIRM[k]): v for k, v in _CONFIRM_VALUES.items()})
_CONFIRM_OVERRIDE = vol.Schema({vol.Optional(k): v for k, v in _CONFIRM_VALUES.items()})

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entities"): _ENTITIES,
        vol.Optional("detail"): cv.string,
        vol.Optional("rules", default={}): _MODE_RULES,
        vol.Optional("confirm", default={}): _CONFIRM_OVERRIDE,
    }
)

ZONE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("rules", default={}): _MODE_RULES,
        vol.Optional("confirm", default={}): _CONFIRM_OVERRIDE,
        vol.Required("sensors"): vol.All(cv.ensure_list, [SENSOR_SCHEMA]),
    }
)

OUTPUT_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entities"): _ENTITIES,
        vol.Optional("warning", default={}): vol.Schema(
            {
                vol.Optional("enabled", default=False): cv.boolean,
                vol.Optional("seconds", default=TEST_SECONDS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=MAX_SECONDS)
                ),
            }
        ),
        vol.Optional("trigger", default={}): vol.Schema(
            {vol.Optional("enabled", default=True): cv.boolean}
        ),
    }
)

RULES_SCHEMA = {
    vol.Optional("warning", default={}): vol.Schema(
        {
            vol.Optional("limit", default=DEFAULT_LIMIT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=20)
            ),
            vol.Optional("window_minutes", default=DEFAULT_WINDOW_MINUTES): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=24 * 60)
            ),
            vol.Optional("confirm", default={}): CONFIRM_SCHEMA,
        }
    ),
    vol.Optional("notification", default={}): vol.Schema(
        {
            vol.Optional("view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
            vol.Optional("warning", default=True): cv.boolean,
            vol.Optional("trigger", default=True): cv.boolean,
            # Tell the house when the alarm is disarmed, and by whom when the app knows.
            # Follows the trigger switch: whoever turned those notifications off hears none.
            vol.Optional("disarm", default=True): cv.boolean,
            # While the alarm stays triggered, send the notification again every this
            # many seconds. 0 sends it once.
            vol.Optional("trigger_repeat", default=0): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=3600)
            ),
        }
    ),
    vol.Optional("outputs", default=[]): vol.All(cv.ensure_list, [OUTPUT_SCHEMA]),
    vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [ZONE_SCHEMA]),
}


# What the decisions and the Annika events say, by Home Assistant language.
TEXTS = {
    "en": {
        "logbook_name": "Alarm",
        "mode_away": "away",
        "mode_night": "night",
        "mode_vacation": "vacation",
        "warning": "{sensor} · {mode} · warning {n} of {limit}",
        "limit": "{sensor} · {mode} · warning limit reached, trigger",
        "trigger": "{sensor} · {mode} · trigger",
        "triggered": "Alarm triggered",
        "armed": "Armed · {mode}{by}",
        "disarmed": "Disarmed{by}",
        "by": " · by {actor}",
        "by_auto": " · automatic",
        "title_warning": "⚠️ Alarm warning",
        "title_trigger": "🚨 Alarm triggered",
        "title_disarmed": "🔓 Alarm disarmed",
        "notify_warning": "{sensor} - warning {n} of {limit}",
        "notify_reminder": "Reminder #{n}",
        "notify_disarmed_by": "Disarmed by {actor}",
        "notify_disarmed": "Disarmed",
        "notify_disarmed_auto": "Disarmed automatically",
        "title_test": "Alarm notification test",
        "message_test": "This is a test of the alarm notifications",
        "expired": "No detections for {minutes} min: warning counter reset",
    },
    "es": {
        "logbook_name": "Alarma",
        "mode_away": "salida",
        "mode_night": "noche",
        "mode_vacation": "vacaciones",
        "warning": "{sensor} · {mode} · aviso {n} de {limit}",
        "limit": "{sensor} · {mode} · límite de avisos alcanzado, disparo",
        "trigger": "{sensor} · {mode} · disparo",
        "triggered": "Alarma disparada",
        "armed": "Armada · {mode}{by}",
        "disarmed": "Desarmada{by}",
        "by": " · por {actor}",
        "by_auto": " · automática",
        "title_warning": "⚠️ Aviso de alarma",
        "title_trigger": "🚨 Alarma disparada",
        "title_disarmed": "🔓 Alarma desactivada",
        "notify_warning": "{sensor} - aviso {n} de {limit}",
        "notify_reminder": "Recordatorio #{n}",
        "notify_disarmed_by": "Desactivada por {actor}",
        "notify_disarmed": "Desactivada",
        "notify_disarmed_auto": "Desactivada automáticamente",
        "title_test": "Prueba de notificación de la alarma",
        "message_test": "Esta es una prueba de las notificaciones de la alarma",
        "expired": "Sin detecciones por {minutes} min: contador de avisos en cero",
    },
}


class _Sensor:
    def __init__(self, zone: "_Zone", config: dict) -> None:
        self.zone = zone
        self.id = slug(config["name"])
        self.name = config["name"]
        self.detail = config.get("detail")
        self.entities: list[str] = config["entities"]
        self.rules: dict[str, str | None] = {m: config["rules"].get(m) for m in MODES}
        self.confirm: dict[str, int] = dict(config.get("confirm", {}))

    @property
    def key(self) -> str:
        return f"{self.zone.id}.{self.id}"

    def rule(self, mode: str) -> str:
        return self.rules.get(mode) or self.zone.rules.get(mode) or "off"


class _Zone:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name = config["name"]
        self.rules: dict[str, str] = {m: config["rules"].get(m, "off") for m in MODES}
        self.confirm: dict[str, int] = dict(config.get("confirm", {}))
        # The signals waiting for the rest of a warning's `count`, by time.
        self.signals: list[datetime] = []
        self.sensors = [_Sensor(self, sensor) for sensor in config["sensors"]]


class _Output:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name = config["name"]
        self.entities: list[str] = config["entities"]
        self.warning_enabled: bool = config["warning"]["enabled"]
        self.warning_seconds: int = config["warning"]["seconds"]
        self.trigger_enabled: bool = config["trigger"]["enabled"]
        self.on = False
        self.cancel: Callable[[], None] | None = None


class AnnikaAlarmRules:
    """Decides what a detection means and drives the outputs. The panel holds the state."""

    def __init__(self, hass: HomeAssistant, panel: "AnnikaAlarmPanel", config: dict) -> None:
        self.hass = hass
        self.panel = panel
        self.limit: int = config["warning"]["limit"]
        self.window_minutes: int = config["warning"]["window_minutes"]
        self.confirm: dict[str, int] = {**DEFAULT_CONFIRM, **config["warning"].get("confirm", {})}
        # While a sensor stays on: its pending timer, by (sensor, entity).
        self._runs: dict[tuple[str, str], Callable[[], None]] = {}
        notification = config["notification"]
        self.notify_view: str | None = notification.get("view")
        self.notify_warning: bool = notification["warning"]
        self.notify_trigger: bool = notification["trigger"]
        self.trigger_repeat: int = notification["trigger_repeat"]
        self.notify_disarm: bool = notification["disarm"]
        self._cancel_repeat: Callable[[], None] | None = None
        self._reminders = 0
        self._arming_actor: str | None = None
        self.zones = [_Zone(zone) for zone in config["zones"]]
        self.outputs = [_Output(output) for output in config["outputs"]]
        self.decisions: list[dict] = []

        self.count = 0
        self.last_detection: datetime | None = None
        self._cancel_expiry: Callable[[], None] | None = None
        self._cancel_sensors: Callable[[], None] | None = None
        self._last_state: str | None = None
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.alarm_rules")
        self._by_entity: dict[str, list[_Sensor]] = {}
        for zone in self.zones:
            for sensor in zone.sensors:
                for entity_id in sensor.entities:
                    self._by_entity.setdefault(entity_id, []).append(sensor)

    # --- lifecycle ----------------------------------------------------------

    async def async_load(self) -> None:
        saved = await self._store.async_load() or {}
        self._apply(saved)
        self.decisions = saved.get("decisions", [])[:MAX_DECISIONS]
        if self._by_entity:
            self._cancel_sensors = async_track_state_change_event(
                self.hass, list(self._by_entity), self._sensor_changed
            )
        self._last_state = self.panel.state
        self.panel.on_change(self._panel_changed)

    async def async_stop(self, _event=None) -> None:
        if self._cancel_sensors is not None:
            self._cancel_sensors()
        if self._cancel_expiry is not None:
            self._cancel_expiry()
        self._stop_repeat()
        self._reset_confirm()
        for output in self.outputs:
            if output.cancel is not None:
                output.cancel()
                output.cancel = None
        await self._store.async_save(self._saved())

    # --- settings (what the card edits) -------------------------------------

    def _apply(self, saved: dict) -> None:
        warning = saved.get("warning", {})
        self.limit = warning.get("limit", self.limit)
        self.window_minutes = warning.get("window_minutes", self.window_minutes)
        confirm = warning.get("confirm", {})
        for name in CONFIRM_FIELDS:
            value = confirm.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                try:
                    self.confirm[name] = _CONFIRM_VALUES[name](value)
                except vol.Invalid:
                    pass
        notify = saved.get("notification", {})
        self.notify_warning = notify.get("warning", self.notify_warning)
        self.notify_trigger = notify.get("trigger", self.notify_trigger)
        repeat = notify.get("trigger_repeat")
        if isinstance(repeat, int) and 0 <= repeat <= 3600:
            self.trigger_repeat = repeat
        by_id = {output.id: output for output in self.outputs}
        for output_id, values in saved.get("outputs", {}).items():
            if (output := by_id.get(output_id)) is None:
                continue
            output.warning_enabled = values.get("warning_enabled", output.warning_enabled)
            output.warning_seconds = values.get("warning_seconds", output.warning_seconds)
            output.trigger_enabled = values.get("trigger_enabled", output.trigger_enabled)
        zones = {zone.id: zone for zone in self.zones}
        for key, rules in saved.get("rules", {}).items():
            kind, _, ident = key.partition(":")
            if kind == "zone" and ident in zones:
                zones[ident].rules.update({m: r for m, r in rules.items() if m in MODES and r in RULES})
            elif kind == "sensor":
                zone_id, _, sensor_id = ident.partition(".")
                zone = zones.get(zone_id)
                sensor = next((s for s in zone.sensors if s.id == sensor_id), None) if zone else None
                if sensor is not None:
                    for mode, rule in rules.items():
                        if mode in MODES and (rule is None or rule in RULES):
                            sensor.rules[mode] = rule

    def _saved(self) -> dict[str, Any]:
        return {
            "warning": {
                "limit": self.limit,
                "window_minutes": self.window_minutes,
                "confirm": dict(self.confirm),
            },
            "notification": {
                "warning": self.notify_warning,
                "trigger": self.notify_trigger,
                "trigger_repeat": self.trigger_repeat,
            },
            "outputs": {
                output.id: {
                    "warning_enabled": output.warning_enabled,
                    "warning_seconds": output.warning_seconds,
                    "trigger_enabled": output.trigger_enabled,
                }
                for output in self.outputs
            },
            "rules": {
                **{f"zone:{zone.id}": dict(zone.rules) for zone in self.zones},
                **{
                    f"sensor:{sensor.key}": dict(sensor.rules)
                    for zone in self.zones
                    for sensor in zone.sensors
                },
            },
            "decisions": self.decisions,
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self.panel.notify_listeners()

    def set_rule(self, target: str, ident: str, mode: str, rule: str | None) -> None:
        if mode not in MODES or (rule is not None and rule not in RULES):
            raise ValueError("invalid rule")
        if target == "zone":
            zone = next((z for z in self.zones if z.id == ident), None)
            if zone is None or rule is None:
                raise ValueError("unknown zone")
            zone.rules[mode] = rule
        else:
            zone_id, _, sensor_id = ident.partition(".")
            sensor = next(
                (s for z in self.zones if z.id == zone_id for s in z.sensors if s.id == sensor_id),
                None,
            )
            if sensor is None:
                raise ValueError("unknown sensor")
            sensor.rules[mode] = rule
        self._changed()

    def set_output(self, ident: str, **values) -> None:
        output = next((o for o in self.outputs if o.id == ident), None)
        if output is None:
            raise ValueError("unknown output")
        for name, value in values.items():
            if value is not None:
                setattr(output, name, value)
        self._changed()

    def set_warning(
        self,
        limit: int | None = None,
        window_minutes: int | None = None,
        confirm_count: int | None = None,
        confirm_window_seconds: int | None = None,
        confirm_min_seconds: int | None = None,
        confirm_recount_seconds: int | None = None,
    ) -> None:
        if limit is not None:
            self.limit = limit
        if window_minutes is not None:
            self.window_minutes = window_minutes
        for name, value in (
            ("count", confirm_count),
            ("window_seconds", confirm_window_seconds),
            ("min_seconds", confirm_min_seconds),
            ("recount_seconds", confirm_recount_seconds),
        ):
            if value is not None:
                self.confirm[name] = value
        self._reschedule_expiry()
        self._changed()

    def set_notification(
        self,
        warning: bool | None = None,
        trigger: bool | None = None,
        trigger_repeat: int | None = None,
    ) -> None:
        if warning is not None:
            self.notify_warning = warning
        if trigger is not None:
            self.notify_trigger = trigger
        if trigger_repeat is not None:
            self.trigger_repeat = trigger_repeat
        if self.panel.state == "triggered":
            # Take the new setting for a trigger already going on.
            self._stop_repeat()
            self._start_repeat()
        self._changed()

    # --- detections ---------------------------------------------------------

    @callback
    def _sensor_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        entity_id = event.data["entity_id"]
        if new is None:
            return
        if new.state != "on":
            # Off (or gone): what was waiting for this sensor to stay on is over.
            for sensor in self._by_entity.get(entity_id, []):
                self._cancel_run((sensor.key, entity_id))
            return
        # Any way into "on" is a detection (off, unavailable, unknown); an
        # update that leaves it on, or an entity showing up already on, is not.
        if old is None or old.state == "on":
            return
        for sensor in self._by_entity.get(entity_id, []):
            self._detected(sensor, entity_id)

    def _detected(self, sensor: _Sensor, entity_id: str) -> None:
        # Only an armed panel reacts: not while arming (the person is leaving),
        # and not once it is already pending or triggered.
        if not self.panel.armed:
            return
        mode = self.panel.mode
        rule = sensor.rule(mode)
        values = {"sensor": sensor.name, "mode": self._text(f"mode_{mode}")}
        if rule == "off":
            # Off means off: nothing to decide, nothing to log.
            return
        if rule == "trigger":
            self._decide("trigger", self._text("trigger", **values))
            self.panel.trigger()
            return
        settings = self._confirm(sensor)
        if settings["count"] <= 1 and not settings["min_seconds"] and not settings["recount_seconds"]:
            # No gate: the detection is the warning, right now.
            self._warn(sensor, mode, values)
            return
        self._begin_run(sensor, entity_id, settings)

    # --- the confirmation gate ----------------------------------------------

    def _confirm(self, sensor: _Sensor) -> dict[str, int]:
        """A sensor's confirm settings: its own, else its zone's, else the global ones."""

        return {
            name: next(
                (
                    source[name]
                    for source in (sensor.confirm, sensor.zone.confirm)
                    if source.get(name) is not None
                ),
                self.confirm[name],
            )
            for name in CONFIRM_FIELDS
        }

    def _begin_run(self, sensor: _Sensor, entity_id: str, settings: dict[str, int]) -> None:
        """A warning sensor just went on: its first signal comes after `min_seconds`
        (right now when that is 0), then one more every `recount_seconds` while it stays on."""

        key = (sensor.key, entity_id)
        self._cancel_run(key)
        if settings["min_seconds"]:
            self._schedule_run(key, sensor, entity_id, settings["min_seconds"])
            return
        self._signal(sensor)
        if settings["recount_seconds"] and self.panel.armed:
            self._schedule_run(key, sensor, entity_id, settings["recount_seconds"])

    def _schedule_run(self, key: tuple[str, str], sensor: _Sensor, entity_id: str, seconds: int) -> None:
        self._runs[key] = async_call_later(
            self.hass,
            seconds,
            callback(lambda _now, k=key, s=sensor, e=entity_id: self._run_due(k, s, e)),
        )

    @callback
    def _run_due(self, key: tuple[str, str], sensor: _Sensor, entity_id: str) -> None:
        self._runs.pop(key, None)
        state = self.hass.states.get(entity_id)
        if state is None or state.state != "on" or not self.panel.armed:
            return
        self._signal(sensor)
        recount = self._confirm(sensor)["recount_seconds"]
        if recount and self.panel.armed:
            self._schedule_run(key, sensor, entity_id, recount)

    def _cancel_run(self, key: tuple[str, str]) -> None:
        if (cancel := self._runs.pop(key, None)) is not None:
            cancel()

    def _reset_confirm(self) -> None:
        """Forget what the gate was waiting for (disarmed, tripped, stopping)."""

        for cancel in list(self._runs.values()):
            cancel()
        self._runs.clear()
        for zone in self.zones:
            zone.signals.clear()

    def _signal(self, sensor: _Sensor) -> None:
        """One counted detection. The warning goes once its zone has `count` of them
        inside `window_seconds`; each warning starts the count over."""

        if not self.panel.armed:
            return
        mode = self.panel.mode
        if sensor.rule(mode) != "warning":
            return
        settings = self._confirm(sensor)
        now = dt_util.utcnow()
        zone = sensor.zone
        window = timedelta(seconds=settings["window_seconds"])
        zone.signals = [at for at in zone.signals if now - at <= window]
        zone.signals.append(now)
        if len(zone.signals) < settings["count"]:
            return
        zone.signals.clear()
        self._warn(sensor, mode, {"sensor": sensor.name, "mode": self._text(f"mode_{mode}")})

    def _resume_sensors(self) -> None:
        """The panel just armed: a sensor that is already on keeps counting, so one
        that is stuck on (a person who stayed, or a failure) still ends in an alarm.
        Only for sensors that recount; without it a sensor needs a new detection."""

        mode = self.panel.mode
        for sensor in (s for zone in self.zones for s in zone.sensors):
            if sensor.rule(mode) != "warning":
                continue
            settings = self._confirm(sensor)
            if not settings["recount_seconds"]:
                continue
            for entity_id in sensor.entities:
                state = self.hass.states.get(entity_id)
                if state is not None and state.state == "on":
                    self._begin_run(sensor, entity_id, settings)

    def _warn(self, sensor: _Sensor, mode: str, values: dict) -> None:
        now = dt_util.utcnow()
        if self.last_detection is not None and now > self.last_detection + timedelta(minutes=self.window_minutes):
            self.count = 0
        if self.count >= self.limit:
            self._decide("trigger", self._text("limit", **values))
            self.panel.trigger()
            return
        self.count += 1
        self.last_detection = now
        self._reschedule_expiry()
        fired = [output for output in self.outputs if output.warning_enabled]
        for output in fired:
            self._switch_on(output, output.warning_seconds)
        self._decide(
            "warning",
            self._text(
                "warning",
                **values,
                n=self.count,
                limit=self.limit,
            ),
        )
        if self.notify_warning:
            self._send(
                self._text("title_warning"),
                self._text("notify_warning", sensor=sensor.name, n=self.count, limit=self.limit),
            )
        self.panel.notify_listeners()

    @property
    def resets_at(self) -> datetime | None:
        if self.count == 0 or self.last_detection is None:
            return None
        return self.last_detection + timedelta(minutes=self.window_minutes)

    def _reschedule_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None
        if (at := self.resets_at) is not None:
            self._cancel_expiry = async_track_point_in_time(self.hass, self._expired, at)

    @callback
    def _expired(self, _now) -> None:
        self._cancel_expiry = None
        if self.count:
            self.count = 0
            self.last_detection = None
            self._decide("info", self._text("expired", minutes=self.window_minutes))
            self.panel.notify_listeners()

    # --- the panel moving ---------------------------------------------------

    @callback
    def _panel_changed(self, new: str) -> None:
        previous, self._last_state = self._last_state, new
        if previous is None or previous == new or self.panel.restoring:
            return
        if new != "triggered":
            self._stop_repeat()
        if not new.startswith("armed_"):
            self._reset_confirm()
        if new == "arming":
            self._arming_actor = self._actor_for("alarm_arm")
        if new.startswith("armed_"):
            actor = self._arming_actor if previous == "arming" else self._actor_for("alarm_arm")
            self._arming_actor = None
            self._decide(
                "info",
                self._text("armed", mode=self._text(f"mode_{new[len('armed_'):]}"), by=self._by(actor)),
            )
            self._resume_sensors()
        if new == "triggered":
            self._decide("trigger", self._text("triggered"))
            for output in self.outputs:
                if output.trigger_enabled:
                    self._switch_on(output, None)
            self._reminders = 0
            if self.notify_trigger:
                self._reminders = 1
                self._send(self._text("title_trigger"), self._text("notify_reminder", n=1))
                self._start_repeat()
        elif new == "disarmed":
            self.count = 0
            self.last_detection = None
            self._reschedule_expiry()
            had_outputs = any(output.on for output in self.outputs)
            for output in self.outputs:
                self._switch_off(output)
            self._arming_actor = None
            actor = self._actor_for("alarm_disarm")
            self._decide("info", self._text("disarmed", by=self._by(actor)))
            if self.notify_disarm and self.notify_trigger and previous != "arming":
                if actor:
                    message = self._text("notify_disarmed_by", actor=actor)
                elif self.panel.last_source == "auto":
                    message = self._text("notify_disarmed_auto")
                else:
                    message = self._text("notify_disarmed")
                self._send(self._text("title_disarmed"), message)

    # --- outputs ------------------------------------------------------------

    def _switch_on(self, output: _Output, seconds: int | None) -> None:
        if output.cancel is not None:
            output.cancel()
            output.cancel = None
        output.on = True
        self._call("turn_on", output)
        self.panel.notify_listeners()
        if seconds is not None:
            output.cancel = async_call_later(
                self.hass, seconds, callback(lambda _now, o=output: self._timed_out(o))
            )

    @callback
    def _timed_out(self, output: _Output) -> None:
        # A trigger that switches the output on replaces this timer (see
        # _switch_on), so a siren it turned on stays on until disarmed.
        output.cancel = None
        self._switch_off(output)

    def _switch_off(self, output: _Output) -> None:
        if output.cancel is not None:
            output.cancel()
            output.cancel = None
        if output.on:
            output.on = False
            self._call("turn_off", output)
            self.panel.notify_listeners()

    def _call(self, service: str, output: _Output) -> None:
        self.hass.async_create_task(
            self.hass.services.async_call(
                "homeassistant", service, {"entity_id": output.entities}, blocking=False
            )
        )

    def test_output(self, ident: str) -> None:
        """Run an output the way a warning would, so the person can hear and see it.

        Pressing it again while the output is on stops it.
        """

        if self.panel.state == "triggered":
            return
        if ident == "notification":
            self._send(self._text("title_test"), self._text("message_test"))
            return
        output = next((o for o in self.outputs if o.id == ident), None)
        if output is None:
            raise ValueError("unknown output")
        if output.on:
            # Pressed again while running: that is the stop button.
            self._switch_off(output)
            return
        self._switch_on(output, output.warning_seconds if output.warning_enabled else TEST_SECONDS)

    # --- notifications, decisions, logbook ----------------------------------

    def _text(self, key: str, **values) -> str:
        language = str(self.hass.config.language or "en").split("-")[0].lower()
        texts = TEXTS.get(language, TEXTS["en"])
        return texts.get(key, TEXTS["en"][key]).format(**values)

    def _decide(self, level: str, text: str) -> None:
        self.decisions.insert(0, {"time": dt_util.utcnow().isoformat(), "level": level, "text": text})
        del self.decisions[MAX_DECISIONS:]
        self._store.async_delay_save(self._saved, 2)
        if (entity_id := getattr(self.panel, "entity_id", None)) is not None:
            self.hass.bus.async_fire(
                "logbook_entry",
                {"name": self._text("logbook_name"), "message": text, "entity_id": entity_id, "domain": DOMAIN},
            )
        self.panel.notify_listeners()

    def _by(self, actor: str | None) -> str:
        """" · by Delfi", " · automatic", or nothing when nobody is known."""

        if actor:
            return self._text("by", actor=actor)
        if self.panel.last_source == "auto":
            return self._text("by_auto")
        return ""

    def _actor_for(self, service_prefix: str) -> str | None:
        """The Annika app user who just armed or disarmed the panel, when the app said so.

        The app stamps the call (see actor.py) and the stamp is claimed when the call
        starts, before the panel moves: that record is the one to read. A keypad, an
        automation or the auto-disarm leave no stamp, and then nobody is named.
        """

        last = (self.hass.data.get(f"{DOMAIN}_actor") or {}).get("last_action")
        action = last.action if last is not None else None
        if action is None or action.domain != "alarm_control_panel":
            return None
        if not action.service.startswith(service_prefix):
            return None
        if self.panel.entity_id and self.panel.entity_id not in action.entity_ids:
            return None
        if (dt_util.utcnow() - action.at).total_seconds() > 15:
            return None
        return action.actor.name

    def _start_repeat(self) -> None:
        """Notify again every `trigger_repeat` seconds for as long as the alarm is triggered."""

        if self._cancel_repeat is not None or not self.trigger_repeat or not self.notify_trigger:
            return
        self._cancel_repeat = async_track_time_interval(
            self.hass, self._repeat_trigger, timedelta(seconds=self.trigger_repeat)
        )

    def _stop_repeat(self) -> None:
        if self._cancel_repeat is not None:
            self._cancel_repeat()
            self._cancel_repeat = None

    @callback
    def _repeat_trigger(self, _now) -> None:
        if self.panel.state != "triggered" or not self.notify_trigger:
            self._stop_repeat()
            return
        self._reminders += 1
        self._send(self._text("title_trigger"), self._text("notify_reminder", n=self._reminders))

    def _send(self, title: str, message: str) -> None:
        if not self.notify_view:
            return
        self.hass.async_create_task(self._async_send(title, message))

    async def _async_send(self, title: str, message: str) -> None:
        try:
            await AnnikaEventClient(self.hass).async_send(
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "info",
                    "title": title,
                    "message": message,
                    "view": self.notify_view,
                }
            )
        except Exception:  # noqa: BLE001 — a missed notification must not stop the alarm
            _LOGGER.warning("Annika alarm: could not send the %s event", title)

    # --- what the card reads ------------------------------------------------

    def attributes(self) -> dict[str, Any]:
        return {
            "config": {
                "warning": {
                    "limit": self.limit,
                    "window_minutes": self.window_minutes,
                    "count": self.count,
                    "resets_at": self.resets_at.isoformat() if self.resets_at else None,
                    "confirm": dict(self.confirm),
                },
                "notification": {
                    "enabled": bool(self.notify_view),
                    "warning": self.notify_warning,
                    "trigger": self.notify_trigger,
                    "trigger_repeat": self.trigger_repeat,
                    "view": self.notify_view,
                },
                "outputs": [
                    {
                        "id": output.id,
                        "name": output.name,
                        "entities": output.entities,
                        "warning_enabled": output.warning_enabled,
                        "warning_seconds": output.warning_seconds,
                        "on": output.on,
                        "trigger_enabled": output.trigger_enabled,
                    }
                    for output in self.outputs
                ],
                "zones": [
                    {
                        "id": zone.id,
                        "name": zone.name,
                        "rules": zone.rules,
                        "confirm": zone.confirm,
                        "sensors": [
                            {
                                "id": sensor.key,
                                "name": sensor.name,
                                "detail": sensor.detail,
                                "entities": sensor.entities,
                                "rules": sensor.rules,
                                "confirm": sensor.confirm,
                            }
                            for sensor in zone.sensors
                        ],
                    }
                    for zone in self.zones
                ],
            },
            "decisions": self.decisions,
        }
