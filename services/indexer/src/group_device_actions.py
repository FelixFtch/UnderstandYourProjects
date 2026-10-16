#!/usr/bin/env python3
"""Fail-closed group device-action adapter.

Group messages currently use NandaTown as a text transport.  Device control
must not be inferred from that transport or from a local ``groups.json``
record: HomeHub remains the authority that decides which member may control
which device and which curated action.  This module validates the small
request envelope needed to bridge a HomeHub-issued group context to the
existing provider-neutral HomeHub device route.

The adapter intentionally implements only a dry-run proposal today.  It
returns the exact envelope a future HomeHub group-action adapter must forward
to ``/api/studio/home-devices/<id>/actions``.  Live execution is rejected
until HomeHub supplies a group delegation endpoint; there is no safe way for
UYP to turn a text message or a local group record into an owner grant.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from groups import GroupsError, validate_group_context


DEVICE_ACTION_ID = re.compile(r"^home\.[a-z0-9_]+\.[a-z0-9_]+$")
HOME_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_SCOPE_IDS = 64
MAX_PARAMETERS = 32


class GroupDeviceActionError(ValueError):
    """A client-visible, fail-closed group action validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _scopes(value: Any, field: str) -> list[str]:
    """Normalize a HomeHub-issued action/device capability scope."""
    if value == "*":
        return ["*"]
    if not isinstance(value, list) or not value:
        raise GroupDeviceActionError(
            "group_device_scope_missing",
            f"HomeHub group context must include a non-empty {field} scope.",
        )
    if len(value) > MAX_SCOPE_IDS or any(not isinstance(item, str) for item in value):
        raise GroupDeviceActionError("group_device_scope_invalid", f"Invalid {field} scope.")
    result: list[str] = []
    for item in value:
        item = item.strip()
        if not item or len(item) > 160:
            raise GroupDeviceActionError("group_device_scope_invalid", f"Invalid {field} scope.")
        if item == "*":
            return ["*"]
        result.append(item)
    return list(dict.fromkeys(result))


def _allows(scope: list[str], value: str) -> bool:
    return "*" in scope or value in scope


def _context_scopes(context: Mapping[str, Any], field: str) -> list[str]:
    """Read optional capability scopes without inventing them.

    HomeHub's existing group context schema has no device/action scopes yet.
    Missing fields are deliberately rejected by this adapter.  That makes a
    group text grant unusable for device control until HomeHub explicitly
    issues the stronger delegation.
    """
    return _scopes(context.get(field), field)


def validate_group_device_action(
    context: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    now=None,
) -> dict[str, Any]:
    """Validate a group action and return a provider-neutral dry-run plan.

    ``context`` must be the HomeHub-issued group context projection.  The
    optional ``device_ids`` and ``action_ids`` fields are the capability
    scopes that a future HomeHub group-delegation endpoint must add.  UYP
    never widens either scope, resolves provider references, or executes a
    live action here.
    """
    try:
        normalized_context = validate_group_context(context, now=now)
    except GroupsError as exc:
        raise GroupDeviceActionError("group_context_invalid", str(exc)) from exc
    if not isinstance(payload, Mapping):
        raise GroupDeviceActionError("group_device_action_invalid", "The action body must be an object.")
    allowed_fields = {
        "schema_version", "action_id", "actionId", "home_device_id", "homeDeviceId",
        "parameters", "request_id", "requestId", "execution_mode", "executionMode",
    }
    unknown = sorted(set(payload) - allowed_fields)
    if unknown:
        raise GroupDeviceActionError("group_device_action_fields_invalid", "Unknown action fields.")
    if str(payload.get("schema_version") or "homehub-device-action-request-v1") != "homehub-device-action-request-v1":
        raise GroupDeviceActionError("group_device_action_schema_invalid", "Unsupported device action schema.")
    device_id = str(payload.get("home_device_id") or payload.get("homeDeviceId") or "").strip()
    if not HOME_DEVICE_ID.fullmatch(device_id):
        raise GroupDeviceActionError("home_device_id_invalid", "A valid HomeHub device id is required.")
    if payload.get("home_device_id") and payload.get("homeDeviceId") and payload["home_device_id"] != payload["homeDeviceId"]:
        raise GroupDeviceActionError("home_device_id_ambiguous", "home_device_id and homeDeviceId disagree.")
    action_id = str(payload.get("action_id") or payload.get("actionId") or "").strip()
    if not DEVICE_ACTION_ID.fullmatch(action_id):
        raise GroupDeviceActionError("device_action_id_invalid", "A curated HomeHub action id is required.")
    if payload.get("action_id") and payload.get("actionId") and payload["action_id"] != payload["actionId"]:
        raise GroupDeviceActionError("device_action_id_ambiguous", "action_id and actionId disagree.")
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, Mapping) or len(parameters) > MAX_PARAMETERS:
        raise GroupDeviceActionError("device_action_parameters_invalid", "Action parameters must be a bounded object.")
    # Provider details are never allowed to cross the group boundary.
    forbidden = {
        "entity_id", "entityId", "service", "service_name", "serviceName", "domain",
        "provider_device_ref", "providerDeviceRef", "endpoint", "endpoint_ref", "endpointRef",
    }
    if forbidden.intersection(parameters):
        raise GroupDeviceActionError("provider_action_fields_forbidden", "Provider-specific fields are not accepted.")
    request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip()
    if request_id and not REQUEST_ID.fullmatch(request_id):
        raise GroupDeviceActionError("device_action_request_id_invalid", "Invalid request id.")
    mode = str(payload.get("execution_mode") or payload.get("executionMode") or "dry_run").strip().lower()
    if mode not in {"dry_run", "live"}:
        raise GroupDeviceActionError("device_action_execution_mode_invalid", "execution_mode must be dry_run or live.")

    device_scope = _context_scopes(normalized_context, "device_ids")
    action_scope = _context_scopes(normalized_context, "action_ids")
    if not _allows(device_scope, device_id):
        raise GroupDeviceActionError("group_device_not_granted", "HomeHub did not grant this group access to the device.")
    if not _allows(action_scope, action_id):
        raise GroupDeviceActionError("group_action_not_granted", "HomeHub did not grant this group access to the action.")
    if mode == "live":
        raise GroupDeviceActionError(
            "group_device_action_pending",
            "HomeHub has not issued a group device-action delegation; live execution is disabled.",
        )
    return {
        "status": "dry_run",
        "schema_version": "homehub-group-device-action-plan-v1",
        "groupId": normalized_context["group_id"],
        "memberId": normalized_context["member_id"],
        "homeDeviceId": device_id,
        "actionId": action_id,
        "parameters": dict(parameters),
        "executionMode": "dry_run",
        "executed": False,
        "allowed": True,
        "requestId": request_id or f"group-dry-run-{uuid.uuid4().hex}",
        "grantEpoch": normalized_context["grant_epoch"],
        "auditId": normalized_context["audit_id"],
        "forwardRoute": f"/api/studio/home-devices/{device_id}/actions",
        "forwardEnvelope": {
            "schema_version": "homehub-device-action-request-v1",
            "home_device_id": device_id,
            "action_id": action_id,
            "parameters": dict(parameters),
            "execution_mode": "dry_run",
        },
    }


__all__ = ["GroupDeviceActionError", "validate_group_device_action"]
