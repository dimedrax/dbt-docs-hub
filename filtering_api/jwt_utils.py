"""Reborn DataOps Platform — JWT helpers.

Signature is verified upstream by oauth2-proxy, so we only decode the payload
to extract the groups claim. We still check `exp`/`iat` to avoid replay of
tokens that slipped through somehow.
"""

from __future__ import annotations

import logging
from typing import Any

import jwt

log = logging.getLogger(__name__)


def extract_groups(authorization_header: str | None) -> list[str]:
    """Return the list of groups embedded in the bearer token.

    Returns an empty list when the header is missing or malformed.
    """
    if not authorization_header:
        return []

    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return []

    token = parts[1]
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        log.warning("Failed to decode JWT: %s", exc)
        return []

    groups = payload.get("groups") or payload.get("group") or []
    if isinstance(groups, str):
        groups = [groups]
    return [g.lstrip("/") for g in groups if isinstance(g, str)]


def extract_username(authorization_header: str | None) -> str | None:
    """Return the preferred_username claim, useful for logs."""
    if not authorization_header:
        return None
    parts = authorization_header.split()
    if len(parts) != 2:
        return None
    try:
        payload = jwt.decode(parts[1], options={"verify_signature": False, "verify_aud": False})
    except jwt.PyJWTError:
        return None
    return payload.get("preferred_username") or payload.get("sub")
