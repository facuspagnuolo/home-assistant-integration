"""What goes over the wire to Annika's API: `navigate` is always there for events that open a view."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.annika.const import CONF_API_URL, CONF_UNIT_ID, CONF_WEBHOOK_SECRET, DOMAIN
from custom_components.annika.send_event import AnnikaEventClient, async_send_event


@pytest.fixture
def posted(hass: HomeAssistant):
    hass.data[DOMAIN] = {CONF_API_URL: "https://api.test", CONF_UNIT_ID: "u1", CONF_WEBHOOK_SECRET: "s"}
    bodies: list[dict] = []

    class Response:
        status = 202

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def post(url, data, **kwargs):
        bodies.append(json.loads(data))
        return Response()

    session = MagicMock()
    session.post = post
    with patch("custom_components.annika.send_event.async_get_clientsession", return_value=session):
        yield bodies


async def test_events_that_open_a_view_always_carry_navigate(hass, posted):
    client = AnnikaEventClient(hass)
    await client.async_send({"eventId": "1", "type": "info", "message": "m", "view": "alarm"})
    await client.async_send({"eventId": "2", "type": "security", "message": "m", "view": "alarm", "navigate": True})
    assert posted[0]["navigate"] is False
    assert posted[1]["navigate"] is True


async def test_heartbeat_and_system_events_are_left_alone(hass, posted):
    client = AnnikaEventClient(hass)
    await client.async_send({"eventId": "1", "type": "heartbeat", "message": "m", "data": {}})
    await client.async_send({"eventId": "2", "type": "system", "message": "m"})
    assert all("navigate" not in body for body in posted)


async def test_the_service_always_sends_navigate_and_passes_the_actor(hass, posted):
    call = MagicMock()
    call.data = {"type": "info", "message": "m", "view": "alarm", "actor": "devices", "navigate": True}
    await async_send_event(hass, call)
    call.data = {"type": "info", "message": "m", "view": "alarm"}
    await async_send_event(hass, call)
    assert posted[0]["actor"] == "devices" and posted[0]["navigate"] is True
    assert posted[1]["navigate"] is False and "actor" not in posted[1]


@pytest.mark.parametrize("value", [0, 10, 1440])
async def test_reads_only_the_validated_rainbird_delay_with_a_signed_get(hass, value):
    hass.data[DOMAIN] = {CONF_API_URL: "https://api.test", CONF_UNIT_ID: "u1", CONF_WEBHOOK_SECRET: "s"}
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"rainbirdAlertDelayMinutes": value})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = response
    with patch("custom_components.annika.send_event.async_get_clientsession", return_value=session):
        assert await AnnikaEventClient(hass).async_rainbird_alert_delay() == value
    args, kwargs = session.get.call_args
    assert args[0] == "https://api.test/units/u1/settings"
    headers = kwargs["headers"]
    expected = hmac.new(b"s", f"{headers['x-annika-timestamp']}.".encode(), hashlib.sha256).hexdigest()
    assert headers["x-annika-signature"] == expected


@pytest.mark.parametrize("value", [-1, 1441, 1.5, True, "10", None])
async def test_rejects_invalid_remote_rainbird_settings(hass, value):
    hass.data[DOMAIN] = {CONF_API_URL: "https://api.test", CONF_UNIT_ID: "u1", CONF_WEBHOOK_SECRET: "s"}
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"rainbirdAlertDelayMinutes": value})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = response
    with patch("custom_components.annika.send_event.async_get_clientsession", return_value=session):
        with pytest.raises(HomeAssistantError, match="Invalid Rain Bird"):
            await AnnikaEventClient(hass).async_rainbird_alert_delay()
