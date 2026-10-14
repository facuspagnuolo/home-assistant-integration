"""Annika irrigation selects. See irrigation.py and irrigation_entities.py."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import alarm_panel_entities, irrigation_entities
from .const import DISCOVERY_KIND, KIND_ALARM, KIND_IRRIGATION
from .irrigation import DATA_IRRIGATION


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the irrigation selects from the YAML config."""

    if discovery_info is not None and discovery_info.get(DISCOVERY_KIND) == KIND_ALARM:
        await alarm_panel_entities.async_setup_platform(hass, "select", async_add_entities)
        return

    if discovery_info is None or discovery_info.get(DISCOVERY_KIND) != KIND_IRRIGATION:
        return

    irrigation = hass.data[DATA_IRRIGATION]
    async_add_entities([irrigation_entities.IrrigationStartModeSelect(irrigation)])
