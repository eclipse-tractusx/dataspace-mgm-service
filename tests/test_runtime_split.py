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
"""Runtime split (ADR-0002): module selection per pod and event delivery between pods."""
from __future__ import annotations

import httpx
import pytest

from portal_common import event_forwarder, events, tokens
from scaffold import registry


def test_registry_serves_only_enabled_modules(monkeypatch):
    monkeypatch.setenv("ENABLED_MODULES", "c1-m2, C3-M1")
    assert [e.id for e in registry.load()] == ["c1-m2", "c3-m1"]


def test_registry_serves_all_modules_by_default(monkeypatch):
    monkeypatch.delenv("ENABLED_MODULES", raising=False)
    assert {"c1-m2", "c3-m1", "c12-m1"} <= {e.id for e in registry.load()}


@pytest.fixture
def forwarder(monkeypatch):
    monkeypatch.setenv("EVENT_SINKS", "http://peer-a:8000/, http://peer-b:8000")
    monkeypatch.setattr(tokens, "service_token", lambda module: f"token-of-{module}")
    monkeypatch.setattr(event_forwarder, "RETRY_DELAYS", (0.01, 0.01))
    fw = event_forwarder.Forwarder()
    yield fw
    fw.stop()


def _use(fw, handler):
    fw._client = httpx.Client(transport=httpx.MockTransport(handler))


def test_event_is_posted_to_every_sink_with_the_service_token(forwarder):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["authorization"], request.headers["content-type"]))
        return httpx.Response(202)

    _use(forwarder, handler)
    ev = events.cloudevent("c1-m2", "ApplicationSubmitted", {"applicationId": "a"})
    forwarder.submit(ev)
    assert forwarder.wait_idle()
    assert sorted(seen) == [
        ("http://peer-a:8000/api/v1/events/inbox", "Bearer token-of-c1-m2", "application/cloudevents+json"),
        ("http://peer-b:8000/api/v1/events/inbox", "Bearer token-of-c1-m2", "application/cloudevents+json")]
    assert forwarder.failures == []


def test_transient_errors_are_retried_and_rejections_are_not(forwarder):
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 202)

    _use(forwarder, flaky)
    forwarder._send("http://peer-a:8000", "c1-m2", events.cloudevent("c1-m2", "ApplicationSubmitted"))
    assert calls["n"] == 3 and forwarder.failures == []

    calls["n"] = 0
    _use(forwarder, lambda request: (calls.__setitem__("n", calls["n"] + 1), httpx.Response(400))[1])
    forwarder._send("http://peer-a:8000", "c1-m2", events.cloudevent("c1-m2", "ApplicationSubmitted"))
    assert calls["n"] == 1 and forwarder.failures[0]["error"] == "HTTP 400"


def test_nothing_is_forwarded_without_sinks(monkeypatch):
    monkeypatch.delenv("EVENT_SINKS", raising=False)
    fw = event_forwarder.Forwarder()
    fw.submit(events.cloudevent("c1-m2", "ApplicationSubmitted"))
    assert fw.wait_idle(0.1) and not fw._threads


def test_received_events_are_not_forwarded_again(monkeypatch):
    sent = []
    monkeypatch.setattr(event_forwarder.FORWARDER, "submit", sent.append)
    events.RELAY.receive(events.cloudevent("c1-m2", "ApplicationSubmitted"))
    assert sent == []
    ev = events.publish("c3-m1", "CompanyCreated", {"companyId": "c"})
    assert sent == [ev]
