"""The unit health report groups unavailable entities by device, so a dead camera is one finding, not thirty."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.annika.heartbeat import HeartbeatReporter

UNAVAILABLE = "unavailable"


def add_device(
    hass: HomeAssistant,
    name: str,
    states: dict[str, str],
    name_by_user: str | None = None,
    platform: str = "test",
) -> str:
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", name)}, name=name
    )
    if name_by_user:
        dr.async_get(hass).async_update_device(device.id, name_by_user=name_by_user)
    for entity_id, state in states.items():
        domain, object_id = entity_id.split(".", 1)
        er.async_get(hass).async_get_or_create(
            domain,
            platform,
            f"{name}-{entity_id}",
            suggested_object_id=object_id,
            device_id=device.id,
            config_entry=entry,
        )
        hass.states.async_set(entity_id, state)
    return device.id


def devices(hass: HomeAssistant) -> list[dict]:
    return HeartbeatReporter(hass).build()["unavailableDevices"]


async def test_a_device_with_every_monitored_entity_unavailable_is_one_finding(hass, freezer):
    device_id = add_device(
        hass,
        "RP-PCB8M 9",
        {
            "binary_sensor.rp_pcb8m_motion_9": UNAVAILABLE,
            "switch.rp_pcb8m_record_9": UNAVAILABLE,
            "camera.rp_pcb8m_fluent_9": UNAVAILABLE,
        },
    )
    started = hass.states.get("camera.rp_pcb8m_fluent_9").last_changed
    freezer.tick(timedelta(minutes=6))

    report = HeartbeatReporter(hass).build()

    assert report["unavailableDevices"] == [
        {
            "deviceId": device_id,
            "name": "RP-PCB8M 9",
            "since": started.isoformat().replace("+00:00", "Z"),
            "unavailableEntities": 3,
            "totalEntities": 3,
        }
    ]
    assert len(report["unavailable"]) == 3


async def test_the_name_the_user_gave_the_device_wins(hass, freezer):
    add_device(hass, "RP-PCB8M 9", {"camera.rp_pcb8m_fluent_9": UNAVAILABLE}, name_by_user="Cámara patio")
    freezer.tick(timedelta(minutes=6))

    assert devices(hass)[0]["name"] == "Cámara patio"


async def test_entities_outside_the_monitored_domains_do_not_count(hass, freezer):
    """A Shelly keeps its `button` at `unknown` when it drops: that must not hide the device being down."""

    add_device(
        hass,
        "Cancha 1",
        {
            "binary_sensor.cancha_1_input": UNAVAILABLE,
            "switch.cancha_1": UNAVAILABLE,
            "button.cancha_1_reboot": "unknown",
            "update.cancha_1_firmware": UNAVAILABLE,
        },
    )
    freezer.tick(timedelta(minutes=6))

    [device] = devices(hass)

    assert device["name"] == "Cancha 1"
    assert (device["unavailableEntities"], device["totalEntities"]) == (2, 2)


async def test_a_single_unavailable_entity_does_not_make_the_device_unavailable(hass, freezer):
    add_device(
        hass,
        "Cancha 2",
        {"binary_sensor.cancha_2_input": UNAVAILABLE, "switch.cancha_2": "off"},
    )
    freezer.tick(timedelta(minutes=6))

    assert devices(hass) == []
    assert [entity["entityId"] for entity in HeartbeatReporter(hass).build()["unavailable"]] == [
        "binary_sensor.cancha_2_input"
    ]


async def test_a_device_is_reported_only_after_every_entity_has_been_unavailable_for_five_minutes(hass, freezer):
    add_device(hass, "Cancha 3", {"switch.cancha_3": UNAVAILABLE, "binary_sensor.cancha_3_input": "off"})
    freezer.tick(timedelta(minutes=6))
    hass.states.async_set("binary_sensor.cancha_3_input", UNAVAILABLE)
    freezer.tick(timedelta(minutes=4))

    assert devices(hass) == []

    freezer.tick(timedelta(minutes=2))

    assert [device["unavailableEntities"] for device in devices(hass)] == [2]


async def test_since_is_when_the_first_entity_of_the_device_went_down(hass, freezer):
    add_device(hass, "Cancha 1", {"switch.cancha_1": UNAVAILABLE, "binary_sensor.cancha_1_input": "off"})
    first = hass.states.get("switch.cancha_1").last_changed
    freezer.tick(timedelta(minutes=2))
    hass.states.async_set("binary_sensor.cancha_1_input", UNAVAILABLE)
    freezer.tick(timedelta(minutes=6))

    assert devices(hass)[0]["since"] == first.isoformat().replace("+00:00", "Z")


async def test_an_entity_without_a_device_stands_for_itself(hass, freezer):
    hass.states.async_set("light.living", UNAVAILABLE, {"friendly_name": "Luz del living"})
    freezer.tick(timedelta(minutes=6))

    assert [(device["deviceId"], device["name"]) for device in devices(hass)] == [
        ("light.living", "Luz del living")
    ]


async def test_devices_that_only_have_entities_outside_the_monitored_domains_are_ignored(hass, freezer):
    add_device(hass, "Sensor de temperatura", {"sensor.temperatura": UNAVAILABLE})
    freezer.tick(timedelta(minutes=6))

    assert devices(hass) == []


async def test_each_failing_device_is_its_own_finding(hass, freezer):
    add_device(hass, "RP-PCB8M 9", {"camera.rp_pcb8m_fluent_9": UNAVAILABLE})
    add_device(hass, "RP-PCB8M 10", {"camera.rp_pcb8m_fluent_10": UNAVAILABLE})
    add_device(hass, "Cancha 1", {"switch.cancha_1": "on"})
    freezer.tick(timedelta(minutes=6))

    assert sorted(device["name"] for device in devices(hass)) == ["RP-PCB8M 10", "RP-PCB8M 9"]


async def test_annika_entities_that_mirror_rain_bird_zones_are_not_a_device(hass, freezer):
    entry = MockConfigEntry(domain="annika")
    entry.add_to_hass(hass)
    for zone in (1, 2):
        entity_id = f"switch.irrigation_manual_zona_{zone}"
        er.async_get(hass).async_get_or_create(
            "switch", "annika", f"manual-{zone}", suggested_object_id=entity_id.split(".", 1)[1], config_entry=entry
        )
        hass.states.async_set(entity_id, UNAVAILABLE)
    freezer.tick(timedelta(minutes=6))

    report = HeartbeatReporter(hass).build()

    assert report["unavailableDevices"] == []
    assert len(report["unavailable"]) == 2


async def test_rain_bird_is_left_to_its_own_reconnection(hass, freezer):
    add_device(
        hass,
        "Rain Bird",
        {"switch.rain_bird_zone_1": UNAVAILABLE, "binary_sensor.rain_bird_rain_sensor": UNAVAILABLE},
        platform="rainbird",
    )
    freezer.tick(timedelta(minutes=6))

    report = HeartbeatReporter(hass).build()

    assert report["unavailableDevices"] == []
    assert len(report["unavailable"]) == 2
