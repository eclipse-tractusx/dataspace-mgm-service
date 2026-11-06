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
"""C3-M1 with the default configuration of installation OSP A (the whole app of `scaffold.app`):
`POST /companies/{companyId}/attestation-updates` trusts the installation's own EBW-Connector
(`ATTESTATION_JWKS_URL`, here the in-process double at `{BASE_URL}/ebw/jwks`) and no other key
(README 4, 6.7, 11.2; FRAMEWORK 4.8; OPEN-QUESTIONS 7)."""
import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from conftest import BASE, bearer, person_token
from modules.c3_m1 import config, store
from portal_common import http as phttp
from tools import test_iam
from tools.keys import ec_jwk

from test_c3_m1_steps import A1, U1, _c1_m2, seed, step  # noqa: F401  (_c1_m2: fixture)

BPN_U1 = "BPNLIUK2REMLK3F4"


@pytest.fixture
def osp_a(monkeypatch):
    """Installation OSP A as configured (config/osp-a), no test override of the attestation keys."""
    for name in [k for k in os.environ if k.startswith("ATTESTATION_")]:
        monkeypatch.delenv(name)
    before = set(os.environ)
    from scaffold.app import create_app, reset_all
    app = create_app()
    phttp.register_local(BASE, app)
    try:
        with TestClient(app, base_url=BASE) as client:
            seed(A1, U1)
            for name, extra in (("create_company", {}), ("assign_identifier", {"bpn": BPN_U1}),
                                ("activate_company", {})):
                step(name, companyId=U1, applicationId=A1, **extra)
            iam = test_iam.iam()
            erika = iam.find("erika")
            iam.add_portal_roles(erika, ["Company Admin"])
            iam.bind(erika, U1, BPN_U1)
            yield client
    finally:
        reset_all(app.state.entries)
        for name in set(os.environ) - before:     # the installation's defaults (create_app) stay out of later tests
            os.environ.pop(name, None)


def update(client: TestClient, attestation: str):
    return client.post(f"/api/c3-m1/companies/{U1}/attestation-updates", json={"attestation": attestation},
                       headers=bearer(person_token("erika")))


def test_the_installation_uses_its_ebw_connector_and_no_file(osp_a):
    assert config.attestation_jwks_file() is None
    assert config.attestation_jwks_url() == f"{BASE}/ebw/jwks"


def test_an_attestation_of_the_installations_ebw_connector_is_accepted(osp_a):
    real = osp_a.post("/ebw/test/attestations", json={"company": "maschinenbau", "clientId": "osp-a-ui"})
    r = update(osp_a, real.json()["attestation"])
    assert r.status_code == 200, r.json()
    assert store.get_company(U1)["core_data_source"] == "EBW"


def test_an_attestation_signed_with_another_key_is_refused(osp_a):
    """Guard: a key that is not the EBW-Connector's is not trusted, even with the kid of the key pair
    this module once shipped. (The fix itself is shown by the two tests above, which fail with the
    old default `ATTESTATION_JWKS_FILE`.)"""
    private, _ = ec_jwk("ebw-test-2026-1")
    now = int(time.time())
    claims = {"iss": os.environ["ATTESTATION_ISSUER"], "aud": "portal-registration", "client_id": "osp-a-ui",
              "purpose": "onboarding", "jti": f"forged-{now}", "iat": now - 10, "exp": now + 3600,
              "verified_at": now - 10, "representation": {"confirmed": True},
              "company": {"legal_name": "Mallory Takeover GmbH", "ebwoid": "EBWOID-DE-0000000001", "country": "DE"}}
    forged = jwt.encode(claims, jwt.PyJWK(private).key, algorithm="ES256",
                        headers={"typ": "ebw-attestation+jwt", "kid": private["kid"]})
    r = update(osp_a, forged)
    assert r.status_code == 400 and r.json()["reason"] == "signature", r.json()
    assert store.get_company(U1)["name"] == "Beispiel Maschinenbau GmbH"
