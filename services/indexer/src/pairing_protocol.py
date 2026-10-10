#!/usr/bin/env python3
"""HomeHub-owned pairing approval and transport offer contracts.

This module validates data returned by HomeHub or a deployment controller.  It
does not create pairing codes, contact Cloudflare, or mutate Connector state.
That distinction lets the Jetson service prepare a reviewable pairing draft
without accidentally becoming a second device-ownership authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


class PairingProtocolError(ValueError):
    pass


def _text(value: Any, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise PairingProtocolError(f"{field} must be a bounded non-empty string")
    return value.strip()


def _expiry(value: Any) -> str:
    text = _text(value, "expiresAt")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PairingProtocolError("expiresAt must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise PairingProtocolError("pairing approval is expired")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_endpoint(value: Any, *, transport: str) -> str:
    """Return an origin-only endpoint suitable for transport reachability."""
    endpoint = _text(value, "endpoint", 1024)
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise PairingProtocolError("endpoint must be an origin without credentials or query parameters")
    if transport == "cloudflare" and parts.scheme != "https":
        raise PairingProtocolError("Cloudflare transport requires HTTPS")
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def validate_pairing_approval(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a one-time HomeHub pairing approval projection."""
    if not isinstance(value, Mapping):
        raise PairingProtocolError("pairing approval must be an object")
    required = {"approvalId", "homeHubDeviceId", "jetsonNodeId", "connectorId", "nonce", "grantEpoch", "auditId", "expiresAt", "transport", "endpoint"}
    missing = required.difference(value.keys())
    if missing:
        raise PairingProtocolError("missing pairing fields: " + ", ".join(sorted(missing)))
    transport = _text(value["transport"], "transport")
    if transport not in {"lan", "cloudflare", "local"}:
        raise PairingProtocolError("unsupported pairing transport")
    forbidden = {"device_token", "token", "secret", "private_key", "password", "pairing_code"}
    if forbidden.intersection(value.keys()):
        raise PairingProtocolError("HomeHub approval must not carry Connector credentials")
    return {
        "approvalId": _text(value["approvalId"], "approvalId"),
        "homeHubDeviceId": _text(value["homeHubDeviceId"], "homeHubDeviceId"),
        "jetsonNodeId": _text(value["jetsonNodeId"], "jetsonNodeId"),
        "connectorId": _text(value["connectorId"], "connectorId"),
        "nonce": _text(value["nonce"], "nonce"),
        "grantEpoch": _text(value["grantEpoch"], "grantEpoch"),
        "auditId": _text(value["auditId"], "auditId"),
        "expiresAt": _expiry(value["expiresAt"]),
        "transport": transport,
        "endpoint": normalize_endpoint(value["endpoint"], transport=transport),
    }
