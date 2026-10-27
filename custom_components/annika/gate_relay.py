"""The Shelly relay that pulses the gate's board: read and set its auto-off timer.

The gate releases the relay by itself after every pulse, but if the network or
Home Assistant drops while it is on, the board's input stays pressed. The
relay's own auto-off timer covers that. Home Assistant's Shelly integration
does not expose it, so it is read and written on the device, which the
integration's config entry says how to reach. Anything that is not a Shelly,
or cannot be reached, simply has no auto-off to show.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

SHELLY_DOMAIN = "shelly"
REQUEST_TIMEOUT = 5
CHANNEL = re.compile(r"(?:switch:|relay_)(\d+)")


class RelayError(Exception):
    """The device could not be read or written."""


class ShellyRelay:
    """One relay channel of a Shelly, over its local HTTP API (generation 1, or 2 and later)."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        generation: int,
        channel: int,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._hass = hass
        self._host = host
        self._generation = generation
        self._channel = channel
        self._username = username
        self._password = password

    async def _async_get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        session = async_get_clientsession(self._hass)
        kwargs: dict[str, Any] = {"timeout": aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)}
        if self._username and self._password:
            if self._generation >= 2:
                kwargs["middlewares"] = (aiohttp.DigestAuthMiddleware(self._username, self._password),)
            else:
                kwargs["auth"] = aiohttp.BasicAuth(self._username, self._password)
        try:
            async with session.get(f"http://{self._host}{path}", params=params, **kwargs) as response:
                if response.status in (401, 403):
                    raise RelayError("auth")
                response.raise_for_status()
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise RelayError(str(error)) from error

    async def async_get_auto_off(self) -> float:
        """Seconds the relay stays on before it turns itself off; 0 when it never does."""

        if self._generation >= 2:
            config = await self._async_get("/rpc/Switch.GetConfig", {"id": self._channel})
            return float(config.get("auto_off_delay") or 0) if config.get("auto_off") else 0.0
        config = await self._async_get(f"/settings/relay/{self._channel}")
        return float(config.get("auto_off") or 0)

    async def async_set_auto_off(self, seconds: float) -> None:
        """Turn the timer on for `seconds`, or off with 0."""

        if self._generation >= 2:
            on = seconds > 0
            params = {"id": self._channel, "config": json.dumps({"auto_off": on, **({"auto_off_delay": seconds} if on else {})}, separators=(",", ":"))}
            await self._async_get("/rpc/Switch.SetConfig", params)
            return
        await self._async_get(f"/settings/relay/{self._channel}", {"auto_off": seconds})


def find_relay(hass: HomeAssistant, entity_id: str) -> ShellyRelay | None:
    """The Shelly relay behind `entity_id`, or None if it is not one (or not registered yet)."""

    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != SHELLY_DOMAIN or entry.config_entry_id is None:
        return None
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry is None or not config_entry.data.get("host"):
        return None
    match = CHANNEL.search(entry.unique_id or "")
    return ShellyRelay(
        hass,
        config_entry.data["host"],
        int(config_entry.data.get("gen", 1)),
        int(match.group(1)) if match else 0,
        config_entry.data.get("username"),
        config_entry.data.get("password"),
    )
