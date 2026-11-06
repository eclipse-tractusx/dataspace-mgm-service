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
"""Public interface of C3-M1 Company Profile: the steps of Process Orchestration (README 8), the
queries of other modules (9) and the read paths.

Names and signatures follow the call convention of AGENTS.md: a step is
`def create_company(input: dict) -> dict` returning `{stepRunId, state, result}`, a query takes its
parameters by their openapi names. No token checks here.

Steps are idempotent (FRAMEWORK 4.4): the business key is looked up first, only what is missing is
created, a repetition returns the stored result and publishes nothing. Every changing operation
writes the audit log of README 5 and FRAMEWORK 4.3 before it publishes.
"""
from __future__ import annotations

import datetime as dt
import json

from portal_common import events, neighbours, standin
from portal_common.problems import Problem
from tools import testdata

from . import attestation, config, store, validation

MODULE = "c3-m1"


def _timestamp(value: str | None) -> dt.datetime | None:
    """Parse a stored ISO timestamp (`Z` or offset) to an instant; `None` when unreadable."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _audit(company_id: str | None, operation: str, input: dict, details: dict | None = None) -> None:
    """Steps carry `processId` and `stepRunId` instead of a `sub` (README 5, 4.3)."""
    store.audit(company_id, None, operation, None,
                (details or {}) | {"processId": input.get("processId"),
                                   "stepRunId": input.get("stepRunId")})


# ------------------------------------------------------------------------ start and seed (README 4)
def reset() -> None:
    """Empty state, then the seed data of the OSP company (README 4). Seed data has no events."""
    try:
        store.reset()
        target = store
    except Problem as error:
        if error.status != 501:
            raise
        # the start survives an unusable database; the seed then lands in memory, calls answer 501
        target = store.backend_memory()
        target.reset()
    attestation.reset()
    seed = config.seed_company()
    if not seed or target.get_company(config.osp_company_id()) is not None:
        return
    address = seed.get("address") or {}
    target.create_company({
        "id": seed["companyId"], "name": seed["name"], "bpn": seed.get("bpn"),
        "street": address.get("street"), "house_number": address.get("houseNumber"),
        "postal_code": address.get("postalCode"), "city": address.get("city"),
        "region": address.get("region"), "country_code": address.get("countryCode"),
        "status": "ACTIVE", "core_data_source": "MANUAL",
    })
    target.set_identifiers(seed["companyId"], seed.get("identifiers") or [])
    for role in seed.get("companyRoles") or []:
        target.add_role(seed["companyId"], role, status="ACTIVE", source_kind="SEED",
                        source_ref="ospCompanyFile")


# ---------------------------------------------------------------------------------- mapping (5)
def get_company(cid: str | None) -> dict:
    row = store.get_company(cid)
    if row is None:
        raise Problem(MODULE, 404, "not-found", retryable=False)
    return row


def _address(row: dict) -> dict:
    return {key: row.get(field) for key, field in
            (("street", "street"), ("houseNumber", "house_number"),
             ("addressAddition", "address_addition"), ("postalCode", "postal_code"),
             ("city", "city"), ("region", "region"), ("countryCode", "country_code"))}


def _identifiers(row: dict) -> list[dict]:
    return [{"type": entry["type"], "value": entry["value"], "source": entry["source"]}
            for entry in store.list_identifiers(row["id"])]


def _active_roles(company: str | None) -> list[str]:
    return sorted(role for role, status in store.list_roles(company).items() if status == "ACTIVE")


def _roles(row: dict) -> list[dict]:
    return [{"companyRole": role, "status": status}
            for role, status in store.list_roles(row["id"]).items()]


def company_view(cid: str | None, *, detail: bool = False) -> dict:
    """`Company` (7.1) and `CompanyDetail` (7.11) in camelCase, with the dataspace name for people."""
    row = get_company(cid)
    view = {"id": row["id"], "name": row["name"], "shortName": row["short_name"],
            "address": _address(row), "identifiers": _identifiers(row),
            "coreDataSource": row["core_data_source"],
            "coreDataVerifiedAt": row["core_data_verified_at"], "bpn": row["bpn"],
            "status": row["status"], "companyRoles": _roles(row),
            "createdAt": row["created_at"], "dataspaceName": config.dataspace_name()}
    if detail:
        view |= {"applicationId": row["application_id"], "verificationRef": row["verification_ref"],
                 "bpnAssignedAt": row["bpn_assigned_at"],
                 "deactivationReason": row["deactivation_reason"],
                 "changedAt": row["changed_at"], "activatedAt": row["activated_at"],
                 "rejectedAt": row["rejected_at"], "deactivatedAt": row["deactivated_at"],
                 "reactivatedAt": row["reactivated_at"],
                 "openChangeRequestId": (store.open_change_request(row["id"]) or {}).get("id")}
    return view


def company_internal(cid: str | None) -> dict:
    """`CompanyInternal` (9.1): address, identifiers, source and active roles for other modules."""
    row = get_company(cid)
    return {"id": row["id"], "name": row["name"], "shortName": row["short_name"],
            "address": {key: row.get(field) for key, field in
                        (("street", "street"), ("houseNumber", "house_number"),
                         ("postalCode", "postal_code"), ("city", "city"),
                         ("region", "region"), ("countryCode", "country_code"))},
            "identifiers": _identifiers(row), "coreDataSource": row["core_data_source"],
            "status": row["status"], "bpn": row["bpn"],
            "companyRoles": [role for role, status in store.list_roles(row["id"]).items()
                             if status == "ACTIVE"],
            "deactivationReason": row["deactivation_reason"], "createdAt": row["created_at"],
            "activatedAt": row["activated_at"], "deactivatedAt": row["deactivated_at"]}


def role_view(cid: str | None) -> dict:
    """`Company` of the paths for people (7.1, 7.7): roles with status, so a role can read REQUESTED."""
    row = get_company(cid)
    view = company_view(cid)
    view["companyRoles"] = [{"companyRole": role, "status": status}
                            for role, status in store.list_roles(row["id"]).items()]
    return view


# ----------------------------------------------------------------------------------- steps (8.1)
def _stub_applications() -> dict[str, dict]:
    """Built-in stand-in for C1-M2 (11.1): `STUB_APPLICATIONS_FILE` in `ApplicationInternal` form."""
    path = config.stub_applications_file()
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("applications") if isinstance(document, dict) else document
    return {entry["id"]: entry for entry in entries or []}


def _application(application_id: str | None) -> dict:
    config.apply_registration_url()
    """The application at C1-M2 (11.1); a failed call is an error, not "not found" (skill 5)."""
    if neighbours.is_standin("c1-m2"):
        application = _stub_applications().get(application_id or "")
        if application is None:
            raise Problem(MODULE, 404, "not-found", detail="application unknown", retryable=False)
        return application
    try:
        application = neighbours.query(MODULE, "c1-m2", "get_application_internal",
                                       applicationId=application_id)
    except Problem:
        raise
    if not application:
        raise Problem(MODULE, 404, "not-found", detail="application unknown", retryable=False)
    return application


def create_company(input: dict) -> dict:
    """8.1: create the company `REQUESTED` from a submitted application of kind ONBOARDING/TRANSFER."""
    cid, application_id = input.get("companyId"), input.get("applicationId")
    existing = store.get_company(cid)
    if existing is not None:
        if existing["application_id"] == application_id:
            return standin.step_reply(input, {"companyId": cid, "status": existing["status"],
                                              "bpn": existing["bpn"],
                                              "coreDataSource": existing["core_data_source"]})
        raise Problem(MODULE, 409, "conflict", detail="company belongs to another application",
                      retryable=False)

    application = _application(application_id)
    if application.get("companyId") != cid:
        raise Problem(MODULE, 409, "conflict", detail="application has another companyId",
                      retryable=False)
    if application.get("kind") == "REACTIVATION":
        raise Problem(MODULE, 409, "conflict", detail="reactivation uses reactivate-company",
                      retryable=False)
    if application.get("status") not in ("SUBMITTED", "APPROVED"):
        raise Problem(MODULE, 409, "invalid-state",
                      detail=f"application {application.get('status')}", retryable=False)

    data = application.get("companyData") or {}
    source_address = data.get("address") or {}
    verification = application.get("verification")
    row = {"name": data.get("legalName"), "short_name": data.get("shortName"),
           "street": source_address.get("streetName"), "house_number": source_address.get("streetNumber"),
           "postal_code": source_address.get("postalCode"), "city": source_address.get("city"),
           "region": source_address.get("region"), "country_code": source_address.get("countryCode")}
    identifiers = [{"type": entry["type"], "value": entry["value"],
                    "source": "BUSINESS_WALLET" if entry.get("source") == "ATTESTATION" else "DECLARED"}
                   for entry in data.get("identifiers") or []]
    roles = [role for role in application.get("companyRoles") or []
             if config.assignable_by(role) == "COMPANY"]

    errors = validation.validate_company(row)
    errors += validation.validate_identifiers(identifiers, row["country_code"])
    for role in application.get("companyRoles") or []:
        errors += validation.validate_company_role(role, config.role_catalogue())
    if verification == "EBW" and not any(entry["type"] == "EBWOID" for entry in identifiers):
        errors.append({"field": "identifiers", "reason": "EBWOID required with a verification"})
    if errors:
        raise Problem(MODULE, 400, "validation", errors=errors, retryable=False)

    attestation = application.get("attestation") or {}
    with store.lock(cid):
        store.create_company(row | {
            "id": cid, "status": "REQUESTED",
            "core_data_source": "EBW" if verification == "EBW" else "MANUAL",
            "core_data_verified_at": attestation.get("verifiedAt") if verification == "EBW" else None,
            "verification_ref": attestation.get("attestationId") if verification == "EBW" else None,
            "application_id": application_id,
        })
        store.set_identifiers(cid, identifiers)
        for role in roles:
            store.add_role(cid, role, status="REQUESTED", source_kind="APPLICATION",
                           source_ref=application_id)
        _audit(cid, "stepCreateCompany", input, {"applicationId": application_id})
        created = get_company(cid)
        events.publish(MODULE, "CompanyCreated", {"companyId": cid, "applicationId": application_id,
                                                  "coreDataSource": created["core_data_source"]})
    return standin.step_reply(input, {"companyId": cid, "status": created["status"],
                                      "bpn": created["bpn"],
                                      "coreDataSource": created["core_data_source"]})


# ----------------------------------------------------------------------------------- steps (8.2)
def assign_identifier(input: dict) -> dict:
    """8.2: take over the BPN from `CompanyRegisteredAtCsp`."""
    cid, raw = input.get("companyId"), input.get("bpn") or ""
    with store.lock(cid):
        row = get_company(cid)
        errors = validation.validate_bpn(raw)
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors, retryable=False)
        bpn = raw.strip().upper()
        if row["bpn"]:
            if row["bpn"] == bpn:
                return standin.step_reply(input, {"companyId": cid, "status": row["status"], "bpn": bpn})
            raise Problem(MODULE, 409, "bpn-mismatch", detail=f"company has {row['bpn']}",
                          retryable=False)
        if row["status"] != "REQUESTED":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"], retryable=False)
        taken = next((other for other in store.find_companies(bpn=bpn, size=5)[0]
                      if other["id"] != cid and other["status"] != "REJECTED"), None)
        if taken is not None:
            raise Problem(MODULE, 409, "bpn-taken", detail=taken["id"], retryable=False)
        store.update_company(cid, bpn=bpn, bpn_assigned_at=_now())
        _audit(cid, "stepAssignIdentifier", input, {"bpn": bpn})
        events.publish(MODULE, "CompanyIdentifierAssigned", {"companyId": cid, "bpn": bpn})
    return standin.step_reply(input, {"companyId": cid, "status": row["status"], "bpn": bpn})


# ----------------------------------------------------------------------------------- steps (8.3)
def _terms_of_roles() -> dict[str, set[str]]:
    config.apply_registration_url()
    """agreementKey -> roles it belongs to, from the terms of C1-M2 (11.1).

    Without an address for C1-M2 the built-in stand-in answers with the initial values of 14.3.
    """
    if neighbours.is_standin("c1-m2"):
        agreements = testdata.agreements()
    else:
        agreements = neighbours.query(MODULE, "c1-m2", "list_agreements_internal") or []
    terms: dict[str, set[str]] = {}
    for agreement in agreements:
        if agreement.get("scope") != "COMPANY_ROLE":
            continue
        for role in agreement.get("companyRoles") or []:
            terms.setdefault(agreement["agreementKey"], set()).add(role)
    return terms


def activate_company(input: dict) -> dict:
    """8.3: activate, taking over the consents of the application."""
    cid, application_id = input.get("companyId"), input.get("applicationId")
    with store.lock(cid):
        row = get_company(cid)
        if row["status"] == "ACTIVE":
            return standin.step_reply(input, {"companyId": cid, "status": row["status"],
                                              "bpn": row["bpn"],
                                              "companyRoles": _active_roles(cid),
                                              "pendingCompanyRoles": []})
        if row["status"] in ("REJECTED", "INACTIVE"):
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"], retryable=False)
        if not row["bpn"]:
            raise Problem(MODULE, 409, "identifier-missing", retryable=False)
        if application_id != row["application_id"]:
            raise Problem(MODULE, 409, "conflict", detail="application does not match",
                          retryable=False)

        application = _application(application_id)
        terms = _terms_of_roles()
        given = {consent.get("agreementKey"): consent for consent in application.get("consents") or []}
        active, pending = [], []
        for role, status in store.list_roles(cid).items():
            if status != "REQUESTED":
                continue
            needed = {key for key, roles in terms.items() if role in roles}
            if needed <= set(given):
                active.append(role)
            else:
                pending.append(role)
        if not active:
            raise Problem(MODULE, 409, "roles-without-consent", missing=sorted(pending),
                          retryable=False)

        applicant = (application.get("applicant") or {}).get("sub")
        for role in active:
            store.add_role(cid, role, status="ACTIVE", source_kind="APPLICATION",
                           source_ref=application_id)
            for key in (key for key, roles in terms.items() if role in roles):
                store.set_consent(cid, key, version=given[key].get("version"), status="ACTIVE",
                                  source_kind="APPLICATION", source_ref=application_id,
                                  consented_by=applicant, consented_at=given[key].get("givenAt"))
        fields = {"status": "ACTIVE", "activated_at": _now()}
        if row["core_data_source"] == "MANUAL" and not row["core_data_verified_at"]:
            fields["core_data_verified_at"] = _now()
        store.update_company(cid, **fields)
        _audit(cid, "stepActivateCompany", input, {"applicationId": application_id,
                                                   "companyRoles": sorted(active)})
        events.publish(MODULE, "CompanyActivated", {"companyId": cid, "bpn": row["bpn"],
                                                    "companyRoles": sorted(active)})
    return standin.step_reply(input, {"companyId": cid, "status": "ACTIVE", "bpn": row["bpn"],
                                      "companyRoles": sorted(active), "pendingCompanyRoles": pending})


# ----------------------------------------------------------------------------------- steps (8.4)
def reject_company(input: dict) -> dict:
    """8.4: `REJECTED`, final; an assigned BPN becomes free."""
    cid = input.get("companyId")
    with store.lock(cid):
        row = get_company(cid)
        if row["status"] == "REJECTED":
            return standin.step_reply(input, {"companyId": cid, "status": row["status"]})
        if row["status"] in ("ACTIVE", "INACTIVE"):
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"], retryable=False)
        store.update_company(cid, status="REJECTED", rejected_at=_now())
        _audit(cid, "stepRejectCompany", input)
        events.publish(MODULE, "CompanyRejected", {"companyId": cid})
    return standin.step_reply(input, {"companyId": cid, "status": "REJECTED"})


# ------------------------------------------------------------------------ change by people (7.2)
CORE_TEXT_FIELDS = ("name", "street", "house_number", "address_addition", "postal_code", "city",
                    "region", "country_code")
CAMEL = {snake: camel for camel, snake in validation.ALIASES.items()}


def _changed_fields(row: dict, body: dict, identifiers: list[dict] | None) -> list[str]:
    """Names of the fields the body really changes, camelCase, for the event (README 7.2, 7.12)."""
    changed = []
    for key, value in body.items():
        field = validation.field_name(key)
        if field in CORE_TEXT_FIELDS or field == "short_name":
            before, after = row.get(field), value
            if (before or "") != (after or "") and not (
                    before and after and validation.same_value(before, after)):
                changed.append(CAMEL.get(field, field))
    if identifiers is not None:
        before = {(entry["type"], entry["value_normalized"]) for entry in store.list_identifiers(row["id"])}
        after = {(entry["type"], validation.value_normalized(entry["value"])) for entry in identifiers}
        if before != after:
            changed.append("identifiers")
    return changed


def _validate_merge(row: dict, body: dict) -> dict:
    """The row after the body, flat, so the merged state is validated, not only the patch."""
    merged = {field: row.get(field) for field in row}
    merged.update(validation.flat_fields(body))
    return merged


def _identifiers_from(body: dict) -> list[dict] | None:
    if "identifiers" not in body:
        return None
    return [{"type": entry.get("type"), "value": entry.get("value"),
             "source": entry.get("source") or "DECLARED"} for entry in body.get("identifiers") or []]


def update_company(companyId: str, body: dict, sub: str | None = None) -> dict:
    """7.2: the Company Admin changes the short name."""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        locked = [key for key in body if validation.field_name(key) not in ("short_name",)]
        if locked:
            raise Problem(MODULE, 409, "field-locked", fields=locked)
        errors = validation.validate_company(body, partial=True)
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)
        changed = _changed_fields(row, body, None)
        if not changed:
            return company_view(companyId)
        before = {"short_name": row["short_name"]}
        store.update_company(companyId, short_name=validation.flat_fields(body).get("short_name"))
        store.audit(companyId, sub, "updateCompany", None,
                    {"changedFields": changed, "old": before,
                     "new": {key: body.get(key) for key in body}})
        events.publish(MODULE, "CompanyDataChanged",
                       {"companyId": companyId, "changedFields": changed, "coreDataChanged": False,
                        "coreDataSource": row["core_data_source"]})
    return company_view(companyId)


# ----------------------------------------------------------------- correction by OSP staff (7.12)
OSP_LOCKED_FIELDS = {"bpn", "status", "coreDataSource", "applicationId", "verificationRef",
                     "deactivationReason", "createdAt", "changedAt"}


def correct_company(companyId: str, body: dict, sub: str | None = None) -> dict:
    """7.12: correction by OSP staff, always with a justification."""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] in ("REJECTED", "INACTIVE"):
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        errors = validation.validate_reason(body.get("reason"))
        identifiers = _identifiers_from(body)
        fields = {key: value for key, value in validation.flat_fields(body).items()
                  if key not in ("reason", "identifiers")}

        locked = [key for key in fields if key not in CORE_TEXT_FIELDS + ("short_name",)]
        if "country_code" in fields and (row["status"] != "REQUESTED" or row["bpn"]):
            locked.append("countryCode")
        if locked:
            raise Problem(MODULE, 409, "field-locked", fields=locked)

        if identifiers is not None:
            wallet = [{"type": entry["type"], "value": entry["value"], "source": entry["source"]}
                      for entry in store.list_identifiers(companyId)
                      if entry["source"] == "BUSINESS_WALLET"]
            errors += validation.validate_identifiers(list(identifiers) + wallet, row["country_code"])
            errors += _wallet_identifier_conflict(row, identifiers)
        errors += validation.validate_company(_validate_merge(row, fields), partial=False)
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)

        changed = _changed_fields(row, fields, identifiers)
        if not changed:
            return company_view(companyId, detail=True)

        core_changed = any(validation.field_name(key) in CORE_TEXT_FIELDS for key in fields)
        if identifiers is not None and _identifier_core_changed(row, identifiers):
            core_changed = True
        updates = validation.flat_fields(fields)
        if core_changed:
            updates["core_data_verified_at"] = _now()
            if row["core_data_source"] == "EBW":
                updates["core_data_source"] = "MANUAL"
                updates["verification_ref"] = None
        store.update_company(companyId, **updates)
        if identifiers is not None:
            store.set_identifiers(companyId, identifiers)
        store.audit(companyId, sub, "correctCompany", None,
                    {"changedFields": changed, "reason": body.get("reason"),
                     "old": {field: row.get(field) for field in updates},
                     "new": fields})
        events.publish(MODULE, "CompanyDataChanged",
                       {"companyId": companyId, "changedFields": changed,
                        "coreDataChanged": core_changed,
                        "coreDataSource": updates.get("core_data_source", row["core_data_source"])})
    return company_view(companyId, detail=True)


# ------------------------------------------------------------------------------ company roles (7.7 - 7.9)
def _terms() -> list[dict]:
    """Active terms of C1-M2 with scope COMPANY_ROLE (11.1); unreachable stays 502."""
    config.apply_registration_url()
    if neighbours.is_standin("c1-m2"):
        agreements = testdata.agreements()
    else:
        agreements = neighbours.query(MODULE, "c1-m2", "list_agreements_internal") or []
    return [agreement for agreement in agreements if agreement.get("scope") == "COMPANY_ROLE"]


def _role_state(company: str, lang: str) -> list[dict]:
    """`CompanyRoleState` of 7.7: catalogue roles plus the roles the company has or had."""
    terms = _terms()
    roles: dict[str, set[str]] = {}
    for role in config.roles_assignable_by_company():
        roles.setdefault(role, set())
    for role in store.list_roles(company):
        roles.setdefault(role, set())
    states = []
    for role in sorted(roles):
        entry = config.role_catalogue().get(role) or {}
        assigned = store.role_status(company, role)
        own = {consent["agreement_key"]: consent for consent in store.list_consents(company)}
        states.append({
            "companyRole": role, "assignableBy": entry.get("assignableBy"),
            "status": "NONE" if assigned == "NONE" else assigned,
            "description": config.description(role, lang) or "",
            "agreements": [{"agreementKey": term["agreementKey"], "version": term["version"],
                            "name": (term.get("title") or {}).get(lang) or (term.get("title") or {}).get("en"),
                            "names": term.get("title") or {},
                            "documentUrl": (term.get("documentUrls") or {}).get(lang)
                            or (term.get("documentUrls") or {}).get("en"),
                            "consentStatus": (own.get(term["agreementKey"]) or {}).get("status"),
                            "consentedVersion": (own.get(term["agreementKey"]) or {}).get("agreement_version"),
                            "consentedAt": (own.get(term["agreementKey"]) or {}).get("consented_at")}
                           for term in terms if role in (term.get("companyRoles") or [])],
        })
    return states


def list_company_roles(companyId: str, lang: str | None = None) -> list[dict]:
    """7.7"""
    get_company(companyId)
    return _role_state(companyId, lang or "en")


def _terms_of(role: str, terms: list[dict]) -> dict[str, dict]:
    """agreementKey -> active term of the role."""
    return {term["agreementKey"]: term for term in terms
            if role in (term.get("companyRoles") or [])}


def add_company_role(companyId: str, body: dict, sub: str | None = None,
                     lang: str | None = None) -> list[dict]:
    """7.8"""
    role = body.get("companyRole") or ""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        errors = validation.validate_company_role(role, config.role_catalogue())
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)
        if config.assignable_by(role) != "COMPANY":
            raise Problem(MODULE, 409, "role-not-assignable")
        if store.role_status(companyId, role) == "ACTIVE":
            return _role_state(companyId, lang or "en")

        terms = _terms_of(role, _terms())
        given = {consent.get("agreementKey"): consent for consent in body.get("consents") or []}
        missing = sorted(key for key in terms if (given.get(key) or {}).get("version") != terms[key]["version"])
        if missing:
            raise Problem(MODULE, 400, "consent-missing", missing=missing)
        foreign = sorted(set(given) - set(terms))
        if foreign:
            raise Problem(MODULE, 400, "validation",
                          errors=[{"field": "consents", "reason": f"not a term of {role}: {', '.join(foreign)}"}])

        now = _now()
        for key in terms:
            store.set_consent(companyId, key, version=terms[key]["version"], status="ACTIVE",
                              source_kind="COMPANY", consented_by=sub, consented_at=now)
        store.add_role(companyId, role, status="ACTIVE", source_kind="COMPANY", source_ref=sub)
        active = [name for name, status in store.list_roles(companyId).items() if status == "ACTIVE"]
        store.audit(companyId, sub, "addCompanyRole", role, {"companyRole": role})
        events.publish(MODULE, "CompanyRolesChanged", {"companyId": companyId, "companyRoles": active})
    return _role_state(companyId, lang or "en")


def remove_company_role(companyId: str, companyRole: str, sub: str | None = None,
                        lang: str | None = None) -> list[dict]:
    """7.9"""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        if companyRole not in config.role_catalogue():
            raise Problem(MODULE, 404, "not-found")
        if config.assignable_by(companyRole) != "COMPANY":
            raise Problem(MODULE, 409, "role-not-assignable")
        if store.role_status(companyId, companyRole) != "ACTIVE":
            return _role_state(companyId, lang or "en")
        remaining = [role for role, status in store.list_roles(companyId).items()
                     if status == "ACTIVE" and role != companyRole and config.assignable_by(role) == "COMPANY"]
        if not remaining:
            raise Problem(MODULE, 409, "last-role")

        store.remove_role(companyId, companyRole)
        for term in _terms_of(companyRole, _terms()).values():
            others = [role for role, status in store.list_roles(companyId).items()
                      if status == "ACTIVE" and companyRole != role
                      and term["agreementKey"] in [t["agreementKey"] for t in _terms_of(role, _terms()).values()]]
            if not others:
                store.set_consent(companyId, term["agreementKey"], status="INACTIVE",
                                  source_kind="COMPANY", source_ref=sub)
        active = [name for name, status in store.list_roles(companyId).items() if status == "ACTIVE"]
        store.audit(companyId, sub, "removeCompanyRole", companyRole, {"companyRole": companyRole})
        events.publish(MODULE, "CompanyRolesChanged", {"companyId": companyId, "companyRoles": active})
    return _role_state(companyId, lang or "en")


# ---------------------------------------------------------------------- search for OSP (7.10)
def _summary(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "status": row["status"], "bpn": row["bpn"],
            "coreDataSource": row["core_data_source"], "countryCode": row["country_code"],
            "companyRoles": [role for role, status in store.list_roles(row["id"]).items()
                             if status == "ACTIVE"],
            "createdAt": row["created_at"]}


def list_companies(*, status: list[str] | str | None = None, name: str | None = None,
                   bpn: str | None = None, hasBpn: bool | str | None = None,
                   companyRole: str | None = None, coreDataSource: str | None = None,
                   page: int | str = 0, size: int | str = 20) -> dict:
    """7.10: filters, newest first, paged; `companyRole` matches active roles only."""
    has_bpn = None if hasBpn in (None, "") else str(hasBpn).lower() in ("1", "true", "yes")
    try:
        items, total = store.find_companies(
            status=status, name=name, bpn=bpn, has_bpn=has_bpn, company_role=companyRole,
            core_data_source=coreDataSource, page=int(page or 0), size=int(size or 20))
    except ValueError as error:
        raise Problem(MODULE, 400, "validation", errors=[{"field": "filter", "reason": str(error)}])
    return {"items": [_summary(row) for row in items], "page": int(page or 0),
            "size": int(size or 20), "total": total}


# ------------------------------------------------------------ change requests (7.4 - 7.6, 7.14 - 7.18)
def _document_info(row: dict) -> dict:
    return {"id": row["id"], "fileName": row["file_name"], "mediaType": row["media_type"],
            "sizeBytes": row["size_bytes"]}


def _change_request_view(row: dict, *, osp: bool = False, company: dict | None = None) -> dict:
    """`ChangeRequest` (7.5: without `decidedBy`, without document content)."""
    view = {"id": row["id"], "companyId": row["company_id"], "status": row["status"],
            "changes": row["changes"], "comment": row["comment"],
            "documents": [_document_info(document)
                          for document in store.list_documents(row["id"])],
            "requestedBy": row["requested_by"], "createdAt": row["created_at"],
            "closedAt": row["closed_at"], "decisionReason": row["decision_reason"]}
    if osp:
        view |= {"companyName": (company or {}).get("name"), "decidedBy": row["decided_by"]}
    return view


CORE_IDENTIFIERS = ("EUID", "EBWOID")


def _differs_field(row: dict, key: str, value) -> bool:
    """`True` if this part of a request differs from the current state (7.4 point 5/6)."""
    if key == "address":
        return any(not validation.same_value(row.get(field), entry)
                   for field, entry in validation.flat_fields({"address": value}).items())
    return not validation.same_value(row.get(validation.field_name(key)), value)


def _differs_identifiers(row: dict, identifiers: list[dict]) -> bool:
    """Compare with the declared identifiers only; wallet identifiers are not part of a request."""
    before = {(entry["type"], entry["value_normalized"])
              for entry in store.list_identifiers(row["id"])
              if entry["source"] != "BUSINESS_WALLET"}
    after = {(entry["type"], validation.value_normalized(entry["value"])) for entry in identifiers}
    return before != after


def _changes_differs(row: dict, changes: dict) -> bool:
    """`True` if any part of the request differs from the current company (7.4 point 6)."""
    for key, value in changes.items():
        if key == "identifiers":
            if _differs_identifiers(row, value):
                return True
        elif _differs_field(row, key, value):
            return True
    return False


def _wallet_identifier_conflict(row: dict, identifiers: list[dict]) -> list[dict]:
    """Identifiers of the list whose stored source is `BUSINESS_WALLET` (400, 7.4 point 4, 7.12 point 3)."""
    stored = {entry["type"] for entry in store.list_identifiers(row["id"])
              if entry["source"] == "BUSINESS_WALLET"}
    return [{"field": f"identifiers.{entry.get('type')}", "reason": "source BUSINESS_WALLET"}
            for entry in identifiers if entry.get("type") in stored]


def _identifier_core_changed(row: dict, identifiers: list[dict]) -> bool:
    """A changed, added or dropped declared EUID/EBWOID is a change of core data (6.3).

    A wallet identifier that stays outside the request list is not a change.
    """
    stored = {entry["type"]: entry["value"] for entry in store.list_identifiers(row["id"])
              if entry["type"] in CORE_IDENTIFIERS and entry["source"] != "BUSINESS_WALLET"}
    now = {entry["type"]: entry["value"] for entry in identifiers
           if entry.get("type") in CORE_IDENTIFIERS}
    if set(stored) != set(now):
        return True
    return any(not validation.same_value(stored[kind], value) for kind, value in now.items())


def create_change_request(companyId: str, data: dict,
                          documents: list[tuple[str, bytes, str | None]],
                          sub: str | None = None) -> dict:
    """7.4: a change request with supporting documents."""
    if not config.change_requests_enabled():
        raise Problem(MODULE, 409, "change-requests-disabled")
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        if store.open_change_request(companyId):
            raise Problem(MODULE, 409, "change-request-open")

        changes = {key: value for key, value in data.items() if key in ("name", "address", "identifiers")}
        identifiers = changes.get("identifiers")
        wallet = [{"type": entry["type"], "value": entry["value"], "source": entry["source"]}
                  for entry in store.list_identifiers(companyId) if entry["source"] == "BUSINESS_WALLET"]
        errors = validation.validate_change_request(data, row["country_code"])
        if identifiers is not None:
            if not identifiers and wallet:
                # "afterwards at least one identifier" counts the wallet identifiers that stay
                errors = [error for error in errors
                          if not (error["field"] == "identifiers" and error["reason"] == "missing")]
            errors += _wallet_identifier_conflict(row, identifiers)
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)
        core_changed = any(_differs_field(row, key, value)
                           for key, value in changes.items() if key != "identifiers")
        if identifiers is not None and _identifier_core_changed(row, identifiers):
            core_changed = True
        if core_changed and row["core_data_source"] == "EBW":
            raise Problem(MODULE, 409, "attestation-required")
        if not _changes_differs(row, changes):
            raise Problem(MODULE, 400, "validation",
                          errors=[{"field": "changes", "reason": "no change"}])

        errors = []
        if not 1 <= len(documents) <= config.change_request_max_documents():
            errors.append({"field": "documents", "reason": "1 to %d documents"
                                                          % config.change_request_max_documents()})
        for file_name, content, stated in documents:
            errors += validation.validate_document(file_name, content, stated_media_type=stated,
                                                   max_bytes=config.change_request_max_document_bytes())
        if errors:
            raise Problem(MODULE, 400, "document-invalid", errors=errors)

        created = store.create_change_request({
            "company_id": companyId, "changes": changes, "comment": data.get("comment"),
            "requested_by": sub, "status": "OPEN"})
        for file_name, content, stated in documents:
            store.add_document(created["id"], file_name=file_name,
                               media_type=validation.detect_media_type(content) or stated or "",
                               content=content)
        store.audit(companyId, sub, "createChangeRequest", created["id"],
                    {"changedFields": sorted(changes)})
        events.publish(MODULE, "CompanyChangeRequestSubmitted",
                       {"companyId": companyId, "changeRequestId": created["id"]})
    return _change_request_view(created)


def list_own_change_requests(companyId: str, page: int = 0, size: int = 20) -> dict:
    """7.5: own change requests, newest first, without `decidedBy`."""
    get_company(companyId)
    items, total = store.list_change_requests(company_id=companyId, page=page, size=size,
                                              newest_first=True)
    return {"items": [_change_request_view(item) for item in items], "page": page, "size": size,
            "total": total}


def _own_change_request(companyId: str, changeRequestId: str) -> dict:
    row = store.get_change_request(changeRequestId)
    if row is None or row["company_id"] != companyId:
        raise Problem(MODULE, 404, "not-found")
    return row


def withdraw_change_request(companyId: str, changeRequestId: str, sub: str | None = None) -> dict:
    """7.6"""
    with store.lock(companyId):
        row = _own_change_request(companyId, changeRequestId)
        if row["status"] == "WITHDRAWN":
            return _change_request_view(row)
        if row["status"] != "OPEN":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        closed = store.withdraw_change_request(changeRequestId)
        store.audit(companyId, sub, "withdrawChangeRequest", changeRequestId)
        events.publish(MODULE, "CompanyChangeRequestClosed",
                       {"companyId": companyId, "changeRequestId": changeRequestId,
                        "outcome": "WITHDRAWN"})
    return _change_request_view(closed)


# ----------------------------------------------------------------------- review by OSP staff (7.14 - 7.18)
def _reviewed(changeRequestId: str) -> dict:
    row = store.get_change_request(changeRequestId)
    if row is None:
        raise Problem(MODULE, 404, "not-found")
    return row


def list_change_requests(*, status: list[str] | str | None = None,
                         companyId: str | None = None, page: int | str = 0,
                         size: int | str = 20) -> dict:
    """7.14: all change requests, oldest first."""
    try:
        items, total = store.list_change_requests(status=status, company_id=companyId,
                                                  page=int(page or 0), size=int(size or 20))
    except ValueError as error:
        raise Problem(MODULE, 400, "validation", errors=[{"field": "filter", "reason": str(error)}])
    return {"items": [_change_request_view(item, osp=True,
                                           company=store.get_company(item["company_id"]))
                      for item in items],
            "page": int(page or 0), "size": int(size or 20), "total": total}


def get_change_request(changeRequestId: str) -> dict:
    """7.15: the request with the current state of the company."""
    row = _reviewed(changeRequestId)
    company = store.get_company(row["company_id"]) or {}
    view = _change_request_view(row, osp=True, company=company)
    view["company"] = {"id": company.get("id"), "name": company.get("name"),
                       "address": _address(company), "identifiers": _identifiers(company),
                       "coreDataSource": company.get("core_data_source"),
                       "status": company.get("status")}
    return view


def get_change_request_document(changeRequestId: str, documentId: str,
                                sub: str | None = None) -> dict:
    """7.16: content, media type and file name; the read is audited."""
    request = _reviewed(changeRequestId)
    document = store.get_document(documentId)
    if document is None or document["change_request_id"] != changeRequestId:
        raise Problem(MODULE, 404, "not-found")
    store.audit(request["company_id"], sub, "getChangeRequestDocument", documentId)
    return {"content": document["content"], "media_type": document["media_type"],
            "file_name": document["file_name"]}


def _apply_changes(companyId: str, row: dict, changes: dict) -> tuple[list[str], bool]:
    """Apply the request and return the changed field names and whether core data changed (7.17)."""
    fields = {key: value for key, value in changes.items() if key in ("name", "address")}
    identifiers = changes.get("identifiers")
    stored = store.list_identifiers(companyId)
    wallet = [{"type": entry["type"], "value": entry["value"], "source": entry["source"]}
              for entry in stored if entry["source"] == "BUSINESS_WALLET"]
    merged_identifiers = (list(identifiers) + wallet) if identifiers is not None else \
        [{"type": entry["type"], "value": entry["value"], "source": entry["source"]} for entry in stored]
    errors = validation.validate_company(_validate_merge(row, fields), partial=False)
    errors += validation.validate_identifiers(merged_identifiers, row["country_code"])
    if identifiers is not None:
        errors += _wallet_identifier_conflict(row, identifiers)
    if errors:
        raise Problem(MODULE, 400, "validation", errors=errors)

    core_changed = any(_differs_field(row, key, value) for key, value in fields.items())
    if identifiers is not None and _identifier_core_changed(row, identifiers):
        core_changed = True
    if core_changed and row["core_data_source"] == "EBW":
        raise Problem(MODULE, 409, "attestation-required")
    changed = _changed_fields(row, fields, identifiers)
    updates = validation.flat_fields(fields)
    if core_changed:
        updates |= {"core_data_source": "MANUAL", "core_data_verified_at": _now()}
    if updates:
        store.update_company(companyId, **updates)
    if identifiers is not None:
        store.set_identifiers(companyId, merged_identifiers)
    return changed, core_changed


def approve_change_request(changeRequestId: str, body: dict | None = None,
                           sub: str | None = None) -> dict:
    """7.17"""
    with store.lock((store.get_change_request(changeRequestId) or {}).get("company_id")):
        row = _reviewed(changeRequestId)
        if row["status"] == "APPROVED":
            return _change_request_view(row, osp=True)
        if row["status"] != "OPEN":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        if row["requested_by"] and row["requested_by"] == sub:
            raise Problem(MODULE, 409, "same-person")
        company = get_company(row["company_id"])
        if company["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=company["status"])

        changed, core_changed = _apply_changes(row["company_id"], company, row["changes"])
        decided = store.decide_change_request(changeRequestId, "APPROVED", decided_by=sub,
                                              decision_reason=None)
        store.audit(row["company_id"], sub, "approveChangeRequest", changeRequestId,
                    {"changedFields": changed, "comment": (body or {}).get("comment")})
        if changed:
            events.publish(MODULE, "CompanyDataChanged",
                           {"companyId": row["company_id"], "changedFields": changed,
                            "coreDataChanged": core_changed,
                            "coreDataSource": "MANUAL" if core_changed
                            else company["core_data_source"]})
        events.publish(MODULE, "CompanyChangeRequestClosed",
                       {"companyId": row["company_id"], "changeRequestId": changeRequestId,
                        "outcome": "APPROVED"})
    return _change_request_view(decided, osp=True)


def decline_change_request(changeRequestId: str, body: dict | None = None,
                           sub: str | None = None) -> dict:
    """7.18"""
    with store.lock((store.get_change_request(changeRequestId) or {}).get("company_id")):
        row = _reviewed(changeRequestId)
        reason = (body or {}).get("reason")
        if row["status"] == "DECLINED":
            return _change_request_view(row, osp=True)
        if row["status"] != "OPEN":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        errors = validation.validate_decision_reason(reason)
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)
        decided = store.decide_change_request(changeRequestId, "DECLINED", decided_by=sub,
                                              decision_reason=reason)
        store.audit(row["company_id"], sub, "declineChangeRequest", changeRequestId,
                    {"reason": reason})
        events.publish(MODULE, "CompanyChangeRequestClosed",
                       {"companyId": row["company_id"], "changeRequestId": changeRequestId,
                        "outcome": "DECLINED"})
    return _change_request_view(decided, osp=True)


# ----------------------------------------------------- change with an attestation (7.3, 6.3, 6.7)
def _attested_values(row: dict, claims: dict) -> tuple[dict, dict[str, dict]]:
    """Name, address and identifiers from the claims (6.3); returns the fields and the identifiers."""
    company = claims.get("company") or {}
    fields = {"name": company.get("legal_name")}
    stored = {entry["type"]: entry for entry in store.list_identifiers(row["id"])}
    identifiers = [{"type": kind, "value": entry["value"], "source": entry["source"]}
                   for kind, entry in stored.items()]
    for entry in identifiers:
        if entry["type"] == "EBWOID":
            if not validation.same_value(entry["value"], company.get("ebwoid")):
                entry["value"] = company.get("ebwoid")
            entry["source"] = "BUSINESS_WALLET"
    if not any(entry["type"] == "EBWOID" for entry in identifiers):
        identifiers.append({"type": "EBWOID", "value": company.get("ebwoid"),
                            "source": "BUSINESS_WALLET"})
    if company.get("euid"):
        identifiers = [entry for entry in identifiers if entry["type"] != "EUID"]
        identifiers.append({"type": "EUID", "value": company["euid"], "source": "BUSINESS_WALLET"})

    address = company.get("address")
    if isinstance(address, dict):
        same_street = validation.same_value(
            " ".join(filter(None, (row["street"], row["house_number"]))), address.get("street_address"))
        same_city = (validation.same_value(row["postal_code"], address.get("postal_code"))
                     and validation.same_value(row["city"], address.get("locality")))
        if not (same_street and same_city):
            fields |= {"street": address.get("street_address"), "house_number": None,
                       "address_addition": None, "region": None,
                       "postal_code": address.get("postal_code"), "city": address.get("locality")}
    return fields, {entry["type"]: entry for entry in identifiers}


def update_company_from_attestation(companyId: str, body: dict, sub: str | None = None) -> dict:
    """7.3: core data from a new verification attestation, immediately and without OSP staff."""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        claims = attestation.verify(body.get("attestation") or "")
        claims["client_id"] = claims.get("client_id")

        if store.is_used(claims["jti"]):
            raise Problem(MODULE, 409, "attestation-used")
        if claims.get("representation", {}).get("confirmed") is not True:
            raise Problem(MODULE, 409, "representation-not-confirmed")
        company = claims.get("company") or {}
        stored = {entry["type"]: entry for entry in store.list_identifiers(companyId)}
        mismatched = []
        if not validation.same_value((stored.get("EBWOID") or {}).get("value"), company.get("ebwoid")):
            mismatched.append("EBWOID")
        if (row["country_code"] or "") != (company.get("country") or ""):
            mismatched.append("countryCode")
        if mismatched:
            raise Problem(MODULE, 409, "company-mismatch", fields=mismatched)
        verified_at = claims["_verified_at"].isoformat()
        stored_verified_at = _timestamp(row["core_data_verified_at"])
        if stored_verified_at is not None and claims["_verified_at"] <= stored_verified_at:
            raise Problem(MODULE, 409, "attestation-outdated")

        fields, identifiers = _attested_values(row, claims)
        errors = validation.validate_company(fields, partial=True)
        errors += validation.validate_identifiers(list(identifiers.values()), row["country_code"])
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)

        changed = _changed_fields(row, fields, list(identifiers.values()))
        updates = dict(fields)
        updates |= {"core_data_source": "EBW", "core_data_verified_at": verified_at,
                    "verification_ref": claims["jti"]}
        store.update_company(companyId, **updates)
        store.set_identifiers(companyId, list(identifiers.values()))
        store.add_if_unused(claims["jti"], companyId)
        store.audit(companyId, sub, "updateCompanyFromAttestation", None,
                    {"changedFields": changed, "verificationRef": claims["jti"],
                     "old": {field: row.get(field) for field in
                             ("name", "street", "house_number", "postal_code", "city", "region")},
                     "new": fields})
        if changed:
            events.publish(MODULE, "CompanyDataChanged",
                           {"companyId": companyId, "changedFields": changed,
                            "coreDataChanged": True, "coreDataSource": "EBW"})
    return {"changedFields": changed, "company": company_view(companyId)}


# ---------------------------------------------------------------- deactivation and return (7.13, 8.5, 8.6)
def deactivate_company(input: dict) -> dict:
    """8.5: deactivation by Process Orchestration with reason `MANUAL` or `TRANSFERRED`."""
    cid, reason = input.get("companyId"), input.get("reason")
    with store.lock(cid):
        row = get_company(cid)
        if row["status"] == "INACTIVE":
            _check_deactivation_reason(reason)
            if reason == "TRANSFERRED" and row["deactivation_reason"] == "MANUAL":
                store.update_company(cid, deactivation_reason="TRANSFERRED")
                store.audit(cid, None, "stepDeactivateCompany", None,
                            {"deactivationReason": ["MANUAL", "TRANSFERRED"],
                             "processId": input.get("processId"),
                             "stepRunId": input.get("stepRunId")})
            return standin.step_reply(input, {"companyId": cid, "status": row["status"],
                                              "deactivationReason": row["deactivation_reason"]})
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"], retryable=False)
        _check_deactivation_reason(reason)
        store.update_company(cid, status="INACTIVE", deactivation_reason=reason,
                             deactivated_at=_now())
        store.audit(cid, None, "stepDeactivateCompany", None,
                    {"deactivationReason": reason, "processId": input.get("processId"),
                     "stepRunId": input.get("stepRunId")})
        events.publish(MODULE, "CompanyDeactivated", {"companyId": cid, "reason": reason})
    return standin.step_reply(input, {"companyId": cid, "status": "INACTIVE",
                                      "deactivationReason": reason})


def _check_deactivation_reason(reason) -> None:
    if reason not in store.DEACTIVATION_REASONS:
        raise Problem(MODULE, 400, "validation",
                      errors=[{"field": "reason", "reason": "MANUAL or TRANSFERRED"}],
                      retryable=False)


def deactivate_company_by_staff(companyId: str, body: dict, sub: str | None = None) -> dict:
    """7.13: manual deactivation by OSP staff, always with a justification."""
    with store.lock(companyId):
        row = get_company(companyId)
        if row["status"] == "INACTIVE":
            return company_view(companyId, detail=True)
        if row["status"] != "ACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"])
        errors = validation.validate_reason(body.get("reason"))
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors)
        store.update_company(companyId, status="INACTIVE", deactivation_reason="MANUAL",
                             deactivated_at=_now())
        store.audit(companyId, sub, "deactivateCompany", None, {"reason": body.get("reason")})
        events.publish(MODULE, "CompanyDeactivated", {"companyId": companyId, "reason": "MANUAL"})
    return company_view(companyId, detail=True)


def reactivate_company(input: dict) -> dict:
    """8.6: back to ACTIVE from an approved application of the matching kind."""
    cid, application_id = input.get("companyId"), input.get("applicationId")
    with store.lock(cid):
        row = get_company(cid)
        if row["status"] == "ACTIVE":
            return standin.step_reply(input, {"companyId": cid, "status": row["status"],
                                              "bpn": row["bpn"], "companyRoles": _active_roles(cid),
                                              "changedFields": []})
        if row["status"] != "INACTIVE":
            raise Problem(MODULE, 409, "invalid-state", detail=row["status"], retryable=False)

        application = _application(application_id)
        if application.get("companyId") != cid:
            raise Problem(MODULE, 409, "conflict", detail="application has another companyId",
                          retryable=False)
        expected = "TRANSFER" if row["deactivation_reason"] == "TRANSFERRED" else "REACTIVATION"
        if application.get("kind") != expected:
            raise Problem(MODULE, 409, "invalid-state",
                          detail=f"kind {application.get('kind')} does not match the reason",
                          retryable=False)
        # C12 calls this step after ApplicationApproved and before complete-application (flows
        # `reactivation` and `return`), so C1-M2 still has the application SUBMITTED; a repetition
        # after the flow may find it COMPLETED. C1-M2's ApplicationStatus has no APPROVED: the
        # approval is C1-M3's (C1-M2 openapi ApplicationStatus; OPEN-QUESTIONS 12).
        if application.get("status") not in ("SUBMITTED", "COMPLETED"):
            raise Problem(MODULE, 409, "invalid-state",
                          detail=f"application {application.get('status')}", retryable=False)

        data = application.get("companyData") or {}
        source_address = data.get("address") or {}
        verification = application.get("verification")
        fields = {"name": data.get("legalName"), "short_name": data.get("shortName"),
                  "street": source_address.get("streetName"),
                  "house_number": source_address.get("streetNumber"),
                  "postal_code": source_address.get("postalCode"), "city": source_address.get("city"),
                  "region": source_address.get("region"),
                  "country_code": source_address.get("countryCode")}
        if verification == "EBW" and validation.same_value(row["name"], data.get("legalName")):
            fields["name"] = row["name"]   # 6.3: an equal value keeps its stored spelling
        mismatched = []
        if fields["country_code"] != row["country_code"]:
            mismatched.append("countryCode")
        stored = {entry["type"]: entry for entry in store.list_identifiers(cid)}
        if verification == "EBW":
            claimed_ebwoid = next((entry["value"] for entry in data.get("identifiers") or []
                                   if entry.get("type") == "EBWOID"), None)
            if validation.value_normalized(claimed_ebwoid or "") != \
                    (stored.get("EBWOID") or {}).get("value_normalized"):
                mismatched.append("EBWOID")
        if mismatched:
            raise Problem(MODULE, 409, "company-mismatch", fields=mismatched, retryable=False)

        identifiers = list(stored.values())
        for entry in data.get("identifiers") or []:
            if entry.get("type") == "EBWOID":
                continue
            if verification == "EBW":
                if entry.get("type") not in CORE_IDENTIFIERS:
                    continue
                source = "BUSINESS_WALLET" if (stored.get(entry["type"]) or {}).get("source") == "BUSINESS_WALLET" else "DECLARED"
            else:
                source = "DECLARED" if (stored.get(entry["type"]) or {}).get("source") != "BUSINESS_WALLET" else "BUSINESS_WALLET"
            identifiers = [item for item in identifiers if item["type"] != entry["type"]]
            identifiers.append({"type": entry["type"], "value": entry["value"], "source": source})
        identifiers = [{"type": entry["type"], "value": entry["value"], "source": entry["source"]}
                       for entry in identifiers]

        errors = validation.validate_company(fields)
        errors += validation.validate_identifiers(identifiers, fields["country_code"])
        if errors:
            raise Problem(MODULE, 400, "validation", errors=errors, retryable=False)

        attestation_claims = application.get("attestation") or {}
        updates = dict(fields)
        updates |= {"status": "ACTIVE", "deactivation_reason": None, "reactivated_at": _now()}
        if verification == "EBW":
            updates |= {"core_data_source": "EBW",
                        "core_data_verified_at": attestation_claims.get("verifiedAt"),
                        "verification_ref": attestation_claims.get("attestationId")}
        else:
            updates |= {"core_data_source": "MANUAL", "core_data_verified_at": _now()}
        changed = _changed_fields(row, fields, identifiers)
        store.update_company(cid, **updates)
        store.set_identifiers(cid, identifiers)
        store.audit(cid, None, "stepReactivateCompany", None,
                    {"applicationId": application_id, "changedFields": changed,
                     "processId": input.get("processId"), "stepRunId": input.get("stepRunId")})
        if changed:
            events.publish(MODULE, "CompanyDataChanged",
                           {"companyId": cid, "changedFields": changed, "coreDataChanged": True,
                            "coreDataSource": updates["core_data_source"]})
        roles = sorted(role for role, status in store.list_roles(cid).items() if status == "ACTIVE")
        events.publish(MODULE, "CompanyReactivated",
                       {"companyId": cid, "bpn": row["bpn"], "companyRoles": roles})
    return standin.step_reply(input, {"companyId": cid, "status": "ACTIVE", "bpn": row["bpn"],
                                      "companyRoles": roles, "changedFields": changed})


# --------------------------------------------------------------------------- queries (9.1 - 9.3)
def query_company_role_catalog(*, lang: str | None = None, **_other) -> list[dict]:
    """9.4: role catalogue with descriptions in `lang`; the terms of the roles are at C1-M2 (9.3)."""
    wanted = lang or "en"
    return [{"companyRole": role, "assignableBy": entry.get("assignableBy"),
             "description": config.description(role, wanted),
             "descriptions": entry.get("descriptions") or {}}
            for role, entry in config.role_catalogue().items()]


def query_company(*, companyId: str) -> dict:
    """9.1"""
    return company_internal(companyId)


def query_companies(*, id: list[str] | str | None = None, bpn: list[str] | str | None = None,
                    **_other) -> dict:
    """9.2: exactly one of `id` and `bpn`, 1 to QUERY_MAX_COMPANIES values."""
    ids = [id] if isinstance(id, str) else list(id or [])
    bpns = [bpn] if isinstance(bpn, str) else list(bpn or [])
    if bool(ids) == bool(bpns):
        raise Problem(MODULE, 400, "validation",
                      errors=[{"field": "id,bpn", "reason": "exactly one of both"}])
    if len(ids + bpns) > config.query_max_companies():
        raise Problem(MODULE, 400, "validation",
                      errors=[{"field": "id,bpn", "reason": "too many values"}])
    items, found = [], set()
    for wanted in ids:
        if store.get_company(wanted) is not None:
            items.append(company_internal(wanted))
            found.add(wanted)
    for wanted in bpns:
        rows = store.find_companies(bpn=wanted, size=config.query_max_companies())[0]
        live = [row for row in rows if row["status"] != "REJECTED"] or rows
        for other in live:
            items.append(company_internal(other["id"]))
            found.add(wanted)
    return {"items": items, "notFound": [value for value in ids + bpns if value not in found]}


def find_identifier_matches(*, identifiers: list[dict], name: str | None = None,
                            excludeCompanyId: str | None = None,
                            statuses: list[str] | str | None = None, **_other) -> dict:
    """9.3: local duplicate search; the caller decides whether a match is a duplicate."""
    wanted_statuses = [statuses] if isinstance(statuses, str) else list(statuses or [])
    errors = []
    if not 1 <= len(identifiers) <= 10:
        errors.append({"field": "identifiers", "reason": "1 to 10 entries"})
    for entry in identifiers:
        if entry.get("type") not in (*store.IDENTIFIER_TYPES, "BPN"):
            errors.append({"field": "identifiers.type", "reason": str(entry.get("type"))})
        if not entry.get("value"):
            errors.append({"field": "identifiers.value", "reason": "required"})
    for value in wanted_statuses:
        if value not in store.STATUSES:
            errors.append({"field": "statuses", "reason": value})
    if errors:
        raise Problem(MODULE, 400, "validation", errors=errors)
    if not 1 <= len(identifiers) <= 10:
        raise Problem(MODULE, 400, "validation",
                      errors=[{"field": "identifiers", "reason": "1 to 10 entries"}])
    candidates, page, total = [], 0, None
    while total is None or len(candidates) < total:
        batch, total = store.find_companies(
            status=wanted_statuses or ["REQUESTED", "ACTIVE", "INACTIVE"], page=page, size=100)
        candidates += batch
        if not batch:
            break
        page += 1
    wanted_name = validation.normalise(name) if name else None
    matches = []
    for row in candidates:
        if row["id"] == excludeCompanyId:
            continue
        own = {(entry["type"], entry["value_normalized"])
               for entry in store.list_identifiers(row["id"])}
        if row["bpn"]:
            own.add(("BPN", validation.value_normalized(row["bpn"])))
        matched = sorted({entry["type"] for entry in identifiers
                          if (entry["type"], validation.value_normalized(entry["value"])) in own})
        if wanted_name and validation.normalise(row["name"]) == wanted_name:
            matched.append("NAME")
        if matched:
            matches.append({"companyId": row["id"], "name": row["name"], "status": row["status"],
                            "bpn": row["bpn"], "matchedOn": matched})
    matches.sort(key=lambda match: len(match["matchedOn"]), reverse=True)
    return {"matches": matches}

