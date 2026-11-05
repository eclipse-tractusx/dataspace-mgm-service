# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Compact JWE with ECDH-ES (direct key agreement) and AES-GCM, for direct_post.jwt of OpenID4VP."""

import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common.jose import b64url, b64url_decode, key_from_jwk, public_jwk

KEY_BITS = {"A128GCM": 128, "A256GCM": 256}


def _length_prefixed(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _concat_kdf(shared_secret: bytes, enc: str, apu: bytes, apv: bytes) -> bytes:
    """RFC 7518 4.6.2; one SHA-256 round is enough for keys up to 256 bits."""
    bits = KEY_BITS[enc]
    other_info = (
        _length_prefixed(enc.encode())
        + _length_prefixed(apu)
        + _length_prefixed(apv)
        + struct.pack(">I", bits)
    )
    return hashlib.sha256(struct.pack(">I", 1) + shared_secret + other_info).digest()[: bits // 8]


def encrypt(plaintext: bytes, recipient_jwk: dict, enc: str = "A128GCM", apu: bytes = b"", apv: bytes = b"") -> str:
    if enc not in KEY_BITS:
        raise ValueError(f"unsupported enc {enc!r}")
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    shared = ephemeral.exchange(ec.ECDH(), key_from_jwk(recipient_jwk))
    header = {"alg": "ECDH-ES", "enc": enc, "epk": public_jwk(ephemeral)}
    if "kid" in recipient_jwk:
        header["kid"] = recipient_jwk["kid"]
    if apu:
        header["apu"] = b64url(apu)
    if apv:
        header["apv"] = b64url(apv)
    protected = b64url(json.dumps(header, separators=(",", ":")).encode())
    iv = os.urandom(12)
    sealed = AESGCM(_concat_kdf(shared, enc, apu, apv)).encrypt(iv, plaintext, protected.encode("ascii"))
    return f"{protected}..{b64url(iv)}.{b64url(sealed[:-16])}.{b64url(sealed[-16:])}"


def decrypt(token: str, private_key: ec.EllipticCurvePrivateKey) -> tuple[dict, bytes]:
    parts = token.split(".")
    if len(parts) != 5:
        raise ValueError("not a compact JWE")
    protected, encrypted_key, iv, ciphertext, tag = parts
    header = json.loads(b64url_decode(protected))
    if header.get("alg") != "ECDH-ES" or encrypted_key:
        raise ValueError("only ECDH-ES direct key agreement is supported")
    enc = header.get("enc")
    if enc not in KEY_BITS:
        raise ValueError(f"unsupported enc {enc!r}")
    shared = private_key.exchange(ec.ECDH(), key_from_jwk(header["epk"]))
    # Some wallets send "apu": null; treat it like a missing value.
    key = _concat_kdf(shared, enc, b64url_decode(header.get("apu") or ""), b64url_decode(header.get("apv") or ""))
    plaintext = AESGCM(key).decrypt(
        b64url_decode(iv), b64url_decode(ciphertext) + b64url_decode(tag), protected.encode("ascii")
    )
    return header, plaintext
