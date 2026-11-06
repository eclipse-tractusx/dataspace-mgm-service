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
"""Change requests with supporting documents and the four-eyes decision (README 7.4-7.6, 7.14-7.18, 13.13-13.16)."""
import pytest

from modules.c3_m1 import interface, store
from portal_common import events
from portal_common.problems import Problem

from test_c3_m1_api import P1, P3, S1, S2, U1, U2, active, call, client  # noqa: F401
from test_c3_m1_steps import _c1_m2  # noqa: F401  (fixture: C1-M2 as seen over the neighbour call)

PDF = ("auszug.pdf", b"%PDF-1.7 Auszug", "application/pdf")
S2_SUB = "5a1c0012-0000-4000-8000-000000000012"
S1_SUB = "bbede0f3-fbc4-433b-b7ca-1982e8724912"
P1_SUB = "5a1c0001-0000-4000-8000-000000000001"


def submit(company: str = U1, person: str = P1_SUB, **data) -> dict:
    payload = data or {"identifiers": [{"type": "VAT_ID", "value": "DE123456789"},
                                       {"type": "LEI_CODE", "value": "529900T8BM49AURSDO55"}]}
    payload.setdefault("comment", "Bitte ändern")
    return interface.create_change_request(company, payload, [PDF], person)


# ------------------------------------------------------------------------------------------ 13.13
def test_a_name_change_of_an_ebw_company_needs_the_attestation(active):
    with pytest.raises(Problem) as error:
        submit(name="Beispiel Maschinenbau AG")
    assert error.value.status == 409 and error.value.name == "attestation-required"


def test_the_event_fields_are_the_ones_c11_reads(active):
    """FRAMEWORK 6 / README 10: `companyId` and `changeRequestId`, closed also `outcome` (C11-M1)."""
    answer = submit()
    assert set(events.RELAY.log[-1]["data"]) == {"companyId", "changeRequestId"}
    interface.withdraw_change_request(U1, answer["id"], P1_SUB)
    closed = events.RELAY.log[-1]
    assert closed["type"] == "CompanyChangeRequestClosed"
    assert set(closed["data"]) == {"companyId", "changeRequestId", "outcome"}
    assert closed["data"]["outcome"] == "WITHDRAWN"


def test_a_request_with_identifiers_is_created(active):
    answer = submit()
    assert answer["status"] == "OPEN" and answer["documents"][0]["fileName"] == "auszug.pdf"
    assert len(events.RELAY.log) >= 1
    assert events.RELAY.log[-1]["type"] == "CompanyChangeRequestSubmitted"
    with pytest.raises(Problem) as error:
        submit()
    assert error.value.status == 409 and error.value.name == "change-request-open"


def test_a_request_needs_a_document_of_a_known_type(active):
    with pytest.raises(Problem) as error:
        interface.create_change_request(U1, {"comment": "ohne", "identifiers": [
            {"type": "VAT_ID", "value": "DE555444333"}]}, [])
    assert error.value.status == 400 and error.value.name == "document-invalid"
    with pytest.raises(Problem) as error:
        interface.create_change_request(U1, {"comment": "text", "identifiers": [
            {"type": "VAT_ID", "value": "DE555444333"}]},
            [("auszug.pdf", b"nur text", "application/pdf")])
    assert error.value.name == "document-invalid"


def test_a_request_without_a_change_is_refused(active):
    with pytest.raises(Problem) as error:
        submit(identifiers=[{"type": "VAT_ID", "value": "DE123456789"}])
    assert error.value.status == 400 and error.value.name == "validation"


# ------------------------------------------------------------------------------------------ 13.14
def test_review_download_and_approval_of_a_manual_company(active):
    answer = submit(U2, P3, name="Beispiel Logistik SE")
    listed = interface.list_change_requests(status=["OPEN"])
    assert [item["id"] for item in listed["items"]] == [answer["id"]]
    assert listed["items"][0]["companyName"] == "Beispiel Logistik GmbH"

    detail = interface.get_change_request(answer["id"])
    assert detail["company"]["name"] == "Beispiel Logistik GmbH"

    document = interface.get_change_request_document(answer["id"], answer["documents"][0]["id"],
                                                     S1_SUB)
    assert document["media_type"] == "application/pdf" and document["file_name"] == "auszug.pdf"
    assert [entry for entry in store.list_audit(U2) if entry["operation"] == "getChangeRequestDocument"]

    approved = interface.approve_change_request(answer["id"], {}, S1_SUB)
    assert approved["status"] == "APPROVED"
    row = store.get_company(U2)
    assert row["name"] == "Beispiel Logistik SE" and row["core_data_source"] == "MANUAL"
    types = [event["type"] for event in events.RELAY.log]
    assert "CompanyDataChanged" in types and "CompanyChangeRequestClosed" in types
    assert events.RELAY.log[-1]["data"]["outcome"] == "APPROVED"
    assert interface.approve_change_request(answer["id"], {}, S1_SUB)["status"] == "APPROVED"


# ------------------------------------------------------------------------------------------ 13.15
def test_decline_and_withdraw(active):
    answer = submit()
    with pytest.raises(Problem) as error:
        interface.decline_change_request(answer["id"], {}, S1_SUB)
    assert error.value.status == 400 and error.value.name == "validation"
    declined = interface.decline_change_request(answer["id"], {"reason": "Unterlagen fehlen"}, S1_SUB)
    assert declined["status"] == "DECLINED" and declined["decisionReason"] == "Unterlagen fehlen"
    own = interface.list_own_change_requests(U1)
    assert own["items"][0]["decisionReason"] == "Unterlagen fehlen"
    assert "decidedBy" not in own["items"][0] and own["items"][0]["status"] == "DECLINED"

    second = submit()
    withdrawn = interface.withdraw_change_request(U1, second["id"], P1_SUB)
    assert withdrawn["status"] == "WITHDRAWN"
    assert events.RELAY.log[-1]["data"]["outcome"] == "WITHDRAWN"
    events.RELAY.log.clear()
    assert interface.withdraw_change_request(U1, second["id"], P1_SUB)["status"] == "WITHDRAWN"
    assert events.RELAY.log == []

    with pytest.raises(Problem) as error:
        interface.withdraw_change_request(U1, answer["id"], P1_SUB)
    assert error.value.name == "invalid-state"


# ------------------------------------------------------------------------------------------ 13.16
def test_nobody_approves_their_own_request(active):
    osp_company = "11111111-1111-4111-8111-111111111111"
    answer = submit(osp_company, S2_SUB, identifiers=[{"type": "VAT_ID", "value": "DE999999999"}])
    with pytest.raises(Problem) as error:
        interface.approve_change_request(answer["id"], {}, S2_SUB)
    assert error.value.status == 409 and error.value.name == "same-person"
    assert interface.approve_change_request(answer["id"], {}, S1_SUB)["status"] == "APPROVED"


# ---------------------------------------------------------------------------------- 13.13 over HTTP
def test_submission_over_multipart(client, active):
    response = call(client, "POST", f"/api/c3-m1/companies/{U1}/change-requests", P1,
                    data={"data": '{"comment": "per HTTP", "identifiers": '
                                  '[{"type": "VAT_ID", "value": "DE555444333"}]}'},
                    files={"documents": PDF})
    assert response.status_code == 201 and response.json()["comment"] == "per HTTP"


def test_a_foreign_change_request_is_not_visible(client, active):
    answer = submit(U1, P1_SUB)
    assert call(client, "GET", f"/api/c3-m1/companies/{U2}/change-requests", P3).json()["total"] == 0
    assert call(client, "POST", f"/api/c3-m1/companies/{U2}/change-requests/{answer['id']}/withdraw",
                P3).status_code == 404
