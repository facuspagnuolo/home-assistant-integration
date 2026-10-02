"""Tests for the Rain Bird reconnector, against Home Assistant's real rainbird config flow."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.rainbird.config_flow import ConfigFlowError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pyrainbird.data import WifiParams
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.annika import rainbird as rb

MAC = "30:c6:f7:e3:d4:c4"
OLD_HOST = "192.0.2.3"
NEW_HOST = "192.0.2.9"
PASSWORD = "secreto"


@pytest.fixture
def controller_at():
    """Where the fake controller answers; None means nowhere."""
    location = {"host": NEW_HOST}

    async def test_connection(self, host, password):
        if host == location["host"] and password == PASSWORD:
            return "serial", WifiParams(mac_address=MAC)
        raise ConfigFlowError("no controller here", "cannot_connect")

    with patch(
        "homeassistant.components.rainbird.config_flow.RainbirdConfigFlowHandler._test_connection",
        test_connection,
    ), patch("homeassistant.components.rainbird.async_setup_entry", return_value=True), patch(
        "homeassistant.components.rainbird.async_unload_entry", return_value=True
    ):
        yield location


@pytest.fixture(autouse=True)
def lan():
    adapters = [
        {"enabled": True, "ipv4": [{"address": "192.0.2.1", "network_prefix": 28}], "ipv6": []}
    ]
    with patch.object(rb.network, "async_get_adapters", AsyncMock(return_value=adapters)), patch.object(
        rb, "_web_hosts", AsyncMock(return_value=set())
    ), patch.object(rb, "_arp_table", return_value={}):
        yield


@pytest.fixture
def annika_events():
    with patch.object(rb.AnnikaEventClient, "async_send", AsyncMock()) as send:
        yield send


def rainbird_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain="rainbird",
        title=OLD_HOST,
        unique_id=MAC,
        data={"host": OLD_HOST, "password": PASSWORD, "serial_number": "serial", "mac": MAC},
    )
    entry.add_to_hass(hass)
    return entry


async def search(hass, reconnector, entry):
    reconnector._outages[entry.entry_id] = rb._Outage()
    await reconnector._async_search(entry.entry_id)
    await hass.async_block_till_done()


async def test_reconnects_when_the_controller_moved(hass, controller_at, annika_events):
    entry = rainbird_entry(hass)
    reconnector = rb.RainbirdReconnector(hass)

    await search(hass, reconnector, entry)

    assert entry.data["host"] == NEW_HOST
    assert len(hass.config_entries.async_entries("rainbird")) == 1
    assert hass.config_entries.flow.async_progress() == []
    annika_events.assert_awaited_once()
    event = annika_events.await_args.args[0]
    assert event["type"] == "system"
    assert event["title"] == "Rain Bird reconectado"
    assert event["data"] == {"ip": NEW_HOST, "old_ip": OLD_HOST}
    assert entry.entry_id not in reconnector._outages


async def test_stays_quiet_when_the_controller_did_not_move(hass, controller_at, annika_events):
    controller_at["host"] = OLD_HOST
    entry = rainbird_entry(hass)
    reconnector = rb.RainbirdReconnector(hass)

    await search(hass, reconnector, entry)

    assert entry.data["host"] == OLD_HOST
    annika_events.assert_not_awaited()


async def test_reports_not_found_once_and_retries(hass, controller_at, annika_events):
    controller_at["host"] = None
    entry = rainbird_entry(hass)
    reconnector = rb.RainbirdReconnector(hass)

    await search(hass, reconnector, entry)
    outage = reconnector._outages[entry.entry_id]
    assert outage.cancel_timer is not None  # retry scheduled
    assert hass.config_entries.flow.async_progress() == []
    annika_events.assert_awaited_once()
    assert annika_events.await_args.args[0]["title"] == "Rain Bird no disponible"

    # The retry, 15 minutes later, does not notify again.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert outage.attempts == 2
    annika_events.assert_awaited_once()

    # The controller shows up at the next retry.
    controller_at["host"] = NEW_HOST
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=47))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data["host"] == NEW_HOST
    assert annika_events.await_count == 2
    assert annika_events.await_args.args[0]["title"] == "Rain Bird reconectado"


async def test_searches_only_after_staying_unavailable(hass, controller_at, annika_events):
    entry = rainbird_entry(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    er.async_get(hass).async_get_or_create(
        "switch", "rainbird", "zone-1", config_entry=entry, suggested_object_id="zona_1"
    )
    hass.states.async_set("switch.zona_1", STATE_ON)
    reconnector = rb.RainbirdReconnector(hass)
    await reconnector.async_start()
    await hass.async_block_till_done()
    assert reconnector._outages == {}

    # A short drop does nothing.
    hass.states.async_set("switch.zona_1", STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert entry.entry_id in reconnector._outages
    hass.states.async_set("switch.zona_1", STATE_ON)
    await hass.async_block_till_done()
    assert reconnector._outages == {}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data["host"] == OLD_HOST

    # Five minutes unavailable starts the search.
    hass.states.async_set("switch.zona_1", STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=12))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data["host"] == NEW_HOST
    annika_events.assert_awaited_once()
    await reconnector.async_stop()


async def test_ignores_other_entities(hass, controller_at, annika_events):
    entry = rainbird_entry(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    reconnector = rb.RainbirdReconnector(hass)
    await reconnector.async_start()

    hass.states.async_set("light.living", STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    assert reconnector._outages == {}
    await reconnector.async_stop()


async def test_does_nothing_without_rainbird(hass, annika_events):
    reconnector = rb.RainbirdReconnector(hass)
    await reconnector.async_start()
    await hass.async_block_till_done()

    assert reconnector._outages == {}
    await reconnector.async_stop()


async def test_an_entry_that_did_not_load_counts_as_down(hass, controller_at, annika_events):
    entry = rainbird_entry(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    reconnector = rb.RainbirdReconnector(hass)
    await reconnector.async_start()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.data["host"] == NEW_HOST
    await reconnector.async_stop()


def test_it_is_off_unless_the_unit_turns_it_on():
    from custom_components.annika import CONFIG_SCHEMA

    base = {"api_url": "https://api.example.com", "unit_id": "u1", "webhook_secret": "s"}
    assert CONFIG_SCHEMA({"annika": base})["annika"]["rainbird_reconnect"] is False
    assert CONFIG_SCHEMA({"annika": {**base, "rainbird_reconnect": True}})["annika"]["rainbird_reconnect"] is True
