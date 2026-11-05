# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""OpenID4VCI 1.0 issuer: pre-authorized code flow without tx_code, SD-JWT VC (dc+sd-jwt).
Used by the test tools (PID, LPID, legal representation) and the Business Wallet (powers of attorney)."""

import time
from collections.abc import Callable
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from common import sdjwt
from common.jose import key_from_jwk, public_jwk, random_token, read_jws, signing_jwk, verify_jws
from common.statuslist import StatusList
from common.web import read_form

PRE_AUTH_GRANT = "urn:ietf:params:oauth:grant-type:pre-authorized_code"
OFFER_SCHEME = "openid-credential-offer://"
LIFETIME = 600
NONCE_LIFETIME = 300
NO_STORE = {"Cache-Control": "no-store"}


class InvalidNonce(ValueError):
    pass


def error(status: int, code: str, description: str) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=status, headers=NO_STORE)


class Issuer:
    """Credential issuer at the root of its host. `definitions`: configuration ID -> vct, name, labels."""

    def __init__(
        self,
        base_url: str,
        key,
        header: dict,
        definitions: dict[str, dict],
        display_name: str,
        status_list: StatusList | None = None,
        on_issued: Callable[[str, dict, dict | None, str], None] | None = None,
        validity: int = 365 * 24 * 3600,
    ):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.header = header
        self.definitions = definitions
        self.display_name = display_name
        self.status_list = status_list
        self.on_issued = on_issued
        self.validity = validity
        self.offers: dict[str, dict] = {}
        self.codes: dict[str, tuple[str, float]] = {}
        self.tokens: dict[str, tuple[str, float]] = {}
        self.nonces: dict[str, float] = {}
        self.router = APIRouter()
        add = self.router.add_api_route
        add("/.well-known/openid-credential-issuer", self.issuer_metadata, methods=["GET"])
        add("/.well-known/oauth-authorization-server", self.authorization_server_metadata, methods=["GET"])
        add("/.well-known/jwt-vc-issuer", self.jwt_vc_issuer_metadata, methods=["GET"])
        add("/oid4vci/offers/{offer_id}", self.get_offer, methods=["GET"])
        add("/oid4vci/offers/{offer_id}/status", self.offer_status, methods=["GET"])
        add("/oid4vci/token", self.token, methods=["POST"])
        add("/oid4vci/nonce", self.nonce, methods=["POST"])
        add("/oid4vci/credential", self.credential, methods=["POST"])
        if status_list:
            add("/status-lists/1", self.status_list_token, methods=["GET"])

    # Offers

    def create_offer(self, claims_by_config: dict[str, dict], label: str = "") -> tuple[str, str]:
        """Returns (offer ID, link for the wallet). Every configuration may be fetched with the code."""
        code = random_token(24)
        offer_id = random_token(12)
        self.codes[code] = (offer_id, time.time() + LIFETIME)
        self.offers[offer_id] = {
            "offer": {
                "credential_issuer": self.base_url,
                "credential_configuration_ids": list(claims_by_config),
                "grants": {PRE_AUTH_GRANT: {"pre-authorized_code": code}},
            },
            "claims": claims_by_config,
            "label": label,
            "expires": time.time() + LIFETIME,
            "redeemed": False,
            "issued": [],
        }
        offer_uri = f"{self.base_url}/oid4vci/offers/{offer_id}"
        return offer_id, f"{OFFER_SCHEME}?credential_offer_uri={quote(offer_uri, safe='')}"

    def get_offer(self, offer_id: str):
        entry = self.offers.get(offer_id)
        if not entry or entry["expires"] < time.time():
            return JSONResponse({"error": "unknown or expired offer"}, status_code=404)
        return JSONResponse(entry["offer"], headers=NO_STORE)

    def offer_status(self, offer_id: str) -> dict:
        """State of an offer for its page. An unknown offer counts as expired: offers do not survive a restart."""
        entry = self.offers.get(offer_id)
        if not entry:
            return {"status": "EXPIRED", "expires_in": 0, "offered": [], "issued": []}
        expires_in = max(int(entry["expires"] - time.time()), 0)
        status = "PICKED_UP" if entry["redeemed"] else "OPEN" if expires_in else "EXPIRED"
        names = lambda ids: [self.definitions[cid]["name"] for cid in ids]  # noqa: E731
        return {"status": status, "expires_in": expires_in, "offered": names(entry["claims"]), "issued": names(entry["issued"])}

    # Metadata

    def credential_configuration(self, definition: dict) -> dict:
        display = [{"name": definition["name"], "locale": "en"}]
        claims = [
            {"path": [name], "display": [{"name": label, "locale": "en"}]} for name, label in definition["labels"].items()
        ]
        return {
            "format": "dc+sd-jwt",
            "vct": definition["vct"],
            "cryptographic_binding_methods_supported": ["jwk"],
            "credential_signing_alg_values_supported": ["ES256"],
            "proof_types_supported": {"jwt": {"proof_signing_alg_values_supported": ["ES256"]}},
            "credential_metadata": {"display": display, "claims": claims},
            # Wallets on draft 15 read display and claims at this level.
            "display": display,
            "claims": claims,
        }

    def issuer_metadata(self):
        return {
            "credential_issuer": self.base_url,
            "credential_endpoint": f"{self.base_url}/oid4vci/credential",
            "nonce_endpoint": f"{self.base_url}/oid4vci/nonce",
            "display": [{"name": self.display_name, "locale": "en"}],
            "credential_configurations_supported": {
                cid: self.credential_configuration(d) for cid, d in self.definitions.items()
            },
        }

    def authorization_server_metadata(self):
        return {
            "issuer": self.base_url,
            "token_endpoint": f"{self.base_url}/oid4vci/token",
            "response_types_supported": ["code"],
            "grant_types_supported": [PRE_AUTH_GRANT],
            "pre-authorized_grant_anonymous_access_supported": True,
            "token_endpoint_auth_methods_supported": ["none"],
        }

    def jwt_vc_issuer_metadata(self):
        return {"issuer": self.base_url, "jwks": {"keys": [signing_jwk(self.key)]}}

    def status_list_token(self):
        # same header as the credentials: wallets such as Paradym (Credo) require the status list to be signed
        # with the x5c chain of the credential issuer
        token = self.status_list.token(self.key, self.header)
        return Response(token, media_type="application/statuslist+jwt", headers={"Cache-Control": "max-age=30"})

    # Flow

    async def token(self, request: Request):
        form = await read_form(request)
        if form.get("grant_type") != PRE_AUTH_GRANT:
            return error(400, "unsupported_grant_type", "only the pre-authorized code grant is supported")
        offer_id, expiry = self.codes.pop(form.get("pre-authorized_code", ""), (None, 0))
        if expiry < time.time():
            return error(400, "invalid_grant", "unknown, used or expired pre-authorized_code")
        self.offers[offer_id]["redeemed"] = True
        access_token = random_token(32)
        self.tokens[access_token] = (offer_id, time.time() + LIFETIME)
        return JSONResponse(
            {"access_token": access_token, "token_type": "Bearer", "expires_in": LIFETIME}, headers=NO_STORE
        )

    def nonce(self):
        value = random_token()
        self.nonces[value] = time.time() + NONCE_LIFETIME
        return JSONResponse({"c_nonce": value}, headers=NO_STORE)

    def check_proof(self, proof: str) -> dict:
        """Checks a proof of type jwt and returns the holder key for cnf.jwk."""
        header, _ = read_jws(proof)
        if header.get("typ") != "openid4vci-proof+jwt":
            raise ValueError("typ must be openid4vci-proof+jwt")
        if "jwk" not in header:
            raise ValueError("only proofs with jwk in the header are supported")
        holder_jwk = public_jwk(key_from_jwk(header["jwk"]))
        _, payload = verify_jws(proof, key_from_jwk(holder_jwk))
        audience = payload.get("aud")
        if self.base_url not in [str(a).rstrip("/") for a in (audience if isinstance(audience, list) else [audience])]:
            raise ValueError(f"aud must be {self.base_url}")
        if self.nonces.get(payload.get("nonce"), 0) < time.time():
            raise InvalidNonce("unknown or expired c_nonce")
        return holder_jwk

    async def credential(self, request: Request):
        scheme, _, access_token = request.headers.get("authorization", "").partition(" ")
        offer_id, expiry = self.tokens.get(access_token, (None, 0))
        if scheme.lower() not in ("bearer", "dpop") or expiry < time.time():
            return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        try:
            body = await request.json()
        except ValueError:
            return error(400, "invalid_credential_request", "body must be JSON")
        entry = self.offers.get(offer_id)
        cid = body.get("credential_configuration_id")
        if not entry or cid not in entry["claims"]:
            return error(400, "unknown_credential_configuration", f"{cid!r} is not part of the offer")
        proofs = (body.get("proofs") or {}).get("jwt") or []
        if not proofs and isinstance(body.get("proof"), dict) and body["proof"].get("proof_type") == "jwt":
            proofs = [body["proof"]["jwt"]]
        if not proofs:
            return error(400, "invalid_proof", "proofs.jwt missing")

        definition, claims = self.definitions[cid], entry["claims"][cid]
        issued = []
        for proof in proofs:
            try:
                holder_jwk = self.check_proof(proof)
            except InvalidNonce as exc:
                return error(400, "invalid_nonce", str(exc))
            except (ValueError, KeyError) as exc:
                return error(400, "invalid_proof", str(exc))
            status = self.status_list.allocate() if self.status_list else None
            credential = sdjwt.issue(
                claims, definition["vct"], holder_jwk, self.key, self.header, self.base_url, self.validity, status
            )
            if self.on_issued:
                self.on_issued(cid, claims, status, entry["label"])
            issued.append({"credential": credential})
            if cid not in entry["issued"]:
                entry["issued"].append(cid)
        return JSONResponse({"credentials": issued}, headers=NO_STORE)
