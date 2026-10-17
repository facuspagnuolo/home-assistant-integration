"""Entities of the Annika irrigation schedule. See irrigation.py.

Every setting is a plain Home Assistant entity — a switch per season and day,
a number per season and group, the start — restored across restarts and
starting from the YAML defaults the first time. The status sensor carries the
structure (seasons, groups, zones and the entity ids of all of the above) so
annika-irrigation-card draws itself without naming any of them.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import STATE_ON, UnitOfTime
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .irrigation import (
    MAX_MANUAL_MINUTES,
    MAX_RAIN_DELAY_DAYS,
    MAX_SUNRISE_OFFSET_MINUTES,
    MAX_ZONE_MINUTES,
    START_MODES,
    STATUS_DISABLED,
    STATUSES,
    UNIQUE_ENABLED,
    UNIQUE_MANUAL_MINUTES,
    UNIQUE_NEXT_START,
    UNIQUE_RAIN_DELAY_AFTER_RAIN,
    UNIQUE_RUN,
    UNIQUE_START_MODE,
    UNIQUE_START_TIME,
    UNIQUE_STATUS,
    UNIQUE_STOP,
    UNIQUE_SUNRISE_OFFSET,
    WEEKDAYS,
    AnnikaIrrigation,
    IrrigationGroup,
    IrrigationSeason,
    unique_day,
    unique_minutes,
)


class _IrrigationEntity:
    _attr_should_poll = False

    def __init__(self, irrigation: AnnikaIrrigation) -> None:
        self._irrigation = irrigation

    async def _listen(self) -> None:
        self.async_on_remove(self._irrigation.subscribe(self.async_write_ha_state))


# --- switches ---------------------------------------------------------------


class IrrigationEnabledSwitch(_IrrigationEntity, SwitchEntity, RestoreEntity):
    """Whether the schedule waters at all. Turning it off stops a run."""

    _attr_name = "Irrigation Schedule"
    _attr_unique_id = UNIQUE_ENABLED
    _attr_icon = "mdi:sprinkler-variant"

    @property
    def is_on(self) -> bool:
        return self._irrigation.settings.enabled is True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self._irrigation.settings.enabled = last_state is None or last_state.state == STATE_ON
        self._irrigation.settings_changed()
        await self._listen()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._irrigation.settings.enabled = True
        self._irrigation.settings_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._irrigation.settings.enabled = False
        self._irrigation.settings_changed()


class IrrigationDaySwitch(_IrrigationEntity, SwitchEntity, RestoreEntity):
    """Whether a season waters on a weekday."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, irrigation: AnnikaIrrigation, season: IrrigationSeason, weekday: str) -> None:
        super().__init__(irrigation)
        self._key = (season.key, weekday)
        self._default = weekday in irrigation.default_days(season)
        self._attr_name = f"Irrigation {season.name} {weekday.capitalize()}"
        self._attr_unique_id = unique_day(season, weekday)

    @property
    def is_on(self) -> bool:
        return self._irrigation.settings.days.get(self._key) is True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self._irrigation.settings.days[self._key] = (
            self._default if last_state is None else last_state.state == STATE_ON
        )
        self._irrigation.settings_changed()
        await self._listen()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._irrigation.settings.days[self._key] = True
        self._irrigation.settings_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._irrigation.settings.days[self._key] = False
        self._irrigation.settings_changed()


# --- numbers ----------------------------------------------------------------


class _IrrigationNumber(_IrrigationEntity, RestoreNumber):
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def _read(self) -> float | None:
        raise NotImplementedError

    def _write(self, value: float) -> None:
        raise NotImplementedError

    def _default(self) -> float:
        raise NotImplementedError

    @property
    def native_value(self) -> float | None:
        return self._read()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        restored = last.native_value if last is not None else None
        valid = (
            restored is not None
            and self.native_min_value <= restored <= self.native_max_value
        )
        self._write(restored if valid else self._default())
        self._irrigation.settings_changed()
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        self._write(value)
        self._irrigation.settings_changed()


class IrrigationMinutesNumber(_IrrigationNumber):
    """Minutes each zone of a group runs in a season. 0 skips the group."""

    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_ZONE_MINUTES
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, irrigation: AnnikaIrrigation, season: IrrigationSeason, group: IrrigationGroup) -> None:
        super().__init__(irrigation)
        self._key = (season.key, group.key)
        self._initial = irrigation.default_minutes(season, group)
        self._attr_name = f"Irrigation {season.name} {group.name} Minutes"
        self._attr_unique_id = unique_minutes(season, group)

    def _read(self) -> float | None:
        return self._irrigation.settings.minutes.get(self._key)

    def _write(self, value: float) -> None:
        self._irrigation.settings.minutes[self._key] = value

    def _default(self) -> float:
        return self._initial


class IrrigationSunriseOffsetNumber(_IrrigationNumber):
    """Minutes from sunrise to start, negative for before it."""

    _attr_name = "Irrigation Sunrise Offset"
    _attr_unique_id = UNIQUE_SUNRISE_OFFSET
    _attr_icon = "mdi:weather-sunset-up"
    _attr_native_min_value = -MAX_SUNRISE_OFFSET_MINUTES
    _attr_native_max_value = MAX_SUNRISE_OFFSET_MINUTES
    _attr_native_step = 15
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _read(self) -> float | None:
        return self._irrigation.settings.sunrise_offset_minutes

    def _write(self, value: float) -> None:
        self._irrigation.settings.sunrise_offset_minutes = value

    def _default(self) -> float:
        return self._irrigation.default_sunrise_offset_minutes()


class IrrigationRainDelayAfterRainNumber(_IrrigationNumber):
    """Days the controller holds off watering once the rain sensor trips."""

    _attr_name = "Irrigation Rain Delay After Rain"
    _attr_unique_id = UNIQUE_RAIN_DELAY_AFTER_RAIN
    _attr_icon = "mdi:weather-pouring"
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_RAIN_DELAY_DAYS
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def _read(self) -> float | None:
        return self._irrigation.settings.rain_delay_after_rain

    def _write(self, value: float) -> None:
        self._irrigation.settings.rain_delay_after_rain = value

    def _default(self) -> float:
        return self._irrigation.default_rain_delay_after_rain()


class IrrigationManualMinutesNumber(_IrrigationNumber):
    """Safeguard for watering by hand: a Rain Bird zone switched on by hand closes after this.

    The schedule does not use it: each group has its own minutes per season.
    """

    _attr_name = "Irrigation Manual Limit"
    _attr_unique_id = UNIQUE_MANUAL_MINUTES
    _attr_icon = "mdi:timer-alert-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = MAX_MANUAL_MINUTES
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _read(self) -> float | None:
        return self._irrigation.settings.manual_minutes

    def _write(self, value: float) -> None:
        self._irrigation.settings.manual_minutes = value

    def _default(self) -> float:
        return self._irrigation.default_manual_minutes()


# --- start ------------------------------------------------------------------


class IrrigationStartModeSelect(_IrrigationEntity, SelectEntity, RestoreEntity):
    """Start relative to sunrise, or at a fixed time."""

    _attr_name = "Irrigation Start Mode"
    _attr_unique_id = UNIQUE_START_MODE
    # The options are keys; translations/<lang>.json says them in words.
    _attr_translation_key = "start_mode"
    _attr_icon = "mdi:clock-start"
    _attr_options = list(START_MODES)

    @property
    def current_option(self) -> str | None:
        return self._irrigation.settings.start_mode

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        restored = last_state.state if last_state is not None else None
        self._irrigation.settings.start_mode = (
            restored if restored in START_MODES else self._irrigation.default_start_mode()
        )
        self._irrigation.settings_changed()
        await self._listen()

    async def async_select_option(self, option: str) -> None:
        self._irrigation.settings.start_mode = option
        self._irrigation.settings_changed()


class IrrigationStartTime(_IrrigationEntity, TimeEntity, RestoreEntity):
    """The fixed start time, used when the start mode is `time`."""

    _attr_name = "Irrigation Start Time"
    _attr_unique_id = UNIQUE_START_TIME
    _attr_icon = "mdi:clock-outline"

    @property
    def native_value(self) -> time | None:
        return self._irrigation.settings.start_time

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        restored = dt_util.parse_time(last_state.state) if last_state is not None else None
        self._irrigation.settings.start_time = restored or self._irrigation.default_start_time()
        self._irrigation.settings_changed()
        await self._listen()

    async def async_set_value(self, value: time) -> None:
        self._irrigation.settings.start_time = value
        self._irrigation.settings_changed()


# --- actions ----------------------------------------------------------------


class IrrigationRunButton(_IrrigationEntity, ButtonEntity):
    """Water the current season's program now."""

    _attr_name = "Irrigation Run Now"
    _attr_unique_id = UNIQUE_RUN
    _attr_icon = "mdi:play"

    async def async_press(self) -> None:
        self._irrigation.run_now()


class IrrigationStopButton(_IrrigationEntity, ButtonEntity):
    """Stop a run in progress and close the zone that is open."""

    _attr_name = "Irrigation Stop"
    _attr_unique_id = UNIQUE_STOP
    _attr_icon = "mdi:stop"

    async def async_press(self) -> None:
        self._irrigation.stop("stopped")


# --- status -----------------------------------------------------------------


class IrrigationStatusSensor(_IrrigationEntity, SensorEntity):
    """What the schedule is doing, and the map annika-irrigation-card reads."""

    _attr_name = "Irrigation"
    _attr_unique_id = UNIQUE_STATUS
    _attr_icon = "mdi:sprinkler"
    _attr_translation_key = "irrigation_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATUSES)
    # The map of the schedule changes only with the YAML: no point in a copy per state change.
    _unrecorded_attributes = frozenset({"groups", "seasons", "zones", "entities", "pause_seconds", "program", "automation"})

    @property
    def native_value(self) -> str:
        if self._irrigation.settings.enabled is False and self._irrigation.current_zone is None:
            return STATUS_DISABLED
        return self._irrigation.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        irrigation = self._irrigation
        entity = irrigation.entity_id
        today = dt_util.now().date()
        season = irrigation.season_for(today)
        next_season = (
            irrigation.season_for(dt_util.as_local(irrigation.next_run).date())
            if irrigation.next_run else None
        )
        next_program = irrigation.program(next_season) if next_season else []
        return {
            "next_run": irrigation.next_run.isoformat() if irrigation.next_run else None,
            "next_run_duration_seconds": (
                sum(minutes * 60 for _, minutes in next_program)
                + max(0, len(next_program) - 1) * irrigation.pause_seconds
            ) if irrigation.next_run else None,
            "last_run": irrigation.last_run.isoformat() if irrigation.last_run else None,
            "last_result": irrigation.last_result,
            "current_season": season.key if season else None,
            "current_zone": irrigation.current_zone,
            "automation": irrigation.automation,
            # What today's run waters by the card's settings — for an
            # automation of the house's own to follow.
            "waters_today": irrigation.waters_on(today),
            "program": [
                {"entity": zone.entity_id, "minutes": minutes}
                for zone, minutes in (irrigation.program(season) if season else [])
            ],
            "pause_seconds": irrigation.pause_seconds,
            "groups": [{"key": group.key, "name": group.name} for group in irrigation.groups],
            "seasons": [
                {
                    "key": item.key,
                    "name": item.name,
                    "months": list(item.months),
                    "days": {
                        weekday: entity("switch", unique_day(item, weekday)) for weekday in WEEKDAYS
                    },
                    "minutes": {
                        group.key: entity("number", unique_minutes(item, group))
                        for group in irrigation.groups
                    },
                }
                for item in irrigation.seasons
            ],
            "zones": [
                {"entity": zone.entity_id, "group": zone.group, "name": zone.name}
                for zone in irrigation.zones
            ],
            "entities": {
                "enabled": entity("switch", UNIQUE_ENABLED),
                "start_mode": entity("select", UNIQUE_START_MODE),
                "sunrise_offset": entity("number", UNIQUE_SUNRISE_OFFSET),
                "start_time": entity("time", UNIQUE_START_TIME),
                "rain_delay_after_rain": entity("number", UNIQUE_RAIN_DELAY_AFTER_RAIN),
                "manual_minutes": entity("number", UNIQUE_MANUAL_MINUTES),
                "run": entity("button", UNIQUE_RUN),
                "stop": entity("button", UNIQUE_STOP),
                "rain_sensor": irrigation.rain_sensor,
                "rain_delay": irrigation.rain_delay,
                "next_start": entity("sensor", UNIQUE_NEXT_START),
                "automation": irrigation.automation,
            },
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()



class IrrigationNextStartSensor(_IrrigationEntity, SensorEntity):
    """When the next run starts by the card's settings, whoever waters.

    A timestamp, so an automation of the house's own can trigger on it
    (`trigger: time`, `at: sensor.irrigation_next_start`).
    """

    _attr_name = "Irrigation Next Start"
    _attr_unique_id = UNIQUE_NEXT_START
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        return self._irrigation.next_start

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()
        # Added after the status sensor wrote its map: have it write it again.
        self._irrigation.notify()


def sensors(irrigation: AnnikaIrrigation) -> list[SensorEntity]:
    return [IrrigationStatusSensor(irrigation), IrrigationNextStartSensor(irrigation)]

def switches(irrigation: AnnikaIrrigation) -> list[SwitchEntity]:
    return [IrrigationEnabledSwitch(irrigation)] + [
        IrrigationDaySwitch(irrigation, season, weekday)
        for season in irrigation.seasons
        for weekday in WEEKDAYS
    ]


def numbers(irrigation: AnnikaIrrigation) -> list[NumberEntity]:
    entities: list[NumberEntity] = [
        IrrigationMinutesNumber(irrigation, season, group)
        for season in irrigation.seasons
        for group in irrigation.groups
    ]
    entities.append(IrrigationSunriseOffsetNumber(irrigation))
    if irrigation.rain_sensor and irrigation.rain_delay:
        entities.append(IrrigationRainDelayAfterRainNumber(irrigation))
    # Only Rain Bird zones can be given a time limit when switched on by hand.
    if irrigation.rainbird_entries():
        entities.append(IrrigationManualMinutesNumber(irrigation))
    return entities
