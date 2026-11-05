# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Settings of the test tools: test issuer, trust list of the core services, demo OSP."""

import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from common.jose import load_or_create_key, self_signed_cert, signing_jwk

HERE = Path(__file__).parent

PUBLIC_URL = (os.environ.get("PUBLIC_URL") or "http://localhost:8079").rstrip("/")
HOST = urlsplit(PUBLIC_URL).hostname
CONNECTOR_URL = (os.environ.get("CONNECTOR_URL") or "http://localhost:8077").rstrip("/")
KEY_DIR = Path(os.environ.get("KEY_DIR") or HERE / ".keys")
DATA_DIR = Path(os.environ.get("DATA_DIR") or HERE / "data")

ISSUER_KEY = load_or_create_key(KEY_DIR / "issuer.pem")
ISSUER_CERT = self_signed_cert(ISSUER_KEY, HOST, "EBW test issuer")
TRUST_LIST_KEY = load_or_create_key(KEY_DIR / "trust-list.pem")
OSP_KEY = load_or_create_key(KEY_DIR / "osp-client.pem")
OSP_CLIENT_ID = "demo-osp"

# Public key of the trust list for the EBW-Connector (TRUST_LIST_SIGNER_FILE).
(KEY_DIR / "trust-list-signer.json").write_text(json.dumps({"keys": [signing_jwk(TRUST_LIST_KEY)]}, indent=1))

_session_key = KEY_DIR / "session.key"
if not _session_key.exists():
    _session_key.write_bytes(secrets.token_bytes(32))
SESSION_SECRET = _session_key.read_bytes()

CREDENTIAL_VALIDITY_SECONDS = 365 * 24 * 3600
