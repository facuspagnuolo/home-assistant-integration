"""The locks sensor, the settings of each lock and the services annika-locks-card edits through."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .alarm_panel import MODES
from .const import DOMAIN
from .locks import (
    CLOSE_MAX_SECONDS,
    CLOSE_MIN_SECONDS,
    OPEN_MAX_SECONDS,
    OPEN_MIN_SECONDS,
    DATA_LOCKS,
    MAX_TEMP_HOURS,
    AnnikaLocks,
    CodeError,
    _Lock,
)

SERVICE_ADD_LOCK_CODE = "add_lock_code"
SERVICE_DELETE_LOCK_CODE = "delete_lock_code"
SERVICE_IMPORT_LOCK_CODES = "import_lock_codes"
SERVICE_RENAME_LOCK_CODE = "rename_lock_code"
SERVICE_SET_LOCK_RULE = "set_lock_rule"
SERVICE_TEST_LOCK_RULE = "test_lock_rule"


def _error(error: CodeError) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=error.key, translation_placeholders=error.placeholders
    )


async def async_setup_platform(
        hass: HomeAssistant, platform_name: str, async_add_entities: AddEntitiesCallback
) -> None:
    locks: AnnikaLocks = hass.data[DATA_LOCKS]
    if platform_name == "switch":
        async_add_entities(
            entity for lock in locks.locks for entity in (HoldSwitch(locks, lock), CloseSwitch(locks, lock), OpenSwitch(locks, lock))
        )
        return
    if platform_name == "number":
        async_add_entities(
            entity for lock in locks.locks for entity in (CloseSecondsNumber(locks, lock), OpenSecondsNumber(locks, lock))
        )
        return

    await locks.async_start()
    async_add_entities([AnnikaLocksSensor(locks)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ADD_LOCK_CODE,
        {
            vol.Required("name"): cv.string,
            vol.Optional("type", default="fixed"): vol.In(["fixed", "temporary"]),
            vol.Optional("code"): vol.Any(None, cv.string, vol.Coerce(str)),
            vol.Optional("locks"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("hours"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TEMP_HOURS)),
            vol.Optional("until"): cv.string,
        },
        "async_add_lock_code",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_LOCK_CODE, {vol.Required("id"): cv.string}, "async_delete_lock_code"
    )
    platform.async_register_entity_service(SERVICE_IMPORT_LOCK_CODES, {}, "async_import_lock_codes")
    platform.async_register_entity_service(
        SERVICE_RENAME_LOCK_CODE,
        {vol.Required("id"): cv.string, vol.Required("name"): cv.string},
        "async_rename_lock_code",
    )
    platform.async_register_entity_service(
        SERVICE_SET_LOCK_RULE,
        {
            vol.Optional("enabled"): cv.boolean,
            vol.Optional("locks"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("modes"): vol.All(cv.ensure_list, [vol.In(MODES)]),
        },
        "async_set_lock_rule",
    )
    platform.async_register_entity_service(SERVICE_TEST_LOCK_RULE, {}, "async_test_lock_rule")


class AnnikaLocksSensor(SensorEntity):
    """State is when a door was last opened; attributes are everything the card shows."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:lock-open-variant"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The codes are in the attributes: they must not end up in the database's history.
    _unrecorded_attributes = frozenset({"config", "codes", "events"})

    def __init__(self, locks: AnnikaLocks) -> None:
        self._locks = locks
        self._attr_name = locks.name
        self._attr_unique_id = f"{DOMAIN}_locks"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._locks.subscribe(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        return self._locks.last_open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # A copy: the data is edited in place, and a state that shares it with the live
        # data looks unchanged to Home Assistant, which then keeps serving the old values.
        return copy.deepcopy(self._locks.attributes())

    async def async_add_lock_code(self, **values) -> None:
        try:
            await self._locks.async_add_code(
                values["name"],
                values.get("type", "fixed"),
                code=values.get("code"),
                lock_ids=values.get("locks"),
                hours=values.get("hours"),
                until=values.get("until"),
            )
        except CodeError as error:
            raise _error(error) from error

    async def async_delete_lock_code(self, id: str) -> None:
        try:
            await self._locks.async_delete_code(id)
        except CodeError as error:
            raise _error(error) from error

    async def async_import_lock_codes(self) -> None:
        await self._locks.async_import_codes()

    async def async_rename_lock_code(self, id: str, name: str) -> None:
        try:
            await self._locks.async_rename_code(id, name)
        except CodeError as error:
            raise _error(error) from error

    async def async_set_lock_rule(self, **values) -> None:
        try:
            self._locks.set_rule(**values)
        except CodeError as error:
            raise _error(error) from error

    async def async_test_lock_rule(self) -> None:
        self._locks.test_rule()


# --- the settings of each lock ------------------------------------------------


class _Setting:
    _attr_should_poll = False
    _attr_icon: str | None = None

    def __init__(self, locks: AnnikaLocks, lock: _Lock, key: str, label: str) -> None:
        self._locks = locks
        self._lock = lock
        self._attr_unique_id = f"{DOMAIN}_lock_{lock.id}_{key}"
        self._attr_name = f"{lock.name} {label}"

    async def _listen(self) -> None:
        self.async_on_remove(self._locks.subscribe(self.async_write_ha_state))
        # The sensor's attributes name these entities: refresh them now that they exist.
        self._locks.notify()


class HoldSwitch(_Setting, SwitchEntity, RestoreEntity):
    """Whether the card asks to hold the button to unlock this door."""

    _attr_icon = "mdi:gesture-tap-hold"

    def __init__(self, locks: AnnikaLocks, lock: _Lock) -> None:
        super().__init__(locks, lock, "hold", "Hold to unlock")

    @property
    def is_on(self) -> bool:
        return self._lock.hold

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, "off"):
            self._locks.set_lock_settings(self._lock, hold=last.state == STATE_ON)
        await self._listen()

    async def async_turn_on(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, hold=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, hold=False)


class CloseSwitch(_Setting, SwitchEntity, RestoreEntity):
    """Whether this lock locks itself some seconds after its door closes."""

    _attr_icon = "mdi:lock-clock"

    def __init__(self, locks: AnnikaLocks, lock: _Lock) -> None:
        super().__init__(locks, lock, "close", "Lock when closed")

    @property
    def available(self) -> bool:
        return self._lock.sensor is not None

    @property
    def is_on(self) -> bool:
        return self._lock.close_enabled

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, "off"):
            self._locks.set_lock_settings(self._lock, close_enabled=last.state == STATE_ON)
        await self._listen()

    async def async_turn_on(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, close_enabled=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, close_enabled=False)


class CloseSecondsNumber(_Setting, RestoreNumber):
    """How many seconds after the door closes the lock locks itself."""

    _attr_icon = "mdi:timer-lock-outline"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = CLOSE_MIN_SECONDS
    _attr_native_max_value = CLOSE_MAX_SECONDS
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, locks: AnnikaLocks, lock: _Lock) -> None:
        super().__init__(locks, lock, "close_seconds", "Lock when closed after")

    @property
    def available(self) -> bool:
        return self._lock.sensor is not None

    @property
    def native_value(self) -> float:
        return self._lock.close_seconds

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._locks.set_lock_settings(self._lock, close_seconds=int(last.native_value))
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        self._locks.set_lock_settings(self._lock, close_seconds=int(value))


class OpenSwitch(_Setting, SwitchEntity, RestoreEntity):
    """Whether this lock's door being left open is told after some seconds."""

    _attr_icon = "mdi:door-open"

    def __init__(self, locks: AnnikaLocks, lock: _Lock) -> None:
        super().__init__(locks, lock, "open", "Notify when left open")

    @property
    def available(self) -> bool:
        return self._lock.sensor is not None

    @property
    def is_on(self) -> bool:
        return self._lock.open_enabled

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, "off"):
            self._locks.set_lock_settings(self._lock, open_enabled=last.state == STATE_ON)
        await self._listen()

    async def async_turn_on(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, open_enabled=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._locks.set_lock_settings(self._lock, open_enabled=False)


class OpenSecondsNumber(_Setting, RestoreNumber):
    """How many seconds the door may stay open before it is told."""

    _attr_icon = "mdi:timer-alert-outline"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = OPEN_MIN_SECONDS
    _attr_native_max_value = OPEN_MAX_SECONDS
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, locks: AnnikaLocks, lock: _Lock) -> None:
        super().__init__(locks, lock, "open_seconds", "Notify when left open after")

    @property
    def available(self) -> bool:
        return self._lock.sensor is not None

    @property
    def native_value(self) -> float:
        return self._lock.open_seconds

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._locks.set_lock_settings(self._lock, open_seconds=int(last.native_value))
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        self._locks.set_lock_settings(self._lock, open_seconds=int(value))
