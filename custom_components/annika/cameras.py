"""Annika cameras: what each camera does when it detects something.

A camera has up to four detection sensors (person, vehicle, animal, motion).
For each one the person chooses what happens: nothing, a recording, or a
recording and a notification. The notification is an option of the recording,
not a thing of its own: a detection that is not recorded is not notified.

    annika:
      cameras:
        notify_view: alarm                       # optional: where notifications open
        directory: /media/clips                  # clips (default)
        snapshots: /media/snapshots              # one photo per clip (default);
                                                 # a folder under /config/www works too
        recording: {before: 5, after: 10, cooldown: 120, keep_days: 30}
        when: {armed: true, armed_modes: [away, night, vacation]}
        cameras:
          - name: Camera 1
            entity: camera.e1_outdoor_se_poe_clear
            person: binary_sensor.e1_outdoor_se_poe_person
            vehicle: binary_sensor.e1_outdoor_se_poe_vehicle
            rules: {person: record_notify, vehicle: record}

Cameras can be grouped. A camera names its `group`, and the group sets what its
cameras do for each detection; a camera inherits it unless it has a rule of its
own for that detection (the way a sensor inherits its zone's rule in the alarm):

        groups:                                  # optional: where a group starts
          - name: Garden
            rules: {person: record_notify, vehicle: record}
        cameras:
          - {name: Camera 1, entity: ..., person: ..., vehicle: ..., group: Garden}
          - {name: Camera 2, entity: ..., person: ..., group: Garden, rules: {person: record}}

A group named only by its cameras starts at "off".

Every detection of an allowed kind records `before` seconds before it and
`after` seconds after, takes a snapshot of it (the clip's picture, and the
notification's), and at most once per camera every `cooldown` seconds, so a
person walking up the garden is one clip and not twenty. Clips older than
`keep_days` are deleted every night.

`when` says when detections count at all:

    always: true                  every detection, whatever the alarm is doing
    armed: true                   only while the alarm is armed (or tripped);
    armed_modes: [night]          optionally only in these modes
    time: true, from/to           only between two times of day ("22:00" to
                                  "06:00" crosses midnight)

`armed` and `time` combine with "or": record if the alarm is armed or it is
night. `always` overrides both. The YAML is where it starts; what the person
edits from annika-cameras-card is stored and wins from then on.

Needs `stream:` for the lookback (a camera that cannot stream records from the
moment of the detection instead), and both folders allowed in
`allowlist_external_dirs`. Clips are played through Home Assistant's own
media source, so they sit under /media to be reachable.
"""

from __future__ import annotations

import logging
import os
import re
import time as time_module
import uuid
from datetime import datetime, time, timedelta
from typing import Any, Callable

import voluptuous as vol

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_CAMERAS = f"{DOMAIN}_cameras"

DETECTIONS = ("person", "vehicle", "animal", "motion")
ACTIONS = ("off", "record", "record_notify")
MODES = ("away", "night", "vacation")

STORE_VERSION = 1
MAX_CLIPS = 100
DEFAULT_DIRECTORY = "/media/clips"
DEFAULT_SNAPSHOTS = "/media/snapshots"
CLEANUP_AT = (3, 30)

_FILE = re.compile(r"^[a-z0-9_]+_(person|vehicle|animal|motion)_\d{8}_\d{6}\.(mp4|jpg)$")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _clock(value) -> time:
    return cv.time(value)


_ACTION = vol.In(ACTIONS)

CAMERA_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entity"): cv.entity_id,
        **{vol.Optional(kind): cv.entity_id for kind in DETECTIONS},
        vol.Optional("group"): cv.string,
        vol.Optional("rules", default={}): vol.Schema({vol.Optional(kind): _ACTION for kind in DETECTIONS}),
    }
)

GROUP_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("rules", default={}): vol.Schema({vol.Optional(kind): _ACTION for kind in DETECTIONS}),
    }
)

CAMERAS_SCHEMA = vol.Schema(
    {
        vol.Optional("name", default="Annika Cameras"): cv.string,
        vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
        vol.Optional("directory", default=DEFAULT_DIRECTORY): cv.string,
        vol.Optional("snapshots", default=DEFAULT_SNAPSHOTS): cv.string,
        vol.Optional("recording", default={}): vol.Schema(
            {
                vol.Optional("before", default=5): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("after", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                vol.Optional("cooldown", default=120): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                vol.Optional("keep_days", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
            }
        ),
        vol.Optional("when", default={}): vol.Schema(
            {
                vol.Optional("always", default=False): cv.boolean,
                vol.Optional("armed", default=True): cv.boolean,
                vol.Optional("armed_modes", default=list(MODES)): vol.All(cv.ensure_list, [vol.In(MODES)]),
                vol.Optional("time", default=False): cv.boolean,
                vol.Optional("from", default="22:00"): _clock,
                vol.Optional("to", default="06:00"): _clock,
            }
        ),
        vol.Optional("groups", default=[]): vol.All(cv.ensure_list, [GROUP_SCHEMA]),
        vol.Required("cameras"): vol.All(cv.ensure_list, [CAMERA_SCHEMA], vol.Length(min=1)),
    }
)

TEXTS = {
    "en": {
        "title_person": "👤 Person detected",
        "title_vehicle": "🚗 Vehicle detected",
        "title_animal": "🐾 Animal detected",
        "title_motion": "🏃 Motion detected",
    },
    "es": {
        "title_person": "👤 Persona detectada",
        "title_vehicle": "🚗 Vehículo detectado",
        "title_animal": "🐾 Animal detectado",
        "title_motion": "🏃 Movimiento detectado",
    },
}


class _Group:
    def __init__(self, name: str, rules: dict[str, str]) -> None:
        self.id = slug(name)
        self.name = name
        self.rules: dict[str, str] = {kind: rules.get(kind, "off") for kind in DETECTIONS}
        self.kinds: list[str] = []


class _Camera:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name = config["name"]
        self.entity: str = config["entity"]
        self.sensors: dict[str, str] = {kind: config[kind] for kind in DETECTIONS if kind in config}
        self.group_id: str | None = slug(config["group"]) if config.get("group") else None
        # None: follows the group. A camera with no group always has a rule of its own.
        self.rules: dict[str, str | None] = {
            kind: config["rules"].get(kind, None if self.group_id else "off") for kind in self.sensors
        }


def in_range(now: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


class AnnikaCameras:
    """Decides what a detection means, records it and keeps the clips."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.notify_view: str | None = config.get("notify_view")
        self.directory: str = config["directory"].rstrip("/")
        self.snapshots: str = config["snapshots"].rstrip("/")
        recording = config["recording"]
        self.before: int = recording["before"]
        self.after: int = recording["after"]
        self.cooldown: int = recording["cooldown"]
        self.keep_days: int = recording["keep_days"]
        self.when: dict[str, Any] = dict(config["when"])
        self.cameras = [_Camera(camera) for camera in config["cameras"]]
        self.groups = self._build_groups(config)
        self.clips: list[dict] = []

        self._last: dict[str, datetime] = {}
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.cameras")
        self._cancel_sensors: Callable[[], None] | None = None
        self._cancel_cleanup: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._by_entity: dict[str, list[tuple[_Camera, str]]] = {}
        for camera in self.cameras:
            for kind, entity_id in camera.sensors.items():
                self._by_entity.setdefault(entity_id, []).append((camera, kind))

    def _build_groups(self, config: dict) -> list[_Group]:
        """The groups the YAML lists, plus any a camera names that it does not."""

        groups: dict[str, _Group] = {}
        for group in config.get("groups", []):
            groups[slug(group["name"])] = _Group(group["name"], group["rules"])
        for camera, raw in zip(self.cameras, config["cameras"]):
            if camera.group_id and camera.group_id not in groups:
                groups[camera.group_id] = _Group(raw["group"], {})
            if camera.group_id:
                group = groups[camera.group_id]
                group.kinds.extend(kind for kind in camera.sensors if kind not in group.kinds)
        for group in groups.values():
            group.kinds.sort(key=DETECTIONS.index)
        return list(groups.values())

    def action_for(self, camera: _Camera, kind: str) -> str:
        """What the camera does for this detection: its own rule, else its group's."""

        action = camera.rules.get(kind)
        if action is not None:
            return action
        group = next((g for g in self.groups if g.id == camera.group_id), None)
        return group.rules.get(kind, "off") if group else "off"

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._apply(await self._store.async_load() or {})
        for path in (self.directory, self.snapshots):
            if not self.hass.config.is_allowed_path(path):
                _LOGGER.warning("Annika cameras: %s is not in allowlist_external_dirs; recording there will fail", path)
        await self.hass.async_add_executor_job(self._make_directories)
        self._cancel_sensors = async_track_state_change_event(
            self.hass, list(self._by_entity), self._sensor_changed
        )
        hour, minute = CLEANUP_AT
        self._cancel_cleanup = async_track_time_change(
            self.hass, self._cleanup_due, hour=hour, minute=minute, second=0
        )
        await self.async_cleanup()

    async def async_stop(self, _event=None) -> None:
        for cancel in (self._cancel_sensors, self._cancel_cleanup):
            if cancel is not None:
                cancel()
        self._cancel_sensors = self._cancel_cleanup = None
        await self._store.async_save(self._saved())

    def _make_directories(self) -> None:
        for path in (self.directory, self.snapshots):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as error:
                _LOGGER.warning("Annika cameras: could not create %s: %s", path, error)

    # --- settings (what the card edits) -------------------------------------

    def _apply(self, saved: dict) -> None:
        recording = saved.get("recording", {})
        for key in ("before", "after", "cooldown", "keep_days"):
            if isinstance(recording.get(key), int):
                setattr(self, key, recording[key])
        when = saved.get("when", {})
        for key, value in when.items():
            if key in self.when:
                self.when[key] = time.fromisoformat(value) if key in ("from", "to") else value
        by_id = {camera.id: camera for camera in self.cameras}
        for camera_id, rules in saved.get("rules", {}).items():
            if (camera := by_id.get(camera_id)) is not None:
                for kind, action in rules.items():
                    if kind in camera.rules and (action in ACTIONS or (action is None and camera.group_id)):
                        camera.rules[kind] = action
        groups = {group.id: group for group in self.groups}
        for group_id, rules in saved.get("groups", {}).items():
            if (group := groups.get(group_id)) is not None:
                for kind, action in rules.items():
                    if kind in group.rules and action in ACTIONS:
                        group.rules[kind] = action
        self.clips = saved.get("clips", [])[:MAX_CLIPS]

    def _saved(self) -> dict[str, Any]:
        return {
            "recording": {
                "before": self.before,
                "after": self.after,
                "cooldown": self.cooldown,
                "keep_days": self.keep_days,
            },
            "when": {
                key: value.isoformat() if isinstance(value, time) else value
                for key, value in self.when.items()
            },
            "rules": {camera.id: dict(camera.rules) for camera in self.cameras},
            "groups": {group.id: dict(group.rules) for group in self.groups},
            "clips": self.clips,
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self.notify()

    def set_rule(self, camera_id: str, kind: str, action: str | None) -> None:
        """A camera's own rule; None gives it back to its group."""

        camera = next((c for c in self.cameras if c.id == camera_id), None)
        if camera is None or kind not in camera.sensors:
            raise ValueError("unknown camera or detection")
        if action is None:
            if not camera.group_id:
                raise ValueError("a camera with no group has no rule to inherit")
        elif action not in ACTIONS:
            raise ValueError("unknown action")
        camera.rules[kind] = action
        self._changed()

    def set_group_rule(self, group_id: str, kind: str, action: str) -> None:
        group = next((g for g in self.groups if g.id == group_id), None)
        if group is None or kind not in group.kinds or action not in ACTIONS:
            raise ValueError("unknown group or detection")
        group.rules[kind] = action
        self._changed()

    def set_recording(self, **values) -> None:
        for key, value in values.items():
            if value is not None:
                setattr(self, key, value)
        self._changed()

    def set_when(self, **values) -> None:
        for key, value in values.items():
            if value is not None:
                self.when[key] = value
        self._changed()

    # --- listeners ----------------------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --- when ---------------------------------------------------------------

    def allowed(self, now: datetime | None = None) -> bool:
        """Whether detections count right now, by `when`."""

        when = self.when
        if when["always"]:
            return True
        if when["armed"] and self._alarm_armed(when["armed_modes"]):
            return True
        if when["time"]:
            local = dt_util.as_local(now or dt_util.now())
            return in_range(local.time().replace(second=0, microsecond=0), when["from"], when["to"])
        return False

    def _alarm_armed(self, modes: list[str]) -> bool:
        panel = self.hass.data.get(f"{DOMAIN}_alarm_panel")
        if panel is None or panel.state in ("disarmed", "arming"):
            return False
        return panel.mode in modes

    # --- detections ---------------------------------------------------------

    @callback
    def _sensor_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or new.state != "on" or old is None or old.state != "off":
            return
        for camera, kind in self._by_entity.get(event.data["entity_id"], []):
            self._detected(camera, kind)

    def _detected(self, camera: _Camera, kind: str) -> None:
        action = self.action_for(camera, kind)
        if action == "off" or not self.allowed():
            return
        now = dt_util.utcnow()
        last = self._last.get(camera.id)
        if last is not None and now < last + timedelta(seconds=self.cooldown):
            return
        self._last[camera.id] = now
        self.hass.async_create_task(self._capture(camera, kind, action == "record_notify"))

    async def _capture(self, camera: _Camera, kind: str, notify: bool) -> None:
        stamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        base = f"{camera.id}_{kind}_{stamp}"
        video, image = f"{base}.mp4", f"{base}.jpg"
        before, after = self.before, self.after
        image_saved = await self._async_call(
            "snapshot", {"entity_id": camera.entity, "filename": f"{self.snapshots}/{image}"}
        )
        data = {"entity_id": camera.entity, "filename": f"{self.directory}/{video}", "duration": after}
        recorded = False
        if before:
            recorded = await self._async_call("record", {**data, "lookback": before})
        if not recorded:
            # A camera with no stream running has no past to look back into.
            recorded = await self._async_call("record", data)
        if not recorded:
            return
        clip = {
            "id": uuid.uuid4().hex[:8],
            "time": dt_util.utcnow().isoformat(),
            "camera": camera.name,
            "camera_id": camera.id,
            "type": kind,
            "video": video,
            "image": image if image_saved else None,
            "seconds": before + after,
            "notified": notify,
        }
        self.clips.insert(0, clip)
        del self.clips[MAX_CLIPS:]
        self._changed()
        if notify:
            await self._send(camera, kind, clip["image"])

    async def _async_call(self, service: str, data: dict) -> bool:
        try:
            await self.hass.services.async_call("camera", service, data, blocking=True)
        except (HomeAssistantError, vol.Invalid, OSError) as error:
            _LOGGER.warning("Annika cameras: camera.%s failed for %s: %s", service, data["entity_id"], error)
            return False
        return True

    # --- notifications ------------------------------------------------------

    def _text(self, key: str, **values) -> str:
        language = str(self.hass.config.language or "en").split("-")[0].lower()
        texts = TEXTS.get(language, TEXTS["en"])
        return texts.get(key, TEXTS["en"][key]).format(**values)

    @property
    def image_base(self) -> str | None:
        """Where a snapshot is served from, when the folder is under Home Assistant's www or /media."""

        www = self.hass.config.path("www").rstrip("/")
        if self.snapshots.startswith(www + "/") or self.snapshots == www:
            return "/local" + self.snapshots[len(www):]
        if self.snapshots.startswith("/media/"):
            # Home Assistant's media source serves /media (it needs a signed URL).
            return "/media/local/" + self.snapshots[len("/media/"):]
        return None

    @property
    def media_base(self) -> str | None:
        """The media source folder clips are played from, when the folder is under /media."""

        if self.directory.startswith("/media/"):
            return "media-source://media_source/local/" + self.directory[len("/media/"):]
        return None

    async def _send(self, camera: _Camera, kind: str, image: str | None) -> None:
        if not self.notify_view:
            _LOGGER.warning(
                "Annika cameras: %s is set to record and notify but notify_view is not configured; no notification sent",
                camera.name,
            )
            return
        event = {
            "eventId": str(uuid.uuid4()),
            "type": "info",
            "title": self._text(f"title_{kind}"),
            # The API rejects an empty message: the camera's name says where.
            "message": camera.name,
            "view": self.notify_view,
        }
        if image and self.image_base:
            event["imageUrl"] = f"{self.image_base}/{image}"
        try:
            await AnnikaEventClient(self.hass).async_send(event)
        except Exception:  # noqa: BLE001 — a missed notification must not stop the recording
            _LOGGER.warning("Annika cameras: could not send the notification for %s", camera.name)

    # --- clips --------------------------------------------------------------

    async def async_delete_clip(self, clip_id: str) -> None:
        clip = next((c for c in self.clips if c["id"] == clip_id), None)
        if clip is None:
            raise ValueError("unknown clip")
        self.clips.remove(clip)
        self._changed()
        await self.hass.async_add_executor_job(self._remove_files, [clip["video"], clip["image"]])

    def _remove_files(self, names: list[str | None]) -> None:
        for name in names:
            if not name:
                continue
            for folder in (self.directory, self.snapshots):
                try:
                    os.remove(f"{folder}/{name}")
                except FileNotFoundError:
                    pass
                except OSError as error:
                    _LOGGER.warning("Annika cameras: could not delete %s/%s: %s", folder, name, error)

    @callback
    def _cleanup_due(self, _now) -> None:
        self.hass.async_create_task(self.async_cleanup())

    async def async_cleanup(self) -> None:
        """Delete clips older than `keep_days`, and any stray file of ours as old."""

        limit = dt_util.utcnow() - timedelta(days=self.keep_days)
        old = [c for c in self.clips if dt_util.parse_datetime(c["time"]) < limit]
        if old:
            self.clips = [c for c in self.clips if c not in old]
            self._changed()
        await self.hass.async_add_executor_job(
            self._sweep, [c["video"] for c in old] + [c["image"] for c in old], limit.timestamp()
        )

    def _sweep(self, names: list[str | None], limit: float) -> None:
        self._remove_files(names)
        for folder in {self.directory, self.snapshots}:
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                if _FILE.match(entry.name) and entry.stat().st_mtime < limit:
                    try:
                        os.remove(entry.path)
                    except OSError as error:
                        _LOGGER.warning("Annika cameras: could not delete %s: %s", entry.path, error)

    # --- what the card reads ------------------------------------------------

    def attributes(self) -> dict[str, Any]:
        return {
            "config": {
                "recording": {
                    "before": self.before,
                    "after": self.after,
                    "cooldown": self.cooldown,
                    "keep_days": self.keep_days,
                },
                "when": {
                    **{k: v for k, v in self.when.items() if k not in ("from", "to")},
                    "from": self.when["from"].strftime("%H:%M"),
                    "to": self.when["to"].strftime("%H:%M"),
                },
                "notification": bool(self.notify_view),
                "groups": [
                    {"id": group.id, "name": group.name, "kinds": group.kinds, "rules": group.rules}
                    for group in self.groups
                ],
                "cameras": [
                    {
                        "id": camera.id,
                        "group": camera.group_id,
                        "name": camera.name,
                        "entity": camera.entity,
                        "sensors": camera.sensors,
                        "rules": camera.rules,
                    }
                    for camera in self.cameras
                ],
            },
            "clips": self.clips,
            "media_base": self.media_base,
            "image_base": self.image_base,
        }
