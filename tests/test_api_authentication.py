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
"""API key of the APIs under /api/v1 (controllers/, ADR-0002): disabled by default, configurable."""
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import BASE, bearer, person_token
from controllers.fastapi.routers.authentication import auth_api
from portal_common import events, tokens
from portal_common import http as phttp
from scaffold import app as scaffold_app

INBOX = "/api/v1/events/inbox"
KEY = "k" * 40


def event() -> dict:
    return {"specversion": "1.0", "id": str(uuid.uuid4()), "source": "urn:c1-m2", "type": "ApplicationCreated",
            "time": "2026-11-06T09:30:00Z", "datacontenttype": "application/json",
            "data": {"applicationId": str(uuid.uuid4()), "companyId": str(uuid.uuid4()), "kind": "ONBOARDING",
                     "existingCompany": False}}


def client(monkeypatch, **env) -> TestClient:
    for k in ("API_AUTH_ENABLED", "API_KEY", "API_KEY_HEADER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    app = scaffold_app.create_app()   # the configuration is read when the app is created
    phttp.register_local(BASE, app)
    return TestClient(app, base_url=BASE)


def post(c: TestClient, headers: dict) -> object:
    return c.post(INBOX, headers=bearer(tokens.service_token("c1-m2")) | {"Content-Type": "application/cloudevents+json"}
                  | headers, content=json.dumps(event()))


def test_disabled_by_default_with_a_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="portal.api.auth"):
        c = client(monkeypatch)
    assert post(c, {}).status_code == 202
    assert "DISABLED" in caplog.text


def test_enabled_requires_the_key_before_the_controller(monkeypatch):
    c = client(monkeypatch, API_AUTH_ENABLED="true", API_KEY=KEY)
    for headers in ({}, {"X-Api-Key": "wrong"}, {"X-Api-Key": KEY[:-1]}):
        r = post(c, headers)
        assert r.status_code == 401 and r.json()["type"] == "urn:api:problem:unauthorized"
    assert post(c, {"X-Api-Key": KEY}).status_code == 202
    # the key is a layer in front of the controller's own check, never instead of it
    r = c.post(INBOX, headers={"X-Api-Key": KEY, "Content-Type": "application/cloudevents+json"}, content=json.dumps(event()))
    assert r.status_code == 401 and r.json()["type"] == "urn:events:problem:unauthorized"
    assert len(events.RELAY.log) == 1


def test_header_name_is_configurable(monkeypatch):
    c = client(monkeypatch, API_AUTH_ENABLED="true", API_KEY=KEY, API_KEY_HEADER="X-Installation-Key")
    assert post(c, {"X-Api-Key": KEY}).status_code == 401
    assert post(c, {"X-Installation-Key": KEY}).status_code == 202
    schemes = c.get("/openapi.json").json()["components"]["securitySchemes"]
    assert {"type": "apiKey", "in": "header", "name": "X-Installation-Key"}.items() <= next(iter(schemes.values())).items()


def test_enabled_without_a_key_fails_closed(monkeypatch):
    c = client(monkeypatch, API_AUTH_ENABLED="true")
    r = post(c, {"X-Api-Key": ""})
    assert r.status_code == 500 and r.json()["type"] == "urn:api:problem:configuration" and "API_KEY" in r.json()["detail"]
    assert events.RELAY.log == []


def test_module_apis_keep_their_portal_iam_tokens(monkeypatch):
    c = client(monkeypatch, API_AUTH_ENABLED="true", API_KEY=KEY)
    r = c.get("/api/c12-m1/processes", headers=bearer(person_token("otto")))   # no API key needed (FRAMEWORK 4.2)
    assert r.status_code == 200


def test_the_manager_is_the_sdk_one_with_a_constant_time_comparison():
    from tractusx_sdk.dataspace.managers import AuthManager
    assert issubclass(auth_api.ApiKeyManager, AuthManager)
