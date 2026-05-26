"""Reborn DataOps Platform — Policy Engine HTTP client.

The hub doesn't depend on a specific Policy Engine product. It speaks an
HTTP wire format inspired by OPA's data API, but any backend that honours
the contract works:

    POST {POLICY_ENGINE_URL}/v1/data/dbtdocs/allow
    POST {POLICY_ENGINE_URL}/v1/data/dbtdocs/column_visible
    Body:     {"input": {"user": {...}, "resource": {...}}}
    Response: {"result": true | false}

Reference impl: OPA loaded with the `dbtdocs` Rego package shipped
under `examples/opa-policies/` at the repo root.

Fail-closed: if the Policy Engine is unreachable or returns an error,
the decision defaults to deny. There is no "fail-open" knob — opening
up access on infrastructure failure would defeat the purpose.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

POLICY_ENGINE_URL = os.environ.get("POLICY_ENGINE_URL", "http://policy-engine:8181").rstrip("/")
PROJECT_DECISION_PATH = "/v1/data/dbtdocs/allow"
COLUMN_DECISION_PATH = "/v1/data/dbtdocs/column_visible"

_client = httpx.Client(timeout=2.0)


def _query(path: str, input_: dict) -> bool:
    url = f"{POLICY_ENGINE_URL}{path}"
    try:
        r = _client.post(url, json={"input": input_})
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Policy Engine query failed (%s): %s — defaulting to deny", url, exc)
        return False
    result = r.json().get("result", False)
    return bool(result)


def project_allowed(groups: list[str], project: str) -> bool:
    return _query(
        PROJECT_DECISION_PATH,
        {"user": {"groups": groups}, "resource": {"project": project}},
    )


def column_visible(
    groups: list[str], project: str, model: str, column: str, tags: list[str]
) -> bool:
    return _query(
        COLUMN_DECISION_PATH,
        {
            "user": {"groups": groups},
            "resource": {
                "project": project,
                "model": model,
                "column": column,
                "tags": tags,
            },
        },
    )
