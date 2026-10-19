#!/usr/bin/env python3
"""KnowledgeVersion -> gBrain publisher (namespace: project_knowledge).

Design contract (docs/AGENTFLOW_ARCHITECTURE.md section 4): project knowledge
eventually mirrors into the existing gBrain foundation under its own
namespace, isolated from family/conversation memories, and a revocation must
invalidate what was published.

Discovered write surface (Jetson audit 2026-10-10):

  knowledge-service :8790 is a READ facade -- POST /query, /synthesize,
  /permissions[/grant|/revoke] (brain_grants SQLite rows), GET /health.
  It has no page-write endpoint, so a publisher cannot talk to :8790.

  The real ingest surface is a resident `gbrain serve` per brain speaking
  MCP streamable-HTTP (the same protocol as ~/jarvis/gbrain/mcp_ingest.py):
    POST <base>/token   OAuth2 client_credentials (writer creds json with
                        client_id/client_secret; bearer tokens live ~1h)
    POST <base>/mcp     JSON-RPC tools/call, Accept: application/json,
                        text/event-stream (responses may be SSE; unwrap
                        ``data: ``).  A REJECTED call still returns HTTP 200
                        with result.isError=true and the error payload nested
                        in result.content[0].text (2026-09-27 family-brain
                        quota lesson: those must be read as failures).
  Relevant tools: ``put_page {slug, content, force, request_id}`` (content is
  the COMPLETE markdown page with YAML frontmatter; force upserts; a reused
  request_id makes transport retries idempotent), ``delete_page {slug, force,
  request_id}`` (soft-delete: hidden from search/get_page/list_pages, 72h
  recovery, purge is trusted-local-CLI only), ``query``/``search``/``get_page``
  for reads.

  Production caution: gbrain 0.51+ serves enforce a per-principal
  receipt-byte quota and the family-brain writer at 127.0.0.1:3141 is already
  exhausted (refresh_brains.sh 2026-09-27).  A live publish therefore needs a
  DEDICATED project_knowledge brain + serve + fresh writer principal.  This
  module deliberately has NO default endpoint: dry_run is the default and a
  live publish requires an explicit --url/--creds (UYP_GBRAIN_URL /
  UYP_GBRAIN_CREDS), so nothing can accidentally write to the family brain.
  check() (CLI: ``check``) validates a freshly provisioned serve WITHOUT
  touching real payload: it lists the principal's tool surface and, only when
  put_page AND delete_page are both visible, does one tiny put+delete
  round-trip on the project_knowledge/__probe__ slug (a few receipt bytes --
  the same signal the family timer burned, but bounded and cleaned up) to
  prove quota headroom end to end.

Namespace layout (one gbrain page per KnowledgeItem):

  project_knowledge/<project_id>/<grant_epoch>/<relpath...>
  project_knowledge/<project_id>/<grant_epoch>/__manifest__

The grant epoch is part of the slug on purpose -- it is the
revocation-invalidating key part.  A re-grant (new epoch) publishes into a
NEW subtree and never aliases onto an older grant's pages, and revoke()
targets exactly one epoch's subtree.  The KnowledgeVersion travels in every
page's ``uyp_*`` frontmatter (uyp_version, uyp_grant_epoch, ...) so a
reader can prefilter by version/epoch before trusting a hit.  The manifest
page is written LAST: an interrupted publish never leaves a complete-version
marker behind.

Known gaps (documented, not hidden):
  - delete_page is NOT in the starter tool surface; the writer principal
    must be granted it, otherwise revoke() falls back to a tombstone
    manifest (uyp_revoked: true) and reports the per-slug gap.
  - list_pages has no slug-prefix filter, so an epoch's pages cannot be
    enumerated remotely; revoke() needs the local knowledge_root (or an
    explicit slug list) that produced them.
  - Soft-deleted pages stay recoverable for 72h (purge is CLI-only); a
    hard-erasure revocation must be run on the Jetson with the CLI.

Slug rules mirrored from gbrain (src/core/ops/context.ts validatePageSlug):
/ -separated segments, each starting with a word character (any script) or
underscore, continuing with ``.`` ``_`` ``-``; whole slug <= 255 chars.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

NAMESPACE = "project_knowledge"
MANIFEST_SEGMENT = "__manifest__"
PROBE_SLUG = NAMESPACE + "/__probe__"
INGESTED_VIA = "uyp-gbrain-publisher/1.0"
SLUG_MAX = 255
TOKEN_MARGIN_SECONDS = 120.0

# A publish to UYP is a local, durable fact.  Mirroring that fact into gBrain
# is deliberately a second, asynchronous lane: a slow or unavailable gBrain
# serve must never make the IndexJob report a failed local publish.  These
# records live below the UYP state root and contain no bearer credentials or
# HomeHub context.
MIRROR_SCHEMA_VERSION = "1.0"
MIRROR_PHASES = {"queued", "running", "retry_wait", "succeeded", "failed",
                 "blocked", "terminal_expired"}
# ADR (docs/ADR_MIRROR_EPOCH.md, adopted 2026-10-19): a
# ``homehub_grant_epoch_mismatch`` denial is EXPECTED grant-epoch
# rotation noise (the global epoch advances on every create/revoke
# across all projects, ~12-14/day), not a policy problem.  Such records
# move to ``terminal_expired`` - audit chain preserved (record file,
# events, lastError), never retried, never re-enqueued.  The REAL
# policy denials (scope narrowed / never granted / missing epoch) stay
# ``blocked`` so operators still see them.
MISMATCH_DENIAL = "homehub_grant_epoch_mismatch"
MIRROR_MAX_ATTEMPTS = 3
MIRROR_RETRY_BACKOFF_SECONDS = 60


class GbrainPublishError(RuntimeError):
    """A publisher precondition failed (bad input, missing endpoint)."""


class GbrainRejectedError(RuntimeError):
    """The serve rejected a tool call (result.isError or JSON-RPC error)."""

    def __init__(self, tool: str, slug: str, reason: str):
        super().__init__(f"{tool} rejected for {slug}: {reason}")
        self.tool = tool
        self.slug = slug
        self.reason = reason


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mirror_safe_component(value: Any, label: str = "mirror id") -> str:
    """Validate one durable mirror id without importing IndexJob internals."""
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise GbrainPublishError(f"unsafe {label}: {value!r}")
    return text


def mirror_job_id(index_job_id: str) -> str:
    """Return a stable queue id for one IndexJob publication.

    The id is a digest rather than the raw job id so a future caller cannot
    accidentally turn an imported job id containing path separators into a
    filename.  Re-running the same IndexJob therefore reuses one mirror
    record instead of creating duplicate remote pages.
    """
    raw = _mirror_safe_component(index_job_id, "index job id")
    return "mirror-" + hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def _mirror_retry_at(attempt: int, *, stamp: datetime | None = None) -> str:
    stamp = stamp or datetime.now(timezone.utc)
    seconds = MIRROR_RETRY_BACKOFF_SECONDS * (2 ** max(int(attempt) - 1, 0))
    return (stamp + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _mirror_due(record: dict[str, Any], stamp: datetime) -> bool:
    phase = str(record.get("phase") or "")
    if phase == "queued":
        return True
    if phase != "retry_wait":
        return False
    raw = str(record.get("nextAttemptAt") or "")
    if not raw:
        return True
    try:
        due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due <= stamp


class MirrorJobStore:
    """Small durable queue for post-publish gBrain mirror attempts.

    This store is intentionally independent of HomeHub and IndexJob state:
    it records an *attempt* to mirror an already published local version. A
    failure here is observable and retryable, but cannot change the local
    KnowledgeVersion or its UA graph. The worker that calls ``run_pending``
    must supply an explicitly provisioned project-knowledge gBrain endpoint;
    no endpoint or credentials are persisted in these records.
    """

    def __init__(self, state_root: str | os.PathLike[str]):
        self.root = Path(os.path.expanduser(str(state_root))).resolve()
        self.directory = self.root / "gbrain-mirrors"
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, mirror_id: str) -> Path:
        return self.directory / f"{_mirror_safe_component(mirror_id)}.json"

    @staticmethod
    def _write_atomic(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def get(self, mirror_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(mirror_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GbrainPublishError(f"gBrain mirror job not found: {mirror_id}") from exc

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def update(self, mirror_id: str, **fields: Any) -> dict[str, Any]:
        record = self.get(mirror_id)
        record.update(fields)
        record["updatedAt"] = now_iso()
        self._write_atomic(self._path(mirror_id), record)
        return record

    def event(self, mirror_id: str, phase: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        if phase not in MIRROR_PHASES:
            raise GbrainPublishError(f"unknown gBrain mirror phase: {phase}")
        record = self.get(mirror_id)
        record["phase"] = phase
        record["updatedAt"] = now_iso()
        if details:
            for key, value in details.items():
                if key not in {"phase", "events"}:
                    record[key] = value
        record["events"] = int(record.get("events", 0)) + 1
        self._write_atomic(self._path(mirror_id), record)
        return record

    def enqueue(self, *, index_job_id: str, project_id: str, knowledge_root: str,
                source_id: str | None = None,
                version: str, source_epoch: str | None, grant_epoch: str | None,
                published_at: str | None = None, mirror_id: str | None = None) -> dict[str, Any]:
        """Create or refresh one queued mirror record idempotently.

        A missing grant epoch blocks only the mirror lane. It is not invented
        from the local version, because the grant epoch is the revocation key
        and must remain supplied by the authorized IndexJob.
        """
        mirror_id = _mirror_safe_component(mirror_id or mirror_job_id(index_job_id))
        existing_path = self._path(mirror_id)
        if existing_path.exists():
            existing = self.get(mirror_id)
            if str(existing.get("knowledgeVersion")) == str(version) and str(existing.get("grantEpoch")) == str(grant_epoch):
                return existing
        stamp = now_iso()
        record: dict[str, Any] = {
            "schemaVersion": MIRROR_SCHEMA_VERSION,
            "mirrorJobId": mirror_id,
            "indexJobId": _mirror_safe_component(index_job_id, "index job id"),
            "projectId": str(project_id),
            # Source capability is retained so a worker can re-check both
            # HomeHub project and connector scopes after a revoke.  It is an
            # opaque ID, never a source path or token.
            "sourceId": str(source_id).strip() if source_id is not None and str(source_id).strip() else None,
            # Needed by the worker, but never copied into Studio's public
            # projection. This is a local path, not a source-byte payload.
            "knowledgeRoot": str(Path(os.path.expanduser(str(knowledge_root))).resolve()),
            "knowledgeVersion": str(version),
            "sourceEpoch": str(source_epoch) if source_epoch is not None else None,
            "grantEpoch": str(grant_epoch) if grant_epoch is not None else None,
            "publishedAt": published_at or stamp,
            "phase": "queued" if str(grant_epoch or "").strip() else "blocked",
            "attempts": 0,
            "maxAttempts": MIRROR_MAX_ATTEMPTS,
            "nextAttemptAt": None,
            "lastError": None,
            "createdAt": stamp,
            "updatedAt": stamp,
            "events": 0,
        }
        if record["phase"] == "blocked":
            record["lastError"] = "grant_epoch_missing"
        self._write_atomic(existing_path, record)
        return record


def enqueue_mirror(*, state_root: str | os.PathLike[str], index_job_id: str,
                   project_id: str, knowledge_root: str, version: str,
                   source_id: str | None = None,
                   source_epoch: str | None, grant_epoch: str | None,
                   published_at: str | None = None) -> dict[str, Any]:
    """Queue a post-publish mirror without doing network I/O."""
    return MirrorJobStore(state_root).enqueue(
        index_job_id=index_job_id, project_id=project_id, knowledge_root=knowledge_root,
        source_id=source_id,
        version=version, source_epoch=source_epoch, grant_epoch=grant_epoch,
        published_at=published_at)


def mirror_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Return a Studio-safe status projection (no local paths or credentials)."""
    result: dict[str, Any] = {}
    for key in ("mirrorJobId", "indexJobId", "projectId", "sourceId", "knowledgeVersion",
                "sourceEpoch", "grantEpoch", "publishedAt", "phase",
                "attempts", "maxAttempts", "nextAttemptAt", "lastError",
                "createdAt", "updatedAt"):
        if key in record and record[key] is not None:
            result[key] = record[key]
    return result


def _slug_segment(value: Any, label: str) -> str:
    """Sanitize one value into a legal gbrain slug segment.

    gbrain allows word characters from any script plus a leading underscore,
    with ``.`` ``_`` ``-`` as continuation characters.  Anything else (spaces,
    ``@``, ``:``, parentheses, ...) becomes ``_`` so the mapping is
    deterministic; collisions are caught later instead of silently merging
    two different files onto one page.
    """
    raw = str(value or "").strip()
    if not raw:
        raise GbrainPublishError(f"empty {label} cannot become a slug segment")
    chars: list[str] = []
    for index, char in enumerate(raw):
        if char.isalnum() or char == "_" or (index > 0 and char in "._-"):
            chars.append(char)
        else:
            chars.append("_")
    segment = "".join(chars)
    if len(segment) > SLUG_MAX:
        raise GbrainPublishError(f"{label} segment exceeds {SLUG_MAX} chars: {segment[:60]}...")
    return segment


def entry_slug(project_id: str, grant_epoch: Any, relpath: str) -> str:
    """project_knowledge/<project>/<epoch>/<relpath...> for one KnowledgeItem."""
    parts = [NAMESPACE, _slug_segment(project_id, "project id"), _slug_segment(grant_epoch, "grant epoch")]
    parts.extend(_slug_segment(segment, "relpath segment") for segment in str(relpath).split("/"))
    slug = "/".join(parts)
    # gbrain >= 0.60 stores pages at <slug>.md and rejects slugs that already
    # end in .md/.mdx (invalid_params). Drop the source extension; revocation
    # derives slugs through this same function, so the mapping stays 1:1.
    if slug.lower().endswith((".md", ".mdx")):
        slug = slug.rsplit(".", 1)[0]
    if len(slug) > SLUG_MAX:
        raise GbrainPublishError(f"slug exceeds gbrain's {SLUG_MAX}-char limit ({len(slug)} chars): {slug[:80]}...")
    return slug


def manifest_slug(project_id: str, grant_epoch: Any) -> str:
    return "/".join([NAMESPACE, _slug_segment(project_id, "project id"),
                     _slug_segment(grant_epoch, "grant epoch"), MANIFEST_SEGMENT])


def _yaml_scalar(value: Any) -> str:
    """Serialize one frontmatter value; JSON strings are valid YAML scalars."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _page(front: dict[str, Any], body: str) -> str:
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_scalar(value)}" for key, value in front.items())
    lines.extend(["---", ""])
    return "\n".join(lines) + body.rstrip("\n") + "\n"


def load_items(knowledge_root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Load the KnowledgeItems of one published project directory.

    A corrupt item aborts the whole publish: shipping a half-read tree with a
    complete manifest would claim coverage the version does not have.
    """
    root = Path(os.path.expanduser(str(knowledge_root)))
    if not root.is_dir():
        raise GbrainPublishError(f"knowledge root not found: {root}")
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.knowledge.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GbrainPublishError(f"unreadable KnowledgeItem {path.name}: {exc}") from exc
        if not str(item.get("file", "")).strip():
            raise GbrainPublishError(f"KnowledgeItem missing file relpath: {path.name}")
        items.append(item)
    return items


def build_page(item: dict[str, Any], *, project_id: str, version: str,
               grant_epoch: str, published_at: str | None = None,
               source_epoch: str | None = None) -> dict[str, Any]:
    """Render one KnowledgeItem as a gbrain page (slug + markdown + metadata)."""
    relpath = str(item.get("file", "")).strip()
    slug = entry_slug(project_id, grant_epoch, relpath)
    derived = item.get("derived") if isinstance(item.get("derived"), dict) else {}
    front = {
        "type": "note",
        "uyp_namespace": NAMESPACE,
        "uyp_project": project_id,
        "uyp_grant_epoch": str(grant_epoch),
        "uyp_version": str(version),
        "uyp_relpath": relpath,
        "uyp_verdict": str(item.get("verdict", "")),
        "uyp_published_at": published_at or now_iso(),
        "uyp_revoked": False,
    }
    if source_epoch is not None:
        front["uyp_source_epoch"] = str(source_epoch)
    # ``anchor_top`` is the stable evidence cursor emitted by the local
    # KnowledgeItem builder. It lets gBrain results point back to an evidence
    # range without copying source bytes into the page.
    anchor_top = item.get("anchor_top")
    if anchor_top is not None and str(anchor_top).strip():
        front["uyp_evidence_anchor"] = str(anchor_top)
    lines = [f"# {project_id}: {relpath}", ""]
    lines.append(f"verdict: {item.get('verdict', '')} (think gate {item.get('think_gate', '')})")
    lines.append("")
    if source_epoch is not None:
        lines.append(f"- Source epoch: {source_epoch}")
    if anchor_top is not None and str(anchor_top).strip():
        lines.append(f"- Evidence anchor: {anchor_top}")
    purpose = str(derived.get("purpose", "")).strip()
    if purpose:
        lines.append(f"- Purpose: {purpose}")
    for point in [str(x) for x in (derived.get("key_points") or [])][:5]:
        lines.append(f"- Key point: {point}")
    for component in [str(x) for x in (derived.get("components") or [])][:5]:
        lines.append(f"- Component: {component}")
    for dependency in [str(x) for x in (derived.get("depends_on") or [])][:5]:
        lines.append(f"- Depends on: {dependency}")
    if "lines" in derived or "py_defs" in derived or "imports" in derived:
        lines.append("- Structure: {lines} lines, {py_defs} py defs, {imports} imports".format(
            lines=derived.get("lines", "?"), py_defs=derived.get("py_defs", "?"),
            imports=derived.get("imports", "?")))
        if derived.get("too_large"):
            lines.append("- Source was too large to read through the connector (metadata only).")
    if not derived:
        lines.append(f"- (no derived summary; verdict {item.get('verdict', '')})")
    return {"slug": slug, "content": _page(front, "\n".join(lines) + "\n"), "relpath": relpath}


def build_manifest(project_id: str, grant_epoch: str, *, version: str,
                   entries: list[dict[str, Any]], published_at: str | None = None,
                   revoked: bool = False, revoked_at: str | None = None,
                   source_epoch: str | None = None) -> dict[str, Any]:
    """The per-epoch marker page: version manifest in life, tombstone after revoke."""
    front = {
        "type": "note",
        "uyp_namespace": NAMESPACE,
        "uyp_project": project_id,
        "uyp_grant_epoch": str(grant_epoch),
        "uyp_version": str(version),
        "uyp_entry_count": len(entries),
        "uyp_published_at": published_at or now_iso(),
        "uyp_revoked": revoked,
    }
    if source_epoch is not None:
        front["uyp_source_epoch"] = str(source_epoch)
    if revoked:
        front["uyp_revoked_at"] = revoked_at or now_iso()
    lines = [f"# {NAMESPACE} manifest: {project_id} @ {grant_epoch}", ""]
    if revoked:
        lines.append(f"REVOKED: the grant epoch behind these pages was revoked. "
                     f"Every page under {NAMESPACE}/{project_id}/{grant_epoch}/ "
                     "must be treated as stale.")
        lines.append("")
    lines.append(f"KnowledgeVersion: {version}")
    lines.append(f"Entries: {len(entries)}")
    lines.append("")
    lines.extend(f"- {entry['slug']}" for entry in entries)
    return {"slug": manifest_slug(project_id, grant_epoch), "content": _page(front, "\n".join(lines) + "\n")}


def _reject_slug_collisions(entries: list[dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for entry in entries:
        previous = seen.get(entry["slug"])
        if previous is not None:
            raise GbrainPublishError(
                f"slug collision after sanitization: {entry['slug']} "
                f"({previous} vs {entry['relpath']})")
        seen[entry["slug"]] = entry["relpath"]


def _request_id(kind: str, slug: str, content: str = "") -> str:
    """Deterministic put/delete receipt id: identical intent -> identical id.

    gbrain receipts are idempotent per request_id, so a transport retry of
    the SAME page content replays safely while changed content (a different
    intent) gets a fresh id.
    """
    digest = hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"uyp/{kind}/{slug}/{digest}"))


def _put_page_with_fresh_retry(active: Any, entry: dict[str, Any]) -> None:
    """put_page one plan entry; a burned request_id gets one fresh retry.

    The deterministic request_id is correct for transport replays of a
    committed write, but a request_id that was previously REJECTED (e.g.
    during the 0.59 quota outage) is burned on the serve and replays as
    invalid_params forever. Retry once with a salted id; a genuinely invalid
    request still fails on the second attempt.
    """
    payload = {
        "slug": entry["slug"],
        "content": entry["content"],
        "force": True,
        "ingested_via": INGESTED_VIA,
        "request_id": _request_id("put", entry["slug"], entry["content"]),
    }
    try:
        active.call("put_page", payload)
    except GbrainRejectedError as exc:
        if "invalid_params" not in str(exc.reason):
            raise
        payload["request_id"] = str(uuid.uuid5(
            uuid.NAMESPACE_URL, payload["request_id"] + "/retry/" + uuid.uuid4().hex))
        active.call("put_page", payload)


class McpServeClient:
    """Minimal MCP streamable-HTTP client for one gbrain serve.

    Mirrors the production writer path (mcp_ingest.py / McpBrain): OAuth2
    client_credentials at <base>/token, JSON-RPC tools/call at <base>/mcp,
    SSE-or-JSON responses, and the 2026-09-27 failure rule that a rejection
    arrives as HTTP 200 with result.isError=true.
    """

    def __init__(self, base_url: str, creds: dict[str, Any] | str | os.PathLike[str], timeout: float = 30.0):
        if not str(base_url or "").strip():
            raise GbrainPublishError("gbrain serve base URL is required")
        self.base = str(base_url).rstrip("/")
        self.url = self.base + "/mcp"
        self.timeout = timeout
        if isinstance(creds, dict):
            self.creds = creds
        else:
            path = Path(os.path.expanduser(str(creds)))
            try:
                self.creds = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GbrainPublishError(f"unreadable gbrain writer creds {path}: {exc}") from exc
        if not (self.creds.get("client_id") and self.creds.get("client_secret")):
            raise GbrainPublishError("gbrain writer creds need client_id and client_secret")
        self._token = ""
        self._token_expires = 0.0

    def _bearer(self) -> str:
        if self._token and time.time() < self._token_expires - TOKEN_MARGIN_SECONDS:
            return self._token
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.creds["client_id"],
            "client_secret": self.creds["client_secret"],
        }).encode()
        request = urllib.request.Request(
            self.base + "/token", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode())
        self._token = str(payload["access_token"])
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    def _post_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """One JSON-RPC round-trip; unwraps SSE and raises on RPC-level errors."""
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params}).encode()
        request = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self._bearer(),
            "User-Agent": INGESTED_VIA,
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode()
        if raw.startswith("event"):
            raw = raw.split("data: ", 1)[1]
        envelope = json.loads(raw)
        if "error" in envelope:
            raise GbrainRejectedError(str(params.get("name", "") or method),
                                      str(params.get("name", "")),
                                      str(envelope["error"])[:200])
        return envelope.get("result") or {}

    def list_tools(self) -> list[str]:
        """The principal's honest tool surface (JSON-RPC tools/list)."""
        result = self._post_rpc("tools/list", {})
        return sorted(str(tool.get("name", "")) for tool in (result.get("tools") or []))

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._post_rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            reason = str(result.get("content"))[:200]
            try:
                payload = json.loads((result.get("content") or [{}])[0].get("text", "{}"))
                reason = str(payload.get("error", payload))[:200]
            except (ValueError, IndexError, AttributeError):
                pass
            raise GbrainRejectedError(tool, str(arguments.get("slug", "")), reason)
        return result


def _client_from(base_url: str | None, creds: Any) -> McpServeClient:
    """Build a live client; the missing-endpoint error is a safety feature."""
    url = str(base_url or os.environ.get("UYP_GBRAIN_URL") or "").strip()
    if not url:
        raise GbrainPublishError(
            "live publish requires --url/UYP_GBRAIN_URL: there is no default "
            "endpoint on purpose, so the production family serve and :8790 "
            "can never be written by accident")
    source = creds or os.environ.get("UYP_GBRAIN_CREDS")
    if not source:
        raise GbrainPublishError("live publish requires --creds/UYP_GBRAIN_CREDS (writer OAuth creds)")
    return McpServeClient(url, source)


def publish(knowledge_root: str | os.PathLike[str], project_id: str, version: str,
            grant_epoch: str, dry_run: bool = True, *,
            base_url: str | None = None, creds: Any = None,
            client: McpServeClient | None = None,
            log: Callable[[str], None] = print,
            published_at: str | None = None,
            source_epoch: str | None = None) -> dict[str, Any]:
    """Mirror one KnowledgeVersion into gbrain under project_knowledge.

    dry_run (the default) builds the full payload plan and prints it without
    any network I/O.  A live publish put_page's every item first and the
    manifest LAST, so an interrupted run never advertises a complete version.
    Pinning ``published_at`` makes a retry of the same version byte-identical,
    which keeps the derived put_page request_id (and therefore the serve-side
    receipt) stable across replays.
    """
    if not str(version or "").strip():
        raise GbrainPublishError("version (KnowledgeVersion) is required")
    if not str(grant_epoch or "").strip():
        raise GbrainPublishError("grant_epoch is required: it is the revocation key")
    items = load_items(knowledge_root)
    published_at = published_at or now_iso()
    entries = [build_page(item, project_id=project_id, version=version,
                          grant_epoch=grant_epoch, published_at=published_at,
                          source_epoch=source_epoch)
               for item in items]
    _reject_slug_collisions(entries)
    manifest = build_manifest(project_id, grant_epoch, version=version,
                              entries=entries, published_at=published_at,
                              source_epoch=source_epoch)
    plan = entries + [manifest]
    total_bytes = sum(len(entry["content"].encode("utf-8", "surrogatepass")) for entry in plan)
    endpoint = (client.base if client is not None
                else str(base_url or os.environ.get("UYP_GBRAIN_URL") or "") or None)
    if dry_run:
        log(f"gbrain publish DRY RUN: {len(entries)} items + manifest, "
            f"{total_bytes} bytes, namespace {NAMESPACE}/{project_id}/{grant_epoch}")
        log(f"endpoint: {endpoint or '(none configured)'}")
        for entry in plan:
            log(f"  PUT {entry['slug']} ({len(entry['content'].encode('utf-8', 'surrogatepass'))} bytes)")
        return {
            "dryRun": True,
            "namespace": NAMESPACE,
            "project": project_id,
            "grantEpoch": str(grant_epoch),
            "version": str(version),
            "entries": len(entries),
            "bytes": total_bytes,
            "manifestSlug": manifest["slug"],
            "manifestWritten": False,
            "endpoint": endpoint,
        }
    active = client if client is not None else _client_from(base_url, creds)
    summary: dict[str, Any] = {
        "dryRun": False,
        "namespace": NAMESPACE,
        "project": project_id,
        "grantEpoch": str(grant_epoch),
        "version": str(version),
        "entries": len(entries),
        "ok": 0,
        "notAttempted": 0,
        "failed": None,
        "manifestSlug": manifest["slug"],
        "manifestWritten": False,
        "endpoint": active.base,
    }
    for index, entry in enumerate(plan):
        is_manifest = index == len(plan) - 1
        try:
            _put_page_with_fresh_retry(active, entry)
        except GbrainRejectedError as exc:
            # Fail fast: without a complete item set the manifest stays
            # unwritten, so no reader can mistake this for a full version.
            summary["failed"] = {"slug": exc.slug, "reason": exc.reason}
            summary["notAttempted"] = len(plan) - index - 1
            summary["manifestWritten"] = False
            return summary
        if is_manifest:
            summary["manifestWritten"] = True
        else:
            summary["ok"] += 1
    return summary


def _mirror_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _mirror_access_denial(record: dict[str, Any], context: dict[str, Any] | None) -> str | None:
    """Return a HomeHub denial reason for one mirror record, if any.

    A mirror is a *projection* of a previously authorized local publication;
    it must not outlive the grant that authorized that publication.  The
    worker supplies a fresh AccessContext issued by HomeHub.  We compare only
    opaque grant/project identifiers here and never mint or extend a grant.
    ``None`` means the record is allowed to proceed.
    """
    if context is None:
        return "homehub_access_context_unavailable"
    try:
        from homehub_adapter import validate_context

        checked = validate_context(context)
    except Exception:
        # An invalid, expired, or explicitly revoked projection is a hard
        # safety boundary.  Treat it uniformly so callers cannot accidentally
        # distinguish a stale grant from an unavailable policy plane.
        return "homehub_access_context_unavailable"
    grant_epoch = str(record.get("grantEpoch") or "").strip()
    if not grant_epoch:
        return "grant_epoch_missing"
    if grant_epoch != str(checked.get("grantEpoch") or ""):
        return "homehub_grant_epoch_mismatch"
    project_id = str(record.get("projectId") or "").strip()
    scopes = {str(value) for value in checked.get("projectScopes", [])}
    if project_id not in scopes and f"project:{project_id}" not in scopes and "*" not in scopes:
        return "homehub_scope_denied"
    source_id = str(record.get("sourceId") or "").strip()
    if not source_id:
        # Records written before source capability pinning cannot be safely
        # mirrored after a policy change.  They remain inspectable and can be
        # re-enqueued by a fresh IndexJob with sourceId attached.
        return "source_scope_missing"
    source_scopes = {str(value) for value in checked.get("sourceScopes", [])}
    if source_id not in source_scopes and f"connector:{source_id}" not in source_scopes and "*" not in source_scopes:
        return "homehub_source_scope_denied"
    return None


def run_mirror_job(record: dict[str, Any], *, state_root: str | os.PathLike[str],
                   base_url: str | None = None, creds: Any = None,
                   client: McpServeClient | None = None,
                   publisher: Callable[..., dict[str, Any]] = publish,
                   log: Callable[[str], None] = print,
                   access_context: dict[str, Any] | None = None,
                   enforce_access_context: bool = False) -> dict[str, Any]:
    """Attempt one queued mirror, recording bounded retry state.

    This function is intended for a separate timer/worker. It is never called
    from ``publish_staged`` or the IndexJob's synchronous local publish path.
    ``publisher`` and ``client`` are injectable so unit tests can exercise the
    state machine without a network.
    """
    mirror_id = _mirror_safe_component(record.get("mirrorJobId"), "mirror job id")
    store = MirrorJobStore(state_root)
    # Re-read the durable record so a worker acting on a stale queue listing
    # cannot overwrite a newer retry or success state.
    current = store.get(mirror_id)
    if current.get("phase") in {"succeeded", "blocked", "terminal_expired"}:
        return current
    if enforce_access_context or access_context is not None:
        denial = _mirror_access_denial(current, access_context)
        if denial:
            return store.event(
                mirror_id,
                "terminal_expired" if denial == MISMATCH_DENIAL else "blocked",
                {
                    "lastError": denial,
                    "blockedBy": "homehub",
                    **({"expiredBy": "grant_epoch_rotation"}
                       if denial == MISMATCH_DENIAL else {}),
                })
    attempts = int(current.get("attempts") or 0) + 1
    current = store.event(mirror_id, "running", {"attempts": attempts, "lastError": None})
    try:
        grant_epoch = str(current.get("grantEpoch") or "").strip()
        if not grant_epoch:
            raise GbrainPublishError("grant_epoch missing from mirror queue record")
        result = publisher(
            current["knowledgeRoot"],
            str(current["projectId"]),
            str(current["knowledgeVersion"]),
            grant_epoch,
            dry_run=False,
            base_url=base_url,
            creds=creds,
            client=client,
            published_at=current.get("publishedAt"),
            source_epoch=current.get("sourceEpoch"),
            log=log,
        )
        if result.get("failed") or not result.get("manifestWritten"):
            raise GbrainRejectedError(
                "put_page", str(result.get("manifestSlug") or "__manifest__"),
                str((result.get("failed") or {}).get("reason") or "manifest_not_written"))
        return store.event(mirror_id, "succeeded", {
            "attempts": attempts,
            "lastError": None,
            "result": {
                "entries": result.get("entries"),
                "bytes": result.get("bytes"),
                "manifestSlug": result.get("manifestSlug"),
            },
        })
    except GbrainPublishError as exc:
        # Missing endpoint/credentials are configuration blockers, not a
        # reason to hammer a timer every minute. A later explicit run can
        # retry once provisioning has been corrected.
        return store.event(mirror_id, "blocked", {
            "attempts": attempts,
            "lastError": _mirror_error(exc),
        })
    except (GbrainRejectedError, OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        error = _mirror_error(exc)
        max_attempts = int(current.get("maxAttempts") or MIRROR_MAX_ATTEMPTS)
        if attempts < max_attempts:
            return store.event(mirror_id, "retry_wait", {
                "attempts": attempts,
                "lastError": error,
                "nextAttemptAt": _mirror_retry_at(attempts),
            })
        return store.event(mirror_id, "failed", {
            "attempts": attempts,
            "lastError": error,
            "nextAttemptAt": None,
        })


def run_pending_mirrors(state_root: str | os.PathLike[str], *, max_jobs: int = 1,
                        base_url: str | None = None, creds: Any = None,
                        client: McpServeClient | None = None,
                        publisher: Callable[..., dict[str, Any]] = publish,
                        now: datetime | None = None,
                        log: Callable[[str], None] = print,
                        access_context: dict[str, Any] | None = None,
                        enforce_access_context: bool = False) -> dict[str, Any]:
    """Run due mirror records once; suitable for a timer or systemd worker."""
    store = MirrorJobStore(state_root)
    stamp = now or datetime.now(timezone.utc)
    due = [record for record in store.list()
           if _mirror_due(record, stamp) and str(record.get("phase")) in {"queued", "retry_wait"}]
    if enforce_access_context and access_context is None:
        # Do not convert a temporary HomeHub transport failure into a
        # permanent mirror failure.  The next timer tick can retry after the
        # policy plane returns; importantly, no remote write is attempted.
        return {
            "ok": True,
            "scheduled": 0,
            "skipped": len(due),
            "jobs": [],
            "reason": "homehub_access_context_unavailable",
        }
    if enforce_access_context or access_context is not None:
        # Revoke/epoch changes are handled before applying max_jobs so stale
        # records cannot occupy the one worker slot forever.  This is a local
        # state transition only; deleting/tombstoning remote pages remains an
        # explicit HomeHub-authorized revoke operation.
        allowed: list[dict[str, Any]] = []
        for record in due:
            denial = _mirror_access_denial(record, access_context)
            if denial:
                try:
                    store.event(
                        str(record["mirrorJobId"]),
                        "terminal_expired" if denial == MISMATCH_DENIAL else "blocked",
                        {
                            "lastError": denial,
                            "blockedBy": "homehub",
                            **({"expiredBy": "grant_epoch_rotation"}
                               if denial == MISMATCH_DENIAL else {}),
                        })
                except (KeyError, GbrainPublishError):
                    pass
            else:
                allowed.append(record)
        due = allowed
    selected = due[:max(0, int(max_jobs))]
    results = [run_mirror_job(record, state_root=state_root, base_url=base_url,
                              creds=creds, client=client, publisher=publisher, log=log,
                              access_context=access_context,
                              enforce_access_context=enforce_access_context)
               for record in selected]
    return {
        "ok": True,
        "scheduled": len(results),
        "skipped": max(0, len(due) - len(results)),
        "jobs": [mirror_projection(record) for record in results],
    }


def revoke(project_id: str, grant_epoch: str, *,
           knowledge_root: str | os.PathLike[str] | None = None,
           slugs: list[str] | None = None,
           dry_run: bool = True, base_url: str | None = None, creds: Any = None,
           client: McpServeClient | None = None,
           log: Callable[[str], None] = print) -> dict[str, Any]:
    """Invalidate one grant epoch's published pages.

    Remote MCP cannot enumerate a slug prefix (list_pages has no such
    filter), so the targets come from the local knowledge_root that produced
    them, or an explicit slug list.  Each target is delete_page'd (soft-delete
    hides it from search/get_page/list_pages); the manifest is then
    overwritten with a uyp_revoked tombstone so even a reader that ignores
    soft-deletes sees the epoch as stale.  If the serve rejects delete_page
    (it is not in the starter surface), the tombstone still lands and the
    per-slug gap is reported instead of hidden.
    """
    if not str(grant_epoch or "").strip():
        raise GbrainPublishError("grant_epoch is required: revocation targets one epoch")
    if slugs is None:
        if knowledge_root is None:
            raise GbrainPublishError(
                "revoke needs knowledge_root or an explicit slug list: the MCP "
                "surface cannot enumerate a slug prefix remotely")
        slugs = [entry_slug(project_id, grant_epoch, str(item.get("file", "")))
                 for item in load_items(knowledge_root)]
    tombstone = build_manifest(project_id, grant_epoch, version="revoked",
                               entries=[], revoked=True)
    endpoint = (client.base if client is not None
                else str(base_url or os.environ.get("UYP_GBRAIN_URL") or "") or None)
    if dry_run:
        log(f"gbrain revoke DRY RUN: {len(slugs)} pages + tombstone, "
            f"namespace {NAMESPACE}/{project_id}/{grant_epoch}")
        log(f"endpoint: {endpoint or '(none configured)'}")
        for slug in slugs:
            log(f"  DELETE {slug}")
        log(f"  PUT {tombstone['slug']} (uyp_revoked: true)")
        return {
            "dryRun": True,
            "namespace": NAMESPACE,
            "project": project_id,
            "grantEpoch": str(grant_epoch),
            "targets": list(slugs),
            "deleted": [],
            "deleteUnsupported": [],
            "tombstoneSlug": tombstone["slug"],
            "tombstoneWritten": False,
            "endpoint": endpoint,
        }
    active = client if client is not None else _client_from(base_url, creds)
    deleted: list[str] = []
    unsupported: list[dict[str, str]] = []
    for slug in slugs:
        try:
            active.call("delete_page", {
                "slug": slug,
                "force": True,
                "request_id": _request_id("delete", slug),
            })
            deleted.append(slug)
        except GbrainRejectedError as exc:
            unsupported.append({"slug": slug, "reason": exc.reason})
    summary: dict[str, Any] = {
        "dryRun": False,
        "namespace": NAMESPACE,
        "project": project_id,
        "grantEpoch": str(grant_epoch),
        "targets": list(slugs),
        "deleted": deleted,
        "deleteUnsupported": unsupported,
        "tombstoneSlug": tombstone["slug"],
        "tombstoneWritten": False,
        "endpoint": active.base,
    }
    try:
        _put_page_with_fresh_retry(active, tombstone)
        summary["tombstoneWritten"] = True
    except GbrainRejectedError as exc:
        summary["failed"] = {"slug": exc.slug, "reason": exc.reason}
    return summary


def _probe_page() -> str:
    return _page({"type": "note", "uyp_namespace": NAMESPACE, "uyp_probe": True},
                 "# uyp publisher probe\n\nTemporary credentials/quota probe written by "
                 "gbrain_publisher check; deleted again in the same run.\n")


def check(base_url: str | None = None, creds: Any = None, *,
          client: McpServeClient | None = None,
          log: Callable[[str], None] = print) -> dict[str, Any]:
    """Validate a provisioned serve without touching any real payload.

    Proves, in order: the writer OAuth credentials work (a bearer is
    required for every /mcp call), the principal's honest tool surface via
    tools/list (put_page/delete_page visibility decides whether revoke()
    can delete or only tombstone), and -- only when the probe can be
    cleaned up again -- quota headroom, via one tiny put+delete round-trip
    on the project_knowledge/__probe__ slug.  The probe burns a few receipt
    bytes on purpose: "Write capacity exhausted" arrives as an isError
    rejection, exactly the failure class that hid on the family brain for a
    week (2026-09-27), so this is the one signal that proves the lane is
    usable end to end.  ``ok`` is True only when creds, surface, quota AND
    cleanup all check out.
    """
    summary: dict[str, Any] = {
        "ok": False,
        "endpoint": None,
        "tokenOk": False,
        "toolsVisible": [],
        "putPage": False,
        "deletePage": False,
        "probeSlug": PROBE_SLUG,
        "probePut": "not-run",
        "probeDeleted": False,
        "quotaHeadroom": "unverified",
        "warnings": [],
        "error": None,
    }
    try:
        active = client if client is not None else _client_from(base_url, creds)
    except GbrainPublishError as exc:
        summary["error"] = str(exc)
        log(f"check: FAILED ({exc})")
        return summary
    summary["endpoint"] = active.base
    try:
        tools = active.list_tools()
    except GbrainRejectedError as exc:
        summary["error"] = f"tools/list rejected: {exc.reason}"
        log(f"check: FAILED ({summary['error']})")
        return summary
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as exc:
        summary["error"] = f"tools/list failed: {type(exc).__name__}: {exc}"[:250]
        log(f"check: FAILED ({summary['error']})")
        return summary
    summary["tokenOk"] = True
    summary["toolsVisible"] = tools
    summary["putPage"] = "put_page" in tools
    summary["deletePage"] = "delete_page" in tools
    log(f"check: token OK, {len(tools)} tools visible "
        f"(put_page={summary['putPage']}, delete_page={summary['deletePage']})")
    if not summary["putPage"]:
        summary["probePut"] = "skipped: put_page not visible to this principal"
        summary["warnings"].append(
            "surface lacks put_page -- grant the writer profile or rescope the client")
        log(f"check: FAILED ({summary['probePut']})")
        return summary
    if not summary["deletePage"]:
        # A probe we cannot delete would leave litter in the namespace; a
        # publish-lane without delete_page also cannot run revoke() deletions.
        summary["probePut"] = "skipped: delete_page not visible; the probe could not be cleaned up"
        summary["warnings"].append(
            "surface lacks delete_page -- revoke() falls back to tombstone-only "
            "and quota cannot be probed safely")
        log(f"check: FAILED ({summary['probePut']})")
        return summary
    content = _probe_page()
    try:
        active.call("put_page", {
            "slug": PROBE_SLUG,
            "content": content,
            "force": True,
            "ingested_via": INGESTED_VIA,
            "request_id": _request_id("check-put", PROBE_SLUG, content),
        })
    except GbrainRejectedError as exc:
        summary["probePut"] = "rejected"
        summary["warnings"].append(f"probe put rejected: {exc.reason}")
        log(f"check: FAILED (probe put rejected: {exc.reason})")
        return summary
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        summary["probePut"] = "error"
        summary["error"] = f"probe put failed: {type(exc).__name__}: {exc}"[:250]
        log(f"check: FAILED ({summary['error']})")
        return summary
    summary["probePut"] = "ok"
    summary["quotaHeadroom"] = "ok"
    log("check: probe PUT ok (quota headroom confirmed)")
    try:
        active.call("delete_page", {
            "slug": PROBE_SLUG,
            "force": True,
            "request_id": _request_id("check-delete", PROBE_SLUG),
        })
        summary["probeDeleted"] = True
        log("check: probe DELETE ok (namespace clean)")
    except GbrainRejectedError as exc:
        summary["warnings"].append(
            f"probe delete rejected -- the probe page REMAINS at {PROBE_SLUG}: {exc.reason}")
        log(f"check: FAILED (probe delete rejected: {exc.reason})")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        summary["warnings"].append(
            f"probe delete failed -- the probe page REMAINS at {PROBE_SLUG}: {type(exc).__name__}")
        log("check: FAILED (probe delete transport error)")
    summary["ok"] = summary["probeDeleted"]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a KnowledgeVersion into the gBrain project_knowledge "
                    "namespace over a gbrain serve's MCP surface (dry run by default)")
    parser.add_argument("--url", default=os.environ.get("UYP_GBRAIN_URL"),
                        help="gbrain serve base URL, e.g. http://127.0.0.1:3141 (required for --apply)")
    parser.add_argument("--creds", default=os.environ.get("UYP_GBRAIN_CREDS"),
                        help="writer OAuth creds json (client_id/client_secret)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write (default is a dry run that prints the payload plan)")
    sub = parser.add_subparsers(dest="action", required=True)
    put = sub.add_parser("publish", help="mirror a KnowledgeVersion into gbrain")
    put.add_argument("--knowledge-root", required=True,
                     help="published project directory of *.knowledge.json items")
    put.add_argument("--project-id", required=True)
    put.add_argument("--version", required=True, help="KnowledgeVersion being mirrored")
    put.add_argument("--grant-epoch", required=True, help="HomeHub grant epoch (revocation key)")
    put.add_argument("--source-epoch", help="Connector manifest epoch for evidence lineage")
    drop = sub.add_parser("revoke", help="invalidate one grant epoch's published pages")
    drop.add_argument("--project-id", required=True)
    drop.add_argument("--grant-epoch", required=True)
    drop.add_argument("--knowledge-root", help="project directory that produced the pages")
    drop.add_argument("--slugs", help="comma-separated explicit slug list instead")
    sub.add_parser("check", help="validate creds/tool surface/quota headroom against a "
                                 "serve without writing real payload (exits non-zero on failure)")
    args = parser.parse_args()
    if args.action == "publish":
        result = publish(args.knowledge_root, args.project_id, args.version,
                         args.grant_epoch, dry_run=not args.apply,
                         base_url=args.url, creds=args.creds,
                         source_epoch=args.source_epoch)
    elif args.action == "revoke":
        slugs = [part.strip() for part in args.slugs.split(",") if part.strip()] if args.slugs else None
        result = revoke(args.project_id, args.grant_epoch,
                        knowledge_root=args.knowledge_root, slugs=slugs,
                        dry_run=not args.apply, base_url=args.url, creds=args.creds)
    else:
        result = check(args.url, args.creds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # A check is a gate for runbook scripts: propagate the verdict.
        raise SystemExit(0 if result.get("ok") else 1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
