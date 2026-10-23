"""Tests for Annika's doorbells: who a ring is told to, depending on who is home."""

from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_DOORBELLS
from custom_components.annika.doorbells import (
    DATA_DOORBELLS,
    DEBOUNCE_SECONDS,
    DOORBELLS_SCHEMA,
    AnnikaDoorbells,
)

VISITOR = "binary_sensor.front_visitor"
GOLF = "person.golf"
DELFI = "person.delfina"


def config(**overrides):
    values = {
        "notify_view": "alarm",
        "presence": [GOLF, DELFI],
        "doorbells": [{"name": "Front door", "entity": "camera.front", "visitor": VISITOR}],
    }
    values.update(overrides)
    return DOORBELLS_SCHEMA(values)


@pytest.fixture
def services(hass):
    return SimpleNamespace(
        snapshot=async_mock_service(hass, "camera", "snapshot"),
        record=async_mock_service(hass, "camera", "record"),
    )


@pytest.fixture
def sent():
    with patch("custom_components.annika.doorbells.AnnikaEventClient") as client:
        client.return_value.async_send = AsyncMock()
        yield client.return_value.async_send


async def start(hass, **overrides) -> AnnikaDoorbells:
    doorbells = AnnikaDoorbells(hass, config(**overrides))
    hass.states.async_set(VISITOR, "off")
    hass.states.async_set(GOLF, "not_home")
    hass.states.async_set(DELFI, "not_home")
    await doorbells.async_start()
    return doorbells


async def ring(hass, doorbells=None):
    hass.states.async_set(VISITOR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(VISITOR, "off")
    await hass.async_block_till_done()
    if doorbells is not None:
        # Let the next ring through the debounce.
        for key in doorbells._last:
            doorbells._last[key] -= timedelta(seconds=DEBOUNCE_SECONDS + 1)


def test_schema_defaults():
    values = config()
    assert values["recording"] == {"home": False, "away": True, "before": 5, "after": 20, "keep_days": 14}
    assert values["directory"] == "/media/clips"
    assert values["talk"] == {"mute_speaker": True, "auto_off": True, "auto_off_seconds": 60}
    assert values["notifications"] == {}


def test_schema_rejects_non_person_presence():
    with pytest.raises(vol.Invalid):
        config(presence=["light.kitchen"])


async def test_default_notifications(hass, services, sent):
    doorbells = await start(hass)
    assert doorbells.notifications == {
        "devices": {"home": True, "away": True},
        "users": {"home": False, "away": True},
    }


async def test_away_tells_devices_and_users(hass, services, sent):
    doorbells = await start(hass)
    await ring(hass)
    sent.assert_awaited_once()
    event = sent.await_args.args[0]
    assert event["view"] == "alarm"
    assert event["navigate"] is True
    assert "actor" not in event
    assert event["message"] == "Front door"
    assert len(services.snapshot) == 1
    assert doorbells.last_ring is not None


async def test_home_tells_only_devices(hass, services, sent):
    await start(hass)
    hass.states.async_set(DELFI, "home")
    await ring(hass)
    event = sent.await_args.args[0]
    assert event["navigate"] is True
    assert event["actor"] == "devices"
    assert "imageUrl" not in event
    assert services.snapshot == []


async def test_users_only_does_not_navigate(hass, services, sent):
    doorbells = await start(hass)
    doorbells.set_notification("devices", away=False)
    await ring(hass)
    event = sent.await_args.args[0]
    assert "navigate" not in event
    assert "actor" not in event


async def test_nobody_selected_sends_nothing(hass, services, sent):
    doorbells = await start(hass)
    doorbells.set_notification("devices", away=False)
    doorbells.set_notification("users", away=False)
    await ring(hass)
    sent.assert_not_awaited()


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
async def test_unknown_presence_counts_as_away(hass, services, sent, state):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, state)
    hass.states.async_set(DELFI, state)
    assert doorbells.anyone_home() is False
    await ring(hass)
    assert "actor" not in sent.await_args.args[0]


async def test_missing_person_counts_as_away(hass, services, sent):
    doorbells = await start(hass, presence=["person.ghost"])
    assert doorbells.people() == [{"entity": "person.ghost", "name": "person.ghost", "home": False}]
    assert doorbells.anyone_home() is False


async def test_one_person_home_is_enough(hass, services, sent):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, "home")
    assert doorbells.anyone_home() is True


async def test_empty_group_is_always_away(hass, services, sent):
    doorbells = await start(hass, presence=[])
    assert doorbells.anyone_home() is False


async def test_debounce(hass, services, sent):
    await start(hass)
    await ring(hass)
    await ring(hass)
    assert sent.await_count == 1


async def test_rings_after_the_debounce_count(hass, services, sent):
    doorbells = await start(hass)
    await ring(hass, doorbells)
    await ring(hass)
    assert sent.await_count == 2


async def test_only_off_to_on_rings(hass, services, sent):
    await start(hass)
    hass.states.async_set(VISITOR, "unavailable")
    hass.states.async_set(VISITOR, "on")
    await hass.async_block_till_done()
    sent.assert_not_awaited()


async def test_no_notify_view_sends_nothing(hass, services, sent):
    values = config()
    values.pop("notify_view")
    doorbells = AnnikaDoorbells(hass, values)
    hass.states.async_set(VISITOR, "off")
    await doorbells.async_start()
    await ring(hass)
    sent.assert_not_awaited()


async def test_snapshot_failure_still_notifies(hass, sent):
    async def broken(call):
        raise RuntimeError("no picture")

    hass.services.async_register("camera", "snapshot", broken)
    await start(hass)
    await ring(hass)
    event = sent.await_args.args[0]
    assert "imageUrl" not in event
    sent.assert_awaited_once()


async def test_send_failure_does_not_raise(hass, services, sent):
    sent.side_effect = RuntimeError("down")
    await start(hass)
    await ring(hass)


async def test_test_notification(hass, services, sent):
    doorbells = await start(hass)
    await doorbells.async_test("devices")
    event = sent.await_args.args[0]
    assert event["actor"] == "devices"
    assert event["navigate"] is True
    assert "test" in event["title"].lower()
    with pytest.raises(ValueError):
        await doorbells.async_test("nobody")


async def test_settings_persist_and_notify_listeners(hass, services, sent):
    doorbells = await start(hass)
    calls = []
    unsubscribe = doorbells.subscribe(lambda: calls.append(1))
    doorbells.set_notification("users", home=True)
    doorbells.set_presence([GOLF, GOLF])
    doorbells.set_talk(auto_off_seconds=90, mute_speaker=False)
    assert doorbells.notifications["users"]["home"] is True
    assert doorbells.presence == [GOLF]
    assert doorbells.talk["auto_off_seconds"] == 90
    assert doorbells.talk["mute_speaker"] is False
    assert len(calls) == 3
    unsubscribe()
    doorbells.set_talk(auto_off=False)
    assert len(calls) == 3
    await doorbells.async_stop()

    again = await start(hass)
    assert again.notifications["users"]["home"] is True
    assert again.presence == [GOLF]
    assert again.talk["auto_off_seconds"] == 90


def test_set_validation():
    doorbells = AnnikaDoorbells.__new__(AnnikaDoorbells)
    with pytest.raises(ValueError):
        doorbells.set_notification("nobody", home=True)
    with pytest.raises(ValueError):
        doorbells.set_presence(["light.kitchen"])


async def test_presence_change_updates_the_card(hass, services, sent):
    doorbells = await start(hass)
    calls = []
    doorbells.subscribe(lambda: calls.append(1))
    hass.states.async_set(GOLF, "home")
    await hass.async_block_till_done()
    assert calls


async def test_attributes(hass, services, sent):
    doorbells = await start(hass)
    hass.states.async_set(GOLF, "home", {"friendly_name": "Golf"})
    config_attr = doorbells.attributes()["config"]
    assert config_attr["notification"] is True
    assert config_attr["presence"]["home"] == 1
    assert config_attr["presence"]["people"][0] == {"entity": GOLF, "name": "Golf", "home": True}
    assert config_attr["doorbells"][0]["entity"] == "camera.front"
    assert config_attr["talk"]["auto_off_seconds"] == 60
    assert dt_util.utcnow()


async def test_the_sensor_reports_the_config_and_the_services_edit_it(hass, services, sent):
    assert await async_setup_component(hass, "sensor", {})
    doorbells = AnnikaDoorbells(hass, config())
    hass.data[DATA_DOORBELLS] = doorbells
    hass.config.components.add(DOMAIN)
    hass.states.async_set(VISITOR, "off")
    hass.states.async_set(GOLF, "not_home")
    hass.states.async_set(DELFI, "home")
    await async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_DOORBELLS}, {})
    await hass.async_block_till_done()

    entity = "sensor.annika_doorbells"
    state = hass.states.get(entity)
    assert state is not None
    assert state.attributes["config"]["presence"]["home"] == 1

    call = lambda service, **data: hass.services.async_call(  # noqa: E731
        DOMAIN, service, {"entity_id": entity, **data}, blocking=True
    )
    await call("set_doorbell_notification", target="users", home=True)
    await call("set_doorbell_presence", people=[GOLF])
    await call("set_doorbell_talk", auto_off_seconds=120)
    config_attr = hass.states.get(entity).attributes["config"]
    assert config_attr["notifications"]["users"]["home"] is True
    assert [person["entity"] for person in config_attr["presence"]["people"]] == [GOLF]
    assert config_attr["presence"]["home"] == 0
    assert config_attr["talk"]["auto_off_seconds"] == 120

    await call("test_doorbell_notification", target="devices")
    assert sent.await_args.args[0]["actor"] == "devices"

    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await call("set_doorbell_presence", people=["light.kitchen"])
    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await call("set_doorbell_talk", auto_off_seconds=5)


# --- clips ------------------------------------------------------------------


def folders(tmp_path):
    return {"directory": str(tmp_path / "clips"), "snapshots": str(tmp_path / "snaps")}


def touch(folder, name, age_days=0):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    open(path, "w").close()
    if age_days:
        stamp = dt_util.utcnow().timestamp() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


async def test_a_ring_when_away_records_a_clip_with_the_same_picture(hass, tmp_path, services, sent):
    doorbells = await start(hass, directory=str(tmp_path / "clips"), snapshots=hass.config.path("www/snaps"))
    await ring(hass)

    assert len(services.snapshot) == 1 and len(services.record) == 1
    record = services.record[0].data
    assert record["entity_id"] == "camera.front"
    assert record["duration"] == 20 and record["lookback"] == 5
    assert record["filename"].startswith(str(tmp_path / "clips") + "/front_door_ring_")
    clip = doorbells.clips[0]
    assert clip["doorbell"] == "Front door" and clip["notified"] is True
    assert clip["video"].endswith(".mp4") and clip["image"].endswith(".jpg")
    assert clip["image"].startswith("front_door_ring_")
    # The notification used that picture.
    assert sent.await_args.args[0]["imageUrl"] == f"/local/snaps/{clip['image']}"


async def test_no_clip_when_somebody_is_home(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    hass.states.async_set(DELFI, "home")
    await ring(hass)
    assert services.record == [] and doorbells.clips == []


async def test_recording_can_be_turned_on_for_home_and_off_for_away(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    doorbells.set_recording(home=True, away=False)
    hass.states.async_set(DELFI, "home")
    await ring(hass, doorbells)
    assert len(doorbells.clips) == 1
    hass.states.async_set(DELFI, "not_home")
    await ring(hass)
    assert len(doorbells.clips) == 1


async def test_a_clip_is_kept_even_when_nobody_is_notified(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    doorbells.set_notification("devices", away=False)
    doorbells.set_notification("users", away=False)
    await ring(hass)
    sent.assert_not_awaited()
    assert doorbells.clips[0]["notified"] is False


async def test_it_records_without_the_past_when_the_stream_is_not_running(hass, tmp_path, services, sent):
    calls = []

    async def record(call):
        calls.append(dict(call.data))
        if "lookback" in call.data:
            raise RuntimeError("no stream")

    hass.services.async_register("camera", "record", record)
    doorbells = await start(hass, **folders(tmp_path))
    await ring(hass)
    assert ["lookback" in call for call in calls] == [True, False]
    assert len(doorbells.clips) == 1


async def test_a_failed_recording_leaves_no_clip_and_no_picture(hass, tmp_path, services, sent):
    async def record(call):
        raise RuntimeError("no stream")

    async def snapshot(call):
        touch(os.path.dirname(call.data["filename"]), os.path.basename(call.data["filename"]))

    hass.services.async_register("camera", "record", record)
    hass.services.async_register("camera", "snapshot", snapshot)
    doorbells = await start(hass, **folders(tmp_path))
    await ring(hass)
    assert doorbells.clips == []
    assert os.listdir(tmp_path / "snaps") == []
    sent.assert_awaited_once()


async def test_deleting_a_clip_removes_its_files(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    await ring(hass)
    clip = doorbells.clips[0]
    video = touch(tmp_path / "clips", clip["video"])
    image = touch(tmp_path / "snaps", clip["image"])
    await doorbells.async_delete_clip(clip["id"])
    assert doorbells.clips == [] and not os.path.exists(video) and not os.path.exists(image)
    with pytest.raises(ValueError):
        await doorbells.async_delete_clip(clip["id"])


async def test_old_clips_are_deleted_by_themselves(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    doorbells.set_recording(keep_days=3)
    await ring(hass, doorbells)
    await ring(hass)
    old, new = doorbells.clips[1], doorbells.clips[0]
    # Two rings in the same second would share a name; in life the debounce keeps them apart.
    old["video"], old["image"] = "front_door_ring_20260101_000000.mp4", "front_door_ring_20260101_000000.jpg"
    old["time"] = (dt_util.utcnow() - timedelta(days=4)).isoformat()
    old_video = touch(tmp_path / "clips", old["video"], 4)
    old_image = touch(tmp_path / "snaps", old["image"], 4)
    new_video = touch(tmp_path / "clips", new["video"])
    stray = touch(tmp_path / "clips", "front_door_ring_20200101_000000.mp4", 10)
    # Files of the cameras and of the visitor pictures are not ours to sweep here.
    other = touch(tmp_path / "clips", "front_person_20200101_000000.mp4", 10)

    await doorbells.async_cleanup()
    assert doorbells.clips == [new]
    assert not any(os.path.exists(path) for path in (old_video, old_image, stray))
    assert os.path.exists(new_video) and os.path.exists(other)


async def test_clips_are_kept_across_restarts_and_capped(hass, tmp_path, services, sent):
    doorbells = await start(hass, **folders(tmp_path))
    doorbells.set_recording(keep_days=7, home=True)
    await ring(hass)
    await doorbells.async_stop()

    again = await start(hass, **folders(tmp_path))
    assert [clip["id"] for clip in again.clips] == [doorbells.clips[0]["id"]]
    assert again.recording["keep_days"] == 7 and again.recording["home"] is True


async def test_the_card_reads_the_clips_and_where_to_play_them(hass, tmp_path, services, sent):
    doorbells = await start(hass, directory="/media/clips", snapshots="/media/snapshots")
    attributes = doorbells.attributes()
    assert attributes["media_base"] == "media-source://media_source/local/clips"
    assert attributes["image_base"] == "/media/local/snapshots"
    assert attributes["clips"] == []
    assert attributes["config"]["recording"] == {"home": False, "away": True, "before": 5, "after": 20, "keep_days": 14}


async def test_recording_services(hass, tmp_path, services, sent):
    assert await async_setup_component(hass, "sensor", {})
    doorbells = AnnikaDoorbells(hass, config(**folders(tmp_path)))
    hass.data[DATA_DOORBELLS] = doorbells
    hass.config.components.add(DOMAIN)
    hass.states.async_set(VISITOR, "off")
    await async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_DOORBELLS}, {})
    await hass.async_block_till_done()
    entity = "sensor.annika_doorbells"

    await hass.services.async_call(DOMAIN, "set_doorbell_recording", {"entity_id": entity, "home": True, "keep_days": 30}, blocking=True)
    assert hass.states.get(entity).attributes["config"]["recording"]["home"] is True
    assert hass.states.get(entity).attributes["config"]["recording"]["keep_days"] == 30

    await ring(hass)
    clip_id = hass.states.get(entity).attributes["clips"][0]["id"]
    await hass.services.async_call(DOMAIN, "delete_doorbell_clip", {"entity_id": entity, "clip_id": clip_id}, blocking=True)
    assert hass.states.get(entity).attributes["clips"] == []
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "delete_doorbell_clip", {"entity_id": entity, "clip_id": "nope"}, blocking=True)
    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await hass.services.async_call(DOMAIN, "set_doorbell_recording", {"entity_id": entity, "keep_days": 0}, blocking=True)
