"""What the customer is shown for Siri, and when the bridge is reset."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entityfilter import generate_filter
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.annika.homekit import (
    DEFAULT_DOMAINS,
    AnnikaHomeKit,
    async_setup_homekit,
    entity_ids_in,
)

PIN = "031-45-154"
URI = "X-HM://0023ISPZ6XXXX"


class FakeBridge:
    """The part of Home Assistant's HomeKit bridge that Annika reads."""

    def __init__(self, paired: bool = False) -> None:
        self.driver = SimpleNamespace(
            state=SimpleNamespace(paired=paired, pincode=PIN.encode()),
            accessory=SimpleNamespace(xhm_uri=lambda: URI),
        )
        self.unpaired = 0

    def async_unpair(self) -> None:
        self.unpaired += 1
        self.driver.state.paired = False


def add_bridge(hass: HomeAssistant, bridge: FakeBridge | None, name: str = "Annika") -> MockConfigEntry:
    entry = MockConfigEntry(domain="homekit", data={"name": name, "port": 21063})
    entry.add_to_hass(hass)
    if bridge is not None:
        entry.runtime_data = SimpleNamespace(homekit=bridge)
    return entry


@pytest.fixture
async def client(hass: HomeAssistant, hass_ws_client):
    await async_setup_homekit(hass, {})
    return await hass_ws_client(hass)


async def pairing(client) -> dict:
    await client.send_json({"id": 1, "type": "annika/homekit_pairing"})
    response = await client.receive_json()
    assert response["success"], response
    return response["result"]


async def test_a_bridge_that_waits_to_be_added_shows_its_code_and_qr_content(hass, client):
    add_bridge(hass, FakeBridge())
    assert await pairing(client) == {"state": "unpaired", "pin": PIN, "uri": URI}


async def test_a_paired_bridge_shows_no_code(hass, client):
    add_bridge(hass, FakeBridge(paired=True))
    assert await pairing(client) == {"state": "paired", "pin": None, "uri": None}


async def test_a_house_that_never_turned_siri_on_is_told_so(hass, client):
    assert await pairing(client) == {"state": "disabled", "pin": None, "uri": None}


async def test_a_bridge_that_has_not_started_is_unavailable(hass, client):
    bridge = FakeBridge()
    bridge.driver = None
    add_bridge(hass, bridge)
    assert (await pairing(client))["state"] == "unavailable"


async def test_an_entry_that_never_loaded_is_unavailable(hass, client):
    add_bridge(hass, None)
    assert (await pairing(client))["state"] == "unavailable"


async def test_only_the_bridge_named_annika_counts(hass, client):
    add_bridge(hass, FakeBridge(paired=True), name="Casa del lago")
    assert (await pairing(client))["state"] == "disabled"


async def test_unpairing_frees_the_bridge_and_returns_the_code_to_add_it_again(hass, client):
    bridge = FakeBridge(paired=True)
    add_bridge(hass, bridge)

    await client.send_json({"id": 1, "type": "annika/homekit_unpair"})
    response = await client.receive_json()

    assert response["success"]
    assert response["result"] == {"state": "unpaired", "pin": PIN, "uri": URI}
    assert bridge.unpaired == 1


async def test_unpairing_without_a_bridge_is_an_error(hass, client):
    await client.send_json({"id": 1, "type": "annika/homekit_unpair"})
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "not_found"


async def test_only_an_admin_can_ask(hass, hass_ws_client, hass_read_only_access_token):
    bridge = FakeBridge()
    add_bridge(hass, bridge)
    await async_setup_homekit(hass, {})
    client = await hass_ws_client(hass, hass_read_only_access_token)

    commands = (
        {"type": "annika/homekit_pairing"},
        {"type": "annika/homekit_unpair"},
        {"type": "annika/voice_entities"},
        {"type": "annika/homekit_configure", "expose": [], "hide": ["light.sala"]},
    )
    for message_id, command in enumerate(commands, start=1):
        await client.send_json({"id": message_id, **command})
        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "unauthorized"

    assert bridge.unpaired == 0
    assert await Store(hass, 1, "annika.homekit").async_load() is None


DOMAINS = list(DEFAULT_DOMAINS)


def filter_for(expose: list[str] | None = None, exclude: list[str] | None = None) -> dict[str, list[str]]:
    return {
        "include_domains": DOMAINS,
        "include_entities": expose or [],
        "exclude_entities": exclude or [],
    }


@pytest.fixture
def flow(hass: HomeAssistant):
    with patch.object(hass.config_entries.flow, "async_init", AsyncMock()) as async_init:
        yield async_init


@pytest.fixture
def free_ports():
    with patch("custom_components.annika.homekit.port_is_free", return_value=True):
        yield


@pytest.fixture(autouse=True)
def quick_start():
    with patch("custom_components.annika.homekit.BRIDGE_START_TIMEOUT", 0.05), patch(
        "custom_components.annika.homekit.BRIDGE_START_POLL", 0.01
    ):
        yield


def test_the_bridge_exposes_what_a_person_can_control_and_no_readings():
    domains = DEFAULT_DOMAINS
    for controllable in ("light", "switch", "cover", "fan", "climate", "lock"):
        assert controllable in domains
    for reading_or_shortcut in ("sensor", "binary_sensor", "button", "script", "scene", "camera"):
        assert reading_or_shortcut not in domains


def test_entity_ids_are_found_wherever_the_configuration_writes_them():
    found = entity_ids_in(
        {
            "gate": {"cover": "cover.porton", "relay": ["switch.rele", {"entity": "cover.garage"}]},
            "heating": {"zones": [{"thermostats": [{"entity": "climate.living"}]}]},
            "api_url": "https://api.test",
            "webhook_secret": "abc.def.ghi",
            "count": 3,
        }
    )
    assert found == {"cover.porton", "switch.rele", "cover.garage", "climate.living"}


async def test_turning_siri_on_creates_the_bridge_without_anyone_editing_a_file(hass, flow, free_ports):
    await AnnikaHomeKit(hass, {}).async_enable()

    flow.assert_awaited_once()
    args, kwargs = flow.await_args
    assert args == ("homekit",)
    assert kwargs["context"] == {"source": SOURCE_IMPORT}
    assert kwargs["data"] == {
        "name": "Annika",
        "port": 21063,
        "filter": filter_for(),
    }


async def test_turning_siri_on_answers_with_the_code_once_the_bridge_is_running(hass, flow, free_ports):
    async def create_the_bridge(*args, **kwargs):
        add_bridge(hass, FakeBridge())

    flow.side_effect = create_the_bridge

    assert await AnnikaHomeKit(hass, {}).async_enable() == {"state": "unpaired", "pin": PIN, "uri": URI}


async def test_turning_siri_on_does_not_wait_forever_for_a_bridge_that_never_starts(hass, flow, free_ports):
    assert (await AnnikaHomeKit(hass, {}).async_enable())["state"] == "disabled"


async def test_turning_siri_on_twice_does_not_create_a_second_bridge(hass, flow, free_ports):
    add_bridge(hass, FakeBridge(paired=True))

    assert (await AnnikaHomeKit(hass, {}).async_enable())["state"] == "paired"
    flow.assert_not_awaited()


async def test_the_owner_turns_siri_on_through_the_command(hass, client, flow, free_ports):
    async def create_the_bridge(*args, **kwargs):
        add_bridge(hass, FakeBridge())

    flow.side_effect = create_the_bridge

    await client.send_json({"id": 1, "type": "annika/homekit_enable"})
    response = await client.receive_json()

    assert response["success"]
    assert response["result"] == {"state": "unpaired", "pin": PIN, "uri": URI}


async def test_the_bridge_takes_a_port_nobody_uses(hass, flow):
    add_bridge(hass, FakeBridge(), name="Casa del lago")  # a bridge that already holds 21063

    with patch("custom_components.annika.homekit.port_is_free", side_effect=lambda port: port != 21064):
        await AnnikaHomeKit(hass, {}).async_enable()

    assert flow.await_args.kwargs["data"]["port"] == 21065


async def test_what_annika_manages_is_not_handed_to_siri(hass, flow, free_ports):
    registry = er.async_get(hass)
    own_cover = registry.async_get_or_create("cover", "annika", "gate_state", suggested_object_id="annika_gate")
    own_sensor = registry.async_get_or_create("sensor", "annika", "last_action")
    annika_config = {
        "gate": {"cover": "cover.porton"},
        "heating": {"zones": [{"thermostats": [{"entity": "climate.living"}]}]},
        "locks": [{"entity": "lock.puerta"}],
    }

    await AnnikaHomeKit(hass, annika_config).async_enable()

    withheld = flow.await_args.kwargs["data"]["filter"]["exclude_entities"]
    assert withheld == sorted(["cover.porton", "climate.living", own_cover.entity_id])
    assert own_sensor.entity_id not in withheld
    assert "lock.puerta" not in withheld, "locks are on the bridge even when Annika's locks feature names them"


async def test_a_house_without_the_bridge_is_left_alone_at_startup(hass, flow, free_ports):
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {}).async_sync()

    flow.assert_not_awaited()
    reload.assert_not_awaited()


async def test_a_bridge_that_is_already_right_is_left_alone(hass, flow, free_ports):
    entry = add_bridge(hass, None)
    hass.config_entries.async_update_entry(
        entry, options={"filter": filter_for()}
    )

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {}).async_sync()

    reload.assert_not_awaited()


async def test_a_bridge_that_is_not_set_up_yet_is_compared_by_the_filter_it_was_created_with(hass, flow, free_ports):
    entry = add_bridge(hass, None)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "filter": filter_for()},
    )

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {}).async_sync()

    reload.assert_not_awaited()


async def test_a_bridge_whose_filter_changed_is_updated_and_reloaded(hass, flow, free_ports):
    entry = add_bridge(hass, None)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {"gate": {"cover": "cover.porton"}}).async_sync()

    assert entry.options["filter"] == filter_for(exclude=["cover.porton"])
    reload.assert_awaited_once_with(entry.entry_id)


async def test_what_the_backend_took_away_is_not_handed_to_siri(hass, flow, free_ports):
    homekit = AnnikaHomeKit(hass, {})
    await homekit.async_configure([], ["light.sotano", "lock.puerta"])

    await homekit.async_enable()

    assert flow.await_args.kwargs["data"]["filter"] == filter_for(exclude=["light.sotano", "lock.puerta"])


async def test_what_the_backend_added_reaches_siri_even_when_annika_manages_it_or_it_is_not_a_default(
    hass, flow, free_ports
):
    registry = er.async_get(hass)
    own_cover = registry.async_get_or_create("cover", "annika", "gate_state", suggested_object_id="annika_gate")
    homekit = AnnikaHomeKit(hass, {"gate": {"cover": "cover.porton"}})
    await homekit.async_configure([own_cover.entity_id, "cover.porton", "scene.noche"], [])

    await homekit.async_enable()

    assert flow.await_args.kwargs["data"]["filter"] == filter_for(
        expose=sorted([own_cover.entity_id, "cover.porton", "scene.noche"])
    )


async def test_a_device_cannot_be_added_and_taken_away_at_once_and_taking_away_wins(hass):
    homekit = AnnikaHomeKit(hass, {})

    assert await homekit.async_configure(["light.sala"], ["light.sala"]) == {"expose": [], "hide": ["light.sala"]}


async def test_the_choice_survives_a_restart(hass):
    await AnnikaHomeKit(hass, {}).async_configure(["scene.noche"], ["light.sotano"])

    restarted = AnnikaHomeKit(hass, {})
    await restarted.async_load()

    assert restarted._entity_filter() == filter_for(expose=["scene.noche"], exclude=["light.sotano"])


async def test_what_the_house_stored_before_devices_could_be_added_still_applies(hass):
    await Store(hass, 1, "annika.homekit").async_save({"exclude": ["light.sotano"]})

    restarted = AnnikaHomeKit(hass, {})
    await restarted.async_load()

    assert restarted._entity_filter() == filter_for(exclude=["light.sotano"])


async def test_choosing_devices_updates_and_reloads_the_bridge_that_already_exists(hass):
    entry = add_bridge(hass, None)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        result = await AnnikaHomeKit(hass, {}).async_configure(["scene.noche"], ["light.sotano"])

    assert result == {"expose": ["scene.noche"], "hide": ["light.sotano"]}
    assert entry.options["filter"] == filter_for(expose=["scene.noche"], exclude=["light.sotano"])
    reload.assert_awaited_once_with(entry.entry_id)


async def test_choosing_devices_before_siri_is_on_only_remembers_them(hass):
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {}).async_configure([], ["light.sotano"])

    reload.assert_not_awaited()
    assert await Store(hass, 2, "annika.homekit").async_load() == {"expose": [], "hide": ["light.sotano"]}


async def test_the_backend_chooses_devices_through_the_command(hass, client):
    await client.send_json(
        {
            "id": 1,
            "type": "annika/homekit_configure",
            "expose": ["scene.noche", "scene.noche"],
            "hide": ["light.sotano"],
        }
    )
    response = await client.receive_json()

    assert response["success"]
    assert response["result"] == {"expose": ["scene.noche"], "hide": ["light.sotano"]}


async def test_a_malformed_choice_of_devices_is_refused(hass, client):
    choices = ({"expose": ["not an entity"], "hide": []}, {"expose": []}, {"hide": []})
    for message_id, choice in enumerate(choices, start=1):
        await client.send_json({"id": message_id, "type": "annika/homekit_configure", **choice})
        response = await client.receive_json()

        assert not response["success"]
    assert await Store(hass, 2, "annika.homekit").async_load() is None


async def test_every_device_a_voice_assistant_could_get_is_listed_with_what_it_gets_by_default(hass):
    registry = er.async_get(hass)
    own = registry.async_get_or_create("cover", "annika", "gate_state", suggested_object_id="annika_gate")
    own_sensor = registry.async_get_or_create("sensor", "annika", "last_action", suggested_object_id="last_action")
    config = registry.async_get_or_create(
        "switch", "demo", "child_lock", suggested_object_id="child_lock", entity_category=EntityCategory.CONFIG
    )
    states = {
        "light.sala": "Luz de la sala",
        "light.cocina": "cocina",
        "lock.puerta": "Puerta",
        "cover.porton": "Portón",
        "alarm_control_panel.casa": "Alarma",
        "automation.riego": "Riego de la mañana",
        "scene.noche": "Noche",
        "sensor.temperatura": "Temperatura",
        "weather.casa": "Clima",
        "update.hacs": "Actualización",
        own.entity_id: "Portón Annika",
        own_sensor.entity_id: "Última acción",
        config.entity_id: "Bloqueo infantil",
    }
    for entity_id, name in states.items():
        hass.states.async_set(entity_id, "on", {"friendly_name": name})
    homekit = AnnikaHomeKit(hass, {"gate": {"cover": "cover.porton"}})

    listed = await homekit.async_voice_entities()

    # What HomeKit cannot show (weather, updates) and what is only configuration is not offered.
    assert {entity["entity_id"]: (entity["default"], entity["managed"]) for entity in listed} == {
        "light.sala": (True, False),
        "light.cocina": (True, False),
        "lock.puerta": (True, False),
        "alarm_control_panel.casa": (True, False),
        "cover.porton": (False, True),
        own.entity_id: (False, True),
        "automation.riego": (False, False),
        "scene.noche": (False, False),
        "sensor.temperatura": (False, False),
        own_sensor.entity_id: (False, True),
    }
    assert [entity["name"] for entity in listed] == sorted(
        (entity["name"] for entity in listed), key=str.casefold
    ), "by name, without regard for case"
    assert {
        "entity_id": "light.sala",
        "name": "Luz de la sala",
        "default": True,
        "managed": False,
        "integration": None,
        "integration_name": None,
    } in listed


async def test_the_backend_asks_for_the_devices_through_the_command(hass, client):
    hass.states.async_set("light.sala", "on", {"friendly_name": "Luz de la sala"})

    await client.send_json({"id": 1, "type": "annika/voice_entities"})
    response = await client.receive_json()

    assert response["success"]
    assert {
        "entity_id": "light.sala",
        "name": "Luz de la sala",
        "default": True,
        "managed": False,
        "integration": None,
        "integration_name": None,
    } in response["result"]


def home_assistants_filter(entity_filter: dict[str, list[str]]):
    return generate_filter(
        entity_filter["include_domains"],
        entity_filter["include_entities"],
        [],
        entity_filter["exclude_entities"],
    )


async def test_home_assistant_reads_the_filter_the_way_the_choice_means_it(hass):
    registry = er.async_get(hass)
    own = registry.async_get_or_create("cover", "annika", "gate_state", suggested_object_id="annika_gate")
    homekit = AnnikaHomeKit(hass, {"gate": {"cover": "cover.porton"}, "locks": [{"entity": "lock.puerta"}]})
    await homekit.async_configure(["scene.noche", "cover.porton"], ["light.sotano"])

    allowed = home_assistants_filter(homekit._entity_filter())

    assert allowed("light.sala"), "a default device nobody chose anything for"
    assert allowed("light.nueva"), "a device installed later follows the default"
    assert allowed("lock.puerta"), "locks are on the bridge by default"
    assert not allowed("light.sotano"), "a default device that was taken away"
    assert allowed("scene.noche"), "a device outside the default that was added"
    assert allowed("cover.porton"), "a device Annika manages that was added"
    assert not allowed(own.entity_id), "a device Annika manages that nobody added"
    assert not allowed("scene.tarde"), "a device outside the default that nobody added"
    assert not allowed("sensor.temperatura")


async def test_a_forced_sync_reloads_a_bridge_whose_filter_is_the_same(hass):
    entry = add_bridge(hass, None)
    hass.config_entries.async_update_entry(entry, options={"filter": filter_for()})

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await AnnikaHomeKit(hass, {}).async_sync(force=True)

    reload.assert_awaited_once_with(entry.entry_id)


@pytest.fixture
def quick_reload():
    with patch("custom_components.annika.homekit.NEW_ENTITY_DELAY", 0.05):
        yield


async def new_entity(hass, domain: str, name: str) -> None:
    er.async_get(hass).async_get_or_create(domain, "demo", name)
    await hass.async_block_till_done()


async def test_a_new_device_reloads_the_bridge_once_even_when_several_arrive(hass, quick_reload):
    add_bridge(hass, None)
    homekit = AnnikaHomeKit(hass, {})
    homekit.async_watch_new_entities()

    with patch.object(homekit, "async_sync", AsyncMock()) as sync:
        await new_entity(hass, "light", "one")
        await new_entity(hass, "light", "two")
        await asyncio.sleep(0.15)
        await hass.async_block_till_done()

    sync.assert_awaited_once_with(force=True)


async def test_a_device_siri_does_not_get_by_default_does_not_reload_the_bridge(hass, quick_reload):
    add_bridge(hass, None)
    homekit = AnnikaHomeKit(hass, {})
    homekit.async_watch_new_entities()

    with patch.object(homekit, "async_sync", AsyncMock()) as sync:
        await new_entity(hass, "sensor", "temperature")
        await asyncio.sleep(0.15)

    sync.assert_not_awaited()


async def test_a_house_without_the_bridge_ignores_new_devices(hass, quick_reload):
    homekit = AnnikaHomeKit(hass, {})
    homekit.async_watch_new_entities()

    with patch.object(homekit, "async_sync", AsyncMock()) as sync:
        await new_entity(hass, "light", "one")
        await asyncio.sleep(0.15)

    sync.assert_not_awaited()


async def test_each_device_says_which_integration_it_comes_from(hass):
    registry = er.async_get(hass)
    lamp = registry.async_get_or_create("light", "demo", "lamp", suggested_object_id="lamp")
    plain = registry.async_get_or_create("switch", "unknown_vendor", "plug", suggested_object_id="plug")
    for entity_id in (lamp.entity_id, plain.entity_id, "light.sin_registro"):
        hass.states.async_set(entity_id, "on", {"friendly_name": entity_id})

    listed = {
        entity["entity_id"]: (entity["integration"], entity["integration_name"])
        for entity in await AnnikaHomeKit(hass, {}).async_voice_entities()
    }

    assert listed[lamp.entity_id] == ("demo", "Demo"), "the name people know it by"
    assert listed[plain.entity_id] == ("unknown_vendor", "unknown_vendor"), "an integration Home Assistant cannot name"
    assert listed["light.sin_registro"] == (None, None), "a device without a registry entry has none"
