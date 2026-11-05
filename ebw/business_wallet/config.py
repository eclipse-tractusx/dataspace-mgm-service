# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Settings of the Business Wallet."""

import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from common.jose import load_or_create_key, self_signed_cert

HERE = Path(__file__).parent

PUBLIC_URL = (os.environ.get("PUBLIC_URL") or "http://localhost:8078").rstrip("/")
HOST = urlsplit(PUBLIC_URL).hostname
SECURE = PUBLIC_URL.startswith("https")
CONNECTOR_URL = (os.environ.get("CONNECTOR_URL") or "http://localhost:8077").rstrip("/")
CLIENT_ID = os.environ.get("CLIENT_ID") or "business-wallet"
KEY_DIR = Path(os.environ.get("KEY_DIR") or HERE / ".keys")
DATA_DIR = Path(os.environ.get("DATA_DIR") or HERE / "data")
# Status lists are read by the EBW-Connector only, so a local address survives a new tunnel address.
STATUS_BASE_URL = (os.environ.get("STATUS_BASE_URL") or PUBLIC_URL).rstrip("/")

# One key: holder key of the LPID, issuer key of the mandates, client key at the EBW-Connector (C5-M1 11.2).
WALLET_KEY = load_or_create_key(KEY_DIR / "wallet.pem")
WALLET_CERT = self_signed_cert(WALLET_KEY, HOST, "Business Wallet")
WALLET_ADDRESS = f"{PUBLIC_URL}/present"

_session_key = KEY_DIR / "session.key"
if not _session_key.exists():
    _session_key.write_bytes(secrets.token_bytes(32))
SESSION_SECRET = _session_key.read_bytes()

LPID_VCT = os.environ.get("LPID_VCT") or "urn:tx:test:lpid:1"
MANDATE_VCT = os.environ.get("MANDATE_VCT") or "urn:tx:test:mandate:1"
MANDATE_VALIDITY_SECONDS = 365 * 24 * 3600
