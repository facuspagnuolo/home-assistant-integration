"""Annika doorbells: who is told when someone rings.

A doorbell is a camera with a `visitor` sensor that turns on when the button is
pressed (and, optionally, the detection sensors of the camera). When it rings,
Annika tells two kinds of recipients, and the person chooses for each whether it
happens when somebody is home and when nobody is:

    devices   the unit's paired tablets: they are taken to the notification's view
    users     the people of the Annika app: a notification with a picture

    annika:
      doorbell:
        notify_view: doorbell                    # where notifications and tablets open
        snapshots: /media/snapshots              # the notification's picture (default);
                                                 # a folder under /config/www works too
        presence: [person.facu, person.delfi]    # who decides "nobody is home"
        notifications:                           # where it starts; the card edits it
          devices: {home: true, away: true}
          users: {home: false, away: true}
        talk: {mute_speaker: true, auto_off: true, auto_off_seconds: 60}
        doorbells:
          - name: Front Door
            entity: camera.main_doorbell_fluent  # the stream the card plays
            visitor: binary_sensor.main_doorbell_visitor
            person: binary_sensor.main_doorbell_person     # optional, only for the card's icons
            vehicle: binary_sensor.main_doorbell_vehicle
            animal: binary_sensor.main_doorbell_pet
            motion: binary_sensor.main_doorbell_motion

Somebody is home when any of the `presence` people is `home`; nobody is home when
none is (a person that is `unknown` or `unavailable` counts as not home, so a
tracker that went quiet does not silence the notification). The YAML is where it
starts; what the person edits from annika-doorbell-card is stored and wins from
then on.

`talk` is what the card does while someone speaks to the visitor through the
doorbell: whether the speaker is muted meanwhile (so the doorbell's microphone
does not hear itself) and whether the microphone is turned off by itself.
Nothing here decides who may talk: that is who may open the dashboard.

Needs the snapshot folder in `allowlist_external_dirs`.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

import voluptuous as vol

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .cameras import slug
from .const import DOMAIN
from .send_event import ACTOR_DEVICES, AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_DOORBELLS = f"{DOMAIN}_doorbells"

DETECTIONS = ("person", "vehicle", "animal", "motion")
TARGETS = ("devices", "users")
WHEN = ("home", "away")

STORE_VERSION = 1
DEFAULT_SNAPSHOTS = "/media/snapshots"
# A button pressed three times in a row is one visit, not three notifications.
DEBOUNCE_SECONDS = 10
SNAPSHOT_KEEP_SECONDS = 24 * 3600

_FILE = re.compile(r"^[a-z0-9_]+_visitor_\d{8}_\d{6}\.jpg$")

_PERSON = vol.All(cv.entity_id, vol.Match(r"^person\."))

DOORBELL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entity"): cv.entity_id,
        vol.Required("visitor"): cv.entity_id,
        **{vol.Optional(kind): cv.entity_id for kind in DETECTIONS},
    }
)

_WHEN = vol.Schema({vol.Optional(when): cv.boolean for when in WHEN})

DOORBELLS_SCHEMA = vol.Schema(
    {
        vol.Optional("name", default="Annika Doorbells"): cv.string,
        vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
        vol.Optional("snapshots", default=DEFAULT_SNAPSHOTS): cv.string,
        vol.Optional("presence", default=[]): vol.All(cv.ensure_list, [_PERSON]),
        vol.Optional("notifications", default={}): vol.Schema(
            {vol.Optional(target): _WHEN for target in TARGETS}
        ),
        vol.Optional("talk", default={}): vol.Schema(
            {
                vol.Optional("mute_speaker", default=True): cv.boolean,
                vol.Optional("auto_off", default=True): cv.boolean,
                vol.Optional("auto_off_seconds", default=60): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=600)
                ),
            }
        ),
        vol.Required("doorbells"): vol.All(cv.ensure_list, [DOORBELL_SCHEMA], vol.Length(min=1)),
    }
)

# The devices are told wherever the person is; the people of the app only when nobody is home.
DEFAULT_NOTIFICATIONS = {
    "devices": {"home": True, "away": True},
    "users": {"home": False, "away": True},
}

TEXTS = {
    "en": {"title": "🔔 Someone is at the door", "title_test": "🔔 Doorbell test"},
    "es": {"title": "🔔 Alguien en la puerta", "title_test": "🔔 Prueba del timbre"},
}


class _Doorbell:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name: str = config["name"]
        self.entity: str = config["entity"]
        self.visitor: str = config["visitor"]
        self.sensors: dict[str, str] = {kind: config[kind] for kind in DETECTIONS if kind in config}


def image_base(hass: HomeAssistant, folder: str) -> str | None:
    """Where a snapshot is served from, when the folder is under Home Assistant's www or /media."""

    www = hass.config.path("www").rstrip("/")
    if folder.startswith(www + "/") or folder == www:
        return "/local" + folder[len(www):]
    if folder.startswith("/media/"):
        # Home Assistant's media source serves /media (it needs a signed URL).
        return "/media/local/" + folder[len("/media/"):]
    return None


class AnnikaDoorbells:
    """Decides who a ring is told to, and tells them."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.notify_view: str | None = config.get("notify_view")
        self.snapshots: str = config["snapshots"].rstrip("/")
        self.doorbells = [_Doorbell(doorbell) for doorbell in config["doorbells"]]
        self.presence: list[str] = list(dict.fromkeys(config["presence"]))
        self.notifications: dict[str, dict[str, bool]] = {
            target: {
                when: config["notifications"].get(target, {}).get(when, DEFAULT_NOTIFICATIONS[target][when])
                for when in WHEN
            }
            for target in TARGETS
        }
        self.talk: dict[str, Any] = dict(config["talk"])
        self.last_ring: datetime | None = None

        self._last: dict[str, datetime] = {}
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.doorbells")
        self._cancel_visitors: Callable[[], None] | None = None
        self._cancel_presence: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._by_visitor = {doorbell.visitor: doorbell for doorbell in self.doorbells}

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._apply(await self._store.async_load() or {})
        if not self.hass.config.is_allowed_path(self.snapshots):
            _LOGGER.warning(
                "Annika doorbells: %s is not in allowlist_external_dirs; the notification will have no picture",
                self.snapshots,
            )
        await self.hass.async_add_executor_job(self._make_directory)
        self._cancel_visitors = async_track_state_change_event(
            self.hass, list(self._by_visitor), self._visitor_changed
        )
        self._track_presence()

    async def async_stop(self, _event=None) -> None:
        for cancel in (self._cancel_visitors, self._cancel_presence):
            if cancel is not None:
                cancel()
        self._cancel_visitors = self._cancel_presence = None
        await self._store.async_save(self._saved())

    def _make_directory(self) -> None:
        try:
            os.makedirs(self.snapshots, exist_ok=True)
        except OSError as error:
            _LOGGER.warning("Annika doorbells: could not create %s: %s", self.snapshots, error)

    def _track_presence(self) -> None:
        if self._cancel_presence is not None:
            self._cancel_presence()
            self._cancel_presence = None
        if self.presence:
            self._cancel_presence = async_track_state_change_event(
                self.hass, self.presence, self._presence_changed
            )

    @callback
    def _presence_changed(self, _event: Event) -> None:
        self.notify()

    # --- settings (what the card edits) -------------------------------------

    def _apply(self, saved: dict) -> None:
        for target, values in saved.get("notifications", {}).items():
            if target in self.notifications and isinstance(values, dict):
                for when in WHEN:
                    if isinstance(values.get(when), bool):
                        self.notifications[target][when] = values[when]
        if isinstance(saved.get("presence"), list):
            self.presence = [
                entity for entity in dict.fromkeys(saved["presence"])
                if isinstance(entity, str) and entity.startswith("person.")
            ]
        talk = saved.get("talk", {})
        for key in ("mute_speaker", "auto_off"):
            if isinstance(talk.get(key), bool):
                self.talk[key] = talk[key]
        if isinstance(talk.get("auto_off_seconds"), int) and 10 <= talk["auto_off_seconds"] <= 600:
            self.talk["auto_off_seconds"] = talk["auto_off_seconds"]

    def _saved(self) -> dict[str, Any]:
        return {
            "notifications": {target: dict(values) for target, values in self.notifications.items()},
            "presence": list(self.presence),
            "talk": dict(self.talk),
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self.notify()

    def set_notification(self, target: str, home: bool | None = None, away: bool | None = None) -> None:
        if target not in TARGETS:
            raise ValueError("unknown target")
        for when, value in (("home", home), ("away", away)):
            if value is not None:
                self.notifications[target][when] = value
        self._changed()

    def set_presence(self, people: list[str]) -> None:
        if any(not isinstance(entity, str) or not entity.startswith("person.") for entity in people):
            raise ValueError("only person entities can say who is home")
        self.presence = list(dict.fromkeys(people))
        self._track_presence()
        self._changed()

    def set_talk(self, **values) -> None:
        for key, value in values.items():
            if value is not None:
                self.talk[key] = value
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

    # --- who is home --------------------------------------------------------

    def people(self) -> list[dict[str, Any]]:
        people = []
        for entity in self.presence:
            state = self.hass.states.get(entity)
            people.append(
                {
                    "entity": entity,
                    "name": (state.attributes.get("friendly_name") if state else None) or entity,
                    "home": state is not None and state.state == "home",
                }
            )
        return people

    def anyone_home(self) -> bool:
        return any(person["home"] for person in self.people())

    # --- rings --------------------------------------------------------------

    @callback
    def _visitor_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or new.state != "on" or old is None or old.state != "off":
            return
        doorbell = self._by_visitor.get(event.data["entity_id"])
        if doorbell is not None:
            self._rang(doorbell)

    def _rang(self, doorbell: _Doorbell) -> None:
        now = dt_util.utcnow()
        last = self._last.get(doorbell.id)
        if last is not None and now < last + timedelta(seconds=DEBOUNCE_SECONDS):
            return
        self._last[doorbell.id] = now
        self.last_ring = now
        self.notify()
        when = "home" if self.anyone_home() else "away"
        targets = [target for target in TARGETS if self.notifications[target][when]]
        if targets:
            self.hass.async_create_task(self._announce(doorbell, targets))

    # --- notifications ------------------------------------------------------

    def _text(self, key: str) -> str:
        language = str(self.hass.config.language or "en").split("-")[0].lower()
        return TEXTS.get(language, TEXTS["en"]).get(key, TEXTS["en"][key])

    @property
    def image_base(self) -> str | None:
        return image_base(self.hass, self.snapshots)

    async def async_test(self, target: str) -> None:
        """Send what a ring would send to one kind of recipient, now."""

        if target not in TARGETS:
            raise ValueError("unknown target")
        await self._announce(self.doorbells[0], [target], test=True)

    async def _announce(self, doorbell: _Doorbell, targets: list[str], test: bool = False) -> None:
        if not self.notify_view:
            _LOGGER.warning(
                "Annika doorbells: %s rang but notify_view is not configured; no notification sent",
                doorbell.name,
            )
            return
        image = await self._snapshot(doorbell) if "users" in targets else None
        event: dict[str, Any] = {
            "eventId": str(uuid.uuid4()),
            "type": "info",
            "title": self._text("title_test" if test else "title"),
            # The API rejects an empty message: the doorbell's name says where.
            "message": doorbell.name,
            "view": self.notify_view,
        }
        if image and self.image_base:
            event["imageUrl"] = f"{self.image_base}/{image}"
        if "devices" in targets:
            event["navigate"] = True
        if "users" not in targets:
            # Only the tablets are told: nobody gets a notification.
            event["actor"] = ACTOR_DEVICES
        try:
            await AnnikaEventClient(self.hass).async_send(event)
        except Exception:  # noqa: BLE001 — a missed notification must not break the next ring
            _LOGGER.warning("Annika doorbells: could not send the notification for %s", doorbell.name)

    async def _snapshot(self, doorbell: _Doorbell) -> str | None:
        name = f"{doorbell.id}_visitor_{dt_util.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        try:
            await self.hass.services.async_call(
                "camera",
                "snapshot",
                {"entity_id": doorbell.entity, "filename": f"{self.snapshots}/{name}"},
                blocking=True,
            )
        except Exception as error:  # noqa: BLE001 — a doorbell with no picture is still worth a notification
            _LOGGER.warning("Annika doorbells: camera.snapshot failed for %s: %s", doorbell.entity, error)
            return None
        await self.hass.async_add_executor_job(
            self._sweep, dt_util.utcnow().timestamp() - SNAPSHOT_KEEP_SECONDS
        )
        return name

    def _sweep(self, limit: float) -> None:
        """Delete the pictures of ours that are a day old: the notification has long since fetched them."""

        try:
            entries = list(os.scandir(self.snapshots))
        except OSError:
            return
        for entry in entries:
            if _FILE.match(entry.name) and entry.stat().st_mtime < limit:
                try:
                    os.remove(entry.path)
                except OSError as error:
                    _LOGGER.warning("Annika doorbells: could not delete %s: %s", entry.path, error)

    # --- what the card reads ------------------------------------------------

    def attributes(self) -> dict[str, Any]:
        people = self.people()
        return {
            "config": {
                "notification": bool(self.notify_view),
                "notifications": {target: dict(values) for target, values in self.notifications.items()},
                "presence": {"people": people, "home": sum(1 for person in people if person["home"])},
                "talk": dict(self.talk),
                "doorbells": [
                    {
                        "id": doorbell.id,
                        "name": doorbell.name,
                        "entity": doorbell.entity,
                        "visitor": doorbell.visitor,
                        "sensors": doorbell.sensors,
                    }
                    for doorbell in self.doorbells
                ],
            },
        }
