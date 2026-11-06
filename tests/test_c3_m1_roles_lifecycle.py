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
"""Company roles with consents, deactivation, return and transfer (README 7.7-7.9, 7.13, 8.5, 8.6, 13.19-13.22, 13.26, 13.27)."""
import pytest

from modules.c3_m1 import interface, store
from portal_common import events
from portal_common.problems import Problem

from test_c3_m1_api import S2, U1, U2, active, call, client  # noqa: F401
from test_c3_m1_attestation import _keys  # noqa: F401  (fixture: attestation environment)
from test_c3_m1_steps import A1, A3, ADDRESS, CONSENTS, P1, U3, _c1_m2, seed, step  # noqa: F401  (_c1_m2: fixture)

A5 = "a0000005-0000-4000-8000-000000000005"
A6 = "a0000006-0000-4000-8000-000000000006"
A7 = "a0000007-0000-4000-8000-000000000007"
A8 = "a0000008-0000-4000-8000-000000000008"
U4 = "c0000004-0000-4000-8000-000000000004"
S2_SUB = "5a1c0012-0000-4000-8000-000000000012"
P1_SUB = "5a1c0001-0000-4000-8000-000000000001"

CONSENT_APP = [{"agreementKey": "terms-app-provider", "version": "1.0"}]


# ------------------------------------------------------------------------------------------ 13.27
def test_a_role_is_added_with_its_consents(active):
    roles = interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": CONSENT_APP},
                                       P1_SUB)
    states = {role["companyRole"]: role for role in roles}
    assert states["APP_PROVIDER"]["status"] == "ACTIVE"
    consent = store.get_consent(U1, "terms-app-provider")
    assert consent["status"] == "ACTIVE" and consent["consented_by"] == P1_SUB
    assert events.RELAY.log[-1]["type"] == "CompanyRolesChanged"
    # a second call changes nothing
    events.RELAY.log.clear()
    interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": CONSENT_APP}, P1_SUB)
    assert events.RELAY.log == []


def test_the_consent_checks(active):
    with pytest.raises(Problem) as error:
        interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": []}, P1_SUB)
    assert error.value.status == 400 and error.value.name == "consent-missing"
    assert error.value.ext["missing"] == ["terms-app-provider"]

    with pytest.raises(Problem) as error:
        interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": [
            {"agreementKey": "terms-app-provider", "version": "0.9"}]}, P1_SUB)
    assert error.value.name == "consent-missing"

    with pytest.raises(Problem) as error:
        interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": CONSENT_APP + [
            {"agreementKey": "security-regulations", "version": "1.0"}]}, P1_SUB)
    assert error.value.status == 400 and error.value.name == "validation"

    with pytest.raises(Problem) as error:
        interface.add_company_role(U1, {"companyRole": "NOPE", "consents": []}, P1_SUB)
    assert error.value.name == "validation"


def test_the_seed_role_is_not_assignable(active):
    with pytest.raises(Problem) as error:
        interface.add_company_role(U1, {"companyRole": "ONBOARDING_SERVICE_PROVIDER",
                                        "consents": []}, P1_SUB)
    assert error.value.status == 409 and error.value.name == "role-not-assignable"


def test_the_last_role_cannot_be_removed(active):
    interface.add_company_role(U1, {"companyRole": "APP_PROVIDER", "consents": CONSENT_APP}, P1_SUB)
    interface.remove_company_role(U1, "APP_PROVIDER", P1_SUB)
    assert store.get_consent(U1, "terms-app-provider")["status"] == "INACTIVE"
    with pytest.raises(Problem) as error:
        interface.remove_company_role(U1, "ACTIVE_PARTICIPANT", P1_SUB)
    assert error.value.status == 409 and error.value.name == "last-role"


# ------------------------------------------------------------------------------------------ 13.19
def test_the_osp_deactivation_and_the_lock_while_inactive(active):
    answer = interface.deactivate_company_by_staff(U1, {"reason": "Vertrag beendet"}, S2_SUB)
    assert answer["status"] == "INACTIVE" and answer["deactivationReason"] == "MANUAL"
    event = events.RELAY.log[-1]
    assert event["type"] == "CompanyDeactivated" and event["data"]["reason"] == "MANUAL"
    assert "Vertrag beendet" not in str(event["data"])
    assert interface.deactivate_company_by_staff(U1, {"reason": "nochmal"}, S2_SUB)["status"] == "INACTIVE"
    with pytest.raises(Problem) as error:
        interface.update_company(U1, {"shortName": "x"}, P1_SUB)
    assert error.value.status == 409 and error.value.name == "invalid-state"


# ------------------------------------------------------------------------------------------ 13.20
def test_the_reactivation_with_a_new_attestation(active):
    interface.deactivate_company_by_staff(U1, {"reason": "Pause"}, S2_SUB)
    seed(A5, U1, status="APPROVED", kind="REACTIVATION", companyData={
        "legalName": "Beispiel Maschinenbau GmbH", "address": dict(ADDRESS, streetName="Musterstraße",
                                                                   streetNumber="7"),
        "identifiers": [{"type": "EBWOID", "value": "EBWOID-DE-0000000001", "source": "ATTESTATION"},
                        {"type": "VAT_ID", "value": "DE123456789", "source": "APPLICANT"}]})
    events.RELAY.log.clear()
    answer = step("reactivate_company", companyId=U1, applicationId=A5)
    assert answer["result"]["status"] == "ACTIVE"
    row = store.get_company(U1)
    assert row["street"] == "Musterstraße" and row["house_number"] == "7"
    assert row["core_data_source"] == "EBW" and row["deactivation_reason"] is None
    types = [event["type"] for event in events.RELAY.log]
    assert types == ["CompanyDataChanged", "CompanyReactivated"]

    events.RELAY.log.clear()
    assert step("reactivate_company", companyId=U1, applicationId=A5)["state"] == "DONE"
    assert events.RELAY.log == []


def test_the_reactivation_needs_the_matching_kind(active):
    step("deactivate_company", companyId=U1, reason="TRANSFERRED")
    seed(A6, U1, kind="REACTIVATION", status="APPROVED")
    with pytest.raises(Problem) as error:
        step("reactivate_company", companyId=U1, applicationId=A6)
    assert error.value.status == 409 and error.value.name == "invalid-state"


# ------------------------------------------------------------------------------------------ 13.21
def test_the_transfer_away_and_the_return(active):
    answer = step("deactivate_company", companyId=U2, reason="TRANSFERRED")
    assert answer["result"]["deactivationReason"] == "TRANSFERRED"
    assert events.RELAY.log[-1]["data"]["reason"] == "TRANSFERRED"
    events.RELAY.log.clear()
    step("deactivate_company", companyId=U2, reason="TRANSFERRED")
    assert events.RELAY.log == []

    seed(A7, U2, status="APPROVED", kind="TRANSFER", verification="DOCUMENTS", attestation=None)
    assert step("assign_identifier", companyId=U2, bpn="BPNL00000000U2LG")["state"] == "DONE"
    assert step("reactivate_company", companyId=U2, applicationId=A7)["result"]["status"] == "ACTIVE"


# ------------------------------------------------------------------------------------------ 13.22
def test_a_company_transfers_to_this_installation():
    seed(A8, U4, kind="TRANSFER", companyData={
        "legalName": "Andere Beispiel AG", "address": {"streetName": "Beispielweg", "streetNumber": "2",
                                                       "postalCode": "80331", "city": "München",
                                                       "region": "BY", "countryCode": "DE"},
        "identifiers": [{"type": "EBWOID", "value": "EBWOID-DE-0000000002", "source": "ATTESTATION"}]})
    step("create_company", companyId=U4, applicationId=A8)
    step("assign_identifier", companyId=U4, bpn="BPNL00000000002B")
    answer = step("activate_company", companyId=U4, applicationId=A8)
    assert answer["result"]["status"] == "ACTIVE"
    assert store.get_company(U4)["bpn"] == "BPNL00000000002B"


# ------------------------------------------------------------------------------------------ 13.26, 13.27 over HTTP
def test_the_roles_are_visible_with_terms(client, active):
    response = call(client, "GET", f"/api/c3-m1/companies/{U1}/company-roles?lang=de", P1)
    assert response.status_code == 200
    states = {role["companyRole"]: role for role in response.json()}
    assert states["ACTIVE_PARTICIPANT"]["status"] == "ACTIVE"
    assert [term["agreementKey"] for term in states["ACTIVE_PARTICIPANT"]["agreements"]] == \
        ["terms-active-participant", "security-regulations"]
    assert "APP_PROVIDER" in states


def test_no_token_attestation_document_or_person_name_leaks(active, _keys):
    """13.26: no JWT, no document content, no token, no names of people in events or audit."""
    from test_c3_m1_attestation import claims as attestation_claims, sign

    interface.create_change_request(U1, {"comment": "privat", "identifiers": [
        {"type": "VAT_ID", "value": "DE555444333"}]},
        [("auszug.pdf", b"%PDF-1.7 Vertraulich", "application/pdf")], P1_SUB)
    interface.update_company_from_attestation(U1, {"attestation": sign(attestation_claims())}, P1_SUB)
    interface.deactivate_company_by_staff(U1, {"reason": "Grund"}, S2_SUB)

    dumps = [str(event["data"]) for event in events.RELAY.log] + \
            [str(entry["details"]) for entry in store.list_audit(U1)]
    assert len(dumps) > 5
    for text in dumps:
        assert "eyJ" not in text          # no attestation, no token
        assert "%PDF" not in text         # no document content
        assert "Mustermann" not in text   # no names of people
