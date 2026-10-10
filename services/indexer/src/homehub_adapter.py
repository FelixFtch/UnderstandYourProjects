#!/usr/bin/env python3
"""Strict read-only adapter for a HomeHub ``AccessContext`` projection.

UnderstandYourProjects is deliberately not a HomeHub implementation.  This
module only validates a projection that HomeHub has already resolved and
issued.  It never creates principals, grants, pairing codes, revocations, or
audit records.  Keeping this boundary in one small module makes it possible
for the query service, an IndexJob worker, and the federation adapter to share
the same fail-closed checks.

The JSON shape is intentionally transport-neutral.  A future HomeHub adapter
may obtain the projection over a local socket, HTTPS, or a signed message;
callers should pass the resulting dictionary to :func:`validate_context`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping


REQUIRED_FIELDS = frozenset(
    {
        "principalId",
        "sessionId",
        "jarvisNodeId",
        "projectScopes",
        "sourceScopes",
        "grantEpoch",
        "policyDigest",
        "expiresAt",
        "auditId",
    }
)


class AccessContextError(ValueError):
    """Raised when a HomeHub projection is absent, malformed, or expired."""


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccessContextError(f"{field} must be a non-empty string")
    return value.strip()


def _scope_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry.strip() for entry in value):
        raise AccessContextError(f"{field} must be a list of non-empty strings")
    # Preserve the HomeHub ordering, but remove duplicates so callers cannot
    # accidentally treat repeated scopes as separate capabilities.
    return list(dict.fromkeys(entry.strip() for entry in value))


def parse_expiry(value: Any) -> datetime:
    """Parse an ISO-8601 expiry and normalize it to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise AccessContextError("expiresAt must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccessContextError("expiresAt must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        raise AccessContextError("expiresAt must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_context(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate and return a normalized HomeHub projection.

    This function is deliberately strict.  A missing field, a revoked marker,
    or an expired grant is indistinguishable from no access to callers.  The
    returned copy contains only JSON-compatible values and never adds an
    inferred scope or principal.
    """
    if not isinstance(value, Mapping):
        raise AccessContextError("AccessContext must be an object")
    missing = sorted(REQUIRED_FIELDS.difference(value.keys()))
    if missing:
        raise AccessContextError("missing HomeHub fields: " + ", ".join(missing))
    if value.get("revoked") is True or value.get("validation") in {"revoked", "expired"}:
        raise AccessContextError("HomeHub AccessContext is revoked or expired")
    expiry = parse_expiry(value["expiresAt"])
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expiry <= reference:
        raise AccessContextError("HomeHub AccessContext is expired")

    normalized = dict(value)
    for field in ("principalId", "sessionId", "jarvisNodeId", "grantEpoch", "policyDigest", "auditId"):
        normalized[field] = _non_empty_text(value[field], field)
    normalized["projectScopes"] = _scope_list(value["projectScopes"], "projectScopes")
    normalized["sourceScopes"] = _scope_list(value["sourceScopes"], "sourceScopes")
    normalized["expiresAt"] = expiry.isoformat().replace("+00:00", "Z")
    # Never let an invalid optional marker pass through as an authorization
    # signal.  HomeHub may add more metadata, which remains opaque to UYP.
    if "issuedAt" in value:
        normalized["issuedAt"] = _non_empty_text(value["issuedAt"], "issuedAt")
    return normalized


def _load_file(path: str) -> dict[str, Any] | None:
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            return validate_context(json.load(handle))
    except (OSError, json.JSONDecodeError, AccessContextError, TypeError):
        return None


def _load_url(url: str, token_file: str | None = None) -> dict[str, Any] | None:
    """Read a HomeHub projection over an approved local transport.

    HomeHub remains the issuer and policy authority.  UYP only sends the
    bearer stored in a separately permissioned file and validates the returned
    projection; it never exchanges, mints, or refreshes credentials.
    """
    try:
        headers = {"Accept": "application/json"}
        configured_token_file = token_file or os.environ.get("UYP_HOMEHUB_TOKEN_FILE")
        if configured_token_file:
            with open(os.path.expanduser(configured_token_file), encoding="utf-8") as handle:
                token = handle.read().strip()
            if not token:
                return None
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            return validate_context(json.loads(response.read()))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, AccessContextError, TypeError, ValueError):
        return None


def load_context(path: str | None = None) -> dict[str, Any] | None:
    """Load a HomeHub projection, returning ``None`` on any failure.

    When the approved HomeHub URL is configured it is authoritative for every
    read.  A URL failure therefore fails closed instead of falling back to a
    stale but locally valid projection that could survive a revocation.  The
    file path is retained for offline tests and deployments that deliberately
    provision a projection without the URL transport.
    """
    url = os.environ.get("UYP_HOMEHUB_ACCESS_CONTEXT_URL")
    if url:
        return _load_url(url)
    configured = path or os.environ.get("UYP_ACCESS_CONTEXT_FILE")
    if configured:
        return _load_file(configured)
    return None


def scope_allows(context: Mapping[str, Any], project_id: str, source_id: str) -> bool:
    """Check an already validated context against opaque capability IDs.

    A project or source identifier is a capability label, never a filesystem
    path.  The Connector is still the only component allowed to resolve a
    source path.
    """
    projects = context.get("projectScopes", [])
    sources = context.get("sourceScopes", [])
    return ("*" in projects or project_id in projects) and ("*" in sources or source_id in sources)


def public_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return fields safe for Studio status and audit displays.

    The full projection remains an internal capability.  This reduced object
    is useful in responses and logs without exposing opaque policy material.
    """
    checked = validate_context(context)
    return {
        "principalId": checked["principalId"],
        "sessionId": checked["sessionId"],
        "jarvisNodeId": checked["jarvisNodeId"],
        "grantEpoch": checked["grantEpoch"],
        "expiresAt": checked["expiresAt"],
        "auditId": checked["auditId"],
        "projectScopeCount": len(checked["projectScopes"]),
        "sourceScopeCount": len(checked["sourceScopes"]),
    }
