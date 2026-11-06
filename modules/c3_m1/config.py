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
"""Configuration of C3-M1: the variables of README 4, read at call time and never at import.

FRAMEWORK 4.8 makes the example column the default, so a module starts without any setting. Values
that differ per installation (the seed company, the dataspace, the reference data) come from the
installation settings through `portal_common.settings`; the module keeps no installation data.

Paths in the settings count from the settings file (FRAMEWORK 4.8); the path of a configuration
variable (`COMPANY_ROLES_FILE`) counts from the repository root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from portal_common import settings
from portal_common.spec import ROOT

MODULE = "c3-m1"

#: README 4, example column: the default of every variable that has one (FRAMEWORK 4.8).
DEFAULTS = {
    "LANGUAGES": "de,en",
    "QUERY_MAX_COMPANIES": "100",
    "REGISTRATION_URL": "in-process",
    "COMPANY_ROLES_FILE": "config/company-roles.json",
    "ATTESTATION_ISSUER": "https://ebw.osp-a.example.org",
    "ATTESTATION_AUDIENCE": "portal-registration",
    "ATTESTATION_MAX_AGE_HOURS": "24",
    "ATTESTATION_CLOCK_SKEW_SECONDS": "60",
    "ATTESTATION_JWKS_CACHE_SECONDS": "300",
    "CHANGE_REQUESTS_ENABLED": "true",
    "CHANGE_REQUEST_MAX_DOCUMENTS": "3",
    "CHANGE_REQUEST_MAX_DOCUMENT_BYTES": "10485760",
    "STUB_APPLICATIONS_FILE": "stub-applications.json",
    "ATTESTATION_JWKS_FILE": "",   # tests only, no default: keys are never defaulted (FRAMEWORK 4.8)
}


def _fallback(path: Path, *candidates: Path) -> Path:
    return path if path.exists() else next((c for c in candidates if c.exists()), path)


def value(name: str, default: str | None = None) -> str:
    """The variable from the environment, else its README default, else `default` (or empty)."""
    if name in os.environ:
        return os.environ[name]
    if name in DEFAULTS:
        return DEFAULTS[name]
    return default if default is not None else ""


def number(name: str) -> int:
    try:
        return int(value(name))
    except ValueError:
        raise ValueError(f"{name}: not a number ({value(name)!r})") from None


def flag(name: str) -> bool:
    return value(name).strip().lower() in ("1", "true", "yes", "on")


def languages() -> list[str]:
    """Languages for descriptions in this installation; `en` always answers as the fallback."""
    return [code.strip() for code in value("LANGUAGES").split(",") if code.strip()] or ["en"]


def query_max_companies() -> int:
    return number("QUERY_MAX_COMPANIES")


def change_requests_enabled() -> bool:
    return flag("CHANGE_REQUESTS_ENABLED")


def change_request_max_documents() -> int:
    return number("CHANGE_REQUEST_MAX_DOCUMENTS")


def change_request_max_document_bytes() -> int:
    return number("CHANGE_REQUEST_MAX_DOCUMENT_BYTES")


def attestation_issuer() -> str:
    return value("ATTESTATION_ISSUER").rstrip("/")


def attestation_jwks_url() -> str:
    """JWKS of the C5-M1 EBW-Connector of the installation (README 11.2)."""
    return value("ATTESTATION_JWKS_URL") or f"{attestation_issuer()}/jwks"


MODULE_DIR = Path(__file__).parent


def attestation_jwks_file() -> Path | None:
    """Tests only: the JWKS as a file; set means no fetch (README 4, 11.2).

    No default: an installation takes the keys from `ATTESTATION_JWKS_URL`, the JWKS of its own
    EBW-Connector (FRAMEWORK 4.8: keys are never defaulted; OPEN-QUESTIONS 7). A bare name counts
    from the module folder, an absolute path as given.
    """
    path = _path(MODULE_DIR, value("ATTESTATION_JWKS_FILE"))
    return path if path else None


def attestation_client_ids() -> list[str]:
    """Allowed `client_id` values of a verification attestation; empty means no check."""
    return [x.strip() for x in value("ATTESTATION_CLIENT_IDS").split(",") if x.strip()]


def attestation_audience() -> str:
    return value("ATTESTATION_AUDIENCE")


def attestation_max_age_hours() -> int:
    return number("ATTESTATION_MAX_AGE_HOURS")


def attestation_clock_skew_seconds() -> int:
    return number("ATTESTATION_CLOCK_SKEW_SECONDS")


def attestation_jwks_cache_seconds() -> int:
    return number("ATTESTATION_JWKS_CACHE_SECONDS")


def stub_applications_file() -> Path | None:
    """Stand-in for C1-M2: applications in the format of C1-M2 `ApplicationInternal` (11.1).

    A bare name counts from the module folder (README 4 example), an absolute path as given.
    """
    path = _path(MODULE_DIR, value("STUB_APPLICATIONS_FILE"))
    if path is None:
        return None
    path = _fallback(path, ROOT / path.name)
    return path if path.exists() else None


# ------------------------------------------------------------------ installation settings (4.8)
def apply_registration_url() -> None:
    """Bridge README 4's `REGISTRATION_URL` to the neighbour lookup of AGENTS.md 6.

    `portal_common.neighbours` reads `C1_M2_URL`, `MODULE_URLS` and `MODULE_URLS_DEFAULT`. Where the
    installation sets `REGISTRATION_URL` and the scaffold default is empty, that value is the
    neighbour address. An empty `MODULE_URLS_DEFAULT` keeps its meaning: built-in stand-in.
    """
    url = os.environ.get("REGISTRATION_URL")
    if not url or os.environ.get("C1_M2_URL") or not os.environ.get("MODULE_URLS_DEFAULT", "").strip():
        return
    os.environ["C1_M2_URL"] = url


def osp_company_id() -> str:
    return settings.get("ospCompanyId") or ""


def dataspace_name() -> str | None:
    """`dataspace.name` for the responses to people (OP-14); not company data."""
    return (settings.get("dataspace") or {}).get("name")


def seed_company() -> dict | None:
    """Seed data of the OSP company (`ospCompanyFile`); `None` without the setting (README 4).

    The `companyId` in the file must equal `ospCompanyId`, otherwise the start aborts (README 4).
    """
    path = settings.resolve_path(settings.get("ospCompanyFile"))
    if path is None or not path.exists():
        return None
    seed = json.loads(path.read_text(encoding="utf-8"))
    if seed.get("companyId") != osp_company_id():
        raise ValueError(f"{path}: companyId differs from ospCompanyId {osp_company_id()} (README 4)")
    return seed


# ------------------------------------------------------------------------ role catalogue (6.5)
def company_roles_file() -> Path | None:
    path = _path(ROOT, value("COMPANY_ROLES_FILE"))
    return path if path and path.exists() else None


#: Initial values of README 6.5, used while the installation has no `COMPANY_ROLES_FILE`.
INITIAL_ROLES = {
    "ACTIVE_PARTICIPANT": {
        "assignableBy": "COMPANY",
        "descriptions": {"de": "Teilnehmer am Datenaustausch", "en": "Participant in data exchange"},
    },
    "APP_PROVIDER": {
        "assignableBy": "COMPANY",
        "descriptions": {"de": "Anbieter von Apps", "en": "Provider of apps"},
    },
    "SERVICE_PROVIDER": {
        "assignableBy": "COMPANY",
        "descriptions": {"de": "Anbieter von Diensten", "en": "Provider of services"},
    },
    "ONBOARDING_SERVICE_PROVIDER": {
        "assignableBy": "SEED",
        "descriptions": {"de": "Onboarding-Dienstleister", "en": "Onboarding service provider"},
    },
}


def role_catalogue() -> dict[str, dict]:
    """Role catalogue of the installation: `companyRole` -> `{assignableBy, descriptions}`.

    Without `COMPANY_ROLES_FILE` the initial values of README 6.5 apply, so the module runs
    without configuration (FRAMEWORK 4.8, OPEN-QUESTIONS 7).
    """
    path = company_roles_file()
    if path is None:
        return {role: dict(entry) for role, entry in INITIAL_ROLES.items()}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {entry["companyRole"]: entry for entry in document.get("roles", []) if entry.get("companyRole")}


def assignable_by(company_role: str) -> str | None:
    """`COMPANY`, `SEED`, or `None` for a role the catalogue does not know."""
    entry = role_catalogue().get(company_role)
    return entry.get("assignableBy") if entry else None


def roles_assignable_by_company() -> list[str]:
    return [role for role, entry in role_catalogue().items() if entry.get("assignableBy") == "COMPANY"]


def description(company_role: str, lang: str) -> str | None:
    """Description in `lang`, falling back to `en` (README 7.7, 9.4)."""
    descriptions = (role_catalogue().get(company_role) or {}).get("descriptions") or {}
    return descriptions.get(lang) or descriptions.get("en")


def _path(root: Path, value_: str) -> Path | None:
    if not value_:
        return None
    path = Path(value_)
    return path if path.is_absolute() else root / path
