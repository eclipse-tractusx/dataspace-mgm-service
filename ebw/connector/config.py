# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Settings of the EBW-Connector (C5-M1 README section 4)."""

import base64
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from common.jose import load_or_create_key, self_signed_cert, signing_jwk

HERE = Path(__file__).parent


def env(name: str, default: str = "") -> str:
    """Empty values count as unset."""
    return os.environ.get(name) or default


PUBLIC_URL = env("PUBLIC_URL", "http://localhost:8077").rstrip("/")
HOST = urlsplit(PUBLIC_URL).hostname
SECURE = PUBLIC_URL.startswith("https")
KEY_DIR = Path(env("KEY_DIR", str(HERE / ".keys")))

SIGNING_KEY = load_or_create_key(KEY_DIR / "signing.pem")
SIGNING_JWK = signing_jwk(SIGNING_KEY)
KID = SIGNING_JWK["kid"]

_subject_key = KEY_DIR / "subject.key"
if not _subject_key.exists():
    _subject_key.write_bytes(secrets.token_bytes(32))
SUBJECT_KEY = _subject_key.read_bytes()

if env("REQUEST_CERT_FILE"):
    _chain = x509.load_pem_x509_certificates(Path(env("REQUEST_CERT_FILE")).read_bytes())
else:
    _chain = [self_signed_cert(SIGNING_KEY, HOST, "EBW-Connector (test certificate)")]
REQUEST_X5C = [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode() for cert in _chain]
WALLET_CLIENT_ID = f"x509_san_dns:{HOST}"

CLIENTS_FILE = Path(env("CLIENTS_FILE", str(HERE / "clients.json")))
# Without CLIENTS_FILE, the demo OSP and the Business Wallet of this folder are registered.
TEST_TOOLS_URL = env("TEST_TOOLS_URL", "http://localhost:8079").rstrip("/")
BUSINESS_WALLET_URL = env("BUSINESS_WALLET_URL", "http://localhost:8078").rstrip("/")

TRUST_LIST_URL = env("TRUST_LIST_URL", "http://localhost:8079/trust-list")
TRUST_LIST_SIGNER_FILE = Path(env("TRUST_LIST_SIGNER_FILE", str(HERE.parent / "test_tools" / ".keys" / "trust-list-signer.json")))
TRUST_LIST_FILE = env("TRUST_LIST_FILE")
TRUST_LIST_CACHE_SECONDS = int(env("TRUST_LIST_CACHE_SECONDS", "300"))

VCT = {
    "PID": env("PID_VCT", "urn:eudi:pid:1"),
    "LPID": env("LPID_VCT", "urn:tx:test:lpid:1"),
    "MANDATE": env("MANDATE_VCT", "urn:tx:test:mandate:1"),
}
ACCEPTED_REPRESENTATION_TYPES = [
    t.strip() for t in env("ACCEPTED_REPRESENTATION_TYPES", "legal_representative,power_of_attorney").split(",") if t.strip()
]
RESPONSE_MODE = env("RESPONSE_MODE", "direct_post.jwt")
if RESPONSE_MODE not in ("direct_post.jwt", "direct_post"):
    raise ValueError("RESPONSE_MODE must be direct_post.jwt or direct_post")
WALLET_URL_SCHEME = env("WALLET_URL_SCHEME", "openid4vp://")

TRANSACTION_TTL_SECONDS = int(env("TRANSACTION_TTL_SECONDS", "600"))
AUTH_CODE_TTL_SECONDS = int(env("AUTH_CODE_TTL_SECONDS", "60"))
ACCESS_TOKEN_TTL_SECONDS = int(env("ACCESS_TOKEN_TTL_SECONDS", "300"))
ATTESTATION_AUDIENCE = env("ATTESTATION_AUDIENCE", "portal-registration")
ATTESTATION_TTL_HOURS = int(env("ATTESTATION_TTL_HOURS", "720"))
STATUS_LIST_CACHE_SECONDS = int(env("STATUS_LIST_CACHE_SECONDS", "300"))
AUDIT_LOG_FILE = Path(env("AUDIT_LOG_FILE", str(HERE / "audit.log")))
