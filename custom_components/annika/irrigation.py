"""Annika irrigation schedule.

Rain Bird (or any integration whose zones are switches) owns the valves. Annika
owns the schedule on top of them: in which months each season applies, which
days it waters, for how long each group of zones runs, and when it starts. All
of that is entities the person living in the house edits from the Annika card;
the structure — seasons, groups and zones — is a deployment decision:

    annika:
      irrigation:
        rain_sensor: binary_sensor.rain_bird_controller_rainsensor
        rain_delay: number.rain_bird_controller_rain_delay
        notify_view: irrigation        # optional: Annika events start/end
        pause_seconds: 20              # between zones
        start:
          sunrise_offset: "-02:00"     # or `time: "05:30"`
        rain_delay_after_rain: 1       # days, starting value
        groups:
          - Goteo
          - Aspersores
        seasons:
          - name: Verano
            months: [12, 1, 2]
            days: [mon, tue, wed, thu, fri, sat, sun]
            minutes: { Goteo: 18, Aspersores: 8 }
          - name: Invierno
            months: [6, 7, 8]
            days: [tue, fri]
            minutes: { Goteo: 12, Aspersores: 4 }
        zones:                          # watered one at a time, in this order
          - entity: switch.rain_bird_sprinkler_1_drip_west
            group: Goteo
            name: West drip
          - entity: switch.rain_bird_sprinkler_2_west_side
            group: Aspersores

`days`, `minutes`, `start` and `rain_delay_after_rain` are only where each
entity starts: from then on the person's edits win and survive restarts.

A month no season covers simply does not water. Rain Bird zones are opened
with the controller's own duration (`rainbird.start_irrigation`), so a valve
closes on time even if Home Assistant goes down halfway through a run; any
other switch is turned on and off.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

import voluptuous as vol

from homeassistant.const import STATE_ON, SUN_EVENT_SUNRISE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_IRRIGATION = f"{DOMAIN}_irrigation"

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

START_SUNRISE = "sunrise"
START_TIME = "time"
START_MODES = (START_SUNRISE, START_TIME)

MAX_ZONE_MINUTES = 120
MAX_SUNRISE_OFFSET_MINUTES = 360
MAX_RAIN_DELAY_DAYS = 14
# How far ahead to look for the next day that waters. Two weeks covers any
# weekly pattern, and a season that starts after that is reached on a later
# reschedule (every run and every edit reschedules).
LOOKAHEAD_DAYS = 14

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_IDLE, STATUS_RUNNING, STATUS_DISABLED)

SKIP_RAIN = "rain_sensor"
SKIP_RAIN_DELAY = "rain_delay"
SKIP_BUSY = "zone_running"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _named(value: Any) -> dict:
    return {"name": value} if isinstance(value, str) else value


def _validate_structure(config: dict) -> dict:
    groups = [slugify(group["name"]) for group in config["groups"]]
    if len(set(groups)) != len(groups):
        raise vol.Invalid("irrigation groups must have different names")

    seasons = [slugify(season["name"]) for season in config["seasons"]]
    if len(set(seasons)) != len(seasons):
        raise vol.Invalid("irrigation seasons must have different names")

    taken: dict[int, str] = {}
    for season in config["seasons"]:
        for month in season["months"]:
            if month in taken:
                raise vol.Invalid(
                    f"month {month} is in both {taken[month]} and {season['name']}"
                )
            taken[month] = season["name"]
        for group in season["minutes"]:
            if slugify(group) not in groups:
                raise vol.Invalid(f"{season['name']} sets minutes for unknown group {group}")

    for zone in config["zones"]:
        if slugify(zone["group"]) not in groups:
            raise vol.Invalid(f"zone {zone['entity']} is in unknown group {zone['group']}")
    return config


IRRIGATION_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("rain_sensor"): cv.entity_id,
            vol.Optional("rain_delay"): cv.entity_id,
            vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
            # An automation of the house's own that waters instead of Annika's
            # schedule. Every entity is still created, for it to read.
            vol.Optional("automation"): cv.entity_domain("automation"),
            vol.Optional("pause_seconds", default=20): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=600)
            ),
            vol.Optional("start", default={"sunrise_offset": timedelta(0)}): vol.All(
                {
                    vol.Exclusive("sunrise_offset", "start"): cv.time_period,
                    vol.Exclusive("time", "start"): cv.time,
                },
                vol.Length(min=1, msg="start needs sunrise_offset or time"),
            ),
            vol.Optional("rain_delay_after_rain", default=0): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_RAIN_DELAY_DAYS)
            ),
            vol.Required("groups"): vol.All(
                cv.ensure_list,
                vol.Length(min=1),
                [vol.All(_named, {vol.Required("name"): cv.string})],
            ),
            vol.Required("seasons"): vol.All(
                cv.ensure_list,
                vol.Length(min=1),
                [
                    {
                        vol.Required("name"): cv.string,
                        vol.Required("months"): vol.All(
                            cv.ensure_list,
                            vol.Length(min=1),
                            [vol.All(vol.Coerce(int), vol.Range(min=1, max=12))],
                        ),
                        vol.Optional("days", default=[]): vol.All(
                            cv.ensure_list, [vol.In(WEEKDAYS)]
                        ),
                        vol.Optional("minutes", default={}): {
                            cv.string: vol.All(
                                vol.Coerce(int), vol.Range(min=0, max=MAX_ZONE_MINUTES)
                            )
                        },
                    }
                ],
            ),
            vol.Required("zones"): vol.All(
                cv.ensure_list,
                vol.Length(min=1),
                [
                    {
                        vol.Required("entity"): cv.entity_id,
                        vol.Required("group"): cv.string,
                        vol.Optional("name"): cv.string,
                    }
                ],
            ),
        }
    ),
    _validate_structure,
)


@dataclass(frozen=True)
class IrrigationGroup:
    key: str
    name: str


@dataclass(frozen=True)
class IrrigationSeason:
    key: str
    name: str
    months: tuple[int, ...]


@dataclass(frozen=True)
class IrrigationZone:
    entity_id: str
    group: str
    name: str | None


@dataclass
class IrrigationSettings:
    """What the person edits. `None` until the owning entity restored it."""

    enabled: bool | None = None
    days: dict[tuple[str, str], bool | None] = field(default_factory=dict)
    minutes: dict[tuple[str, str], float | None] = field(default_factory=dict)
    start_mode: str | None = None
    sunrise_offset_minutes: float | None = None
    start_time: time | None = None
    rain_delay_after_rain: float | None = None


class AnnikaIrrigation:
    """The schedule, the runs and the rain delay of one unit."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self.groups = [
            IrrigationGroup(slugify(group["name"]), group["name"]) for group in config["groups"]
        ]
        self.seasons = [
            IrrigationSeason(slugify(season["name"]), season["name"], tuple(season["months"]))
            for season in config["seasons"]
        ]
        self.zones = [
            IrrigationZone(zone["entity"], slugify(zone["group"]), zone.get("name"))
            for zone in config["zones"]
        ]
        self.rain_sensor: str | None = config.get("rain_sensor")
        self.rain_delay: str | None = config.get("rain_delay")
        self.notify_view: str | None = config.get("notify_view")
        self.automation: str | None = config.get("automation")
        self.pause_seconds: int = config["pause_seconds"]

        self.settings = IrrigationSettings()
        self.status = STATUS_IDLE
        self.current_zone: str | None = None
        self.next_run: datetime | None = None
        # When the card's settings say the next run starts, whoever waters.
        self.next_start: datetime | None = None
        self.last_run: datetime | None = None
        self.last_result: str | None = None

        self._listeners: list[Callable[[], None]] = []
        self._unsubscribers: list[Callable[[], None]] = []
        self._unschedule: Callable[[], None] | None = None
        self._task: asyncio.Task | None = None
        # HA starts tasks eagerly: a run can stop, or even finish, before `_task` is assigned,
        # so whether one is running is tracked on its own.
        self._running = False
        self._abort = asyncio.Event()
        self._abort_reason: str | None = None

    # --- defaults the entities start from --------------------------------

    def default_days(self, season: IrrigationSeason) -> set[str]:
        return set(self._season_config(season)["days"])

    def default_minutes(self, season: IrrigationSeason, group: IrrigationGroup) -> int:
        minutes = self._season_config(season)["minutes"]
        return next((value for name, value in minutes.items() if slugify(name) == group.key), 0)

    def default_start_mode(self) -> str:
        return START_TIME if "time" in self.config["start"] else START_SUNRISE

    def default_sunrise_offset_minutes(self) -> int:
        offset = self.config["start"].get("sunrise_offset", timedelta(0))
        return int(offset.total_seconds() // 60)

    def default_start_time(self) -> time:
        return self.config["start"].get("time", time(5, 0))

    def default_rain_delay_after_rain(self) -> int:
        return self.config["rain_delay_after_rain"]

    def _season_config(self, season: IrrigationSeason) -> dict:
        return next(item for item in self.config["seasons"] if slugify(item["name"]) == season.key)

    # --- change notification ---------------------------------------------

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def settings_changed(self) -> None:
        """An entity changed a setting: the next run may have moved."""

        if self.settings.enabled is False and self._running:
            self.stop("disabled")
        self._reschedule()
        self.notify()

    # --- lifecycle ---------------------------------------------------------

    async def async_start(self) -> None:
        if self.rain_sensor:
            self._unsubscribers.append(
                async_track_state_change_event(self.hass, [self.rain_sensor], self._rain_sensor_changed)
            )
        if self.rain_sensor and self.rain_delay:
            self._unsubscribers.append(
                async_track_time_change(self.hass, self._midnight_rain_check, hour=0, minute=5, second=0)
            )
        self._reschedule()

    async def async_stop(self, _event: Event | None = None) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._unschedule:
            self._unschedule()
            self._unschedule = None
        if self._running:
            self.stop("stopped")
        if self._task is not None and not self._task.done():
            await asyncio.gather(self._task, return_exceptions=True)

    # --- the schedule ------------------------------------------------------

    def season_for(self, day: date) -> IrrigationSeason | None:
        return next((season for season in self.seasons if day.month in season.months), None)

    def waters_on(self, day: date) -> bool:
        season = self.season_for(day)
        return bool(season) and self.settings.days.get((season.key, WEEKDAYS[day.weekday()])) is True

    def start_on(self, day: date) -> datetime | None:
        """When the run of `day` starts, in local time."""

        if self.settings.start_mode == START_TIME:
            start = self.settings.start_time
            if start is None:
                return None
            return dt_util.as_local(
                datetime.combine(day, start, tzinfo=dt_util.get_default_time_zone())
            )
        offset = self.settings.sunrise_offset_minutes
        if offset is None:
            return None
        sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, day)
        if sunrise is None:
            return None
        return dt_util.as_local(sunrise) + timedelta(minutes=offset)

    def compute_next_run(self, now: datetime) -> datetime | None:
        if self.settings.enabled is not True:
            return None
        today = dt_util.as_local(now).date()
        for ahead in range(LOOKAHEAD_DAYS + 1):
            day = today + timedelta(days=ahead)
            if not self.waters_on(day):
                continue
            start = self.start_on(day)
            if start is not None and start > now:
                return start
        return None

    @callback
    def _reschedule(self) -> None:
        if self._unschedule:
            self._unschedule()
            self._unschedule = None
        self.next_start = self.compute_next_run(dt_util.now())
        # With an automation of its own, the house waters; Annika only keeps
        # the next start current for it.
        self.next_run = None if self.automation else self.next_start
        if self.next_start is not None:
            self._unschedule = async_track_point_in_time(self.hass, self._scheduled, self.next_start)

    @callback
    def _scheduled(self, now: datetime) -> None:
        self._unschedule = None
        day = dt_util.as_local(now).date()
        if not self.automation and self.settings.enabled is True and self.waters_on(day):
            season = self.season_for(day)
            reason = self.skip_reason()
            if reason:
                self._finish(f"skipped:{reason}", f"Salteado: {_SKIP_TEXT[reason]}")
            elif season is not None:
                self._launch(season, manual=False)
        self._reschedule()
        self.notify()

    def skip_reason(self) -> str | None:
        if self.rain_sensor and self._state(self.rain_sensor) == STATE_ON:
            return SKIP_RAIN
        if self.rain_delay and _as_float(self._state(self.rain_delay)) > 0:
            return SKIP_RAIN_DELAY
        if self._running or any(self._state(zone.entity_id) == STATE_ON for zone in self.zones):
            return SKIP_BUSY
        return None

    # --- runs --------------------------------------------------------------

    @callback
    def run_now(self) -> bool:
        """Water the current season's program now, whatever day it is."""

        season = self.season_for(dt_util.now().date())
        if season is None or self.skip_reason() == SKIP_BUSY:
            return False
        self._launch(season, manual=True)
        self.notify()
        return True

    @callback
    def stop(self, reason: str = "stopped") -> None:
        if not self._running:
            return
        self._abort_reason = reason
        self._abort.set()

    @callback
    def _launch(self, season: IrrigationSeason, manual: bool) -> None:
        self._abort = asyncio.Event()
        self._abort_reason = None
        self._running = True
        self._task = self.hass.async_create_background_task(
            self._async_run(season, manual), f"{DOMAIN} irrigation {season.key}"
        )

    def program(self, season: IrrigationSeason) -> list[tuple[IrrigationZone, int]]:
        """The zones a run of `season` waters, in order, with their minutes."""

        program = [
            (zone, int(self.settings.minutes.get((season.key, zone.group)) or 0)) for zone in self.zones
        ]
        return [(zone, minutes) for zone, minutes in program if minutes > 0]

    async def _async_run(self, season: IrrigationSeason, manual: bool) -> None:
        program = self.program(season)
        self.status = STATUS_RUNNING
        self.last_run = dt_util.now()
        self.notify()
        self._logbook(f"Inicio del riego de {season.name}{' (manual)' if manual else ''}")
        await self._send_event("Riego iniciado", f"Programa de {season.name}")

        result = "completed"
        try:
            for index, (zone, minutes) in enumerate(program):
                self.current_zone = zone.entity_id
                self.notify()
                await self._open(zone, minutes)
                try:
                    if await self._wait(minutes * 60):
                        result = self._abort_reason or "stopped"
                        break
                finally:
                    await self._close(zone)
                    self.current_zone = None
                    self.notify()
                if index < len(program) - 1 and await self._wait(self.pause_seconds):
                    result = self._abort_reason or "stopped"
                    break
        except Exception:  # noqa: BLE001 — a failed valve must not leave the run marked as running
            _LOGGER.exception("Annika irrigation: run of %s failed", season.name)
            result = "failed"
        finally:
            self._running = False

        texts = {
            "completed": (f"Riego de {season.name} terminado", "Riego terminado"),
            SKIP_RAIN: (f"Riego de {season.name} interrumpido por lluvia", "Riego interrumpido por lluvia"),
            "failed": (f"Riego de {season.name} falló", "El riego falló"),
        }
        log, title = texts.get(result, (f"Riego de {season.name} detenido", "Riego detenido"))
        self._finish(result, log)
        await self._send_event(title, f"Programa de {season.name}")
        self._reschedule()
        self.notify()

    async def _wait(self, seconds: float) -> bool:
        """Sleep, or wake early and return True when the run is aborted."""

        try:
            await asyncio.wait_for(self._abort.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    async def _open(self, zone: IrrigationZone, minutes: float) -> None:
        entry = er.async_get(self.hass).async_get(zone.entity_id)
        if entry is not None and entry.platform == "rainbird":
            await self.hass.services.async_call(
                "rainbird",
                "start_irrigation",
                {"entity_id": zone.entity_id, "duration": minutes},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": zone.entity_id}, blocking=True
            )

    async def _close(self, zone: IrrigationZone) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": zone.entity_id}, blocking=True
            )
        except Exception:  # noqa: BLE001 — the controller's own duration still closes it
            _LOGGER.exception("Annika irrigation: could not close %s", zone.entity_id)

    @callback
    def _finish(self, result: str, log: str) -> None:
        self.status = STATUS_IDLE
        self.last_result = result
        self._logbook(log)

    # --- rain ----------------------------------------------------------------

    @callback
    def _rain_sensor_changed(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state != STATE_ON:
            return
        self.stop(SKIP_RAIN)
        self.hass.async_create_task(self._async_apply_rain_delay())

    @callback
    def _midnight_rain_check(self, _now: datetime) -> None:
        self.hass.async_create_task(self._async_apply_rain_delay())

    async def _async_apply_rain_delay(self) -> None:
        if not (self.rain_sensor and self.rain_delay):
            return
        if self._state(self.rain_sensor) != STATE_ON:
            return
        days = int(self.settings.rain_delay_after_rain or 0)
        if days <= 0:
            return
        await self.hass.services.async_call(
            "number", "set_value", {"entity_id": self.rain_delay, "value": days}, blocking=True
        )

    # --- helpers -------------------------------------------------------------

    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def entity_id(self, domain: str, unique_id: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(domain, DOMAIN, unique_id)

    def _logbook(self, message: str) -> None:
        entity_id = self.entity_id("sensor", UNIQUE_STATUS)
        if entity_id is None:
            return
        self.hass.bus.async_fire(
            "logbook_entry",
            {"name": "Riego", "message": message, "entity_id": entity_id, "domain": DOMAIN},
        )

    async def _send_event(self, title: str, message: str) -> None:
        if not self.notify_view:
            return
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
        except Exception:  # noqa: BLE001 — a missed notification must not stop the watering
            _LOGGER.warning("Annika irrigation: could not send the %s event", title)


_SKIP_TEXT = {
    SKIP_RAIN: "está lloviendo",
    SKIP_RAIN_DELAY: "demora por lluvia activa",
    SKIP_BUSY: "ya había una zona regando",
}


def _as_float(value: str | None) -> float:
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0


# Unique ids of the entities this module's platforms create. The card finds
# them through the status sensor's attributes, so none is named in YAML.
UNIQUE_STATUS = "annika_irrigation"
UNIQUE_ENABLED = "annika_irrigation_enabled"
UNIQUE_START_MODE = "annika_irrigation_start_mode"
UNIQUE_SUNRISE_OFFSET = "annika_irrigation_sunrise_offset"
UNIQUE_START_TIME = "annika_irrigation_start_time"
UNIQUE_RAIN_DELAY_AFTER_RAIN = "annika_irrigation_rain_delay_after_rain"
UNIQUE_RUN = "annika_irrigation_run"
UNIQUE_STOP = "annika_irrigation_stop"
UNIQUE_NEXT_START = "annika_irrigation_next_start"


def unique_day(season: IrrigationSeason, weekday: str) -> str:
    return f"annika_irrigation_{season.key}_{weekday}"


def unique_minutes(season: IrrigationSeason, group: IrrigationGroup) -> str:
    return f"annika_irrigation_{season.key}_{group.key}_minutes"
