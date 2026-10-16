#!/usr/bin/env python3
"""Fail-closed group device-action adapter.

Group messages currently use NandaTown as a text transport.  Device control
must not be inferred from that transport or from a local ``groups.json``
record: HomeHub remains the authority that decides which member may control
which device and which curated action.  This module validates the small
request envelope needed to bridge a HomeHub-issued group context to the
existing provider-neutral HomeHub device route.

P1b: the context must be a signed ``homehub-group-device-context-v1`` grant
(cardId/keyFingerprint/signature present; the cryptographic check itself is
HomeHub's).  A dry-run proposal stays offline.  Before any LIVE execution the
adapter calls back HomeHub's ``/internal/studio/group-device/verify`` machine
hook (revocation/epoch/expiry are online state, never trust the presented
copy), then forwards the provider-neutral envelope to the existing device
route with the caller's HomeHub bearer, and independently reads the device
state back before reporting ``executed``.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Mapping

from groups import GroupsError, validate_group_context


DEVICE_ACTION_ID = re.compile(r"^home\.[a-z0-9_]+\.[a-z0-9_]+$")
HOME_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_SCOPE_IDS = 64
MAX_PARAMETERS = 32
READBACK_ACTION_ID = "home.device.read_state"
# Loopback machine hooks on the same box by default; deployment may point
# this at the Jetson's private LAN address (the value is administrator
# configuration, never request input).
INTERNAL_URL_ENV = "UYP_HOMEHUB_INTERNAL_URL"
DEFAULT_INTERNAL_URL = "http://127.0.0.1:5120"
VERIFY_PATH = "/internal/studio/group-device/verify"
# HomeHub's loopback machine guard (routes/studio_internal.py) requires this
# machine-to-machine marker on every internal call.
MACHINE_HEADER = {"X-Task-Source": "agent-gateway"}
HTTP_TIMEOUT_SECONDS = 5


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

    Device/action scopes exist only on the signed
    ``homehub-group-device-context-v1`` grant.  Missing fields are
    deliberately rejected by this adapter: a knowledge-only group context is
    unusable for device control.
    """
    return _scopes(context.get(field), field)


def _require_signature_fields(context: Mapping[str, Any]) -> None:
    """Presence check for the signed-grant fields (fail-closed).

    UYP never holds HomeHub's signing key, so the cryptographic check is
    HomeHub's online verify hook; what UYP can and must do locally is refuse
    any context that does not even CARRY the signature material.  This applies
    to dry-run as well: an unsigned context is not a device grant at all.
    """
    for field in ("signature", "cardId"):
        value = context.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GroupDeviceActionError(
                "group_device_signature_missing",
                "The group device context must be a signed HomeHub grant (cardId + signature).",
            )


def _internal_base_url() -> str:
    """Return the configured HomeHub internal URL after the loopback
    whitelist check (same discipline as companion-api's studio_homehub
    bridge): http/https only, no credentials/query/fragment, and the host
    must be loopback, RFC1918/link-local, localhost or *.local."""
    value = str(os.environ.get(INTERNAL_URL_ENV) or "").strip() or DEFAULT_INTERNAL_URL
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GroupDeviceActionError("group_device_action_unavailable", "HomeHub internal URL is misconfigured.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GroupDeviceActionError("group_device_action_unavailable", "HomeHub internal URL is misconfigured.")
    host = str(parsed.hostname).lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host not in {"localhost"} and not host.endswith(".local"):
            raise GroupDeviceActionError(
                "group_device_action_unavailable", "HomeHub internal URL host is not an approved local endpoint.")
    else:
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise GroupDeviceActionError(
                "group_device_action_unavailable", "HomeHub internal URL host is not an approved local endpoint.")
    return value.rstrip("/")


def _resolve_bearer(homehub_token: str | None) -> str:
    """Caller-presented HomeHub bearer first, then the service token file
    (the same credential resolution homehub_adapter._load_url uses)."""
    if homehub_token and homehub_token.strip():
        return homehub_token.strip()
    token_file = os.environ.get("UYP_HOMEHUB_TOKEN_FILE")
    if token_file:
        try:
            with open(os.path.expanduser(token_file), encoding="utf-8") as handle:
                token = handle.read().strip()
        except OSError:
            token = ""
        if token:
            return token
    raise GroupDeviceActionError(
        "group_device_action_unavailable",
        "No HomeHub bearer is available for live execution.",
    )


def _post_json(path: str, body: Mapping[str, Any], *, token: str | None) -> dict[str, Any]:
    """POST one JSON body to the approved HomeHub internal endpoint.

    Any transport failure or non-2xx status is fail-closed and raises
    ``group_device_action_unavailable``; the caller never sees a partial
    outcome as success.
    """
    url = _internal_base_url() + path
    headers = {"Accept": "application/json", "Content-Type": "application/json", **MACHINE_HEADER}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        raise GroupDeviceActionError(
            "group_device_action_unavailable",
            "HomeHub did not answer the group device call.",
        ) from exc
    if not isinstance(payload, dict):
        raise GroupDeviceActionError(
            "group_device_action_unavailable", "HomeHub returned a malformed response.")
    return payload


def _verify_context_online(context: Mapping[str, Any]) -> None:
    """Online re-verification before live execution: signature, ledger
    revocation, grant epoch and expiry are HomeHub online state, so the
    presented copy is never trusted on its own.  Any refusal or transport
    failure is fail-closed."""
    try:
        result = _post_json(VERIFY_PATH, {"context": dict(context)}, token=None)
    except GroupDeviceActionError as exc:
        raise GroupDeviceActionError(
            "group_context_invalid",
            "HomeHub group-device verify is unreachable; refusing live execution.",
        ) from exc
    if result.get("ok") is not True:
        reason = str(result.get("reason") or "unknown")
        raise GroupDeviceActionError(
            "group_context_invalid",
            f"HomeHub refused the group device context ({reason}).",
        )


def _execute_live(
    normalized_context: Mapping[str, Any],
    *,
    device_id: str,
    action_id: str,
    parameters: Mapping[str, Any],
    request_id: str,
    forward_route: str,
    homehub_token: str | None,
) -> dict[str, Any]:
    """Forward the provider-neutral envelope to HomeHub's existing device
    route with execution_mode=live, then independently read the state back.

    The response auditRef anchors the receipt.  ``executed`` is true only
    when HomeHub reported execution AND the independent readback state
    matches the state the execution claimed; a mismatch fails closed with
    ``group_device_readback_mismatch`` and never reports executed.
    """
    token = _resolve_bearer(homehub_token)
    envelope = {
        "schema_version": "homehub-device-action-request-v1",
        "home_device_id": device_id,
        "action_id": action_id,
        "parameters": dict(parameters),
        "request_id": request_id,
        "execution_mode": "live",
    }
    result = _post_json(forward_route, envelope, token=token)
    expected_state = result.get("state") if isinstance(result.get("state"), Mapping) else {}
    executed = bool(result.get("executed")) and bool(result.get("allowed", True))
    audit_ref = str(result.get("auditRef") or result.get("audit_ref") or "")
    if executed:
        # Independent readback through the same governed route: the action's
        # own 2xx is not proof the physical state changed.
        readback = _post_json(
            forward_route,
            {
                "schema_version": "homehub-device-action-request-v1",
                "home_device_id": device_id,
                "action_id": READBACK_ACTION_ID,
                "parameters": {},
                "request_id": f"{request_id}-readback",
                "execution_mode": "live",
            },
            token=token,
        )
        observed_state = readback.get("state") if isinstance(readback.get("state"), Mapping) else {}
        if dict(expected_state) != dict(observed_state):
            raise GroupDeviceActionError(
                "group_device_readback_mismatch",
                "The post-action readback state does not match the executed result.",
            )
    return {
        "executed": executed,
        "auditRef": audit_ref,
        "state": dict(expected_state),
        "reasonCode": str(result.get("reasonCode") or result.get("reason_code") or ""),
    }


def validate_group_device_action(
    context: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    now=None,
    homehub_token: str | None = None,
) -> dict[str, Any]:
    """Validate a group action and return a provider-neutral plan.

    ``context`` must be the signed HomeHub group device grant
    (``homehub-group-device-context-v1``).  Dry-run stays an offline plan;
    live execution verifies the context online with HomeHub first, forwards
    the envelope with the presented bearer, and confirms by readback.  UYP
    never widens either scope or resolves provider references.
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
    # Scope checks first (they name the caller's own mistake); only then the
    # grant-authenticity gate, which applies to dry-run and live alike.
    _require_signature_fields(normalized_context)
    resolved_request_id = request_id or f"group-{mode.replace('_', '-')}-{uuid.uuid4().hex}"
    forward_route = f"/api/studio/home-devices/{device_id}/actions"
    plan = {
        "schema_version": "homehub-group-device-action-plan-v1",
        "groupId": normalized_context["group_id"],
        "memberId": normalized_context["member_id"],
        "homeDeviceId": device_id,
        "actionId": action_id,
        "parameters": dict(parameters),
        "allowed": True,
        "requestId": resolved_request_id,
        "grantEpoch": normalized_context["grant_epoch"],
        "auditId": normalized_context["audit_id"],
        "forwardRoute": forward_route,
        "forwardEnvelope": {
            "schema_version": "homehub-device-action-request-v1",
            "home_device_id": device_id,
            "action_id": action_id,
            "parameters": dict(parameters),
            "execution_mode": "dry_run",
        },
    }
    if mode == "live":
        _verify_context_online(normalized_context)
        live = _execute_live(
            normalized_context,
            device_id=device_id,
            action_id=action_id,
            parameters=parameters,
            request_id=resolved_request_id,
            forward_route=forward_route,
            homehub_token=homehub_token,
        )
        plan.update(
            {
                "status": "live",
                "executionMode": "live",
                "executed": live["executed"],
                "state": live["state"],
                "reasonCode": live["reasonCode"],
                "auditRef": live["auditRef"],
            }
        )
        return plan
    plan.update({"status": "dry_run", "executionMode": "dry_run", "executed": False})
    return plan


__all__ = ["GroupDeviceActionError", "validate_group_device_action"]
