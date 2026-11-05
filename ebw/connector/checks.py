# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Checks of credentials (C5-M1 6.3) and of the representation (6.5)."""

import time
import unicodedata
from dataclasses import dataclass

import httpx

from common import sdjwt
from common.jose import key_from_jwk, read_jws, verify_jws
from common.statuslist import status_at
from connector import clients, config, trust
from connector.errors import VerificationError

CLOCK_SKEW = 60
KB_MAX_AGE = 300

_status_cache: dict[str, tuple[float, str]] = {}


@dataclass
class Presented:
    """A presentation after the checks that need no issuer key (6.3 steps 1 to 3, 6)."""

    credential_type: str
    presentation: str
    issuer_jwt: str
    payload: dict
    claims: dict
    key_binding: str | None
    status_checked: bool = False


def parse(presentation, credential_type: str) -> Presented:
    if not isinstance(presentation, str):
        raise VerificationError("UNSUPPORTED_FORMAT", "presentation is not an SD-JWT")
    try:
        issuer_jwt, disclosures, key_binding = sdjwt.split(presentation)
        header, payload = read_jws(issuer_jwt)
    except ValueError as exc:
        raise VerificationError("UNSUPPORTED_FORMAT", str(exc)) from None
    if header.get("typ") not in ("dc+sd-jwt", "vc+sd-jwt") or header.get("alg") != "ES256":
        raise VerificationError("UNSUPPORTED_FORMAT", f"typ {header.get('typ')!r}, alg {header.get('alg')!r}")
    if payload.get("vct") != config.VCT[credential_type]:
        raise VerificationError("MISSING_CREDENTIAL", f"{credential_type}: vct {payload.get('vct')!r}")
    try:
        claims = sdjwt.resolve(payload, disclosures)
    except (ValueError, TypeError) as exc:
        raise VerificationError("INVALID_RESPONSE", f"disclosures: {exc}") from None
    return Presented(credential_type, presentation, issuer_jwt, payload, claims, key_binding)


def check_times(item: Presented) -> None:
    now = time.time()
    payload = item.payload
    if payload.get("exp", now) < now - CLOCK_SKEW or max(payload.get("iat", 0), payload.get("nbf", 0)) > now + CLOCK_SKEW:
        raise VerificationError("CREDENTIAL_EXPIRED", f"{item.credential_type} outside exp, iat or nbf")


def check_status(item: Presented, issuer_key) -> None:
    reference = (item.payload.get("status") or {}).get("status_list")
    if not reference:
        return
    uri, index = reference.get("uri", ""), reference.get("idx")
    if not (uri.startswith("https://") or uri.startswith(("http://localhost", "http://127.0.0.1"))):
        raise VerificationError("STATUS_UNAVAILABLE", "status list address not allowed")
    cached = _status_cache.get(uri)
    if cached and cached[0] > time.time():
        token = cached[1]
    else:
        try:
            response = httpx.get(uri, headers={"Accept": "application/statuslist+jwt"}, timeout=5)
            response.raise_for_status()
            token = response.text
        except httpx.HTTPError as exc:
            raise VerificationError("STATUS_UNAVAILABLE", f"{item.credential_type}: {exc}") from None
        _status_cache[uri] = (time.time() + config.STATUS_LIST_CACHE_SECONDS, token)
    try:
        header, status_list = verify_jws(token, issuer_key)
        if header.get("typ") != "statuslist+jwt" or status_list.get("sub") != uri:
            raise ValueError("typ or sub of the status list")
        value = status_at(status_list, int(index))
    except (ValueError, KeyError, TypeError) as exc:
        raise VerificationError("STATUS_UNAVAILABLE", f"{item.credential_type}: {exc}") from None
    if value != 0:
        raise VerificationError("CREDENTIAL_REVOKED", f"{item.credential_type} revoked")
    item.status_checked = True


def check_key_binding(item: Presented, nonce: str) -> None:
    def failed(message: str) -> VerificationError:
        return VerificationError("HOLDER_BINDING_FAILED", f"{item.credential_type}: {message}")

    holder_jwk = (item.payload.get("cnf") or {}).get("jwk")
    if not item.key_binding or not holder_jwk:
        raise failed("KB-JWT or cnf.jwk missing")
    try:
        header, kb = verify_jws(item.key_binding, key_from_jwk(holder_jwk))
    except (ValueError, KeyError) as exc:
        raise failed(f"KB-JWT {exc}") from None
    if header.get("typ") != "kb+jwt":
        raise failed("typ must be kb+jwt")
    if kb.get("aud") != config.WALLET_CLIENT_ID:
        raise failed(f"aud is {kb.get('aud')!r}, expected {config.WALLET_CLIENT_ID!r}")
    if kb.get("nonce") != nonce:
        raise failed("nonce does not match the request")
    if abs(time.time() - kb.get("iat", 0)) > KB_MAX_AGE:
        raise failed("iat too old or in the future")
    if kb.get("sd_hash") != sdjwt.sd_hash(item.presentation):
        raise failed("sd_hash does not match")


def check_claims(item: Presented, names: list[str]) -> None:
    missing = [name for name in names if name not in item.claims]
    if missing:
        raise VerificationError("MISSING_CLAIM", f"{item.credential_type}: {', '.join(missing)}")


def verify_listed(presentation, credential_type: str, nonce: str, claim_names: list[str]) -> Presented:
    """PID and LPID: all checks of 6.3 at once."""
    item = parse(presentation, credential_type)
    _, key = trust.find_key(credential_type, item.issuer_jwt, item.payload.get("iss"))
    check_times(item)
    check_status(item, key)
    check_key_binding(item, nonce)
    check_claims(item, claim_names)
    return item


def receive_mandate(presentation, nonce: str) -> Presented:
    """Mandate: the checks that need no issuer key; the rest follows in representation()."""
    item = parse(presentation, "MANDATE")
    check_key_binding(item, nonce)
    return item


def _normalise(value) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().casefold()


def _mandate_key(mandate: Presented, lpid: Presented | None, client: dict) -> tuple[str | None, object]:
    """Rule of 6.5 whose key verifies the mandate, and the key."""
    try:
        _, key = trust.find_key("MANDATE", mandate.issuer_jwt, mandate.payload.get("iss"))
        return "trust_list", key
    except VerificationError:
        pass
    candidates = []
    if lpid is not None and (lpid.payload.get("cnf") or {}).get("jwk"):
        candidates.append(("company_key", key_from_jwk(lpid.payload["cnf"]["jwk"])))
    candidates += [("client_key", key) for _, key in clients.client_keys(client)]
    for rule, key in candidates:
        try:
            verify_jws(mandate.issuer_jwt, key)
            return rule, key
        except ValueError:
            continue
    return None, None


def representation(mandate: Presented, pid: Presented, lpid: Presented | None, client: dict, claim_names: list[str]) -> dict:
    """Result of 6.5. Raises VerificationError if a trusted mandate is expired, revoked or incomplete."""
    rule, key = _mandate_key(mandate, lpid, client)
    if rule is None:
        return {"result": "NOT_CONFIRMED", "reasons": ["ISSUER_NOT_TRUSTED"], "issuer": mandate.payload.get("iss")}
    check_times(mandate)
    check_status(mandate, key)
    check_claims(mandate, claim_names)
    claims = mandate.claims
    representative = claims.get("representative") or {}
    represented = claims.get("represented") or {}
    reasons = []
    if any(_normalise(representative.get(k)) != _normalise(pid.claims.get(k)) for k in ("given_name", "family_name", "birthdate")):
        reasons.append("PERSON_MISMATCH")
    if lpid is not None and represented.get("identifier") not in (lpid.claims.get("ebwoid"), lpid.claims.get("euid")):
        reasons.append("COMPANY_MISMATCH")
    if claims.get("representation_type") not in config.ACCEPTED_REPRESENTATION_TYPES:
        reasons.append("TYPE_NOT_ACCEPTED")
    if claims.get("valid_until") and claims["valid_until"] < time.strftime("%Y-%m-%d", time.gmtime()):
        reasons.append("EXPIRED")
    result = {
        "result": "NOT_CONFIRMED" if reasons else "CONFIRMED",
        "type": claims.get("representation_type"),
        "role": claims.get("role"),
        "valid_until": claims.get("valid_until"),
        "company_id": represented.get("identifier"),
        "company_name": represented.get("legal_name"),
        "issuer": mandate.payload.get("iss"),
        "trust": rule,
    }
    if reasons:
        result["reasons"] = reasons
    return {k: v for k, v in result.items() if v is not None}
