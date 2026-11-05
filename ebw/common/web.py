# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Minimal HTML pages, QR codes, form parsing and signed cookie sessions."""

import base64
import hashlib
import hmac
import json
import time
from html import escape
from urllib.parse import parse_qs

import segno
from fastapi import Request, Response

STYLE = """
:root { --primary: #2e8b57; --primary-dark: #1e6b41; --soft: #e6f2eb; --bg: #fff; --card: #fff; --text: #1f2933;
        --line: #e4e7eb; --bar: #fff; --bar-text: #1f2933; --bar-line: #e4e7eb; --radius: 8px; }
body { font-family: system-ui, sans-serif; margin: 0; color: var(--text); background: var(--bg); }
main { max-width: 860px; margin: 0 auto; padding: 1.2rem 16px 3rem; }
header.bar { background: var(--bar); color: var(--bar-text); border-bottom: 3px solid var(--bar-line); }
header.bar div { max-width: 860px; margin: 0 auto; padding: .8rem 16px; display: flex; flex-wrap: wrap; gap: .4rem 1.2rem; align-items: center; }
header.bar a { color: var(--bar-text); text-decoration: none; }
header.bar .logo { font-weight: 700; font-size: 1.15rem; margin-right: auto; }
header.bar .logo small { font-weight: 400; opacity: .75; margin-left: .4rem; }
header.bar nav { display: flex; flex-wrap: wrap; gap: .3rem 1rem; font-size: .95rem; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.15rem; margin-top: 1.2rem; }
a.button, button { display: inline-block; padding: .6rem 1rem; background: var(--primary); color: #fff; border: 0; border-radius: var(--radius); text-decoration: none; font-size: 1rem; cursor: pointer; margin: 0 .35rem .45rem 0; }
button.secondary, a.button.secondary { background: var(--soft); color: var(--primary-dark); }
button.danger { background: #b42318; }
input, textarea, select { font: inherit; padding: .45rem .6rem; border: 1px solid #c5ccd6; border-radius: var(--radius); width: 100%; box-sizing: border-box; margin-bottom: .6rem; background: #fff; }
label { display: block; font-weight: 600; margin-bottom: .2rem; }
code, pre { background: #f2f4f7; border-radius: 4px; padding: .1rem .3rem; font-size: .85rem; }
pre { padding: .8rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }
table { border-collapse: collapse; width: 100%; } td, th { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
.box { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: .2rem 1rem .8rem; margin: 1rem 0; }
.ok { color: #1e6b41; font-weight: 600; } .fail { color: #b42318; font-weight: 600; } .muted { color: #6b7280; }
.steps { display: flex; gap: .5rem; flex-wrap: wrap; margin: 1rem 0; } .steps span { padding: .3rem .7rem; border-radius: 999px; background: #f2f4f7; }
.steps span.done { background: var(--soft); color: var(--primary-dark); } .steps span.current { background: var(--primary); color: #fff; }
summary { cursor: pointer; color: #6b7280; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
.hero { background: var(--soft); border-radius: var(--radius); padding: 1.2rem 1.4rem; margin: 1rem 0; }
.hero h1 { margin-top: 0; }
.credential { background: linear-gradient(135deg, #1e3a8a, #2563eb); color: #fff; border-radius: 16px; padding: 1.2rem 1.4rem;
              max-width: 440px; box-shadow: 0 8px 20px rgba(30, 58, 138, .25); margin: 1rem 0; }
.credential .kind { text-transform: uppercase; letter-spacing: .08em; font-size: .75rem; opacity: .8; }
.credential .name { font-size: 1.3rem; font-weight: 700; margin: .4rem 0 .8rem; }
.credential .row { font-size: .9rem; opacity: .95; } .credential code { background: rgba(255, 255, 255, .15); color: #fff; }
.badge { display: inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .8rem; background: var(--soft); color: var(--primary-dark); }
.badge.off { background: #fde8e8; color: #b42318; }
"""

# Each party of the demo has its own look, so they are easy to tell apart.
THEMES = {
    "wallet": ":root { --primary: #2563eb; --primary-dark: #1e3a8a; --soft: #e0e9ff; --bg: #f3f5fb; --line: #dfe5f2;"
    " --bar: #16213e; --bar-text: #fff; --bar-line: #2563eb; --radius: 12px; }"
    " .box { box-shadow: 0 2px 8px rgba(22, 33, 62, .06); border: 0; }",
    "portal": ":root { --primary: #6d28d9; --primary-dark: #4c1d95; --soft: #f1eafe; --bg: #fff; --line: #ece7f6;"
    " --bar: #fff; --bar-text: #3b0764; --bar-line: #6d28d9; --radius: 6px; }",
    "connector": ":root { --primary: #2e8b57; --primary-dark: #1e6b41; --soft: #e6f2eb; --bg: #f7f8f9; --line: #e4e7eb;"
    " --bar: #374151; --bar-text: #fff; --bar-line: #2e8b57; }",
}


def page(
    title: str,
    body: str,
    brand: str = "EBW",
    lang: str = "en",
    head: str = "",
    home: str = "/",
    theme: str | None = None,
    tagline: str = "",
    nav: str = "",
    show_title: bool = True,
) -> str:
    """Without a theme: plain page with the brand above the title. With a theme: header bar with brand and nav."""
    style = STYLE + THEMES.get(theme or "", "")
    heading = f"<h1>{escape(title)}</h1>" if show_title else ""
    if theme:
        small = f"<small>{escape(tagline)}</small>" if tagline else ""
        top = (
            f'<header class="bar"><div><a class="logo" href="{escape(home)}">{escape(brand)}{small}</a>'
            f"<nav>{nav}</nav></div></header><main>{heading}{body}</main>"
        )
    else:
        top = f'<main><p class="muted"><a href="{escape(home)}">{escape(brand)}</a></p>{heading}{body}</main>'
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{style}</style>{head}</head><body>{top}</body></html>"
    )


def qr(uri: str) -> str:
    data_uri = segno.make(uri, error="m").svg_data_uri(scale=5, border=2)
    return f'<p><img src="{data_uri}" alt="QR code"></p>'


OFFER_SCRIPT = """<script>
document.querySelectorAll("[data-offer]").forEach((box) => {
  const state = box.querySelector(".offer-state");
  let seconds = 0, open = true;
  function close(text, css, renew) {
    open = false;
    box.querySelector(".offer-content").hidden = true;
    box.querySelector(".offer-renew").hidden = !renew;
    state.className = "offer-state " + css;
    state.textContent = text;
  }
  function show() {
    const rest = String(seconds % 60).padStart(2, "0");
    state.textContent = `Waiting for the wallet, valid for ${Math.floor(seconds / 60)}:${rest}.`;
  }
  async function poll() {
    let now;
    try {
      const response = await fetch(`/oid4vci/offers/${box.dataset.offer}/status`);
      if (!response.ok) return;
      now = await response.json();
    } catch (e) { return; }
    if (now.status === "OPEN") {
      seconds = now.expires_in;
      show();
    } else if (now.status === "EXPIRED") {
      clearInterval(polling);
      close("Expired. This offer no longer works.", "fail", true);
    } else {
      if (now.issued.length === now.offered.length || now.expires_in === 0) clearInterval(polling);
      const names = now.issued.join(", ");
      close(names ? `Picked up: ${names}.` : "Picked up by a wallet, fetching the credentials …", "ok", !box.hasAttribute("data-once"));
    }
  }
  const polling = setInterval(poll, 2000);
  setInterval(() => { if (open && seconds > 0) { seconds -= 1; show(); } }, 1000);
  poll();
});
</script>"""


def offer_box(offer_id: str, content: str, renew: str, once: bool = False) -> str:
    """Offer with its live state; `content` goes away once the offer no longer works, then `renew` appears.
    `once`: nothing to renew after a pick-up. The page adds OFFER_SCRIPT after its offers."""
    return (
        f'<div data-offer="{escape(offer_id)}"{" data-once" if once else ""}><div class="offer-content">{content}</div>'
        f'<p class="offer-state muted"></p><div class="offer-renew" hidden>{renew}</div></div>'
    )


def claims_table(claims: dict) -> str:
    rows = "".join(
        f"<tr><th>{escape(str(k))}</th><td>{escape(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))}</td></tr>"
        for k, v in claims.items()
    )
    return f"<table>{rows}</table>"


async def read_form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body, first value per name."""
    return {k: v[0] for k, v in parse_qs((await request.body()).decode(), keep_blank_values=True).items()}


class CookieSession:
    """JSON in a cookie, signed with HMAC-SHA256. For small values only."""

    def __init__(self, name: str, secret: bytes, secure: bool, max_age: int = 8 * 3600):
        self.name, self.secret, self.secure, self.max_age = name, secret, secure, max_age

    def _sign(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, data, hashlib.sha256).digest()).decode().rstrip("=")

    def load(self, request: Request) -> dict:
        value = request.cookies.get(self.name, "")
        encoded, _, signature = value.partition(".")
        try:
            data = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except ValueError:
            return {}
        if not hmac.compare_digest(signature, self._sign(data)):
            return {}
        session = json.loads(data)
        return session if session.get("_exp", 0) > time.time() else {}

    def save(self, response: Response, session: dict) -> None:
        data = json.dumps({**session, "_exp": int(time.time()) + self.max_age}).encode()
        value = base64.urlsafe_b64encode(data).decode().rstrip("=") + "." + self._sign(data)
        response.set_cookie(
            self.name, value, max_age=self.max_age, httponly=True, samesite="lax", secure=self.secure, path="/"
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(self.name, path="/")
