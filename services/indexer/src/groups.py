#!/usr/bin/env python3
"""Jarvis Groups (P10): group -> knowledge-view model and scoped retrieval.

A Jarvis group opens a bounded slice of this box's project knowledge to a
named set of HomeHub members - "这个群只开放这些知识".  This module owns the
local half of that promise and nothing else:

* ``GroupRegistry`` - durable ``state/groups.json`` records of groups, their
  members, and their knowledge view.  The registry is an owner-authored
  input to HomeHub group issuance, never a grant store: it holds no tokens,
  no AccessContexts, and no revocation decisions.
* ``validate_group_context`` - strict, fail-closed validation of a group
  context projection, the same discipline as
  ``homehub_adapter.validate_context`` (required fields, expiry, revoked
  marker).  An invalid group context means no results, never a fallback to
  the unscoped store.
* ``view_allows`` / ``scoped_items`` / ``intersect_views`` - the
  pre-retrieval scope filter and the wildcard/view algebra behind it.
* ``source_overlap`` - which files a proposed answer cites fall outside a
  group view; the input for the future answer-scrubbing step.
* ``membership_snapshot`` / ``membership_stale`` - the per-group cache
  invalidation hook for membership and view changes.

HomeHub remains the only authority for identity, policy, and revocation
(AGENTS.md rule 1; AGENTFLOW_ARCHITECTURE.md sections 2-3).  NandaTown
remains a discovery and transport layer.  Nothing here issues a grant,
widens a scope, or decides that two people are the same.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

try:  # POSIX is the deployment target, but keep unit tests portable.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = "uyp.groups.v1"
DEFAULT_STATE_ROOT = "~/dev/uyp/state"
WILDCARD = "*"

MAX_GROUPS = 64
MAX_MEMBERS = 64
MAX_VIEW_IDS = 64
MAX_TEXT = 256
MAX_ID = 160
MAX_GROUPS_BYTES = 256 * 1024

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")

# The federation invite share policies (federation_protocol.SHARE_POLICIES);
# duplicated so this leaf module stays import-standalone like homehub_adapter.
SHARE_POLICIES = frozenset({"summary_only", "summary_and_evidence_refs"})

CONTEXT_REQUIRED_FIELDS = frozenset({
    "group_id",
    "member_id",
    "jarvis_node_id",
    "project_ids",
    "source_ids",
    "grant_epoch",
    "policy_digest",
    "expires_at",
    "audit_id",
})

_THREAD_LOCK = threading.RLock()


class GroupsError(ValueError):
    """Base class for groups-engine contract violations."""


class GroupContextError(GroupsError):
    """Raised when a group context projection is absent, malformed, or expired."""


class GroupRecordError(GroupsError):
    """Raised when a group record cannot be persisted as written."""


class GroupViewError(GroupsError):
    """Raised when a knowledge view is malformed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_grant_epoch() -> str:
    """A fresh local grant epoch for membership/view re-issues."""
    return f"epoch-{uuid.uuid4().hex[:12]}"


def _text(value: Any, *, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _id(value: Any) -> str | None:
    text = _text(value, limit=MAX_ID)
    if text is None or not _SAFE_ID.fullmatch(text):
        return None
    return text


def _require_id(value: Any, field: str) -> str:
    checked = _id(value)
    if checked is None:
        raise GroupRecordError(f"{field} must be a safe identifier")
    return checked


def _strict_text(value: Any, field: str) -> str:
    """Non-empty text or nothing - the homehub_adapter validation discipline."""
    if not isinstance(value, str) or not value.strip():
        raise GroupContextError(f"{field} must be a non-empty string")
    return value.strip()


def parse_expiry(value: Any) -> datetime:
    """Parse an ISO-8601 expiry and normalize it to UTC (strict)."""
    if not isinstance(value, str) or not value.strip():
        raise GroupContextError("expires_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise GroupContextError("expires_at must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        raise GroupContextError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_group_context(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate and return a normalized HomeHub group context projection.

    Deliberately strict, mirroring ``homehub_adapter.validate_context``: a
    missing field, a revoked marker, or an expired grant is
    indistinguishable from no access to callers.  The returned copy contains
    only JSON-compatible values and never adds an inferred scope or member.
    """
    if not isinstance(value, Mapping):
        raise GroupContextError("group context must be an object")
    missing = sorted(CONTEXT_REQUIRED_FIELDS.difference(value.keys()))
    if missing:
        raise GroupContextError("missing group context fields: " + ", ".join(missing))
    if value.get("revoked") is True or value.get("validation") in {"revoked", "expired"}:
        raise GroupContextError("group context is revoked or expired")
    expiry = parse_expiry(value["expires_at"])
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expiry <= reference:
        raise GroupContextError("group context is expired")

    normalized = dict(value)
    for field in ("group_id", "member_id", "jarvis_node_id", "grant_epoch", "policy_digest", "audit_id"):
        normalized[field] = _strict_text(value[field], field)
    normalized["project_ids"] = _context_scopes(value["project_ids"], "project_ids")
    normalized["source_ids"] = _context_scopes(value["source_ids"], "source_ids")
    normalized["expires_at"] = expiry.isoformat().replace("+00:00", "Z")
    # Never let an invalid optional marker pass through as an authorization
    # signal.  HomeHub may add more metadata, which stays opaque to UYP.
    if "issued_at" in value:
        normalized["issued_at"] = _strict_text(value["issued_at"], "issued_at")
    if value.get("share_policy") is not None:
        policy = _strict_text(value["share_policy"], "share_policy")
        if policy not in SHARE_POLICIES:
            raise GroupContextError("unsupported group share policy")
        normalized["share_policy"] = policy
    return normalized


def _context_scopes(value: Any, field: str) -> list[str]:
    """Scope lists for a context projection: ``"*"`` or non-empty strings."""
    if value == WILDCARD:
        return [WILDCARD]
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry.strip() for entry in value):
        raise GroupContextError(f'{field} must be a list of non-empty strings or "{WILDCARD}"')
    # Preserve HomeHub ordering but drop duplicates; a wildcard makes any
    # entries listed next to it redundant, so collapse to exactly ["*"].
    entries = list(dict.fromkeys(entry.strip() for entry in value))
    return [WILDCARD] if WILDCARD in entries else entries


def normalize_view(value: Any) -> dict[str, Any]:
    """Normalize a knowledge view; strict about shape, explicit about meaning.

    A view is ``{"project_ids": [...] | "*", "source_ids": [...] | "*"}``.
    A ``"*"`` entry collapses the list to exactly ``["*"]`` (wildcard means
    everything, so specific ids next to it are redundant).  An empty list is
    valid and means the group sees nothing in that dimension.
    """
    if not isinstance(value, Mapping):
        raise GroupViewError("knowledge view must be an object")
    return {
        "project_ids": _view_ids(value.get("project_ids"), "project_ids"),
        "source_ids": _view_ids(value.get("source_ids"), "source_ids"),
    }


def _view_ids(value: Any, field: str) -> list[str]:
    if value == WILDCARD:
        return [WILDCARD]
    if not isinstance(value, list):
        raise GroupViewError(f'{field} must be a list of identifiers or "{WILDCARD}"')
    result: list[str] = []
    for entry in value:
        checked = (WILDCARD if isinstance(entry, str) and entry.strip() == WILDCARD
                   else _id(entry))
        if checked is None:
            raise GroupViewError(f"{field} must be a list of safe identifiers")
        if checked not in result:
            result.append(checked)
        if len(result) > MAX_VIEW_IDS:
            raise GroupViewError(f"{field} exceeds {MAX_VIEW_IDS} entries")
    return [WILDCARD] if WILDCARD in result else result


def _project_ids_for(project: str) -> set[str]:
    """Both spelling conventions of a project capability id."""
    return {project, f"project:{project}"} if project else set()


def _source_ids_for(source: str, project: str) -> set[str]:
    """All spelling conventions of a source capability id for one item."""
    result = {source, f"source:{source}"} if source else set()
    if project:
        result.add(f"connector:{project}")
    return result


def _allows(projects: list[str], sources: list[str], project: str, source: str) -> bool:
    """The one scope predicate: wildcard, or an exact id in either spelling.

    Mirrors ``query_api.scope_allows``: an item's project is its output-root
    directory (also spelled ``project:<root>``), its source is the item's
    ``source`` field (also spelled ``connector:<root>`` / ``source:<id>``).
    An item that cannot be attributed to any project is visible only under
    a wildcard, never under a specific view.
    """
    if WILDCARD not in projects and not _project_ids_for(project).intersection(projects):
        return False
    if WILDCARD not in sources and not _source_ids_for(source, project).intersection(sources):
        return False
    return True


def view_allows(group_view: Any, project_id: str, source_id: str) -> bool:
    """Check one (project_id, source_id) pair against a knowledge view."""
    normalized = normalize_view(group_view)
    return _allows(normalized["project_ids"], normalized["source_ids"],
                   str(project_id or ""), str(source_id or ""))


def scoped_items(items: Any, group_view: Any) -> list[dict]:
    """Filter knowledge items to a group's knowledge view (pre-retrieval).

    ``None`` items or a ``None`` view yield ``[]``.  A malformed view raises
    ``GroupViewError``: an explicitly-passed view is a programming contract,
    and the fail-closed public path is :func:`scoped_retrieval`, which
    returns ``[]`` before an invalid view can ever reach this filter.
    Order is preserved; items are returned as-is, never copied or widened.
    """
    if items is None or group_view is None:
        return []
    normalized = normalize_view(group_view)
    projects, sources = normalized["project_ids"], normalized["source_ids"]
    return [item for item in items
            if isinstance(item, Mapping) and _allows(projects, sources, *item_scope(item))]


def intersect_views(first: Any, second: Any) -> dict[str, Any]:
    """The fail-closed meet of two views: an item must be in BOTH.

    This is what clamps a HomeHub-issued group context to the group's
    locally registered view when HomeHub hands the box a broader grant:
    ``"*"`` on one side defers to the other side, disjoint lists meet to
    the empty view (the group then sees nothing).
    """
    left, right = normalize_view(first), normalize_view(second)

    def meet(one: list[str], two: list[str]) -> list[str]:
        if WILDCARD in one:
            return list(two)
        if WILDCARD in two:
            return list(one)
        return [value for value in one if value in set(two)]

    return {
        "project_ids": meet(left["project_ids"], right["project_ids"]),
        "source_ids": meet(left["source_ids"], right["source_ids"]),
    }


def item_scope(item: Mapping[str, Any]) -> tuple[str, str]:
    """(project_id, source_id) of a KnowledgeItem; "" where unattributable.

    Mirrors ``query_api.scope_allows``: the project is the output-root
    directory of the item's ``_out_path`` (explicit ``project_id`` /
    ``project`` fields win when present), the source is the item's
    ``source`` field.  Source and project ids are capability labels here,
    never filesystem paths - the Connector stays the only path resolver.
    """
    if not isinstance(item, Mapping):
        return "", ""
    project = ""
    out_path = str(item.get("_out_path") or "")
    if out_path:
        project = os.path.basename(os.path.dirname(os.path.normpath(out_path)))
    if not project:
        project = str(item.get("project_id") or item.get("project") or "")
    return project, str(item.get("source") or "")


def source_overlap(answer_sources: Any, group_view: Any, items: Any = None) -> dict[str, Any]:
    """Report which files a proposed answer cites fall outside a group view.

    ``answer_sources`` is the ``sources`` list of a knowledge_search result
    (``{"file": ...}`` entries; bare path strings are accepted too).  Each
    cited file is resolved against ``items`` - the full candidate set the
    answer could have drawn on, not just the in-view slice - so a citation
    that only matches an out-of-view project is caught.  A file that cannot
    be resolved at all is ``unresolved``: fail-closed, a citation we cannot
    place inside the view is treated as outside it by ``clean``.
    """
    normalized = (normalize_view(group_view) if group_view is not None
                  else {"project_ids": [], "source_ids": []})
    projects, sources = normalized["project_ids"], normalized["source_ids"]
    index: dict[str, list[tuple[str, str]]] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("file") or item.get("path") or "")
        if path:
            index.setdefault(path, []).append(item_scope(item))
    in_view: list[str] = []
    out_of_view: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw in answer_sources or []:
        if isinstance(raw, Mapping):
            path = str(raw.get("file") or raw.get("path") or "")
        else:
            path = str(raw or "")
        path = path.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        candidates = index.get(path)
        if candidates is None and isinstance(raw, Mapping):
            declared = (str(raw.get("project_id") or ""), str(raw.get("source_id") or ""))
            if declared != ("", ""):
                candidates = [declared]
        if candidates is None:
            unresolved.append(path)
        elif all(_allows(projects, sources, project, source) for project, source in candidates):
            in_view.append(path)
        else:
            # The same relpath can exist in several projects; a citation is
            # only safe when EVERY indexed occurrence is inside the view.
            out_of_view.append(path)
    return {"in_view": in_view, "out_of_view": out_of_view, "unresolved": unresolved,
            "clean": not out_of_view and not unresolved}


def normalize_group(value: Any) -> dict[str, Any] | None:
    """Return a safe group record or ``None`` for malformed input.

    Unknown fields are dropped by design; tokens, grants, and
    AccessContexts never enter the registry because the record schema has
    no place for them.  ``created_at`` / ``grant_epoch`` may be ``None``
    here - the registry fills them on write, and document loads require
    them, so a record without both is not a usable group.
    """
    if not isinstance(value, Mapping):
        return None
    group_id = _id(value.get("group_id"))
    name = _text(value.get("name"))
    owner_member = _id(value.get("owner_member"))
    if not (group_id and name and owner_member):
        return None
    raw_members = value.get("member_members")
    if raw_members is None:
        raw_members = value.get("members")
    members: list[str] | None = []
    if isinstance(raw_members, list):
        for entry in raw_members:
            member = _id(entry)
            if member is None or len(members) >= MAX_MEMBERS:
                return None
            if member not in members:
                members.append(member)
    elif raw_members is not None:
        return None
    try:
        knowledge_view = normalize_view(value.get("knowledge_view"))
    except GroupViewError:
        return None
    return {
        "group_id": group_id,
        "name": name,
        "owner_member": owner_member,
        "member_members": members,
        "knowledge_view": knowledge_view,
        # Transport routing only (which NandaTown run carries this group's
        # messages); nullable and NEVER an access signal - changing it does
        # not re-issue grant_epoch because it cannot widen what the group
        # sees.  Run CREATION stays with the town admin; this is mapping.
        "town_run_id": _id(value.get("town_run_id")),
        "created_at": _text(value.get("created_at")),
        "grant_epoch": _id(value.get("grant_epoch")),
    }


def _record_complete(record: dict[str, Any] | None) -> bool:
    return record is not None and bool(record["created_at"]) and bool(record["grant_epoch"])


def _membership_signature(record: Mapping[str, Any]) -> tuple[str, frozenset[str]]:
    """What a membership change is measured against: owner + member set."""
    return str(record["owner_member"]), frozenset(record["member_members"])


def group_allows_member(record: Any, member_id: str) -> bool:
    """Whether a member id is the owner or a listed member of a group record."""
    checked = normalize_group(record) if isinstance(record, Mapping) else None
    if not _record_complete(checked):
        return False
    member = str(member_id or "").strip()
    return bool(member) and (member == checked["owner_member"] or member in checked["member_members"])


def membership_snapshot(group: Any) -> dict[str, Any]:
    """Capture what a per-group cache depended on at build time.

    Store this next to a cached group result; :func:`membership_stale`
    compares it against the live record and returns the stale flag when
    membership, view, or grant epoch moved.  A snapshot of an unusable
    group is poisoned (empty ids) so every later comparison is stale.
    """
    record = normalize_group(group) if isinstance(group, Mapping) else None
    if record is None:
        return {"group_id": "", "grant_epoch": "", "owner_member": "",
                "member_members": [], "knowledge_view": {"project_ids": [], "source_ids": []}}
    return {
        "group_id": record["group_id"],
        "grant_epoch": record["grant_epoch"] or "",
        "owner_member": record["owner_member"],
        "member_members": list(record["member_members"]),
        "knowledge_view": copy.deepcopy(record["knowledge_view"]),
    }


def membership_stale(group: Any, snapshot: Any) -> bool:
    """The member-change invalidation hook: True when a cached result is stale.

    Fail-closed: a missing group (deleted), an incomplete record, or a
    malformed snapshot is stale - a cache that cannot be proven fresh is
    never served.  Staleness is epoch-first (every registry membership or
    view change re-issues ``grant_epoch``) with owner/member/view
    comparison as the backstop for hand-edited files.
    """
    current = normalize_group(group) if isinstance(group, Mapping) else None
    if not _record_complete(current):
        return True
    if not isinstance(snapshot, Mapping):
        return True
    try:
        snapshot_view = normalize_view(snapshot.get("knowledge_view"))
    except GroupViewError:
        return True
    members = snapshot.get("member_members")
    fresh = (
        isinstance(members, list)
        and all(isinstance(member, str) for member in members)
        and _text(snapshot.get("group_id")) == current["group_id"]
        and _text(snapshot.get("grant_epoch")) == current["grant_epoch"]
        and _text(snapshot.get("owner_member")) == current["owner_member"]
        and set(members) == set(current["member_members"])
        and snapshot_view == current["knowledge_view"]
    )
    return not fresh


def _registry_lookup(registry: Any, group_id: str) -> dict[str, Any] | None:
    """Resolve a group record from a GroupRegistry, a document, or nothing."""
    if registry is None:
        return None
    if isinstance(registry, GroupRegistry):
        return registry.get(group_id)
    if isinstance(registry, Mapping):
        for raw in registry.get("groups", []) or []:
            record = normalize_group(raw)
            if (_record_complete(record) and record["group_id"] == group_id):
                return record
    return None


def scoped_retrieval(items: Any, context: Any, registry: Any = None, *,
                     now: datetime | None = None) -> list[dict]:
    """Fail-closed scoped retrieval for one group query (the P10 engine).

    Pipeline: strict context validation -> registry lookup (a group unknown
    locally yields no results) -> membership check (the requesting member
    must be the owner or a listed member) -> view intersection (the
    HomeHub context clamped to the group's registered knowledge view) ->
    :func:`scoped_items`.  ``registry=None`` scopes by the context's own
    view only, mirroring how non-group search trusts a validated HomeHub
    projection; when a registry IS provided it is mandatory - a group it
    does not know, or a member it does not list, sees nothing.  Any
    invalid input yields ``[]`` - never a fallback to the unscoped store,
    and never an error that leaks whether the group exists.
    """
    if items is None or not isinstance(context, Mapping):
        return []
    try:
        checked = validate_group_context(context, now=now)
    except GroupContextError:
        return []
    view = {"project_ids": checked["project_ids"], "source_ids": checked["source_ids"]}
    if registry is not None:
        record = _registry_lookup(registry, checked["group_id"])
        if record is None or not group_allows_member(record, checked["member_id"]):
            return []
        view = intersect_views(view, record["knowledge_view"])
    return scoped_items(items, view)


def groups_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the groups file path without allowing a source path to be used.

    ``UYP_GROUPS_FILE`` is an explicit deployment setting.  When absent the
    groups file lives at the Jetson state root (``state/groups.json``),
    alongside UA graphs, job state, and the connector registry, never in a
    source connector directory.
    """
    configured = path or os.environ.get("UYP_GROUPS_FILE")
    if configured:
        return Path(os.path.realpath(os.path.expanduser(str(configured))))
    state = os.environ.get("UYP_STATE_ROOT", DEFAULT_STATE_ROOT)
    return Path(os.path.realpath(os.path.join(os.path.expanduser(state), "groups.json")))


def empty_groups(reason: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "groups": []}
    if reason:
        result["warning"] = _text(reason) or "groups file unavailable"
    return result


def _normalize_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return empty_groups(reason="groups schema unavailable")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value.get("groups", []) or []:
        record = normalize_group(raw)
        if not _record_complete(record) or record["group_id"] in seen:
            continue
        seen.add(record["group_id"])
        records.append(record)
        if len(records) >= MAX_GROUPS:
            break
    result = {"schema_version": SCHEMA_VERSION,
              "updated_at": _text(value.get("updated_at")) or now_iso(),
              "groups": records}
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


def _read_document(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            # A first boot has no groups file yet; that is a pending state,
            # not corruption, and a read must never create the file.
            return empty_groups()
        if path.stat().st_size > MAX_GROUPS_BYTES:
            return empty_groups(reason="groups file exceeds size limit")
        with path.open(encoding="utf-8") as fh:
            return _normalize_document(json.load(fh))
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_groups(reason="groups file unreadable")


def _write_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Group metadata (never tokens) still stays private on shared systems.
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


class GroupRegistry:
    """Durable local registry of Jarvis groups and their knowledge views.

    A restart-safe projection of owner intent (``state/groups.json``):
    which groups exist, who their members are, and which slice of this
    box's knowledge each group opens.  It is an input to HomeHub group
    issuance and the local clamp for group retrieval - it is NOT a grant
    store and can never widen access beyond what a validated HomeHub group
    context allows.  Writes are atomic and locked so an indexing worker
    and the query API cannot replace one another's updates.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = groups_path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        """Load a normalized groups document without creating a file on read."""
        return _read_document(self._path)

    def save(self, document: Any) -> dict[str, Any]:
        """Atomically save a normalized groups document; returns what was saved."""
        normalized = _normalize_document(document)
        normalized["updated_at"] = now_iso()
        with _locked(self._path):
            _write_document(self._path, normalized)
        return copy.deepcopy(normalized)

    def get(self, group_id: str) -> dict[str, Any] | None:
        """Return one normalized group record or ``None``."""
        wanted = _id(group_id)
        if wanted is None:
            return None
        for record in self.load()["groups"]:
            if record["group_id"] == wanted:
                return record
        return None

    def upsert(self, record: Any) -> dict[str, Any]:
        """Insert or replace a group record (strict; never a grant).

        On update the creation timestamp is preserved.  A missing
        ``grant_epoch`` is inherited when owner and members are unchanged,
        and re-issued when they are not - so a membership edit through a
        wholesale upsert still invalidates caches.  An explicit
        ``grant_epoch`` (e.g. a HomeHub reissue marker) always wins.
        """
        incoming = normalize_group(record)
        if incoming is None:
            raise GroupRecordError(
                "group record requires a safe group_id, a name, an owner_member, "
                "a member_members list, and a knowledge_view with project_ids/source_ids")
        with _locked(self._path):
            document = _read_document(self._path)
            prior = next((item for item in document["groups"]
                          if item["group_id"] == incoming["group_id"]), None)
            if prior is None:
                incoming["created_at"] = incoming["created_at"] or now_iso()
                incoming["grant_epoch"] = incoming["grant_epoch"] or new_grant_epoch()
            else:
                incoming["created_at"] = prior["created_at"]
                if not incoming["grant_epoch"]:
                    if _membership_signature(incoming) != _membership_signature(prior):
                        incoming["grant_epoch"] = new_grant_epoch()
                    else:
                        incoming["grant_epoch"] = prior["grant_epoch"]
            if prior is None and len(document["groups"]) >= MAX_GROUPS:
                raise GroupRecordError("group limit reached")
            existing = {item["group_id"]: item for item in document["groups"]}
            existing[incoming["group_id"]] = incoming
            _write_document(self._path, {
                "schema_version": SCHEMA_VERSION,
                "updated_at": now_iso(),
                "groups": list(existing.values())[:MAX_GROUPS],
            })
        return copy.deepcopy(incoming)

    def remove(self, group_id: str) -> bool:
        """Forget a group locally; this never revokes a HomeHub grant."""
        wanted = _id(group_id)
        if wanted is None:
            return False
        with _locked(self._path):
            document = _read_document(self._path)
            kept = [item for item in document["groups"] if item["group_id"] != wanted]
            if len(kept) == len(document["groups"]):
                return False
            document["groups"] = kept
            document["updated_at"] = now_iso()
            _write_document(self._path, document)
        return True

    def _mutate(self, group_id: str, mutate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        wanted = _id(group_id)
        if wanted is None:
            raise KeyError(group_id)
        with _locked(self._path):
            document = _read_document(self._path)
            record = next((item for item in document["groups"]
                           if item["group_id"] == wanted), None)
            if record is None:
                raise KeyError(wanted)
            if mutate(record):
                document["updated_at"] = now_iso()
                _write_document(self._path, document)
            return copy.deepcopy(record)

    def add_member(self, group_id: str, member_id: str) -> dict[str, Any]:
        """Add a member; a real membership change re-issues the grant epoch."""
        member = _require_id(member_id, "member_id")

        def mutate(record: dict[str, Any]) -> bool:
            if member in record["member_members"]:
                return False  # a no-op must not invalidate caches
            if len(record["member_members"]) >= MAX_MEMBERS:
                raise GroupRecordError("group member limit reached")
            record["member_members"] = record["member_members"] + [member]
            record["grant_epoch"] = new_grant_epoch()
            return True

        return self._mutate(group_id, mutate)

    def remove_member(self, group_id: str, member_id: str) -> dict[str, Any]:
        """Remove a member; a real membership change re-issues the grant epoch."""
        member = _require_id(member_id, "member_id")

        def mutate(record: dict[str, Any]) -> bool:
            if member not in record["member_members"]:
                return False
            record["member_members"] = [value for value in record["member_members"] if value != member]
            record["grant_epoch"] = new_grant_epoch()
            return True

        return self._mutate(group_id, mutate)

    def set_view(self, group_id: str, knowledge_view: Any) -> dict[str, Any]:
        """Replace the knowledge view; a real view change re-issues the grant epoch."""
        normalized = normalize_view(knowledge_view)

        def mutate(record: dict[str, Any]) -> bool:
            if record["knowledge_view"] == normalized:
                return False
            record["knowledge_view"] = normalized
            record["grant_epoch"] = new_grant_epoch()
            return True

        return self._mutate(group_id, mutate)
