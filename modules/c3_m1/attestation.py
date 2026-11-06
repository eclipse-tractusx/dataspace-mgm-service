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
#  Assisted-By: Hermes Agent (deepseek-v4.1-flash)
#################################################################################
"""Checking a verification attestation of the EBW-Connector (C3-M1 6.7, 11.2).

The order of the checks is the one of 6.7; the first failure decides the `reason` of the
400 `attestation-invalid`. Nothing here changes state — 7.3 maps the claims to the company and
writes afterwards.

Keys come only from the configuration: `ATTESTATION_JWKS_FILE` (tests, no fetch) or
`ATTESTATION_JWKS_URL` with a cache and one reload per minute for an unknown `kid` (6.7 point 4).
Header parameters such as `jku`, `x5u` or `jwk` are ignored.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import time

import httpx
import jwt
from portal_common import http
from portal_common.problems import Problem

from . import config

MODULE = "c3-m1"
TYP = "ebw-attestation+jwt"
ALGORITHM = "ES256"
REQUIRED_CLAIMS = ("jti", "verified_at", "purpose", "company", "representation")

_cache: dict = {"keys": [], "fetched_at": 0.0}
_last_reload = 0.0


def reset() -> None:
    """Forget the cached keys (test helper; the configuration may have changed)."""
    global _last_reload
    _cache.update({"keys": [], "fetched_at": 0.0})
    _last_reload = 0.0


def _invalid(reason: str, detail: str | None = None) -> Problem:
    return Problem(MODULE, 400, "attestation-invalid", reason=reason, detail=detail)


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _load_keys() -> list[dict]:
    """Keys from the file, else from the URL with the cache of 6.7 and 11.2."""
    file = config.attestation_jwks_file()
    if file is not None:
        try:
            return json.loads(file.read_text(encoding="utf-8")).get("keys") or []
        except (OSError, ValueError) as error:
            raise Problem(MODULE, 502, "upstream-error",
                          detail=f"JWKS file unreadable: {error}", retryable=True) from error
    now = time.monotonic()
    if _cache["keys"] and now - float(_cache["fetched_at"]) < config.attestation_jwks_cache_seconds():
        return _cache["keys"]
    try:
        # portal_common.http: also reaches an EBW-Connector registered in-process ({BASE_URL}/ebw)
        response = http.request("GET", config.attestation_jwks_url(), timeout=5.0)
        response.raise_for_status()
        keys = response.json().get("keys") or []
    except (httpx.HTTPError, ValueError) as error:
        raise Problem(MODULE, 502, "upstream-error",
                      detail=f"JWKS not reachable: {error}", retryable=True) from error
    _cache.update({"keys": keys, "fetched_at": now})
    return keys


def _key_for(kid: str | None) -> dict:
    """The key of `kid`; an unknown `kid` reloads the cache at most once per minute (6.7)."""
    global _last_reload
    keys = _load_keys()
    key = next((entry for entry in keys if entry.get("kid") == kid), None)
    if key is not None or config.attestation_jwks_file() is not None:
        if key is None:
            raise _invalid("signature", f"kid {kid!r} is not in the JWKS")
        return key
    if time.monotonic() - _last_reload > 60:
        _last_reload = time.monotonic()
        _cache.update({"keys": [], "fetched_at": 0.0})
        keys = _load_keys()
        key = next((entry for entry in keys if entry.get("kid") == kid), None)
    if key is None:
        raise _invalid("signature", f"kid {kid!r} is not in the JWKS")
    return key


def _moment(value, field: str) -> dt.datetime:
    if not isinstance(value, (int, float)):
        raise _invalid("claims", f"{field} is not a numeric date")
    return dt.datetime.fromtimestamp(value, dt.UTC)


def verify(attestation: str, *, now: dt.datetime | None = None) -> dict:
    """The claims of a valid attestation; raises `attestation-invalid` or `upstream-error` (6.7)."""
    points = now or dt.datetime.now(dt.UTC)
    skew = dt.timedelta(seconds=config.attestation_clock_skew_seconds())

    parts = (attestation or "").split(".")
    if len(parts) != 3:
        raise _invalid("format", "not a compact JWS")
    try:
        header = json.loads(_b64(parts[0]))
    except (ValueError, TypeError) as error:
        raise _invalid("format", "header unreadable") from error
    if not isinstance(header, dict):
        raise _invalid("format", "header is no object")

    if header.get("typ") != TYP or header.get("alg") != ALGORITHM:
        raise _invalid("algorithm", f"typ {header.get('typ')!r}, alg {header.get('alg')!r}")

    try:
        claims = jwt.decode(attestation, options={"verify_signature": False, "verify_aud": False,
                                                  "verify_exp": False, "verify_iat": False})
    except jwt.PyJWTError as error:
        raise _invalid("format", f"payload unreadable: {error}") from error
    if claims.get("iss") != config.attestation_issuer():
        raise _invalid("issuer", f"iss {claims.get('iss')!r}")

    key = _key_for(header.get("kid"))
    try:
        claims = jwt.decode(attestation, jwt.PyJWK(key).key, algorithms=[ALGORITHM],
                            options={"verify_aud": False, "verify_exp": False, "verify_iat": False})
    except jwt.InvalidSignatureError as error:
        raise _invalid("signature", "signature does not verify") from error
    except jwt.PyJWTError as error:
        raise _invalid("signature", str(error)) from error

    audience = claims.get("aud")
    audience = [audience] if isinstance(audience, str) else list(audience or [])
    if config.attestation_audience() not in audience:
        raise _invalid("audience", f"aud {audience!r}")

    expires, issued = _moment(claims.get("exp"), "exp"), _moment(claims.get("iat"), "iat")
    if expires <= points - skew:
        raise _invalid("expired", "exp is in the past")
    if issued > points + skew:
        raise _invalid("not-yet-valid", "iat is in the future")

    company = claims.get("company")
    missing = [name for name in REQUIRED_CLAIMS if claims.get(name) in (None, "")]
    if not isinstance(company, dict):
        missing.append("company.*")
    else:
        missing += [f"company.{name}" for name in ("legal_name", "ebwoid", "country")
                    if company.get(name) in (None, "")]
    if claims.get("purpose") != "onboarding":
        missing.append("purpose=onboarding")
    clients = config.attestation_client_ids()
    if clients and claims.get("client_id") not in clients:
        missing.append("client_id")
    if missing:
        raise _invalid("claims", "missing or wrong: " + ", ".join(missing))

    verified_at = _moment(claims.get("verified_at"), "verified_at")
    if verified_at < points - dt.timedelta(hours=config.attestation_max_age_hours()):
        raise _invalid("too-old", "verified_at is older than the allowed age")
    return claims | {"_verified_at": verified_at}
