#################################################################################
#  Copyright (c) 2026 Contributors to the Eclipse Foundation
#
#  See the NOTICE file(s) distributed with this work for additional
#  information regarding copyright ownership.
#
#  This program and the accompanying materials are made available under the
#  terms of the Apache License, Version 2.0 which is available at
#  https://www.apache.org/licenses/LICENSE-2.0.
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.
#
#  AI Disclosure: This file was entirely AI-generated.
#  The AI-generated portions are made available under CC0-1.0 and not subject
#  to the project's license. The human contributor has reviewed and verified
#  that the code is correct.
#
#  SPDX-License-Identifier: Apache-2.0 AND CC0-1.0
#  Assisted-By: Claude Code (claude-opus-5-5)
#################################################################################
"""Event relay of an installation: stand-in for "outbox per module + relay" (FRAMEWORK 1).

Every event is a CloudEvent (CloudEvents 1.0, JSON event format, FRAMEWORK 6):

    {"specversion": "1.0", "id": "<uuid>", "source": "urn:c1-m2", "type": "ApplicationSubmitted",
     "time": "2026-11-06T09:30:00+00:00", "datacontenttype": "application/json",
     "data": {"applicationId": "...", "companyId": "...", ...}}

`publish(module, type, data)` builds the CloudEvent, only puts it into the outbox and returns it at
once; a relay thread delivers it to every subscriber. A request therefore never runs another
module's reaction (no synchronous bus, no deadlock), and an exception in one subscriber is logged
in `failures` without stopping delivery to the others. Subscribers receive the CloudEvent: the
name is `event["type"]`, the content of FRAMEWORK 6 is in `event["data"]`.

`receive(event)` takes a CloudEvent that arrived over HTTP (event inbox `POST /api/v1/events/inbox`,
FRAMEWORK 6): checked with `validate()`, put into the outbox unchanged (same `id` and `time`), and
delivered once per `source` and `id`.

Without `start()` (unit tests) nothing is delivered until `drain()` is called.
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
import re
import sys
import threading
import traceback
import uuid
import warnings
from collections.abc import Callable

from .event_forwarder import FORWARDER

log = logging.getLogger("portal.events")
FORBIDDEN_KEYS = ("secret", "password", "apikey", "token")
SPECVERSION = "1.0"
DATACONTENTTYPE = "application/json"
ATTRIBUTES = ("specversion", "id", "source", "type", "time", "datacontenttype", "data")
_MODULE_ID = re.compile(r"c[0-9]+-m[0-9]+")
_TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
_SOURCE = re.compile(r"urn:(c[0-9]+-m[0-9]+)")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
RECEIVED_MAX = 10_000   # (source, id) pairs the inbox remembers to deliver a repeated event only once
_warned: set[tuple[str, str]] = set()


def _secret_keys(value: object, path: str = "") -> list[str]:
    """Keys that look like secrets, also in nested objects and lists (FRAMEWORK 4.6)."""
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            here = f"{path}.{k}" if path else str(k)
            if any(f in str(k).lower() for f in FORBIDDEN_KEYS):
                out.append(here)
            out += _secret_keys(v, here)
        return out
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in _secret_keys(v, f"{path}[{i}]")]
    return []


def source_of(module: str) -> str:
    """`source` of the events of a module (FRAMEWORK 6): `urn:<module>`, e.g. `urn:c1-m2`."""
    if not isinstance(module, str) or not _MODULE_ID.fullmatch(module):
        raise ValueError(f"module identifier like 'c1-m2' expected, got {module!r}")
    return f"urn:{module}"


def cloudevent(module: str, type: str, data: dict | None = None, *, id: str | None = None,  # noqa: A002
               time: str | None = None) -> dict:
    """Builds a CloudEvent of FRAMEWORK 6 without publishing it (also for tests that feed a consumer)."""
    if not isinstance(type, str) or not _TYPE.fullmatch(type):
        raise ValueError(f"event type in PascalCase expected (FRAMEWORK 6), got {type!r}")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"data of {type} must be a JSON object")
    bad = _secret_keys(data)
    if bad:
        raise ValueError(f"events never carry secrets (FRAMEWORK 4.6): {bad}")
    return {"specversion": SPECVERSION, "id": id or str(uuid.uuid4()), "source": source_of(module),
            "type": type, "time": time or dt.datetime.now(dt.UTC).isoformat(),
            "datacontenttype": DATACONTENTTYPE, "data": dict(data)}


def validate(event: object) -> dict:
    """Checks a CloudEvent from outside the process against FRAMEWORK 6 and returns it as
    `cloudevent()` builds it. ValueError names the first attribute that is missing or wrong."""
    if not isinstance(event, dict):
        raise ValueError("a CloudEvent is a JSON object")
    extra = sorted(set(event) - set(ATTRIBUTES))
    if extra:
        raise ValueError(f"attributes not allowed (FRAMEWORK 6: no other attributes, no extensions): {extra}")
    missing = [a for a in ATTRIBUTES if a not in event]
    if missing:
        raise ValueError(f"attributes missing: {missing}")
    if event["specversion"] != SPECVERSION:
        raise ValueError(f"specversion {SPECVERSION!r} expected, got {event['specversion']!r}")
    if event["datacontenttype"] != DATACONTENTTYPE:
        raise ValueError(f"datacontenttype {DATACONTENTTYPE!r} expected, got {event['datacontenttype']!r}")
    if not isinstance(event["id"], str) or not _UUID.fullmatch(event["id"]):
        raise ValueError(f"id must be a UUID, got {event['id']!r}")
    m = _SOURCE.fullmatch(event["source"]) if isinstance(event["source"], str) else None
    if not m:
        raise ValueError(f"source urn:<module> expected (e.g. urn:c1-m2), got {event['source']!r}")
    try:
        when = dt.datetime.fromisoformat(event["time"]) if isinstance(event["time"], str) else None
    except ValueError:
        when = None
    if when is None or when.utcoffset() is None:
        raise ValueError(f"time must be ISO 8601 with a time zone, got {event['time']!r}")
    if not isinstance(event["data"], dict):
        raise ValueError("data must be a JSON object")
    return cloudevent(m.group(1), event["type"], event["data"], id=event["id"], time=event["time"])


def _caller_module() -> str | None:
    """Module identifier of the code that called `publish` (for the transitional flat form)."""
    g = sys._getframe(2).f_globals   # 0: this function, 1: Relay.publish, 2: its caller
    if isinstance(g.get("MODULE"), str) and _MODULE_ID.fullmatch(g["MODULE"]):
        return g["MODULE"]
    m = re.match(r"modules\.(c[0-9]+)_(m[0-9]+)(\.|$)", g.get("__name__", ""))
    return f"{m.group(1)}-{m.group(2)}" if m else None


class Relay:
    def __init__(self) -> None:
        self._queue: collections.deque[dict] = collections.deque()
        self._cv = threading.Condition()
        self._subscribers: list[tuple[str, Callable[[dict], None]]] = []
        self._busy = False
        self._thread: threading.Thread | None = None
        self._stop = False
        self._received: collections.OrderedDict[tuple[str, str], None] = collections.OrderedDict()
        self.log: list[dict] = []
        self.failures: list[dict] = []

    def subscribe(self, name: str, handler: Callable[[dict], None]) -> None:
        self._subscribers.append((name, handler))

    def clear_subscribers(self) -> None:
        self._subscribers.clear()

    def publish(self, module: str | dict, type: str | None = None, data: dict | None = None) -> dict:  # noqa: A002
        """Publishes the event `type` of `module` with the content `data`; returns the CloudEvent.

        Transitional: the flat form of the first scaffold, `publish({"eventType": ..., **fields})`, is
        still accepted with a DeprecationWarning; its `source` is the module of the caller.
        """
        if isinstance(module, dict):
            flat = dict(module)
            etype = flat.pop("eventType", None)
            if not etype:
                raise ValueError("event without eventType")
            event_id, occurred_at = flat.pop("eventId", None), flat.pop("occurredAt", None)
            caller = _caller_module()
            if caller is None:
                raise ValueError("use events.publish(module, type, data): the module of the caller is unknown")
            warnings.warn("events.publish({'eventType': ...}) is deprecated; use events.publish(MODULE, type, data) "
                          "(FRAMEWORK 6, CloudEvents)", DeprecationWarning, stacklevel=2)
            if (caller, etype) not in _warned:   # Python hides DeprecationWarning outside __main__
                _warned.add((caller, etype))
                log.warning("%s publishes %s in the deprecated flat form; use events.publish(MODULE, type, data)",
                            caller, etype)
            ev = cloudevent(caller, etype, flat, id=event_id, time=occurred_at)
        else:
            ev = cloudevent(module, type, data)
        self._enqueue(ev)
        FORWARDER.submit(ev)   # to the other runtimes (EVENT_SINKS); nothing in a monolith
        return ev

    def receive(self, event: dict) -> tuple[dict, bool]:
        """Puts a CloudEvent received over HTTP (event inbox, FRAMEWORK 6) into the outbox unchanged.

        Returns the event and whether it is new; the same `source` and `id` again is delivered once.
        ValueError (from `validate`) if the event does not meet FRAMEWORK 6."""
        ev = validate(event)
        key = (ev["source"], ev["id"])
        with self._cv:
            if key in self._received:
                return ev, False
            self._received[key] = None
            if len(self._received) > RECEIVED_MAX:
                self._received.popitem(last=False)
        self._enqueue(ev)
        return ev, True

    def _enqueue(self, ev: dict) -> None:
        with self._cv:
            self.log.append(ev)
            self._queue.append(ev)
            self._cv.notify_all()

    def _deliver(self, ev: dict) -> None:
        for name, handler in list(self._subscribers):
            try:
                handler(ev)
            except Exception as exc:  # noqa: BLE001 - one subscriber must not stop the others
                self.failures.append({"subscriber": name, "id": ev["id"], "type": ev["type"], "error": repr(exc)})
                log.error("subscriber %s failed on %s: %s", name, ev["type"], "".join(traceback.format_exception(exc)))

    def _next(self, block: bool) -> dict | None:
        with self._cv:
            while block and not self._queue and not self._stop:
                self._cv.wait()
            if not self._queue:
                return None
            self._busy = True
            return self._queue.popleft()

    def _done(self) -> None:
        with self._cv:
            self._busy = False
            self._cv.notify_all()

    def drain(self) -> None:
        """Delivers everything queued, in the calling thread (for tests without the relay thread)."""
        while (ev := self._next(block=False)) is not None:
            try:
                self._deliver(ev)
            finally:
                self._done()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False

        def loop() -> None:
            while not self._stop:
                ev = self._next(block=True)
                if ev is None:
                    continue
                try:
                    self._deliver(ev)
                finally:
                    self._done()

        self._thread = threading.Thread(target=loop, name="event-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """True when the outbox is empty and no delivery is running."""
        with self._cv:
            return self._cv.wait_for(lambda: not self._queue and not self._busy, timeout)

    def reset(self) -> None:
        with self._cv:
            self._queue.clear()
            self._received.clear()
            self.log.clear()
            self.failures.clear()
        FORWARDER.reset()


RELAY = Relay()
publish = RELAY.publish
receive = RELAY.receive
subscribe = RELAY.subscribe
