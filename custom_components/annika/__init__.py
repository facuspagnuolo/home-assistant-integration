"""Annika integration."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .alarm import DATA_ALARM, AnnikaAlarmSensors
from .const import (
    CONF_ALARM_SENSORS,
    CONF_API_URL,
    CONF_DEVICES,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_UNIT_ID,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
)
from .heartbeat import HeartbeatReporter
from .send_event import async_send_event

_LOGGER = logging.getLogger(__name__)

SERVICE_INSTALL_RESOURCES = "install_resources"
SERVICE_SEND_EVENT = "send_event"

JS_RESOURCES = (
    ("annika-common.js", "/annika_static/annika-common.js"),
    ("annika-entity-toggle-feature.js", "/annika_static/annika-entity-toggle-feature.js"),
    ("annika-ha-bridge.js", "/annika_static/annika-ha-bridge.js"),
    ("annika-automations-card.js", "/annika_static/annika-automations-card.js"),
    ("annika-lights-card.js", "/annika_static/annika-lights-card.js"),
    ("annika-covers-card.js", "/annika_static/annika-covers-card.js"),
    ("annika-ac-card.js", "/annika_static/annika-ac-card.js"),
    ("annika-heating-card.js", "/annika_static/annika-heating-card.js"),
    ("annika-cameras-card.js", "/annika_static/annika-cameras-card.js"),
    ("annika-remote-card.js", "/annika_static/annika-remote-card.js"),
    ("annika-alarm-card.js", "/annika_static/annika-alarm-card.js"),
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_URL): cv.url,
                vol.Required(CONF_UNIT_ID): cv.string,
                vol.Required(CONF_WEBHOOK_SECRET): cv.string,
                # Physical sensors Annika wraps with an alarm participation
                # switch. Devices can be named or given by registry id; every
                # binary_sensor they own is picked up. See alarm.py.
                vol.Optional(CONF_ALARM_SENSORS): vol.Schema(
                    {
                        vol.Optional(CONF_DEVICES, default=[]): vol.All(
                            cv.ensure_list, [cv.string]
                        ),
                        # A bare entity id, or { entity, name } — the same
                        # shape the Annika cards take. Listing an entity a
                        # device already brought in is how to rename it.
                        vol.Optional(CONF_ENTITIES, default=[]): vol.All(
                            cv.ensure_list,
                            [
                                vol.Any(
                                    cv.entity_id,
                                    vol.Schema(
                                        {
                                            vol.Required("entity"): cv.entity_id,
                                            vol.Optional("name"): cv.string,
                                        }
                                    ),
                                )
                            ],
                        ),
                        vol.Optional(CONF_EXCLUDE, default=[]): vol.All(
                            cv.ensure_list, [cv.entity_id]
                        ),
                    }
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SEND_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("actor"): cv.string,
        vol.Optional("event_id"): cv.string,
        # Dashboard path to deep-link to (e.g. "/dashboard-doorbell") and a
        # snapshot/camera image for the push notification. `cv.string` (not
        # `cv.url`) for image_url since Annika's backend also accepts a
        # relative HA path here, not only an absolute URL — see
        # backend/src/validators/unit-event.ts in the app repo.
        vol.Optional("url"): cv.string,
        vol.Optional("image_url"): cv.string,
        vol.Optional("data"): dict,
    }
)



def _resource_version(path: Path, version: str) -> str:
    """Cache-busting token for a JS resource.

    The integration version alone is not enough: the frontend caches these
    files aggressively (and so does the Annika app's webview), so editing a
    card without releasing a new version leaves clients running the old file
    against a new dashboard config. Hashing the file's contents means every
    edit gets its own URL, released or not.
    """

    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return version

    return f"{version}.{digest}"



async def async_setup_alarm_sensors(hass: HomeAssistant, config: ConfigType) -> None:
    """Wire up the alarm participation layer, if this unit configures one.

    Resolution waits for Home Assistant to finish starting: the panels live in
    another integration, and at this point their entities may not be in the
    registry yet. After that it keeps listening, so a panel added later — or a
    zone enabled on an existing one — shows up without a restart.
    """

    alarm_config = config.get(CONF_ALARM_SENSORS)
    if not alarm_config:
        return

    sensors = AnnikaAlarmSensors(hass, alarm_config)
    hass.data[DATA_ALARM] = sensors

    async def async_start_alarm_sensors(_event=None) -> None:
        sensors.async_refresh()
        if not sensors.sensors:
            _LOGGER.warning(
                "Annika alarm: no source sensors matched the configuration; "
                "nothing to wrap"
            )
        for platform in ("binary_sensor", "switch"):
            hass.async_create_task(
                async_load_platform(hass, platform, DOMAIN, {}, config)
            )

        @callback
        def registry_updated(_event) -> None:
            sensors.async_refresh()

        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated)

    if hass.is_running:
        await async_start_alarm_sensors()
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, async_start_alarm_sensors
        )


async def async_setup(
        hass: HomeAssistant,
        config: ConfigType,
) -> bool:
    """Set up the Annika integration."""

    hass.data[DOMAIN] = config[DOMAIN]

    integration = await async_get_integration(hass, DOMAIN)
    integration_directory = integration.file_path
    source_theme = (
            integration_directory
            / "resources"
            / "themes"
            / "annika-dark.yaml"
    )
    destination_theme = Path(hass.config.path("themes")) / "annika-dark.yaml"
    source_scripts_directory = (
            integration_directory
            / "resources"
            / "scripts"
    )
    destination_packages_directory = Path(hass.config.path("packages"))

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path,
                str(integration_directory / "resources" / "www" / filename),
                # No long-lived cache headers: these files change whenever a
                # card is edited, and a stale copy in a browser (or in the
                # Annika app's webview) renders an old card against a new
                # dashboard config. The `?v=` token below still lets clients
                # cache within a single version.
                False,
            )
            for filename, url_path in JS_RESOURCES
        ]
    )
    www_directory = integration_directory / "resources" / "www"
    resource_urls = await hass.async_add_executor_job(
        lambda: [
            f"{url_path}?v={_resource_version(www_directory / filename, integration.version)}"
            for filename, url_path in JS_RESOURCES
        ]
    )
    for resource_url in resource_urls:
        add_extra_js_url(hass, resource_url)

    async def async_install_resources(call: ServiceCall | None = None) -> None:
        """Install Annika resources in the Home Assistant config directory."""

        def copy_resources() -> None:
            if not source_theme.exists():
                raise FileNotFoundError(f"Annika resource was not found at {source_theme}")

            destination_theme.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_theme, destination_theme)

            destination_packages_directory.mkdir(parents=True, exist_ok=True)
            for source_script in source_scripts_directory.glob("*.yaml"):
                shutil.copy2(
                    source_script,
                    destination_packages_directory / source_script.name,
                )

        await hass.async_add_executor_job(copy_resources)
        await hass.services.async_call("frontend", "reload_themes", blocking=True)

        if call is not None:
            persistent_notification.async_create(
                hass,
                "Annika resources were installed or updated. "
                "Restart Home Assistant to apply script changes.",
                title="Annika resources installed",
                notification_id="annika_resources_installed",
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_RESOURCES,
        async_install_resources,
    )
    async def async_handle_send_event(call: ServiceCall) -> None:
        await async_send_event(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_EVENT,
        async_handle_send_event,
        schema=SEND_EVENT_SCHEMA,
    )

    await async_setup_alarm_sensors(hass, config[DOMAIN])

    heartbeat_reporter = HeartbeatReporter(hass)
    await heartbeat_reporter.async_start()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, heartbeat_reporter.async_stop)

    await async_install_resources()

    return True
