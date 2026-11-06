#################################################################################
#  Copyright (c) 2026 Technovative Solutions
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
#  Assisted-By: Claude Code (claude-opus-5-5)
#################################################################################
"""C3-M1 in the flows of the real Process Orchestration (C12-M1 engine, flows.yaml): reactivation
(FRAMEWORK 5.5) and return of a company (5.6) reach `reactivate-company` while C1-M2 still has the
application SUBMITTED, and must complete (README 8.6, OPEN-QUESTIONS 12).

C3-M1 runs in-process and reads applications from its own C1-M2 stand-in (`STUB_APPLICATIONS_FILE`,
README 11.1); every other module is the built-in stand-in of the engine."""
import datetime as dt

import pytest

from modules.c12_m1 import engine as eng
from modules.c3_m1 import interface, store
from portal_common import events

U1, U2 = "c0000001-0000-4000-8000-000000000001", "c0000002-0000-4000-8000-000000000002"   # FRAMEWORK 7a
A1, A2 = "a0000001-0000-4000-8000-000000000001", "a0000002-0000-4000-8000-000000000002"   # README 14
A5, A7 = "a0000005-0000-4000-8000-000000000005", "a0000007-0000-4000-8000-000000000007"
ERIKA, HANS = "5a1c0001-0000-4000-8000-000000000001", "5a1c0003-0000-4000-8000-000000000003"
OTTO = "5a1c0012-0000-4000-8000-000000000012"                                              # OSP Admin
BPN_U1, BPN_U2 = "BPNLIUK2REMLK3F4", "BPNL00000000U2LG"


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("MODULE_URLS_DEFAULT", "")       # every neighbour: built-in stand-in ...
    monkeypatch.setenv("C3_M1_URL", "in-process")       # ... except C3-M1, the module under test
    monkeypatch.delenv("C1_M2_URL", raising=False)
    monkeypatch.delenv("REGISTRATION_URL", raising=False)
    monkeypatch.delenv("STUB_APPLICATIONS_FILE", raising=False)   # README 4 default: the module's file
    interface.reset()
    e = eng.reset()
    e.clock = lambda: dt.datetime(2026, 11, 6, 9, 0, tzinfo=dt.UTC)
    yield e
    interface.reset()


def active(company: str, application: str, bpn: str) -> None:
    for name, extra in (("create_company", {}), ("assign_identifier", {"bpn": bpn}), ("activate_company", {})):
        getattr(interface, name)({"processId": "p", "stepRunId": f"{name}-{company}", "companyId": company,
                                  "applicationId": application} | extra)


def event(module: str, etype: str, **data) -> dict:
    return events.cloudevent(module, etype, data, time="2026-11-06T09:30:00Z")


def run(engine, flow: str, application: str, company: str, kind: str, applicant: str, **extra) -> dict:
    data = {"applicationId": application, "companyId": company, "kind": kind, "existingCompany": True} | extra
    engine.on_event(event("c1-m2", "ApplicationSubmitted", applicantSub=applicant, **data))
    engine.on_event(event("c1-m3", "ApplicationApproved", **data))
    proc = next(p for p in engine.processes.values() if p["flowKey"] == flow)
    states = {s["stepKey"]: (s["state"], (s.get("lastError") or {}).get("detail")) for s in proc["steps"]}
    assert proc["status"] == "COMPLETED", states
    return proc


def test_reactivation_completes_with_the_application_submitted(engine):
    """FRAMEWORK 5.5: deactivated by OSP staff, reactivated through the flow `reactivation`."""
    active(U1, A1, BPN_U1)
    interface.deactivate_company_by_staff(U1, {"reason": "Pause"}, OTTO)
    assert interface._stub_applications()[A5]["status"] == "SUBMITTED"
    run(engine, "reactivation", A5, U1, "REACTIVATION", ERIKA)
    row = store.get_company(U1)
    assert (row["status"], row["deactivation_reason"]) == ("ACTIVE", None)


def test_return_completes_with_the_application_submitted(engine):
    """FRAMEWORK 5.6: the company moved away (deactivated TRANSFERRED) and comes back (flow `return`)."""
    active(U2, A2, BPN_U2)
    engine.on_event(event("c3-m2", "CompanyTransferredAway", companyId=U2, bpn=BPN_U2))
    assert store.get_company(U2)["deactivation_reason"] == "TRANSFERRED"
    assert interface._stub_applications()[A7]["status"] == "SUBMITTED"
    run(engine, "return", A7, U2, "TRANSFER", HANS, bpn=BPN_U2)
    row = store.get_company(U2)
    assert (row["status"], row["bpn"]) == ("ACTIVE", BPN_U2)
