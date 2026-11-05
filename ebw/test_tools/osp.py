# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Demo OSP: a minimal portal that signs people in and onboards companies through the EBW-Connector.
It keeps the companies it registered, as the registration (C1-M2) would."""

import json
import time
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from common.jose import signing_jwk
from common.oidc_client import OidcClient, OidcError
from common.web import CookieSession, claims_table, page
from test_tools import config

router = APIRouter()

SCOPES = {
    "signin": "openid profile representation",
    "onboarding": "openid profile representation company attestation",
}
TITLES = {"signin": "Sign-in", "onboarding": "Register company"}
REGISTRATIONS = config.DATA_DIR / "osp-registrations.json"

client = OidcClient(config.CONNECTOR_URL, config.OSP_CLIENT_ID, f"{config.PUBLIC_URL}/osp/callback", config.OSP_KEY)
flows = CookieSession("osp_flow", config.SESSION_SECRET, config.PUBLIC_URL.startswith("https"), max_age=900)


def registrations() -> dict[str, dict]:
    """EBWOID -> registered company with its verification attestation."""
    return json.loads(REGISTRATIONS.read_text()) if REGISTRATIONS.exists() else {}


def register(attestation: dict) -> dict:
    entries = registrations()
    company = attestation["company"]
    entry = {
        "company": company,
        "registered_at": time.strftime("%Y-%m-%d %H:%M"),
        "by": f"{attestation['person']['given_name']} {attestation['person']['family_name']}",
        "representation": attestation["representation"],
        "attestation": attestation,
    }
    entries[company["ebwoid"]] = entry
    REGISTRATIONS.parent.mkdir(parents=True, exist_ok=True)
    REGISTRATIONS.write_text(json.dumps(entries, indent=1, ensure_ascii=False))
    return entry


NAV = (
    '<a href="/osp">Home</a>'
    '<a href="/osp/start?kind=onboarding">Register company</a>'
    '<a href="/osp/start?kind=signin">Sign in</a>'
)


def portal(title: str, body: str, show_title: bool = True) -> str:
    return page(title, body, brand="OSP 2.0", tagline="Demo portal", theme="portal", home="/osp", nav=NAV, show_title=show_title)


def osp_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(portal(title, body + '<p><a class="button secondary" href="/osp">Back to the start page</a></p>'))


@router.get("/osp", response_class=HTMLResponse)
def home():
    rows = "".join(
        f"<tr><td>{escape(e['company']['legal_name'])}</td><td><code>{escape(ebwoid)}</code></td>"
        f"<td>{escape(e['registered_at'])}</td><td>{escape(e['by'])}</td>"
        f"<td>{escape(e['representation']['result'])}</td>"
        f'<td><a href="/osp/registrations/{escape(ebwoid)}">Verification attestation</a></td></tr>'
        for ebwoid, e in registrations().items()
    )
    registered = (
        '<div class="box"><h2>Registered companies</h2><table><tr><th>Company</th><th>EBWOID</th>'
        f"<th>Registered</th><th>By</th><th>Representation</th><th></th></tr>{rows}</table>"
        '<form method="post" action="/osp/reset" onsubmit="return confirm(\'Delete all registrations of the portal?\')">'
        '<p><button class="danger">Reset portal</button></p></form></div>'
        if rows
        else '<div class="box"><h2>Registered companies</h2><p class="muted">None yet.</p></div>'
    )
    body = (
        '<div class="hero"><h1>Welcome to the OSP 2.0 portal</h1>'
        "<p>An onboarding service provider that runs its own portal: it registers companies in the dataspace "
        "and signs in their representatives, with EUDI Wallet and Business Wallet through the EBW-Connector.</p></div>"
        '<div class="grid">'
        '<div class="box"><h2>Register company</h2><p>First PID and mandate from the EUDI Wallet, '
        "then the LPID from the Business Wallet. Result: the verification attestation for the registration.</p>"
        '<p><a class="button" href="/osp/start?kind=onboarding">Register company</a></p>'
        '<p class="muted"><code>openid profile representation company attestation</code></p></div>'
        '<div class="box"><h2>Sign in</h2><p>PID and mandate from the EUDI Wallet. '
        "The portal shows which company the person acts for.</p>"
        '<p><a class="button" href="/osp/start?kind=signin">Sign in with EUDI Wallet</a></p>'
        '<p class="muted"><code>openid profile representation</code></p></div>'
        "</div>" + registered
    )
    return HTMLResponse(portal("OSP 2.0 portal", body, show_title=False))


@router.post("/osp/reset")
def reset():
    """Forgets all registrations, for a fresh demo."""
    REGISTRATIONS.unlink(missing_ok=True)
    return RedirectResponse("/osp", status_code=303)


@router.get("/osp/registrations/{ebwoid}", response_class=HTMLResponse)
def registration(ebwoid: str):
    entry = registrations().get(ebwoid)
    if entry is None:
        return osp_page("Not registered", "<p>This company is not registered at the portal.</p>")
    body = (
        f"<p>Registered on {escape(entry['registered_at'])} by {escape(entry['by'])}.</p>"
        f"<pre>{escape(json.dumps(entry['attestation'], indent=1, ensure_ascii=False))}</pre>"
    )
    return osp_page(entry["company"]["legal_name"], body)


@router.get("/osp/start")
def start(kind: str = "signin"):
    kind = kind if kind in SCOPES else "signin"
    try:
        url, flow = client.start(SCOPES[kind])
    except Exception as exc:
        return osp_page("EBW-Connector not reachable", f'<p class="fail">{escape(str(exc))}</p>')
    response = RedirectResponse(url, status_code=303)
    flows.save(response, {**flow, "kind": kind})
    return response


def check_attestation(token: str) -> tuple[dict, list[str]]:
    """Checks as the registration (C1-M2) would: signature, typ, aud, exp."""
    problems = []
    try:
        header, payload = client.verify_signed(token)
    except OidcError as exc:
        return {}, [str(exc)]
    if header.get("typ") != "ebw-attestation+jwt":
        problems.append("typ is not ebw-attestation+jwt")
    if "portal-registration" not in ([payload.get("aud")] if isinstance(payload.get("aud"), str) else payload.get("aud", [])):
        problems.append("aud does not contain portal-registration")
    if payload.get("exp", 0) < time.time():
        problems.append("expired")
    return payload, problems


def representation_line(claims: dict) -> str:
    result = claims.get("representation_result", "–")
    reasons = ", ".join(claims.get("representation_reasons", []))
    text = f"Representation: <b>{escape(result)}</b>" + (f" ({escape(reasons)})" if reasons else "")
    if claims.get("representation_company_name"):
        text += f" for {escape(claims['representation_company_name'])} ({escape(claims.get('representation_role', ''))})"
    return f"<p>{text}</p>"


@router.get("/osp/callback", response_class=HTMLResponse)
def callback(request: Request):
    flow = flows.load(request)
    kind = flow.get("kind", "signin")
    try:
        claims, tokens = client.finish(dict(request.query_params), flow)
    except (OidcError, KeyError) as exc:
        return osp_page(TITLES.get(kind, "Result"), f'<p class="fail">Not successful</p><pre>{escape(str(exc))}</pre>')
    name = f"{claims.get('given_name', '')} {claims.get('family_name', '')}".strip()
    shown = {k: v for k, v in claims.items() if k not in ("iss", "aud", "exp", "iat", "auth_time", "nonce")}
    details = "<details><summary>ID token</summary>" + claims_table(shown) + "</details>"

    if kind == "onboarding":
        payload, problems = check_attestation(tokens.get("ebw_attestation", ""))
        if problems:
            body = f'<p class="fail">Verification attestation invalid: {escape("; ".join(problems))}</p>' + details
        else:
            entry = register(payload)
            company = entry["company"]
            body = (
                f'<p class="ok">{escape(company["legal_name"])} is registered at the portal.</p>'
                f"<p>By {escape(name)}. EBWOID <code>{escape(company['ebwoid'])}</code>.</p>"
                + representation_line(claims)
                + "<p class=\"muted\">The verification attestation is valid: signature against the JWKS of the EBW-Connector, typ, aud and exp, as C1-M2 checks.</p>"
                + "<details><summary>Verification attestation</summary>"
                + f"<pre>{escape(json.dumps(payload, indent=1, ensure_ascii=False))}</pre></details>"
                + details
            )
    else:
        company_id = claims.get("representation_company_id")
        entry = registrations().get(company_id or "")
        if entry:
            status = f'<p class="ok">{escape(entry["company"]["legal_name"])} is registered at the portal (since {escape(entry["registered_at"])}).</p>'
        elif company_id:
            status = f'<p class="fail">The represented company <code>{escape(company_id)}</code> is not registered at the portal yet.</p>'
        else:
            status = '<p class="muted">No confirmed company in the sign-in.</p>'
        body = f'<p class="ok">Signed in: {escape(name)}</p>' + representation_line(claims) + status + details
    response = osp_page(TITLES.get(kind, "Result"), body)
    flows.clear(response)
    return response


@router.get("/osp/jwks")
def jwks():
    return {"keys": [signing_jwk(config.OSP_KEY)]}
