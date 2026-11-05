# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Keys, self-signed certificates and compact JWS with ES256, without a JOSE library."""

import base64
import datetime
import hashlib
import json
import secrets
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.x509.oid import NameOID


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sha256_b64url(text: str) -> str:
    return b64url(hashlib.sha256(text.encode("ascii")).digest())


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def random_token(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def load_or_create_key(path: Path) -> ec.EllipticCurvePrivateKey:
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return key


def public_jwk(key) -> dict:
    public_key = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }


def key_from_jwk(jwk: dict) -> ec.EllipticCurvePublicKey:
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("only EC keys on P-256 are supported")
    x = int.from_bytes(b64url_decode(jwk["x"]), "big")
    y = int.from_bytes(b64url_decode(jwk["y"]), "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def jwk_thumbprint(jwk: dict) -> str:
    """RFC 7638 thumbprint, used as kid."""
    canonical = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(canonical.encode()).digest())


def same_key(a, b) -> bool:
    return public_jwk(a) == public_jwk(b)


def signing_jwk(key) -> dict:
    """Public JWK with kid (thumbprint), use and alg, as published in a JWKS."""
    jwk = public_jwk(key)
    return {**jwk, "kid": jwk_thumbprint(jwk), "use": "sig", "alg": "ES256"}


def keys_from_jwks(jwks: dict) -> list[tuple[str | None, ec.EllipticCurvePublicKey]]:
    """(kid, key) for every EC P-256 key of a JWKS; other keys are skipped."""
    keys = []
    for jwk in jwks.get("keys", []):
        try:
            keys.append((jwk.get("kid"), key_from_jwk(jwk)))
        except (ValueError, KeyError):
            continue
    return keys


def self_signed_cert(key: ec.EllipticCurvePrivateKey, host: str, common_name: str) -> x509.Certificate:
    """Leaf certificate with the host as DNS name in the SAN (x509_san_dns, iss of the SD-JWT VC)."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )


def x5c(cert: x509.Certificate) -> list[str]:
    return [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()]


def cert_from_x5c(entry: str) -> x509.Certificate:
    return x509.load_der_x509_certificate(base64.b64decode(entry))


def san_dns_names(cert: x509.Certificate) -> list[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return san.get_values_for_type(x509.DNSName)


def _json_b64(value: dict) -> str:
    return b64url(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def sign_jws(header: dict, payload: dict, key: ec.EllipticCurvePrivateKey) -> str:
    signing_input = f"{_json_b64({'alg': 'ES256', **header})}.{_json_b64(payload)}"
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def unsigned_jws(header: dict, payload: dict) -> str:
    """alg none, only for the redirect_uri client identifier prefix of OpenID4VP."""
    return f"{_json_b64({'alg': 'none', **header})}.{_json_b64(payload)}."


def read_jws(token: str) -> tuple[dict, dict]:
    """Header and payload, without checking the signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a compact JWS")
    return json.loads(b64url_decode(parts[0])), json.loads(b64url_decode(parts[1]))


def verify_jws(token: str, public_key: ec.EllipticCurvePublicKey) -> tuple[dict, dict]:
    header, payload = read_jws(token)
    if header.get("alg") != "ES256":
        raise ValueError(f"unsupported alg {header.get('alg')!r}")
    signing_input, _, signature = token.rpartition(".")
    raw = b64url_decode(signature)
    if len(raw) != 64:
        raise ValueError("invalid signature")
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        public_key.verify(der, signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise ValueError("invalid signature") from None
    return header, payload
