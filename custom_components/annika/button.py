"""Annika irrigation buttons. See irrigation.py and irrigation_entities.py."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import irrigation_entities
from .const import DISCOVERY_KIND, KIND_IRRIGATION
from .irrigation import DATA_IRRIGATION


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the irrigation buttons from the YAML config."""

    if discovery_info is None or discovery_info.get(DISCOVERY_KIND) != KIND_IRRIGATION:
        return

    irrigation = hass.data[DATA_IRRIGATION]
    async_add_entities([irrigation_entities.IrrigationRunButton(irrigation), irrigation_entities.IrrigationStopButton(irrigation)])
