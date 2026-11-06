#################################################################################
#  Copyright (c) 2026 Contributors to the Eclipse Foundation
#
#  See the NOTICE file(s) distributed with this work for additional
#  information regarding copyright ownership.
#
#  This program and the accompanying materials are made available under the
#  terms of the Apache License, Version 2.0 which is available at
#  https://www.apache.org/licenses/LICENSE-2.0.
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.
#
#  AI Disclosure: This file was entirely AI-generated.
#  The AI-generated portions are made available under CC0-1.0 and not subject
#  to the project's license. The human contributor has reviewed and verified
#  that the code is correct.
#
#  SPDX-License-Identifier: Apache-2.0 AND CC0-1.0
#  Assisted-By: Hermes Agent (deepseek-v4.1-flash)
#################################################################################
"""The verification attestation of README 6.7 and its use in 7.3 (acceptance 11, 12).

The key pair is generated when the tests start and its JWKS is written to a temporary file for
`ATTESTATION_JWKS_FILE`; no key is stored anywhere (OPEN-QUESTIONS 7, 8). T4 is signed with a
second key that is not in the JWKS.
"""
import datetime as dt
import json

import jwt
import pytest

from modules.c3_m1 import interface, store
from portal_common import events
from portal_common.problems import Problem
from tools.keys import ec_jwk

from test_c3_m1_api import P3, active, call, client  # noqa: F401  (fixtures for the HTTP test)
from test_c3_m1_steps import A1, U1, P1, U2, A2, _c1_m2, seed, step  # noqa: F401  (_c1_m2: fixture)

PRIVATE, PUBLIC = ec_jwk("ebw-test-2026-1")   # generated at start; no private key is stored


@pytest.fixture(autouse=True)
def _keys(monkeypatch, tmp_path):
    jwks = tmp_path / "ebw-jwks.json"
    jwks.write_text(json.dumps({"keys": [PUBLIC]}), encoding="utf-8")
    monkeypatch.setenv("ATTESTATION_ISSUER", "https://ebw-connector.example.org")
    monkeypatch.setenv("ATTESTATION_AUDIENCE", "portal-registration")
    monkeypatch.setenv("ATTESTATION_CLIENT_IDS", "demo-osp")
    monkeypatch.setenv("ATTESTATION_JWKS_FILE", str(jwks))
    interface.reset()
    yield


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def sign(claims: dict, key: dict = PRIVATE, *, typ: str = "ebw-attestation+jwt") -> str:
    return jwt.encode(claims, jwt.PyJWK(key).key, algorithm="ES256",
                      headers={"typ": typ, "kid": key["kid"]})


def claims(**over) -> dict:
    base = {
        "iss": "https://ebw-connector.example.org", "aud": "portal-registration",
        "client_id": "demo-osp", "purpose": "onboarding", "jti": "jti-t1",
        "iat": now(), "exp": now() + dt.timedelta(hours=1),
        "verified_at": int((now() - dt.timedelta(hours=1)).timestamp()),
        "company": {"legal_name": "Beispiel Maschinenbau AG",
                    "ebwoid": "EBWOID-DE-0000000001", "country": "DE",
                    "address": {"street_address": "Industriestraße 10", "postal_code": "70565",
                                "locality": "Stuttgart"}},
        "representation": {"confirmed": True, "result": "CONFIRMED"},
    }
    base.update(over)
    return base


def active_company(application: str = A1, company: str = U1) -> None:
    seed(application, company)
    step("create_company", companyId=company, applicationId=application)
    step("assign_identifier", companyId=company, bpn="BPNLIUK2REMLK3F4")
    step("activate_company", companyId=company, applicationId=application)


def update(company_id: str = U1, **over) -> dict:
    return interface.update_company_from_attestation(company_id, {"attestation": sign(claims(**over))}, P1)


# ---------------------------------------------------------------------------------------- 13.11
def test_a_valid_attestation_changes_the_core_data():
    active_company()
    answer = update()
    assert set(answer["changedFields"]) == {"name", "street", "houseNumber", "postalCode", "region"}
    row = store.get_company(U1)
    assert row["name"] == "Beispiel Maschinenbau AG"
    assert (row["street"], row["house_number"], row["region"]) == ("Industriestraße 10", None, None)
    assert row["country_code"] == "DE"
    assert row["core_data_source"] == "EBW" and row["verification_ref"] == "jti-t1"
    identifiers = {entry["type"]: entry["source"] for entry in store.list_identifiers(U1)}
    assert identifiers["EBWOID"] == "BUSINESS_WALLET"
    event = events.RELAY.log[-1]
    assert event["type"] == "CompanyDataChanged" and event["data"]["coreDataChanged"] is True
    with pytest.raises(Problem) as error:
        update()
    assert error.value.status == 409 and error.value.name == "attestation-used"


def test_an_unchanged_address_keeps_its_spelling():
    active_company()
    update()
    second = update(jti="jti-t2", verified_at=int((now() + dt.timedelta(minutes=1)).timestamp()),
                    **{"company": {
        "legal_name": "Beispiel Maschinenbau AG", "ebwoid": "EBWOID-DE-0000000001",
        "country": "DE", "address": {"street_address": "industriestraße 10",
                                     "postal_code": "70565", "locality": "STUTTGART"}}})
    assert second["changedFields"] == []


# ---------------------------------------------------------------------------------------- 13.12
def test_another_ebwoid_is_a_company_mismatch():
    active_company()
    with pytest.raises(Problem) as error:
        update(**{"company": {"legal_name": "X", "ebwoid": "EBWOID-DE-0000000009", "country": "DE"}})
    assert error.value.status == 409 and error.value.name == "company-mismatch"
    assert error.value.ext["fields"] == ["EBWOID"]


def test_an_unconfirmed_representation_is_refused():
    active_company()
    with pytest.raises(Problem) as error:
        update(representation={"confirmed": False, "result": "NOT_CONFIRMED"})
    assert error.value.name == "representation-not-confirmed"


def test_a_foreign_key_is_a_signature_error():
    active_company()
    from cryptography.hazmat.primitives.asymmetric import ec
    foreign = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(Problem) as error:
        interface.update_company_from_attestation(
            U1, {"attestation": jwt.encode(claims(), foreign, algorithm="ES256",
                                           headers={"typ": "ebw-attestation+jwt",
                                                    "kid": PRIVATE["kid"]})})
    assert error.value.status == 400
    assert error.value.name == "attestation-invalid" and error.value.ext["reason"] == "signature"


def test_a_too_old_attestation_is_refused():
    active_company()
    with pytest.raises(Problem) as error:
        update(verified_at=int((now() - dt.timedelta(days=3)).timestamp()))
    assert error.value.ext["reason"] == "too-old"


def test_an_older_attestation_does_not_reset_newer_data():
    active_company()
    update(jti="jti-new", verified_at=int((now() - dt.timedelta(minutes=30)).timestamp()))
    with pytest.raises(Problem) as error:
        update(jti="jti-old", verified_at=int((now() - dt.timedelta(hours=2)).timestamp()))
    assert error.value.status == 409 and error.value.name == "attestation-outdated"


@pytest.mark.parametrize("over,reason", [
    ({"iss": "https://other.example.org"}, "issuer"),
    ({"aud": "other"}, "audience"),
    ({"purpose": "login"}, "claims"),
    ({"client_id": "fremd"}, "claims"),
    ({"exp": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)}, "expired"),
    ({"iat": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)}, "not-yet-valid"),
    ({"jti": ""}, "claims"),
])
def test_the_reasons_of_a_refused_attestation(over, reason):
    active_company()
    with pytest.raises(Problem) as error:
        update(**over)
    assert error.value.name == "attestation-invalid" and error.value.ext["reason"] == reason


def test_the_wrong_typ_is_an_algorithm_error():
    active_company()
    with pytest.raises(Problem) as error:
        interface.update_company_from_attestation(U1, {"attestation": sign(claims(), typ="JWT")})
    assert error.value.ext["reason"] == "algorithm"


def test_a_broken_compact_serialisation_is_a_format_error():
    active_company()
    with pytest.raises(Problem) as error:
        interface.update_company_from_attestation(U1, {"attestation": "nur-ein-teil"})
    assert error.value.ext["reason"] == "format"


def test_an_unreadable_jwks_is_an_upstream_error(monkeypatch, tmp_path):
    active_company()
    monkeypatch.setenv("ATTESTATION_JWKS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(Problem) as error:
        update()
    assert error.value.status == 502 and error.value.name == "upstream-error"
    assert error.value.ext["retryable"] is True


def test_only_active_companies_take_an_attestation():
    seed(A1, U1)
    step("create_company", companyId=U1, applicationId=A1)
    with pytest.raises(Problem) as error:
        update()
    assert error.value.status == 409 and error.value.name == "invalid-state"


# ------------------------------------------------------------------------------------ 13.11 over HTTP
def test_the_endpoint_checks_permission_and_scope(client, active):
    url = f"/api/c3-m1/companies/{U1}/attestation-updates"
    body = {"attestation": sign(claims())}
    assert call(client, "POST", url, "max", json=body).status_code == 403     # Member
    assert call(client, "POST", url, P3, json=body).status_code == 404        # other company
    answer = call(client, "POST", url, P1, json=body)
    assert answer.status_code == 200 and "name" in answer.json()["changedFields"]
