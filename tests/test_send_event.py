"""What goes over the wire to Annika's API: `navigate` is always there for events that open a view."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

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
