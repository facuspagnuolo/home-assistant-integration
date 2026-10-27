"""Entities of the Annika gate. See gate.py.

The cover is what people open, close and stop. Everything else is plain Home
Assistant entities, restored across restarts and starting from the YAML the
first time: the two travel times and the power threshold (numbers), a button
that calibrates, a switch for the notifications. The status sensor carries the
map of all of them (and of the four source entities), so annika-gate-card
draws itself without naming any.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.cover import ATTR_POSITION, CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started

from .gate import (
    CLOSING,
    DATA_GATE,
    IDLE,
    MAX_THRESHOLD,
    MAX_TRAVEL_SECONDS,
    MIN_TRAVEL_SECONDS,
    OPENING,
    STATUS_CLOSED,
    STATUSES,
    AnnikaGate,
    unique_auto_off,
    unique_calibrate,
    unique_closed_inverted,
    unique_close_seconds,
    unique_cover,
    unique_moving,
    unique_notify,
    unique_open_inverted,
    unique_open_seconds,
    unique_status,
    unique_threshold,
)
from .gate_relay import RelayError, find_relay

_LOGGER = logging.getLogger(__name__)

AUTO_OFF_REFRESH = timedelta(minutes=5)
MAX_AUTO_OFF = 60.0


class _GateEntity:
    _attr_should_poll = False

    def __init__(self, gate: AnnikaGate) -> None:
        self._gate = gate

    async def _listen(self) -> None:
        self.async_on_remove(self._gate.subscribe(self.async_write_ha_state))


# --- the gate ---------------------------------------------------------------


class GateCover(_GateEntity, CoverEntity):
    """The gate: open, close, stop, or go to a position."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = gate.name
        self._attr_unique_id = unique_cover(gate)

    @property
    def available(self) -> bool:
        return self._gate.available

    @property
    def current_cover_position(self) -> int:
        return round(self._gate.position_now())

    @property
    def is_opening(self) -> bool:
        return self._gate.shown_motion == OPENING

    @property
    def is_closing(self) -> bool:
        return self._gate.shown_motion == CLOSING

    @property
    def is_closed(self) -> bool:
        return self._gate.status == STATUS_CLOSED

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()
        self.async_on_remove(self._gate.subscribe_position(self.async_write_ha_state))
        # Added after the status sensor wrote its map: have it write it again.
        self._gate.notify()

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._gate.async_open()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._gate.async_close()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._gate.async_stop_movement()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self._gate.async_go_to(kwargs[ATTR_POSITION])


class GateMovingSensor(_GateEntity, BinarySensorEntity):
    """Whether the motor is running, by what it consumes."""

    _attr_device_class = BinarySensorDeviceClass.MOVING

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = f"{gate.name} Moving"
        self._attr_unique_id = unique_moving(gate)

    @property
    def is_on(self) -> bool:
        return self._gate.shown_motion != IDLE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()
        self._gate.notify()


# --- status -----------------------------------------------------------------


class GateStatusSensor(_GateEntity, SensorEntity, RestoreEntity):
    """What the gate is doing, and the map annika-gate-card reads."""

    _attr_icon = "mdi:gate"
    _attr_translation_key = "gate_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATUSES)
    # The map changes only with the YAML: no point in a copy per state change.
    _unrecorded_attributes = frozenset({"entities"})

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = gate.name
        self._attr_unique_id = unique_status(gate)

    @property
    def native_value(self) -> str:
        return self._gate.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        gate = self._gate
        entity = gate.entity_id
        return {
            # What a restart restores.
            "position": round(gate.position_now(), 1),
            "last_direction": gate.last_direction,
            "motion": gate.shown_motion,
            "closed": gate.closed_active,
            "open": gate.open_active,
            "open_seconds": gate.open_seconds,
            "close_seconds": gate.close_seconds,
            "threshold": gate.threshold,
            "calibration": dict(gate.calibration),
            "last_move": dict(gate.last_move) if gate.last_move else None,
            "pulse_seconds": gate.pulse_seconds,
            "entities": {
                "cover": entity("cover", unique_cover(gate)),
                "moving": entity("binary_sensor", unique_moving(gate)),
                "open_seconds": entity("number", unique_open_seconds(gate)),
                "close_seconds": entity("number", unique_close_seconds(gate)),
                "threshold": entity("number", unique_threshold(gate)),
                "calibrate": entity("button", unique_calibrate(gate)),
                "notify": entity("switch", unique_notify(gate)) if gate.notify_view else None,
                "auto_off": entity("number", unique_auto_off(gate)),
                "closed_inverted": entity("switch", unique_closed_inverted(gate)),
                "open_inverted": entity("switch", unique_open_inverted(gate)),
                "power": gate.power_sensor,
                "closed": gate.closed_sensor,
                "open": gate.open_sensor,
                "pulse": gate.pulse_switch,
            },
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                position = float(last_state.attributes.get("position"))
            except (TypeError, ValueError):
                position = None
            self._gate.restore(position, last_state.attributes.get("last_direction"))
        await self._listen()


# --- settings ---------------------------------------------------------------


class GateSettingNumber(_GateEntity, RestoreNumber):
    """A number the person edits: a travel time or the power threshold."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        gate: AnnikaGate,
        key: str,
        name: str,
        unique_id: str,
        default: float,
        minimum: float,
        maximum: float,
        step: float,
        unit: str,
        device_class: NumberDeviceClass,
        icon: str,
    ) -> None:
        super().__init__(gate)
        self._key = key
        self._default = default
        self._attr_name = f"{gate.name} {name}"
        self._attr_unique_id = unique_id
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        return getattr(self._gate.settings, self._key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        restored = last.native_value if last is not None else None
        valid = restored is not None and self.native_min_value <= restored <= self.native_max_value
        setattr(self._gate.settings, self._key, restored if valid else self._default)
        self._gate.settings_changed()
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        setattr(self._gate.settings, self._key, value)
        self._gate.settings_changed()


class GateRelayAutoOff(_GateEntity, NumberEntity):
    """The pulse relay's own auto-off timer, read from the device and written back to it.

    Unavailable when the relay is not a Shelly Home Assistant knows, or cannot be reached.
    """

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_AUTO_OFF
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_icon = "mdi:timer-off-outline"

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = f"{gate.name} Relay Auto Off"
        self._attr_unique_id = unique_auto_off(gate)
        self._value: float | None = None

    @property
    def available(self) -> bool:
        return self._value is not None

    @property
    def native_value(self) -> float | None:
        return self._value

    async def _async_refresh(self, _now: Any = None) -> None:
        relay = find_relay(self.hass, self._gate.pulse_switch)
        value = None
        if relay is not None:
            try:
                value = await relay.async_get_auto_off()
            except RelayError as error:
                _LOGGER.debug("Annika gate %s: could not read the relay's auto-off: %s", self._gate.name, error)
        if value != self._value:
            self._value = value
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._listen()
        # The Shelly integration may not have registered the relay yet: look again once it has, and now and then.
        self.async_on_remove(async_at_started(self.hass, self._async_refresh))
        self.async_on_remove(async_track_time_interval(self.hass, self._async_refresh, AUTO_OFF_REFRESH))
        self._gate.notify()

    async def async_set_native_value(self, value: float) -> None:
        relay = find_relay(self.hass, self._gate.pulse_switch)
        if relay is None:
            raise HomeAssistantError("The gate's pulse switch is not a Shelly relay Home Assistant can reach")
        try:
            await relay.async_set_auto_off(round(value, 1))
        except RelayError as error:
            raise HomeAssistantError(f"Could not set the relay's auto-off: {error}") from error
        await self._async_refresh()


class GateInvertSwitch(_GateEntity, SwitchEntity, RestoreEntity):
    """Whether an end sensor reads the other way round: on when the gate is NOT at that end."""

    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, gate: AnnikaGate, key: str, name: str, unique_id: str) -> None:
        super().__init__(gate)
        self._key = key
        self._attr_name = f"{gate.name} {name}"
        self._attr_unique_id = unique_id

    @property
    def is_on(self) -> bool:
        return getattr(self._gate, f"{self._key}_inverted")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (STATE_ON, STATE_OFF):
            setattr(self._gate.settings, f"{self._key}_inverted", last_state.state == STATE_ON)
        await self._listen()
        self._gate.settings_changed()

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self._gate.settings, f"{self._key}_inverted", True)
        self._gate.settings_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self._gate.settings, f"{self._key}_inverted", False)
        self._gate.settings_changed()


class GateNotifySwitch(_GateEntity, SwitchEntity, RestoreEntity):
    """Whether opening and closing send an Annika event."""

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = f"{gate.name} Notifications"
        self._attr_unique_id = unique_notify(gate)

    @property
    def is_on(self) -> bool:
        return self._gate.settings.notify is not False

    @property
    def icon(self) -> str:
        return "mdi:bell-outline" if self.is_on else "mdi:bell-off-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        self._gate.settings.notify = last_state is None or last_state.state == STATE_ON
        await self._listen()
        self._gate.notify()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._gate.settings.notify = True
        self._gate.notify()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._gate.settings.notify = False
        self._gate.notify()


# --- actions ----------------------------------------------------------------


class GateCalibrateButton(_GateEntity, ButtonEntity):
    """Time the gate all the way open and all the way closed."""

    _attr_icon = "mdi:ruler"

    def __init__(self, gate: AnnikaGate) -> None:
        super().__init__(gate)
        self._attr_name = f"{gate.name} Calibrate"
        self._attr_unique_id = unique_calibrate(gate)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Added after the status sensor wrote its map: have it write it again.
        self._gate.notify()

    async def async_press(self) -> None:
        await self._gate.async_calibrate()


# --- what the platform files ask for ----------------------------------------


def covers(gate: AnnikaGate) -> list[CoverEntity]:
    return [GateCover(gate)]


def sensors(gate: AnnikaGate) -> list[SensorEntity]:
    return [GateStatusSensor(gate)]


def binary_sensors(gate: AnnikaGate) -> list[BinarySensorEntity]:
    return [GateMovingSensor(gate)]


def numbers(gate: AnnikaGate) -> list[NumberEntity]:
    return [
        GateSettingNumber(
            gate,
            "open_seconds",
            "Opening Time",
            unique_open_seconds(gate),
            gate.config["travel_seconds"],
            MIN_TRAVEL_SECONDS,
            MAX_TRAVEL_SECONDS,
            0.1,
            UnitOfTime.SECONDS,
            NumberDeviceClass.DURATION,
            "mdi:timer-sand",
        ),
        GateSettingNumber(
            gate,
            "close_seconds",
            "Closing Time",
            unique_close_seconds(gate),
            gate.config["travel_seconds"],
            MIN_TRAVEL_SECONDS,
            MAX_TRAVEL_SECONDS,
            0.1,
            UnitOfTime.SECONDS,
            NumberDeviceClass.DURATION,
            "mdi:timer-sand",
        ),
        GateSettingNumber(
            gate,
            "threshold",
            "Power Threshold",
            unique_threshold(gate),
            gate.config["power_threshold"],
            1,
            MAX_THRESHOLD,
            1,
            UnitOfPower.WATT,
            NumberDeviceClass.POWER,
            "mdi:flash",
        ),
        GateRelayAutoOff(gate),
    ]


def buttons(gate: AnnikaGate) -> list[ButtonEntity]:
    return [GateCalibrateButton(gate)]


def switches(gate: AnnikaGate) -> list[SwitchEntity]:
    return [
        GateInvertSwitch(gate, "closed", "Invert Closed Sensor", unique_closed_inverted(gate)),
        GateInvertSwitch(gate, "open", "Invert Open Sensor", unique_open_inverted(gate)),
        *([GateNotifySwitch(gate)] if gate.notify_view else []),
    ]


BUILDERS = {
    "cover": covers,
    "sensor": sensors,
    "binary_sensor": binary_sensors,
    "number": numbers,
    "button": buttons,
    "switch": switches,
}


async def async_setup_platform(
    hass: HomeAssistant, platform: str, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(BUILDERS[platform](hass.data[DATA_GATE]))
