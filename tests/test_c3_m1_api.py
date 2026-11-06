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
"""HTTP layer of C3-M1: permissions, scope `company`, corrections (README 6.8, 7.1, 7.2, 7.10-7.12, 13).

Tokens come from the in-memory test IAM of the scaffold; permissions are read from the spec there.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.c3_m1 import interface, router as c3_router
from portal_common import http as phttp
from portal_common import problems, standin
from tools import test_iam

from conftest import BASE, bearer, person_token

U1 = "c0000001-0000-4000-8000-000000000001"
U2 = "c0000002-0000-4000-8000-000000000002"
P1, P2, P3, P4 = "erika", "max", "hans", "lieschen"
S1, S2 = "rolf", "otto"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    problems.install(app)
    app.include_router(test_iam.router)
    app.include_router(c3_router.router)
    app.include_router(standin.fallback_router(c3_router.MODULE, c3_router.router))   # as scaffold/app.py
    phttp.register_local(BASE, app)
    interface.reset()
    return TestClient(app, base_url=BASE)


from test_c3_m1_steps import _c1_m2  # noqa: E402,F401  (fixture: C1-M2 as seen over the neighbour call)


@pytest.fixture
def active(client: TestClient) -> dict:
    """U1 and U2 ACTIVE with BPN, erika/max bound to U1, hans to U2."""
    from test_c3_m1_steps import A1, A2, seed, step
    seed(A1, U1)
    seed(A2, U2, verification="DOCUMENTS", attestation=None,
         companyData={"legalName": "Beispiel Logistik GmbH",
                      "address": {"streetName": "Hafenstraße", "streetNumber": "5",
                                  "postalCode": "68159", "city": "Mannheim", "countryCode": "DE"},
                      "identifiers": [{"type": "VAT_ID", "value": "DE987654321",
                                       "source": "APPLICANT"}]},
         consents=[{"agreementKey": "terms-active-participant", "version": "1.0",
                    "language": "en", "givenAt": "2026-11-06T08:05:00+00:00"},
                   {"agreementKey": "security-regulations", "version": "1.0",
                    "language": "en", "givenAt": "2026-11-06T08:05:00+00:00"}])
    for company, application, bpn in ((U1, A1, "BPNLIUK2REMLK3F4"), (U2, A2, "BPNL00000000U2LG")):
        step("create_company", companyId=company, applicationId=application)
        step("assign_identifier", companyId=company, bpn=bpn)
        step("activate_company", companyId=company, applicationId=application)
    iam = test_iam.iam()
    for person, role, company, bpn in ((P1, "Company Admin", U1, "BPNLIUK2REMLK3F4"),
                                       (P2, "Member", U1, "BPNLIUK2REMLK3F4"),
                                       (P3, "Company Admin", U2, "BPNL00000000U2LG")):
        uid = iam.find(person) or ""
        iam.add_portal_roles(uid, [role])
        iam.bind(uid, company, bpn)
    return {"U1": U1, "U2": U2}


def call(client: TestClient, method: str, path: str, person: str | None = None, **kwargs):
    """As a person; `person` = "svc" uses the service account of the module (query_c3_m1)."""
    if person == "svc":
        headers = bearer(test_iam.iam().client_token("svc-c3-m1"))
    else:
        headers = bearer(person_token(person)) if person else {}
    return client.request(method, path, headers=headers, **kwargs)


# ---------------------------------------------------------------------------------------- 13.8, 13.9
def test_the_scope_hides_other_companies(client, active):
    response = call(client, "GET", f"/api/c3-m1/companies/{U1}", P1)
    assert response.status_code == 200 and response.json()["dataspaceName"] == "Catena-X"
    assert call(client, "GET", f"/api/c3-m1/companies/{U2}", P1).status_code == 404
    assert call(client, "GET", f"/api/c3-m1/companies/{U1}", P3).status_code == 404
    assert call(client, "GET", f"/api/c3-m1/companies/{U1}", P4).status_code == 403
    assert call(client, "GET", "/api/c3-m1/companies/c0000009-0000-4000-8000-000000000009",
                P1).status_code == 404
    response = call(client, "GET", f"/api/c3-m1/companies/{U1}", P2)
    assert response.status_code == 200 and response.json()["id"] == U1
    assert response.json()["createdAt"]


def test_a_member_may_read_but_not_patch(client, active):
    assert call(client, "PATCH", f"/api/c3-m1/companies/{U1}", P2,
                json={"shortName": "x"}).status_code == 403


# ------------------------------------------------------------------------------------------ 13.10
def test_the_short_name_is_changed_and_locked_fields_refused(client, active):
    assert len(interface.store.list_audit(U1)) > 0
    response = call(client, "PATCH", f"/api/c3-m1/companies/{U1}", P1,
                    json={"shortName": "BMW"})
    assert response.status_code == 200 and response.json()["shortName"] == "BMW"
    audit = interface.store.list_audit(U1)[-1]
    assert audit["sub"] == "5a1c0001-0000-4000-8000-000000000001"
    assert audit["details"]["old"]["short_name"] is None

    response = call(client, "PATCH", f"/api/c3-m1/companies/{U1}", P1,
                    json={"shortName": "BMW"})
    assert response.status_code == 200

    response = call(client, "PATCH", f"/api/c3-m1/companies/{U1}", P1, json={"name": "Neu AG"})
    assert response.status_code == 409 and response.json()["type"].endswith("field-locked")
    assert response.json()["fields"] == ["name"]


# ------------------------------------------------------------------------------------- 13.17, 13.18
def test_osp_permissions_do_not_overlap(client, active):
    assert call(client, "GET", "/api/c3-m1/osp/change-requests", P1).status_code == 403
    assert call(client, "PATCH", f"/api/c3-m1/osp/companies/{U1}", S1, json={}).status_code == 403


def test_the_osp_correction_switches_the_source_to_manual(client, active):
    response = call(client, "PATCH", f"/api/c3-m1/osp/companies/{U1}", S2,
                    json={"address": {"street": "Neue Straße", "houseNumber": "9"}, "reason": "Hinweis"})
    assert response.status_code == 200
    body = response.json()
    assert body["address"]["street"] == "Neue Straße" and body["address"]["countryCode"] == "DE"
    assert body["coreDataSource"] == "MANUAL" and body["verificationRef"] is None
    assert body["coreDataVerifiedAt"] is not None
    assert [e for e in interface.store.list_audit(U1) if e["operation"] == "correctCompany"]


def test_the_country_is_locked_after_the_bpn(client, active):
    response = call(client, "PATCH", f"/api/c3-m1/osp/companies/{U1}", S2,
                    json={"countryCode": "US", "reason": "Umzug"})
    assert response.status_code == 409 and response.json()["fields"] == ["countryCode"]


def test_a_business_wallet_identifier_needs_the_attestation(client, active):
    response = call(client, "PATCH", f"/api/c3-m1/osp/companies/{U1}", S2,
                    json={"identifiers": [{"type": "EBWOID", "value": "EBWOID-DE-0000000009"},
                                          {"type": "VAT_ID", "value": "DE123456789"}],
                          "reason": "Korrektur"})
    assert response.status_code == 400 and response.json()["type"].endswith("validation")
    assert "identifiers.EBWOID" in [error["field"] for error in response.json()["errors"]]


def test_a_correction_without_a_reason_is_a_validation_error(client, active):
    response = call(client, "PATCH", f"/api/c3-m1/osp/companies/{U1}", S2,
                    json={"shortName": "X"})
    assert response.status_code == 400 and response.json()["type"].endswith("validation")


# ------------------------------------------------------------------------------- 7.10, 9.2, 9.3, 9.4
def test_the_search_filters_over_http(client, active):
    response = call(client, "GET", "/api/c3-m1/osp/companies?status=ACTIVE&hasBpn=true", S1)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert U1 in ids and U2 in ids
    assert response.json()["total"] >= 2
    assert call(client, "GET", "/api/c3-m1/osp/companies?status=nope", S1).status_code == 400


def test_the_bulk_query_takes_repeated_parameters(client, active):
    response = call(client, "GET",
                    f"/api/c3-m1/internal/companies?id={U2}&id={U1}&id=c0000009-0000-4000-8000-000000000009",
                    "svc")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [U2, U1]
    assert response.json()["notFound"] == ["c0000009-0000-4000-8000-000000000009"]


def test_the_identifier_search_over_http(client, active):
    response = call(client, "POST", "/api/c3-m1/internal/companies/identifier-matches", "svc",
                    json={"identifiers": [{"type": "VAT_ID", "value": "de 123.456.789"}]})
    assert response.status_code == 200
    assert [match["companyId"] for match in response.json()["matches"]] == [U1]


def test_the_role_catalogue_is_a_query(client, active):
    response = call(client, "GET", "/api/c3-m1/internal/company-roles?lang=de", "svc")
    assert response.status_code == 200 and isinstance(response.json(), list)
    roles = {role["companyRole"]: role for role in response.json()}
    assert roles["ACTIVE_PARTICIPANT"]["assignableBy"] == "COMPANY"
    assert roles["ACTIVE_PARTICIPANT"]["description"] == "Teilnehmer am Datenaustausch"
