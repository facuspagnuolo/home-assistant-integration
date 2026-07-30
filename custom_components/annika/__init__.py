"""Annika integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

DOMAIN = "annika"
SERVICE_INSTALL_RESOURCES = "install_resources"


async def async_setup(
        hass: HomeAssistant,
        config: ConfigType,
) -> bool:
    """Set up the Annika integration."""

    async def async_install_resources(call: ServiceCall) -> None:
        """Install Annika resources in the Home Assistant config directory."""

        integration_directory = Path(__file__).resolve().parent

        source_theme = (
                integration_directory
                / "resources"
                / "themes"
                / "annika-dark.yaml"
        )

        destination_directory = Path(hass.config.path("themes"))
        destination_theme = destination_directory / "annika-dark.yaml"

        def copy_resources() -> None:
            if not source_theme.exists():
                raise FileNotFoundError(
                    f"Annika theme was not found at {source_theme}"
                )

            destination_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source_theme,
                destination_theme,
            )

        await hass.async_add_executor_job(copy_resources)

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

    return True
