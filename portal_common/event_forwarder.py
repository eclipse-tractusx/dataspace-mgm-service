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
"""Outbound delivery of events to other runtimes (FRAMEWORK 6, ADR-0002).

Inside a process the relay delivers events in memory. When modules run as separate pods, the events a
module publishes must also reach the others: `EVENT_SINKS` lists the base addresses of the other
runtimes (comma separated, e.g. `http://c3-m1:8000`). Every locally published CloudEvent is posted to
`<sink>/api/v1/events/inbox` (CloudEvents HTTP binding, structured mode) with the service token of the
publishing module (`svc-<module>`).

- Off the request path: `publish` only enqueues; worker threads deliver, so a slow peer never slows a request.
- At least once: retries with exponential backoff; the inbox deduplicates by `source` and `id`.
- Bounded: a full queue drops the oldest event and counts it in `dropped` (a broker with a durable outbox
  is the next step, see ADR-0002).
- Events received through the inbox are never forwarded again (no loops).
- Connection pooling: one keep-alive `httpx.Client` for all deliveries.
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time

import httpx

from . import tokens

log = logging.getLogger("portal.events.forwarder")
INBOX_PATH = "/api/v1/events/inbox"
STRUCTURED = "application/cloudevents+json"
RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0, 5.0)   # seconds before attempt 2..6
QUEUE_MAX = 10_000
WORKERS = 2


def sinks() -> list[str]:
    return [s.strip().rstrip("/") for s in os.environ.get("EVENT_SINKS", "").split(",") if s.strip()]


class Forwarder:
    def __init__(self) -> None:
        self._queue: collections.deque[dict] = collections.deque()
        self._cv = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._stop = False
        self._client: httpx.Client | None = None
        self._pending = 0
        self.dropped = 0
        self.failures: list[dict] = []

    def submit(self, event: dict) -> None:
        if not sinks():
            return
        with self._cv:
            if len(self._queue) >= QUEUE_MAX:
                self._queue.popleft()
                self.dropped += 1
                self._pending -= 1
            self._queue.append(event)
            self._pending += 1
            self._cv.notify()
        self._ensure_started()

    def _ensure_started(self) -> None:
        with self._cv:
            if self._threads and all(t.is_alive() for t in self._threads):
                return
            self._stop = False
            if self._client is None:
                self._client = httpx.Client(timeout=5.0, limits=httpx.Limits(max_keepalive_connections=20))
            self._threads = [threading.Thread(target=self._loop, name=f"event-forwarder-{i}", daemon=True)
                             for i in range(WORKERS)]
            for t in self._threads:
                t.start()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stop:
                    self._cv.wait()
                if self._stop and not self._queue:
                    return
                event = self._queue.popleft()
            try:
                self._send_all(event)
            finally:
                with self._cv:
                    self._pending -= 1
                    self._cv.notify_all()

    def _send_all(self, event: dict) -> None:
        module = event["source"].removeprefix("urn:")
        for sink in sinks():
            self._send(sink, module, event)

    def _send(self, sink: str, module: str, event: dict) -> None:
        error = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                r = self._client.post(sink + INBOX_PATH, json=event, headers={
                    "Content-Type": STRUCTURED, "Authorization": "Bearer " + tokens.service_token(module)})
                if r.status_code == 202:
                    return
                error = f"HTTP {r.status_code}"
                if 400 <= r.status_code < 500 and r.status_code not in (401, 408, 429):
                    break   # the peer rejects the event itself; a retry cannot help
            except Exception as exc:  # noqa: BLE001 - network or token errors are retried
                error = repr(exc)
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
        self.failures.append({"sink": sink, "id": event["id"], "type": event["type"], "error": error})
        log.error("event %s %s not delivered to %s: %s", event["type"], event["id"], sink, error)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: self._pending <= 0, timeout)

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def reset(self) -> None:
        with self._cv:
            self._pending -= len(self._queue)
            self._queue.clear()
            self.failures.clear()
            self.dropped = 0


FORWARDER = Forwarder()
