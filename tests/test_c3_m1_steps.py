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
"""C3-M1 steps and queries against C1-M2 as seen through its interface (README 8, 9, 11.1, 13).

The applications of README 14 (A1, A2, A3, A5) are seeded into `APPLICATIONS`, in the shape of
C1-M2's `ApplicationInternal` (C1-M2 openapi.yaml). The autouse fixture `_c1_m2` answers the two
C1-M2 queries C3-M1 makes (`get_application_internal`, `list_agreements_internal`) from there; all
other neighbour calls go through unchanged. The tests therefore never touch the internal storage of
any C1-M2 implementation (the stand-in of the kit or Team 1's module alike). Other C3-M1 test files
that seed applications import `_c1_m2` with `seed`.
"""
import copy
import json

import pytest

from modules.c3_m1 import interface, store
from portal_common import events, neighbours
from portal_common.problems import Problem
from tools import testdata

U1 = "c0000001-0000-4000-8000-000000000001"
U2 = "c0000002-0000-4000-8000-000000000002"
U3 = "c0000003-0000-4000-8000-000000000003"
A1 = "a0000001-0000-4000-8000-000000000001"
A2 = "a0000002-0000-4000-8000-000000000002"
A3 = "a0000003-0000-4000-8000-000000000003"
A5 = "a0000005-0000-4000-8000-000000000005"
P1 = "5a1c0001-0000-4000-8000-000000000001"

ATTESTATION = {"attestationId": "3f6c1e2a-7b4d-4e8f-9a51-2c0d6b8e4f17",
               "verifiedAt": "2026-11-06T08:00:00+00:00"}
CONSENTS = [{"agreementKey": "terms-active-participant", "version": "1.0", "language": "en",
             "givenAt": "2026-11-06T08:05:00+00:00"},
            {"agreementKey": "security-regulations", "version": "1.0", "language": "en",
             "givenAt": "2026-11-06T08:05:00+00:00"}]
ADDRESS = {"streetName": "Musterstraße", "streetNumber": "1", "postalCode": "70569",
           "city": "Stuttgart", "region": "BW", "countryCode": "DE"}


APPLICATIONS: dict[str, dict] = {}   # applicationId -> ApplicationInternal, as C1-M2 answers it


@pytest.fixture(autouse=True)
def _state():
    interface.reset()
    yield


@pytest.fixture(autouse=True)
def _c1_m2(monkeypatch):
    """C1-M2 as C3-M1 sees it over the neighbour call (11.1): the seeded applications and the
    terms of the shared catalogue, in the shapes of C1-M2's openapi.yaml. Unknown applications are
    `None`, as `neighbours.query` answers a 404 of the neighbour."""
    original = neighbours.query
    APPLICATIONS.clear()

    def query(caller, target, function, /, **params):
        if target == "c1-m2" and function == "get_application_internal":
            found = APPLICATIONS.get(params.get("applicationId") or "")
            return copy.deepcopy(found) if found is not None else None
        if target == "c1-m2" and function == "list_agreements_internal":
            if params.get("status") not in (None, "ACTIVE"):
                return []
            return [{k: x[k] for k in ("agreementKey", "version", "party", "scope", "companyRoles", "title",
                                       "documentUrls")} | {"status": "ACTIVE"} for x in testdata.agreements()]
        return original(caller, target, function, **params)

    monkeypatch.setattr(neighbours, "query", query)
    yield
    APPLICATIONS.clear()


def seed(application: str = A1, company: str = U1, **over) -> dict:
    """Seed an application of README 14 as C1-M2 answers it (`ApplicationInternal`)."""
    private = [key for key in over if key.startswith("_")]
    assert not private, f"use the public fields of ApplicationInternal, not {private}"
    entry = {
        "id": application, "companyId": company, "kind": "ONBOARDING", "existingCompany": False,
        "status": "SUBMITTED", "verification": "EBW", "attestation": ATTESTATION,
        "applicant": {"sub": P1},
        "companyData": {"legalName": "Beispiel Maschinenbau GmbH", "address": ADDRESS,
                        "identifiers": [{"type": "EBWOID", "value": "EBWOID-DE-0000000001",
                                         "source": "ATTESTATION"},
                                        {"type": "EUID", "value": "DEXX001T.HRB100001",
                                         "source": "ATTESTATION"},
                                        {"type": "VAT_ID", "value": "DE123456789",
                                         "source": "APPLICANT"}]},
        "companyRoles": ["ACTIVE_PARTICIPANT"], "consents": CONSENTS,
    }
    entry.update(over)
    roles = entry.get("companyRoles") or []
    entry.setdefault("requiredAgreements", [] if entry["status"] == "CREATED" else [
        {"agreementKey": x["agreementKey"], "version": x["version"]} for x in testdata.required_agreements(roles)])
    APPLICATIONS[entry["id"]] = entry
    return entry


def step(name: str, **payload) -> dict:
    payload.setdefault("processId", "p-1")
    payload.setdefault("stepRunId", "s-1")
    return getattr(interface, name)(payload)


def published(name: str) -> list[dict]:
    return [event for event in events.RELAY.log if event["type"] == name]


# ------------------------------------------------------------------------------ 13.1, 13.2, 13.28
def test_create_company_maps_the_application():
    seed()
    reply = step("create_company", companyId=U1, applicationId=A1)
    assert reply["result"]["status"] == "REQUESTED"
    row = store.get_company(U1)
    assert row["core_data_source"] == "EBW"
    assert row["verification_ref"] == ATTESTATION["attestationId"]
    assert row["core_data_verified_at"] == ATTESTATION["verifiedAt"]
    identifiers = {entry["type"]: entry["source"] for entry in store.list_identifiers(U1)}
    assert identifiers == {"EBWOID": "BUSINESS_WALLET", "EUID": "BUSINESS_WALLET", "VAT_ID": "DECLARED"}
    assert store.role_status(U1, "ACTIVE_PARTICIPANT") == "REQUESTED"
    assert len(published("CompanyCreated")) == 1
    assert published("CompanyCreated")[0]["data"]["coreDataSource"] == "EBW"


def test_create_company_is_idempotent():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    reply = step("create_company", companyId=U1, applicationId=A1)
    assert reply["state"] == "DONE"
    assert len(published("CompanyCreated")) == 1
    assert len(store.find_companies(size=100)[0]) == 2   # seed company + U1


def test_create_company_conflicts():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    with pytest.raises(Problem) as error:
        step("create_company", companyId=U1, applicationId=A2)
    assert error.value.status == 409 and error.value.name == "conflict"


def test_create_company_refuses_a_reactivation():
    seed(A5, U1, kind="REACTIVATION")
    with pytest.raises(Problem) as error:
        step("create_company", companyId=U1, applicationId=A5)
    assert error.value.status == 409 and error.value.name == "conflict"


def test_create_company_needs_an_ebwoid_with_a_verification():
    seed()
    APPLICATIONS[A1]["companyData"]["identifiers"] = [
        {"type": "VAT_ID", "value": "DE123456789", "source": "APPLICANT"}]
    with pytest.raises(Problem) as error:
        step("create_company", companyId=U1, applicationId=A1)
    assert error.value.status == 400 and error.value.name == "validation"


def test_create_company_needs_a_submitted_application():
    seed(status="CREATED")
    with pytest.raises(Problem) as error:
        step("create_company", companyId=U1, applicationId=A1)
    assert error.value.status == 409 and error.value.name == "invalid-state"


def test_create_company_writes_an_audit_entry_without_a_sub():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    entry = store.list_audit(U1)[-1]
    assert entry["sub"] == "" and entry["operation"] == "stepCreateCompany"
    assert entry["details"]["processId"] == "p-1" and entry["details"]["stepRunId"] == "s-1"


# ------------------------------------------------------------------------------ 13.3, 13.4, 13.5
def test_activate_before_the_bpn():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    with pytest.raises(Problem) as error:
        step("activate_company", companyId=U1, applicationId=A1)
    assert error.value.status == 409 and error.value.name == "identifier-missing"


def test_assign_identifier_and_its_errors():
    seed()
    seed(A3, U3, verification="DOCUMENTS", attestation=None, companyRoles=["ACTIVE_PARTICIPANT"],
         companyData={"legalName": "Ohne Zustimmung GmbH", "address": ADDRESS,
                      "identifiers": [{"type": "VAT_ID", "value": "DE111111111", "source": "APPLICANT"}]},
         consents=[])
    step("create_company", companyId=U1, applicationId=A1)
    step("create_company", companyId=U3, applicationId=A3)

    reply = step("assign_identifier", companyId=U1, bpn="BPNLIUK2REMLK3F4")
    assert reply["result"]["bpn"] == "BPNLIUK2REMLK3F4"
    assert len(published("CompanyIdentifierAssigned")) == 1
    assert step("assign_identifier", companyId=U1, bpn="BPNLIUK2REMLK3F4")["state"] == "DONE"
    assert len(published("CompanyIdentifierAssigned")) == 1

    with pytest.raises(Problem) as error:
        step("assign_identifier", companyId=U1, bpn="BPNL00000000U2LG")
    assert error.value.name == "bpn-mismatch"
    with pytest.raises(Problem) as error:
        step("assign_identifier", companyId=U3, bpn="BPNLIUK2REMLK3F4")
    assert error.value.name == "bpn-taken"
    with pytest.raises(Problem) as error:
        step("assign_identifier", companyId=U3, bpn="nope")
    assert error.value.status == 400 and error.value.name == "validation"


def test_activate_takes_over_the_consents():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    step("assign_identifier", companyId=U1, bpn="BPNLIUK2REMLK3F4")
    reply = step("activate_company", companyId=U1, applicationId=A1)
    assert reply["result"]["status"] == "ACTIVE"
    assert store.role_status(U1, "ACTIVE_PARTICIPANT") == "ACTIVE"
    consents = {c["agreement_key"]: c for c in store.list_consents(U1)}
    assert consents["terms-active-participant"]["consented_by"] == P1
    assert consents["terms-active-participant"]["source_kind"] == "APPLICATION"
    assert len(published("CompanyActivated")) == 1
    assert step("activate_company", companyId=U1, applicationId=A1)["state"] == "DONE"
    assert len(published("CompanyActivated")) == 1


def test_activate_without_consents_keeps_requested():
    seed(A3, U3, verification="DOCUMENTS", attestation=None, consents=[])
    step("create_company", companyId=U3, applicationId=A3)
    step("assign_identifier", companyId=U3, bpn="BPNL00000000U3OZ")
    with pytest.raises(Problem) as error:
        step("activate_company", companyId=U3, applicationId=A3)
    assert error.value.status == 409 and error.value.name == "roles-without-consent"
    assert store.get_company(U3)["status"] == "REQUESTED"


# ---------------------------------------------------------------------------------- 13.6, 13.7
def test_reject_company():
    seed(A3, U3, verification="DOCUMENTS", attestation=None, consents=[])
    step("create_company", companyId=U3, applicationId=A3)
    reply = step("reject_company", companyId=U3)
    assert reply["result"]["status"] == "REJECTED"
    assert len(published("CompanyRejected")) == 1
    assert step("reject_company", companyId=U3)["state"] == "DONE"
    assert len(published("CompanyRejected")) == 1

    seed()
    step("create_company", companyId=U1, applicationId=A1)
    step("assign_identifier", companyId=U1, bpn="BPNLIUK2REMLK3F4")
    step("activate_company", companyId=U1, applicationId=A1)
    with pytest.raises(Problem) as error:
        step("reject_company", companyId=U1)
    assert error.value.name == "invalid-state"


# ------------------------------------------------------------------------------------ 13.23, 13.24
def test_bulk_query_keeps_the_order_and_reports_the_missing():
    seed()
    seed(A2, U2, verification="DOCUMENTS", attestation=None,
         companyData={"legalName": "Beispiel Logistik GmbH", "address": ADDRESS,
                      "identifiers": [{"type": "VAT_ID", "value": "DE987654321", "source": "APPLICANT"}]},
         consents=[])
    step("create_company", companyId=U1, applicationId=A1)
    step("create_company", companyId=U2, applicationId=A2)
    answer = interface.query_companies(id=[U2, "c0000009-0000-4000-8000-000000000009", U1])
    assert [item["id"] for item in answer["items"]] == [U2, U1]
    assert answer["notFound"] == ["c0000009-0000-4000-8000-000000000009"]
    with pytest.raises(Problem):
        interface.query_companies(id=[U1], bpn=["BPNLIUK2REMLK3F4"])


def test_identifier_matches_normalise_and_exclude():
    seed()
    step("create_company", companyId=U1, applicationId=A1)
    matches = interface.find_identifier_matches(
        identifiers=[{"type": "VAT_ID", "value": "de 123.456.789"}])
    assert [match["companyId"] for match in matches["matches"]] == [U1]
    assert matches["matches"][0]["matchedOn"] == ["VAT_ID"]
    assert interface.find_identifier_matches(
        identifiers=[{"type": "VAT_ID", "value": "de 123.456.789"}],
        excludeCompanyId=U1)["matches"] == []


# --------------------------------------------------------------------------------------------- 13.28
def test_the_built_in_stand_in_reads_the_stub_file(tmp_path, monkeypatch):
    """28: without an address for C1-M2 the module answers from `STUB_APPLICATIONS_FILE`."""
    monkeypatch.setenv("MODULE_URLS_DEFAULT", "")          # no neighbour: built-in stand-in
    stub = tmp_path / "stub-applications.json"
    stub.write_text(json.dumps({"applications": [{
        "id": A1, "companyId": U1, "kind": "ONBOARDING", "existingCompany": False,
        "status": "SUBMITTED", "verification": "EBW", "attestation": ATTESTATION,
        "applicant": {"sub": P1},
        "companyData": {"legalName": "Beispiel Maschinenbau GmbH", "address": ADDRESS,
                        "identifiers": [{"type": "EBWOID", "value": "EBWOID-DE-0000000001",
                                         "source": "ATTESTATION"},
                                        {"type": "VAT_ID", "value": "DE123456789",
                                         "source": "APPLICANT"}]},
        "companyRoles": ["ACTIVE_PARTICIPANT"], "consents": CONSENTS}]}), encoding="utf-8")
    monkeypatch.setenv("STUB_APPLICATIONS_FILE", str(stub))

    step("create_company", companyId=U1, applicationId=A1)
    step("assign_identifier", companyId=U1, bpn="BPNLIUK2REMLK3F4")
    reply = step("activate_company", companyId=U1, applicationId=A1)
    assert reply["result"]["status"] == "ACTIVE"
    assert store.role_status(U1, "ACTIVE_PARTICIPANT") == "ACTIVE"


# --------------------------------------------------------------------------------------------- 13.25
def test_the_seed_company_is_there_after_reset():
    row = store.get_company("11111111-1111-4111-8111-111111111111")
    assert row["status"] == "ACTIVE" and row["bpn"] == "BPNL00000000OSPA"
    assert set(store.list_roles(row["id"])) == {"ONBOARDING_SERVICE_PROVIDER", "ACTIVE_PARTICIPANT",
                                                "APP_PROVIDER", "SERVICE_PROVIDER"}
    assert events.RELAY.log == []
