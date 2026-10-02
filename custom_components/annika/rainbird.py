"""Reconnect the Rain Bird integration when its controller changes IP.

Annika does not control the router in most units, so the DHCP lease of the Rain
Bird controller can change at any time and the `rainbird` integration keeps
talking to the old address. This module finds the controller again and points
the integration at the new address, the same way someone would do it by hand:

1. Something of the `rainbird` integration goes unavailable (or the integration
   never finished loading).
2. After a grace period, if it is still down, every address of the local network
   is tried by starting the integration's own config flow with that host and the
   stored password. The integration identifies the controller by its MAC: when
   the address belongs to the controller that is already configured, the flow
   aborts with `already_configured`, updates the host of the existing entry and
   reloads it. Any other address returns the form with an error and the flow is
   closed.
3. Annika's staff gets a `system` unit event: reconnected, or not found (once
   per outage). While it stays down the search is retried with a backoff.

Off unless the unit opts in, since not every house has a Rain Bird:

    annika:
      rainbird_reconnect: true
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.components import network
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

RAINBIRD_DOMAIN = "rainbird"
RAINBIRD_FLOW_LOGGER = "homeassistant.components.rainbird.config_flow"

# A short drop (a reload, a Wi-Fi hiccup) should not start a search.
GRACE_PERIOD = timedelta(minutes=5)
# When the controller is not found, try again after these delays; the last one
# repeats for as long as it stays down.
RETRY_DELAYS = (timedelta(minutes=15), timedelta(minutes=30), timedelta(hours=1))

PARALLEL_ATTEMPTS = 16
PORT_TIMEOUT_SECONDS = 2
# Networks bigger than this are only searched around Home Assistant's address.
MAX_NETWORK_PREFIX = 22


@dataclass
class _Outage:
    """Bookkeeping for a Rain Bird entry that is currently down."""

    cancel_timer: Callable[[], None] | None = None
    attempts: int = 0
    notified_not_found: bool = False


@dataclass
class _SearchResult:
    host: str | None = None
    tried: int = 0
    networks: list[str] = field(default_factory=list)


class RainbirdReconnector:
    """Watch the Rain Bird integration and reconnect it when its IP changes."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._client = AnnikaEventClient(hass)
        self._outages: dict[str, _Outage] = {}
        self._search_lock = asyncio.Lock()
        self._unsubscribers: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        """Start watching once Home Assistant is running."""

        @callback
        def started(_event: Event | None = None) -> None:
            self._unsubscribers.append(
                self._hass.bus.async_listen(
                    EVENT_STATE_CHANGED,
                    self._state_changed,
                    event_filter=self._is_rainbird_state,
                )
            )
            # Entries that failed to load at startup never change state again
            # on their own, so look at all of them once.
            for entry in self._entries():
                self._evaluate(entry)

        if self._hass.is_running:
            started()
        else:
            self._unsubscribers.append(
                self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, started)
            )

    async def async_stop(self, _event: Event | None = None) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        for outage in self._outages.values():
            if outage.cancel_timer:
                outage.cancel_timer()
        self._outages.clear()

    # ------------------------------------------------------------- detection

    def _entries(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self._hass.config_entries.async_entries(RAINBIRD_DOMAIN)
            if entry.disabled_by is None
        ]

    @callback
    def _is_rainbird_state(self, event_data) -> bool:
        entry = er.async_get(self._hass).async_get(event_data["entity_id"])
        return entry is not None and entry.platform == RAINBIRD_DOMAIN

    @callback
    def _state_changed(self, event: Event) -> None:
        registry_entry = er.async_get(self._hass).async_get(event.data["entity_id"])
        if registry_entry is None or registry_entry.config_entry_id is None:
            return
        entry = self._hass.config_entries.async_get_entry(registry_entry.config_entry_id)
        if entry is not None and entry.disabled_by is None:
            self._evaluate(entry)

    def _is_down(self, entry: ConfigEntry) -> bool:
        if entry.state is not ConfigEntryState.LOADED:
            return True
        for registry_entry in er.async_entries_for_config_entry(
            er.async_get(self._hass), entry.entry_id
        ):
            state = self._hass.states.get(registry_entry.entity_id)
            if state is not None and state.state == STATE_UNAVAILABLE:
                return True
        return False

    @callback
    def _evaluate(self, entry: ConfigEntry) -> None:
        outage = self._outages.get(entry.entry_id)
        if not self._is_down(entry):
            if outage is not None:
                _LOGGER.info("Rain Bird %s is available again", entry.title)
                if outage.cancel_timer:
                    outage.cancel_timer()
                del self._outages[entry.entry_id]
            return
        if outage is None:
            _LOGGER.info(
                "Rain Bird %s is unavailable; searching in %s if it stays down",
                entry.title,
                GRACE_PERIOD,
            )
            outage = self._outages[entry.entry_id] = _Outage()
            self._schedule(entry.entry_id, outage, GRACE_PERIOD)

    def _schedule(self, entry_id: str, outage: _Outage, delay: timedelta) -> None:
        if outage.cancel_timer:
            outage.cancel_timer()

        @callback
        def fire(_now) -> None:
            outage.cancel_timer = None
            self._hass.async_create_background_task(
                self._async_search(entry_id), f"annika rainbird search {entry_id}"
            )

        outage.cancel_timer = async_call_later(self._hass, delay, fire)

    # ---------------------------------------------------------------- search

    async def _async_search(self, entry_id: str) -> None:
        async with self._search_lock:
            entry = self._hass.config_entries.async_get_entry(entry_id)
            outage = self._outages.get(entry_id)
            if entry is None or outage is None or not self._is_down(entry):
                self._outages.pop(entry_id, None)
                return

            old_host = entry.data.get(CONF_HOST)
            _LOGGER.info("Rain Bird %s still down; searching the network", entry.title)
            try:
                result = await self._async_find(entry)
            except Exception:
                _LOGGER.exception("Rain Bird search failed")
                result = _SearchResult()

            if result.host is not None:
                self._outages.pop(entry_id, None)
                if result.host == old_host:
                    _LOGGER.info("Rain Bird %s answered on its usual address", entry.title)
                    return
                _LOGGER.info(
                    "Rain Bird %s moved from %s to %s; integration updated",
                    entry.title,
                    old_host,
                    result.host,
                )
                await self._async_notify(
                    "Rain Bird reconectado",
                    f"El Rain Bird cambió de IP ({old_host} → {result.host}) "
                    "y se reconectó solo.",
                    {"ip": result.host, "old_ip": old_host},
                )
                return

            _LOGGER.warning(
                "Rain Bird %s not found after trying %s addresses of %s",
                entry.title,
                result.tried,
                ", ".join(result.networks) or "no network",
            )
            if not outage.notified_not_found:
                outage.notified_not_found = True
                await self._async_notify(
                    "Rain Bird no disponible",
                    "El Rain Bird está desconectado y no apareció en ninguna IP de "
                    "la red. Puede estar apagado o en otra red.",
                    {"old_ip": old_host},
                )
            delay = RETRY_DELAYS[min(outage.attempts, len(RETRY_DELAYS) - 1)]
            outage.attempts += 1
            self._schedule(entry_id, outage, delay)

    async def _async_find(self, entry: ConfigEntry) -> _SearchResult:
        password = entry.data.get(CONF_PASSWORD)
        old_host = entry.data.get(CONF_HOST)
        mac = _norm_mac(entry.data.get(CONF_MAC))
        networks = await self._async_networks()
        result = _SearchResult(networks=[str(net) for net in networks])
        if not password or not networks:
            return result

        hosts = [str(host) for net in networks for host in net.hosts()]
        # A quick look at who answers on 80/443 (which also fills the ARP
        # table) only decides the order. Nothing is skipped: a sleeping Wi-Fi
        # device can be slow to answer.
        web = await _web_hosts(hosts)
        arp = await self._hass.async_add_executor_job(_arp_table)

        def priority(ip: str) -> tuple:
            ip_mac = arp.get(ip, "")
            return (
                ip != old_host,
                not (mac and ip_mac == mac),
                not (mac and ip_mac[:8] == mac[:8]),
                ip not in web,
                ipaddress.IPv4Address(ip),
            )

        order = sorted(hosts, key=priority)
        found = asyncio.Event()

        async def attempt(ip: str) -> None:
            if found.is_set():
                return
            result.tried += 1
            if await self._async_try_host(entry, ip, password):
                result.host = result.host or ip
                found.set()

        # The likely ones alone first, so a controller that is still where it
        # was does not open sixteen flows.
        likely = [ip for ip in order if ip == old_host or (mac and arp.get(ip) == mac)]
        semaphore = asyncio.Semaphore(PARALLEL_ATTEMPTS)

        async def limited(ip: str) -> None:
            async with semaphore:
                await attempt(ip)

        # The rainbird config flow logs an error for every address that is not the
        # controller: hundreds of lines per search. Keep them out of the log while
        # searching.
        flow_logger = logging.getLogger(RAINBIRD_FLOW_LOGGER)
        previous_level = flow_logger.level
        flow_logger.setLevel(logging.CRITICAL)
        try:
            for ip in likely:
                await attempt(ip)
            if not found.is_set():
                await asyncio.gather(*(limited(ip) for ip in order if ip not in likely))
        finally:
            flow_logger.setLevel(previous_level)
        return result

    async def _async_try_host(self, entry: ConfigEntry, host: str, password: str) -> bool:
        """Start the Rain Bird config flow for a host; True if it is this entry's controller."""

        flow_manager = self._hass.config_entries.flow
        try:
            flow = await flow_manager.async_init(
                RAINBIRD_DOMAIN,
                context={"source": SOURCE_USER},
                data={CONF_HOST: host, CONF_PASSWORD: password},
            )
        except Exception as err:  # noqa: BLE001 - a misbehaving host must not stop the search
            _LOGGER.debug("Rain Bird flow for %s failed: %s", host, err)
            return False

        if flow["type"] == FlowResultType.FORM:
            flow_manager.async_abort(flow["flow_id"])
            return False
        if flow["type"] == FlowResultType.ABORT and flow.get("reason") == "already_configured":
            # The flow updated the entry that owns this controller's MAC. It may
            # be another Rain Bird of the unit: only this entry's host counts.
            current = self._hass.config_entries.async_get_entry(entry.entry_id)
            return current is not None and current.data.get(CONF_HOST) == host
        if flow["type"] == FlowResultType.CREATE_ENTRY:
            _LOGGER.warning("Rain Bird search found a new controller at %s and added it", host)
        return False

    async def _async_networks(self) -> list[ipaddress.IPv4Network]:
        networks: list[ipaddress.IPv4Network] = []
        for adapter in await network.async_get_adapters(self._hass):
            if not adapter["enabled"]:
                continue
            for info in adapter["ipv4"]:
                net = ipaddress.ip_network(
                    f"{info['address']}/{info['network_prefix']}", strict=False
                )
                if net.prefixlen < MAX_NETWORK_PREFIX:
                    net = ipaddress.ip_network(
                        f"{info['address']}/{MAX_NETWORK_PREFIX}", strict=False
                    )
                if not net.is_loopback and net not in networks:
                    networks.append(net)
        return networks

    async def _async_notify(self, title: str, message: str, data: dict) -> None:
        try:
            await self._client.async_send(
                {
                    "eventId": str(uuid.uuid4()),
                    "type": "system",
                    "title": title,
                    "message": message,
                    "data": data,
                }
            )
        except Exception:
            _LOGGER.exception("Unable to send the Rain Bird event to Annika")


async def _port_open(ip: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), PORT_TIMEOUT_SECONDS
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True


async def _web_hosts(hosts: list[str]) -> set[str]:
    semaphore = asyncio.Semaphore(128)

    async def check(ip: str) -> str | None:
        async with semaphore:
            if await _port_open(ip, 80) or await _port_open(ip, 443):
                return ip
        return None

    return {ip for ip in await asyncio.gather(*(check(ip) for ip in hosts)) if ip}


def _arp_table() -> dict[str, str]:
    """IP -> MAC from the kernel's ARP table."""

    table: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="ascii") as arp:
            next(arp)
            for line in arp:
                parts = line.split()
                if len(parts) >= 4 and parts[2] != "0x0":
                    table[parts[0]] = parts[3].lower()
    except (OSError, StopIteration):
        pass
    return table


def _norm_mac(mac: str | None) -> str:
    digits = "".join(c for c in (mac or "").lower() if c in "0123456789abcdef")
    return ":".join(digits[i : i + 2] for i in range(0, len(digits), 2))
