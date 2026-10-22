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

from .actor import async_setup_actor
from .alarm import DATA_ALARM, AnnikaAlarmSensors
from .alarm_panel import ALARM_SCHEMA, DATA_ALARM_PANEL, AnnikaAlarmPanel
from .cameras import CAMERAS_SCHEMA, DATA_CAMERAS, AnnikaCameras
from .alarm_rules import AnnikaAlarmRules
from .doorbells import DATA_DOORBELLS, DOORBELLS_SCHEMA, AnnikaDoorbells
from .const import (
    CONF_ALARM,
    CONF_CAMERAS,
    CONF_DOORBELLS,
    CONF_ALARM_SENSORS,
    CONF_API_URL,
    CONF_DEVICES,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_IRRIGATION,
    CONF_RAINBIRD_RECONNECT,
    CONF_POOL_FILTER,
    CONF_UNIT_ID,
    CONF_WEBHOOK_SECRET,
    DISCOVERY_KIND,
    DOMAIN,
    KIND_ALARM,
    KIND_CAMERAS,
    KIND_DOORBELLS,
    KIND_IRRIGATION,
    KIND_POOL_FILTER,
)
from .heartbeat import HeartbeatReporter
from .irrigation import DATA_IRRIGATION, IRRIGATION_SCHEMA, AnnikaIrrigation
from .rainbird import RainbirdReconnector
from .pool_filter import DATA_POOL_FILTER, POOL_FILTER_SCHEMA, AnnikaPoolFilter
from .send_event import ACTOR_DEVICES, async_send_event

_LOGGER = logging.getLogger(__name__)

SERVICE_INSTALL_RESOURCES = "install_resources"
SERVICE_SEND_EVENT = "send_event"

JS_RESOURCES = (
    ("annika-common.js", "/annika_static/annika-common.js"),
    ("annika-ha-bridge.js", "/annika_static/annika-ha-bridge.js"),
    ("annika-automations-card.js", "/annika_static/annika-automations-card.js"),
    ("annika-lights-card.js", "/annika_static/annika-lights-card.js"),
    ("annika-covers-card.js", "/annika_static/annika-covers-card.js"),
    ("annika-ac-card.js", "/annika_static/annika-ac-card.js"),
    ("annika-heating-card.js", "/annika_static/annika-heating-card.js"),
    ("annika-cameras-card.js", "/annika_static/annika-cameras-card.js"),
    ("annika-doorbell-card.js", "/annika_static/annika-doorbell-card.js"),
    ("annika-remote-card.js", "/annika_static/annika-remote-card.js"),
    ("annika-alarm-card.js", "/annika_static/annika-alarm-card.js"),
    ("annika-activity-card.js", "/annika_static/annika-activity-card.js"),
    ("annika-irrigation-card.js", "/annika_static/annika-irrigation-card.js"),
    ("annika-pool-filter-card.js", "/annika_static/annika-pool-filter-card.js"),
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_URL): cv.url,
                vol.Required(CONF_UNIT_ID): cv.string,
                vol.Required(CONF_WEBHOOK_SECRET): cv.string,
                # Find the Rain Bird controller again when its IP changes and
                # point the rainbird integration at it. See rainbird.py.
                vol.Optional(CONF_RAINBIRD_RECONNECT, default=False): cv.boolean,
                # Seasons, groups and zones of a watering schedule the person
                # edits from annika-irrigation-card. See irrigation.py.
                vol.Optional(CONF_IRRIGATION): IRRIGATION_SCHEMA,
                # The pool filter's seasonal timetable, edited from
                # annika-pool-filter-card. See pool_filter.py.
                vol.Optional(CONF_POOL_FILTER): POOL_FILTER_SCHEMA,
                # Annika's own alarm panel: name, starting code and the time
                # each mode takes to arm and to sound. See alarm_panel.py.
                # Checked where each is started, not here: a mistake in one of these
                # blocks must not stop the rest of the integration from loading.
                vol.Optional(CONF_ALARM): dict,
                vol.Optional(CONF_CAMERAS): dict,
                vol.Optional(CONF_DOORBELLS): dict,
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

# Event types that reach Annika's staff instead of the unit's customers, so there
# is no dashboard view for a notification to open.
EVENT_TYPES_WITHOUT_VIEW = {"system", "heartbeat"}


def _require_view_for_customer_events(data: dict) -> dict:
    if data["type"] not in EVENT_TYPES_WITHOUT_VIEW and not data.get("view"):
        raise vol.Invalid(f"view is required for {data['type']} events")
    if data.get("actor") == ACTOR_DEVICES and not data.get("navigate"):
        # Only the tablets are told, and only navigate tells them: it would do nothing.
        raise vol.Invalid(f"actor {ACTOR_DEVICES} needs navigate: true")
    return data


SEND_EVENT_SCHEMA = vol.All(vol.Schema(
    {
        vol.Required("type"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("actor"): cv.string,
        vol.Optional("event_id"): cv.string,
        vol.Optional("view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
        # `cv.string` (not `cv.url`) for image_url since Annika's backend also
        # accepts a relative HA path here, not only an absolute URL — see
        # backend/src/validators/unit-event.ts in the app repo.
        vol.Optional("image_url"): cv.string,
        vol.Optional("data"): dict,
        vol.Optional("navigate", default=False): cv.boolean,
    }
), _require_view_for_customer_events)



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


IRRIGATION_PLATFORMS = ("switch", "number", "select", "time", "button", "sensor")


async def async_setup_irrigation(hass: HomeAssistant, config: ConfigType) -> None:
    """Wire up the irrigation schedule, if this unit configures one.

    Starts after Home Assistant has: the zones and the rain sensor belong to
    another integration, and the first schedule needs the restored settings,
    which the entities only hand over once they are added.
    """

    irrigation_config = config[DOMAIN].get(CONF_IRRIGATION)
    if not irrigation_config:
        return

    irrigation = AnnikaIrrigation(hass, irrigation_config)
    hass.data[DATA_IRRIGATION] = irrigation

    for platform in IRRIGATION_PLATFORMS:
        hass.async_create_task(
            async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_IRRIGATION}, config)
        )

    async def async_start_irrigation(_event=None) -> None:
        await irrigation.async_start()

    if hass.is_running:
        await async_start_irrigation()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_start_irrigation)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, irrigation.async_stop)


POOL_FILTER_PLATFORMS = ("switch", "number", "time", "button", "sensor")


async def async_setup_pool_filter(hass: HomeAssistant, config: ConfigType) -> None:
    """Wire up the pool filter's timetable, if this unit configures one.

    Starts after Home Assistant has, like the irrigation: the switch belongs
    to another integration, and the first timetable needs the restored
    settings, which the entities only hand over once they are added.
    """

    pool_filter_config = config[DOMAIN].get(CONF_POOL_FILTER)
    if not pool_filter_config:
        return

    pool_filter = AnnikaPoolFilter(hass, pool_filter_config)
    hass.data[DATA_POOL_FILTER] = pool_filter

    for platform in POOL_FILTER_PLATFORMS:
        hass.async_create_task(
            async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_POOL_FILTER}, config)
        )

    async def async_start_pool_filter(_event=None) -> None:
        await pool_filter.async_start()

    if hass.is_running:
        await async_start_pool_filter()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_start_pool_filter)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, pool_filter.async_stop)


async def async_setup_alarm_panel(hass: HomeAssistant, config: ConfigType) -> None:
    """Create Annika's alarm panel, if this unit configures one."""

    panel_config = config[DOMAIN].get(CONF_ALARM)
    if not panel_config:
        return
    try:
        panel_config = ALARM_SCHEMA(panel_config)
    except vol.Invalid as error:
        _LOGGER.error("Annika alarm not started, invalid configuration: %s", error)
        return

    panel = AnnikaAlarmPanel(hass, panel_config)
    hass.data[DATA_ALARM_PANEL] = panel
    if panel_config["zones"] or panel_config["outputs"]:
        panel.rules = AnnikaAlarmRules(hass, panel, panel_config)
    hass.async_create_task(
        async_load_platform(hass, "alarm_control_panel", DOMAIN, {}, config)
    )
    for platform in ("switch", "time", "number", "select"):
        hass.async_create_task(
            async_load_platform(hass, platform, DOMAIN, {DISCOVERY_KIND: KIND_ALARM}, config)
        )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, panel.async_stop)


async def async_setup_cameras(hass: HomeAssistant, config: ConfigType) -> None:
    """Create Annika's cameras, if this unit configures any."""

    cameras_config = config[DOMAIN].get(CONF_CAMERAS)
    if not cameras_config:
        return
    try:
        cameras_config = CAMERAS_SCHEMA(cameras_config)
    except vol.Invalid as error:
        _LOGGER.error("Annika cameras not started, invalid configuration: %s", error)
        return

    cameras = AnnikaCameras(hass, cameras_config)
    hass.data[DATA_CAMERAS] = cameras
    hass.async_create_task(
        async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_CAMERAS}, config)
    )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cameras.async_stop)


async def async_setup_doorbells(hass: HomeAssistant, config: ConfigType) -> None:
    """Create Annika's doorbells, if this unit configures any."""

    doorbells_config = config[DOMAIN].get(CONF_DOORBELLS)
    if not doorbells_config:
        return
    try:
        doorbells_config = DOORBELLS_SCHEMA(doorbells_config)
    except vol.Invalid as error:
        _LOGGER.error("Annika doorbells not started, invalid configuration: %s", error)
        return

    doorbells = AnnikaDoorbells(hass, doorbells_config)
    hass.data[DATA_DOORBELLS] = doorbells
    hass.async_create_task(
        async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_DOORBELLS}, config)
    )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, doorbells.async_stop)


async def async_setup_actor_sensor(hass: HomeAssistant, config: ConfigType) -> None:
    """Wire up actor attribution and the sensor that surfaces it.

    Unconditional — unlike the alarm layer there is nothing to configure, and
    a unit with no attributed actions simply keeps a sensor that never leaves
    its restored value. See actor.py.
    """

    async_setup_actor(hass)
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))


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
    await async_setup_actor_sensor(hass, config)
    await async_setup_irrigation(hass, config)
    await async_setup_pool_filter(hass, config)
    await async_setup_alarm_panel(hass, config)
    await async_setup_cameras(hass, config)
    await async_setup_doorbells(hass, config)

    heartbeat_reporter = HeartbeatReporter(hass)
    await heartbeat_reporter.async_start()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, heartbeat_reporter.async_stop)

    if config[DOMAIN][CONF_RAINBIRD_RECONNECT]:
        rainbird_reconnector = RainbirdReconnector(hass)
        await rainbird_reconnector.async_start()
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, rainbird_reconnector.async_stop)

    await async_install_resources()

    return True
