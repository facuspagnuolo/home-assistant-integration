"""Send unit events to Annika's API.

Signs the request with the unit's webhook secret and posts it, mirroring the
standalone annika_send_event.py script this replaces. Unit credentials come
from this integration's own configuration.yaml entry (see const.py) rather
than a hand-parsed secrets.yaml.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import aiohttp

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_URL, CONF_UNIT_ID, CONF_WEBHOOK_SECRET, DOMAIN

TIMEOUT_SECONDS = 10


class AnnikaEventClient:
    """Sign and send unit events to Annika's API."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def async_send(self, event: dict) -> None:
        """Post a signed unit event."""

        unit_config = self._hass.data[DOMAIN]
        body = json.dumps(event).encode()
        timestamp = str(int(time.time()))
        url = (
            f"{unit_config[CONF_API_URL].rstrip('/')}"
            f"/units/{unit_config[CONF_UNIT_ID]}/events"
        )

        session = async_get_clientsession(self._hass)
        try:
            async with session.post(
                url,
                data=body,
                headers={
                    "content-type": "application/json",
                    "x-annika-timestamp": timestamp,
                    "x-annika-signature": self._sign(
                        unit_config[CONF_WEBHOOK_SECRET], timestamp, body
                    ),
                },
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            ) as response:
                if response.status >= 400:
                    detail = (await response.text()).strip()
                    raise HomeAssistantError(
                        f"Annika event failed with status {response.status}: "
                        f"{detail or response.reason}"
                    )
        except aiohttp.ClientError as error:
            raise HomeAssistantError(f"Annika event failed: {error}") from error

    def _sign(self, secret: str, timestamp: str, body: bytes) -> str:
        return hmac.new(
            secret.encode(),
            f"{timestamp}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()


async def async_send_event(hass: HomeAssistant, call: ServiceCall) -> None:
    """Sign and post a unit event to Annika's API."""

    event = {
        "eventId": call.data.get("event_id") or str(uuid.uuid4()),
        "type": call.data["type"],
        "message": call.data["message"],
    }
    if call.data.get("title"):
        event["title"] = call.data["title"]
    if call.data.get("actor"):
        event["actor"] = call.data["actor"]
    if call.data.get("url"):
        event["url"] = call.data["url"]
    if call.data.get("image_url"):
        event["imageUrl"] = call.data["image_url"]
    if call.data.get("data"):
        event["data"] = call.data["data"]

    await AnnikaEventClient(hass).async_send(event)
