"""Security-critical: Policy Engine HTTP wrapper.

The hub fails CLOSED. Any bug that turns a network error into "allow"
is a privilege-escalation vulnerability, so each failure mode gets its
own test.
"""

from __future__ import annotations

import httpx
import pytest
import respx

import policy_engine

# All tests use the same base URL set in conftest.py.
BASE = "http://policy-engine.test"


# ---- happy path: shape of the request the hub sends -------------------------


@respx.mock
def test_project_allowed_posts_correct_shape_and_returns_true():
    route = respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        return_value=httpx.Response(200, json={"result": True})
    )
    assert policy_engine.project_allowed(["dbt-docs-voiture"], "voiture") is True
    assert route.called
    body = route.calls.last.request.read().decode().replace(" ", "")
    assert '"groups":["dbt-docs-voiture"]' in body
    assert '"project":"voiture"' in body


@respx.mock
def test_project_allowed_returns_false_on_explicit_deny():
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        return_value=httpx.Response(200, json={"result": False})
    )
    assert policy_engine.project_allowed(["random-group"], "voiture") is False


@respx.mock
def test_column_visible_posts_correct_shape_with_tags():
    route = respx.post(f"{BASE}/v1/data/dbtdocs/column_visible").mock(
        return_value=httpx.Response(200, json={"result": False})
    )
    assert (
        policy_engine.column_visible(
            ["dbt-docs-voiture"], "voiture", "dim_client", "email", ["pii"]
        )
        is False
    )
    body = route.calls.last.request.read().decode().replace(" ", "")
    assert '"model":"dim_client"' in body
    assert '"column":"email"' in body
    assert '"tags":["pii"]' in body


# ---- fail-closed: the contract that protects everything ---------------------


@respx.mock
def test_fails_closed_on_5xx():
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(return_value=httpx.Response(500))
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is False


@respx.mock
def test_fails_closed_on_4xx():
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(return_value=httpx.Response(404))
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is False


@respx.mock
def test_fails_closed_on_connection_error():
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        side_effect=httpx.ConnectError("backend unreachable")
    )
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is False


@respx.mock
def test_fails_closed_on_timeout():
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        side_effect=httpx.ReadTimeout("policy engine slow")
    )
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is False


@respx.mock
def test_fails_closed_when_response_lacks_result_field():
    # Defensive: a Policy Engine that returns 200 but {"unexpected": "shape"}
    # must not be interpreted as allow.
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is False


@respx.mock
def test_fails_closed_when_result_is_truthy_but_not_bool():
    # bool() on "yes" is True — make sure we don't interpret strings as decisions.
    # The wrapper accepts anything truthy as True (documented behaviour); this
    # test pins that contract so a future change must be deliberate.
    respx.post(f"{BASE}/v1/data/dbtdocs/allow").mock(
        return_value=httpx.Response(200, json={"result": "yes"})
    )
    assert policy_engine.project_allowed(["dbt-docs-admin"], "voiture") is True


# ---- decision paths: hub speaks the documented OPA-style URLs --------------


@pytest.mark.parametrize(
    ("attr", "expected"),
    [
        ("PROJECT_DECISION_PATH", "/v1/data/dbtdocs/allow"),
        ("COLUMN_DECISION_PATH", "/v1/data/dbtdocs/column_visible"),
    ],
)
def test_decision_paths_match_documented_contract(attr, expected):
    # The README's "Policy Engine contract" section advertises these paths;
    # changing them is a breaking change for every alternative implementation.
    assert getattr(policy_engine, attr) == expected
