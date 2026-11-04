"""What Alexa is given by a house, and when the endpoint that relays its orders exists."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.loader import IntegrationNotFound
from homeassistant.setup import async_setup_component

from custom_components.annika import async_setup_alexa_endpoint
from custom_components.annika.alexa import DATA_ALEXA, AnnikaAlexa, async_setup_alexa
from custom_components.annika.homekit import DATA_HOMEKIT, AnnikaHomeKit, async_setup_homekit

ENDPOINT = "/api/alexa/smart_home"

DISCOVERY = {
    "directive": {
        "header": {
            "namespace": "Alexa.Discovery",
            "name": "Discover",
            "payloadVersion": "3",
            "messageId": "discovery-1",
        },
        "payload": {"scope": {"type": "BearerToken", "token": "annika-token"}},
    }
}

ANNIKA_CONFIG = {"gate": {"cover": "cover.porton"}}


@pytest.fixture(autouse=True)
async def http(hass: HomeAssistant):
    assert await async_setup_component(hass, "http", {})


@pytest.fixture
async def homekit(hass: HomeAssistant) -> AnnikaHomeKit:
    return await async_setup_homekit(hass, ANNIKA_CONFIG)


@pytest.fixture
async def alexa(hass: HomeAssistant, homekit: AnnikaHomeKit) -> AnnikaAlexa:
    return await async_setup_alexa(hass, homekit)


@pytest.fixture
async def client(hass: HomeAssistant, alexa, hass_ws_client):
    return await hass_ws_client(hass)


@pytest.fixture
def quick_refresh():
    with patch("custom_components.annika.alexa.NEW_ENTITY_DELAY", 0.05):
        yield


async def command(client, type: str, **payload) -> dict:
    message_id = getattr(client, "last_message_id", 0) + 1
    client.last_message_id = message_id
    await client.send_json({"id": message_id, "type": type, **payload})
    return await client.receive_json()


def add_light(hass: HomeAssistant, entity_id: str, name: str | None = None) -> None:
    hass.states.async_set(
        entity_id,
        "on",
        {"friendly_name": name or entity_id, "supported_color_modes": ["onoff"]},
    )


async def discovered(hass_client) -> set[str]:
    response = await hass_client.post(ENDPOINT, json=DISCOVERY)
    assert response.status == 200
    body = await response.json()
    assert body["event"]["header"]["name"] == "Discover.Response"
    return {endpoint["endpointId"].replace("#", ".") for endpoint in body["event"]["payload"]["endpoints"]}


async def test_a_house_that_never_turned_alexa_on_is_told_so_and_has_no_endpoint(hass, client, hass_client):
    assert (await command(client, "annika/alexa_status"))["result"] == {"state": "disabled"}

    response = await (await hass_client()).post(ENDPOINT, json=DISCOVERY)

    assert response.status == 404


async def test_turning_alexa_on_opens_the_endpoint_without_anyone_editing_a_file(hass, client, hass_client):
    add_light(hass, "light.sala")

    response = await command(client, "annika/alexa_enable")

    assert response["success"]
    assert response["result"] == {"state": "enabled"}
    assert (await command(client, "annika/alexa_status"))["result"] == {"state": "enabled"}
    assert "light.sala" in await discovered(await hass_client())


async def test_turning_alexa_on_twice_opens_one_endpoint(hass, client):
    await command(client, "annika/alexa_enable")
    await command(client, "annika/alexa_enable")

    endpoints = [resource for resource in hass.http.app.router.resources() if resource.canonical == ENDPOINT]
    assert len(endpoints) == 1


async def test_the_endpoint_needs_the_token_of_the_house(hass, client, aiohttp_client):
    await command(client, "annika/alexa_enable")

    anonymous = await aiohttp_client(hass.http.app)

    assert (await anonymous.post(ENDPOINT, json=DISCOVERY)).status == 401


async def test_alexa_gets_what_siri_gets_and_nothing_else(hass, client, hass_client):
    registry = er.async_get(hass)
    own = registry.async_get_or_create("light", "annika", "pool_lights", suggested_object_id="annika_pool")
    for entity_id in ("light.sala", "light.sotano", "light.nueva", own.entity_id):
        add_light(hass, entity_id)
    hass.states.async_set("cover.porton", "closed", {"friendly_name": "Portón", "supported_features": 3})
    hass.states.async_set("scene.noche", "scening", {"friendly_name": "Noche"})
    hass.states.async_set(
        "sensor.temperatura",
        "21",
        {"friendly_name": "Temperatura", "unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await command(client, "annika/homekit_configure", expose=[], hide=["light.sotano"])

    await command(client, "annika/alexa_enable")

    found = await discovered(await hass_client())
    assert {"light.sala", "light.nueva"} <= found, "a default device, and one installed later"
    assert "light.sotano" not in found, "a device the backend took away"
    assert own.entity_id not in found, "a device Annika manages"
    assert "cover.porton" not in found, "a device the configuration names"
    assert "scene.noche" not in found, "a device outside the default that nobody added"
    assert "sensor.temperatura" not in found, "a reading"


async def test_a_configuration_or_diagnostic_entity_never_reaches_alexa(hass, client, hass_client):
    registry = er.async_get(hass)
    for platform, entity_id, category in (
        ("reolink", "switch.camara_record", er.EntityCategory.CONFIG),
        ("reolink", "switch.camara_status_led", er.EntityCategory.DIAGNOSTIC),
        ("reolink", "switch.camara_siren", None),
    ):
        registry.async_get_or_create(
            "switch",
            platform,
            entity_id.split(".", 1)[1],
            suggested_object_id=entity_id.split(".", 1)[1],
            entity_category=category,
        )
        hass.states.async_set(entity_id, "on", {"friendly_name": entity_id})
    await command(client, "annika/alexa_enable")

    found = await discovered(await hass_client())

    assert "switch.camara_siren" in found, "a switch of the house"
    assert "switch.camara_record" not in found, "a setting of the device"
    assert "switch.camara_status_led" not in found, "a diagnostic of the device"


async def test_a_new_choice_changes_what_alexa_is_given_without_restarting_anything(hass, client, hass_client):
    add_light(hass, "light.sala")
    add_light(hass, "light.sotano")
    hass.states.async_set("scene.noche", "scening", {"friendly_name": "Noche"})
    await command(client, "annika/alexa_enable")
    alexa_client = await hass_client()
    before = await discovered(alexa_client)

    response = await command(client, "annika/homekit_configure", expose=["scene.noche"], hide=["light.sotano"])

    assert response["success"]
    after = await discovered(alexa_client)
    assert {"light.sala", "light.sotano"} <= before and "scene.noche" not in before
    assert "light.sotano" not in after, "taken away"
    assert "scene.noche" in after, "added"
    assert "light.sala" in after, "untouched"


async def test_a_choice_made_before_alexa_was_turned_on_applies_from_the_first_answer(hass, client, hass_client):
    add_light(hass, "light.sala")
    add_light(hass, "light.sotano")
    await command(client, "annika/homekit_configure", expose=[], hide=["light.sotano"])

    await command(client, "annika/alexa_enable")

    assert await discovered(await hass_client()) == {"light.sala"}


async def test_a_new_device_of_annika_is_left_out_once_the_registry_has_it(hass, client, hass_client, quick_refresh):
    await command(client, "annika/alexa_enable")
    alexa_client = await hass_client()

    own = er.async_get(hass).async_get_or_create("light", "annika", "new_lights", suggested_object_id="annika_nueva")
    add_light(hass, own.entity_id)
    await asyncio.sleep(0.15)
    await hass.async_block_till_done()

    assert own.entity_id not in await discovered(alexa_client)


async def test_several_new_devices_refresh_the_filter_once(hass, alexa, quick_refresh):
    with patch.object(alexa, "refresh") as refresh:
        alexa._config = object()
        for name in ("one", "two"):
            er.async_get(hass).async_get_or_create("light", "demo", name)
            await hass.async_block_till_done()
        await asyncio.sleep(0.15)

    refresh.assert_called_once_with()


async def test_a_device_alexa_does_not_get_by_default_does_not_refresh_the_filter(hass, alexa, quick_refresh):
    with patch.object(alexa, "refresh") as refresh:
        alexa._config = object()
        er.async_get(hass).async_get_or_create("sensor", "demo", "temperature")
        await hass.async_block_till_done()
        await asyncio.sleep(0.15)

    refresh.assert_not_called()


async def test_a_house_without_alexa_ignores_new_devices(hass, alexa, quick_refresh):
    with patch.object(alexa, "refresh") as refresh:
        er.async_get(hass).async_get_or_create("light", "demo", "one")
        await hass.async_block_till_done()
        await asyncio.sleep(0.15)

    refresh.assert_not_called()


async def test_the_house_remembers_that_alexa_is_on(hass, client):
    await command(client, "annika/alexa_enable")

    assert await Store(hass, 1, "annika.alexa").async_load() == {"enabled": True, "room_names": False}

    restarted = AnnikaAlexa(hass, AnnikaHomeKit(hass, {}))
    await restarted.async_load()
    assert restarted.status() == {"state": "enabled"}


async def test_a_house_that_turned_alexa_on_opens_the_endpoint_when_home_assistant_has_started(
    hass, homekit, hass_client
):
    await Store(hass, 1, "annika.alexa").async_save({"enabled": True})
    add_light(hass, "light.sala")
    restarted = await async_setup_alexa(hass, homekit)

    assert (await (await hass_client()).post(ENDPOINT, json=DISCOVERY)).status == 404, "not before it has started"

    await restarted.async_sync()

    assert "light.sala" in await discovered(await hass_client())


async def test_a_house_that_never_turned_alexa_on_opens_nothing_at_start(hass, alexa, hass_client):
    await alexa.async_sync()

    assert (await (await hass_client()).post(ENDPOINT, json=DISCOVERY)).status == 404


async def test_a_house_where_alexa_cannot_open_says_so_and_does_not_remember_it(hass, client):
    with patch("custom_components.annika.alexa.async_get_integration", side_effect=IntegrationNotFound("alexa")):
        response = await command(client, "annika/alexa_enable")

    assert not response["success"]
    assert (await command(client, "annika/alexa_status"))["result"] == {"state": "disabled"}
    assert await Store(hass, 1, "annika.alexa").async_load() is None


async def test_only_an_admin_can_ask(hass, alexa, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(hass, hass_read_only_access_token)

    for message_id, type in enumerate(("annika/alexa_status", "annika/alexa_enable"), start=1):
        await client.send_json({"id": message_id, "type": type})
        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "unauthorized"

    assert alexa.status() == {"state": "disabled"}
    assert await Store(hass, 1, "annika.alexa").async_load() is None


async def test_annika_keeps_running_when_alexa_cannot_register_its_commands(hass, homekit):
    hass.data[DATA_HOMEKIT] = homekit

    with patch("custom_components.annika.async_setup_alexa", AsyncMock(side_effect=RuntimeError("boom"))):
        await async_setup_alexa_endpoint(hass)

    assert DATA_ALEXA not in hass.data


async def test_annika_keeps_running_when_the_endpoint_cannot_be_updated(hass, homekit):
    hass.data[DATA_HOMEKIT] = homekit

    with patch.object(AnnikaAlexa, "async_sync", AsyncMock(side_effect=RuntimeError("boom"))) as sync:
        await async_setup_alexa_endpoint(hass)

    sync.assert_awaited_once()


async def friendly_names(hass_client) -> dict[str, str]:
    response = await hass_client.post(ENDPOINT, json=DISCOVERY)
    body = await response.json()
    return {
        endpoint["endpointId"].replace("#", "."): endpoint["friendlyName"]
        for endpoint in body["event"]["payload"]["endpoints"]
    }


def put_in_room(hass: HomeAssistant, entity_id: str, area_name: str, name: str = "Lámpara") -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create("light", "hue", entity_id, suggested_object_id=entity_id.split(".")[1])
    registry.async_update_entity(entity_id, area_id=ar.async_get(hass).async_get_or_create(area_name).id)
    add_light(hass, entity_id, name)


async def test_the_room_goes_in_front_of_the_name_alexa_hears_when_the_owner_chose_it(hass, client, hass_client):
    put_in_room(hass, "light.lampara", "Dormitorio principal")
    add_light(hass, "light.escritorio", "Escritorio")

    await command(client, "annika/alexa_enable", room_names=True)

    assert await friendly_names(await hass_client()) == {
        "light.lampara": "Dormitorio principal Lámpara",
        "light.escritorio": "Escritorio",
    }


async def test_the_names_stay_as_they_are_when_the_owner_did_not_choose_the_room(hass, client, hass_client):
    put_in_room(hass, "light.lampara", "Dormitorio principal")

    await command(client, "annika/alexa_enable", room_names=False)

    assert await friendly_names(await hass_client()) == {"light.lampara": "Lámpara"}


async def test_a_house_that_never_chose_keeps_the_names_it_has(hass, client, hass_client):
    put_in_room(hass, "light.lampara", "Dormitorio principal")

    await command(client, "annika/alexa_enable")

    assert await friendly_names(await hass_client()) == {"light.lampara": "Lámpara"}


async def test_a_name_that_already_says_its_room_is_not_repeated_for_alexa(hass, client, hass_client):
    put_in_room(hass, "light.lampara", "Dormitorio", name="Lámpara dormitorio")

    await command(client, "annika/alexa_enable", room_names=True)

    assert await friendly_names(await hass_client()) == {"light.lampara": "Lámpara dormitorio"}


async def test_the_choice_of_room_names_changes_what_alexa_hears_without_restarting_anything(
    hass, client, hass_client
):
    put_in_room(hass, "light.lampara", "Dormitorio")
    await command(client, "annika/alexa_enable", room_names=False)
    assert await friendly_names(await hass_client()) == {"light.lampara": "Lámpara"}

    await command(client, "annika/alexa_enable", room_names=True)

    assert await friendly_names(await hass_client()) == {"light.lampara": "Dormitorio Lámpara"}


async def test_the_house_remembers_the_choice_of_room_names(hass, client):
    await command(client, "annika/alexa_enable", room_names=True)

    assert await Store(hass, 1, "annika.alexa").async_load() == {"enabled": True, "room_names": True}


async def test_a_house_that_chose_room_names_hears_them_again_after_a_restart(hass, homekit, hass_client):
    await Store(hass, 1, "annika.alexa").async_save({"enabled": True, "room_names": True})
    put_in_room(hass, "light.lampara", "Dormitorio")
    restarted = await async_setup_alexa(hass, homekit)

    await restarted.async_sync()

    assert await friendly_names(await hass_client()) == {"light.lampara": "Dormitorio Lámpara"}


async def test_a_house_where_alexa_cannot_open_does_not_remember_the_choice_of_room_names(hass, client):
    with patch("custom_components.annika.alexa.async_get_integration", side_effect=IntegrationNotFound("alexa")):
        response = await command(client, "annika/alexa_enable", room_names=True)

    assert not response["success"]
    assert await Store(hass, 1, "annika.alexa").async_load() is None


async def test_a_malformed_choice_of_room_names_is_refused_for_alexa(hass, client):
    response = await command(client, "annika/alexa_enable", room_names="maybe")

    assert not response["success"]
    assert await Store(hass, 1, "annika.alexa").async_load() is None
