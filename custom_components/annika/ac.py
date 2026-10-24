"""Annika AC: the mode, target and fan of each air conditioner, the schedule that sets them and the season.

    annika:
      ac:
        name: Annika AC
        weather: weather.forecast_home          # optional: the cooling season follows it
        day_mode: binary_sensor.today_working_day  # a sensor (on: workday), weekend or days
        season:                                 # optional, and edited from the card
          on_above: 26                          # the AC is let on when the forecast stays above this...
          off_below: 22                         # ...and is turned off when it stays below this...
          hours: 12                             # ...for this many hours
        zones:
          - name: First Floor
            units:
              - entity: climate.main_bedroom
                name: Main Bedroom              # optional, and so is icon
              - climate.kids_bedroom
            schedule:                           # optional: where the schedule starts; the card edits it
              workday:
                - {time: "07:00", name: Day, mode: "off"}
                - {time: "21:30", name: Night, mode: cool, target: 24, fan: low}

The days are told apart like the heating's (see heating.py: day_mode).

What decides what a unit does, the first that applies:

1. Manual: somebody changed it (from the card, or with the remote or on the unit itself) and
   Annika leaves it alone until it is put back to Auto. Nothing else changes it.
2. The season: outside it, the units that are in Auto are off.
3. The schedule: the latest slot that started and applies to the unit (a mode, and a target
   and a fan when the mode has them). A unit that no slot applies to is off.

The general switch off turns every unit off, once, and then leaves them alone.
Turned on, everything is back in Auto.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

import voluptuous as vol

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .cameras import slug
from .const import DOMAIN
from .heating import (
    ADOPT_GRACE_SECONDS,
    ALL_DAYS,
    DAY_MODES,
    MAX_EVENTS,
    MAX_SLOTS,
    RESEND_SECONDS,
    STORE_VERSION,
    WEEKDAYS,
    _clock,
    _entity_of,
    _iso,
    _mode_of,
    _number,
    day_keys,
)

_LOGGER = logging.getLogger(__name__)

DATA_AC = f"{DOMAIN}_ac"

MIN_TARGET = 16.0
MAX_TARGET = 32.0
# An AC rounds what it is told: two targets this close are the same.
TOLERANCE = 0.5

OFF = "off"
MODES = ("off", "cool", "heat", "dry", "fan_only", "auto", "heat_cool")
# The modes that have a target temperature.
WITH_TARGET = ("cool", "heat", "auto", "heat_cool")
FANS = ("auto", "low", "medium", "high")

_CLIMATE = vol.All(cv.entity_id, vol.Match(r"^climate\."))
_WEATHER = vol.All(cv.entity_id, vol.Match(r"^weather\."))
_TARGET = vol.All(vol.Coerce(float), vol.Range(min=MIN_TARGET, max=MAX_TARGET))


def _check_slot(slot: dict) -> dict:
    if slot["mode"] in WITH_TARGET and slot.get("target") is None:
        raise vol.Invalid(f"a slot in {slot['mode']} mode needs a target")
    return slot


SLOT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("id"): cv.string,
            vol.Required("time"): _clock,
            vol.Optional("name", default=""): vol.All(cv.string, vol.Length(max=40)),
            vol.Required("mode"): vol.In(MODES),
            vol.Optional("target"): vol.Any(None, _TARGET),
            vol.Optional("fan"): vol.Any(None, cv.string),
            vol.Optional("units", default=[]): vol.All(cv.ensure_list, [_CLIMATE]),
        }
    ),
    _check_slot,
)

SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional(day, default=[]): vol.All(cv.ensure_list, [SLOT_SCHEMA], vol.Length(max=MAX_SLOTS))
        for day in ALL_DAYS
    }
)

UNIT_SCHEMA = vol.Any(
    _CLIMATE,
    vol.Schema(
        {
            vol.Required("entity"): _CLIMATE,
            vol.Optional("name"): cv.string,
            vol.Optional("icon"): cv.string,
        }
    ),
)

ZONE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("units"): vol.All(cv.ensure_list, [UNIT_SCHEMA], vol.Length(min=1)),
        vol.Optional("schedule", default={}): SCHEDULE_SCHEMA,
    }
)

SEASON_SCHEMA = vol.Schema(
    {
        vol.Optional("enabled", default=True): cv.boolean,
        vol.Optional("on_above", default=26): vol.All(vol.Coerce(float), vol.Range(min=-30, max=60)),
        vol.Optional("off_below", default=22): vol.All(vol.Coerce(float), vol.Range(min=-30, max=60)),
        vol.Optional("hours", default=12): vol.All(vol.Coerce(int), vol.Range(min=1, max=72)),
    }
)


def _check_references(config: dict) -> dict:
    keys = day_keys(_mode_of(config))
    zones: set[str] = set()
    seen: set[str] = set()
    for zone in config["zones"]:
        zone_id = slug(zone["name"])
        if zone_id in zones:
            raise vol.Invalid(f"zone names must be different: {zone['name']}")
        zones.add(zone_id)
        members = [_entity_of(item) for item in zone["units"]]
        for entity in members:
            if entity in seen:
                raise vol.Invalid(f"{entity} is in more than one zone")
            seen.add(entity)
        for day in ALL_DAYS:
            if day not in keys and zone["schedule"][day]:
                raise vol.Invalid(f"zone {zone['name']} has a schedule for {day}, which day_mode {_mode_of(config)} does not use")
        for day in keys:
            for slot in zone["schedule"][day]:
                for entity in slot["units"]:
                    if entity not in members:
                        raise vol.Invalid(f"{entity} is in a slot of {zone['name']} but not in the zone")
    if config["season"]["on_above"] < config["season"]["off_below"]:
        raise vol.Invalid("season on_above must not be below off_below")
    return config


AC_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name", default="Annika AC"): cv.string,
            vol.Optional("weather"): _WEATHER,
            vol.Optional("day_mode"): vol.Any(vol.In(("weekend", "days")), cv.entity_id),
            # Whether a change made on a unit itself (the remote, the unit) is kept as a manual one.
            vol.Optional("adopt_manual", default=True): cv.boolean,
            vol.Optional("season", default={}): SEASON_SCHEMA,
            vol.Required("zones"): vol.All(cv.ensure_list, [ZONE_SCHEMA], vol.Length(min=1)),
        }
    ),
    _check_references,
)


class AcError(ValueError):
    """What is asked of the AC and cannot be. `key` is the translation key."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two settings ({mode, target, fan}) are the same thing."""

    if a["mode"] != b["mode"]:
        return False
    if a["mode"] in WITH_TARGET and not _close(a.get("target"), b.get("target")):
        return False
    return a["mode"] == OFF or a.get("fan") in (None, b.get("fan")) or b.get("fan") is None


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= TOLERANCE


class _Unit:
    def __init__(self, hass: HomeAssistant, item: Any) -> None:
        self.entity: str = _entity_of(item)
        config = {} if isinstance(item, str) else item
        self.id = slug(self.entity)
        self.given_name: str | None = config.get("name")
        self.icon: str | None = config.get("icon")
        self._hass = hass

    @property
    def name(self) -> str:
        if self.given_name:
            return self.given_name
        state = self._hass.states.get(self.entity)
        name = (state.attributes.get("friendly_name") if state else None) or self.entity
        for suffix in (" AC", " Ac", " ac", " A/C", " Air Conditioner"):
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[: -len(suffix)]
        return name.strip()


class _Zone:
    def __init__(self, hass: HomeAssistant, config: dict, keys: tuple[str, ...]) -> None:
        self.id = slug(config["name"])
        self.name: str = config["name"]
        self.units = [_Unit(hass, item) for item in config["units"]]
        self.schedule: dict[str, list[dict[str, Any]]] = {
            day: [self._slot(slot) for slot in config["schedule"][day]] for day in keys
        }

    @staticmethod
    def _slot(slot: dict) -> dict[str, Any]:
        mode = slot["mode"]
        return {
            "id": slot.get("id") or uuid.uuid4().hex[:8],
            "time": slot["time"],
            "name": slot.get("name", ""),
            "mode": mode,
            "target": float(slot["target"]) if mode in WITH_TARGET and slot.get("target") is not None else None,
            "fan": slot.get("fan") if mode not in (OFF,) else None,
            "units": list(dict.fromkeys(slot.get("units") or [])),
        }


class AnnikaAc:
    """The zones, their schedules and the season."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.weather: str | None = config.get("weather")
        self.day_mode: str = _mode_of(config)
        self.workday_entity: str | None = config["day_mode"] if self.day_mode == "sensor" else None
        self.day_keys: tuple[str, ...] = day_keys(self.day_mode)
        self.adopt: bool = config["adopt_manual"]
        self.zones = [_Zone(hass, zone, self.day_keys) for zone in config["zones"]]
        self.enabled = True
        self.season: dict[str, Any] = {
            **SEASON_SCHEMA(config["season"]),
            "active": None,
            "hot_since": None,
            "cool_since": None,
        }
        # The units somebody took over, until they are put back to Auto.
        self.manual: set[str] = set()
        self.events: list[dict[str, Any]] = []

        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.ac")
        self._zones = {zone.id: zone for zone in self.zones}
        self._units = {unit.entity: (zone, unit) for zone in self.zones for unit in zone.units}
        self._day_types: dict[str, str] = {}
        self._listeners: list[Callable[[], None]] = []
        self._cancels: list[CALLBACK_TYPE] = []
        self._commanded: dict[str, datetime] = {}
        self._keys: dict[str, dict] = {}
        self._started = False
        self._pending = False
        self._running = False

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._apply(await self._store.async_load() or {})
        entities = list(self._units)
        entities += [entity for entity in (self.weather, self.workday_entity) if entity]
        self._cancels.append(async_track_state_change_event(self.hass, entities, self._state_changed))
        self._cancels.append(async_track_time_change(self.hass, self._tick, second=0))
        self._started = True
        await self._async_evaluate()

    async def async_stop(self, _event=None) -> None:
        self._started = False
        for cancel in self._cancels:
            cancel()
        self._cancels = []
        await self._store.async_save(self._saved())

    # --- storage ------------------------------------------------------------

    def _apply(self, saved: dict) -> None:
        self.enabled = saved.get("enabled", True) is not False
        season = saved.get("season")
        if isinstance(season, dict):
            try:
                values = SEASON_SCHEMA({key: season[key] for key in ("enabled", "on_above", "off_below", "hours") if key in season})
                if values["on_above"] >= values["off_below"]:
                    self.season.update(values)
            except vol.Invalid:
                pass
            if season.get("active") in (True, False):
                self.season["active"] = season["active"]
            for key in ("hot_since", "cool_since"):
                if isinstance(season.get(key), str) and dt_util.parse_datetime(season[key]):
                    self.season[key] = season[key]
        for zone_id, schedule in (saved.get("schedules") or {}).items():
            zone = self._zones.get(zone_id)
            if zone is None:
                continue
            try:
                parsed = SCHEDULE_SCHEMA(schedule)
            except vol.Invalid:
                continue
            members = {unit.entity for unit in zone.units}
            for day in self.day_keys:
                # A day the store has never saved keeps what the configuration says.
                if day in schedule:
                    zone.schedule[day] = sorted(
                        (_Zone._slot({**slot, "units": [e for e in slot["units"] if e in members]}) for slot in parsed[day]),
                        key=lambda slot: slot["time"],
                    )
        self.manual = {entity for entity in (saved.get("manual") or []) if entity in self._units}
        self.events = [event for event in saved.get("events", []) if isinstance(event, dict)][:MAX_EVENTS]
        days = saved.get("day_types")
        if isinstance(days, dict):
            self._day_types = {key: value for key, value in days.items() if value in ALL_DAYS}

    def _saved(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "season": {key: self.season[key] for key in ("enabled", "on_above", "off_below", "hours", "active", "hot_since", "cool_since")},
            "schedules": {zone.id: {day: [dict(slot) for slot in zone.schedule[day]] for day in self.day_keys} for zone in self.zones},
            "manual": sorted(self.manual),
            "events": list(self.events),
            "day_types": dict(sorted(self._day_types.items())[-4:]),
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self.notify()

    # --- listeners ----------------------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _log(self, kind: str, **values: Any) -> None:
        self.events.insert(0, {"time": dt_util.utcnow().isoformat(), "kind": kind, **values})
        del self.events[MAX_EVENTS:]

    # --- the day ------------------------------------------------------------

    def _day_type(self, day: date) -> str:
        if self.day_mode == "days":
            return WEEKDAYS[day.weekday()]
        if self.day_mode == "sensor" and day == dt_util.now().date():
            state = self.hass.states.get(self.workday_entity) if self.workday_entity else None
            if state is not None and state.state in (STATE_ON, STATE_OFF):
                kind = "workday" if state.state == STATE_ON else "non_workday"
                self._day_types[day.isoformat()] = kind
                return kind
        elif self.day_mode == "sensor" and (kind := self._day_types.get(day.isoformat())):
            return kind
        return "workday" if day.weekday() < 5 else "non_workday"

    @staticmethod
    def _start(day: date, slot: dict[str, Any], tzinfo) -> datetime:
        hours, minutes = (int(part) for part in slot["time"].split(":"))
        return datetime.combine(day, time(hours, minutes), tzinfo=tzinfo)

    def _candidates(self, zone: _Zone, unit: _Unit, now: datetime):
        """The slots that apply to a unit and have started, the latest first."""

        for back in (0, 1):
            day = (now - timedelta(days=back)).date()
            for slot in sorted(zone.schedule[self._day_type(day)], key=lambda item: item["time"], reverse=True):
                if slot["units"] and unit.entity not in slot["units"]:
                    continue
                start = self._start(day, slot, now.tzinfo)
                if start <= now:
                    yield start, slot

    @staticmethod
    def _settings(slot: dict[str, Any]) -> dict[str, Any]:
        return {"mode": slot["mode"], "target": slot["target"], "fan": slot["fan"]}

    def _desired(self, zone: _Zone, unit: _Unit, now: datetime) -> dict[str, Any]:
        """What a unit should be at ({mode, target, fan}), and why."""

        if unit.entity in self.manual:
            return {**self._current(unit.entity), "source": "manual", "slot": None, "start": None}
        if self.season["active"] is False:
            return {"mode": OFF, "target": None, "fan": None, "source": "season", "slot": None, "start": None}
        for start, slot in self._candidates(zone, unit, now):
            return {**self._settings(slot), "source": "slot", "slot": slot, "start": start}
        return {"mode": OFF, "target": None, "fan": None, "source": "none", "slot": None, "start": None}

    # --- the season -----------------------------------------------------------

    def _update_season(self, now: datetime) -> bool:
        season = self.season
        before = (season["active"], season["hot_since"], season["cool_since"])
        if not (self.weather and season["enabled"]):
            season["active"] = True
            season["hot_since"] = season["cool_since"] = None
            return before != (True, None, None)
        state = self.hass.states.get(self.weather)
        temperature = _number(state.attributes.get("temperature")) if state is not None else None
        if temperature is None:
            return False
        hold = timedelta(hours=season["hours"])
        if temperature > season["on_above"]:
            season["cool_since"] = None
            season["hot_since"] = season["hot_since"] or now.isoformat()
        elif temperature < season["off_below"]:
            season["hot_since"] = None
            season["cool_since"] = season["cool_since"] or now.isoformat()
        else:
            season["hot_since"] = season["cool_since"] = None
        if season["active"] is None:
            season["active"] = temperature > (season["on_above"] + season["off_below"]) / 2
        elif season["hot_since"] and now - dt_util.parse_datetime(season["hot_since"]) >= hold:
            season["active"] = True
        elif season["cool_since"] and now - dt_util.parse_datetime(season["cool_since"]) >= hold:
            season["active"] = False
        if before[0] is not None and season["active"] != before[0]:
            self._log("season", on=season["active"], temperature=temperature)
        return before != (season["active"], season["hot_since"], season["cool_since"])

    # --- talking to the units -------------------------------------------------------

    def _current(self, entity: str) -> dict[str, Any]:
        """What a unit is set to now: {mode, target, fan}."""

        state = self.hass.states.get(entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return {"mode": OFF, "target": None, "fan": None}
        mode = state.state
        target = _number(state.attributes.get("temperature")) if mode in WITH_TARGET else None
        return {"mode": mode, "target": target, "fan": state.attributes.get("fan_mode")}

    def _available(self, entity: str) -> bool:
        state = self.hass.states.get(entity)
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    async def _call(self, service: str, entity: str, **data: Any) -> None:
        try:
            await self.hass.services.async_call("climate", service, {"entity_id": entity, **data}, blocking=True)
        except HomeAssistantError as error:
            _LOGGER.warning("Annika AC could not %s %s: %s", service, entity, error)

    async def _ensure(self, unit: _Unit, desired: dict[str, Any], force: bool = False) -> None:
        if not self._available(unit.entity):
            return
        state = self.hass.states.get(unit.entity)
        current = self._current(unit.entity)
        mode = desired["mode"]
        if mode not in (state.attributes.get("hvac_modes") or MODES) and mode != OFF:
            return
        fan = desired.get("fan")
        fans = state.attributes.get("fan_modes") or []
        wants_fan = mode != OFF and fan in fans and state.attributes.get("fan_mode") != fan
        wants_mode = current["mode"] != mode
        wants_target = mode in WITH_TARGET and desired.get("target") is not None and not _close(current["target"], desired["target"])
        if not (wants_mode or wants_target or wants_fan):
            return
        now = dt_util.utcnow()
        last = self._commanded.get(unit.entity)
        if not force and last is not None and (now - last).total_seconds() < RESEND_SECONDS:
            return
        self._commanded[unit.entity] = now
        if mode in WITH_TARGET and desired.get("target") is not None and (wants_mode or wants_target):
            await self._call("set_temperature", unit.entity, temperature=desired["target"], hvac_mode=mode)
        elif wants_mode:
            await self._call("set_hvac_mode", unit.entity, hvac_mode=mode)
        if wants_fan:
            await self._call("set_fan_mode", unit.entity, fan_mode=fan)

    # --- evaluating -------------------------------------------------------------

    @callback
    def _tick(self, _now) -> None:
        self._schedule_evaluation()

    @callback
    def _schedule_evaluation(self) -> None:
        if not self._started:
            return
        if self._running:
            self._pending = True
            return
        self.hass.async_create_task(self._async_evaluate())

    @callback
    def _state_changed(self, event: Event) -> None:
        entity = event.data["entity_id"]
        if entity in self._units:
            self._unit_changed(entity, event.data.get("old_state"), event.data.get("new_state"))
        self._schedule_evaluation()

    @staticmethod
    def _valid(state) -> bool:
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    def _unit_changed(self, entity: str, old, new) -> None:
        """A change made on the unit itself (the remote, the unit): it takes the unit over."""

        if not (self.adopt and self.enabled and self._started and entity not in self.manual):
            return
        if not (self._valid(old) and self._valid(new)):
            return
        keys = ("temperature", "fan_mode", "swing_mode", "swing_horizontal_mode")
        if old.state == new.state and all(old.attributes.get(key) == new.attributes.get(key) for key in keys):
            return
        last = self._commanded.get(entity)
        if last is not None and (dt_util.utcnow() - last).total_seconds() < ADOPT_GRACE_SECONDS:
            return
        zone, unit = self._units[entity]
        desired = self._desired(zone, unit, dt_util.now())
        if desired["source"] != "manual" and _same(self._current(entity), desired) and all(
            old.attributes.get(key) == new.attributes.get(key) for key in ("swing_mode", "swing_horizontal_mode")
        ):
            return
        self.manual.add(entity)
        self._log("manual", zone=zone.id, unit=entity, **self._brief(self._current(entity)), external=True)
        self._changed()

    @staticmethod
    def _brief(settings: dict[str, Any]) -> dict[str, Any]:
        return {"mode": settings["mode"], "target": settings.get("target"), "fan": settings.get("fan")}

    async def _async_evaluate(self, force: bool = False) -> None:
        if not self._started or not self.enabled:
            return
        if self._running:
            self._pending = True
            return
        self._running = True
        try:
            while True:
                self._pending = False
                await self._evaluate_once(force)
                force = False
                if not self._pending:
                    break
        finally:
            self._running = False

    async def _evaluate_once(self, force: bool) -> None:
        now = dt_util.now()
        changed = self._update_season(now)
        for zone in self.zones:
            slots: dict[str, tuple] = {}
            primary = None
            for unit in zone.units:
                desired = self._desired(zone, unit, now)
                if desired["source"] == "slot":
                    slots[unit.entity] = (desired["slot"]["id"], desired["mode"], desired["target"])
                    primary = primary or desired
                if desired["source"] != "manual":
                    await self._ensure(unit, desired, force)
            previous = self._keys.get(zone.id)
            self._keys[zone.id] = slots
            if previous is not None and primary is not None and any(previous.get(e) != v for e, v in slots.items()):
                self._log("slot", zone=zone.id, name=primary["slot"]["name"], **self._brief(primary))
                changed = True
        if changed:
            self._changed()
        else:
            self.notify()

    # --- what the entities and the services do -----------------------------------

    async def async_set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        self._log("master", on=enabled)
        if not enabled:
            for zone in self.zones:
                for unit in zone.units:
                    await self._ensure(unit, {"mode": OFF, "target": None, "fan": None}, force=True)
            self._changed()
            return
        # Turned on: every unit starts again from its schedule.
        self.manual.clear()
        self._keys.clear()
        self._changed()
        await self._async_evaluate(force=True)

    def _resolve(self, zone: str | None, units: list[str] | None) -> list[tuple[_Zone, _Unit]]:
        found: list[tuple[_Zone, _Unit]] = []
        if zone:
            target = self._zones.get(zone) or self._zones.get(slug(zone))
            if target is None:
                raise AcError("unknown_zone", zone=zone)
            found = [(target, unit) for unit in target.units]
        if units:
            wanted = []
            for entity in units:
                if entity not in self._units:
                    raise AcError("unknown_unit", unit=entity)
                wanted.append(self._units[entity])
            found = [pair for pair in found if pair[1].entity in units] if zone else wanted
        return found

    async def async_set_manual(
        self,
        zone: str | None = None,
        units: list[str] | None = None,
        mode: str | None = None,
        target: float | None = None,
        fan: str | None = None,
        swing: str | None = None,
        swing_horizontal: str | None = None,
    ) -> None:
        """Take a zone or some units over: what is given is set on them, and Annika leaves them alone."""

        if not self.enabled:
            raise AcError("disabled")
        if not zone and not units:
            raise AcError("unknown_target")
        if mode is not None and mode not in MODES:
            raise AcError("invalid_mode", mode=mode)
        pairs = self._resolve(zone, units)
        number = None
        if target is not None:
            number = _number(target)
            if number is None:
                raise AcError("invalid_target")
            number = round(max(MIN_TARGET, min(MAX_TARGET, number)) * 2) / 2
        touched: list[tuple[_Zone, _Unit]] = []
        for owner, unit in pairs:
            current = self._current(unit.entity)
            final = mode or current["mode"]
            # A bare target does not reach a unit that is off or has no target to set.
            if mode is None and fan is None and swing is None and swing_horizontal is None and final not in WITH_TARGET:
                continue
            touched.append((owner, unit))
            self.manual.add(unit.entity)
            if not self._available(unit.entity):
                continue
            state = self.hass.states.get(unit.entity)
            modes = state.attributes.get("hvac_modes") or []
            if mode is not None and modes and mode not in modes:
                continue
            if final in WITH_TARGET and (number is not None or (mode is not None and mode != current["mode"])):
                value = number if number is not None else current["target"]
                if value is None:
                    value = number if number is not None else 24.0
                self._commanded[unit.entity] = dt_util.utcnow()
                await self._call("set_temperature", unit.entity, temperature=value, hvac_mode=final)
            elif mode is not None and mode != current["mode"]:
                self._commanded[unit.entity] = dt_util.utcnow()
                await self._call("set_hvac_mode", unit.entity, hvac_mode=mode)
            if fan is not None and fan in (state.attributes.get("fan_modes") or []):
                self._commanded[unit.entity] = dt_util.utcnow()
                await self._call("set_fan_mode", unit.entity, fan_mode=fan)
            if swing is not None and swing in (state.attributes.get("swing_modes") or []):
                self._commanded[unit.entity] = dt_util.utcnow()
                await self._call("set_swing_mode", unit.entity, swing_mode=swing)
            if swing_horizontal is not None and swing_horizontal in (state.attributes.get("swing_horizontal_modes") or []):
                self._commanded[unit.entity] = dt_util.utcnow()
                await self._call("set_swing_horizontal_mode", unit.entity, swing_horizontal_mode=swing_horizontal)
        if zone and not units and touched:
            self._log("manual", zone=touched[0][0].id, unit=None, mode=mode, target=number, fan=fan, external=False)
        else:
            for owner, unit in touched:
                self._log("manual", zone=owner.id, unit=unit.entity, mode=mode, target=number, fan=fan, external=False)
        self._changed()

    async def async_set_auto(self, zone: str | None = None, units: list[str] | None = None) -> None:
        """Back to what the schedule says: a zone, some units, or everything."""

        if not zone and not units:
            pairs = list(self._units.values())
        else:
            pairs = self._resolve(zone, units)
        released = [pair for pair in pairs if pair[1].entity in self.manual]
        for _zone, unit in released:
            self.manual.discard(unit.entity)
        if released:
            if zone and not units:
                self._log("auto", zone=released[0][0].id, unit=None)
            else:
                for owner, unit in released:
                    self._log("auto", zone=owner.id, unit=unit.entity)
        self._changed()
        await self._async_evaluate(force=True)

    async def async_set_schedule(self, zone: str, day: str, slots: list[dict[str, Any]]) -> None:
        target = self._zones.get(zone) or self._zones.get(slug(zone))
        if target is None:
            raise AcError("unknown_zone", zone=zone)
        if day not in self.day_keys:
            raise AcError("invalid_slot", error=f"day must be one of {', '.join(self.day_keys)}")
        members = {unit.entity for unit in target.units}
        try:
            parsed = vol.Schema(vol.All([SLOT_SCHEMA], vol.Length(max=MAX_SLOTS)))(list(slots))
        except vol.Invalid as error:
            raise AcError("invalid_slot", error=str(error)) from error
        for slot in parsed:
            for entity in slot["units"]:
                if entity not in members:
                    raise AcError("unknown_unit", unit=entity)
        target.schedule[day] = sorted((_Zone._slot(slot) for slot in parsed), key=lambda slot: slot["time"])
        self._changed()
        await self._async_evaluate()

    async def async_set_season(self, **values: Any) -> None:
        merged = {key: self.season[key] for key in ("enabled", "on_above", "off_below", "hours")}
        merged.update({key: value for key, value in values.items() if value is not None and key in merged})
        try:
            merged = SEASON_SCHEMA(merged)
        except vol.Invalid as error:
            raise AcError("invalid_season", error=str(error)) from error
        if merged["on_above"] < merged["off_below"]:
            raise AcError("invalid_season", error="on_above must not be below off_below")
        self.season.update(merged)
        self.season["hot_since"] = self.season["cool_since"] = None
        self.season["active"] = None if merged["enabled"] and self.weather else True
        self._changed()
        await self._async_evaluate()

    # --- what the card reads ----------------------------------------------------

    def _entity_ids(self) -> dict[str, str | None]:
        registry = er.async_get(self.hass)
        return {"master": registry.async_get_entity_id("switch", DOMAIN, f"{DOMAIN}_ac_enabled")}

    @staticmethod
    def _slot_view(slot: dict[str, Any]) -> dict[str, Any]:
        return dict(slot, units=list(slot["units"]))

    def _zone_state(self, zone: _Zone, now: datetime) -> dict[str, Any]:
        desired = {unit.entity: self._desired(zone, unit, now) for unit in zone.units}
        targets = [item["target"] for item in desired.values() if item["mode"] != OFF and item["target"] is not None]
        target: float | None = None
        if targets:
            target = max(set(targets), key=lambda value: (targets.count(value), -targets.index(value)))
        primary = next((item for item in desired.values() if item["source"] == "slot"), None)
        today = now.date()
        upcoming = []
        for offset in (0, 1):
            day = today + timedelta(days=offset)
            for slot in sorted(zone.schedule[self._day_type(day)], key=lambda item: item["time"]):
                start = self._start(day, slot, now.tzinfo)
                if start > now:
                    upcoming.append((start, slot))
        end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=now.tzinfo)
        manual = [entity for entity, item in desired.items() if item["source"] == "manual"]
        return {
            "target": target,
            "manual": manual,
            "slot": {
                "id": primary["slot"]["id"],
                "name": primary["slot"]["name"],
                "since": _iso(primary["start"]),
                "mode": primary["slot"]["mode"],
                "target": primary["slot"]["target"],
            } if primary else None,
            "next": {
                "id": upcoming[0][1]["id"],
                "name": upcoming[0][1]["name"],
                "time": _iso(upcoming[0][0]),
                "mode": upcoming[0][1]["mode"],
                "target": upcoming[0][1]["target"],
            } if upcoming else None,
            "plan": [
                {"time": _iso(start), "name": slot["name"], "mode": slot["mode"], "target": slot["target"]}
                for start, slot in upcoming
                if start < end
            ],
            "units": {
                entity: {
                    "mode": item["mode"],
                    "target": item["target"],
                    "fan": item["fan"],
                    "source": item["source"],
                    "slot": item["slot"]["id"] if item["slot"] else None,
                }
                for entity, item in desired.items()
            },
        }

    @property
    def status(self) -> str:
        if not self.enabled:
            return "off"
        if self.season["active"] is False and not self.manual:
            return "standby"
        for entity in self._units:
            state = self.hass.states.get(entity)
            if state is not None and state.attributes.get("hvac_action") in ("cooling", "heating", "drying", "fan"):
                return "running"
        return "idle"

    def attributes(self) -> dict[str, Any]:
        now = dt_util.now()
        return {
            "config": {
                "enabled": self.enabled,
                "weather": self.weather,
                "day_mode": self.day_mode,
                "day_keys": list(self.day_keys),
                "day_type": self._day_type(now.date()),
                "season": {key: self.season[key] for key in ("enabled", "on_above", "off_below", "hours", "active")},
                "entities": self._entity_ids(),
                "zones": [
                    {
                        "id": zone.id,
                        "name": zone.name,
                        "units": [{"id": unit.id, "entity": unit.entity, "name": unit.name, "icon": unit.icon} for unit in zone.units],
                        "schedule": {day: [self._slot_view(slot) for slot in zone.schedule[day]] for day in self.day_keys},
                    }
                    for zone in self.zones
                ],
            },
            "state": {zone.id: self._zone_state(zone, now) for zone in self.zones},
            "events": [dict(event) for event in self.events],
        }
