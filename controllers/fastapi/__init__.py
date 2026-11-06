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
"""HTTP controllers of the installation that belong to no module (base skeleton, FRAMEWORK 1).

Layout as in the Industry Core Hub backend: one folder per API category under `routers/`, one
folder per version, one file per controller with its own `router`:

    controllers/fastapi/routers/<category>/v1/<name>_api.py   router = APIRouter(prefix="/<category>")

`include(app)` mounts every controller under `/api/v1`, e.g. `POST /api/v1/events/inbox`, behind the
optional API key of `routers/authentication/auth_api.py` (ADR-0002, disabled by default). The APIs of
the modules stay in `modules/<id>/router.py` under `/api/<module>` (FRAMEWORK 4.1); a new category
gets its own folder here and one line in `v1_router()`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from .routers.authentication.auth_api import get_authentication_dependency
from .routers.events.v1 import inbox_api

API_V1 = "/api/v1"

TAGS = [
    {"name": inbox_api.TAG,
     "description": "Event inbox of the installation: receives the CloudEvents of split-out modules over HTTP "
                    "(FRAMEWORK 6, proposal OP-54)"},
]


def v1_router() -> APIRouter:
    """All controllers under `/api/v1`, behind the API key when it is enabled (ADR-0002)."""
    router = APIRouter(prefix=API_V1, dependencies=[Depends(get_authentication_dependency())])
    router.include_router(inbox_api.router)
    return router


def include(app: FastAPI) -> None:
    """Mounts the controllers and adds their tags to the OpenAPI document of the installation."""
    app.include_router(v1_router())
    known = {t["name"] for t in app.openapi_tags or []}
    app.openapi_tags = [*(app.openapi_tags or []), *(t for t in TAGS if t["name"] not in known)]
