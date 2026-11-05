# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Business Wallet in the browser: holds the company's LPID, presents it, issues mandates to employees.
People sign in with their EUDI Wallet through the EBW-Connector (C5-M1)."""

from html import escape
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from business_wallet import config, store
from common import holder
from common.issuer import Issuer
from common.jose import random_token, signing_jwk, x5c
from common.oidc_client import OidcClient, OidcError
from common.statuslist import StatusList
from common.web import OFFER_SCRIPT, CookieSession, offer_box, page, qr, read_form

ROLE = {"legal_representative": "Administrator"}
MANDATE_DEFINITION = {
    "mandate": {
        "vct": config.MANDATE_VCT,
        "name": "Power of attorney",
        "labels": {
            "representative": "Authorised person",
            "represented": "Company",
            "representation_type": "Type of representation",
            "role": "Role",
            "valid_until": "Valid until",
        },
    }
}

status_list = StatusList(config.DATA_DIR / "status-list.json", f"{config.STATUS_BASE_URL}/status-lists/1")


def mark_issued(cid: str, claims: dict, status: dict | None, label: str) -> None:
    store.update_mandate(label, state="ISSUED", status_index=status["status_list"]["idx"] if status else None)


issuer = Issuer(
    config.PUBLIC_URL,
    config.WALLET_KEY,
    {"kid": signing_jwk(config.WALLET_KEY)["kid"], "x5c": x5c(config.WALLET_CERT)},
    MANDATE_DEFINITION,
    "Business Wallet",
    status_list,
    on_issued=mark_issued,
    validity=config.MANDATE_VALIDITY_SECONDS,
)
oidc = OidcClient(config.CONNECTOR_URL, config.CLIENT_ID, f"{config.PUBLIC_URL}/login/callback", config.WALLET_KEY)
sessions = CookieSession("bw_session", config.SESSION_SECRET, config.SECURE)
flows = CookieSession("bw_flow", config.SESSION_SECRET, config.SECURE, max_age=900)
offer_links: dict[str, str] = {}  # mandate ID -> link of its current offer
pending: dict[str, dict] = {}  # ID -> request object of a presentation request

app = FastAPI(title="Business Wallet")
app.include_router(issuer.router)

COPY = """<script>
function copyText(id) { navigator.clipboard.writeText(document.getElementById(id).textContent); }
</script>"""


def company_name() -> str:
    lpid = store.lpid()
    return lpid.get("legal_name", "Company") if lpid else "not set up yet"


def bw_page(title: str, body: str, request: Request | None = None, show_title: bool = True) -> HTMLResponse:
    issuer.display_name = f"Business Wallet {company_name()}"
    current = user(request) if request is not None else {}
    nav = '<a href="/">Home</a>'
    if current:
        nav += f'<span>{escape(current["name"])} · {escape(current["role"])}</span><a href="/logout">Sign out</a>'
    elif store.lpid() is not None:
        nav += '<a href="/login">Sign in</a>'
    return HTMLResponse(
        page(title, body, brand="Business Wallet", tagline=company_name(), theme="wallet", nav=nav, show_title=show_title)
    )


def message(title: str, text: str, ok: bool = False) -> HTMLResponse:
    css = "ok" if ok else "fail"
    return bw_page(title, f'<div class="box"><p class="{css}">{escape(text)}</p><p><a class="button secondary" href="/">Back to the start page</a></p></div>')


def user(request: Request) -> dict:
    return sessions.load(request).get("user") or {}


def credential_card(lpid: dict) -> str:
    address = lpid.get("address") or {}
    place = " ".join(filter(None, [address.get("postal_code"), address.get("locality")]))
    return (
        '<div class="credential"><div class="kind">Company credential · LPID</div>'
        f'<div class="name">{escape(lpid.get("legal_name", ""))}</div>'
        f'<div class="row">EBWOID <code>{escape(lpid.get("ebwoid", ""))}</code></div>'
        f'<div class="row">EUID <code>{escape(lpid.get("euid", "–"))}</code></div>'
        f'<div class="row">{escape(address.get("street_address", ""))}, {escape(place)}, {escape(lpid.get("country", ""))}</div></div>'
    )


def address_box() -> str:
    return (
        '<div class="box"><h2>Wallet address</h2><p>Enter this address once on the page of the EBW-Connector '
        "when an OSP asks for the company credential.</p>"
        f'<pre id="wallet-address">{escape(config.WALLET_ADDRESS)}</pre>'
        "<p><button class=\"secondary\" onclick=\"copyText('wallet-address')\">Copy address</button></p></div>"
    )


def reset_form() -> str:
    return (
        '<form method="post" action="/reset" onsubmit="return confirm(\'Reset the Business Wallet? '
        'The LPID and the powers of attorney are deleted.\')"><p><button class="danger">Reset Business Wallet</button></p></form>'
    )


# Start page


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if "request_uri" in request.query_params:  # wallet address entered without /present
        return RedirectResponse(f"/present?{request.url.query}", status_code=303)
    lpid = store.lpid()
    if lpid is None:
        body = (
            '<div class="hero"><h1>Set up the Business Wallet</h1><p>This Business Wallet does not hold a '
            "company credential yet. First fetch the LPID from the register.</p></div>" + receive_form()
        )
        return bw_page("Set up the Business Wallet", body, request, show_title=False)
    current = user(request)
    if not current:
        body = (
            credential_card(lpid)
            + '<div class="box"><h2>Sign in</h2><p>Sign in with your EUDI Wallet. You need a '
            f"mandate for {escape(lpid.get('legal_name', ''))}.</p>"
            '<p><a class="button" href="/login">Sign in with EUDI Wallet</a></p></div>'
            + address_box()
            + reset_form()
            + COPY
        )
        return bw_page("Business Wallet", body, request, show_title=False)
    admin = current["role"] == "Administrator"
    function = f", {escape(current['function'])}" if current.get("function") else ""
    body = (
        f"<h1>Hello {escape(current['name'].split(' ')[0])}</h1>"
        f'<p class="muted">{escape(current["role"])}{function} of {escape(lpid.get("legal_name", ""))}</p>'
        + credential_card(lpid)
        + mandate_list(admin)
        + '<div class="grid">'
        + (issue_form() if admin else "")
        + paste_form()
        + "</div>"
        + address_box()
        + (receive_form("Fetch a new company credential") + reset_form() if admin else "")
        + COPY
    )
    return bw_page("Business Wallet", body, request, show_title=False)


def receive_form(title: str = "Fetch the company credential (LPID)") -> str:
    return (
        f'<div class="box"><h2>{escape(title)}</h2><form method="post" action="/receive">'
        '<label for="offer">Link of the offer from the register (openid-credential-offer://…)</label>'
        '<textarea id="offer" name="offer" rows="3" required></textarea>'
        "<button>Fetch</button></form></div>"
    )


def paste_form() -> str:
    return (
        '<div class="box"><h2>Paste a request</h2><form method="get" action="/present">'
        '<label for="link">Link of the request (openid4vp://…), if the wallet did not open directly</label>'
        '<textarea id="link" name="link" rows="3" required></textarea>'
        "<button>Open request</button></form></div>"
    )


def issue_form() -> str:
    return (
        '<div class="box"><h2>Issue a power of attorney</h2>'
        "<p>It goes into the EUDI Wallet of the person as a mandate.</p>"
        '<form method="post" action="/mandates">'
        '<label for="given_name">Given name</label><input id="given_name" name="given_name" required>'
        '<label for="family_name">Family name</label><input id="family_name" name="family_name" required>'
        '<label for="birthdate">Date of birth</label><input id="birthdate" name="birthdate" type="date" required>'
        '<label for="role">Role</label><input id="role" name="role" placeholder="for example Purchasing" required>'
        '<label for="valid_until">Valid until</label><input id="valid_until" name="valid_until" type="date" required>'
        "<button>Issue power of attorney</button></form></div>"
    )


def mandate_list(admin: bool) -> str:
    rows = ""
    for mandate in reversed(store.mandates()):
        actions = ""
        if admin and mandate["state"] == "OFFERED":
            actions = f'<a href="/mandates/{mandate["id"]}">Show QR code</a>'
        elif admin and mandate["state"] == "ISSUED":
            actions = f'<form method="post" action="/mandates/{mandate["id"]}/revoke"><button class="danger">Revoke</button></form>'
        state = {"OFFERED": "offered", "ISSUED": "issued", "REVOKED": "revoked"}[mandate["state"]]
        badge = f'<span class="badge{" off" if mandate["state"] == "REVOKED" else ""}">{state}</span>'
        rows += (
            f"<tr><td>{escape(mandate['given_name'])} {escape(mandate['family_name'])}</td><td>{escape(mandate['role'])}</td>"
            f"<td>{escape(mandate['valid_until'])}</td><td>{badge}</td><td>{actions}</td></tr>"
        )
    if not rows:
        return ""
    return (
        '<div class="box"><h2>Powers of attorney</h2><table><tr><th>Person</th><th>Role</th><th>Valid until</th>'
        f"<th>Status</th><th></th></tr>{rows}</table></div>"
    )


@app.post("/reset")
def reset(request: Request):
    """Back to an empty Business Wallet. Keys and the status list stay, so indexes are not reused."""
    if store.lpid() is not None and user(request) and user(request).get("role") != "Administrator":
        return message("Not allowed", "Only administrators reset the Business Wallet.")
    store.save({"credentials": [], "mandates": []})
    offer_links.clear()
    pending.clear()
    response = RedirectResponse("/", status_code=303)
    sessions.clear(response)
    return response


# Receiving the LPID


@app.post("/receive")
async def receive(request: Request):
    if store.lpid() is not None and user(request).get("role") != "Administrator":
        return message("Not allowed", "Only administrators fetch a new company credential.")
    link = (await read_form(request)).get("offer", "")
    try:
        with httpx.Client(timeout=10) as http:
            offer = holder.resolve_offer(link, http)
            credentials = holder.obtain_credentials(offer, config.WALLET_KEY, http)
    except (holder.WalletError, httpx.HTTPError, ValueError, KeyError) as exc:
        return message("Fetching failed", str(exc))
    for credential in credentials.values():
        store.add_credential(credential)
    if store.lpid() is None:
        return message("No company credential", f"The offer contained no LPID ({config.LPID_VCT}).")
    return RedirectResponse("/", status_code=303)


# Sign-in through the EBW-Connector


@app.get("/login")
def login(request: Request, next: str = "/"):
    try:
        url, flow = oidc.start("openid profile representation")
    except (httpx.HTTPError, KeyError) as exc:
        return message("EBW-Connector not reachable", str(exc))
    response = RedirectResponse(url, status_code=303)
    flows.save(response, {**flow, "next": next if next.startswith("/") else "/"})
    return response


@app.get("/login/callback")
def login_callback(request: Request):
    flow = flows.load(request)
    try:
        claims, _ = oidc.finish(dict(request.query_params), flow)
    except (OidcError, KeyError, httpx.HTTPError) as exc:
        return message("Sign-in failed", str(exc))
    lpid = store.lpid() or {}
    if claims.get("representation_result") != "CONFIRMED":
        reasons = ", ".join(claims.get("representation_reasons", [])) or "none stated"
        return message("Sign-in refused", f"The mandate is not confirmed ({reasons}).")
    if claims.get("representation_company_id") != lpid.get("ebwoid"):
        return message("Sign-in refused", "The mandate is for another company.")
    session_user = {
        "sub": claims["sub"],
        "name": f"{claims.get('given_name', '')} {claims.get('family_name', '')}".strip(),
        "role": ROLE.get(claims.get("representation_type"), "Employee"),
        "function": claims.get("representation_role"),
        "trust": claims.get("representation_trust"),
    }
    response = RedirectResponse(flow.get("next", "/"), status_code=303)
    sessions.save(response, {"user": session_user})
    flows.clear(response)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    sessions.clear(response)
    return response


# Presenting the LPID (wallet address)


@app.get("/present", response_class=HTMLResponse)
def present(request: Request):
    params = dict(request.query_params)
    if "link" in params:
        params = holder.query_params(params["link"])
    if not user(request):
        target = "/present?" + urlencode({k: params[k] for k in ("client_id", "request_uri") if k in params})
        return RedirectResponse(f"/login?{urlencode({'next': target})}", status_code=303)
    try:
        with httpx.Client(timeout=10) as http:
            request_object = holder.read_request(params, http)
    except (holder.WalletError, httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return message("Invalid request", str(exc))
    queries = holder.requested(request_object)
    missing = [q["id"] for q in queries if holder.find_credential(store.credentials(), q["vct_values"]) is None]
    request_id = random_token()
    pending[request_id] = request_object
    verifier = request_object["client_id"].split(":", 1)[-1]
    if verifier.startswith("http"):
        verifier = urlsplit(verifier).hostname
    name = request_object.get("client_metadata", {}).get("client_name", "")
    wanted = "".join(
        f"<li><b>{escape(q['id'])}</b> ({escape(', '.join(q['vct_values']))}): {escape(', '.join(q['claims']))}</li>"
        for q in queries
    )
    body = (
        f'<div class="box"><p><b>{escape(verifier)}</b>{" for " + escape(name) if name else ""} asks for credentials of the company:</p>'
        f"<ul>{wanted}</ul>"
    )
    if missing:
        body += f'<p class="fail">Not available: {escape(", ".join(missing))}</p>'
        body += f'<form method="post" action="/present/{request_id}/decline"><button class="secondary">Decline</button></form>'
    else:
        body += (
            f'<form method="post" action="/present/{request_id}/approve" style="display:inline"><button>Approve</button></form>'
            f'<form method="post" action="/present/{request_id}/decline" style="display:inline"><button class="secondary">Decline</button></form>'
        )
    return bw_page("Request", body + "</div>", request)


def follow(answer: dict) -> RedirectResponse | HTMLResponse:
    if answer.get("redirect_uri"):
        return RedirectResponse(answer["redirect_uri"], status_code=303)
    return message("Sent", "The verifier has received the answer.", ok=True)


@app.post("/present/{request_id}/approve")
def approve(request_id: str, request: Request):
    request_object = pending.pop(request_id, None)
    if not user(request) or request_object is None:
        return message("Invalid request", "The request is unknown or has already been answered.")
    try:
        with httpx.Client(timeout=10) as http:
            answer = holder.answer(request_object, store.credentials(), config.WALLET_KEY, http)
    except (holder.WalletError, httpx.HTTPError, ValueError) as exc:
        return message("Sending failed", str(exc))
    return follow(answer)


@app.post("/present/{request_id}/decline")
def decline(request_id: str, request: Request):
    request_object = pending.pop(request_id, None)
    if not user(request) or request_object is None:
        return message("Invalid request", "The request is unknown or has already been answered.")
    try:
        with httpx.Client(timeout=10) as http:
            answer = holder.decline(request_object, http)
    except (holder.WalletError, httpx.HTTPError) as exc:
        return message("Sending failed", str(exc))
    return follow(answer)


# Issuing mandates to employees


def mandate_claims(mandate: dict) -> dict:
    lpid = store.lpid() or {}
    return {
        "representative": {k: mandate[k] for k in ("given_name", "family_name", "birthdate")},
        "represented": {"identifier": lpid.get("ebwoid"), "legal_name": lpid.get("legal_name")},
        "representation_type": "power_of_attorney",
        "role": mandate["role"],
        "valid_until": mandate["valid_until"],
    }


@app.post("/mandates")
async def create_mandate(request: Request):
    if user(request).get("role") != "Administrator":
        return message("Not allowed", "Only administrators issue powers of attorney.")
    form = await read_form(request)
    mandate = {"id": random_token(8), **{k: form.get(k, "").strip() for k in ("given_name", "family_name", "birthdate", "role", "valid_until")}}
    if not all(mandate.values()):
        return message("Incomplete details", "Please fill in all fields.")
    store.add_mandate(mandate)
    return RedirectResponse(f"/mandates/{mandate['id']}", status_code=303)


@app.get("/mandates/{mandate_id}", response_class=HTMLResponse)
def show_mandate(mandate_id: str, request: Request):
    mandate = next((m for m in store.mandates() if m["id"] == mandate_id), None)
    if user(request).get("role") != "Administrator" or mandate is None:
        return message("Not found", "Unknown power of attorney or no permission.")
    if mandate["state"] != "OFFERED":
        return RedirectResponse("/", status_code=303)
    offer_id, link = issuer.create_offer({"mandate": mandate_claims(mandate)}, mandate_id)
    offer_links[mandate_id] = link
    body = (
        f"<div class=\"box\"><p>Power of attorney for <b>{escape(mandate['given_name'])} {escape(mandate['family_name'])}</b> "
        f"({escape(mandate['role'])}, valid until {escape(mandate['valid_until'])}). "
        "The person scans the QR code with their EUDI Wallet.</p>"
        + offer_box(
            offer_id,
            qr(link) + f'<p><a class="button" href="{escape(link)}">Open in wallet</a></p>',
            f'<a class="button secondary" href="/mandates/{mandate_id}">New QR code</a>',
            once=True,
        )
        + '<p><a class="button secondary" href="/">Done</a></p></div>'
        + OFFER_SCRIPT
    )
    return bw_page("Hand over the power of attorney", body, request)


@app.post("/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str, request: Request):
    mandate = next((m for m in store.mandates() if m["id"] == mandate_id), None)
    if user(request).get("role") != "Administrator" or mandate is None or mandate.get("status_index") is None:
        return message("Not possible", "Unknown power of attorney or no permission.")
    status_list.set_revoked(mandate["status_index"])
    store.update_mandate(mandate_id, state="REVOKED")
    return RedirectResponse("/", status_code=303)


@app.get("/jwks")
def jwks():
    """Client key at the EBW-Connector and key of the mandates (C5-M1 6.5 rule 3)."""
    return {"keys": [signing_jwk(config.WALLET_KEY)]}


@app.get("/api/state")
def api_state():
    """For automated tests: company and mandates, without credentials."""
    return {"lpid": store.lpid(), "mandates": store.mandates()}
