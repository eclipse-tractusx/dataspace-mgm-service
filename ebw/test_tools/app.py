# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Test tools: test issuer (PID provider and register), trust list of the core services, demo OSP."""

import json
import os
import time
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from common.issuer import Issuer
from common.jose import sign_jws, signing_jwk, x5c
from common.statuslist import StatusList
from common.web import OFFER_SCRIPT, offer_box, page, qr, read_form
from test_tools import config, osp
from test_tools.data import DEFINITIONS, TYPES, claims_with

# Status lists are read by the EBW-Connector only, so a local address survives a new tunnel address.
STATUS_BASE_URL = (os.environ.get("STATUS_BASE_URL") or config.PUBLIC_URL).rstrip("/")
REGISTRY = config.DATA_DIR / "issued.json"

status_list = StatusList(config.DATA_DIR / "status-list.json", f"{STATUS_BASE_URL}/status-lists/1")


def load_registry() -> list[dict]:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []


def record(cid: str, claims: dict, status: dict | None, label: str) -> None:
    registry = load_registry()
    registry.append(
        {
            "index": status["status_list"]["idx"] if status else None,
            "type": TYPES[cid],
            "label": label,
            "issued_at": time.strftime("%Y-%m-%d %H:%M"),
        }
    )
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(registry, indent=1, ensure_ascii=False))


issuer = Issuer(
    config.PUBLIC_URL,
    config.ISSUER_KEY,
    {"kid": signing_jwk(config.ISSUER_KEY)["kid"], "x5c": x5c(config.ISSUER_CERT)},
    DEFINITIONS,
    "EBW test issuer",
    status_list,
    on_issued=record,
    validity=config.CREDENTIAL_VALIDITY_SECONDS,
)

app = FastAPI(title="EBW test tools")
app.include_router(issuer.router)
app.include_router(osp.router)

TAB_STYLE = """<style>
.tabs { display: flex; flex-wrap: wrap; gap: .3rem; border-bottom: 2px solid var(--line); margin: .8rem 0 .6rem; }
.tabs button { background: none; color: var(--primary-dark); margin: 0 0 -2px; padding: .5rem .9rem;
               border-radius: var(--radius) var(--radius) 0 0; border-bottom: 2px solid transparent; }
.tabs button.active { background: var(--soft); border-bottom-color: var(--primary); font-weight: 600; }
</style>"""

TAB_SCRIPT = """<script>
function showTab(key) {
  const buttons = [...document.querySelectorAll(".tabs button")];
  if (!buttons.some((b) => b.dataset.tab === key)) key = buttons[0].dataset.tab;
  buttons.forEach((b) => { b.classList.toggle("active", b.dataset.tab === key); b.setAttribute("aria-selected", b.dataset.tab === key); });
  document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.dataset.panel !== key; });
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  history.replaceState(null, "", "?tab=" + b.dataset.tab);
  showTab(b.dataset.tab);
}));
showTab(new URLSearchParams(location.search).get("tab"));
</script>"""


def offer_tabs(tabs: list[tuple[str, str, str, str, str]]) -> str:
    """Offers as tabs (key, label, text, offer ID, link): only one QR code is visible, so the wrong one is not scanned."""
    buttons = "".join(
        f'<button type="button" role="tab" data-tab="{key}"{" class=\"active\"" if i == 0 else ""}>{escape(label)}</button>'
        for i, (key, label, *_) in enumerate(tabs)
    )
    panels = "".join(
        f'<div class="tab-panel" role="tabpanel" data-panel="{key}"{"" if i == 0 else " hidden"}>'
        f'<p class="muted">{escape(text)}</p>'
        + offer_box(
            offer_id,
            qr(link) + f'<p><a class="button" href="{escape(link)}">Open in wallet</a></p>',
            f'<a class="button secondary" href="/?tab={key}">New QR code</a>',
        )
        + "</div>"
        for i, (key, _, text, offer_id, link) in enumerate(tabs)
    )
    return f'<div class="tabs" role="tablist">{buttons}</div>{panels}{TAB_SCRIPT}'


COPY = """<script>
function copyText(id) { navigator.clipboard.writeText(document.getElementById(id).textContent); }
</script>"""


@app.get("/", response_class=HTMLResponse)
def index():
    person_offer, person_link = issuer.create_offer({"pid": claims_with("pid", None), "mandate": claims_with("mandate", None)}, "Erika Mustermann")
    # Some wallets (for example Paradym) take only the first credential of an offer
    pid_offer, pid_link = issuer.create_offer({"pid": claims_with("pid", None)}, "Erika Mustermann")
    mandate_offer, mandate_link = issuer.create_offer({"mandate": claims_with("mandate", None)}, "Erika Mustermann")
    company_offer, company_link = issuer.create_offer({"lpid": claims_with("lpid", None)}, "Beispiel Maschinenbau GmbH")
    rows = "".join(
        f"<tr><td>{entry['index']}</td><td>{escape(entry['type'])}</td><td>{escape(entry['label'])}</td>"
        f"<td>{escape(entry['issued_at'])}</td><td>"
        + (
            ""
            if entry["index"] is None
            else f'<form method="post" action="/revoke/{entry["index"]}">'
            + (
                '<span class="fail">revoked</span> <button class="secondary">restore</button>'
                if status_list.is_revoked(entry["index"])
                else '<button class="danger">revoke</button>'
            )
            + "</form>"
        )
        + "</td></tr>"
        for entry in reversed(load_registry()[-30:])
    )
    body = (
        '<div class="box"><h2>EUDI Wallet of the person</h2>'
        "<p>Test PID and mandate from the register: Erika Mustermann, legal representative "
        "of Beispiel Maschinenbau GmbH. Choose the tab that fits your wallet: Hidy picks up both credentials "
        "from one offer, Paradym only the first one, so scan PID and then Mandate with it.</p>"
        + offer_tabs(
            [
                ("both", "PID and Mandate", "Both credentials in one offer.", person_offer, person_link),
                ("pid", "PID", "Only the test PID. Scan this first.", pid_offer, pid_link),
                ("mandate", "Mandate", "Only the mandate. Scan it after the PID with the same wallet.",
                 mandate_offer, mandate_link),
            ]
        )
        + '</div><div class="box"><h2>Test PID for another person</h2>'
        "<p>For example for an employee who gets a power of attorney from the Business Wallet. "
        "Name and date of birth must match the power of attorney.</p>"
        '<form method="post" action="/pid">'
        '<label for="given_name">Given name</label><input id="given_name" name="given_name" required>'
        '<label for="family_name">Family name</label><input id="family_name" name="family_name" required>'
        '<label for="birthdate">Date of birth</label><input id="birthdate" name="birthdate" type="date" required>'
        "<button>Offer test PID</button></form></div>"
        '<div class="box"><h2>Business Wallet</h2>'
        "<p>LPID of Beispiel Maschinenbau GmbH. Paste the link in the Business Wallet under "
        "“Fetch the company credential (LPID)”.</p>"
        + offer_box(
            company_offer,
            f'<pre id="lpid-link">{escape(company_link)}</pre>'
            "<p><button class=\"secondary\" onclick=\"copyText('lpid-link')\">Copy link</button></p>",
            '<a class="button secondary" href="/">New link</a>',
        )
        + '</div><div class="box"><h2>Core services</h2><p>Signed trust list: '
        '<a href="/trust-list.json">view</a> · <a href="/trust-list">as JWS</a></p></div>'
        '<div class="box"><h2>OSP 2.0 demo portal</h2><p>Sign-in and onboarding through the EBW-Connector: '
        '<a href="/osp">Open the portal</a></p></div>'
        '<div class="box"><h2>Issued credentials</h2>'
        f"<table><tr><th>No.</th><th>Type</th><th>For</th><th>Time</th><th>Status</th></tr>{rows}</table></div>"
        + COPY
        + OFFER_SCRIPT
    )
    return HTMLResponse(page("Test tools", body, brand="EBW test tools", head=TAB_STYLE))


@app.post("/pid", response_class=HTMLResponse)
async def pid_offer(request: Request):
    form = await read_form(request)
    person = {k: form.get(k, "").strip() for k in ("given_name", "family_name", "birthdate")}
    if not all(person.values()):
        return RedirectResponse("/", status_code=303)
    offer_id, link = issuer.create_offer({"pid": claims_with("pid", person)}, f"{person['given_name']} {person['family_name']}")
    renew = (
        '<form method="post" action="/pid">'
        + "".join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in person.items())
        + '<button class="secondary">New QR code</button></form>'
    )
    body = (
        f"<p>Test PID for <b>{escape(person['given_name'])} {escape(person['family_name'])}</b>, "
        f"born {escape(person['birthdate'])}. Scan with the EUDI Wallet of this person.</p>"
        + offer_box(offer_id, qr(link) + f'<p><a class="button" href="{escape(link)}">Open in wallet</a></p>', renew)
        + '<p><a class="button secondary" href="/">Back</a></p>'
        + OFFER_SCRIPT
    )
    return HTMLResponse(page("Test PID", body, brand="EBW test tools"))


@app.post("/revoke/{index}")
def revoke(index: int):
    status_list.set_revoked(index, not status_list.is_revoked(index))
    return RedirectResponse("/", status_code=303)


@app.post("/api/offers")
async def api_offer(request: Request):
    """For automated tests: offer with test variants, e.g. {"credentials": {"pid": {}, "mandate": {"role": "x"}}}."""
    body = await request.json()
    wanted = body.get("credentials") or {"pid": {}, "mandate": {}}
    claims = {cid: claims_with(cid, overrides) for cid, overrides in wanted.items() if cid in DEFINITIONS}
    offer_id, link = issuer.create_offer(claims, body.get("label", "API"))
    return {"offer_id": offer_id, "link": link}


@app.post("/api/revoke/{index}")
def api_revoke(index: int):
    status_list.set_revoked(index, True)
    return {"revoked": index}


def trust_list_payload() -> dict:
    now = int(time.time())
    return {
        "iss": config.PUBLIC_URL,
        "iat": now,
        "exp": now + 24 * 3600,
        "entries": [
            {
                "name": "ebw-test-issuer",
                "credential_types": ["PID", "LPID", "MANDATE"],
                "jwks": {"keys": [signing_jwk(config.ISSUER_KEY)]},
            }
        ],
    }


@app.get("/trust-list")
def trust_list():
    header = {"typ": "trust-list+jwt", "kid": signing_jwk(config.TRUST_LIST_KEY)["kid"]}
    return Response(sign_jws(header, trust_list_payload(), config.TRUST_LIST_KEY), media_type="application/jwt")


@app.get("/trust-list.json")
def trust_list_json():
    return JSONResponse(trust_list_payload())


@app.get("/trust-list/signer-jwks")
def trust_list_signer():
    return {"keys": [signing_jwk(config.TRUST_LIST_KEY)]}
