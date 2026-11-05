# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""SD-JWT VC: issue with top-level disclosures, present with key binding, split and resolve."""

import json
import os
import time

from common.jose import b64url, b64url_decode, read_jws, sha256_b64url, sign_jws


def issue(
    claims: dict,
    vct: str,
    holder_jwk: dict,
    key,
    header: dict,
    issuer: str,
    validity: int,
    status: dict | None = None,
) -> str:
    """Every top-level claim becomes its own disclosure; nested objects are disclosed as a whole."""
    disclosures = [
        b64url(json.dumps([b64url(os.urandom(16)), name, value], ensure_ascii=False).encode())
        for name, value in claims.items()
    ]
    now = int(time.time())
    payload = {
        "iss": issuer,
        "iat": now,
        "exp": now + validity,
        "vct": vct,
        "cnf": {"jwk": holder_jwk},
        "_sd_alg": "sha-256",
        "_sd": sorted(sha256_b64url(d) for d in disclosures),
    }
    if status:
        payload["status"] = status
    jwt = sign_jws({"typ": "dc+sd-jwt", **header}, payload, key)
    return jwt + "~" + "".join(d + "~" for d in disclosures)


def split(presentation: str) -> tuple[str, list[str], str | None]:
    """Issuer-signed JWT, disclosures and KB-JWT (None if the presentation ends with ~)."""
    issuer_jwt, *rest = presentation.split("~")
    if not rest:
        raise ValueError("not an SD-JWT")
    key_binding = rest[-1] or None
    return issuer_jwt, [d for d in rest[:-1] if d], key_binding


def sd_hash(presentation: str) -> str:
    """Hash over the SD-JWT without the KB-JWT, up to and including the last ~."""
    return sha256_b64url(presentation[: presentation.rfind("~") + 1])


def disclosure_name(disclosure: str) -> str | None:
    content = json.loads(b64url_decode(disclosure))
    return content[1] if len(content) == 3 else None


def resolve(payload: dict, disclosures: list[str]) -> dict:
    """Claims from the payload plus the disclosures; only top-level _sd, as issued by issue()."""
    if payload.get("_sd_alg", "sha-256") != "sha-256":
        raise ValueError(f"unsupported _sd_alg {payload['_sd_alg']!r}")
    by_digest = {}
    for disclosure in disclosures:
        digest = sha256_b64url(disclosure)
        if digest in by_digest:
            raise ValueError("disclosure sent twice")
        by_digest[digest] = json.loads(b64url_decode(disclosure))
    claims = {k: v for k, v in payload.items() if k not in ("_sd", "_sd_alg")}
    for digest in payload.get("_sd", []):
        if digest in by_digest:
            _salt, name, value = by_digest.pop(digest)
            claims[name] = value
    if by_digest:
        raise ValueError("disclosure without matching digest in _sd")
    return claims


def present(sd_jwt: str, claim_names: list[str] | None, holder_key, audience: str, nonce: str) -> str:
    """Presentation with the disclosures of the named claims (all if None) and a KB-JWT."""
    issuer_jwt, disclosures, _ = split(sd_jwt)
    if claim_names is not None:
        disclosures = [d for d in disclosures if disclosure_name(d) in claim_names]
    without_kb = issuer_jwt + "~" + "".join(d + "~" for d in disclosures)
    key_binding = sign_jws(
        {"typ": "kb+jwt"},
        {"iat": int(time.time()), "aud": audience, "nonce": nonce, "sd_hash": sha256_b64url(without_kb)},
        holder_key,
    )
    return without_kb + key_binding


def payload_of(sd_jwt: str) -> dict:
    """Payload of the issuer-signed JWT, without checking the signature."""
    return read_jws(split(sd_jwt)[0])[1]
