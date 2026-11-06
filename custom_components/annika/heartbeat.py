"""Build and periodically send Annika unit health reports."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .send_event import AnnikaEventClient

BATTERY_WARNING_LEVEL = 30
HEARTBEAT_INTERVAL = timedelta(minutes=1)
UNAVAILABLE_WARNING_AFTER = timedelta(minutes=5)

MONITORED_UNAVAILABLE_DOMAINS = {
    "light",
    "switch",
    "lock",
    "cover",
    "climate",
    "camera",
    "binary_sensor",
}

# Rain Bird already has its own reconnection and alert (see rainbird.py); reporting
# its entities as an unavailable device would tell the owner about the same outage twice.
# Annika's own entities (the irrigation zones, for one) only mirror another device, so they
# go unavailable with it and would report that outage a second time under another name.
EXCLUDED_DEVICE_PLATFORMS = {"rainbird", DOMAIN}

SYSTEM_CPU_ENTITY_ID = "sensor.system_monitor_processor_use"
SYSTEM_MEMORY_ENTITY_ID = "sensor.system_monitor_memory_usage"
SYSTEM_DISK_ENTITY_ID = "sensor.system_monitor_disk_usage"

_LOGGER = logging.getLogger(__name__)


class HeartbeatReporter:
    """Collect Home Assistant health information and report it to Annika."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._client = AnnikaEventClient(hass)
        self._remove_interval: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """Send the first report and schedule subsequent reports."""

        await self.async_send()
        self._remove_interval = async_track_time_interval(
            self._hass,
            self.async_send,
            HEARTBEAT_INTERVAL,
        )

    async def async_stop(self, _event: object | None = None) -> None:
        """Stop periodic reporting."""

        if self._remove_interval is not None:
            self._remove_interval()
            self._remove_interval = None

    async def async_send(self, _now: datetime | None = None) -> None:
        """Build and send a heartbeat without disrupting Home Assistant on failure."""

        try:
            await self._client.async_send(
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "heartbeat",
                    "title": "Unit heartbeat",
                    "message": "Unit health report",
                    "data": self.build(),
                }
            )
        except Exception:
            _LOGGER.exception("Unable to send Annika heartbeat")

    def build(self) -> dict:
        """Build the current unit health report."""

        return {
            "timestamp": self._timestamp(datetime.now(timezone.utc)),
            "system": self._system_usage(),
            "unavailable": self._unavailable_entities(),
            "unavailableDevices": self._unavailable_devices(),
            "updates": self._pending_updates(),
            "batteries": self._low_batteries(),
        }

    def _system_usage(self) -> dict[str, float | None]:
        return {
            "cpu": self._numeric_sensor_value(SYSTEM_CPU_ENTITY_ID),
            "memory": self._numeric_sensor_value(SYSTEM_MEMORY_ENTITY_ID),
            "disk": self._numeric_sensor_value(SYSTEM_DISK_ENTITY_ID),
        }

    def _unavailable_entities(self) -> list[dict]:
        now = datetime.now(timezone.utc)

        return [
            {
                "entityId": state.entity_id,
                "name": state.name,
                "since": self._timestamp(state.last_changed),
            }
            for state in self._hass.states.async_all()
            if state.state == "unavailable"
               and now - state.last_changed >= UNAVAILABLE_WARNING_AFTER
               and state.entity_id.split(".", 1)[0] in MONITORED_UNAVAILABLE_DOMAINS
        ]

    def _unavailable_devices(self) -> list[dict]:
        """Devices whose monitored entities are all unavailable.

        A camera that loses power takes all its entities down with it, so the
        entity list alone says "30 unavailable" for two cameras. A device counts
        as down only when every one of its monitored entities has been
        unavailable for the warning period; a single sensor failing on its own
        is not a device failure. Entities that belong to no device stand for
        themselves. Integrations with their own recovery flow are left out.
        """

        now = datetime.now(timezone.utc)
        entity_registry = er.async_get(self._hass)
        device_registry = dr.async_get(self._hass)
        groups: dict[str, dict] = {}

        for state in self._hass.states.async_all():
            if state.entity_id.split(".", 1)[0] not in MONITORED_UNAVAILABLE_DOMAINS:
                continue

            entry = entity_registry.async_get(state.entity_id)
            if entry is not None and entry.platform in EXCLUDED_DEVICE_PLATFORMS:
                continue

            device = (
                device_registry.async_get(entry.device_id)
                if entry is not None and entry.device_id
                else None
            )
            device_id = device.id if device is not None else state.entity_id
            group = groups.setdefault(
                device_id,
                {
                    "name": (device.name_by_user or device.name) if device else None,
                    "fallback_name": state.name,
                    "total": 0,
                    "unavailable_since": [],
                },
            )
            group["total"] += 1
            if state.state == "unavailable" and now - state.last_changed >= UNAVAILABLE_WARNING_AFTER:
                group["unavailable_since"].append(state.last_changed)

        return [
            {
                "deviceId": device_id,
                "name": group["name"] or group["fallback_name"],
                "since": self._timestamp(min(group["unavailable_since"])),
                "unavailableEntities": len(group["unavailable_since"]),
                "totalEntities": group["total"],
            }
            for device_id, group in groups.items()
            if group["unavailable_since"] and len(group["unavailable_since"]) == group["total"]
        ]

    def _pending_updates(self) -> list[dict]:
        return [
            {
                "entityId": state.entity_id,
                "name": state.name,
                "installedVersion": self._optional_string(
                    state.attributes.get("installed_version")
                ),
                "latestVersion": self._optional_string(
                    state.attributes.get("latest_version")
                ),
            }
            for state in self._hass.states.async_all("update")
            if state.state == "on"
        ]

    def _low_batteries(self) -> list[dict]:
        batteries: list[dict] = []

        for state in self._hass.states.async_all("sensor"):
            if state.attributes.get("device_class") != "battery":
                continue

            try:
                level = float(state.state)
            except (TypeError, ValueError):
                continue

            if math.isfinite(level) and 0 <= level < BATTERY_WARNING_LEVEL:
                batteries.append(
                    {
                        "entityId": state.entity_id,
                        "name": state.name,
                        "level": level,
                    }
                )

        batteries.extend(
            {
                "entityId": state.entity_id,
                "name": state.name,
                "level": None,
            }
            for state in self._hass.states.async_all("binary_sensor")
            if state.attributes.get("device_class") == "battery"
            and state.state == "on"
        )

        return batteries

    def _numeric_sensor_value(self, entity_id: str) -> float | None:
        state = self._hass.states.get(entity_id)

        if state is None or state.state in {"unknown", "unavailable"}:
            return None

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None

        return value if math.isfinite(value) and 0 <= value <= 100 else None

    def _timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _optional_string(self, value: object | None) -> str | None:
        return None if value is None else str(value)
