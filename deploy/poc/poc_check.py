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
#  Assisted-By: Claude Code (claude-opus-5-5)
"""Checks the PoC of the runtime split (ADR-0002) against `docker-compose.poc.yml`.

    docker compose -f docker-compose.yml -f docker-compose.poc.yml up -d --build
    uv run python deploy/poc/poc_check.py

1. each pod serves only its module;
2. synchronous call over HTTP: C3-M1 `create-company` asks C1-M2 (service token) and maps its 404;
3. event over the inbox: the `CompanyDeactivated` that C3-M1 publishes arrives at C1-M2.
Exit code 0 = green. The state is in memory: restart the pods to run it again.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import httpx

GATEWAY = "http://localhost:8000"
IAM = "http://localhost:8080/auth/realms/CX-Central/protocol/openid-connect/token"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.poc.yml"]
OSP_COMPANY = "11111111-1111-4111-8111-111111111111"
UNKNOWN_APPLICATION = "0f8e2d4c-6b1a-4c3e-8f7d-2a9b1c0d3e4f"


def pod(service: str, path: str):
    out = subprocess.run([*COMPOSE, "exec", "-T", service, "wget", "-qO-", f"http://localhost:8000{path}"],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail and not ok else ''}")
    return ok


def main() -> int:
    token = httpx.post(IAM, data={"grant_type": "client_credentials", "client_id": "svc-c12-m1",
                                  "client_secret": "test-only-service-secret"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    results = [
        check("C1-M2 pod serves only c1-m2", [m["module"] for m in pod("c1-m2", "/scaffold/modules")] == ["c1-m2"]),
        check("C3-M1 pod serves only c3-m1", [m["module"] for m in pod("c3-m1", "/scaffold/modules")] == ["c3-m1"]),
    ]
    r = httpx.post(f"{GATEWAY}/api/c3-m1/steps/create-company", headers=headers, json={
        "processId": "poc", "stepRunId": "poc-1", "companyId": "c0000001-0000-4000-8000-000000000001",
        "applicationId": UNKNOWN_APPLICATION})
    results.append(check("C3-M1 asks C1-M2 over HTTP (404 of C1-M2 mapped, no 502)",
                         r.status_code == 404 and r.json()["type"] == "urn:c3-m1:problem:not-found", r.text))
    r = httpx.post(f"{GATEWAY}/api/c3-m1/steps/deactivate-company", headers=headers, json={
        "processId": "poc", "stepRunId": "poc-2", "companyId": OSP_COMPANY, "reason": "MANUAL"})
    results.append(check("C3-M1 step answers DONE through the gateway", r.status_code == 200, r.text))
    arrived = []
    for _ in range(20):
        arrived = [e for e in pod("c1-m2", "/scaffold/events")["events"] if e["type"] == "CompanyDeactivated"]
        if arrived:
            break
        time.sleep(0.5)
    results.append(check("CompanyDeactivated of C3-M1 arrives at the C1-M2 pod", bool(arrived)
                         and arrived[0]["source"] == "urn:c3-m1"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
