"""Annika actor layer — which *app* user performed an action.

Home Assistant already records who called a service, but on an Annika unit
that answer is useless: every household member reaches this HA through the
Annika app's iframe, and the app signs them all in with one shared HA user.
`context.user_id` is therefore the same value for everybody.

The app knows who is looking at the screen. This layer is the channel that
carries that name across the iframe boundary and attaches it to the action:

    Annika app  --postMessage-->  annika-ha-bridge.js  (inside HA's origin)
                                          |
                                          |  annika/stamp_actor, sent on the
                                          |  same websocket immediately
                                          |  before the real call
                                          v
                                    stamp store  (this file)
                                          |
    any service call  --EVENT_CALL_SERVICE-->  matched against the store
                                          |
                              +-----------+-----------+
                              v                       v
                  sensor.annika_last_action     event: annika_action
                  (for templates)               (for triggers)

The stamp is a websocket command rather than a service call, and that is the
one part of this that is not interchangeable. Home Assistant hands each
incoming `call_service` message to its own task, so two of them sent
back-to-back on the same socket are not guaranteed to be *processed* in the
order they were sent — the stamp could land after the call it was meant to
describe, and then sit in the store until something else claimed it. A
`@callback` websocket command is dispatched synchronously, inline, before the
socket reads the next message. That makes the ordering free instead of costing
the bridge a round trip it would otherwise have to wait out before every
button press.

The stamp is matched on (domain, service, entity_id) and consumed once, so a
stamp can only ever be claimed by the call it was written for. Two people with
the app open do not collide: each iframe has its own bridge, each bridge
stamps its own calls, and the stamps queue independently. The one genuinely
ambiguous case is two people hitting the *same* service on the *same* entity
within the TTL below — and there both of them did it, so either name is true.

WHAT THIS IS NOT
----------------
This is informational attribution, not proof. The name is asserted by the
frontend, and anything holding a session on this HA can send the
`annika/stamp_actor` command with any name it likes. That is why every record
carries `actor_verified: false`. Use it to say "Delfi desarmó la alarma" in a
notification; do not use it to decide what someone is allowed to do. Making it
provable means the app signing a short-lived token that this integration
verifies against Annika's backend — a separate layer that would set
`actor_verified: true`, deliberately left for the day something depends on it.

An action with no matching stamp — a physical keypad, an automation, another
Home Assistant client — records nothing at all, which is what keeps the sensor
from quietly attributing those to whoever last used the app. See the freshness
guard documented on AnnikaLastAction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import voluptuous as vol

from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    EVENT_CALL_SERVICE,
)
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN

# Set on hass.data so the sensor platform reaches the same store.
DATA_ACTOR = f"{DOMAIN}_actor"

WS_TYPE_STAMP_ACTOR = f"{DOMAIN}/stamp_actor"
EVENT_ANNIKA_ACTION = f"{DOMAIN}_action"

ATTR_ACTOR_ID = "actor_id"
ATTR_ACTOR_NAME = "actor_name"
ATTR_ACTOR_VERIFIED = "actor_verified"
ATTR_AT = "at"

# How long a stamp stays claimable. The bridge sends it on the same websocket
# microseconds before the call it describes, so this only has to cover the
# round trip plus whatever queueing HA is doing — seconds, not minutes. Short
# on purpose: a stamp that outlives its call is a stamp that can be claimed by
# the wrong one.
STAMP_TTL = 8.0

# Nothing should ever accumulate stamps — each is consumed by the call right
# behind it, and the rest expire. This is the backstop for a client that
# stamps without ever calling: bounded memory, oldest dropped first.
MAX_STAMPS = 64

# Long enough for a real name, short enough that the attribute stays readable
# in the UI and in a push notification.
MAX_NAME_LENGTH = 64

# A Home Assistant state is capped at 255 characters.
MAX_STATE_LENGTH = 255


@dataclass(frozen=True)
class Actor:
    """Who the app says is acting."""

    name: str
    actor_id: str | None = None
    # Always False today — see the module docstring. Kept as a field rather
    # than a constant so the signed-token layer, if it ever lands, changes one
    # call site instead of every consumer.
    verified: bool = False


@dataclass
class ActorAction:
    """One attributed action."""

    actor: Actor
    domain: str
    service: str
    entity_ids: list[str]
    at: datetime

    @property
    def entity_id(self) -> str | None:
        """The entity this record is named after."""

        return self.entity_ids[0] if self.entity_ids else None

    @property
    def state(self) -> str:
        """What the sensor shows.

        The entity acted on, because that is what an automation compares
        against to decide whether this record is about the thing it just saw
        change. Service calls with no entity fall back to naming the service.
        """

        value = self.entity_id or f"{self.domain}.{self.service}"
        return value[:MAX_STATE_LENGTH]

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            ATTR_ACTOR_NAME: self.actor.name,
            ATTR_ACTOR_ID: self.actor.actor_id,
            ATTR_ACTOR_VERIFIED: self.actor.verified,
            "domain": self.domain,
            "service": self.service,
            ATTR_ENTITY_ID: self.entity_id,
            # Everything the call targeted. One press can name several
            # entities, and only the first becomes the state — a template
            # guarding on an entity that might be second should test this
            # instead: `'x' in state_attr(sensor, 'entity_ids')`.
            "entity_ids": list(self.entity_ids),
            ATTR_AT: self.at.isoformat(),
        }

    @property
    def event_data(self) -> dict[str, Any]:
        """Payload of the `annika_action` bus event.

        Deliberately the same keys as the attributes, so an automation reading
        `trigger.event.data.actor_name` and one reading
        `state_attr(..., 'actor_name')` are looking at the same field.
        """

        return dict(self.attributes)


def clean_name(value: Any) -> str | None:
    """A display name worth recording, or None."""

    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    if not name:
        return None
    return name[:MAX_NAME_LENGTH]


def entity_ids_from(data: Any) -> list[str]:
    """Every entity id a service call payload names.

    Home Assistant has moved entity ids around over the years — `entity_id`
    inside the service data, and a separate `target` block since the services
    rewrite — and what lands in the `call_service` event depends on both the
    version and how the caller phrased it. Read every shape rather than
    betting on one: a miss here means an action silently loses its actor.
    """

    if not isinstance(data, dict):
        return []

    found: list[str] = []
    sources = [data]
    target = data.get("target")
    if isinstance(target, dict):
        sources.append(target)

    for source in sources:
        value = source.get(ATTR_ENTITY_ID)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple, set)):
            found.extend(item for item in value if isinstance(item, str))

    # Sorted so the keys a stamp registers and the keys a call looks up are
    # built the same way from the same ids, whatever order they arrived in.
    return sorted({item for item in found if item})


@dataclass
class _Stamp:
    """One pending attribution, waiting for its call."""

    actor: Actor
    expires: float
    domain: str
    service: str
    # Empty when the caller named no entity — see the matching rules below.
    entity_ids: frozenset[str]


class ActorStamps:
    """Stamps waiting to be claimed by the service call they describe.

    The domain and the service always have to line up. Entity ids are the
    tie-breaker, and the rule there has two halves:

      - When both the stamp and the call name entities, they must overlap.
        Without this a stamp for light.kitchen would be handed to the next
        call on light.hall purely because both are `light.turn_on`, and with
        several sessions open that is a name attached to the wrong action.
      - When either side names none, domain and service are all there is to
        match on. This is the escape hatch for calls whose target does not
        survive to the bus event in the shape the bridge saw it — area and
        device targets, and whatever a future Home Assistant does with them.

    Overlapping matches are tried before falling back, so an exact hit always
    wins over a looser one. Consuming removes the whole stamp: a call naming
    three lights is one action, and leaving two behind would let the next call
    on either of them claim this actor.
    """

    def __init__(self, hass: HomeAssistant, ttl: float = STAMP_TTL) -> None:
        self.hass = hass
        self._ttl = ttl
        self._stamps: list[_Stamp] = []

    def _now(self) -> float:
        # Monotonic: a clock adjustment must not resurrect an expired stamp
        # or expire a live one.
        return time.monotonic()

    def _purge(self, now: float) -> None:
        self._stamps = [stamp for stamp in self._stamps if stamp.expires > now]

    @callback
    def stamp(
        self, actor: Actor, domain: str, service: str, entity_ids: list[str]
    ) -> None:
        """Record who is about to make this call."""

        now = self._now()
        self._purge(now)

        self._stamps.append(
            _Stamp(
                actor=actor,
                expires=now + self._ttl,
                domain=domain,
                service=service,
                entity_ids=frozenset(entity_ids),
            )
        )
        if len(self._stamps) > MAX_STAMPS:
            del self._stamps[: len(self._stamps) - MAX_STAMPS]

    @callback
    def consume(
        self, domain: str, service: str, entity_ids: list[str]
    ) -> Actor | None:
        """Claim the stamp for this call, if one is waiting.

        Oldest first: two sessions acting on the same entity queue up, and
        each call takes the stamp that was written before it.
        """

        now = self._now()
        self._purge(now)

        wanted = frozenset(entity_ids)

        for allow_fallback in (False, True):
            for index, stamp in enumerate(self._stamps):
                if stamp.domain != domain or stamp.service != service:
                    continue
                if stamp.entity_ids and wanted:
                    matched = bool(stamp.entity_ids & wanted)
                else:
                    matched = allow_fallback
                if matched:
                    del self._stamps[index]
                    return stamp.actor

        return None

    @property
    def pending(self) -> int:
        """Live stamps — for tests and diagnostics."""

        self._purge(self._now())
        return len(self._stamps)


class AnnikaLastAction:
    """The most recent attributed action, and who is listening for it.

    Only actions that carried a stamp land here. An action from a keypad, an
    automation or another Home Assistant client leaves this untouched, which
    is deliberate but means a template has to check *two* things before
    trusting the name: that the record is about the entity it cares about, and
    that it is recent. Without the freshness check, a disarm from the physical
    keypad would read back whoever last used the app, however long ago.
    """

    def __init__(self) -> None:
        self.action: ActorAction | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def record(self, action: ActorAction) -> None:
        self.action = action
        for listener in list(self._listeners):
            listener()


STAMP_ACTOR_SCHEMA = {
    vol.Required("type"): WS_TYPE_STAMP_ACTOR,
    vol.Required("name"): cv.string,
    vol.Optional("id"): vol.Any(cv.string, None),
    vol.Required("domain"): cv.string,
    vol.Required("service"): cv.string,
    # `cv.string`, not `cv.entity_id`: Home Assistant accepts targets this
    # validator would reject (the literal "all", and area or device targets
    # that only resolve to entities later), and a stamp that raises is a stamp
    # that takes the user's actual button press down with it.
    vol.Optional("entity_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
}


def async_setup_actor(hass: HomeAssistant) -> AnnikaLastAction:
    """Register the stamp command and start attributing service calls."""

    stamps = ActorStamps(hass)
    last_action = AnnikaLastAction()
    hass.data[DATA_ACTOR] = {"stamps": stamps, "last_action": last_action}

    # `@callback` outermost, the way Home Assistant's own commands are
    # written. It is what marks this as running inline on the socket's own
    # message loop rather than in a task, which is the entire reason the stamp
    # is a websocket command — see the module docstring.
    @callback
    @websocket_api.websocket_command(STAMP_ACTOR_SCHEMA)
    def handle_stamp_actor(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict
    ) -> None:
        """Record who is about to make the next call on this socket."""

        name = clean_name(msg.get("name"))
        if name:
            stamps.stamp(
                Actor(name=name, actor_id=msg.get("id") or None),
                str(msg["domain"]).lower(),
                str(msg["service"]).lower(),
                [str(item) for item in msg.get("entity_id", [])],
            )

        # Answered either way. A nameless stamp is the app telling us it does
        # not know who is looking at the screen, which is a fine thing to say
        # and not an error the bridge should have to handle.
        connection.send_result(msg["id"], {"stamped": bool(name)})

    websocket_api.async_register_command(hass, handle_stamp_actor)

    @callback
    def handle_call_service(event: Event) -> None:
        domain = event.data.get(ATTR_DOMAIN)
        service = event.data.get(ATTR_SERVICE)
        if not isinstance(domain, str) or not isinstance(service, str):
            return

        # Annika's own services are plumbing, not something a person did —
        # and `stamp_actor` itself arrives here, so without this the stamp
        # would try to claim itself.
        if domain == DOMAIN:
            return

        entity_ids = entity_ids_from(event.data.get(ATTR_SERVICE_DATA))
        actor = stamps.consume(domain, service, entity_ids)
        if actor is None:
            return

        action = ActorAction(
            actor=actor,
            domain=domain,
            service=service,
            # One record per action: a call naming several entities is still
            # one thing a person did.
            entity_ids=entity_ids,
            at=dt_util.utcnow(),
        )
        last_action.record(action)

        # Same context as the call, so the event and the state change it
        # describes stay linked in the logbook and in `trigger.context`.
        hass.bus.async_fire(
            EVENT_ANNIKA_ACTION, action.event_data, context=event.context
        )

    hass.bus.async_listen(EVENT_CALL_SERVICE, handle_call_service)

    return last_action
