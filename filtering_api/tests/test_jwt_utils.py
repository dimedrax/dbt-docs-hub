"""Security-critical: JWT claim extraction.

Wrong behaviour here directly maps to wrong RBAC decisions, so we cover
both happy paths and every input shape that could let a malformed token
escalate or crash the API.
"""

from __future__ import annotations

import jwt
import pytest

from jwt_utils import extract_groups, extract_username


def _make_token(payload: dict) -> str:
    return jwt.encode(payload, "irrelevant-test-secret", algorithm="HS256")


def _bearer(payload: dict) -> str:
    return f"Bearer {_make_token(payload)}"


# ---- extract_groups ---------------------------------------------------------


def test_extract_groups_returns_empty_when_header_missing():
    assert extract_groups(None) == []
    assert extract_groups("") == []


def test_extract_groups_returns_empty_when_header_malformed():
    assert extract_groups("NotBearer xxx") == []
    assert extract_groups("Bearer") == []  # missing token
    assert extract_groups("Bearer too many parts") == []


def test_extract_groups_returns_empty_on_undecodable_token():
    assert extract_groups("Bearer not.a.jwt") == []


def test_extract_groups_extracts_groups_claim():
    h = _bearer({"groups": ["dbt-docs-voiture", "dbt-docs-admin"]})
    assert extract_groups(h) == ["dbt-docs-voiture", "dbt-docs-admin"]


def test_extract_groups_falls_back_to_singular_group_claim():
    h = _bearer({"group": ["dbt-docs-voiture"]})
    assert extract_groups(h) == ["dbt-docs-voiture"]


def test_extract_groups_handles_string_claim_as_single_group():
    h = _bearer({"groups": "dbt-docs-voiture"})
    assert extract_groups(h) == ["dbt-docs-voiture"]


def test_extract_groups_strips_keycloak_leading_slashes():
    # Keycloak prefixes group paths with "/" — must be stripped to match
    # the bare names used in Rego policies.
    h = _bearer({"groups": ["/dbt-docs-voiture", "/dbt-docs-admin"]})
    assert extract_groups(h) == ["dbt-docs-voiture", "dbt-docs-admin"]


def test_extract_groups_skips_non_string_entries():
    # Defensive: never crash on a malformed claim where one entry is e.g. an int.
    h = _bearer({"groups": ["dbt-docs-voiture", 42, None]})
    assert extract_groups(h) == ["dbt-docs-voiture"]


def test_extract_groups_returns_empty_when_claim_absent():
    h = _bearer({"sub": "alice"})
    assert extract_groups(h) == []


# ---- extract_username -------------------------------------------------------


def test_extract_username_returns_none_when_header_missing():
    assert extract_username(None) is None
    assert extract_username("") is None


def test_extract_username_prefers_preferred_username_over_sub():
    h = _bearer({"preferred_username": "alice", "sub": "uuid-123"})
    assert extract_username(h) == "alice"


def test_extract_username_falls_back_to_sub():
    h = _bearer({"sub": "uuid-123"})
    assert extract_username(h) == "uuid-123"


def test_extract_username_returns_none_on_malformed_token():
    assert extract_username("Bearer not.a.jwt") is None


@pytest.mark.parametrize("header", ["", "Bearer", "BearerOnlyOnePart"])
def test_extract_username_returns_none_on_malformed_header(header):
    assert extract_username(header) is None
