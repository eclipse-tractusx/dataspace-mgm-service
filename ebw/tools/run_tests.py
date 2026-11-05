# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Acceptance tests (C5-M1 README section 13) against freshly started services on test ports.

    .venv/bin/python -m tools.run_tests

A script plays the browser and the EUDI Wallet; the Business Wallet is the real one.
"""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from common import holder, sdjwt
from common.issuer import Issuer
from common.jose import load_or_create_key, public_jwk
from common.oidc_client import OidcClient, OidcError

ROOT = Path(__file__).resolve().parent.parent
PORTS = {"connector": 18077, "business_wallet": 18078, "test_tools": 18079}
URL = {name: f"http://localhost:{port}" for name, port in PORTS.items()}
TMP = Path(tempfile.mkdtemp(prefix="ebw-test-"))

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, bool(condition), detail))
    print(f"{'OK  ' if condition else 'FAIL'} {name}{'' if condition else ' – ' + detail}", flush=True)


# Services


def start_services() -> list[subprocess.Popen]:
    tools_keys = TMP / "test_tools" / "keys"
    common_env = {
        **os.environ,
        "CONNECTOR_URL": URL["connector"],
        "TEST_TOOLS_URL": URL["test_tools"],
        "BUSINESS_WALLET_URL": URL["business_wallet"],
        "TRUST_LIST_URL": f"{URL['test_tools']}/trust-list",
        "TRUST_LIST_SIGNER_FILE": str(tools_keys / "trust-list-signer.json"),
        "TRUST_LIST_CACHE_SECONDS": "1",
        "STATUS_LIST_CACHE_SECONDS": "0",
        "AUDIT_LOG_FILE": str(TMP / "audit.log"),
        "CLIENTS_FILE": str(TMP / "no-clients.json"),
        "PYTHONUTF8": "1",  # as in tools.start
    }
    processes = []
    for name in ("test_tools", "connector", "business_wallet"):
        env = {
            **common_env,
            "PUBLIC_URL": URL[name],
            "KEY_DIR": str(TMP / name / "keys"),
            "DATA_DIR": str(TMP / name / "data"),
        }
        (TMP / name / "keys").mkdir(parents=True, exist_ok=True)
        log = open(TMP / f"{name}.log", "w")
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", f"{name}.app:app", "--port", str(PORTS[name])],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
        )  # fmt: skip
        for _ in range(60):
            try:
                httpx.get(URL[name] + "/", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.25)
    return processes


# Browser and EUDI Wallet


class Browser:
    """Follows redirects like a browser; stops at a given address (the client's callback)."""

    def __init__(self):
        self.http = httpx.Client(timeout=15)

    def go(self, url: str, stop_at: str | None = None, method: str = "GET", data: dict | None = None) -> httpx.Response:
        response = self.http.request(method, url, data=data)
        for _ in range(15):
            if response.status_code not in (301, 302, 303, 307):
                return response
            location = response.headers["location"]
            if location.startswith("/"):
                parts = urlsplit(str(response.request.url))
                location = f"{parts.scheme}://{parts.netloc}{location}"
            if stop_at and location.startswith(stop_at):
                return response
            response = self.http.get(location)
        raise RuntimeError("too many redirects")


class Wallet:
    """EUDI Wallet of a person: holds credentials, answers the person step."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credentials: list[str] = []
        self.http = httpx.Client(timeout=15)

    def receive(self, link: str) -> None:
        offer = holder.resolve_offer(link, self.http)
        self.credentials += holder.obtain_credentials(offer, self.key, self.http).values()

    def answer(self, page: str, nonce: str | None = None, decline: bool = False) -> httpx.Response:
        match = re.search(r'id="wallet-link" href="([^"]+)"', page)
        assert match, "no wallet link on the page"
        request = holder.read_request(holder.query_params(html.unescape(match.group(1))), self.http)
        if decline:
            holder.decline(request, self.http)
            return request
        holder.answer(request, self.credentials, self.key, self.http, nonce=nonce)
        return request


def tools_offer(credentials: dict, label: str = "Test") -> str:
    response = httpx.post(f"{URL['test_tools']}/api/offers", json={"credentials": credentials, "label": label})
    return response.json()["link"]


def present_in_business_wallet(browser: Browser, page: str, stop_at: str, address: str = "/present") -> httpx.Response:
    """Company step: open the Business Wallet with the request and approve."""
    match = re.search(r'id="request-link">([^<]+)<', page)
    assert match, "no request link on the page"
    params = holder.query_params(html.unescape(match.group(1)))
    response = browser.go(f"{URL['business_wallet']}{address}?{urlencode(params)}")
    action = re.search(r'action="(/present/[^/]+/approve)"', response.text)
    assert action, f"no approve form: {response.text[:300]}"
    return browser.go(URL["business_wallet"] + action.group(1), stop_at=stop_at, method="POST")


def oidc_flow(client: OidcClient, browser: Browser, scope: str, wallet: Wallet, company: bool = False, nonce=None, decline=False, address="/present"):
    """Runs a transaction; returns (claims, tokens) or raises OidcError."""
    url, flow = client.start(scope)
    response = browser.go(url, stop_at=client.redirect_uri)
    if response.status_code == 200:
        page_url = str(response.request.url)
        wallet.answer(response.text, nonce=nonce, decline=decline)
        response = browser.go(page_url, stop_at=client.redirect_uri)
        if response.status_code == 200 and company:
            response = present_in_business_wallet(browser, response.text, client.redirect_uri, address)
    return client.finish(holder.query_params(response.headers.get("location", "")), flow)


def bw_login(browser: Browser, wallet: Wallet) -> httpx.Response:
    response = browser.go(f"{URL['business_wallet']}/login")
    wallet.answer(response.text)
    return browser.go(str(response.request.url))


# Scenarios


def main() -> None:
    processes = start_services()
    try:
        run()
    finally:
        for process in processes:
            process.terminate()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed. Logs: {TMP}")
    sys.exit(1 if failed else 0)


def run() -> None:
    osp_key = load_or_create_key(TMP / "test_tools" / "keys" / "osp-client.pem")
    bw_key = load_or_create_key(TMP / "business_wallet" / "keys" / "wallet.pem")
    osp = OidcClient(URL["connector"], "demo-osp", f"{URL['test_tools']}/osp/callback", osp_key)
    bw_client = OidcClient(URL["connector"], "business-wallet", f"{URL['business_wallet']}/login/callback", bw_key)
    signin, onboarding = "openid profile representation", "openid profile representation company attestation"

    # 1 Discovery, JWKS, errors at authorize
    metadata = httpx.get(f"{URL['connector']}/.well-known/openid-configuration").json()
    check("1 Discovery", metadata["issuer"] == URL["connector"] and "S256" in metadata["code_challenge_methods_supported"])
    check("1 JWKS", len(httpx.get(f"{URL['connector']}/jwks").json()["keys"]) == 1)
    url, _ = osp.start(signin)
    no_pkce = re.sub(r"&code_challenge=[^&]+", "", url)
    response = httpx.get(no_pkce)
    check("1 authorize without PKCE -> invalid_request", "error=invalid_request" in response.headers.get("location", ""))
    encoded = urlencode({"redirect_uri": osp.redirect_uri}).split("=", 1)[1]
    response = httpx.get(url.replace(encoded, "https%3A%2F%2Fevil.example%2Fcb"))
    check("1 unknown redirect_uri -> error page", response.status_code == 400 and "location" not in response.headers)

    # Erika: PID and legal representation in her EUDI Wallet; LPID in the Business Wallet
    erika = Wallet()
    erika.receive(tools_offer({"pid": {}, "mandate": {}}, "Erika"))
    admin = Browser()
    response = admin.go(f"{URL['business_wallet']}/receive", method="POST", data={"offer": tools_offer({"lpid": {}}, "LPID")})
    check("Business Wallet holds the LPID", httpx.get(f"{URL['business_wallet']}/api/state").json()["lpid"] is not None)

    # 2, 3 Sign-in with the register mandate
    browser = Browser()
    url, flow = osp.start(signin)
    page = browser.go(url).text
    request = erika.answer(page)
    check("3 Request Object: client_id x509_san_dns", request["client_id"] == "x509_san_dns:localhost")
    check("3 Request Object: direct_post.jwt, without credential_sets",
          request["response_mode"] == "direct_post.jwt" and "credential_sets" not in request["dcql_query"])  # fmt: skip
    tx_url = f"{URL['connector']}/transactions/{re.search(r'/transactions/([^/]+)/status', page).group(1)}"
    response = browser.go(tx_url, stop_at=osp.redirect_uri)
    claims, tokens = osp.finish(holder.query_params(response.headers["location"]), flow)
    check("2 Sign-in: CONFIRMED through trust_list",
          claims.get("representation_result") == "CONFIRMED" and claims.get("representation_trust") == "trust_list",
          json.dumps(claims))  # fmt: skip
    info = httpx.get(f"{URL['connector']}/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    check("2 userinfo as ID token", info.get("representation_result") == "CONFIRMED" and info.get("sub") == claims["sub"])

    # 4 Admin login at the Business Wallet
    response = bw_login(admin, erika)
    check("Business Wallet: Erika signed in as administrator", "Administrator" in response.text, response.text[:300])

    # 5 Onboarding with Erika
    claims, tokens = oidc_flow(osp, admin, onboarding, erika, company=True)
    attestation_ok = False
    if "ebw_attestation" in tokens:
        header, payload = osp.verify_signed(tokens["ebw_attestation"])
        attestation_ok = (
            header.get("typ") == "ebw-attestation+jwt"
            and payload["representation"]["confirmed"] is True
            and payload["company"]["ebwoid"] == "EBWOID-DE-0000000001"
            and [e["wallet"] for e in payload["evidence"]] == ["EUDI_WALLET", "EUDI_WALLET", "BUSINESS_WALLET"]
        )
    check("5 Onboarding: verification attestation valid and confirmed", attestation_ok, json.dumps(tokens)[:300])
    claims, tokens = oidc_flow(osp, admin, onboarding, erika, company=True, address="/")
    check("5 Onboarding: wallet address without /present", "ebw_attestation" in tokens, json.dumps(claims)[:300])

    # 6 Employee with a power of attorney from the Business Wallet
    response = admin.go(
        f"{URL['business_wallet']}/mandates",
        method="POST",
        data={"given_name": "Max", "family_name": "Beispiel", "birthdate": "1990-05-05", "role": "Purchasing", "valid_until": "2027-06-30"},
    )
    link = html.unescape(re.search(r'href="(openid-credential-offer://[^"]+)"', response.text).group(1))
    max_wallet = Wallet()
    max_wallet.receive(tools_offer({"pid": {"given_name": "Max", "family_name": "Beispiel", "birthdate": "1990-05-05"}}, "Max"))
    max_wallet.receive(link)
    employee = Browser()
    response = bw_login(employee, max_wallet)
    check("6 Employee sign-in at the Business Wallet (client_key)", "Employee" in response.text, response.text[:300])
    claims, tokens = oidc_flow(osp, employee, onboarding, max_wallet, company=True)
    check("6 Onboarding by an employee: CONFIRMED through company_key",
          claims.get("representation_result") == "CONFIRMED" and claims.get("representation_trust") == "company_key",
          json.dumps(claims))  # fmt: skip
    claims, _ = oidc_flow(osp, Browser(), signin, max_wallet)
    check("6 Sign-in at the OSP: NOT_CONFIRMED, ISSUER_NOT_TRUSTED, no data of the power of attorney",
          claims.get("representation_reasons") == ["ISSUER_NOT_TRUSTED"] and "representation_type" not in claims,
          json.dumps(claims))  # fmt: skip

    # 7 Mismatches
    other = Wallet()
    other.receive(tools_offer({"pid": {}, "mandate": {"represented": {"identifier": "EBWOID-DE-0000000002", "legal_name": "Other GmbH"}}}))
    claims, _ = oidc_flow(osp, admin, onboarding, other, company=True)
    check("7 Mandate for another company: COMPANY_MISMATCH", "COMPANY_MISMATCH" in claims.get("representation_reasons", []), json.dumps(claims))
    stranger = Wallet()
    stranger.receive(tools_offer({"pid": {}, "mandate": {"representative": {"given_name": "Max", "family_name": "Mustermann", "birthdate": "1980-01-01"}}}))
    claims, _ = oidc_flow(osp, Browser(), signin, stranger)
    check("7 Mandate for another person: PERSON_MISMATCH", "PERSON_MISMATCH" in claims.get("representation_reasons", []), json.dumps(claims))

    # 8 PID of an untrusted issuer
    fake = Wallet()
    fake.receive(tools_offer({"mandate": {}}))
    rogue = ec.generate_private_key(ec.SECP256R1())
    fake.credentials.append(
        sdjwt.issue(
            {"given_name": "Erika", "family_name": "Mustermann", "birthdate": "1984-01-26", "issuing_country": "DE"},
            "urn:eudi:pid:1", public_jwk(fake.key), rogue, {}, "https://rogue.example", 3600,
        )
    )  # fmt: skip
    try:
        oidc_flow(osp, Browser(), signin, fake)
        check("8 PID not trusted: UNTRUSTED_ISSUER", False, "no error")
    except OidcError as exc:
        check("8 PID not trusted: UNTRUSTED_ISSUER", "UNTRUSTED_ISSUER" in str(exc), str(exc))

    # 9 Revoked power of attorney
    mandate_id = next(m["id"] for m in httpx.get(f"{URL['business_wallet']}/api/state").json()["mandates"])
    admin.go(f"{URL['business_wallet']}/mandates/{mandate_id}/revoke", method="POST")
    try:
        oidc_flow(bw_client, Browser(), signin, max_wallet)
        check("9 Revoked power of attorney: CREDENTIAL_REVOKED", False, "no error")
    except OidcError as exc:
        check("9 Revoked power of attorney: CREDENTIAL_REVOKED", "CREDENTIAL_REVOKED" in str(exc), str(exc))

    # 10 Wrong nonce, second response
    try:
        oidc_flow(osp, Browser(), signin, erika, nonce="wrong")
        check("10 Wrong nonce: HOLDER_BINDING_FAILED", False, "no error")
    except OidcError as exc:
        check("10 Wrong nonce: HOLDER_BINDING_FAILED", "HOLDER_BINDING_FAILED" in str(exc), str(exc))
    browser = Browser()
    url, flow = osp.start(signin)
    page = browser.go(url).text
    request = erika.answer(page)
    second = httpx.post(request["response_uri"], data={"response": "x"})
    check("10 Second answer to the same response_uri: 400", second.status_code == 400, str(second.status_code))

    # 11 Wallet declines
    try:
        oidc_flow(osp, Browser(), signin, erika, decline=True)
        check("11 Wallet declines: WALLET_ERROR", False, "no error")
    except OidcError as exc:
        check("11 Wallet declines: WALLET_ERROR", "WALLET_ERROR" in str(exc), str(exc))

    # 12 Pairwise sub
    first, _ = oidc_flow(osp, Browser(), signin, erika)
    second_claims, _ = oidc_flow(osp, Browser(), signin, erika)
    other_client, _ = oidc_flow(bw_client, Browser(), signin, erika)
    check("12 sub equal at the same client, different at another",
          first["sub"] == second_claims["sub"] and first["sub"] != other_client["sub"])  # fmt: skip

    # 13 Code twice, client assertion twice
    browser = Browser()
    url, flow = osp.start(signin)
    page = browser.go(url).text
    erika.answer(page)
    tx_url = f"{URL['connector']}/transactions/{re.search(r'/transactions/([^/]+)/status', page).group(1)}"
    params = holder.query_params(browser.go(tx_url, stop_at=osp.redirect_uri).headers["location"])
    _, tokens = osp.finish(params, flow)
    assertion = osp.assertion()
    token_form = {
        "grant_type": "authorization_code", "code": params["code"], "redirect_uri": osp.redirect_uri,
        "code_verifier": flow["verifier"],
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": assertion,
    }  # fmt: skip
    again = httpx.post(f"{URL['connector']}/token", data=token_form)
    userinfo = httpx.get(f"{URL['connector']}/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    check("13 Code twice: invalid_grant, access token invalid",
          again.json().get("error") == "invalid_grant" and userinfo.status_code == 401)  # fmt: skip
    reused = httpx.post(f"{URL['connector']}/token", data=token_form)
    check("13 Client assertion twice: invalid_client", reused.json().get("error") == "invalid_client", reused.text)

    # 14 Without the cookie
    browser = Browser()
    url, _ = osp.start(signin)
    page = browser.go(url).text
    tx_id = re.search(r"/transactions/([^/]+)/status", page).group(1)
    stranger_browser = httpx.Client()
    check("14 complete without cookie: 404", stranger_browser.get(f"{URL['connector']}/transactions/{tx_id}/complete").status_code == 404)
    neutral = stranger_browser.get(f"{URL['connector']}/transactions/{tx_id}").text
    check("14 Page without cookie shows no data", "Step done" in neutral and "wallet-link" not in neutral)

    # State of an offer, as its page shows it
    created = httpx.post(f"{URL['test_tools']}/api/offers", json={"credentials": {"pid": {}, "mandate": {}}, "label": "State"}).json()
    status_url = f"{URL['test_tools']}/oid4vci/offers/{created['offer_id']}/status"
    state = httpx.get(status_url).json()
    check("Offer open: time left, nothing issued", state["status"] == "OPEN" and 0 < state["expires_in"] <= 600 and state["issued"] == [], json.dumps(state))
    Wallet().receive(created["link"])
    state = httpx.get(status_url).json()
    check("Offer picked up: all credentials named",
          state["status"] == "PICKED_UP" and sorted(state["issued"]) == ["Test PID", "Test mandate (register)"], json.dumps(state))  # fmt: skip
    try:
        Wallet().receive(created["link"])
        check("Offer picked up: a second wallet gets nothing", False, "no error")
    except holder.WalletError as exc:
        check("Offer picked up: a second wallet gets nothing", "400" in str(exc), str(exc))
    unknown = httpx.get(f"{URL['test_tools']}/oid4vci/offers/unknown/status").json()
    check("Unknown offer counts as expired", unknown["status"] == "EXPIRED", json.dumps(unknown))
    issuer = Issuer("http://issuer.test", ec.generate_private_key(ec.SECP256R1()), {}, {"pid": {"vct": "x", "name": "x", "labels": {}}}, "Test")
    offer_id, _ = issuer.create_offer({"pid": {}})
    issuer.offers[offer_id]["expires"] = time.time() - 1
    check("Offer after its time: expired", issuer.offer_status(offer_id)["status"] == "EXPIRED")
    check("Test tools page tracks all offers", httpx.get(URL["test_tools"] + "/").text.count("data-offer=") == 4)

    # 15 Audit log without personal data
    audit = (TMP / "audit.log").read_text()
    check("15 Audit log without personal data",
          not any(word in audit for word in ("Erika", "Mustermann", "1984-01-26", "Beispiel", "1990-05-05")))  # fmt: skip


if __name__ == "__main__":
    main()
