"""Tests for Annika's cameras: what a detection records, notifies, and when it counts."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.annika.cameras import (
    CAMERAS_SCHEMA,
    DATA_CAMERAS,
    AnnikaCameras,
    in_range,
)
from custom_components.annika.const import DISCOVERY_KIND, DOMAIN, KIND_CAMERAS

PERSON = "binary_sensor.front_person"
VEHICLE = "binary_sensor.front_vehicle"
MOTION = "binary_sensor.back_motion"


def config(hass, tmp_path, **overrides):
    values = {
        "notify_view": "alarm",
        "directory": str(tmp_path / "clips"),
        "snapshots": hass.config.path("www/snaps"),
        "recording": {"before": 5, "after": 10, "cooldown": 120, "keep_days": 30},
        "when": {"always": True},
        "cameras": [
            {
                "name": "Front",
                "entity": "camera.front",
                "person": PERSON,
                "vehicle": VEHICLE,
                "rules": {"person": "record_notify", "vehicle": "record"},
            },
            {"name": "Back", "entity": "camera.back", "motion": MOTION, "rules": {"motion": "record"}},
        ],
    }
    values.update(overrides)
    return CAMERAS_SCHEMA(values)


@pytest.fixture
def services(hass):
    return SimpleNamespace(
        snapshot=async_mock_service(hass, "camera", "snapshot"),
        record=async_mock_service(hass, "camera", "record"),
    )


@pytest.fixture
def sent():
    with patch("custom_components.annika.cameras.AnnikaEventClient") as client:
        client.return_value.async_send = AsyncMock()
        yield client.return_value.async_send


async def start(hass, tmp_path, **overrides) -> AnnikaCameras:
    cameras = AnnikaCameras(hass, config(hass, tmp_path, **overrides))
    for sensor in (PERSON, VEHICLE, MOTION):
        hass.states.async_set(sensor, "off")
    await cameras.async_start()
    return cameras


async def detect(hass, sensor):
    hass.states.async_set(sensor, "on")
    await hass.async_block_till_done()
    hass.states.async_set(sensor, "off")
    await hass.async_block_till_done()


def panel(hass, state, mode):
    hass.data[f"{DOMAIN}_alarm_panel"] = SimpleNamespace(state=state, mode=mode)


async def test_a_recorded_detection_makes_a_clip_with_a_picture_and_no_notification(
    hass, tmp_path, services, sent
):
    cameras = await start(hass, tmp_path)
    await detect(hass, VEHICLE)

    assert len(services.snapshot) == 1 and len(services.record) == 1
    record = services.record[0].data
    assert record["entity_id"] == "camera.front"
    assert record["duration"] == 10 and record["lookback"] == 5
    clip = cameras.clips[0]
    assert clip["type"] == "vehicle" and clip["camera"] == "Front" and clip["notified"] is False
    assert clip["image"] and clip["image"].endswith(".jpg") and clip["video"].endswith(".mp4")
    assert services.snapshot[0].data["filename"].endswith(clip["image"])
    sent.assert_not_called()


async def test_record_and_notify_sends_the_snapshot_with_the_notification(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)

    sent.assert_awaited_once()
    event = sent.await_args.args[0]
    assert event["view"] == "alarm" and event["title"] == "Front: person detected"
    assert event["image_url"] == f"/local/snaps/{cameras.clips[0]['image']}"
    assert cameras.clips[0]["notified"] is True


async def test_off_does_nothing(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    cameras.set_rule("front", "person", "off")
    await detect(hass, PERSON)

    assert not services.record and not services.snapshot and not cameras.clips
    sent.assert_not_called()


async def test_a_detection_nobody_asked_for_is_ignored(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    # The back camera's motion rule is "record"; its person is not even a sensor.
    await detect(hass, MOTION)
    assert [clip["camera"] for clip in cameras.clips] == ["Back"]


async def test_snapshots_under_media_are_served_by_the_media_source(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, snapshots="/media/snapshots")
    assert cameras.image_base == "/media/local/snapshots"
    await detect(hass, PERSON)
    assert sent.await_args.args[0]["image_url"] == f"/media/local/snapshots/{cameras.clips[0]['image']}"
    assert services.snapshot[0].data["filename"] == f"/media/snapshots/{cameras.clips[0]['image']}"


async def test_snapshots_outside_www_and_media_have_no_url(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, snapshots=str(tmp_path / "private"))
    assert cameras.image_base is None
    await detect(hass, PERSON)
    assert "image_url" not in sent.await_args.args[0]


async def test_no_notification_without_a_view(hass, tmp_path, services, sent):
    values = config(hass, tmp_path)
    del values["notify_view"]
    cameras = AnnikaCameras(hass, values)
    for sensor in (PERSON, VEHICLE, MOTION):
        hass.states.async_set(sensor, "off")
    await cameras.async_start()
    await detect(hass, PERSON)

    assert len(cameras.clips) == 1
    sent.assert_not_called()


async def test_a_failed_notification_keeps_the_clip(hass, tmp_path, services, sent):
    sent.side_effect = RuntimeError("offline")
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)
    assert len(cameras.clips) == 1


# --- when -------------------------------------------------------------------


async def test_armed_only_ignores_detections_while_disarmed(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, when={"armed": True})
    panel(hass, "disarmed", None)
    await detect(hass, PERSON)
    assert not cameras.clips

    panel(hass, "armed_away", "away")
    await detect(hass, PERSON)
    assert len(cameras.clips) == 1


async def test_armed_only_in_the_chosen_modes(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, when={"armed": True, "armed_modes": ["away"]})
    panel(hass, "armed_night", "night")
    await detect(hass, PERSON)
    assert not cameras.clips

    panel(hass, "armed_away", "away")
    await detect(hass, PERSON)
    assert len(cameras.clips) == 1


async def test_an_alarm_that_is_still_arming_or_has_no_panel_does_not_count(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, when={"armed": True})
    await detect(hass, PERSON)  # no panel at all
    panel(hass, "arming", "away")
    await detect(hass, PERSON)
    assert not cameras.clips

    for state in ("pending", "triggered"):
        panel(hass, state, "away")
        cameras._last.clear()
        await detect(hass, PERSON)
    assert len(cameras.clips) == 2


async def test_a_time_range_counts_only_inside_it_even_across_midnight(hass, tmp_path, services, sent, freezer):
    cameras = await start(hass, tmp_path, when={"armed": False, "time": True, "from": "22:00", "to": "06:00"})
    local = dt_util.now().replace(hour=23, minute=0, second=0, microsecond=0)

    freezer.move_to(local)
    await detect(hass, PERSON)
    assert len(cameras.clips) == 1

    freezer.move_to(local.replace(hour=3) + timedelta(days=1))
    cameras._last.clear()
    await detect(hass, PERSON)
    assert len(cameras.clips) == 2

    freezer.move_to(local.replace(hour=12) + timedelta(days=1))
    cameras._last.clear()
    await detect(hass, PERSON)
    assert len(cameras.clips) == 2


def test_in_range():
    assert in_range(time(23), time(22), time(6))
    assert in_range(time(5, 59), time(22), time(6))
    assert not in_range(time(6), time(22), time(6))
    assert not in_range(time(12), time(22), time(6))
    assert in_range(time(10), time(8), time(18))
    assert not in_range(time(18), time(8), time(18))
    assert in_range(time(3), time(5), time(5))  # a range with no length is the whole day


async def test_armed_and_time_combine_with_or(hass, tmp_path, services, sent, freezer):
    cameras = await start(
        hass, tmp_path, when={"armed": True, "time": True, "from": "22:00", "to": "06:00"}
    )
    noon = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    night = noon.replace(hour=23)
    panel(hass, "disarmed", None)

    freezer.move_to(noon)
    assert not cameras.allowed()          # neither
    freezer.move_to(night)
    assert cameras.allowed()              # night, disarmed
    freezer.move_to(noon)
    panel(hass, "armed_away", "away")
    assert cameras.allowed()              # armed, daytime


async def test_always_overrides_the_rest(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, when={"always": True, "armed": True})
    panel(hass, "disarmed", None)
    await detect(hass, PERSON)
    assert len(cameras.clips) == 1


async def test_with_nothing_selected_nothing_counts(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, when={"always": False, "armed": False, "time": False})
    panel(hass, "armed_away", "away")
    await detect(hass, PERSON)
    assert not cameras.clips


# --- cooldown ---------------------------------------------------------------


async def test_a_camera_records_once_per_cooldown_and_cameras_are_independent(
    hass, tmp_path, services, sent, freezer
):
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)
    freezer.tick(timedelta(seconds=119))
    await detect(hass, VEHICLE)          # same camera, still cooling down
    await detect(hass, MOTION)           # another camera
    assert [c["camera"] for c in cameras.clips] == ["Back", "Front"]

    freezer.tick(timedelta(seconds=2))
    await detect(hass, VEHICLE)
    assert len(cameras.clips) == 3


async def test_a_sensor_that_stays_on_or_goes_unavailable_is_not_a_detection(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    hass.states.async_set(PERSON, "unavailable")
    hass.states.async_set(PERSON, "on")        # unavailable -> on: not a rising edge
    hass.states.async_set(PERSON, "on", {"x": 1})  # attribute change only
    await hass.async_block_till_done()
    assert not cameras.clips


# --- recording failures -----------------------------------------------------


async def test_without_a_stream_it_records_from_now_instead_of_failing(hass, tmp_path, sent):
    async_mock_service(hass, "camera", "snapshot")
    calls = []

    async def record(call):
        calls.append(dict(call.data))
        if "lookback" in call.data:
            raise HomeAssistantError("no stream")

    hass.services.async_register("camera", "record", record)
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)

    assert ["lookback" in c for c in calls] == [True, False]
    assert len(cameras.clips) == 1


async def test_a_recording_that_fails_leaves_no_clip_and_no_notification(hass, tmp_path, sent):
    async_mock_service(hass, "camera", "snapshot")

    async def record(call):
        raise HomeAssistantError("broken")

    hass.services.async_register("camera", "record", record)
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)

    assert not cameras.clips
    sent.assert_not_called()


async def test_a_failed_snapshot_still_records_without_a_picture(hass, tmp_path, services, sent):
    async def snapshot(call):
        raise HomeAssistantError("no picture")

    hass.services.async_register("camera", "snapshot", snapshot)
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)

    assert cameras.clips[0]["image"] is None
    assert "image_url" not in sent.await_args.args[0]


async def test_no_lookback_when_before_is_zero(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    cameras.set_recording(before=0)
    await detect(hass, PERSON)
    assert "lookback" not in services.record[0].data and len(services.record) == 1


# --- settings, clips, retention ---------------------------------------------


async def test_settings_survive_a_restart(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    cameras.set_rule("front", "motion" if False else "vehicle", "record_notify")
    cameras.set_recording(after=20, keep_days=7)
    cameras.set_when(always=False, armed=False, time=True, **{"from": time(21, 30)})
    await detect(hass, PERSON)  # blocked by `when` now? time is on and probably outside; save anyway
    await cameras.async_stop()

    again = AnnikaCameras(hass, config(hass, tmp_path))
    await again.async_start()
    front = next(c for c in again.cameras if c.id == "front")
    assert front.rules["vehicle"] == "record_notify"
    assert again.after == 20 and again.keep_days == 7
    assert again.when["always"] is False and again.when["time"] is True
    assert again.when["from"] == time(21, 30) and again.when["to"] == time(6, 0)


async def test_a_rule_for_a_sensor_that_is_not_there_is_refused(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    with pytest.raises(ValueError):
        cameras.set_rule("front", "motion", "record")
    with pytest.raises(ValueError):
        cameras.set_rule("garage", "person", "record")
    with pytest.raises(ValueError):
        cameras.set_rule("front", "person", "shout")


async def test_deleting_a_clip_removes_its_files(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)
    clip = cameras.clips[0]
    video = tmp_path / "clips" / clip["video"]
    image = tmp_path / "snaps" / clip["image"]
    video.write_bytes(b"v")
    snaps = hass.config.path("www/snaps")
    import os
    os.makedirs(snaps, exist_ok=True)
    image = os.path.join(snaps, clip["image"])
    open(image, "wb").write(b"i")

    await cameras.async_delete_clip(clip["id"])

    assert not cameras.clips and not video.exists() and not os.path.exists(image)
    with pytest.raises(ValueError):
        await cameras.async_delete_clip(clip["id"])


async def test_old_clips_are_deleted_and_recent_ones_kept(hass, tmp_path, services, sent, freezer):
    cameras = await start(hass, tmp_path)
    await detect(hass, PERSON)
    old = dict(cameras.clips[0], id="old", video="front_person_20200101_000000.mp4", image=None,
               time=(dt_util.utcnow() - timedelta(days=31)).isoformat())
    cameras.clips.append(old)
    (tmp_path / "clips" / old["video"]).write_bytes(b"v")
    keep = tmp_path / "clips" / cameras.clips[0]["video"]
    keep.write_bytes(b"v")

    await cameras.async_cleanup()

    assert [c["id"] for c in cameras.clips] != ["old"] and all(c["id"] != "old" for c in cameras.clips)
    assert not (tmp_path / "clips" / old["video"]).exists() and keep.exists()


async def test_cleanup_runs_every_night(hass, tmp_path, services, sent, freezer):
    cameras = await start(hass, tmp_path)
    cameras.clips.append(
        {"id": "old", "time": (dt_util.utcnow() - timedelta(days=40)).isoformat(), "camera": "Front",
         "camera_id": "front", "type": "person", "video": "x.mp4", "image": None, "seconds": 15, "notified": False}
    )
    local = dt_util.now().replace(hour=3, minute=30, second=0, microsecond=0) + timedelta(days=1)
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()
    assert not cameras.clips


async def test_a_stray_old_file_of_ours_is_swept_and_other_files_are_not(hass, tmp_path, services, sent):
    import os
    cameras = await start(hass, tmp_path)
    ours = tmp_path / "clips" / "front_person_20200101_000000.mp4"
    other = tmp_path / "clips" / "holiday.mp4"
    for f in (ours, other):
        f.write_bytes(b"x")
        os.utime(f, (1, 1))
    await cameras.async_cleanup()
    assert not ours.exists() and other.exists()


async def test_clips_are_capped(hass, tmp_path, services, sent):
    cameras = await start(hass, tmp_path, recording={"cooldown": 0})
    for _ in range(105):
        await detect(hass, VEHICLE)
    assert len(cameras.clips) == 100


# --- the entity ---------------------------------------------------------------


async def test_the_sensor_reports_clips_and_the_services_edit_settings(hass, tmp_path, services, sent):
    assert await async_setup_component(hass, "sensor", {})
    cameras = AnnikaCameras(hass, config(hass, tmp_path))
    hass.data[DATA_CAMERAS] = cameras
    hass.config.components.add(DOMAIN)
    for sensor in (PERSON, VEHICLE, MOTION):
        hass.states.async_set(sensor, "off")
    await async_load_platform(hass, "sensor", DOMAIN, {DISCOVERY_KIND: KIND_CAMERAS}, {})
    await hass.async_block_till_done()

    entity = "sensor.annika_cameras"
    assert hass.states.get(entity).state == "0"
    await detect(hass, PERSON)
    state = hass.states.get(entity)
    assert state.state == "1" and state.attributes["clips"][0]["type"] == "person"
    assert state.attributes["config"]["cameras"][0]["rules"]["person"] == "record_notify"
    assert state.attributes["image_base"] == "/local/snaps"

    await hass.services.async_call(
        DOMAIN, "set_camera_rule", {"entity_id": entity, "camera": "front", "type": "person", "action": "off"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "set_recording_when",
        {"entity_id": entity, "always": False, "armed": True, "armed_modes": ["night"], "time": True,
         "from": "21:00:00", "to": "07:30:00"},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "set_recording", {"entity_id": entity, "keep_days": 10}, blocking=True)
    attrs = hass.states.get(entity).attributes["config"]
    assert attrs["cameras"][0]["rules"]["person"] == "off"
    assert attrs["when"] == {"always": False, "armed": True, "armed_modes": ["night"], "time": True,
                             "from": "21:00", "to": "07:30"}
    assert attrs["recording"]["keep_days"] == 10

    clip_id = hass.states.get(entity).attributes["clips"][0]["id"]
    await hass.services.async_call(DOMAIN, "delete_clip", {"entity_id": entity, "clip_id": clip_id}, blocking=True)
    assert hass.states.get(entity).state == "0"


def test_clips_and_snapshots_default_to_the_media_folders():
    schema = CAMERAS_SCHEMA({"cameras": [{"name": "A", "entity": "camera.a"}]})
    assert schema["directory"] == "/media/clips" and schema["snapshots"] == "/media/snapshots"


def test_the_schema_rejects_nonsense():
    base = {"cameras": [{"name": "A", "entity": "camera.a", "person": "binary_sensor.p"}]}
    assert CAMERAS_SCHEMA(base)["recording"] == {"before": 5, "after": 10, "cooldown": 120, "keep_days": 30}
    import voluptuous as vol
    for bad in (
        {"cameras": []},
        {"cameras": [{"name": "A", "entity": "camera.a", "rules": {"person": "shout"}}]},
        {**base, "recording": {"after": 0}},
        {**base, "when": {"armed_modes": ["home"]}},
        {**base, "when": {"from": "25:00"}},
    ):
        with pytest.raises(vol.Invalid):
            CAMERAS_SCHEMA(bad)
