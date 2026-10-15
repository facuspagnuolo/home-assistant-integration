"""Annika pool filter: one switch that runs on a seasonal timetable.

The pool filter is a single switch that is on for a while at a few times of
day, with the times and the minutes changing with the season. The timetable is
edited from annika-pool-filter-card; the YAML only says what the seasons and
their runs are to begin with:

    annika:
      pool_filter:
        switch: switch.pool_filter
        notify_view: pool            # optional: Annika events on and off
        seasons:
          - name: Summer
            months: [12, 1, 2]
            minutes: 90              # each run of the season
            runs: ["11:00", "14:00", "17:00", "20:00"]
          - name: Winter
            months: [6, 7, 8]
            minutes: 60
            runs: ["11:00", "14:00", "17:00"]

`minutes` and `runs` are only where each entity starts: from then on the
person's edits win and survive restarts. A month no season covers does not
run.

The end of a run is a time Annika remembers, not a sleep in the middle of an
automation: if Home Assistant restarts while the switch is on, it is turned
off on the way back up when its time has passed, instead of staying on until
somebody notices.

`automation:` hands the running to an automation of the house's own. Every
entity is still created, and `sensor.pool_filter_next_start` is a timestamp to
trigger on, but Annika itself does not switch anything on its timetable.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable

import voluptuous as vol

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_POOL_FILTER = f"{DOMAIN}_pool_filter"

MAX_RUN_MINUTES = 720
# Far enough to reach the first run of the next season across a gap of months
# that no season covers.
LOOKAHEAD_DAYS = 62

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_IDLE, STATUS_RUNNING, STATUS_DISABLED)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _validate(config: dict) -> dict:
    seasons = [slugify(season["name"]) for season in config["seasons"]]
    if len(set(seasons)) != len(seasons):
        raise vol.Invalid("pool_filter seasons must have different names")

    taken: dict[int, str] = {}
    for season in config["seasons"]:
        for month in season["months"]:
            if month in taken:
                raise vol.Invalid(f"month {month} is in both {taken[month]} and {season['name']}")
            taken[month] = season["name"]
    return config


POOL_FILTER_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name", default="Pool Filter"): cv.string,
            vol.Required("switch"): cv.entity_domain("switch"),
            vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
            vol.Optional("automation"): cv.entity_domain("automation"),
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
                        vol.Required("minutes"): vol.All(
                            vol.Coerce(int), vol.Range(min=0, max=MAX_RUN_MINUTES)
                        ),
                        vol.Required("runs"): vol.All(
                            cv.ensure_list, vol.Length(min=1), [cv.time]
                        ),
                    }
                ],
            ),
        }
    ),
    _validate,
)


@dataclass(frozen=True)
class PoolFilterSeason:
    key: str
    name: str
    months: tuple[int, ...]
    runs: tuple[time, ...]


@dataclass
class PoolFilterSettings:
    """What the person edits. `None` until the owning entity restored it."""

    enabled: bool | None = None
    run_enabled: dict[tuple[str, int], bool | None] = field(default_factory=dict)
    run_time: dict[tuple[str, int], time | None] = field(default_factory=dict)
    minutes: dict[str, float | None] = field(default_factory=dict)


TEXTS = {
    "en": {
        "started": "{name} on ({season}, {minutes} min){manual}",
        "manual": " · manual",
        "finished": "{name} off",
        "stopped": "{name} stopped",
        "disabled": "{name} off: the pool_filter was turned off",
        "manual_off": "{name} turned off by hand",
        "restart": "{name} off: Home Assistant restarted during the run",
        "event_on": "🌊 {name} on",
        "event_off": "🌊 {name} off",
        "event_message": "{season}, {minutes} min",
    },
    "es": {
        "started": "{name} prendida ({season}, {minutes} min){manual}",
        "manual": " · manual",
        "finished": "{name} apagada",
        "stopped": "{name} detenida",
        "disabled": "{name} apagada: se apagó el programa",
        "manual_off": "{name} apagada a mano",
        "restart": "{name} apagada: Home Assistant se reinició durante la corrida",
        "event_on": "🌊 {name} prendida",
        "event_off": "🌊 {name} apagada",
        "event_message": "{season}, {minutes} min",
    },
}


class AnnikaPoolFilter:
    """The timetable and the runs of the pool filter."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self.name: str = config["name"]
        self.switch: str = config["switch"]
        self.notify_view: str | None = config.get("notify_view")
        self.automation: str | None = config.get("automation")
        self.seasons = [
            PoolFilterSeason(
                slugify(season["name"]),
                season["name"],
                tuple(season["months"]),
                tuple(season["runs"]),
            )
            for season in config["seasons"]
        ]

        self.settings = PoolFilterSettings()
        self.status = STATUS_IDLE
        # Set while a run is on: when it ends. Persisted by the status sensor.
        self.running_until: datetime | None = None
        self.running_season: str | None = None
        self.next_start: datetime | None = None
        self.next_run: datetime | None = None
        self.last_run: datetime | None = None
        self.last_result: str | None = None

        self._restored_until: datetime | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribers: list[Callable[[], None]] = []
        self._unschedule: Callable[[], None] | None = None
        self._unend: Callable[[], None] | None = None

    # --- defaults the entities start from --------------------------------

    def season_config(self, season: PoolFilterSeason) -> dict:
        return next(item for item in self.config["seasons"] if slugify(item["name"]) == season.key)

    def default_minutes(self, season: PoolFilterSeason) -> int:
        return self.season_config(season)["minutes"]

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

        if self.settings.enabled is False and self.running_until is not None:
            self.stop("disabled")
        self._reschedule()
        self.notify()

    # --- lifecycle ---------------------------------------------------------

    @callback
    def restore_running(self, until: datetime | None) -> None:
        """The status sensor hands back when the run that was on at shutdown ends."""

        self._restored_until = until

    async def async_start(self) -> None:
        self._unsubscribers.append(
            async_track_state_change_event(self.hass, [self.switch], self._switch_changed)
        )
        await self._async_resume()
        self._reschedule()
        self.notify()

    async def _async_resume(self) -> None:
        until, self._restored_until = self._restored_until, None
        if until is None:
            return
        now = dt_util.now()
        if until > now:
            self.running_until = until
            self.status = STATUS_RUNNING
            self._unend = async_track_point_in_time(self.hass, self._ended, until)
            return
        # The run ended while Home Assistant was down: close what it left on.
        if self._state(self.switch) == STATE_ON:
            await self._async_switch(False)
            self._logbook("restart")

    async def async_stop(self, _event: Event | None = None) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._unschedule:
            self._unschedule()
            self._unschedule = None
        # The run is left as it is, with its end remembered: the next start
        # picks it up, or closes it if its time has passed.
        if self._unend:
            self._unend()
            self._unend = None

    # --- the timetable -----------------------------------------------------

    def season_for(self, day: date) -> PoolFilterSeason | None:
        return next((season for season in self.seasons if day.month in season.months), None)

    def runs_on(self, day: date) -> list[datetime]:
        """The starts of `day`, in local time and in order."""

        season = self.season_for(day)
        if season is None:
            return []
        zone = dt_util.get_default_time_zone()
        starts = []
        for index in range(len(season.runs)):
            if self.settings.run_enabled.get((season.key, index)) is not True:
                continue
            at = self.settings.run_time.get((season.key, index))
            if at is None:
                continue
            starts.append(dt_util.as_local(datetime.combine(day, at, tzinfo=zone)))
        return sorted(starts)

    def compute_next_run(self, now: datetime) -> datetime | None:
        if self.settings.enabled is not True:
            return None
        today = dt_util.as_local(now).date()
        for ahead in range(LOOKAHEAD_DAYS + 1):
            for start in self.runs_on(today + timedelta(days=ahead)):
                if start > now:
                    return start
        return None

    @callback
    def _reschedule(self) -> None:
        if self._unschedule:
            self._unschedule()
            self._unschedule = None
        self.next_start = self.compute_next_run(dt_util.now())
        self.next_run = None if self.automation else self.next_start
        if self.next_start is not None:
            self._unschedule = async_track_point_in_time(self.hass, self._scheduled, self.next_start)

    @callback
    def _scheduled(self, now: datetime) -> None:
        self._unschedule = None
        season = self.season_for(dt_util.as_local(now).date())
        if not self.automation and self.settings.enabled is True and season is not None:
            self._begin(season, manual=False)
        self._reschedule()
        self.notify()

    # --- runs --------------------------------------------------------------

    @callback
    def run_now(self) -> bool:
        """Run the current season's minutes now, whatever the timetable says."""

        season = self.season_for(dt_util.now().date())
        if season is None:
            return False
        started = self._begin(season, manual=True)
        self.notify()
        return started

    @callback
    def stop(self, reason: str = "stopped") -> None:
        if self.running_until is None:
            return
        self._finish(reason, switch_off=True)

    def minutes_for(self, season: PoolFilterSeason) -> int:
        return int(self.settings.minutes.get(season.key) or 0)

    @callback
    def _begin(self, season: PoolFilterSeason, manual: bool) -> bool:
        minutes = self.minutes_for(season)
        if minutes <= 0:
            return False
        now = dt_util.now()
        until = now + timedelta(minutes=minutes)
        was_running = self.running_until is not None
        # A run that begins inside another one lets the later end win.
        if was_running and self.running_until > until:
            until = self.running_until
        if self._unend:
            self._unend()
        self.running_until = until
        self.running_season = season.key
        self.status = STATUS_RUNNING
        self.last_run = now
        self._unend = async_track_point_in_time(self.hass, self._ended, until)
        self.hass.async_create_task(self._async_switch(True))
        if not was_running:
            self._logbook(
                "started", season=season.name, minutes=minutes, manual=self._text("manual") if manual else ""
            )
            self.hass.async_create_task(
                self._send_event("event_on", season=season.name, minutes=minutes)
            )
        return True

    @callback
    def _ended(self, _now: datetime) -> None:
        self._unend = None
        self._finish("completed", switch_off=True)

    @callback
    def _finish(self, result: str, switch_off: bool) -> None:
        if self._unend:
            self._unend()
            self._unend = None
        season = self.running_season
        self.running_until = None
        self.running_season = None
        self.status = STATUS_IDLE
        self.last_result = result
        if switch_off:
            self.hass.async_create_task(self._async_switch(False))
        key = {"completed": "finished", "manual": "manual_off"}.get(result, result)
        self._logbook(key if key in TEXTS["en"] else "stopped")
        self.hass.async_create_task(
            self._send_event("event_off", season=season or "", minutes=0)
        )
        self.notify()

    @callback
    def _switch_changed(self, event: Event) -> None:
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if self.running_until is None or old is None or new is None:
            return
        if old.state == STATE_ON and new.state == STATE_OFF:
            # Somebody turned it off by hand in the middle of a run.
            self._finish("manual", switch_off=False)

    async def _async_switch(self, on: bool) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_on" if on else "turn_off", {"entity_id": self.switch}, blocking=True
            )
        except Exception:  # noqa: BLE001 — a failed switch must not take the pool_filter down
            _LOGGER.exception("Annika pool_filter %s: could not turn %s %s", self.name, self.switch, "on" if on else "off")

    # --- helpers -------------------------------------------------------------

    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

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

    async def _send_event(self, key: str, **values) -> None:
        if not self.notify_view:
            return
        try:
            await AnnikaEventClient(self.hass).async_send(
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "info",
                    "title": self._text(key),
                    "message": self._text("event_message", **values) if values.get("minutes") else "",
                    "view": self.notify_view,
                }
            )
        except Exception:  # noqa: BLE001 — a missed notification must not stop the pool_filter
            _LOGGER.warning("Annika pool_filter %s: could not send the %s event", self.name, key)


# Unique ids of the entities this module's platforms create. The card finds
# them through the status sensor's attributes, so none is named in YAML.
def unique_status(pool_filter: AnnikaPoolFilter) -> str:
    return f"annika_pool_filter"


def unique_enabled(pool_filter: AnnikaPoolFilter) -> str:
    return f"annika_pool_filter_enabled"


def unique_run(pool_filter: AnnikaPoolFilter) -> str:
    return f"annika_pool_filter_run"


def unique_stop(pool_filter: AnnikaPoolFilter) -> str:
    return f"annika_pool_filter_stop"


def unique_next_start(pool_filter: AnnikaPoolFilter) -> str:
    return f"annika_pool_filter_next_start"


def unique_minutes(pool_filter: AnnikaPoolFilter, season: PoolFilterSeason) -> str:
    return f"annika_pool_filter_{season.key}_minutes"


def unique_run_enabled(pool_filter: AnnikaPoolFilter, season: PoolFilterSeason, index: int) -> str:
    return f"annika_pool_filter_{season.key}_run_{index + 1}"


def unique_run_time(pool_filter: AnnikaPoolFilter, season: PoolFilterSeason, index: int) -> str:
    return f"annika_pool_filter_{season.key}_run_{index + 1}_time"
