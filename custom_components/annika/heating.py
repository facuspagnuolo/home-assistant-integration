"""Annika heating: the target of each thermostat, the schedule that sets it and the boilers that follow.

    annika:
      heating:
        name: Annika Heating
        weather: weather.forecast_home          # optional: the heating season follows it
        workday: binary_sensor.today_working_day  # optional: tells workdays from the rest (default Mon-Fri)
        day_mode: sensor                        # optional: sensor | weekend | days (see below)
        season:                                 # optional, and edited from the card
          on_below: 14                          # heating starts when the forecast stays below this...
          off_above: 18                         # ...and stops when it stays above this...
          hours: 12                             # ...for this many hours
        boilers:
          - name: Boiler
            entity: switch.heating
        zones:
          - name: Ground Floor
            boiler: Boiler                      # optional with a single boiler
            thermostats:
              - entity: climate.kitchen_thermostat
                name: Kitchen                   # optional, and so is icon
              - climate.living_thermostat
            schedule:                           # optional: where the schedule starts; the card edits it
              workday:
                - {time: "04:30", name: Morning, target: 20}
                - {time: "17:00", name: Afternoon, target: 22}
                - time: "22:00"
                  name: Night
                  target: 16
                  motion: {sensors: [binary_sensor.ground_motion], minutes: 60}
              non_workday:
                - {time: "05:30", name: Morning, target: 20}

Telling the days apart (day_mode): `sensor` has two schedules, workday and non_workday, and
the sensor above says which one today is (Monday to Friday when there is none or it is
unavailable); `weekend` has the same two but Monday-Friday against the weekend, whatever the
sensor says; `days` has a schedule for each day of the week (monday ... sunday). Without
day_mode it is `sensor` when a workday sensor is given and `weekend` when not.

What decides a thermostat's target, the first that applies:

1. Manual: somebody set it (from the card, or on the thermostat itself) and it stays until
   it is put back to Auto. Nothing else changes it, the season included.
2. The heating season: outside it, the thermostats that are in Auto are off.
3. The schedule: the latest slot that started and applies to the thermostat. A slot may have
   a condition (the motion sensors have been off for some minutes); until it is met, the
   slot before it stays in effect. A thermostat that no slot applies to is off.

The thermostats do the rest: they heat while the room is colder than the target and idle
when it is not. A boiler is on while any thermostat of its zones asks for heat, and off
when none does. Nothing to configure there.

The general switch off turns every thermostat and boiler off, once, and then leaves them alone.
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

_LOGGER = logging.getLogger(__name__)

DATA_HEATING = f"{DOMAIN}_heating"

STORE_VERSION = 1
MAX_EVENTS = 50
MAX_SLOTS = 12

MIN_TARGET = 5.0
MAX_TARGET = 35.0
# Two setpoints this close are the same: thermostats round what they are told.
TOLERANCE = 0.25
# A thermostat that does not follow is told again after this long.
RESEND_SECONDS = 300
# A change on a thermostat this soon after Annika wrote to it is the thermostat answering.
ADOPT_GRACE_SECONDS = 60

DAY_TYPES = ("workday", "non_workday")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ALL_DAYS = DAY_TYPES + WEEKDAYS
# How the days are told apart: by a sensor (workday or not), by Monday-Friday against the
# weekend, or one schedule per day of the week.
DAY_MODES = ("sensor", "weekend", "days")


def day_keys(mode: str) -> tuple[str, ...]:
    return WEEKDAYS if mode == "days" else DAY_TYPES

OFF = "off"

MOTION_CLASSES = ("motion", "occupancy", "presence")

_CLIMATE = vol.All(cv.entity_id, vol.Match(r"^climate\."))
_BINARY = vol.All(cv.entity_id, vol.Match(r"^binary_sensor\."))
_WEATHER = vol.All(cv.entity_id, vol.Match(r"^weather\."))


def _clock(value: Any) -> str:
    return cv.time(value).strftime("%H:%M")


_TARGET = vol.All(vol.Coerce(float), vol.Range(min=MIN_TARGET, max=MAX_TARGET))

MOTION_SCHEMA = vol.Schema(
    {
        vol.Required("sensors"): vol.All(cv.ensure_list, [_BINARY], vol.Length(min=1)),
        vol.Optional("minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
    }
)

SLOT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Required("time"): _clock,
        vol.Optional("name", default=""): vol.All(cv.string, vol.Length(max=40)),
        vol.Required("target"): _TARGET,
        vol.Optional("thermostats", default=[]): vol.All(cv.ensure_list, [_CLIMATE]),
        vol.Optional("motion"): vol.Any(None, MOTION_SCHEMA),
    }
)

SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional(day, default=[]): vol.All(cv.ensure_list, [SLOT_SCHEMA], vol.Length(max=MAX_SLOTS))
        for day in ALL_DAYS
    }
)

THERMOSTAT_SCHEMA = vol.Any(
    _CLIMATE,
    vol.Schema(
        {
            vol.Required("entity"): _CLIMATE,
            vol.Optional("name"): cv.string,
            vol.Optional("icon"): cv.string,
        }
    ),
)

BOILER_SCHEMA = vol.Schema({vol.Required("name"): cv.string, vol.Required("entity"): cv.entity_id})

ZONE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("boiler"): cv.string,
        vol.Required("thermostats"): vol.All(cv.ensure_list, [THERMOSTAT_SCHEMA], vol.Length(min=1)),
        vol.Optional("schedule", default={}): SCHEDULE_SCHEMA,
    }
)

SEASON_SCHEMA = vol.Schema(
    {
        vol.Optional("enabled", default=True): cv.boolean,
        vol.Optional("on_below", default=14): vol.All(vol.Coerce(float), vol.Range(min=-30, max=50)),
        vol.Optional("off_above", default=18): vol.All(vol.Coerce(float), vol.Range(min=-30, max=50)),
        vol.Optional("hours", default=12): vol.All(vol.Coerce(int), vol.Range(min=1, max=72)),
    }
)


def _entity_of(item: Any) -> str:
    return item if isinstance(item, str) else item["entity"]


def _mode_of(config: dict) -> str:
    return config.get("day_mode") or ("sensor" if config.get("workday") else "weekend")


def _check_references(config: dict) -> dict:
    keys = day_keys(_mode_of(config))
    boilers = {slug(boiler["name"]) for boiler in config["boilers"]}
    if len(boilers) != len(config["boilers"]):
        raise vol.Invalid("boiler names must be different")
    zones: set[str] = set()
    seen: set[str] = set()
    for zone in config["zones"]:
        zone_id = slug(zone["name"])
        if zone_id in zones:
            raise vol.Invalid(f"zone names must be different: {zone['name']}")
        zones.add(zone_id)
        if zone.get("boiler") and slug(zone["boiler"]) not in boilers:
            raise vol.Invalid(f"zone {zone['name']} names a boiler that is not configured: {zone['boiler']}")
        members = [_entity_of(item) for item in zone["thermostats"]]
        for entity in members:
            if entity in seen:
                raise vol.Invalid(f"{entity} is in more than one zone")
            seen.add(entity)
        for day in ALL_DAYS:
            if day not in keys and zone["schedule"][day]:
                raise vol.Invalid(f"zone {zone['name']} has a schedule for {day}, which day_mode {_mode_of(config)} does not use")
        for day in keys:
            for slot in zone["schedule"][day]:
                for entity in slot["thermostats"]:
                    if entity not in members:
                        raise vol.Invalid(f"{entity} is in a slot of {zone['name']} but not in the zone")
    if config["season"]["on_below"] > config["season"]["off_above"]:
        raise vol.Invalid("season on_below must not be above off_above")
    return config


HEATING_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name", default="Annika Heating"): cv.string,
            vol.Optional("weather"): _WEATHER,
            vol.Optional("workday"): cv.entity_id,
            # sensor: the workday sensor decides (Mon-Fri without one); weekend: Mon-Fri against
            # Sat-Sun whatever the sensor says; days: a schedule for each day of the week.
            vol.Optional("day_mode"): vol.In(DAY_MODES),
            # Whether a change made on a thermostat itself is kept as a manual one.
            vol.Optional("adopt_manual", default=True): cv.boolean,
            vol.Optional("season", default={}): SEASON_SCHEMA,
            vol.Optional("boilers", default=[]): vol.All(cv.ensure_list, [BOILER_SCHEMA]),
            vol.Required("zones"): vol.All(cv.ensure_list, [ZONE_SCHEMA], vol.Length(min=1)),
        }
    ),
    _check_references,
)


class HeatingError(ValueError):
    """What is asked of the heating and cannot be. `key` is the translation key."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same(a: float | str, b: float | str) -> bool:
    if a == OFF or b == OFF:
        return a == b
    return abs(float(a) - float(b)) <= TOLERANCE


class _Thermostat:
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
        for suffix in (" Thermostat", " thermostat", " Termostato", " termostato"):
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[: -len(suffix)]
        return name


class _Boiler:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name: str = config["name"]
        self.entity: str = config["entity"]


class _Zone:
    def __init__(self, hass: HomeAssistant, config: dict, boilers: list[_Boiler], keys: tuple[str, ...]) -> None:
        self.id = slug(config["name"])
        self.name: str = config["name"]
        self.thermostats = [_Thermostat(hass, item) for item in config["thermostats"]]
        if config.get("boiler"):
            self.boiler: str | None = slug(config["boiler"])
        else:
            self.boiler = boilers[0].id if len(boilers) == 1 else None
        self.schedule: dict[str, list[dict[str, Any]]] = {
            day: [self._slot(slot) for slot in config["schedule"][day]] for day in keys
        }

    @staticmethod
    def _slot(slot: dict) -> dict[str, Any]:
        motion = slot.get("motion")
        return {
            "id": slot.get("id") or uuid.uuid4().hex[:8],
            "time": slot["time"],
            "name": slot["name"],
            "target": float(slot["target"]),
            "thermostats": list(dict.fromkeys(slot["thermostats"])),
            "motion": {"sensors": list(dict.fromkeys(motion["sensors"])), "minutes": int(motion["minutes"])} if motion else None,
        }


class AnnikaHeating:
    """The zones, their schedules, the boilers and the season."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.weather: str | None = config.get("weather")
        self.workday_entity: str | None = config.get("workday")
        self.day_mode: str = _mode_of(config)
        self.day_keys: tuple[str, ...] = day_keys(self.day_mode)
        self.adopt: bool = config["adopt_manual"]
        self.boilers = [_Boiler(boiler) for boiler in config["boilers"]]
        self.zones = [_Zone(hass, zone, self.boilers, self.day_keys) for zone in config["zones"]]
        self.enabled = True
        self.season: dict[str, Any] = {
            **SEASON_SCHEMA(config["season"]),
            "active": None,
            "cold_since": None,
            "warm_since": None,
        }
        # entity -> the target somebody set (a number), or OFF
        self.manual: dict[str, float | str] = {}
        self.events: list[dict[str, Any]] = []

        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.heating")
        self._zones = {zone.id: zone for zone in self.zones}
        self._boilers = {boiler.id: boiler for boiler in self.boilers}
        self._thermostats = {th.entity: (zone, th) for zone in self.zones for th in zone.thermostats}
        self._day_types: dict[str, str] = {}
        self._listeners: list[Callable[[], None]] = []
        self._cancels: list[CALLBACK_TYPE] = []
        self._sensor_cancel: CALLBACK_TYPE | None = None
        self._sensors: frozenset[str] = frozenset()
        self._commanded: dict[str, datetime] = {}
        self._keys: dict[str, tuple] = {}
        self._boiler_on: dict[str, bool] = {}
        self._started = False
        self._pending = False
        self._running = False

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._apply(await self._store.async_load() or {})
        entities = list(self._thermostats) + [boiler.entity for boiler in self.boilers]
        entities += [entity for entity in (self.weather, self.workday_entity if self.day_mode == "sensor" else None) if entity]
        self._cancels.append(async_track_state_change_event(self.hass, entities, self._state_changed))
        self._cancels.append(async_track_time_change(self.hass, self._tick, second=0))
        self._track_sensors()
        self._started = True
        await self._async_evaluate()

    async def async_stop(self, _event=None) -> None:
        self._started = False
        for cancel in self._cancels:
            cancel()
        self._cancels = []
        if self._sensor_cancel is not None:
            self._sensor_cancel()
            self._sensor_cancel = None
        await self._store.async_save(self._saved())

    # --- storage ------------------------------------------------------------

    def _apply(self, saved: dict) -> None:
        self.enabled = saved.get("enabled", True) is not False
        season = saved.get("season")
        if isinstance(season, dict):
            try:
                values = SEASON_SCHEMA({key: season[key] for key in ("enabled", "on_below", "off_above", "hours") if key in season})
                if values["on_below"] <= values["off_above"]:
                    self.season.update(values)
            except vol.Invalid:
                pass
            if season.get("active") in (True, False):
                self.season["active"] = season["active"]
            for key in ("cold_since", "warm_since"):
                if isinstance(season.get(key), str) and dt_util.parse_datetime(season[key]):
                    self.season[key] = season[key]
        for zone_id, schedule in (saved.get("schedules") or {}).items():
            zone = self._zones.get(zone_id)
            if zone is None:
                continue
            try:
                parsed = SCHEDULE_SCHEMA(schedule)
                members = {th.entity for th in zone.thermostats}
                for day in self.day_keys:
                    # A day the store has never saved keeps what the configuration says.
                    if day in schedule:
                        zone.schedule[day] = sorted(
                            (_Zone._slot({**slot, "thermostats": [e for e in slot["thermostats"] if e in members]}) for slot in parsed[day]),
                            key=lambda slot: slot["time"],
                        )
            except vol.Invalid:
                continue
        for entity, value in (saved.get("manual") or {}).items():
            if entity not in self._thermostats:
                continue
            if value == OFF:
                self.manual[entity] = OFF
            elif (number := _number(value)) is not None:
                self.manual[entity] = number
        self.events = [event for event in saved.get("events", []) if isinstance(event, dict)][:MAX_EVENTS]
        days = saved.get("day_types")
        if isinstance(days, dict):
            self._day_types = {key: value for key, value in days.items() if value in ALL_DAYS}

    def _saved(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "season": {key: self.season[key] for key in ("enabled", "on_below", "off_above", "hours", "active", "cold_since", "warm_since")},
            "schedules": {zone.id: {day: [dict(slot) for slot in zone.schedule[day]] for day in self.day_keys} for zone in self.zones},
            "manual": dict(self.manual),
            "events": list(self.events),
            "day_types": dict(sorted(self._day_types.items())[-4:]),
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self._track_sensors()
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

    def _track_sensors(self) -> None:
        """The motion sensors the schedules look at, which change when a schedule does."""

        sensors = frozenset(
            sensor
            for zone in self.zones
            for day in self.day_keys
            for slot in zone.schedule[day]
            if slot["motion"]
            for sensor in slot["motion"]["sensors"]
        )
        if sensors == self._sensors and (self._sensor_cancel is not None or not sensors):
            return
        if self._sensor_cancel is not None:
            self._sensor_cancel()
            self._sensor_cancel = None
        self._sensors = sensors
        if sensors:
            self._sensor_cancel = async_track_state_change_event(self.hass, list(sensors), self._sensor_changed)

    # --- what happened --------------------------------------------------------

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

    def _candidates(self, zone: _Zone, th: _Thermostat, now: datetime):
        """The slots that apply to a thermostat and have started, the latest first."""

        for back in (0, 1):
            day = (now - timedelta(days=back)).date()
            for slot in sorted(zone.schedule[self._day_type(day)], key=lambda item: item["time"], reverse=True):
                if slot["thermostats"] and th.entity not in slot["thermostats"]:
                    continue
                start = self._start(day, slot, now.tzinfo)
                if start <= now:
                    yield start, slot

    def _condition(self, slot: dict[str, Any], now: datetime) -> bool:
        motion = slot["motion"]
        if not motion:
            return True
        for sensor in motion["sensors"]:
            state = self.hass.states.get(sensor)
            if state is None or state.state != STATE_OFF:
                return False
            if (now - state.last_changed).total_seconds() < motion["minutes"] * 60:
                return False
        return True

    def _desired(self, zone: _Zone, th: _Thermostat, now: datetime) -> dict[str, Any]:
        """What a thermostat should be at: a target, or OFF, and why."""

        if th.entity in self.manual:
            return {"value": self.manual[th.entity], "source": "manual", "slot": None, "start": None}
        if self.season["active"] is False:
            return {"value": OFF, "source": "season", "slot": None, "start": None}
        for start, slot in self._candidates(zone, th, now):
            if self._condition(slot, now):
                return {"value": slot["target"], "source": "slot", "slot": slot, "start": start}
        return {"value": OFF, "source": "none", "slot": None, "start": None}

    # --- the season -----------------------------------------------------------

    def _update_season(self, now: datetime) -> bool:
        season = self.season
        before = (season["active"], season["cold_since"], season["warm_since"])
        if not (self.weather and season["enabled"]):
            season["active"] = True
            season["cold_since"] = season["warm_since"] = None
            return before != (True, None, None)
        state = self.hass.states.get(self.weather)
        temperature = _number(state.attributes.get("temperature")) if state is not None else None
        if temperature is None:
            return False
        hold = timedelta(hours=season["hours"])
        if temperature < season["on_below"]:
            season["warm_since"] = None
            season["cold_since"] = season["cold_since"] or now.isoformat()
        elif temperature > season["off_above"]:
            season["cold_since"] = None
            season["warm_since"] = season["warm_since"] or now.isoformat()
        else:
            season["cold_since"] = season["warm_since"] = None
        if season["active"] is None:
            season["active"] = temperature < (season["on_below"] + season["off_above"]) / 2
        elif season["cold_since"] and now - dt_util.parse_datetime(season["cold_since"]) >= hold:
            season["active"] = True
        elif season["warm_since"] and now - dt_util.parse_datetime(season["warm_since"]) >= hold:
            season["active"] = False
        if before[0] is not None and season["active"] != before[0]:
            self._log("season", on=season["active"], temperature=temperature)
        return before != (season["active"], season["cold_since"], season["warm_since"])

    # --- talking to the thermostats ---------------------------------------------

    @staticmethod
    def _value_of(state) -> float | str | None:
        """What a thermostat is set to: OFF, a target, or None when it is in a mode we do not drive."""

        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if state.state == OFF:
            return OFF
        if state.state in ("heat", "auto", "heat_cool"):
            return _number(state.attributes.get("temperature"))
        return None

    async def _ensure(self, th: _Thermostat, desired: float | str, force: bool = False) -> None:
        state = self.hass.states.get(th.entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if desired == OFF:
            if state.state == OFF:
                return
            service, data = "set_hvac_mode", {"hvac_mode": OFF}
        else:
            current = _number(state.attributes.get("temperature"))
            if state.state == "heat" and current is not None and abs(current - desired) <= TOLERANCE:
                return
            service, data = "set_temperature", {"temperature": desired, "hvac_mode": "heat"}
        now = dt_util.utcnow()
        last = self._commanded.get(th.entity)
        if not force and last is not None and (now - last).total_seconds() < RESEND_SECONDS:
            return
        self._commanded[th.entity] = now
        try:
            await self.hass.services.async_call("climate", service, {"entity_id": th.entity, **data}, blocking=True)
        except HomeAssistantError as error:
            _LOGGER.warning("Annika heating could not set %s: %s", th.entity, error)

    async def _sync_boilers(self) -> None:
        for boiler in self.boilers:
            zones = [zone for zone in self.zones if zone.boiler == boiler.id]
            asking = [
                th
                for zone in zones
                for th in zone.thermostats
                if (state := self.hass.states.get(th.entity)) is not None and state.attributes.get("hvac_action") == "heating"
            ]
            state = self.hass.states.get(boiler.entity)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            if asking and state.state != STATE_ON:
                await self._boiler(boiler, True, asking[0].name)
            elif not asking and state.state == STATE_ON:
                await self._boiler(boiler, False, None)

    async def _boiler(self, boiler: _Boiler, on: bool, who: str | None) -> None:
        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_on" if on else "turn_off", {"entity_id": boiler.entity}, blocking=True
            )
        except HomeAssistantError as error:
            _LOGGER.warning("Annika heating could not switch %s: %s", boiler.entity, error)
            return
        self._log("boiler", boiler=boiler.id, on=on, who=who)
        self._changed()

    # --- evaluating -------------------------------------------------------------

    @callback
    def _tick(self, _now) -> None:
        self._schedule_evaluation()

    @callback
    def _sensor_changed(self, _event: Event) -> None:
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
        if entity in self._thermostats:
            self._thermostat_changed(entity, event.data.get("old_state"), event.data.get("new_state"))
        self._schedule_evaluation()

    def _thermostat_changed(self, entity: str, old, new) -> None:
        """A change made on the thermostat itself stays: it is a manual one."""

        if not (self.adopt and self.enabled and self._started):
            return
        before, after = self._value_of(old), self._value_of(new)
        if before is None or after is None or _same(before, after):
            return
        last = self._commanded.get(entity)
        if last is not None and (dt_util.utcnow() - last).total_seconds() < ADOPT_GRACE_SECONDS:
            return
        zone, th = self._thermostats[entity]
        if _same(self._desired(zone, th, dt_util.now())["value"], after):
            return
        self.manual[entity] = after
        self._log("manual", zone=zone.id, thermostat=entity, target=after, external=True)
        self._changed()

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
            keys: dict[str, tuple] = {}
            slots: dict[str, tuple] = {}
            primary = None
            for th in zone.thermostats:
                desired = self._desired(zone, th, now)
                keys[th.entity] = (desired["source"], desired["slot"]["id"] if desired["slot"] else None, desired["value"])
                if desired["source"] == "slot":
                    slots[th.entity] = (desired["slot"]["id"], desired["value"])
                    primary = primary or desired
                await self._ensure(th, desired["value"], force)
            previous = self._keys.get(zone.id)
            self._keys[zone.id] = slots
            if previous is not None and primary is not None and any(previous.get(e) != v for e, v in slots.items()):
                self._log("slot", zone=zone.id, name=primary["slot"]["name"], target=primary["value"])
                changed = True
        await self._sync_boilers()
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
                for th in zone.thermostats:
                    await self._ensure(th, OFF, force=True)
            for boiler in self.boilers:
                state = self.hass.states.get(boiler.entity)
                if state is not None and state.state == STATE_ON:
                    await self._boiler(boiler, False, None)
            self._changed()
            return
        # Turned on: every thermostat starts again from its schedule.
        self.manual.clear()
        self._keys.clear()
        self._changed()
        await self._async_evaluate(force=True)

    def _resolve(self, zone: str | None, thermostats: list[str] | None) -> list[tuple[_Zone, _Thermostat]]:
        found: list[tuple[_Zone, _Thermostat]] = []
        if zone:
            target = self._zones.get(zone) or self._zones.get(slug(zone))
            if target is None:
                raise HeatingError("unknown_zone", zone=zone)
            found = [(target, th) for th in target.thermostats]
        if thermostats:
            wanted = []
            for entity in thermostats:
                if entity not in self._thermostats:
                    raise HeatingError("unknown_thermostat", thermostat=entity)
                wanted.append(self._thermostats[entity])
            found = [pair for pair in found if pair[1].entity in thermostats] if zone else wanted
        if not found and not zone and not thermostats:
            return [pair for pair in self._thermostats.values()]
        return found

    async def async_set_manual(
        self,
        zone: str | None = None,
        thermostats: list[str] | None = None,
        target: float | None = None,
        off: bool = False,
    ) -> None:
        """Hold a target on a zone or on some of its thermostats, until they are put back to Auto."""

        if not self.enabled:
            raise HeatingError("heating_disabled")
        if not zone and not thermostats:
            raise HeatingError("unknown_target")
        pairs = self._resolve(zone, thermostats)
        if off:
            value: float | str = OFF
        else:
            number = _number(target)
            if number is None:
                raise HeatingError("target_required")
            value = round(max(MIN_TARGET, min(MAX_TARGET, number)), 1)
        for _zone, th in pairs:
            self.manual[th.entity] = value
        if zone and not thermostats:
            self._log("manual", zone=pairs[0][0].id, thermostat=None, target=value, external=False)
        else:
            for owner, th in pairs:
                self._log("manual", zone=owner.id, thermostat=th.entity, target=value, external=False)
        self._changed()
        for _zone, th in pairs:
            await self._ensure(th, value, force=True)
        await self._sync_boilers()

    async def async_set_auto(self, zone: str | None = None, thermostats: list[str] | None = None) -> None:
        """Back to what the schedule says: a zone, some thermostats, or everything."""

        pairs = self._resolve(zone, thermostats)
        released = [pair for pair in pairs if pair[1].entity in self.manual]
        for _zone, th in released:
            del self.manual[th.entity]
        if released:
            if zone and not thermostats:
                self._log("auto", zone=released[0][0].id, thermostat=None)
            else:
                for owner, th in released:
                    self._log("auto", zone=owner.id, thermostat=th.entity)
        self._changed()
        await self._async_evaluate(force=True)

    async def async_set_schedule(self, zone: str, day: str, slots: list[dict[str, Any]]) -> None:
        target = self._zones.get(zone) or self._zones.get(slug(zone))
        if target is None:
            raise HeatingError("unknown_zone", zone=zone)
        if day not in self.day_keys:
            raise HeatingError("invalid_slot", error=f"day must be one of {', '.join(self.day_keys)}")
        members = {th.entity for th in target.thermostats}
        try:
            parsed = vol.Schema(vol.All([SLOT_SCHEMA], vol.Length(max=MAX_SLOTS)))(list(slots))
        except vol.Invalid as error:
            raise HeatingError("invalid_slot", error=str(error)) from error
        for slot in parsed:
            for entity in slot["thermostats"]:
                if entity not in members:
                    raise HeatingError("unknown_thermostat", thermostat=entity)
        target.schedule[day] = sorted((_Zone._slot(slot) for slot in parsed), key=lambda slot: slot["time"])
        self._changed()
        await self._async_evaluate()

    async def async_set_season(self, **values: Any) -> None:
        merged = {key: self.season[key] for key in ("enabled", "on_below", "off_above", "hours")}
        merged.update({key: value for key, value in values.items() if value is not None and key in merged})
        try:
            merged = SEASON_SCHEMA(merged)
        except vol.Invalid as error:
            raise HeatingError("invalid_season", error=str(error)) from error
        if merged["on_below"] > merged["off_above"]:
            raise HeatingError("invalid_season", error="on_below must not be above off_above")
        self.season.update(merged)
        self.season["cold_since"] = self.season["warm_since"] = None
        self.season["active"] = None if merged["enabled"] and self.weather else True
        self._changed()
        await self._async_evaluate()

    # --- what the card reads ----------------------------------------------------

    def _entity_ids(self) -> dict[str, str | None]:
        registry = er.async_get(self.hass)
        return {"master": registry.async_get_entity_id("switch", DOMAIN, f"{DOMAIN}_heating_enabled")}

    def _motion_sensors(self) -> list[dict[str, str]]:
        found = []
        for state in self.hass.states.async_all("binary_sensor"):
            if state.attributes.get("device_class") in MOTION_CLASSES:
                found.append({"entity": state.entity_id, "name": state.attributes.get("friendly_name") or state.entity_id})
        return sorted(found, key=lambda item: item["name"].lower())

    def _slot_view(self, slot: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": slot["id"],
            "time": slot["time"],
            "name": slot["name"],
            "target": slot["target"],
            "thermostats": list(slot["thermostats"]),
            "motion": dict(slot["motion"], sensors=list(slot["motion"]["sensors"])) if slot["motion"] else None,
        }

    def _zone_state(self, zone: _Zone, now: datetime) -> dict[str, Any]:
        desired = {th.entity: self._desired(zone, th, now) for th in zone.thermostats}
        values = [item["value"] for item in desired.values() if item["value"] != OFF]
        target: float | None = None
        if values:
            target = max(set(values), key=lambda value: (values.count(value), -values.index(value)))
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
        return {
            "target": target,
            "mixed": len(set(values)) > 1,
            "manual": [entity for entity, item in desired.items() if item["source"] == "manual"],
            "slot": {
                "id": primary["slot"]["id"],
                "name": primary["slot"]["name"],
                "since": _iso(primary["start"]),
                "conditional": bool(primary["slot"]["motion"]),
            } if primary else None,
            "next": {
                "id": upcoming[0][1]["id"],
                "name": upcoming[0][1]["name"],
                "time": _iso(upcoming[0][0]),
                "target": upcoming[0][1]["target"],
                "conditional": bool(upcoming[0][1]["motion"]),
                "minutes": upcoming[0][1]["motion"]["minutes"] if upcoming[0][1]["motion"] else None,
            } if upcoming else None,
            "plan": [
                {"time": _iso(start), "name": slot["name"], "target": slot["target"], "conditional": bool(slot["motion"])}
                for start, slot in upcoming
                if start < end
            ],
            "thermostats": {
                entity: {"value": item["value"], "source": item["source"], "slot": item["slot"]["id"] if item["slot"] else None}
                for entity, item in desired.items()
            },
        }

    @property
    def status(self) -> str:
        if not self.enabled:
            return "off"
        if self.season["active"] is False and not self.manual:
            return "standby"
        for boiler in self.boilers:
            state = self.hass.states.get(boiler.entity)
            if state is not None and state.state == STATE_ON:
                return "heating"
        return "idle"

    def attributes(self) -> dict[str, Any]:
        now = dt_util.now()
        return {
            "config": {
                "enabled": self.enabled,
                "weather": self.weather,
                "workday": self.workday_entity,
                "day_mode": self.day_mode,
                "day_keys": list(self.day_keys),
                "day_type": self._day_type(now.date()),
                "season": {key: self.season[key] for key in ("enabled", "on_below", "off_above", "hours", "active")},
                "motion_sensors": self._motion_sensors(),
                "entities": self._entity_ids(),
                "boilers": [
                    {
                        "id": boiler.id,
                        "name": boiler.name,
                        "entity": boiler.entity,
                        "zones": [zone.id for zone in self.zones if zone.boiler == boiler.id],
                    }
                    for boiler in self.boilers
                ],
                "zones": [
                    {
                        "id": zone.id,
                        "name": zone.name,
                        "boiler": zone.boiler,
                        "thermostats": [
                            {"id": th.id, "entity": th.entity, "name": th.name, "icon": th.icon} for th in zone.thermostats
                        ],
                        "schedule": {day: [self._slot_view(slot) for slot in zone.schedule[day]] for day in self.day_keys},
                    }
                    for zone in self.zones
                ],
            },
            "state": {zone.id: self._zone_state(zone, now) for zone in self.zones},
            "events": [dict(event) for event in self.events],
        }
