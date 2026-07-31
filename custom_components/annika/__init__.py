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

BRIDGE_URL_PATH = "/annika_static/annika-ha-bridge.js"

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
    bridge_script = (
            integration_directory
            / "resources"
            / "www"
            / "annika-ha-bridge.js"
    )
    source_theme = (
            integration_directory
            / "resources"
            / "themes"
            / "annika-dark.yaml"
    )
    destination_theme = Path(hass.config.path("themes")) / "annika-dark.yaml"
    source_script = (
            integration_directory
            / "resources"
            / "scripts"
            / "send_notification.yaml"
    )
    destination_script = (
            Path(hass.config.path("scripts")) / "send_notification.yaml"
    )

    await hass.http.async_register_static_paths(
        [StaticPathConfig(BRIDGE_URL_PATH, str(bridge_script), True)]
    )
    add_extra_js_url(hass, f"{BRIDGE_URL_PATH}?v={integration.version}")

    async def async_install_resources(call: ServiceCall | None = None) -> None:
        """Install Annika resources in the Home Assistant config directory."""

        def copy_resources() -> None:
            for source, destination in (
                (source_theme, destination_theme),
                (source_script, destination_script),
            ):
                if not source.exists():
                    raise FileNotFoundError(f"Annika resource was not found at {source}")

                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

        await hass.async_add_executor_job(copy_resources)
        await hass.services.async_call("frontend", "reload_themes", blocking=True)
        await hass.services.async_call("script", "reload", blocking=True)

        if call is not None:
            persistent_notification.async_create(
                hass,
                "Annika resources were installed or updated.",
                title="Annika resources installed",
                notification_id="annika_resources_installed",
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_RESOURCES,
        async_install_resources,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_EVENT,
        lambda call: async_send_event(hass, call),
        schema=SEND_EVENT_SCHEMA,
    )

    await async_install_resources()

    return True
