#!/usr/bin/env python3
"""Fail-closed contracts for Jarvis-to-Jarvis retrieval.

NandaTown is a discovery and transport layer.  It is not a policy authority,
and this module intentionally does not perform network I/O.  A transport
adapter may decode JSON and call these validators before handing a request to a
local HomeHub-aware query coordinator.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping


PROTOCOL_VERSION = "uyp-federation-v1"
AGENT_IDENTITY_VERSION = "uyp-agent-identity-v1"
OPERATIONS = {"project.search", "project.related"}
VISIBILITIES = {"summary", "evidence_refs"}
SHARE_POLICIES = {"summary_only", "summary_and_evidence_refs"}
AGENT_MESSAGE_KINDS = {
    "agent.ask", "agent.reply", "contact.invite", "contact.accept",
    "group.invite", "group.accept", "group.message",
}
_JARVIS_NUMBER = re.compile(r"^J-[0-9]{4}-[0-9]{4}$")
_AGENT_FORBIDDEN = {
    "token", "bearer", "device_token", "accessContext", "grant",
    "rawSource", "sourceBytes", "filesystemPath", "vectorStore", "database",
}


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


def _issued_at(value: Any) -> str:
    """Normalize an issuance timestamp without treating it as authority."""
    text = _text(value, "issuedAt")
    try:
        issued = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FederationProtocolError("issuedAt must be ISO-8601") from exc
    if issued.tzinfo is None:
        raise FederationProtocolError("issuedAt must include a timezone")
    return issued.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_scopes(value: Any, field: str) -> list[str]:
    scopes = _list(value, field)
    if len(scopes) > 64:
        raise FederationProtocolError(f"{field} is too large")
    return scopes


def validate_agent_card(value: Mapping[str, Any], *, audience: str | None = None,
                       now: datetime | None = None) -> dict[str, Any]:
    """Validate a HomeHub-issued public Agent card projection.

    This checks the transport shape, expiry, revocation marker, and audience;
    it does *not* verify a signature or mint trust.  The HomeHub adapter must
    perform cryptographic verification and revocation lookup before a caller
    treats the returned card as verified.  Legacy Studio ``my_card`` values
    (display/number/urn/town only) are discovery metadata and intentionally do
    not pass this validator.
    """
    if not isinstance(value, Mapping):
        raise FederationProtocolError("agent card must be an object")
    required = {
        "schemaVersion", "cardId", "jarvisNodeId", "agentUrn", "jarvisNumber",
        "displayLabel", "capabilities", "issuer", "audience", "issuedAt",
        "expiresAt", "revocationRef", "keyFingerprint", "signature",
    }
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing agent card fields: " + ", ".join(sorted(missing)))
    if value["schemaVersion"] != AGENT_IDENTITY_VERSION:
        raise FederationProtocolError("unsupported agent identity protocol")
    if _AGENT_FORBIDDEN.intersection(value.keys()):
        raise FederationProtocolError("agent card contains authority or private source material")
    card = {key: _text(value[key], key) for key in (
        "schemaVersion", "cardId", "jarvisNodeId", "agentUrn", "jarvisNumber",
        "displayLabel", "issuer", "audience", "revocationRef",
        "keyFingerprint", "signature")}
    if not _JARVIS_NUMBER.fullmatch(card["jarvisNumber"]):
        raise FederationProtocolError("jarvisNumber must be J-####-####")
    card["issuedAt"] = _issued_at(value["issuedAt"])
    card["expiresAt"] = _future_expiry(value["expiresAt"])
    if value.get("revoked") is True or value.get("validation") in {"revoked", "expired"}:
        raise FederationProtocolError("agent card is revoked or expired")
    if audience is not None and card["audience"] != _text(audience, "audience"):
        raise FederationProtocolError("agent card audience mismatch")
    card["capabilities"] = _bounded_scopes(value["capabilities"], "capabilities")
    return card


def validate_agent_message(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate the shared Miku/Jarvis/NandaTown message envelope.

    This is a shape and confidentiality boundary only.  HomeHub must still
    resolve the sender/receiver, delegation, share card, grant epoch, and
    revocation state before dispatching the body.  The envelope never carries
    a bearer, AccessContext, raw source, vector store, or database.
    """
    if not isinstance(value, Mapping):
        raise FederationProtocolError("agent message must be an object")
    required = {
        "schemaVersion", "messageId", "kind", "requestId", "senderNodeId",
        "receiverNodeId", "nonce", "issuedAt", "expiresAt", "audience",
        "authorizationRef", "scope", "body",
    }
    missing = required.difference(value.keys())
    if missing:
        raise FederationProtocolError("missing agent message fields: " + ", ".join(sorted(missing)))
    if value["schemaVersion"] != AGENT_IDENTITY_VERSION:
        raise FederationProtocolError("unsupported agent identity protocol")
    if value["kind"] not in AGENT_MESSAGE_KINDS:
        raise FederationProtocolError("unsupported agent message kind")
    if _AGENT_FORBIDDEN.intersection(value.keys()):
        raise FederationProtocolError("agent message contains authority or private source material")
    result = {
        "schemaVersion": AGENT_IDENTITY_VERSION,
        "messageId": _text(value["messageId"], "messageId"),
        "kind": _text(value["kind"], "kind"),
        "requestId": _text(value["requestId"], "requestId"),
        "senderNodeId": _text(value["senderNodeId"], "senderNodeId"),
        "receiverNodeId": _text(value["receiverNodeId"], "receiverNodeId"),
        "nonce": _text(value["nonce"], "nonce"),
        "issuedAt": _issued_at(value["issuedAt"]),
        "expiresAt": _future_expiry(value["expiresAt"]),
        "audience": _text(value["audience"], "audience"),
        "authorizationRef": _text(value["authorizationRef"], "authorizationRef"),
    }
    if result["senderNodeId"] == result["receiverNodeId"]:
        raise FederationProtocolError("agent message must target a different node")
    scope = value["scope"]
    if not isinstance(scope, Mapping):
        raise FederationProtocolError("scope must be an object")
    share = _text(scope.get("sharePolicy"), "scope.sharePolicy")
    if share not in SHARE_POLICIES:
        raise FederationProtocolError("unsupported scope share policy")
    normalized_scope = {"sharePolicy": share}
    for key in ("projectScopes", "sourceScopes"):
        if key in scope:
            normalized_scope[key] = _bounded_scopes(scope[key], f"scope.{key}")
    result["scope"] = normalized_scope
    body = value["body"]
    if not isinstance(body, Mapping):
        raise FederationProtocolError("body must be an object")
    if _AGENT_FORBIDDEN.intersection(body.keys()):
        raise FederationProtocolError("agent message body contains private source material")
    # Body is intentionally opaque to the transport, but bounded to prevent a
    # discovery/mailbox protocol from becoming a source-dump channel.
    try:
        encoded = __import__("json").dumps(body, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise FederationProtocolError("body must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise FederationProtocolError("agent message body is too large")
    result["body"] = dict(body)
    for key in ("groupId", "contactId", "sessionId", "delegationRef"):
        if key in value and value[key] is not None:
            result[key] = _text(value[key], key)
    if value["kind"].startswith("group.") and not result.get("groupId"):
        raise FederationProtocolError("group messages require groupId")
    if value["kind"].startswith("contact.") and not result.get("contactId"):
        raise FederationProtocolError("contact messages require contactId")
    if value["kind"].startswith("agent.") and not (result.get("contactId") or result.get("groupId")):
        raise FederationProtocolError("agent messages require contactId or groupId")
    return result


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
