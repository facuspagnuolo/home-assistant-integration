"""Annika numbers: irrigation, the pool filter and the gate. See irrigation_entities.py, pool_filter_entities.py and gate_entities.py."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import alarm_panel_entities, gate_entities, irrigation_entities, locks_entities, pool_filter_entities
from .const import DISCOVERY_KIND, KIND_ALARM, KIND_GATE, KIND_IRRIGATION, KIND_LOCKS, KIND_POOL_FILTER
from .irrigation import DATA_IRRIGATION


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the numbers from the YAML config."""

    kind = discovery_info.get(DISCOVERY_KIND) if discovery_info else None
    if kind == KIND_IRRIGATION:
        irrigation = hass.data[DATA_IRRIGATION]
        async_add_entities(irrigation_entities.numbers(irrigation))
    elif kind == KIND_ALARM:
        await alarm_panel_entities.async_setup_platform(hass, "number", async_add_entities)
    elif kind == KIND_POOL_FILTER:
        await pool_filter_entities.async_setup_platform(hass, "number", async_add_entities)
    elif kind == KIND_LOCKS:
        await locks_entities.async_setup_platform(hass, "number", async_add_entities)
    elif kind == KIND_GATE:
        await gate_entities.async_setup_platform(hass, "number", async_add_entities)
