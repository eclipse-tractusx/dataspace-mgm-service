# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Pages of a transaction (C5-M1 6.6, 7.3)."""

import json
from html import escape

from common.web import page, qr
from connector import config
from connector.transactions import Step, Transaction

TEXT = {
    "title": "Identify with your wallet",
    "tagline": "verification of credentials",
    "asks": "{client} wants to check:",
    "person_step": "EUDI Wallet",
    "company_step": "Business Wallet",
    "pid": "person identification data (PID) from your EUDI Wallet",
    "mandate": "mandate from your EUDI Wallet",
    "lpid": "company identification (LPID) from the company's Business Wallet",
    "scan": "Scan the QR code with your EUDI Wallet, or open it on this device:",
    "open_wallet": "Open in wallet",
    "bw_intro": "Now open your company's Business Wallet. Enter its wallet address once; this browser remembers it.",
    "bw_address": "Wallet address of the Business Wallet",
    "open_bw": "Open in Business Wallet",
    "copy_intro": "Or copy this link and paste it into the Business Wallet:",
    "copy": "Copy link",
    "waiting": "This page continues as soon as the wallet has answered.",
    "done_title": "Step done",
    "done": "The wallet has answered. Please continue on your other device.",
    "error_title": "Invalid request",
}

POLL = """<script>
const seen = %s;
setInterval(async () => {
  try {
    const response = await fetch("/transactions/%s/status");
    if (!response.ok) return;
    const now = await response.json();
    if (now.status !== seen.status || now.step !== seen.step) location.reload();
  } catch (e) {}
}, 2000);
</script>"""

BUSINESS_WALLET = """<script>
const storageKey = "ebw-business-wallet-address";
const input = document.getElementById("bw-address");
try { input.value = localStorage.getItem(storageKey) || ""; } catch (e) {}
function openBusinessWallet() {
  const address = input.value.trim();
  if (!address) { input.focus(); return; }
  try { localStorage.setItem(storageKey, address); } catch (e) {}
  location.href = address + (address.includes("?") ? "&" : "?") + %s;
}
function copyRequest() { navigator.clipboard.writeText(document.getElementById("request-link").textContent); }
</script>"""


def _wallet_link(step: Step) -> str:
    return f"{config.WALLET_URL_SCHEME}?{step.link_params}"


def transaction_page(tx: Transaction) -> str:
    t = TEXT
    step = tx.step
    requested = "".join(f"<li>{escape(t[cid])}</li>" for s in tx.steps for cid in s.credential_ids)
    progress = "".join(
        f'<span class="{"done" if s.status == "VERIFIED" else "current" if s is step else ""}">'
        f'{i + 1}. {escape(t[s.name + "_step"])}</span>'
        for i, s in enumerate(tx.steps)
    )
    body = f"<p>{escape(t['asks'].format(client=tx.client.get('name', tx.client['clientId'])))}</p><ul>{requested}</ul>"
    if len(tx.steps) > 1:
        body += f'<div class="steps">{progress}</div>'
    if step.name == "person":
        link = _wallet_link(step)
        body += (
            f'<div class="box"><h2>{escape(t["person_step"])}</h2><p>{escape(t["scan"])}</p>'
            + qr(link)
            + f'<p><a class="button" id="wallet-link" href="{escape(link)}">{escape(t["open_wallet"])}</a></p></div>'
        )
    else:
        body += (
            f'<div class="box"><h2>{escape(t["company_step"])}</h2><p>{escape(t["bw_intro"])}</p>'
            f'<label for="bw-address">{escape(t["bw_address"])}</label>'
            '<input id="bw-address" type="url" placeholder="https://…/present">'
            f'<p><button onclick="openBusinessWallet()">{escape(t["open_bw"])}</button></p>'
            f'<p class="muted">{escape(t["copy_intro"])}</p><pre id="request-link">{escape(_wallet_link(step))}</pre>'
            f'<p><button class="secondary" onclick="copyRequest()">{escape(t["copy"])}</button></p></div>'
            + BUSINESS_WALLET % json.dumps(step.link_params)
        )
    body += f'<p class="muted">{escape(t["waiting"])}</p>'
    body += POLL % (json.dumps({"status": tx.status, "step": step.name}), tx.id)
    return page(t["title"], body, brand="EBW-Connector", theme="connector", tagline=t["tagline"])


def done_page() -> str:
    return page(TEXT["done_title"], f"<p>{escape(TEXT['done'])}</p>", brand="EBW-Connector", theme="connector", tagline=TEXT["tagline"])


def error_page(message: str) -> str:
    return page(TEXT["error_title"], f'<p class="fail">{escape(message)}</p>', brand="EBW-Connector", theme="connector", tagline=TEXT["tagline"])
