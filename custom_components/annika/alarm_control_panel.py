"""Annika's alarm panel as a Home Assistant entity. See alarm_panel.py."""

from __future__ import annotations

import copy
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .alarm_panel import (
    ARMED_PREFIX,
    DATA_ALARM_PANEL,
    MAX_ATTEMPTS,
    MAX_SECONDS,
    MODES,
    STATE_ARMING,
    STATE_DISARMED,
    STATE_PENDING,
    STATE_TRIGGERED,
    AnnikaAlarmPanel,
    CodeError,
)
from .alarm_panel_entities import (
    AUTO_ARM_ENABLED,
    AUTO_ARM_MODE,
    AUTO_ARM_QUIET,
    AUTO_ARM_TIME,
    AUTO_DISARM_ENABLED,
    AUTO_DISARM_MODE,
    AUTO_DISARM_TIME,
    unique_id,
)
from .const import DOMAIN
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

SERVICE_CHANGE_CODE = "change_code"

_STATES = {
    STATE_DISARMED: AlarmControlPanelState.DISARMED,
    STATE_ARMING: AlarmControlPanelState.ARMING,
    STATE_PENDING: AlarmControlPanelState.PENDING,
    STATE_TRIGGERED: AlarmControlPanelState.TRIGGERED,
    "armed_away": AlarmControlPanelState.ARMED_AWAY,
    "armed_night": AlarmControlPanelState.ARMED_NIGHT,
    "armed_vacation": AlarmControlPanelState.ARMED_VACATION,
}


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    panel: AnnikaAlarmPanel = hass.data[DATA_ALARM_PANEL]
    await panel.async_load()
    if panel.rules is not None:
        await panel.rules.async_load()
    async_add_entities([AnnikaAlarmControlPanel(panel)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_CHANGE_CODE,
        {
            vol.Required("current_code"): cv.string,
            vol.Required("new_code"): cv.string,
        },
        "async_change_code",
    )
    platform.async_register_entity_service(
        "set_timing",
        {
            vol.Required("mode"): vol.In(MODES),
            vol.Optional("arming"): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_SECONDS)),
            vol.Optional("pending"): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_SECONDS)),
        },
        "async_set_timing",
    )
    platform.async_register_entity_service(
        "set_mode_enabled",
        {vol.Required("mode"): vol.In(MODES), vol.Required("enabled"): cv.boolean},
        "async_set_mode_enabled",
    )
    platform.async_register_entity_service(
        "set_rule",
        {
            vol.Required("target"): vol.In(["zone", "sensor"]),
            vol.Required("id"): cv.string,
            vol.Required("mode"): vol.In(MODES),
            vol.Required("rule"): vol.Any(None, vol.In(["off", "warning", "trigger"])),
        },
        "async_set_rule",
    )
    platform.async_register_entity_service(
        "set_output",
        {
            vol.Required("output"): cv.string,
            vol.Optional("warning_enabled"): cv.boolean,
            vol.Optional("warning_seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=24 * 3600)),
            vol.Optional("trigger_enabled"): cv.boolean,
        },
        "async_set_output",
    )
    platform.async_register_entity_service(
        "set_warning",
        {
            vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            vol.Optional("window_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        },
        "async_set_warning",
    )
    platform.async_register_entity_service(
        "set_notification",
        {
            vol.Optional("warning"): cv.boolean,
            vol.Optional("trigger"): cv.boolean,
            vol.Optional("trigger_repeat"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
        },
        "async_set_notification",
    )
    platform.async_register_entity_service(
        "test_output", {vol.Required("output"): cv.string}, "async_test_output"
    )

    # Only when the configuration opts in: with these anyone who can call
    # services can arm or disarm with no code.
    if panel.allow_disarm_without_code:
        _LOGGER.warning("annika.disarm_without_code is enabled: the alarm can be disarmed with no code")
        platform.async_register_entity_service(
            "disarm_without_code", None, "async_disarm_without_code"
        )
    if panel.allow_arm_without_code:
        _LOGGER.warning("annika.arm_without_code is enabled: the alarm can be armed with no code")
        platform.async_register_entity_service(
            "arm_without_code",
            {vol.Required("mode"): vol.In(MODES)},
            "async_arm_without_code",
        )


def _raise(error: CodeError) -> None:
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=error.reason,
        translation_placeholders={"attempts": str(MAX_ATTEMPTS)},
    ) from error


class AnnikaAlarmControlPanel(AlarmControlPanelEntity, RestoreEntity):
    """The panel. Arming and disarming ask for the code; the rules engine does not."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    # Big, and rebuilt from the rules' own storage: not for the recorder.
    _unrecorded_attributes = frozenset({"config", "decisions", "auto"})
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = True
    _FEATURES = {
        "away": AlarmControlPanelEntityFeature.ARM_AWAY,
        "night": AlarmControlPanelEntityFeature.ARM_NIGHT,
        "vacation": AlarmControlPanelEntityFeature.ARM_VACATION,
    }

    def __init__(self, panel: AnnikaAlarmPanel) -> None:
        self._panel = panel
        self._attr_name = panel.name
        self._attr_unique_id = f"{DOMAIN}_alarm_panel"

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        # Only the modes that exist and are enabled can be armed.
        features = AlarmControlPanelEntityFeature.TRIGGER
        for mode in self._panel.enabled_modes:
            features |= self._FEATURES[mode]
        return features

    async def async_added_to_hass(self) -> None:
        self._panel.entity_id = self.entity_id
        last = await self.async_get_last_state()
        deadline = None
        mode = None
        state = None
        if last is not None and last.state in _STATE_NAMES:
            state = last.state
            mode = last.attributes.get("mode")
            raw = last.attributes.get("deadline")
            deadline = dt_util.parse_datetime(raw) if raw else None
        self._panel.restore(state, mode, deadline)
        self.async_on_remove(self._panel.subscribe(self.async_write_ha_state))

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        return _STATES[self._panel.state]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        panel = self._panel
        # A copy: the timings, rules and decisions are edited in place, and a state
        # that shares them with the live data looks unchanged to Home Assistant, which
        # then fires no event and keeps serving the old values.
        return copy.deepcopy({
            "mode": panel.mode,
            "deadline": panel.deadline.isoformat() if panel.deadline else None,
            "locked_until": panel.locked_until.isoformat() if panel.locked else None,
            "modes": panel.modes,
            "auto": self._auto(),
            **(self._panel.rules.attributes() if self._panel.rules else {}),
        })

    def _auto(self) -> dict[str, Any]:
        """What the card needs to edit the automatic arming: entity ids and the mode."""

        panel = self._panel
        registry = er.async_get(self.hass)

        def find(domain: str, key: str) -> str | None:
            return registry.async_get_entity_id(domain, DOMAIN, unique_id(key))

        auto: dict[str, Any] = {}
        if panel.has_auto_arm:
            auto["arm"] = {
                "mode": panel.auto_arm_mode,
                "waiting": panel.auto_arm_waiting,
                "has_sensors": bool(panel.auto_arm_sensors),
                "enabled": find("switch", AUTO_ARM_ENABLED),
                "time": find("time", AUTO_ARM_TIME),
                "quiet_minutes": find("number", AUTO_ARM_QUIET),
                "mode_entity": find("select", AUTO_ARM_MODE),
            }
        if panel.has_auto_disarm:
            auto["disarm"] = {
                "enabled": find("switch", AUTO_DISARM_ENABLED),
                "time": find("time", AUTO_DISARM_TIME),
                "mode": panel.auto_disarm_mode,
                "mode_entity": find("select", AUTO_DISARM_MODE),
            }
        return auto

    async def _run(self, action) -> None:
        try:
            action()
        except CodeError as error:
            _raise(error)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._run(lambda: self._panel.disarm(code))

    async def async_disarm_without_code(self) -> None:
        await self._run(lambda: self._panel.disarm(skip_code=True))

    async def async_arm_without_code(self, mode: str) -> None:
        await self._run(lambda: self._panel.arm(mode, skip_code=True))

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._run(lambda: self._panel.arm("away", code))

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._run(lambda: self._panel.arm("night", code))

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        await self._run(lambda: self._panel.arm("vacation", code))

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        self._panel.trigger()

    async def async_change_code(self, current_code: str, new_code: str) -> None:
        try:
            await self._panel.async_change_code(current_code, new_code)
        except CodeError as error:
            _raise(error)


_STATE_NAMES = set(_STATES)


def _rules(self: AnnikaAlarmControlPanel):
    if self._panel.rules is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_rules")
    return self._panel.rules


def _guard(action):
    try:
        action()
    except ValueError as error:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_target"
        ) from error


async def _async_set_timing(self, mode, **values):
    self._panel.set_timing(mode, **values)


async def _async_set_mode_enabled(self, mode, enabled):
    await self._run(lambda: self._panel.set_mode_enabled(mode, enabled))


async def _async_set_rule(self, target, id, mode, rule):
    _guard(lambda: _rules(self).set_rule(target, id, mode, rule))


async def _async_set_output(self, output, **values):
    _guard(lambda: _rules(self).set_output(output, **values))


async def _async_set_warning(self, **values):
    _rules(self).set_warning(**values)


async def _async_set_notification(self, **values):
    _rules(self).set_notification(**values)


async def _async_test_output(self, output):
    _guard(lambda: _rules(self).test_output(output))


AnnikaAlarmControlPanel.async_set_timing = _async_set_timing
AnnikaAlarmControlPanel.async_set_mode_enabled = _async_set_mode_enabled
AnnikaAlarmControlPanel.async_set_rule = _async_set_rule
AnnikaAlarmControlPanel.async_set_output = _async_set_output
AnnikaAlarmControlPanel.async_set_warning = _async_set_warning
AnnikaAlarmControlPanel.async_set_notification = _async_set_notification
AnnikaAlarmControlPanel.async_test_output = _async_test_output
