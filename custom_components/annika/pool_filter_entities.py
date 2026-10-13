"""Entities of the Annika pool filter. See pool_filter.py.

Every setting is a plain Home Assistant entity — a switch per run, a time per
run, a number of minutes per season — restored across restarts and starting
from the YAML the first time. The status sensor carries the structure (seasons,
runs and the entity ids of all of the above) so annika-schedule-card draws
itself without naming any of them.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import STATE_ON, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .pool_filter import (
    DATA_POOL_FILTER,
    MAX_RUN_MINUTES,
    STATUS_DISABLED,
    STATUSES,
    AnnikaPoolFilter,
    PoolFilterSeason,
    unique_enabled,
    unique_minutes,
    unique_next_start,
    unique_run,
    unique_run_enabled,
    unique_run_time,
    unique_status,
    unique_stop,
)


class _ScheduleEntity:
    _attr_should_poll = False

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        self._pool_filter = pool_filter

    async def _listen(self) -> None:
        self.async_on_remove(self._pool_filter.subscribe(self.async_write_ha_state))


# --- switches ---------------------------------------------------------------


class PoolFilterEnabledSwitch(_ScheduleEntity, SwitchEntity, RestoreEntity):
    """Whether the timetable runs at all. Turning it off ends a run."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        super().__init__(pool_filter)
        self._attr_name = f"{pool_filter.name} Schedule"
        self._attr_unique_id = unique_enabled(pool_filter)

    @property
    def is_on(self) -> bool:
        return self._pool_filter.settings.enabled is True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self._pool_filter.settings.enabled = last_state is None or last_state.state == STATE_ON
        self._pool_filter.settings_changed()
        await self._listen()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._pool_filter.settings.enabled = True
        self._pool_filter.settings_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._pool_filter.settings.enabled = False
        self._pool_filter.settings_changed()


class PoolFilterRunSwitch(_ScheduleEntity, SwitchEntity, RestoreEntity):
    """Whether a run of a season happens."""

    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, pool_filter: AnnikaPoolFilter, season: PoolFilterSeason, index: int) -> None:
        super().__init__(pool_filter)
        self._key = (season.key, index)
        self._attr_name = f"{pool_filter.name} {season.name} Run {index + 1}"
        self._attr_unique_id = unique_run_enabled(pool_filter, season, index)

    @property
    def is_on(self) -> bool:
        return self._pool_filter.settings.run_enabled.get(self._key) is True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self._pool_filter.settings.run_enabled[self._key] = (
            True if last_state is None else last_state.state == STATE_ON
        )
        self._pool_filter.settings_changed()
        await self._listen()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._pool_filter.settings.run_enabled[self._key] = True
        self._pool_filter.settings_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._pool_filter.settings.run_enabled[self._key] = False
        self._pool_filter.settings_changed()


# --- minutes and times ------------------------------------------------------


class PoolFilterMinutesNumber(_ScheduleEntity, RestoreNumber):
    """Minutes each run of a season lasts. 0 skips the season's runs."""

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_RUN_MINUTES
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, pool_filter: AnnikaPoolFilter, season: PoolFilterSeason) -> None:
        super().__init__(pool_filter)
        self._season = season
        self._attr_name = f"{pool_filter.name} {season.name} Minutes"
        self._attr_unique_id = unique_minutes(pool_filter, season)

    @property
    def native_value(self) -> float | None:
        return self._pool_filter.settings.minutes.get(self._season.key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        restored = last.native_value if last is not None else None
        valid = restored is not None and self.native_min_value <= restored <= self.native_max_value
        self._pool_filter.settings.minutes[self._season.key] = (
            restored if valid else self._pool_filter.default_minutes(self._season)
        )
        self._pool_filter.settings_changed()
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        self._pool_filter.settings.minutes[self._season.key] = value
        self._pool_filter.settings_changed()


class PoolFilterRunTime(_ScheduleEntity, TimeEntity, RestoreEntity):
    """When a run of a season starts."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, pool_filter: AnnikaPoolFilter, season: PoolFilterSeason, index: int) -> None:
        super().__init__(pool_filter)
        self._key = (season.key, index)
        self._default = season.runs[index]
        self._attr_name = f"{pool_filter.name} {season.name} Run {index + 1} Time"
        self._attr_unique_id = unique_run_time(pool_filter, season, index)

    @property
    def native_value(self) -> time | None:
        return self._pool_filter.settings.run_time.get(self._key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        restored = dt_util.parse_time(last_state.state) if last_state is not None else None
        self._pool_filter.settings.run_time[self._key] = restored or self._default
        self._pool_filter.settings_changed()
        await self._listen()

    async def async_set_value(self, value: time) -> None:
        self._pool_filter.settings.run_time[self._key] = value
        self._pool_filter.settings_changed()


# --- actions ----------------------------------------------------------------


class PoolFilterRunButton(_ScheduleEntity, ButtonEntity):
    """Run the current season's minutes now."""

    _attr_icon = "mdi:play"

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        super().__init__(pool_filter)
        self._attr_name = f"{pool_filter.name} Run Now"
        self._attr_unique_id = unique_run(pool_filter)

    async def async_press(self) -> None:
        self._pool_filter.run_now()


class PoolFilterStopButton(_ScheduleEntity, ButtonEntity):
    """End a run in progress and turn the switch off."""

    _attr_icon = "mdi:stop"

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        super().__init__(pool_filter)
        self._attr_name = f"{pool_filter.name} Stop"
        self._attr_unique_id = unique_stop(pool_filter)

    async def async_press(self) -> None:
        self._pool_filter.stop("stopped")


# --- status -----------------------------------------------------------------


class PoolFilterStatusSensor(_ScheduleEntity, SensorEntity, RestoreEntity):
    """What the pool_filter is doing, and the map annika-schedule-card reads."""

    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "pool_filter_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATUSES)
    # The map of the timetable changes only with the YAML: no point in a copy per state change.
    _unrecorded_attributes = frozenset({"seasons", "entities", "runs_today", "automation", "switch"})

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        super().__init__(pool_filter)
        self._attr_name = pool_filter.name
        self._attr_unique_id = unique_status(pool_filter)

    @property
    def native_value(self) -> str:
        if self._pool_filter.settings.enabled is False and self._pool_filter.running_until is None:
            return STATUS_DISABLED
        return self._pool_filter.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pool_filter = self._pool_filter
        entity = pool_filter.entity_id
        today = dt_util.now().date()
        season = pool_filter.season_for(today)
        return {
            "next_run": pool_filter.next_run.isoformat() if pool_filter.next_run else None,
            "last_run": pool_filter.last_run.isoformat() if pool_filter.last_run else None,
            "last_result": pool_filter.last_result,
            # Remembered across restarts: what ends a run that was on at shutdown.
            "running_until": pool_filter.running_until.isoformat() if pool_filter.running_until else None,
            "current_season": season.key if season else None,
            "automation": pool_filter.automation,
            "switch": pool_filter.switch,
            # Today's starts by the card's settings, for an automation of the
            # house's own to follow.
            "runs_today": [start.isoformat() for start in pool_filter.runs_on(today)],
            "minutes_today": pool_filter.minutes_for(season) if season else 0,
            "seasons": [
                {
                    "key": item.key,
                    "name": item.name,
                    "months": list(item.months),
                    "minutes": entity("number", unique_minutes(pool_filter, item)),
                    "runs": [
                        {
                            "enabled": entity("switch", unique_run_enabled(pool_filter, item, index)),
                            "time": entity("time", unique_run_time(pool_filter, item, index)),
                        }
                        for index in range(len(item.runs))
                    ],
                }
                for item in pool_filter.seasons
            ],
            "entities": {
                "enabled": entity("switch", unique_enabled(pool_filter)),
                "run": entity("button", unique_run(pool_filter)),
                "stop": entity("button", unique_stop(pool_filter)),
                "next_start": entity("sensor", unique_next_start(pool_filter)),
                "switch": pool_filter.switch,
                "automation": pool_filter.automation,
            },
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        until = dt_util.parse_datetime(last_state.attributes.get("running_until") or "") if last_state else None
        self._pool_filter.restore_running(until)
        await self._listen()


class PoolFilterNextStartSensor(_ScheduleEntity, SensorEntity):
    """When the next run starts by the card's settings, whoever runs it.

    A timestamp, so an automation of the house's own can trigger on it
    (`trigger: time`, `at: sensor.pool_filter_next_start`).
    """

    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, pool_filter: AnnikaPoolFilter) -> None:
        super().__init__(pool_filter)
        self._attr_name = f"{pool_filter.name} Next Start"
        self._attr_unique_id = unique_next_start(pool_filter)

    @property
    def native_value(self) -> datetime | None:
        return self._pool_filter.next_start

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()
        # Added after the status sensor wrote its map: have it write it again.
        self._pool_filter.notify()


# --- what the platform files ask for ----------------------------------------


def sensors(pool_filter: AnnikaPoolFilter) -> list[SensorEntity]:
    return [PoolFilterStatusSensor(pool_filter), PoolFilterNextStartSensor(pool_filter)]


def switches(pool_filter: AnnikaPoolFilter) -> list[SwitchEntity]:
    return [PoolFilterEnabledSwitch(pool_filter)] + [
        PoolFilterRunSwitch(pool_filter, season, index)
        for season in pool_filter.seasons
        for index in range(len(season.runs))
    ]


def numbers(pool_filter: AnnikaPoolFilter) -> list[NumberEntity]:
    return [PoolFilterMinutesNumber(pool_filter, season) for season in pool_filter.seasons]


def times(pool_filter: AnnikaPoolFilter) -> list[TimeEntity]:
    return [
        PoolFilterRunTime(pool_filter, season, index)
        for season in pool_filter.seasons
        for index in range(len(season.runs))
    ]


def buttons(pool_filter: AnnikaPoolFilter) -> list[ButtonEntity]:
    return [PoolFilterRunButton(pool_filter), PoolFilterStopButton(pool_filter)]


BUILDERS = {
    "sensor": sensors,
    "switch": switches,
    "number": numbers,
    "time": times,
    "button": buttons,
}


async def async_setup_platform(
    hass: HomeAssistant, platform: str, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(BUILDERS[platform](hass.data[DATA_POOL_FILTER]))
