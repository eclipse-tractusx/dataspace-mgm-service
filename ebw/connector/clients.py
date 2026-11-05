# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Registered clients (C5-M1 6.8): client assertions with private_key_jwt, client keys."""

import json
import time

import httpx

from common.jose import keys_from_jwks, read_jws, verify_jws
from connector import config

JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ALL_SCOPES = ["openid", "profile", "representation", "company", "attestation"]

_used_jtis: dict[str, float] = {}
_jwks_cache: dict[str, tuple[float, list]] = {}


class ClientAuthError(Exception):
    pass


def default_clients() -> list[dict]:
    return [
        {
            "clientId": "demo-osp",
            "name": "OSP 2.0 demo portal",
            "jwksUri": f"{config.TEST_TOOLS_URL}/osp/jwks",
            "redirectUris": [f"{config.TEST_TOOLS_URL}/osp/callback"],
            "scopes": ALL_SCOPES,
        },
        {
            "clientId": "business-wallet",
            "name": "Business Wallet",
            "jwksUri": f"{config.BUSINESS_WALLET_URL}/jwks",
            "redirectUris": [f"{config.BUSINESS_WALLET_URL}/login/callback"],
            "scopes": ["openid", "profile", "representation"],
        },
    ]


def all_clients() -> dict[str, dict]:
    entries = json.loads(config.CLIENTS_FILE.read_text()) if config.CLIENTS_FILE.exists() else default_clients()
    return {c["clientId"]: c for c in entries}


def get(client_id: str | None) -> dict | None:
    return all_clients().get(client_id or "")


def client_keys(client: dict, refresh: bool = False) -> list:
    if "jwks" in client:
        return keys_from_jwks(client["jwks"])
    uri = client["jwksUri"]
    cached = _jwks_cache.get(uri)
    if cached and not refresh and cached[0] > time.time():
        return cached[1]
    try:
        response = httpx.get(uri, timeout=5)
        response.raise_for_status()
        keys = keys_from_jwks(response.json())
    except (httpx.HTTPError, ValueError):
        return cached[1] if cached else []
    _jwks_cache[uri] = (time.time() + 300, keys)
    return keys


def authenticate(form: dict) -> dict:
    """Client from a valid client assertion (RFC 7523); raises ClientAuthError."""
    if form.get("client_assertion_type") != JWT_BEARER or not form.get("client_assertion"):
        raise ClientAuthError("client_assertion missing")
    assertion = form["client_assertion"]
    try:
        header, payload = read_jws(assertion)
    except ValueError:
        raise ClientAuthError("client_assertion is not a JWT") from None
    client = get(payload.get("iss"))
    if not client or payload.get("sub") != payload.get("iss"):
        raise ClientAuthError("unknown client")
    keys = client_keys(client)
    if header.get("kid") and header["kid"] not in [kid for kid, _ in keys]:
        keys = client_keys(client, refresh=True)
    if not any(_verifies(assertion, key) for _, key in keys):
        raise ClientAuthError("signature of the client assertion does not verify")
    audience = payload.get("aud")
    if not {config.PUBLIC_URL, f"{config.PUBLIC_URL}/token"} & set(audience if isinstance(audience, list) else [audience]):
        raise ClientAuthError("aud of the client assertion is wrong")
    now = time.time()
    if not now - 60 < payload.get("exp", 0) <= now + 360:
        raise ClientAuthError("exp of the client assertion is missing, passed or too far in the future")
    jti = payload.get("jti")
    for used, expiry in list(_used_jtis.items()):
        if expiry < now:
            del _used_jtis[used]
    if not jti or jti in _used_jtis:
        raise ClientAuthError("jti missing or used before")
    _used_jtis[jti] = payload["exp"] + 60
    return client


def _verifies(token: str, key) -> bool:
    try:
        verify_jws(token, key)
        return True
    except ValueError:
        return False
