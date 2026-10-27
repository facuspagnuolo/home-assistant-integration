"""Annika cover: the gate. See gate.py and gate_entities.py."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import gate_entities
from .const import DISCOVERY_KIND, KIND_GATE


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the gate's cover from the YAML config."""

    if discovery_info is not None and discovery_info.get(DISCOVERY_KIND) == KIND_GATE:
        await gate_entities.async_setup_platform(hass, "cover", async_add_entities)
