# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""State of the Business Wallet in a JSON file: held credentials and issued mandates."""

import json
import time

from common import sdjwt
from business_wallet import config

PATH = config.DATA_DIR / "wallet.json"


def load() -> dict:
    return json.loads(PATH.read_text()) if PATH.exists() else {"credentials": [], "mandates": []}


def save(state: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False))


def credentials() -> list[str]:
    return load()["credentials"]


def add_credential(credential: str) -> None:
    state = load()
    state["credentials"].append(credential)
    save(state)


def lpid() -> dict | None:
    """Claims of the most recent LPID, or None."""
    for credential in reversed(credentials()):
        if sdjwt.payload_of(credential).get("vct") == config.LPID_VCT:
            _, disclosures, _ = sdjwt.split(credential)
            return sdjwt.resolve(sdjwt.payload_of(credential), disclosures)
    return None


def mandates() -> list[dict]:
    return load()["mandates"]


def add_mandate(mandate: dict) -> None:
    state = load()
    state["mandates"].append({**mandate, "state": "OFFERED", "created_at": time.strftime("%Y-%m-%d %H:%M")})
    save(state)


def update_mandate(mandate_id: str, **changes) -> dict | None:
    state = load()
    for mandate in state["mandates"]:
        if mandate["id"] == mandate_id:
            mandate.update(changes)
            save(state)
            return mandate
    return None
