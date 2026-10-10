#!/usr/bin/env python3
"""Fail-closed contracts for Jarvis-to-Jarvis retrieval.

NandaTown is a discovery and transport layer.  It is not a policy authority,
and this module intentionally does not perform network I/O.  A transport
adapter may decode JSON and call these validators before handing a request to a
local HomeHub-aware query coordinator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


PROTOCOL_VERSION = "uyp-federation-v1"
OPERATIONS = {"project.search", "project.related"}
VISIBILITIES = {"summary", "evidence_refs"}
SHARE_POLICIES = {"summary_only", "summary_and_evidence_refs"}


class FederationProtocolError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederationProtocolError(f"{field} must be a non-empty string")
    return value.strip()


def _list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise FederationProtocolError(f"{field} must be a list of strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _future_expiry(value: Any) -> str:
    text = _text(value, "expiresAt")
    try:
        expiry = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FederationProtocolError("expiresAt must be ISO-8601") from exc
    if expiry.tzinfo is None or expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise FederationProtocolError("federation request is expired")
    return expiry.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_peer_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the public metadata NandaTown may expose to Studio."""
    if not isinstance(value, Mapping):
        raise FederationProtocolError("peer metadata must be an object")
    required = {"peerId", "nodeId", "displayLabel", "transport", "status"}
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing peer fields: " + ", ".join(sorted(missing)))
    transport = _text(value["transport"], "transport")
    status = _text(value["status"], "status")
    if transport not in {"loopback", "lan", "cloudflare", "unknown"}:
        raise FederationProtocolError("unsupported peer transport")
    if status not in {"online", "offline", "discoverable", "unknown"}:
        raise FederationProtocolError("unsupported peer status")
    result = {key: _text(value[key], key) for key in ("peerId", "nodeId", "displayLabel", "transport", "status")}
    for key in ("handle", "lastSeen"):
        if key in value and value[key] is not None:
            result[key] = _text(value[key], key)
    for key in ("capabilities",):
        result[key] = _list(value.get(key, []), key)
    # A directory entry is deliberately incapable of carrying scopes,
    # credentials, or source paths.  Those are exchanged only after local
    # HomeHub authorization and are never part of discovery metadata.
    return result


def validate_query_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a bounded federation request without authorizing it."""
    if not isinstance(value, Mapping):
        raise FederationProtocolError("federation request must be an object")
    required = {"protocolVersion", "requestId", "groupId", "senderNodeId", "recipientNodeId", "operation", "query", "nonce", "expiresAt"}
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing request fields: " + ", ".join(sorted(missing)))
    if value["protocolVersion"] != PROTOCOL_VERSION:
        raise FederationProtocolError("unsupported federation protocol")
    operation = _text(value["operation"], "operation")
    if operation not in OPERATIONS:
        raise FederationProtocolError("operation is not read-only")
    query = _text(value["query"], "query")
    if len(query) > 4096:
        raise FederationProtocolError("query is too large")
    result = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": _text(value["requestId"], "requestId"),
        "groupId": _text(value["groupId"], "groupId"),
        "senderNodeId": _text(value["senderNodeId"], "senderNodeId"),
        "recipientNodeId": _text(value["recipientNodeId"], "recipientNodeId"),
        "operation": operation,
        "query": query,
        "nonce": _text(value["nonce"], "nonce"),
        "expiresAt": _future_expiry(value["expiresAt"]),
    }
    for key in ("projectScopes", "sourceScopes"):
        if key in value:
            result[key] = _list(value[key], key)
    audience = value.get("audience")
    if audience is not None:
        result["audience"] = _text(audience, "audience")
    return result


def validate_query_response(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an attributed summary/evidence response.

    Raw source bytes, arbitrary paths, vector stores, and full graph exports
    are rejected at this boundary.  A receiver still needs to validate the
    local HomeHub context and request nonce before accepting the response.
    """
    if not isinstance(value, Mapping):
        raise FederationProtocolError("federation response must be an object")
    required = {"protocolVersion", "requestId", "producingJarvis", "status", "visibility", "knowledgeVersion", "auditId"}
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing response fields: " + ", ".join(sorted(missing)))
    if value["protocolVersion"] != PROTOCOL_VERSION:
        raise FederationProtocolError("unsupported federation protocol")
    visibility = _text(value["visibility"], "visibility")
    if visibility not in VISIBILITIES:
        raise FederationProtocolError("response visibility must be summary or evidence_refs")
    forbidden = {"rawSource", "sourceBytes", "vectorStore", "database", "filesystemPath"}
    if forbidden.intersection(value.keys()):
        raise FederationProtocolError("federation response contains private source material")
    status = _text(value["status"], "status")
    if status not in {"ok", "denied", "expired", "offline", "error"}:
        raise FederationProtocolError("unsupported response status")
    result = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": _text(value["requestId"], "requestId"),
        "producingJarvis": _text(value["producingJarvis"], "producingJarvis"),
        "status": status,
        "visibility": visibility,
        "knowledgeVersion": _text(value["knowledgeVersion"], "knowledgeVersion"),
        "auditId": _text(value["auditId"], "auditId"),
    }
    if "answer" in value:
        result["answer"] = _text(value["answer"], "answer")
    refs = value.get("evidenceRefs", [])
    if not isinstance(refs, list) or any(not isinstance(ref, Mapping) for ref in refs):
        raise FederationProtocolError("evidenceRefs must be a list of objects")
    result["evidenceRefs"] = [dict(ref) for ref in refs]
    return result


def validate_group_invite(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a NandaTown group invite draft.

    An invite is a transport message and a HomeHub review input.  It is never
    itself a membership grant.  The requested scopes are copied as opaque
    capability IDs for the owner to review; the receiving Jarvis must obtain
    a fresh HomeHub context before using them.
    """
    if not isinstance(value, Mapping):
        raise FederationProtocolError("group invite must be an object")
    required = {
        "protocolVersion", "inviteId", "groupId", "inviterNodeId", "inviteeNodeId",
        "audience", "sharePolicy", "nonce", "expiresAt", "auditId",
    }
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing invite fields: " + ", ".join(sorted(missing)))
    if value["protocolVersion"] != PROTOCOL_VERSION:
        raise FederationProtocolError("unsupported federation protocol")
    result = {
        "protocolVersion": PROTOCOL_VERSION,
        "inviteId": _text(value["inviteId"], "inviteId"),
        "groupId": _text(value["groupId"], "groupId"),
        "inviterNodeId": _text(value["inviterNodeId"], "inviterNodeId"),
        "inviteeNodeId": _text(value["inviteeNodeId"], "inviteeNodeId"),
        "audience": _text(value["audience"], "audience"),
        "sharePolicy": _text(value["sharePolicy"], "sharePolicy"),
        "nonce": _text(value["nonce"], "nonce"),
        "expiresAt": _future_expiry(value["expiresAt"]),
        "auditId": _text(value["auditId"], "auditId"),
    }
    if result["inviterNodeId"] == result["inviteeNodeId"]:
        raise FederationProtocolError("invite must target a different Jarvis node")
    if result["sharePolicy"] not in SHARE_POLICIES:
        raise FederationProtocolError("unsupported group share policy")
    for key in ("requestedProjectScopes", "requestedSourceScopes"):
        if key in value:
            scopes = _list(value[key], key)
            if len(scopes) > 64:
                raise FederationProtocolError(f"{key} is too large")
            result[key] = scopes
    forbidden = {"token", "device_token", "grant", "accessContext", "rawSource", "filesystemPath"}
    if forbidden.intersection(value.keys()):
        raise FederationProtocolError("group invite contains authority or private source material")
    return result


def validate_group_invite_result(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a transport acknowledgement without turning it into a grant."""
    if not isinstance(value, Mapping):
        raise FederationProtocolError("group invite result must be an object")
    required = {"protocolVersion", "inviteId", "groupId", "status", "auditId"}
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing invite result fields: " + ", ".join(sorted(missing)))
    if value["protocolVersion"] != PROTOCOL_VERSION:
        raise FederationProtocolError("unsupported federation protocol")
    status = _text(value["status"], "status")
    if status not in {"pending", "accepted", "declined", "expired", "revoked"}:
        raise FederationProtocolError("unsupported invite result status")
    forbidden = {"grant", "accessContext", "device_token", "token"}
    if forbidden.intersection(value.keys()):
        raise FederationProtocolError("invite result must not carry HomeHub authority")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "inviteId": _text(value["inviteId"], "inviteId"),
        "groupId": _text(value["groupId"], "groupId"),
        "status": status,
        "auditId": _text(value["auditId"], "auditId"),
    }
