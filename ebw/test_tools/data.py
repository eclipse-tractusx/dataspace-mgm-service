# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Test persona and credential definitions, following C5-M1 (6.4, 14.1)."""

import copy

PERSON = {"given_name": "Erika", "family_name": "Mustermann", "birthdate": "1984-01-26"}
COMPANY = {"legal_name": "Beispiel Maschinenbau GmbH", "ebwoid": "EBWOID-DE-0000000001"}

DEFINITIONS = {
    "pid": {
        "vct": "urn:eudi:pid:1",
        "name": "Test PID",
        "labels": {
            "given_name": "Given name",
            "family_name": "Family name",
            "birthdate": "Date of birth",
            "place_of_birth": "Place of birth",
            "nationalities": "Nationalities",
            "issuing_country": "Issuing country",
            "issuing_authority": "Issuing authority",
            "date_of_expiry": "Expiry date",
        },
    },
    "mandate": {
        "vct": "urn:tx:test:mandate:1",
        "name": "Test mandate (register)",
        "labels": {
            "representative": "Representative",
            "represented": "Represented company",
            "representation_type": "Type of representation",
            "role": "Role",
            "valid_until": "Valid until",
        },
    },
    "lpid": {
        "vct": "urn:tx:test:lpid:1",
        "name": "Test LPID company",
        "labels": {
            "legal_name": "Name",
            "ebwoid": "EBWOID",
            "euid": "EUID",
            "address": "Address",
            "country": "Country",
        },
    },
}

CLAIMS = {
    # place_of_birth and date_of_expiry are mandatory in the PID rulebook; wallets such as Paradym rely on them
    "pid": {
        **PERSON,
        "place_of_birth": {"locality": "Stuttgart", "country": "DE"},
        "nationalities": ["DE"],
        "issuing_country": "DE",
        "issuing_authority": "DE",
        "date_of_expiry": "2031-12-31",
    },
    "mandate": {
        "representative": PERSON,
        "represented": {"identifier": COMPANY["ebwoid"], "legal_name": COMPANY["legal_name"]},
        "representation_type": "legal_representative",
        "role": "Geschäftsführerin",
        "valid_until": "2027-12-31",
    },
    "lpid": {
        **COMPANY,
        "euid": "DEXX001T.HRB100001",
        "address": {"street_address": "Musterstraße 1", "postal_code": "70569", "locality": "Stuttgart", "country": "DE"},
        "country": "DE",
    },
}

TYPES = {"pid": "PID", "mandate": "MANDATE", "lpid": "LPID"}


def claims_with(cid: str, overrides: dict | None) -> dict:
    """Default claims of a credential with top-level values replaced (for test variants)."""
    claims = copy.deepcopy(CLAIMS[cid])
    claims.update(overrides or {})
    return claims
