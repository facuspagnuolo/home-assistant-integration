"""Annika locks: the codes of the doors, who opened them, and what an opening does.

    annika:
      locks:
        name: Annika Locks
        notify_view: locks                  # where security notifications open
        slots: 10                           # the code slots Annika may use (1..10)
        emergency_offset: 200               # the emergency code of slot N is programmed in N + 200
        disarm_alarm:                       # where the rule starts; the card edits it
          enabled: false
          locks: [lock.front_door_lock]     # none = every lock
          modes: []                         # none = any mode
        locks:
          - name: Front Door
            entity: lock.front_door_lock    # a Z-Wave JS lock
            sensor: binary_sensor.front_door_contact   # optional: the door, on = open
            battery: sensor.front_door_lock_battery    # optional

Codes. A code has a name, a slot and the locks it works on, and it is programmed
in those locks (`zwave_js.set_lock_usercode`). It is fixed, or temporary: a
temporary one is removed from the locks by itself when it expires. Home Assistant
cannot read a PIN back from a lock, so the codes live here, in the integration's
storage, and the card shows them.

Emergency code. Every code has another one: the same digits with the last one
changed to 0. It is programmed in slot + `emergency_offset`, opens the door like the
code itself and, when it is used, sends a security notification saying who and
where. Nothing to turn on: it is part of every code. That is why a code cannot end
in 0 (it would be its own emergency code) and why two codes cannot differ only in
the last digit.

Who opened. The lock says it through Z-Wave (`zwave_js_notification`: a keypad
code, the thumb turn, the remote, the auto-lock). The app says it for the doors it
opens (actor.py). A fingerprint, or anything the lock does not say, is an opening
of nobody in particular: the lock changed, that is all Annika knows.

Rule: disarm the alarm when a door is unlocked, however it was opened, while the
alarm is armed (or counting down) in one of the chosen modes.

Lock when closed: a lock can lock itself some seconds after its door closes
(needs a `sensor`). The two settings of that and the one of "hold to unlock" are
entities of each lock, so the card shows them as it shows any other setting.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .actor import DATA_ACTOR
from .alarm_panel import DATA_ALARM_PANEL, MODES
from .cameras import slug
from .const import DOMAIN
from .send_event import AnnikaEventClient

_LOGGER = logging.getLogger(__name__)

DATA_LOCKS = f"{DOMAIN}_locks"

STORE_VERSION = 1
MAX_EVENTS = 50

CODE_MIN_LENGTH = 4
CODE_MAX_LENGTH = 8
DEFAULT_SLOTS = 10
DEFAULT_OFFSET = 200
MAX_TEMP_HOURS = 24 * 30

DEFAULT_CLOSE_SECONDS = 30
CLOSE_MIN_SECONDS = 5
CLOSE_MAX_SECONDS = 600

DEFAULT_OPEN_SECONDS = 60
OPEN_MIN_SECONDS = 10
OPEN_MAX_SECONDS = 3600

# How long an action of the app, or a lock Annika locked itself, is remembered as
# the reason for the opening that follows it.
ORIGIN_WINDOW = 15
# A lock that changed with no word from Z-Wave is given this long to say it.
ZWAVE_WAIT = 3
# What counts as the same opening between the Z-Wave word and the state change.
SAME_OPENING = 10
EXPIRY_RETRY = 300

EVENT_ZWAVE = "zwave_js_notification"

KINDS_OPEN = ("unlock", "emergency", "unknown")

# Z-Wave "Access Control" events of a lock: what happened and how.
ZWAVE_EVENTS = {
    1: ("lock", "manual"),
    2: ("unlock", "manual"),
    3: ("lock", "remote"),
    4: ("unlock", "remote"),
    5: ("lock", "keypad"),
    6: ("unlock", "keypad"),
    9: ("lock", "auto"),
}
ZWAVE_LABELS = (
    ("keypad unlock", ("unlock", "keypad")),
    ("keypad lock", ("lock", "keypad")),
    ("manual unlock", ("unlock", "manual")),
    ("manual lock", ("lock", "manual")),
    ("rf unlock", ("unlock", "remote")),
    ("rf lock", ("lock", "remote")),
    ("auto lock locked", ("lock", "auto")),
)

_LOCK = vol.All(cv.entity_id, vol.Match(r"^lock\."))

LOCK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entity"): _LOCK,
        vol.Optional("sensor"): cv.entity_id,
        vol.Optional("battery"): cv.entity_id,
    }
)


def _rule_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional("enabled", default=False): cv.boolean,
            vol.Optional("locks", default=[]): vol.All(cv.ensure_list, [_LOCK]),
            vol.Optional("modes", default=[]): vol.All(cv.ensure_list, [vol.In(MODES)]),
        }
    )


def _offset_covers_slots(config: dict) -> dict:
    if config["emergency_offset"] < config["slots"]:
        raise vol.Invalid("emergency_offset must not be smaller than slots")
    return config


LOCKS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name", default="Annika Locks"): cv.string,
            vol.Optional("notify_view"): vol.All(cv.string, vol.Match(r"^[\w-]+$")),
            vol.Optional("slots", default=DEFAULT_SLOTS): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
            vol.Optional("emergency_offset", default=DEFAULT_OFFSET): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=900)
            ),
            vol.Optional("disarm_alarm", default={}): _rule_schema(),
            vol.Required("locks"): vol.All(cv.ensure_list, [LOCK_SCHEMA], vol.Length(min=1)),
        }
    ),
    _offset_covers_slots,
)

TEXTS = {
    "en": {
        "emergency_title": "🚨 Emergency!",
        "emergency_message": "{who} used the emergency code · {lock}",
        "imported_name": "Code in slot {slot}",
        "left_open_title": "🚪 Door open",
        "left_open_message": "{lock} has been open for {time}",
    },
    "es": {
        "emergency_title": "🚨 ¡Emergencia!",
        "emergency_message": "{who} usó el código de emergencia · {lock}",
        "imported_name": "Código de la posición {slot}",
        "left_open_title": "🚪 Puerta abierta",
        "left_open_message": "{lock} lleva {time} abierta",
    },
}

# The logbook's line (activity.py reads "<what> por <who>"), by kind of event.
LOGBOOK_VERBS = {
    "unlock": "abierto con llave",
    "lock": "cerrado con llave",
    "emergency": "abierto con código de emergencia",
}


class CodeError(ValueError):
    """A code, or what is asked of one, that cannot be. `key` is the translation key."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


def emergency_code(code: str) -> str:
    """The same code with the last digit changed to 0."""

    return code[:-1] + "0"


def random_code(length: int = 6) -> str:
    """A code that does not end in 0 (that ending is the emergency alert)."""

    digits = "".join(secrets.choice("0123456789") for _ in range(length - 1))
    return digits + secrets.choice("123456789")


def _digits(code: Any) -> str:
    code = str(code).strip()
    if not re.fullmatch(rf"\d{{{CODE_MIN_LENGTH},{CODE_MAX_LENGTH}}}", code):
        raise CodeError("invalid_lock_code")
    return code


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class _Lock:
    def __init__(self, config: dict) -> None:
        self.id = slug(config["name"])
        self.name: str = config["name"]
        self.entity: str = config["entity"]
        self.sensor: str | None = config.get("sensor")
        self.battery: str | None = config.get("battery")
        # The settings of the lock (entities: see locks_entities.py).
        self.hold = True
        self.close_enabled = False
        self.close_seconds = DEFAULT_CLOSE_SECONDS
        self.open_enabled = False
        self.open_seconds = DEFAULT_OPEN_SECONDS


class AnnikaLocks:
    """The codes, the activity and the rules of the doors."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.name: str = config["name"]
        self.notify_view: str | None = config.get("notify_view")
        self.slots: int = config["slots"]
        self.offset: int = config["emergency_offset"]
        self.locks = [_Lock(lock) for lock in config["locks"]]
        self.last_open: datetime | None = None

        rule = config["disarm_alarm"]
        self.rule: dict[str, Any] = {
            "enabled": rule["enabled"],
            "locks": [self._by_entity_id(entity).id for entity in rule["locks"] if self._by_entity_id(entity)],
            "modes": list(dict.fromkeys(rule["modes"])),
        }
        self.codes: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.locks")
        self._by_id = {lock.id: lock for lock in self.locks}
        self._listeners: list[Callable[[], None]] = []
        self._cancels: list[CALLBACK_TYPE] = []
        self._cancel_expiry: CALLBACK_TYPE | None = None
        self._close_timers: dict[str, CALLBACK_TYPE] = {}
        self._open_timers: dict[str, CALLBACK_TYPE] = {}
        self._heard: dict[str, datetime] = {}
        self._origins: dict[str, tuple[str, datetime]] = {}
        self._disarmed: dict[str, datetime] = {}

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._apply(await self._store.async_load() or {})
        entities = [lock.entity for lock in self.locks] + [lock.sensor for lock in self.locks if lock.sensor]
        self._cancels.append(async_track_state_change_event(self.hass, entities, self._state_changed))
        self._cancels.append(self.hass.bus.async_listen(EVENT_ZWAVE, self._zwave_notification))
        await self._async_expire(None)

    async def async_stop(self, _event=None) -> None:
        for cancel in self._cancels:
            cancel()
        self._cancels = []
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None
        for cancel in self._close_timers.values():
            cancel()
        self._close_timers = {}
        for cancel in self._open_timers.values():
            cancel()
        self._open_timers = {}
        await self._store.async_save(self._saved())

    # --- storage ------------------------------------------------------------

    def _apply(self, saved: dict) -> None:
        codes = []
        for item in saved.get("codes", []):
            try:
                codes.append(
                    {
                        "id": str(item["id"]),
                        "slot": int(item["slot"]),
                        "name": str(item["name"]),
                        "type": "temporary" if item.get("type") == "temporary" else "fixed",
                        "code": str(item["code"]),
                        "locks": [lock for lock in item.get("locks", []) if lock in self._by_id],
                        "expires": item.get("expires"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        self.codes = codes
        self.events = [event for event in saved.get("events", []) if isinstance(event, dict)][:MAX_EVENTS]
        rule = saved.get("rule")
        if isinstance(rule, dict):
            self._set_rule(**{key: rule[key] for key in ("enabled", "locks", "modes") if key in rule})
        for event in self.events:
            if event.get("kind") in KINDS_OPEN and (when := dt_util.parse_datetime(event.get("time", ""))):
                if self.last_open is None or when > self.last_open:
                    self.last_open = when

    def _saved(self) -> dict[str, Any]:
        return {
            "codes": [dict(code) for code in self.codes],
            "events": list(self.events),
            "rule": {key: self.rule[key] for key in ("enabled", "locks", "modes")},
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._saved, 2)
        self.notify()

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

    # --- helpers ------------------------------------------------------------

    def _by_entity_id(self, entity: str) -> _Lock | None:
        return next((lock for lock in self.locks if lock.entity == entity), None)

    def lock_for_entity(self, entity: str) -> _Lock:
        lock = self._by_entity_id(entity) or self._by_id.get(entity)
        if lock is None:
            raise CodeError("unknown_lock", lock=entity)
        return lock

    def _text(self, key: str, **values) -> str:
        language = str(self.hass.config.language or "en").split("-")[0].lower()
        return TEXTS.get(language, TEXTS["en"]).get(key, TEXTS["en"][key]).format(**values)

    def _code_of_slot(self, slot: int) -> dict[str, Any] | None:
        return next((code for code in self.codes if code["slot"] == slot), None)

    # --- codes --------------------------------------------------------------

    def _check_new_code(self, code: str) -> None:
        if code.endswith("0"):
            raise CodeError("emergency_ending")
        for other in self.codes:
            if (
                other["code"] == code
                or emergency_code(other["code"]) == code
                or emergency_code(code) == other["code"]
                # Two codes that differ only in the last digit would share an emergency code.
                or emergency_code(other["code"]) == emergency_code(code)
            ):
                raise CodeError("code_taken")

    def _free_slot(self) -> int:
        used = {code["slot"] for code in self.codes}
        for slot in range(1, self.slots + 1):
            if slot not in used:
                return slot
        raise CodeError("no_free_slot")

    def _expiry(self, hours: int | None, until: str | None) -> datetime:
        now = dt_util.utcnow()
        if until:
            when = dt_util.parse_datetime(until)
            if when is None:
                raise CodeError("invalid_expiry")
            when = dt_util.as_utc(when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone()))
        elif hours:
            when = now + timedelta(hours=hours)
        else:
            raise CodeError("invalid_expiry")
        if when <= now or when > now + timedelta(hours=MAX_TEMP_HOURS):
            raise CodeError("invalid_expiry")
        return when

    async def _call(self, service: str, **data) -> None:
        await self.hass.services.async_call("zwave_js", service, data, blocking=True)

    async def _program(self, lock: _Lock, slot: int, code: str) -> None:
        await self._call("set_lock_usercode", entity_id=lock.entity, code_slot=slot, usercode=code)
        await self._call(
            "set_lock_usercode", entity_id=lock.entity, code_slot=slot + self.offset, usercode=emergency_code(code)
        )

    async def _clear(self, lock: _Lock, slot: int) -> None:
        await self._call("clear_lock_usercode", entity_id=lock.entity, code_slot=slot)
        await self._call("clear_lock_usercode", entity_id=lock.entity, code_slot=slot + self.offset)

    async def async_add_code(
        self,
        name: str,
        kind: str = "fixed",
        code: str | None = None,
        lock_ids: list[str] | None = None,
        hours: int | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        name = " ".join(str(name).split())
        if not name:
            raise CodeError("name_required")
        if kind not in ("fixed", "temporary"):
            raise CodeError("unknown_type")
        locks = [self.lock_for_entity(item) for item in (lock_ids or [lock.id for lock in self.locks])]
        if not locks:
            raise CodeError("unknown_lock", lock="")
        code = random_code() if code in (None, "") else _digits(code)
        self._check_new_code(code)
        expires = self._expiry(hours, until) if kind == "temporary" else None
        slot = self._free_slot()

        done: list[_Lock] = []
        try:
            for lock in locks:
                await self._program(lock, slot, code)
                done.append(lock)
        except HomeAssistantError:
            for lock in done:  # take back what was already programmed
                try:
                    await self._clear(lock, slot)
                except HomeAssistantError:
                    _LOGGER.warning("Annika locks: could not clear slot %s of %s", slot, lock.entity)
            raise

        item = {
            "id": uuid.uuid4().hex[:8],
            "slot": slot,
            "name": name,
            "type": kind,
            "code": code,
            "locks": [lock.id for lock in locks],
            "expires": _iso(expires),
        }
        self.codes.append(item)
        self._schedule_expiry()
        self._changed()
        return item

    async def _read_slot(self, lock: _Lock, slot: int) -> str | None:
        """The code a lock holds in a slot, or None when the slot is empty (or the lock does not answer)."""

        try:
            result = await self.hass.services.async_call(
                "zwave_js",
                "get_lock_usercode",
                {"entity_id": lock.entity, "code_slot": slot},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as error:
            _LOGGER.warning("Annika locks: could not read slot %s of %s: %s", slot, lock.entity, error)
            return None
        info = ((result or {}).get(lock.entity) or {}).get(str(slot)) or {}
        code = str(info.get("usercode") or "").strip()
        return code if info.get("in_use") and re.fullmatch(r"\d{4,8}", code) else None

    async def async_import_codes(self) -> int:
        """Adopt the codes the locks already hold in Annika's slots, which the list does not know.

        A lock cannot tell who a code is for, so each one comes in named after its slot (rename it
        after). The same code in the same slot of several locks is one code. A slot that holds
        different codes in different locks, or a code Annika could not keep as it keeps its own (it
        ends in 0, or it is too close to another), is left alone. What is missing is the emergency
        code: it is programmed beside it. Returns how many codes came in.
        """

        known = {code["slot"] for code in self.codes}
        found: dict[int, dict[str, list[_Lock]]] = {}
        for slot in range(1, self.slots + 1):
            if slot in known:
                continue
            for lock in self.locks:
                if (code := await self._read_slot(lock, slot)) is not None:
                    found.setdefault(slot, {}).setdefault(code, []).append(lock)
        imported = 0
        for slot, by_code in found.items():
            if len(by_code) != 1:
                _LOGGER.warning("Annika locks: slot %s holds different codes in different locks, not imported", slot)
                continue
            (code, locks), = by_code.items()
            try:
                self._check_new_code(code)
            except CodeError:
                _LOGGER.warning("Annika locks: the code in slot %s cannot be kept by Annika, not imported", slot)
                continue
            for lock in locks:
                if await self._read_slot(lock, slot + self.offset) != emergency_code(code):
                    try:
                        await self._call(
                            "set_lock_usercode",
                            entity_id=lock.entity,
                            code_slot=slot + self.offset,
                            usercode=emergency_code(code),
                        )
                    except HomeAssistantError as error:
                        _LOGGER.warning("Annika locks: could not set the emergency code of slot %s: %s", slot, error)
            self.codes.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "slot": slot,
                    "name": self._text("imported_name", slot=slot),
                    "type": "fixed",
                    "code": code,
                    "locks": [lock.id for lock in locks],
                    "expires": None,
                }
            )
            imported += 1
        if imported:
            self.codes.sort(key=lambda item: item["slot"])
            self._changed()
        return imported

    async def async_rename_code(self, code_id: str, name: str) -> None:
        item = next((code for code in self.codes if code["id"] == str(code_id)), None)
        if item is None:
            raise CodeError("unknown_code")
        name = str(name).strip()
        if not name:
            raise CodeError("name_required")
        item["name"] = name
        self._changed()

    async def async_delete_code(self, code_id: str) -> None:
        item = next((code for code in self.codes if code["id"] == str(code_id)), None)
        if item is None:
            raise CodeError("unknown_code")
        failed = False
        for lock_id in item["locks"]:
            try:
                await self._clear(self._by_id[lock_id], item["slot"])
            except HomeAssistantError:
                _LOGGER.warning("Annika locks: could not clear slot %s of %s", item["slot"], lock_id)
                failed = True
        if failed:
            # Still in the lock: keep it in the list so the person sees it and can try again.
            raise HomeAssistantError(f"Could not remove the code {item['name']} from every lock")
        self.codes.remove(item)
        self._schedule_expiry()
        self._changed()

    # --- expiry -------------------------------------------------------------

    def _schedule_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None
        times = [when for code in self.codes if (when := dt_util.parse_datetime(code.get("expires") or ""))]
        if times:
            self._cancel_expiry = async_track_point_in_time(self.hass, self._async_expire, min(times))

    async def _async_expire(self, _now) -> None:
        now = dt_util.utcnow()
        retry = False
        for item in list(self.codes):
            when = dt_util.parse_datetime(item.get("expires") or "")
            if when is None or when > now:
                continue
            try:
                await self.async_delete_code(item["id"])
            except HomeAssistantError:
                retry = True
                continue
            self._log("expired", None, who=item["name"], slot=item["slot"])
        self._schedule_expiry()
        if retry:
            # A lock that could not be reached: the code is still in it, try again soon.
            self._cancel_expiry = async_call_later(self.hass, EXPIRY_RETRY, self._async_expire)

    # --- activity -----------------------------------------------------------

    def _log(self, kind: str, lock: _Lock | None, **values: Any) -> dict[str, Any]:
        event = {
            "time": dt_util.utcnow().isoformat(),
            "lock": lock.id if lock else None,
            "kind": kind,
            "how": values.pop("how", None),
            "who": values.pop("who", None),
            "slot": values.pop("slot", None),
            "disarmed": values.pop("disarmed", False),
            "notified": values.pop("notified", False),
        }
        self.events.insert(0, event)
        del self.events[MAX_EVENTS:]
        if kind in KINDS_OPEN:
            self.last_open = dt_util.utcnow()
        if lock is not None and event["who"] and kind in LOGBOOK_VERBS:
            self.hass.bus.async_fire(
                "logbook_entry",
                {
                    "name": lock.name,
                    "message": f"{LOGBOOK_VERBS[kind]} por {event['who']}",
                    "entity_id": lock.entity,
                    "domain": DOMAIN,
                },
            )
        self._changed()
        return event

    def _recent_event(self, lock: _Lock, kinds: tuple[str, ...]) -> dict[str, Any] | None:
        now = dt_util.utcnow()
        for event in self.events:
            when = dt_util.parse_datetime(event["time"])
            if when is None or (now - when).total_seconds() > SAME_OPENING:
                return None
            if event["lock"] == lock.id and event["kind"] in kinds:
                return event
        return None

    # --- who opened: Z-Wave, the app and Annika itself ------------------------

    def _device_id(self, lock: _Lock) -> str | None:
        entry = er.async_get(self.hass).async_get(lock.entity)
        return entry.device_id if entry else None

    def _lock_of_device(self, device_id: str | None) -> _Lock | None:
        if not device_id:
            return None
        return next((lock for lock in self.locks if self._device_id(lock) == device_id), None)

    def _origin(self, lock: _Lock, direction: str) -> tuple[str, str | None] | None:
        """How an opening or closing that Z-Wave did not describe came about: Annika's own lock or the app."""

        now = dt_util.utcnow()
        marker = self._origins.get(lock.id)
        if marker and (now - marker[1]).total_seconds() <= ORIGIN_WINDOW:
            return (marker[0], None)
        last = (self.hass.data.get(DATA_ACTOR) or {}).get("last_action")
        action = last.action if last is not None else None
        if (
            action is not None
            and action.domain == "lock"
            and action.service in (("unlock", "open") if direction == "unlock" else ("lock",))
            and lock.entity in action.entity_ids
            and (now - action.at).total_seconds() <= ORIGIN_WINDOW
        ):
            return ("app", action.actor.name)
        return None

    @callback
    def _zwave_notification(self, event: Event) -> None:
        data = event.data
        lock = self._lock_of_device(data.get("device_id"))
        if lock is None:
            return
        what = ZWAVE_EVENTS.get(data.get("event"))
        if what is None:
            label = str(data.get("event_label") or "").lower()
            what = next((value for key, value in ZWAVE_LABELS if key in label), None)
        if what is None:
            return
        direction, how = what
        self._heard[lock.id] = dt_util.utcnow()
        who: str | None = None
        slot: int | None = None
        kind = direction
        if how == "keypad":
            try:
                slot = int((data.get("parameters") or {}).get("userId"))
            except (TypeError, ValueError):
                slot = None
            who, kind = self._who_of_slot(slot, direction)
        elif how == "remote":
            origin = self._origin(lock, direction)
            how, who = origin if origin else ("remote", None)
        self._record(lock, direction, kind, how, who, slot)

    def _who_of_slot(self, slot: int | None, direction: str) -> tuple[str | None, str]:
        """The name behind a keypad slot, and what kind of event it is."""

        if slot is None:
            return None, direction
        item = self._code_of_slot(slot)
        if item is not None:
            return item["name"], direction
        if slot > self.offset and (item := self._code_of_slot(slot - self.offset)) is not None:
            return item["name"], "emergency" if direction == "unlock" else direction
        return None, "unknown" if direction == "unlock" else direction

    def _record(
        self, lock: _Lock, direction: str, kind: str, how: str, who: str | None, slot: int | None
    ) -> None:
        disarmed = False
        if kind in KINDS_OPEN:
            marked = self._disarmed.get(lock.id)
            disarmed = marked is not None and (dt_util.utcnow() - marked).total_seconds() <= SAME_OPENING
        event = self._log(kind, lock, how=how, who=who, slot=slot, disarmed=disarmed)
        if kind == "emergency":
            event["notified"] = self._emergency(lock, who or "")

    def _emergency(self, lock: _Lock, who: str) -> bool:
        if not self.notify_view:
            _LOGGER.warning("Annika locks: the emergency code was used at %s but notify_view is not configured", lock.name)
            return False
        self.hass.async_create_task(
            self._async_send(
                {
                    "type": "security",
                    "title": self._text("emergency_title"),
                    "message": self._text("emergency_message", who=who or "?", lock=lock.name),
                    "view": self.notify_view,
                    **({"actor": who} if who else {}),
                }
            )
        )
        return True

    async def _async_send(self, event: dict[str, Any]) -> None:
        try:
            await AnnikaEventClient(self.hass).async_send({"eventId": str(uuid.uuid4()), **event})
        except Exception:  # noqa: BLE001 — a missed notification must not break the door
            _LOGGER.warning("Annika locks: could not send the notification %s", event.get("title"))

    # --- the doors ----------------------------------------------------------

    @callback
    def _state_changed(self, event: Event) -> None:
        entity = event.data["entity_id"]
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or old is None or new.state == old.state:
            return
        lock = self._by_entity_id(entity)
        if lock is not None:
            self._lock_changed(lock, new.state)
            return
        door = next((lock for lock in self.locks if lock.sensor == entity), None)
        if door is not None:
            self._door_changed(door, new.state, old.state)

    def _lock_changed(self, lock: _Lock, state: str) -> None:
        self._cancel_close(lock)
        if state == "unlocked":
            self._disarm_alarm(lock)
        if state in ("locked", "unlocked"):
            direction = "unlock" if state == "unlocked" else "lock"
            at = dt_util.utcnow()

            @callback
            def unheard(_now) -> None:
                self._unheard(lock, direction, at)

            async_call_later(self.hass, ZWAVE_WAIT, unheard)
        self.notify()

    @callback
    def _unheard(self, lock: _Lock, direction: str, at: datetime) -> None:
        """A lock that changed and Z-Wave said nothing about: the app, Annika, or a fingerprint."""

        heard = self._heard.get(lock.id)
        if heard is not None and (heard - at).total_seconds() > -SAME_OPENING:
            return
        origin = self._origin(lock, direction)
        how, who = origin if origin else ("unknown", None)
        self._record(lock, direction, direction, how, who, None)

    # --- the alarm ----------------------------------------------------------

    def _disarm_alarm(self, lock: _Lock) -> None:
        rule = self.rule
        if not rule["enabled"] or (rule["locks"] and lock.id not in rule["locks"]):
            return
        panel = self.hass.data.get(DATA_ALARM_PANEL)
        if panel is None or not (panel.armed or panel.state == "pending"):
            return
        if rule["modes"] and panel.mode not in rule["modes"]:
            return
        panel.disarm(skip_code=True, source="locks")
        now = dt_util.utcnow()
        self._disarmed[lock.id] = now
        event = self._recent_event(lock, KINDS_OPEN)
        if event is not None:
            event["disarmed"] = True
        self._changed()

    def _set_rule(
        self,
        enabled: bool | None = None,
        locks: list[str] | None = None,
        modes: list[str] | None = None,
    ) -> None:
        if enabled is not None:
            self.rule["enabled"] = bool(enabled)
        if locks is not None:
            self.rule["locks"] = [lock.id for lock in (self.lock_for_entity(item) for item in dict.fromkeys(locks))]
        if modes is not None:
            if any(mode not in MODES for mode in modes):
                raise CodeError("invalid_mode")
            self.rule["modes"] = list(dict.fromkeys(modes))

    def set_rule(self, **values) -> None:
        self._set_rule(**values)
        self._changed()

    def test_rule(self) -> None:
        """Put a test line in the activity, without touching the alarm or a lock."""

        lock = next((self._by_id[item] for item in self.rule["locks"] if item in self._by_id), self.locks[0])
        self._log("test", lock, how="test")

    # --- lock when closed ---------------------------------------------------

    def _cancel_close(self, lock: _Lock) -> None:
        cancel = self._close_timers.pop(lock.id, None)
        if cancel is not None:
            cancel()

    def _door_changed(self, lock: _Lock, new: str, old: str) -> None:
        if new == "on":
            self._cancel_close(lock)
            self._arm_open(lock)
        elif new == "off":
            self._cancel_open(lock)
            if old == "on":
                self._arm_close(lock)

    def _arm_close(self, lock: _Lock) -> None:
        """The door just closed: lock it after the lock's number of seconds, if it asks for that."""

        self._cancel_close(lock)
        state = self.hass.states.get(lock.entity)
        if not lock.close_enabled or state is None or state.state != "unlocked":
            return

        @callback
        def fire(_now) -> None:
            self.hass.async_create_task(self._async_close(lock))

        self._close_timers[lock.id] = async_call_later(self.hass, lock.close_seconds, fire)

    async def _async_close(self, lock: _Lock) -> None:
        self._close_timers.pop(lock.id, None)
        door = self.hass.states.get(lock.sensor) if lock.sensor else None
        state = self.hass.states.get(lock.entity)
        if not lock.close_enabled or door is None or door.state != "off" or state is None or state.state != "unlocked":
            return
        self._origins[lock.id] = ("close", dt_util.utcnow())
        try:
            await self.hass.services.async_call("lock", "lock", {"entity_id": lock.entity}, blocking=True)
        except HomeAssistantError as error:
            self._origins.pop(lock.id, None)
            _LOGGER.warning("Annika locks: could not lock %s after the door closed: %s", lock.entity, error)

    # --- notify when the door stays open ------------------------------------

    def _cancel_open(self, lock: _Lock) -> None:
        cancel = self._open_timers.pop(lock.id, None)
        if cancel is not None:
            cancel()

    def _arm_open(self, lock: _Lock) -> None:
        """The door just opened: say so if it is still open after the lock's number of seconds."""

        self._cancel_open(lock)
        if not lock.open_enabled:
            return

        @callback
        def fire(_now) -> None:
            self.hass.async_create_task(self._async_left_open(lock))

        self._open_timers[lock.id] = async_call_later(self.hass, lock.open_seconds, fire)

    @staticmethod
    def _duration(seconds: int) -> str:
        return f"{seconds} s" if seconds < 120 else f"{round(seconds / 60)} min"

    async def _async_left_open(self, lock: _Lock) -> None:
        self._open_timers.pop(lock.id, None)
        door = self.hass.states.get(lock.sensor) if lock.sensor else None
        if not lock.open_enabled or door is None or door.state != "on":
            return
        notified = bool(self.notify_view)
        self._log("left_open", lock, how="door", notified=notified)
        if notified:
            await self._async_send(
                {
                    "type": "info",
                    "title": self._text("left_open_title"),
                    "message": self._text(
                        "left_open_message", lock=lock.name, time=self._duration(lock.open_seconds)
                    ),
                    "view": self.notify_view,
                }
            )

    def set_lock_settings(
        self,
        lock: _Lock,
        hold: bool | None = None,
        close_enabled: bool | None = None,
        close_seconds: int | None = None,
        open_enabled: bool | None = None,
        open_seconds: int | None = None,
    ) -> None:
        """What the entities of a lock write; the card and the timers read it from here."""

        if hold is not None:
            lock.hold = bool(hold)
        if close_enabled is not None:
            lock.close_enabled = bool(close_enabled)
            if not lock.close_enabled:
                self._cancel_close(lock)
        if close_seconds is not None:
            lock.close_seconds = max(CLOSE_MIN_SECONDS, min(CLOSE_MAX_SECONDS, int(close_seconds)))
        if open_seconds is not None:
            lock.open_seconds = max(OPEN_MIN_SECONDS, min(OPEN_MAX_SECONDS, int(open_seconds)))
        if open_enabled is not None:
            lock.open_enabled = bool(open_enabled)
            if not lock.open_enabled:
                self._cancel_open(lock)
            elif (door := self.hass.states.get(lock.sensor) if lock.sensor else None) and door.state == "on":
                # Turned on with the door already open: the count starts now.
                self._arm_open(lock)
        self.notify()

    # --- what the card reads ------------------------------------------------

    def _entity_ids(self, lock: _Lock) -> dict[str, str | None]:
        registry = er.async_get(self.hass)
        return {
            "hold": registry.async_get_entity_id("switch", DOMAIN, f"{DOMAIN}_lock_{lock.id}_hold"),
            "close": registry.async_get_entity_id("switch", DOMAIN, f"{DOMAIN}_lock_{lock.id}_close"),
            "seconds": registry.async_get_entity_id("number", DOMAIN, f"{DOMAIN}_lock_{lock.id}_close_seconds"),
            "open": registry.async_get_entity_id("switch", DOMAIN, f"{DOMAIN}_lock_{lock.id}_open"),
            "open_seconds": registry.async_get_entity_id("number", DOMAIN, f"{DOMAIN}_lock_{lock.id}_open_seconds"),
        }

    def attributes(self) -> dict[str, Any]:
        panel = self.hass.data.get(DATA_ALARM_PANEL)
        return {
            "config": {
                "notification": bool(self.notify_view),
                "slots": self.slots,
                "offset": self.offset,
                "rule": {**self.rule, "available": panel is not None},
                "modes": list(panel.enabled_modes) if panel is not None else list(MODES),
                "locks": [
                    {
                        "id": lock.id,
                        "name": lock.name,
                        "entity": lock.entity,
                        "sensor": lock.sensor,
                        "battery": lock.battery,
                        "settings": {
                            "hold": lock.hold,
                            "close": lock.close_enabled,
                            "seconds": lock.close_seconds,
                            "open": lock.open_enabled,
                            "open_seconds": lock.open_seconds,
                        },
                        "entities": self._entity_ids(lock),
                    }
                    for lock in self.locks
                ],
            },
            "codes": [dict(code) for code in self.codes],
            "events": [dict(event) for event in self.events],
        }
