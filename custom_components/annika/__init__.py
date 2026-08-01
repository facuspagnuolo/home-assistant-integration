"""Annika integration."""

from __future__ import annotations

import shutil
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CONF_API_URL, CONF_UNIT_ID, CONF_WEBHOOK_SECRET, DOMAIN
from .send_event import async_send_event

SERVICE_INSTALL_RESOURCES = "install_resources"
SERVICE_SEND_EVENT = "send_event"

JS_RESOURCES = (
    ("annika-ha-bridge.js", "/annika_static/annika-ha-bridge.js"),
    ("annika-automations-card.js", "/annika_static/annika-automations-card.js"),
    ("annika-lights-card.js", "/annika_static/annika-lights-card.js"),
    ("annika-ac-card.js", "/annika_static/annika-ac-card.js"),
    ("annika-heating-card.js", "/annika_static/annika-heating-card.js"),
    ("annika-cameras-card.js", "/annika_static/annika-cameras-card.js"),
    ("annika-alarm-card.js", "/annika_static/annika-alarm-card.js"),
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_URL): cv.url,
                vol.Required(CONF_UNIT_ID): cv.string,
                vol.Required(CONF_WEBHOOK_SECRET): cv.string,
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
        vol.Optional("data"): dict,
    }
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
                True,
            )
            for filename, url_path in JS_RESOURCES
        ]
    )
    for _, url_path in JS_RESOURCES:
        add_extra_js_url(hass, f"{url_path}?v={integration.version}")

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

    await async_install_resources()

    return True
