#!/usr/bin/env python3
"""Project registry for analyzed folders (Jarvis Studio v2, docs/STUDIO_V2.md §6.2).

The registry is derived, owner-visible metadata about folders this Agent Box
has analyzed: which connector grant a project came from, its folder path (as
reported by the Connector, never read here), its place in the folder
hierarchy, and cached output statistics.  It is NOT an authorization source:
every read path filters records through the caller's HomeHub AccessContext
(``visible``), and grants stay with HomeHub.

Layout (all under ``UYP_STATE_ROOT``):

* ``projects/registry.json``         - the registry (atomic replace writes)
* ``projects/cache/<id>.json``       - per-project compact item index + stats

Identity rules:

* ``project_id`` is a HomeHub-opaque-safe id (``[A-Za-z0-9_.@-]``).  The plain
  connector ``root_name`` is used when it is safe and not already taken, so
  existing output directories (``output/<root_name>``) keep working.  A second
  folder with the same name (another device, or another path) gets
  ``<slug>-<hash6>``.
* ``output_dir`` (internal) is the directory name under the output/state
  roots.  It equals ``project_id`` except for imported legacy directories
  whose names are not opaque-id safe.

Hierarchy: on the same device, the deepest registered ancestor folder is the
parent; children are the projects whose parent is this one; siblings share a
non-null parent.  ``relink`` recomputes the whole relation after any change,
so nested chains (grandchildren) stay correct.
"""
from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import os
import posixpath
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCHEMA = "uyp.projects.v1"
CACHE_SCHEMA = "uyp.project-cache.v2"
DEFAULT_OUTPUT = "~/dev/uyp/output"
DEFAULT_STATE = "~/dev/uyp/state"
TIERS = ("A", "B", "C", "gate")
STATUSES = ("analyzed", "analyzing", "queued", "stale", "failed", "not_analyzed")
_ID_SAFE = re.compile(r"^[A-Za-z0-9_@-][A-Za-z0-9_.@-]{0,127}$")
# Route words under /api/projects/ that a project id must never shadow.
RESERVED_IDS = frozenset({"ids", "analyze", "jobs"})
_DEVICE_SAFE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_LOCK = threading.RLock()
_GRANTS_CACHE: dict = {"expires": 0.0, "grants": None}
_ACTIVE_RECOMPUTE_SECONDS = 60.0


# --------------------------------------------------------------- paths --
def _configured(name: str, default: str) -> str:
    return os.path.realpath(os.path.expanduser(os.environ.get(name, default)))


def output_root() -> str:
    return _configured("UYP_OUTPUT_ROOT", DEFAULT_OUTPUT)


def state_root() -> str:
    return _configured("UYP_STATE_ROOT", DEFAULT_STATE)


def registry_path() -> str:
    return os.path.join(state_root(), "projects", "registry.json")


def cache_dir() -> str:
    return os.path.join(state_root(), "projects", "cache")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_component(value) -> str | None:
    """A single path component under output/state roots, never a path."""
    text = str(value or "")
    if (not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text
            or text.startswith(".") or len(text) > 200
            or any(ord(ch) < 32 for ch in text)):
        return None
    return text


def safe_project_id(value) -> str | None:
    text = str(value or "")
    return text if _ID_SAFE.match(text) else None


def safe_device_id(value) -> str | None:
    text = str(value or "").strip()
    return text if _DEVICE_SAFE.match(text) else None


def parse_time(value) -> float | None:
    """Epoch seconds from an int/float epoch, a numeric string, or ISO-8601.

    Connector manifests carry ``int(st_mtime)``; index_project stamps
    ``analyzed_at`` as naive local ``%FT%T`` (interpreted as local time).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        return number if number > 0 else None
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # naive -> server-local time
    return parsed.timestamp()


def iso_from_epoch(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------- folder paths --
class PathError(ValueError):
    """Raised for a folder path that cannot be analyzed."""


def normalize_folder_path(value) -> str:
    """Validate an owner-supplied Mac folder path (absolute or ``~/``).

    The Connector resolves and authorizes the path; this only rejects shapes
    that can never be a grantable folder (relative paths, traversal, control
    characters) before anything is sent anywhere.
    """
    if not isinstance(value, str):
        raise PathError("path must be a string")
    text = value.strip()
    if not text or len(text) > 1024 or "\x00" in text or any(ord(ch) < 32 for ch in text):
        raise PathError("path is empty, too long, or contains control characters")
    if not (text.startswith("/") or text.startswith("~/")):
        raise PathError("path must be absolute (/...) or home-relative (~/...)")
    if any(part == ".." for part in text.split("/")):
        raise PathError("path must not contain '..'")
    head, rest = ("~", text[1:]) if text.startswith("~/") else ("", text)
    normalized = posixpath.normpath(rest)
    if normalized in {"/", "."}:
        raise PathError("path must name a folder, not the root")
    return head + normalized


def is_ancestor(ancestor: str | None, descendant: str | None) -> bool:
    if not ancestor or not descendant:
        return False
    base = ancestor.rstrip("/")
    return descendant != base and descendant.startswith(base + "/")


def relative_inside(ancestor: str, descendant: str) -> str:
    return descendant[len(ancestor.rstrip("/")) + 1:]


# --------------------------------------------------------------- registry --
def _empty_registry() -> dict:
    return {"schema_version": SCHEMA, "updated_at": None, "projects": []}


def _atomic_write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


@contextlib.contextmanager
def _file_lock(path: str):
    """Process-wide + cross-process (flock) lock around registry edits."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _LOCK:
        handle = open(path + ".lock", "a+")
        try:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield
        finally:
            handle.close()


class ProjectRegistry:
    """Durable registry document at ``<state>/projects/registry.json``."""

    def __init__(self, path: str | None = None):
        self.path = path or registry_path()

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return _empty_registry()
        if not isinstance(doc, dict) or not isinstance(doc.get("projects"), list):
            return _empty_registry()
        doc.setdefault("schema_version", SCHEMA)
        doc["projects"] = [r for r in doc["projects"] if isinstance(r, dict) and safe_project_id(r.get("project_id"))]
        return doc

    def save(self, doc: dict) -> None:
        doc["schema_version"] = SCHEMA
        doc["updated_at"] = now_iso()
        _atomic_write_json(self.path, doc)

    @contextlib.contextmanager
    def edit(self):
        """Read-modify-write under the registry lock; saves on clean exit."""
        with _file_lock(self.path):
            doc = self.load()
            before = json.dumps(doc, sort_keys=True, ensure_ascii=False)
            yield doc
            relink(doc)
            # Skip the write when nothing changed (list calls refresh often).
            if json.dumps(doc, sort_keys=True, ensure_ascii=False) != before or not os.path.exists(self.path):
                self.save(doc)

    def records(self) -> list[dict]:
        return self.load()["projects"]

    def get(self, project_id: str) -> dict | None:
        return next((r for r in self.records() if r.get("project_id") == project_id), None)


def connector_device_id() -> str:
    """The Mac connector's device id, shared with companion /api/studio/devices.

    Same env and default as the POLICY devices route: ``UYP_CONNECTOR_DEVICE_ID``
    or ``d_mac``.  Every project analyzed through this connector lives there.
    """
    return safe_device_id(os.environ.get("UYP_CONNECTOR_DEVICE_ID")) or "d_mac"


def effective_device(doc: dict, record: dict) -> str:
    return record.get("device_id") or connector_device_id()


def relink(doc: dict) -> None:
    """Recompute parent/children for every record (deepest ancestor wins)."""
    records = doc["projects"]
    by_id = {r["project_id"]: r for r in records}
    for record in records:
        record["parent_id"] = None
        record["children"] = []
    for record in records:
        best = None
        for other in records:
            if other is record or effective_device(doc, other) != effective_device(doc, record):
                continue
            if is_ancestor(other.get("path"), record.get("path")):
                if best is None or len(other["path"]) > len(best["path"]):
                    best = other
        if best is not None:
            record["parent_id"] = best["project_id"]
    for record in records:
        if record["parent_id"] in by_id:
            by_id[record["parent_id"]]["children"].append(record["project_id"])
    for record in records:
        record["children"].sort()


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.@-]+", "-", str(text or "")).strip("-.")
    return slug[:60] or "project"


def allocate_project_id(doc: dict, root_name: str, device_id: str | None, path: str | None) -> str:
    """Plain root_name when safe and free; otherwise ``<slug>-<hash6>``."""
    taken = {r["project_id"] for r in doc["projects"]}
    taken_dirs = {r.get("output_dir") for r in doc["projects"]}
    if (safe_project_id(root_name) and root_name not in RESERVED_IDS
            and root_name not in taken and root_name not in taken_dirs):
        return root_name
    seed = f"{device_id or ''}|{path or root_name}"
    for salt in range(0, 50):
        digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()[:6]
        candidate = f"{_slug(root_name)}-{digest}"
        if candidate not in taken and candidate not in taken_dirs:
            return candidate
    raise RuntimeError("could not allocate a unique project id")


def find_by_path(doc: dict, path: str, device_id: str | None) -> dict | None:
    device = device_id or connector_device_id()
    for record in doc["projects"]:
        if record.get("path") == path and effective_device(doc, record) == device:
            return record
    return None


def new_record(project_id: str, *, root_name: str, path: str | None, device_id: str | None,
               output_dir: str, grant_id: str | None, origin: str) -> dict:
    stamp = now_iso()
    return {
        "project_id": project_id, "device_id": device_id or connector_device_id(), "root_name": root_name,
        "path": path, "output_dir": output_dir, "grant_id": grant_id,
        "parent_id": None, "children": [], "status": "not_analyzed",
        "analyzed_at": None, "stats": empty_stats(), "tiers": empty_tiers(),
        "embedded_roots": [], "origin": origin, "created_at": stamp, "updated_at": stamp,
        "context": None, "linked_children": [], "last_job_id": None, "signature": None,
    }


def empty_stats() -> dict:
    return {"files": 0, "summarized": 0, "nodes": 0, "edges": 0, "languages": []}


def empty_tiers() -> dict:
    return {tier: 0 for tier in TIERS}


# -------------------------------------------------------------- connector --
class ConnectorError(RuntimeError):
    def __init__(self, code: str, message: str = "", status: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.status = status


class ConnectorClient:
    """Minimal Mac Connector client (CONNECTOR_PROTOCOL_V1) for project jobs.

    Fast, no retries: this runs on request paths.  The long-running indexer
    keeps its own retrying client.
    """

    def __init__(self, host: str | None = None, token_file: str | None = None, timeout: float = 8.0):
        self.host = (host or os.environ.get("UYP_CONNECTOR_HOST") or "").rstrip("/")
        self.token_file = os.path.expanduser(token_file or os.environ.get("UYP_CONNECTOR_TOKEN_FILE", "~/.config/uyp/token"))
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.host)

    def _token(self) -> str:
        try:
            with open(self.token_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError as exc:
            raise ConnectorError("connector_token_missing", "Connector token file is unreadable") from exc
        if not token:
            raise ConnectorError("connector_token_missing", "Connector token file is empty")
        return token

    def request(self, method: str, path: str, body: dict | None = None):
        if not self.host:
            raise ConnectorError("connector_unconfigured", "UYP_CONNECTOR_HOST is not set")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        safe_path = urllib.parse.quote(path, safe="/?=&%")
        request = urllib.request.Request(self.host + safe_path, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read() or b"{}")
            except (ValueError, OSError):
                detail = {}
            finally:
                exc.close()
            raise ConnectorError(str(detail.get("error") or f"connector_http_{exc.code}"),
                                 f"Connector answered {exc.code}", exc.code) from exc
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise ConnectorError("connector_unavailable", f"Connector unreachable: {type(exc).__name__}") from exc

    def grants(self) -> list[dict]:
        value = self.request("GET", "/grants")
        grants = value.get("grants") if isinstance(value, dict) else None
        return [g for g in grants if isinstance(g, dict) and g.get("id") and g.get("path")] if isinstance(grants, list) else []

    def create_grant(self, path: str) -> dict:
        value = self.request("POST", "/grants", {"path": path})
        if not isinstance(value, dict) or not value.get("id") or not value.get("path"):
            raise ConnectorError("connector_bad_response", "Connector did not return a grant")
        return {"id": str(value["id"]), "path": str(value["path"])}

    def manifest(self, grant_id: str) -> dict:
        from index_project import fetch_full_manifest  # follows the 2000-entry page cursor

        def api_fn(_host, _token, path, binary=False):
            return self.request("GET", path)

        return fetch_full_manifest(self.host, "", grant_id, api_fn=api_fn)


def cached_connector_grants(client: ConnectorClient | None = None, ttl: float = 60.0) -> list[dict] | None:
    """Connector grants (id -> path) cached briefly; None when unreachable."""
    now = time.monotonic()
    with _LOCK:
        if now < _GRANTS_CACHE["expires"]:
            return _GRANTS_CACHE["grants"]
    client = client or ConnectorClient(timeout=3.0)
    grants = None
    if client.configured:
        try:
            grants = client.grants()
        except ConnectorError:
            grants = None
    with _LOCK:
        _GRANTS_CACHE["expires"] = now + (ttl if grants is not None else min(ttl, 15.0))
        _GRANTS_CACHE["grants"] = grants
    return grants


def reset_caches() -> None:
    with _LOCK:
        _GRANTS_CACHE["expires"] = 0.0
        _GRANTS_CACHE["grants"] = None


def match_grant(grants: list[dict], path: str) -> dict | None:
    """Find an existing connector grant for an absolute or ``~/`` path."""
    for grant in grants:
        if grant.get("path") == path:
            return grant
    if path.startswith("~/"):
        tail = path[1:]
        for grant in grants:
            gpath = str(grant.get("path") or "")
            if gpath.endswith(tail) and re.match(r"^/(Users|home)/[^/]+$", gpath[: -len(tail)] or ""):
                return grant
    return None


# ----------------------------------------------------------- output stats --
def _project_dirs(output_dir: str) -> tuple[str, str, str]:
    return (os.path.join(output_root(), output_dir),
            os.path.join(state_root(), output_dir + ".json"),
            os.path.join(state_root(), output_dir, "ua", "knowledge-graph.json"))


def _stat_sig(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return "-"


def output_signature(output_dir: str) -> str:
    out_dir, state_file, graph = _project_dirs(output_dir)
    try:
        count = sum(1 for name in os.listdir(out_dir) if name.endswith(".knowledge.json"))
    except OSError:
        count = 0
    return "|".join((_stat_sig(out_dir), str(count), _stat_sig(state_file),
                     _stat_sig(os.path.join(state_root(), output_dir + ".keyfiles.json")), _stat_sig(graph)))


def _compact_item(item: dict) -> dict | None:
    rel = item.get("file")
    if not isinstance(rel, str) or not rel:
        return None
    derived = item.get("derived") if isinstance(item.get("derived"), dict) else {}
    purpose = derived.get("purpose")
    keyfile = item.get("keyfile") if isinstance(item.get("keyfile"), dict) else {}
    version = item.get("version") if isinstance(item.get("version"), dict) else {}

    def strings(value, cap):
        return [str(v)[:240] for v in value[:cap]] if isinstance(value, list) else []

    rank = keyfile.get("rank")
    return {
        "file": rel,
        "mtime": parse_time(version.get("mtime")),
        "purpose": str(purpose)[:600] if isinstance(purpose, str) and purpose.strip() else "",
        "key_points": strings(derived.get("key_points"), 3),
        "components": strings(derived.get("components"), 3),
        "tier": keyfile.get("tier") if keyfile.get("tier") in TIERS else None,
        "rank": rank if isinstance(rank, int) else None,
        "embedded": str(keyfile["embedded"]) if keyfile.get("embedded") else None,
        "verdict": str(item.get("verdict") or ""),
        "analyzed_at": parse_time(item.get("analyzed_at")),
    }


def read_items(output_dir: str) -> list[dict]:
    out_dir = os.path.join(output_root(), output_dir)
    items = []
    for path in sorted(glob.glob(os.path.join(glob.escape(out_dir), "*.knowledge.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(raw, dict):
            compact = _compact_item(raw)
            if compact:
                items.append(compact)
    return items


def load_graph(output_dir: str) -> dict | None:
    _, _, graph_path = _project_dirs(output_dir)
    try:
        with open(graph_path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("nodes"), list) else None


def summarize_graph(graph: dict | None, top: int = 10) -> dict:
    if not graph:
        return {"nodes": 0, "edges": 0, "languages": [], "layers": [], "top_nodes": []}
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in graph.get("edges", []) if isinstance(e, dict)]
    degree: dict[str, int] = {}
    for edge in edges:
        for end in (edge.get("source"), edge.get("target")):
            if isinstance(end, str):
                degree[end] = degree.get(end, 0) + 1
    ranked = sorted((n for n in nodes if degree.get(str(n.get("id")), 0) > 0),
                    key=lambda n: (-degree.get(str(n.get("id")), 0), str(n.get("name") or n.get("id"))))
    top_nodes = [{"name": str(n.get("name") or n.get("id") or ""), "type": str(n.get("type") or ""),
                  "file": str(n.get("filePath") or "")} for n in ranked[:top]]
    layers = []
    for layer in graph.get("layers", []) or []:
        if not isinstance(layer, dict):
            continue
        members = layer.get("nodeIds") if isinstance(layer.get("nodeIds"), list) else layer.get("files")
        layers.append({"name": str(layer.get("name") or layer.get("id") or "layer"),
                       "files": len(members) if isinstance(members, list) else 0})
    project = graph.get("project") if isinstance(graph.get("project"), dict) else {}
    languages = [str(v) for v in project.get("languages", []) if isinstance(v, str)] if isinstance(project.get("languages"), list) else []
    return {"nodes": len(nodes), "edges": len(edges), "languages": languages[:12],
            "layers": layers, "top_nodes": top_nodes}


def _state_ran_at(output_dir: str) -> float | None:
    try:
        with open(os.path.join(state_root(), output_dir + ".json"), encoding="utf-8") as fh:
            value = json.load(fh)
        return parse_time(value.get("ran_at")) if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _keyfile_tiers(output_dir: str) -> dict:
    try:
        with open(os.path.join(state_root(), output_dir + ".keyfiles.json"), encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    tiers = value.get("tiers") if isinstance(value, dict) else None
    return {k: int(v) for k, v in tiers.items() if k in TIERS and isinstance(v, int)} if isinstance(tiers, dict) else {}


def _cache_path(project_id: str, kind: str = "meta") -> str:
    suffix = ".json" if kind == "meta" else ".items.json"
    return os.path.join(cache_dir(), project_id + suffix)


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def compute_cache(record: dict, *, active: bool = False, force: bool = False) -> dict:
    """Stats for one project, cached by output signature.

    Two files per project: ``<id>.json`` (small: signature, stats, tiers,
    graph summary) and ``<id>.items.json`` (the compact item index used by
    digest/activity/ask).  While a job is writing outputs the signature
    changes constantly; the cache is then reused for up to a minute instead
    of re-reading every item on each request.
    """
    output_dir = record.get("output_dir") or record["project_id"]
    cached = _read_json(_cache_path(record["project_id"]))
    if not isinstance(cached, dict) or cached.get("schema") != CACHE_SCHEMA:
        cached = None
    signature = output_signature(output_dir)
    if cached and not force:
        if cached.get("signature") == signature:
            return cached
        if active and time.time() - float(cached.get("computed_epoch") or 0) < _ACTIVE_RECOMPUTE_SECONDS:
            return cached
    items = read_items(output_dir)
    graph_sig = _stat_sig(_project_dirs(output_dir)[2])
    if cached and cached.get("graph_signature") == graph_sig and isinstance(cached.get("graph"), dict):
        graph = cached["graph"]
    else:
        graph = summarize_graph(load_graph(output_dir))
    tiers = empty_tiers()
    for item in items:
        if item["tier"]:
            tiers[item["tier"]] += 1
    if not any(tiers.values()):
        tiers.update(_keyfile_tiers(output_dir))
    analyzed = [item["analyzed_at"] for item in items if item["analyzed_at"]]
    analyzed_at = max(analyzed) if analyzed else _state_ran_at(output_dir)
    if analyzed_at is None and graph["nodes"]:
        try:
            analyzed_at = os.path.getmtime(_project_dirs(output_dir)[2])
        except OSError:
            analyzed_at = None
    value = {
        "schema": CACHE_SCHEMA, "signature": signature, "graph_signature": graph_sig,
        "computed_epoch": time.time(),
        "stats": {"files": len(items), "summarized": sum(1 for item in items if item["purpose"]),
                  "nodes": graph["nodes"], "edges": graph["edges"], "languages": graph["languages"]},
        "tiers": tiers,
        "embedded_roots": sorted({item["embedded"] for item in items if item["embedded"]}),
        "analyzed_at": iso_from_epoch(analyzed_at),
        "graph": graph,
    }
    with contextlib.suppress(OSError):
        _atomic_write_json(_cache_path(record["project_id"], "items"),
                           {"schema": CACHE_SCHEMA, "signature": signature, "items": items})
        _atomic_write_json(_cache_path(record["project_id"]), value)
    value["_items"] = items
    return value


def project_items(record: dict, *, active: bool = False) -> tuple[dict, list[dict]]:
    """(meta, compact items) for a project, refreshing the cache if needed."""
    meta = compute_cache(record, active=active)
    if "_items" in meta:
        return meta, meta.pop("_items")
    stored = _read_json(_cache_path(record["project_id"], "items"))
    if isinstance(stored, dict) and stored.get("signature") == meta.get("signature") and isinstance(stored.get("items"), list):
        return meta, stored["items"]
    meta = compute_cache(record, force=True)
    return meta, meta.pop("_items", [])


def has_outputs(record: dict) -> bool:
    stats = record.get("stats") or {}
    return bool(stats.get("files") or stats.get("nodes"))


def derive_status(record: dict, job: dict | None, *, now: float | None = None) -> str:
    """Status from the latest job state plus output presence and freshness."""
    job_status = (job or {}).get("status")
    if job_status == "queued":
        return "queued"
    if job_status == "running":
        return "analyzing"
    analyzed_at = parse_time(record.get("analyzed_at"))
    if job_status == "failed":
        finished = parse_time((job or {}).get("finished_at"))
        if not has_outputs(record) or analyzed_at is None or (finished and finished >= analyzed_at):
            return "failed"
    if not has_outputs(record):
        return "not_analyzed"
    try:
        stale_days = float(os.environ.get("UYP_PROJECT_STALE_DAYS", "14"))
    except ValueError:
        stale_days = 14.0
    reference = now if now is not None else time.time()
    if analyzed_at is not None and stale_days > 0 and reference - analyzed_at > stale_days * 86400:
        return "stale"
    return "analyzed"


# ---------------------------------------------------------------- import --
def _output_dirs() -> list[str]:
    """Output/state directories that hold analysis results."""
    names = set()
    root = output_root()
    with contextlib.suppress(OSError):
        for name in os.listdir(root):
            if safe_component(name) and glob.glob(os.path.join(glob.escape(os.path.join(root, name)), "*.knowledge.json")):
                names.add(name)
    state = state_root()
    with contextlib.suppress(OSError):
        for name in os.listdir(state):
            if safe_component(name) and os.path.isfile(os.path.join(state, name, "ua", "knowledge-graph.json")):
                names.add(name)
    return sorted(names)


def _recorded_grant(output_dir: str) -> str | None:
    for path in (os.path.join(state_root(), output_dir + ".json"),
                 os.path.join(state_root(), output_dir, "ua", "connector-manifest.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                value = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        grant = value.get("grant") if isinstance(value, dict) else None
        if isinstance(grant, str) and grant.strip():
            return grant.strip()
    return None


def sync_registry(registry: ProjectRegistry | None = None, *, jobs_by_project: dict | None = None,
                  grants: list[dict] | None = None, use_connector: bool = True) -> dict:
    """Import analyzed outputs, backfill paths, refresh cached stats/status.

    Returns the saved registry document.  Never raises for a missing
    connector: paths simply stay empty until the connector is reachable.
    """
    registry = registry or ProjectRegistry()
    jobs_by_project = jobs_by_project or {}
    dirs = _output_dirs()
    with registry.edit() as doc:
        known_dirs = {r.get("output_dir") or r["project_id"] for r in doc["projects"]}
        missing = [name for name in dirs if name not in known_dirs]
        needs_paths = bool(missing) or any(not r.get("path") for r in doc["projects"])
        if grants is None and needs_paths and use_connector:
            grants = cached_connector_grants()
        grant_paths = {str(g["id"]): str(g["path"]) for g in (grants or [])}
        for name in missing:
            grant_id = _recorded_grant(name)
            path = grant_paths.get(grant_id or "")
            if not path and grants:
                # No grant recorded: a unique basename match is still reliable.
                candidates = [g for g in grants if posixpath.basename(str(g["path"])) == name]
                if len(candidates) == 1:
                    path, grant_id = str(candidates[0]["path"]), str(candidates[0]["id"])
            project_id = allocate_project_id(doc, name, None, path)
            doc["projects"].append(new_record(project_id, root_name=name, path=path, device_id=None,
                                              output_dir=name, grant_id=grant_id, origin="import"))
        for record in doc["projects"]:
            if not record.get("device_id"):
                record["device_id"] = connector_device_id()
            if not record.get("path") and record.get("grant_id") in grant_paths:
                record["path"] = grant_paths[record["grant_id"]]
            job = jobs_by_project.get(record["project_id"])
            active = (job or {}).get("status") in {"queued", "running"}
            cache = compute_cache(record, active=active)
            cache.pop("_items", None)
            record["stats"], record["tiers"] = cache["stats"], cache["tiers"]
            record["embedded_roots"], record["analyzed_at"] = cache["embedded_roots"], cache["analyzed_at"]
            record["signature"] = cache["signature"]
            record["status"] = derive_status(record, job)
    return doc


# ------------------------------------------------------------- projection --
def visible(context: dict | None, record: dict) -> bool:
    """HomeHub scope check: project AND source capability must be granted."""
    if not context:
        return False
    project_id = record["project_id"]
    projects = {str(v) for v in context.get("projectScopes", [])}
    sources = {str(v) for v in context.get("sourceScopes", [])}
    project_ok = "*" in projects or project_id in projects or f"project:{project_id}" in projects
    source_ok = ("*" in sources or f"connector:{project_id}" in sources
                 or f"connector:{record.get('root_name')}" in sources)
    return project_ok and source_ok


def public_record(doc: dict, record: dict, visible_ids: set[str], status: str | None = None) -> dict:
    """The §6.2 project shape; relations limited to what the caller may see."""
    parent = record.get("parent_id")
    stats = record.get("stats") or empty_stats()
    tiers = record.get("tiers") or empty_tiers()
    return {
        "project_id": record["project_id"],
        "device_id": effective_device(doc, record),
        "root_name": record.get("root_name") or record["project_id"],
        "path": record.get("path") or "",
        "parent_id": parent if parent in visible_ids else None,
        "children": [c for c in record.get("children", []) if c in visible_ids],
        "status": status or record.get("status") or "not_analyzed",
        "analyzed_at": record.get("analyzed_at"),
        "stats": {"files": int(stats.get("files") or 0), "summarized": int(stats.get("summarized") or 0),
                  "nodes": int(stats.get("nodes") or 0), "edges": int(stats.get("edges") or 0),
                  "languages": list(stats.get("languages") or [])},
        "tiers": {tier: int(tiers.get(tier) or 0) for tier in TIERS},
        "embedded_roots": list(record.get("embedded_roots") or []),
    }


def build_tree(projects: list[dict]) -> list[dict]:
    ids = {p["project_id"] for p in projects}
    by_parent: dict[str | None, list[str]] = {}
    for project in projects:
        parent = project["parent_id"] if project["parent_id"] in ids else None
        by_parent.setdefault(parent, []).append(project["project_id"])

    def node(project_id: str, seen: frozenset) -> dict:
        kids = [k for k in sorted(by_parent.get(project_id, [])) if k not in seen]
        return {"project_id": project_id, "children": [node(k, seen | {k}) for k in kids]}

    return [node(pid, frozenset({pid})) for pid in sorted(by_parent.get(None, []))]
