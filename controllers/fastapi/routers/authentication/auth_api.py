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
"""Authentication of the APIs of the installation under `/api/v1` (controllers/), ADR-0002.

Like the Industry Core Hub backend, with the API key manager of the Eclipse Tractus-X SDK
(`tractusx_sdk.dataspace.managers.AuthManager`). The API key is the minimum layer; it is checked
before the controller's own authorization (e.g. the service account of the event inbox), never
instead of it. Disabled by default:

| Variable | Meaning | Default |
|---|---|---|
| `API_AUTH_ENABLED` | `true` requires the API key on every controller under `/api/v1` | `false` |
| `API_KEY_HEADER` | name of the header that carries the key | `X-Api-Key` |
| `API_KEY` | the key (secret, at least 32 characters recommended); required when enabled | – |

Enabled without `API_KEY`, every call answers 500 `configuration` naming the variable (fail
closed, FRAMEWORK 4.8). A missing or wrong key answers 401 `unauthorized`. The key is compared in
constant time. An identity provider of the operator (bring your own IdP) is the next mode; it
plugs in here as a further check of `get_authentication_dependency()` (ADR-0002).
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Request, Security
from fastapi.security import APIKeyHeader
from tractusx_sdk.dataspace.managers import AuthManager

from portal_common.problems import Problem

AREA = "api"                  # Problem Details `urn:api:problem:<name>`
DEFAULT_HEADER = "X-Api-Key"
RECOMMENDED_MIN_LENGTH = 32
log = logging.getLogger("portal.api.auth")


class ApiKeyManager(AuthManager):
    """The SDK's API key manager with a constant-time comparison (the SDK compares with `==`)."""

    def is_authenticated(self, request: Request) -> bool:
        if not self.auth_enabled:
            return True
        given = request.headers.get(self.api_key_header)
        return given is not None and hmac.compare_digest(given.encode(), (self.configured_api_key or "").encode())


def _enabled() -> bool:
    return os.environ.get("API_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def manager() -> ApiKeyManager:
    """The API key manager of the current configuration (read when the app is created)."""
    return ApiKeyManager(configured_api_key=os.environ.get("API_KEY", ""),
                         api_key_header=os.environ.get("API_KEY_HEADER") or DEFAULT_HEADER, auth_enabled=_enabled())


def get_authentication_dependency():
    """FastAPI dependency for the routers under `/api/v1`: OPTIONS (CORS preflight) passes, otherwise
    the API key when `API_AUTH_ENABLED` is `true`. Logs the mode once, at app creation."""
    m = manager()
    if not m.auth_enabled:
        log.warning("API key authentication of /api/v1 is DISABLED (API_AUTH_ENABLED=false); the controllers "
                    "rely on their own authorization only")
    elif not m.configured_api_key:
        log.error("API_AUTH_ENABLED=true but API_KEY is not set: every call to /api/v1 answers 500")
    else:
        log.info("API key authentication of /api/v1 is enabled (header %s)", m.api_key_header)
        if len(m.configured_api_key) < RECOMMENDED_MIN_LENGTH:
            log.warning("API_KEY is shorter than %d characters", RECOMMENDED_MIN_LENGTH)
    header = APIKeyHeader(name=m.api_key_header, auto_error=False,
                          description="API key of the installation (ADR-0002); only when API_AUTH_ENABLED=true")

    def authenticate(request: Request) -> None:
        if request.method == "OPTIONS" or not m.auth_enabled:
            return
        if not m.configured_api_key:
            raise Problem(AREA, 500, "configuration", detail="API_AUTH_ENABLED is true but API_KEY is not set")
        if not m.is_authenticated(request):
            raise Problem(AREA, 401, "unauthorized", detail=f"API key missing or wrong (header {m.api_key_header})")

    async def dependency(request: Request, _key: str | None = Security(header)) -> None:   # documents the header
        authenticate(request)

    return dependency
