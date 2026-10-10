#!/usr/bin/env python3
"""Durable metadata for the Agent Box connector registry.

The registry answers *which connector projections are known to this Agent Box*.
It is deliberately not a policy store: it never contains bearer tokens, grants,
AccessContexts, or revocation decisions.  HomeHub remains the authority for
all of those things.  A future pairing/manifest adapter can upsert records
after HomeHub has returned its projection; the query service only reads the
sanitized projection.

The file is a small, versioned JSON document under ``UYP_STATE_ROOT`` (or the
path in ``UYP_CONNECTOR_REGISTRY_FILE``).  Writes are atomic and use a lock so
an indexing worker and the query API cannot replace one another's updates.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit

try:  # POSIX is the deployment target, but keep unit tests portable.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = "uyp.connector-registry.v1"
DEFAULT_STATE_ROOT = "~/dev/uyp/state"
MAX_CONNECTORS = 128
MAX_TEXT = 256
MAX_ID = 160
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")

VALID_KINDS = frozenset({"local", "nas", "github", "device"})
VALID_STATES = frozenset({"current", "partial", "pending", "offline", "failed", "revoked", "unsupported"})
VALID_MANIFEST_STATES = frozenset({"ready", "pending", "unavailable"})
VALID_TRANSPORTS = frozenset({"lan", "cloudflare", "local", "unknown"})

_THREAD_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def registry_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the registry path without allowing a source path to be used.

    ``UYP_CONNECTOR_REGISTRY_FILE`` is an explicit deployment setting.  When
    it is absent the registry lives below the Jetson state root, alongside UA
    graphs and job state, rather than in a source connector directory.
    """
    configured = path or os.environ.get("UYP_CONNECTOR_REGISTRY_FILE")
    if configured:
        return Path(os.path.realpath(os.path.expanduser(str(configured))))
    state = os.environ.get("UYP_STATE_ROOT", DEFAULT_STATE_ROOT)
    return Path(os.path.realpath(os.path.join(os.path.expanduser(state), "connectors", "registry.json")))


def _text(value: Any, *, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


def _id(value: Any, *, source: bool = False) -> str | None:
    value = _text(value, limit=MAX_ID)
    if value is None:
        return None
    if not (_SAFE_SOURCE_ID if source else _SAFE_ID).fullmatch(value):
        return None
    return value


def _string_list(value: Any, *, source: bool = False, limit: int = 64) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        item_id = _id(item, source=source)
        if item_id and item_id not in result:
            result.append(item_id)
        if len(result) >= limit:
            break
    return result


def _url_origin(value: Any) -> str | None:
    """Keep only an endpoint origin; never persist query strings or tokens."""
    raw = _text(value, limit=1024)
    if raw is None:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    # ``urlunsplit`` intentionally drops query/fragment.  A userinfo segment
    # is also rejected because it is commonly a credential accidentally put
    # in a URL.
    if parts.username or parts.password:
        return None
    try:
        host = parts.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host if parts.port is None else f"{host}:{parts.port}"
    except ValueError:
        return None
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def _health(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("state", "detail", "checkedAt", "connectorVersion"):
        text = _text(value.get(key), limit=MAX_TEXT)
        if text:
            result[key] = text
    if result.get("state") not in VALID_STATES:
        result.pop("state", None)
    return result


def _manifest(value: Any) -> dict[str, Any]:
    """Normalize bounded manifest metadata without retaining file paths."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    state = _text(value.get("state"))
    if state in VALID_MANIFEST_STATES:
        result["state"] = state
    epoch = _text(value.get("sourceEpoch"), limit=MAX_TEXT)
    if epoch:
        result["sourceEpoch"] = epoch
    generated = _text(value.get("generatedAt"), limit=MAX_TEXT)
    if generated:
        result["generatedAt"] = generated
    cursor = _text(value.get("cursor"), limit=MAX_TEXT)
    if cursor:
        result["cursor"] = cursor
    for key in ("fileCount", "total", "deletedCount"):
        number = value.get(key)
        if isinstance(number, int) and 0 <= number <= 10_000_000:
            result[key] = number
    return result


def normalize_connector(value: Any, *, require_id: bool = True) -> dict[str, Any] | None:
    """Return a safe connector record or ``None`` for malformed input.

    Unknown fields are dropped by design.  In particular, token-like fields,
    arbitrary paths, and full manifest file entries never enter the registry.
    """
    if not isinstance(value, dict):
        return None
    connector_id = _id(value.get("connectorId") or value.get("id"))
    node_id = _id(value.get("nodeId"))
    if require_id and (connector_id is None or node_id is None):
        return None
    if connector_id is None:
        connector_id = "connector:pending"
    if node_id is None:
        node_id = "node:pending"
    kind = _text(value.get("kind")) or "local"
    if kind not in VALID_KINDS:
        kind = "local"
    state = _text(value.get("state")) or "pending"
    if state not in VALID_STATES:
        state = "pending"
    manifest_state = _text(value.get("manifestState"))
    manifest = _manifest(value.get("manifest"))
    if manifest_state not in VALID_MANIFEST_STATES:
        manifest_state = manifest.get("state", "pending")
    transport = _text(value.get("transport")) or "unknown"
    if transport not in VALID_TRANSPORTS:
        transport = "unknown"

    record: dict[str, Any] = {
        "connectorId": connector_id,
        "nodeId": node_id,
        "kind": kind,
        "label": _text(value.get("label"), limit=MAX_TEXT) or "Connector",
        "state": state,
        "manifestState": manifest_state,
        "sourceIds": _string_list(value.get("sourceIds"), source=True),
        "capabilities": _string_list(value.get("capabilities"), limit=32),
        "transport": transport,
        "registeredAt": _text(value.get("registeredAt"), limit=MAX_TEXT) or now_iso(),
        "updatedAt": _text(value.get("updatedAt"), limit=MAX_TEXT) or now_iso(),
    }
    for key in ("lastSeen", "lastSyncAt", "sourceEpoch", "connectorVersion"):
        text = _text(value.get(key), limit=MAX_TEXT)
        if text:
            record[key] = text
    endpoint = _url_origin(value.get("endpoint"))
    if endpoint:
        record["endpoint"] = endpoint
    health = _health(value.get("health"))
    if health:
        record["health"] = health
    if manifest:
        record["manifest"] = manifest
    # HomeHub context is intentionally not a registry field.  Ignore any
    # grant/access/audit data supplied by a caller.
    return record


def empty_registry(*, reason: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "updatedAt": now_iso(), "connectors": []}
    if reason:
        result["warning"] = _text(reason) or "registry unavailable"
    return result


def _normalize_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        return empty_registry(reason="registry schema unavailable")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value.get("connectors", []):
        record = normalize_connector(raw)
        if record is None or record["connectorId"] in seen:
            continue
        seen.add(record["connectorId"])
        records.append(record)
        if len(records) >= MAX_CONNECTORS:
            break
    result = {"schemaVersion": SCHEMA_VERSION, "updatedAt": _text(value.get("updatedAt"), limit=MAX_TEXT) or now_iso(), "connectors": records}
    warning = _text(value.get("warning"))
    if warning:
        result["warning"] = warning
    return result


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with _THREAD_LOCK:
        with lock_path.open("a+", encoding="utf-8") as lock:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            return _normalize_document(json.load(fh))
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_registry(reason="registry unreadable")


def load_registry(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load a normalized registry without creating a file on read."""
    return _read_unlocked(registry_path(path))


def registry_health(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return non-sensitive registry diagnostics for the Studio health card."""
    resolved = registry_path(path)
    document = load_registry(resolved)
    exists = resolved.exists()
    warning = document.get("warning")
    return {
        "state": "current" if exists and not warning else "partial" if exists else "pending",
        "schemaVersion": document["schemaVersion"],
        "connectorCount": len(document["connectors"]),
        "updatedAt": document.get("updatedAt"),
        **({"warning": warning} if warning else {}),
    }


def _write_unlocked(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # State directories contain connector metadata but never tokens; still
    # keep them private by default on shared systems.
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def save_registry(document: dict[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Atomically save a normalized registry and return the saved document."""
    resolved = registry_path(path)
    normalized = _normalize_document(document)
    normalized["updatedAt"] = now_iso()
    with _locked(resolved):
        _write_unlocked(resolved, normalized)
    return copy.deepcopy(normalized)


def upsert_connector(record: dict[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Insert or update a connector projection; does not grant access."""
    incoming = normalize_connector(record)
    if incoming is None:
        raise ValueError("connector requires a safe connectorId and nodeId")
    resolved = registry_path(path)
    with _locked(resolved):
        document = _read_unlocked(resolved)
        existing = {item["connectorId"]: item for item in document["connectors"]}
        prior = existing.get(incoming["connectorId"])
        if prior:
            merged = {**prior, **incoming}
            # A partial health/manifest update must not erase prior details.
            if prior.get("health") and not incoming.get("health"):
                merged["health"] = prior["health"]
            if prior.get("manifest") and not incoming.get("manifest"):
                merged["manifest"] = prior["manifest"]
            incoming = normalize_connector(merged) or incoming
        existing[incoming["connectorId"]] = incoming
        ordered = list(existing.values())[:MAX_CONNECTORS]
        saved = _normalize_document({"schemaVersion": SCHEMA_VERSION, "connectors": ordered})
        saved["updatedAt"] = now_iso()
        _write_unlocked(resolved, saved)
    return copy.deepcopy(incoming)


def upsert_projection(record: dict[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Compatibility name for pairing/health adapters.

    The operation is still only a local metadata upsert.  It does not approve
    a pairing, issue a token, create a grant, or alter HomeHub state.
    """
    return upsert_connector(record, path)


def update_health(connector_id: str, *, state: str, detail: str | None = None, checked_at: str | None = None, connector_version: str | None = None, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Merge a connector health observation without changing HomeHub policy."""
    if state not in VALID_STATES:
        raise ValueError(f"invalid connector state: {state}")
    document = load_registry(path)
    current = next((item for item in document["connectors"] if item["connectorId"] == connector_id), None)
    if current is None:
        raise KeyError(connector_id)
    current["state"] = state
    current["updatedAt"] = now_iso()
    current["health"] = {key: value for key, value in {"state": state, "detail": detail, "checkedAt": checked_at or now_iso(), "connectorVersion": connector_version}.items() if value}
    if connector_version:
        current["connectorVersion"] = connector_version
    return upsert_connector(current, path)


def update_manifest(connector_id: str, manifest: dict[str, Any], *, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Merge bounded manifest metadata; file entries are never persisted."""
    document = load_registry(path)
    current = next((item for item in document["connectors"] if item["connectorId"] == connector_id), None)
    if current is None:
        raise KeyError(connector_id)
    safe = _manifest(manifest)
    current["manifest"] = safe
    current["manifestState"] = safe.get("state", current.get("manifestState", "pending"))
    if safe.get("sourceEpoch"):
        current["sourceEpoch"] = safe["sourceEpoch"]
    current["updatedAt"] = now_iso()
    return upsert_connector(current, path)


def forget_connector(connector_id: str, path: str | os.PathLike[str] | None = None) -> bool:
    """Forget local metadata only; this never revokes a HomeHub grant."""
    resolved = registry_path(path)
    with _locked(resolved):
        document = _read_unlocked(resolved)
        kept = [item for item in document["connectors"] if item["connectorId"] != connector_id]
        if len(kept) == len(document["connectors"]):
            return False
        document["connectors"] = kept
        document["updatedAt"] = now_iso()
        _write_unlocked(resolved, document)
    return True


def public_projection(document: dict[str, Any] | None = None, *, include_sources: bool = False) -> list[dict[str, Any]]:
    """Return fields matching Studio's ``ConnectorSummary`` contract.

    ``include_sources`` is only for an already-authorized projection.  The
    default intentionally omits source IDs, labels, and endpoint metadata.
    """
    records = (document or load_registry()).get("connectors", [])
    result: list[dict[str, Any]] = []
    for raw in records:
        record = normalize_connector(raw)
        if record is None:
            continue
        item: dict[str, Any] = {
            "connectorId": record["connectorId"],
            "nodeId": record["nodeId"],
            "kind": record["kind"],
            "label": record["label"] if include_sources else "Connector metadata pending",
            "state": record["state"],
            "manifestState": record["manifestState"],
            "sourceIds": record["sourceIds"] if include_sources else [],
        }
        for key in ("sourceEpoch", "grantEpoch", "auditId"):
            if include_sources and record.get(key):
                item[key] = record[key]
        result.append(item)
    return result

