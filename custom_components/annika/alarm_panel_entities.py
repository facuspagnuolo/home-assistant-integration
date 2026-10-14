"""Entities of the Annika alarm panel's automatic arming and disarming. See alarm_panel.py.

Whether each runs, when, and how long the house stays quiet first are plain
Home Assistant entities: restored across restarts, starting from the YAML the
first time, and editable from annika-alarm-card.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.select import SelectEntity
from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import STATE_ON, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .alarm_panel import DATA_ALARM_PANEL, MODES, AnnikaAlarmPanel
from .const import DOMAIN

AUTO_ARM_ENABLED = "auto_arm_enabled"
AUTO_ARM_TIME = "auto_arm_time"
AUTO_ARM_QUIET = "auto_arm_quiet_minutes"
AUTO_ARM_MODE = "auto_arm_mode"
AUTO_DISARM_ENABLED = "auto_disarm_enabled"
AUTO_DISARM_TIME = "auto_disarm_time"
AUTO_DISARM_MODE = "auto_disarm_mode"


def unique_id(key: str) -> str:
    return f"{DOMAIN}_alarm_{key}"


class _AutoEntity:
    _attr_should_poll = False

    def __init__(self, panel: AnnikaAlarmPanel, key: str, label: str) -> None:
        self._panel = panel
        self._attr_unique_id = unique_id(key)
        self._attr_name = f"{panel.name} {label}"

    async def _listen(self) -> None:
        self.async_on_remove(self._panel.subscribe(self.async_write_ha_state))
        # The panel's `auto` attribute names these entities: refresh it now that they exist.
        self._panel.notify_listeners()


class AutoSwitch(_AutoEntity, SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:shield-sync"

    def __init__(self, panel: AnnikaAlarmPanel, key: str, label: str, setting: str) -> None:
        super().__init__(panel, key, label)
        self._setting = setting

    @property
    def is_on(self) -> bool:
        return getattr(self._panel, self._setting)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, "off"):
            self._panel.configure_auto(**{self._setting: last.state == STATE_ON})
        await self._listen()

    async def async_turn_on(self, **kwargs) -> None:
        self._panel.configure_auto(**{self._setting: True})

    async def async_turn_off(self, **kwargs) -> None:
        self._panel.configure_auto(**{self._setting: False})


class AutoTime(_AutoEntity, TimeEntity, RestoreEntity):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, panel: AnnikaAlarmPanel, key: str, label: str, setting: str) -> None:
        super().__init__(panel, key, label)
        self._setting = setting

    @property
    def native_value(self) -> time:
        return getattr(self._panel, self._setting)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and (restored := dt_util.parse_time(last.state)) is not None:
            self._panel.configure_auto(**{self._setting: restored.replace(second=0, microsecond=0)})
        await self._listen()

    async def async_set_value(self, value: time) -> None:
        self._panel.configure_auto(**{self._setting: value.replace(second=0, microsecond=0)})


class AutoQuietMinutes(_AutoEntity, RestoreNumber):
    _attr_icon = "mdi:timer-sand"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, panel: AnnikaAlarmPanel) -> None:
        super().__init__(panel, AUTO_ARM_QUIET, "Auto Arm Quiet Minutes")

    @property
    def native_value(self) -> float:
        return self._panel.auto_arm_quiet

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._panel.configure_auto(auto_arm_quiet=int(last.native_value))
        await self._listen()

    async def async_set_native_value(self, value: float) -> None:
        self._panel.configure_auto(auto_arm_quiet=int(value))


class AutoModeSelect(_AutoEntity, SelectEntity, RestoreEntity):
    """The mode the panel arms itself in, or the one it disarms itself from."""

    _attr_icon = "mdi:shield-home"
    _attr_options = list(MODES)
    _attr_translation_key = "alarm_mode"

    def __init__(self, panel: AnnikaAlarmPanel, key: str, label: str, setting: str) -> None:
        super().__init__(panel, key, label)
        self._setting = setting

    @property
    def current_option(self) -> str:
        return getattr(self._panel, self._setting)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state in MODES:
            self._panel.configure_auto(**{self._setting: last.state})
        await self._listen()

    async def async_select_option(self, option: str) -> None:
        self._panel.configure_auto(**{self._setting: option})


async def async_setup_platform(
        hass: HomeAssistant, platform: str, async_add_entities: AddEntitiesCallback
) -> None:
    panel: AnnikaAlarmPanel = hass.data[DATA_ALARM_PANEL]
    entities = []
    if platform == "switch":
        if panel.has_auto_arm:
            entities.append(AutoSwitch(panel, AUTO_ARM_ENABLED, "Auto Arm", "auto_arm_enabled"))
        if panel.has_auto_disarm:
            entities.append(AutoSwitch(panel, AUTO_DISARM_ENABLED, "Auto Disarm", "auto_disarm_enabled"))
    elif platform == "time":
        if panel.has_auto_arm:
            entities.append(AutoTime(panel, AUTO_ARM_TIME, "Auto Arm Time", "auto_arm_time"))
        if panel.has_auto_disarm:
            entities.append(AutoTime(panel, AUTO_DISARM_TIME, "Auto Disarm Time", "auto_disarm_time"))
    elif platform == "number" and panel.has_auto_arm:
        entities.append(AutoQuietMinutes(panel))
    elif platform == "select":
        if panel.has_auto_arm:
            entities.append(AutoModeSelect(panel, AUTO_ARM_MODE, "Auto Arm Mode", "auto_arm_mode"))
        if panel.has_auto_disarm:
            entities.append(AutoModeSelect(panel, AUTO_DISARM_MODE, "Auto Disarm Mode", "auto_disarm_mode"))
    if entities:
        async_add_entities(entities)
