# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""OpenID Connect client with PKCE and private_key_jwt, for the Business Wallet and the demo OSP."""

import base64
import hashlib
import time
from urllib.parse import urlencode

import httpx

from common.jose import keys_from_jwks, random_token, read_jws, sign_jws, signing_jwk, verify_jws


class OidcError(Exception):
    pass


class OidcClient:
    def __init__(self, issuer: str, client_id: str, redirect_uri: str, key):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.key = key
        self.kid = signing_jwk(key)["kid"]
        self._metadata: dict | None = None

    def metadata(self) -> dict:
        if self._metadata is None:
            response = httpx.get(f"{self.issuer}/.well-known/openid-configuration", timeout=10)
            response.raise_for_status()
            self._metadata = response.json()
        return self._metadata

    def start(self, scope: str) -> tuple[str, dict]:
        """Authorization URL and the values to keep until the callback."""
        flow = {"state": random_token(), "nonce": random_token(), "verifier": random_token(32)}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).decode().rstrip("=")
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": scope,
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.metadata()['authorization_endpoint']}?{urlencode(params)}", flow

    def assertion(self) -> str:
        now = int(time.time())
        return sign_jws(
            {"typ": "JWT", "kid": self.kid},
            {
                "iss": self.client_id,
                "sub": self.client_id,
                "aud": self.metadata()["token_endpoint"],
                "iat": now,
                "exp": now + 120,
                "jti": random_token(),
            },
            self.key,
        )

    def finish(self, params: dict, flow: dict) -> tuple[dict, dict]:
        """Checks the callback, redeems the code; returns (ID token claims, token response)."""
        if params.get("state") != flow.get("state"):
            raise OidcError("state does not match")
        if "iss" in params and params["iss"].rstrip("/") != self.issuer:
            raise OidcError("iss does not match")
        if "error" in params:
            raise OidcError(f"{params['error']}: {params.get('error_description', '')}")
        response = httpx.post(
            self.metadata()["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": params.get("code", ""),
                "redirect_uri": self.redirect_uri,
                "code_verifier": flow["verifier"],
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": self.assertion(),
            },
            timeout=10,
        )
        if response.is_error:
            raise OidcError(f"token endpoint: {response.status_code} {response.text[:300]}")
        tokens = response.json()
        return self.verify_id_token(tokens["id_token"], flow["nonce"]), tokens

    def provider_keys(self) -> list:
        response = httpx.get(self.metadata()["jwks_uri"], timeout=10)
        response.raise_for_status()
        return keys_from_jwks(response.json())

    def verify_signed(self, token: str) -> tuple[dict, dict]:
        """Header and payload of a JWT signed by the provider (ID token, attestation)."""
        kid = read_jws(token)[0].get("kid")
        for key_id, key in self.provider_keys():
            if kid in (None, key_id):
                try:
                    return verify_jws(token, key)
                except ValueError:
                    continue
        raise OidcError("signature of the provider does not verify")

    def verify_id_token(self, id_token: str, nonce: str) -> dict:
        _, claims = self.verify_signed(id_token)
        audience = claims.get("aud")
        if claims.get("iss", "").rstrip("/") != self.issuer:
            raise OidcError("iss of the ID token does not match")
        if self.client_id not in (audience if isinstance(audience, list) else [audience]):
            raise OidcError("aud of the ID token does not match")
        if claims.get("nonce") != nonce:
            raise OidcError("nonce of the ID token does not match")
        if claims.get("exp", 0) < time.time() - 60:
            raise OidcError("ID token expired")
        return claims
