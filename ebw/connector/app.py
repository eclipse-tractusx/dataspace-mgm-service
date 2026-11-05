# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""EBW-Connector (C5-M1): OpenID Connect for clients, OpenID4VP for wallets."""

import base64
import hashlib
import time
from html import escape
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from common.jose import random_token, sha256_hex, sign_jws
from common.web import page, read_form
from connector import clients, config, pages, transactions
from connector.transactions import Transaction

app = FastAPI(title="EBW-Connector (C5-M1)")

COOKIE = "ebw_tx"
NO_STORE = {"Cache-Control": "no-store"}
CLAIMS_SUPPORTED = [
    "sub", "verification_id", "given_name", "family_name", "birthdate",
    "representation_result", "representation_reasons", "representation_type", "representation_role",
    "representation_valid_until", "representation_company_id", "representation_company_name",
    "representation_issuer", "representation_trust",
    "company_legal_name", "company_ebwoid", "company_euid", "company_country", "company_address",
]  # fmt: skip


def oauth_error(code: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=status, headers=NO_STORE)


@app.get("/", response_class=HTMLResponse)
def index():
    rows = {
        "Address": config.PUBLIC_URL,
        "Discovery": f"{config.PUBLIC_URL}/.well-known/openid-configuration",
        "Client ID towards wallets": config.WALLET_CLIENT_ID,
        "Response mode": config.RESPONSE_MODE,
        "Clients": ", ".join(clients.all_clients()),
    }
    table = "".join(f"<tr><th>{escape(k)}</th><td><code>{escape(v)}</code></td></tr>" for k, v in rows.items())
    return page("EBW-Connector (C5-M1)", f'<div class="box"><table>{table}</table></div>', brand="EBW-Connector", theme="connector", tagline="C5-M1")


@app.get("/.well-known/openid-configuration")
def discovery():
    base = config.PUBLIC_URL
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "userinfo_endpoint": f"{base}/userinfo",
        "jwks_uri": f"{base}/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["pairwise"],
        "id_token_signing_alg_values_supported": ["ES256"],
        "token_endpoint_auth_methods_supported": ["private_key_jwt"],
        "token_endpoint_auth_signing_alg_values_supported": ["ES256"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": clients.ALL_SCOPES,
        "claims_supported": CLAIMS_SUPPORTED,
        "authorization_response_iss_parameter_supported": True,
        "ui_locales_supported": ["en"],
    }


@app.get("/jwks")
def jwks():
    return JSONResponse({"keys": [config.SIGNING_JWK]}, headers={"Cache-Control": "max-age=3600"})


def redirect_to_client(redirect_uri: str, params: dict) -> RedirectResponse:
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{separator}{urlencode({**params, 'iss': config.PUBLIC_URL})}", status_code=302)


@app.get("/authorize")
def authorize(request: Request):
    params = dict(request.query_params)
    client = clients.get(params.get("client_id"))
    if not client or params.get("redirect_uri") not in client.get("redirectUris", []):
        return HTMLResponse(pages.error_page("Unknown client or redirect_uri not registered."), 400)
    redirect_uri, state = params["redirect_uri"], params.get("state", "")
    scopes = params.get("scope", "").split()
    if params.get("response_type") != "code" or not params.get("nonce") or not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
        return redirect_to_client(redirect_uri, {"error": "invalid_request", "error_description": "response_type code, nonce and PKCE S256 are required", "state": state})
    allowed = set(client.get("scopes", clients.ALL_SCOPES))
    if "openid" not in scopes or not set(scopes) <= allowed or (
        "attestation" in scopes and not {"profile", "representation", "company"} <= set(scopes)
    ):
        return redirect_to_client(redirect_uri, {"error": "invalid_scope", "error_description": "scope not allowed", "state": state})
    browser_value = request.cookies.get(COOKIE) or random_token(24)
    tx = transactions.create(client, params, scopes, browser_value)
    response = RedirectResponse(f"/transactions/{tx.id}", status_code=302)
    response.set_cookie(COOKIE, browser_value, httponly=True, samesite="lax", secure=config.SECURE, path="/")
    return response


def bound(tx_id: str, request: Request) -> Transaction | None:
    """Transaction if the browser holds its cookie."""
    tx = transactions.transactions.get(tx_id)
    value = request.cookies.get(COOKIE)
    if not tx or not value or sha256_hex(value) != tx.browser_hash:
        return None
    tx.refresh()
    return tx


@app.get("/transactions/{tx_id}", response_class=HTMLResponse)
def transaction_page(tx_id: str, request: Request):
    if tx_id not in transactions.transactions:
        return HTMLResponse(pages.error_page("Unknown transaction."), 404)
    tx = bound(tx_id, request)
    if tx is None:
        return HTMLResponse(pages.done_page())
    if tx.status != "PENDING":
        return RedirectResponse(f"/transactions/{tx_id}/complete", status_code=302)
    return HTMLResponse(pages.transaction_page(tx))


@app.get("/transactions/{tx_id}/status")
def transaction_status(tx_id: str, request: Request):
    tx = bound(tx_id, request)
    if tx is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"status": tx.status, "step": tx.step.name if tx.step else None}


@app.get("/transactions/{tx_id}/complete")
def complete(tx_id: str, request: Request):
    tx = bound(tx_id, request)
    if tx is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if tx.status == "PENDING":
        return RedirectResponse(f"/transactions/{tx_id}", status_code=302)
    if tx.status == "VERIFIED":
        return redirect_to_client(tx.redirect_uri, {"code": transactions.issue_code(tx), "state": tx.state})
    reason = tx.failure_reason or tx.status
    return redirect_to_client(tx.redirect_uri, {"error": "access_denied", "error_description": reason, "state": tx.state})


@app.api_route("/openid4vp/requests/{request_id}", methods=["GET", "POST"])
async def request_object(request_id: str, request: Request):
    found = transactions.for_request(request_id)
    if not found:
        return JSONResponse({"error": "invalid_request", "error_description": "unknown or closed request"}, 404)
    wallet_nonce = (await read_form(request)).get("wallet_nonce") if request.method == "POST" else None
    return Response(transactions.request_object(*found, wallet_nonce), media_type="application/oauth-authz-req+jwt")


@app.post("/openid4vp/responses/{request_id}")
async def wallet_response(request_id: str, request: Request):
    found = transactions.for_request(request_id)
    if not found:
        return oauth_error("invalid_request", "unknown or closed request")
    tx, step = found
    if step.status == "VERIFIED":
        return oauth_error("invalid_request", "this step has already been answered")
    transactions.receive(tx, step, await read_form(request))
    print(f"Transaction {tx.id}: step {step.name} {step.status}, transaction {tx.status}", flush=True)
    return JSONResponse({"redirect_uri": f"{config.PUBLIC_URL}/transactions/{tx.id}"})


@app.post("/token")
async def token(request: Request):
    form = await read_form(request)
    try:
        client = clients.authenticate(form)
    except clients.ClientAuthError as exc:
        return oauth_error("invalid_client", str(exc), 401)
    if form.get("grant_type") != "authorization_code":
        return oauth_error("unsupported_grant_type", "only authorization_code")
    tx = transactions.find_by_code(form.get("code", ""))
    if tx is None:
        return oauth_error("invalid_grant", "unknown code")
    if tx.code_used:
        if tx.access_hash:
            transactions.access_tokens.pop(tx.access_hash, None)
        tx.access_expires = 0
        return oauth_error("invalid_grant", "code used before; the access token is revoked")
    tx.refresh()
    if tx.status != "CODE_ISSUED" or tx.client["clientId"] != client["clientId"] or tx.redirect_uri != form.get("redirect_uri"):
        return oauth_error("invalid_grant", "code expired or issued to another client or redirect_uri")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
    if challenge != tx.code_challenge:
        return oauth_error("invalid_grant", "PKCE verification failed")
    tx.code_used, tx.status = True, "COMPLETED"
    now = int(time.time())
    access_token = random_token(32)
    tx.access_hash, tx.access_expires = sha256_hex(access_token), now + config.ACCESS_TOKEN_TTL_SECONDS
    transactions.access_tokens[tx.access_hash] = tx.id
    id_token = sign_jws(
        {"typ": "JWT", "kid": config.KID},
        {
            "iss": config.PUBLIC_URL,
            "sub": tx.sub,
            "aud": client["clientId"],
            "iat": now,
            "exp": now + 300,
            "auth_time": tx.verified_at,
            "nonce": tx.nonce,
            **tx.claims,
        },
        config.SIGNING_KEY,
    )
    body = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": config.ACCESS_TOKEN_TTL_SECONDS,
        "id_token": id_token,
    }
    if tx.attestation:
        body["ebw_attestation"] = tx.attestation
    transactions.log(tx, "completed")
    return JSONResponse(body, headers=NO_STORE)


@app.get("/userinfo")
def userinfo(request: Request):
    scheme, _, access_token = request.headers.get("authorization", "").partition(" ")
    tx = transactions.transactions.get(transactions.access_tokens.get(sha256_hex(access_token), ""))
    if scheme.lower() != "bearer" or tx is None or tx.access_expires < time.time():
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    return {"sub": tx.sub, **tx.claims}
