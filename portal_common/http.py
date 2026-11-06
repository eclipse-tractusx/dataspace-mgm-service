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
"""One HTTP entry point for all outgoing calls (neighbours, IAM, CSP, issuers, providers).

An app registered with `register_local(base_url, app)` is called in the same process through
its ASGI interface instead of the network. That is how `in-process` neighbours work
(FRAMEWORK 1, 4.7), and how tests run several systems without opening ports. The request
still carries a token and passes the same routes, checks and Problem Details as over HTTP.
"""
from __future__ import annotations

import warnings

import httpx

with warnings.catch_warnings():   # starlette announces a successor of httpx for its test client
    warnings.simplefilter("ignore")
    from starlette.testclient import TestClient

DEFAULT_TIMEOUT = 10.0
_local: dict[str, object] = {}
# One pooled client: keep-alive connections to the neighbours of a split-out module (ADR-0002)
_pool = httpx.Client(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))


def register_local(base_url: str, app) -> None:
    _local[base_url.rstrip("/")] = app


def unregister_local(base_url: str) -> None:
    _local.pop(base_url.rstrip("/"), None)


def _local_app(url: str):
    for base, app in _local.items():
        if url == base or url.startswith(base + "/"):
            return base, app
    return None, None


def request(method: str, url: str, timeout: float = DEFAULT_TIMEOUT, **kw) -> httpx.Response:
    """Like `httpx.request`; raises `httpx.HTTPError` on timeouts and connection errors."""
    base, app = _local_app(url)
    if app is None:
        return _pool.request(method, url, timeout=timeout, **kw)
    # MINIMAL: one TestClient per call (thread-safe, starts a short-lived event loop thread);
    # upgrade: a pooled ASGI transport if call volume ever matters.
    client = TestClient(app, base_url=base, raise_server_exceptions=False)
    return client.request(method, url[len(base):] or "/", **kw)
