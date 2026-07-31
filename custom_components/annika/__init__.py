"""Annika integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

DOMAIN = "annika"
SERVICE_INSTALL_RESOURCES = "install_resources"

BRIDGE_URL_PATH = "/annika_static/annika-ha-bridge.js"


async def async_setup(
        hass: HomeAssistant,
        config: ConfigType,
) -> bool:
    """Set up the Annika integration."""

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

    await hass.http.async_register_static_paths(
        [StaticPathConfig(BRIDGE_URL_PATH, str(bridge_script), True)]
    )
    add_extra_js_url(hass, f"{BRIDGE_URL_PATH}?v={integration.version}")

    async def async_install_resources(call: ServiceCall | None = None) -> None:
        """Install Annika resources in the Home Assistant config directory."""

        def copy_theme() -> None:
            if not source_theme.exists():
                raise FileNotFoundError(
                    f"Annika theme was not found at {source_theme}"
                )

            destination_theme.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source_theme,
                destination_theme,
            )

        await hass.async_add_executor_job(copy_theme)
        await hass.services.async_call(
            "frontend",
            "reload_themes",
            blocking=True,
        )

        if call is not None:
            persistent_notification.async_create(
                hass,
                (
                    "El theme de Annika fue instalado en "
                    "`/config/themes/annika-dark.yaml`."
                ),
                title="Recursos de Annika instalados",
                notification_id="annika_resources_installed",
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_RESOURCES,
        async_install_resources,
    )

    await async_install_resources()

    return True
