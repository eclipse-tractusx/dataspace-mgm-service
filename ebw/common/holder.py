# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Wallet side: fetch credentials (OpenID4VCI 1.0) and answer presentation requests (OpenID4VP 1.0).
Used by the Business Wallet and by the test wallet."""

import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from common import jwe, sdjwt
from common.jose import cert_from_x5c, public_jwk, read_jws, san_dns_names, sign_jws, verify_jws

PRE_AUTH_GRANT = "urn:ietf:params:oauth:grant-type:pre-authorized_code"


class WalletError(Exception):
    pass


def well_known(base: str, name: str) -> str:
    """Well-known address with path insertion (RFC 8414, OpenID4VCI 1.0)."""
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}/.well-known/{name}{parts.path.rstrip('/')}"


def _json(response: httpx.Response) -> dict:
    if response.is_error:
        raise WalletError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text[:300]}")
    return response.json()


def query_params(link: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(link.strip()).query).items()}


def resolve_offer(link: str, http: httpx.Client) -> dict:
    params = query_params(link)
    if "credential_offer_uri" in params:
        return _json(http.get(params["credential_offer_uri"]))
    if "credential_offer" in params:
        return json.loads(params["credential_offer"])
    raise WalletError("no credential offer in the link")


def obtain_credentials(offer: dict, holder_key, http: httpx.Client) -> dict[str, str]:
    """Pre-authorized code flow; returns credential configuration ID -> SD-JWT VC."""
    issuer = offer["credential_issuer"]
    grant = offer.get("grants", {}).get(PRE_AUTH_GRANT)
    if not grant:
        raise WalletError("only the pre-authorized code flow is supported")
    metadata = _json(http.get(well_known(issuer, "openid-credential-issuer")))
    authorization_server = (metadata.get("authorization_servers") or [issuer])[0]
    as_metadata = _json(http.get(well_known(authorization_server, "oauth-authorization-server")))
    token = _json(
        http.post(
            as_metadata["token_endpoint"],
            data={"grant_type": PRE_AUTH_GRANT, "pre-authorized_code": grant["pre-authorized_code"]},
        )
    )
    credentials = {}
    for cid in offer["credential_configuration_ids"]:
        nonce = _json(http.post(metadata["nonce_endpoint"]))["c_nonce"]
        proof = sign_jws(
            {"typ": "openid4vci-proof+jwt", "jwk": public_jwk(holder_key)},
            {"aud": issuer, "iat": int(time.time()), "nonce": nonce},
            holder_key,
        )
        response = _json(
            http.post(
                metadata["credential_endpoint"],
                headers={"Authorization": f"Bearer {token['access_token']}"},
                json={"credential_configuration_id": cid, "proofs": {"jwt": [proof]}},
            )
        )
        credentials[cid] = response["credentials"][0]["credential"]
    return credentials


def read_request(params: dict[str, str], http: httpx.Client) -> dict:
    """Fetches the request object of an authorization request and checks the client identifier."""
    client_id, request_uri = params.get("client_id"), params.get("request_uri")
    if not client_id or not request_uri:
        raise WalletError("client_id and request_uri are required")
    response = http.get(request_uri)
    if response.is_error:
        raise WalletError(f"request object not available ({response.status_code})")
    token = response.text
    header, request = read_jws(token)
    if client_id.startswith("x509_san_dns:"):
        cert = cert_from_x5c(header["x5c"][0])
        verify_jws(token, cert.public_key())
        if client_id.removeprefix("x509_san_dns:") not in san_dns_names(cert):
            raise WalletError("client_id does not match the certificate")
    elif not client_id.startswith("redirect_uri:"):
        raise WalletError(f"unsupported client identifier {client_id!r}")
    if request.get("client_id") != client_id:
        raise WalletError("client_id of the request object differs from the link")
    return request


def requested(request: dict) -> list[dict]:
    """Credential queries with their claim names (top-level paths only)."""
    return [
        {"id": q["id"], "vct_values": q["meta"]["vct_values"], "claims": [c["path"][0] for c in q.get("claims", [])]}
        for q in request["dcql_query"]["credentials"]
    ]


def find_credential(credentials: list[str], vct_values: list[str]) -> str | None:
    """The most recently stored credential with one of the vct values."""
    return next((c for c in reversed(credentials) if sdjwt.payload_of(c).get("vct") in vct_values), None)


def build_vp_token(request: dict, credentials: list[str], holder_key, nonce: str | None = None) -> dict:
    vp_token = {}
    for query in requested(request):
        credential = find_credential(credentials, query["vct_values"])
        if credential is None:
            raise WalletError(f"no credential for {query['id']} ({', '.join(query['vct_values'])})")
        vp_token[query["id"]] = [
            sdjwt.present(credential, query["claims"], holder_key, request["client_id"], nonce or request["nonce"])
        ]
    return vp_token


def send_response(request: dict, parameters: dict, http: httpx.Client) -> dict:
    """direct_post or direct_post.jwt; returns the verifier's JSON answer (e.g. redirect_uri)."""
    if request.get("response_mode") == "direct_post.jwt":
        metadata = request.get("client_metadata", {})
        keys = metadata.get("jwks", {}).get("keys", [])
        key = next((k for k in keys if k.get("use", "enc") == "enc"), None)
        if key is None:
            raise WalletError("no encryption key in client_metadata")
        enc = (metadata.get("encrypted_response_enc_values_supported") or ["A128GCM"])[0]
        data = {"response": jwe.encrypt(json.dumps(parameters).encode(), key, enc)}
    else:
        data = {k: json.dumps(v) if isinstance(v, dict) else v for k, v in parameters.items()}
    return _json(http.post(request["response_uri"], data=data))


def answer(request: dict, credentials: list[str], holder_key, http: httpx.Client, nonce: str | None = None) -> dict:
    vp_token = build_vp_token(request, credentials, holder_key, nonce)
    return send_response(request, {"vp_token": vp_token, "state": request.get("state")}, http)


def decline(request: dict, http: httpx.Client) -> dict:
    data = {"error": "access_denied", "error_description": "declined by the user", "state": request.get("state", "")}
    return _json(http.post(request["response_uri"], data=data))
