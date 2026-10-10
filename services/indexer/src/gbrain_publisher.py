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
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

NAMESPACE = "project_knowledge"
MANIFEST_SEGMENT = "__manifest__"
INGESTED_VIA = "uyp-gbrain-publisher/1.0"
SLUG_MAX = 255
TOKEN_MARGIN_SECONDS = 120.0


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
               grant_epoch: str, published_at: str | None = None) -> dict[str, Any]:
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
    lines = [f"# {project_id}: {relpath}", ""]
    lines.append(f"verdict: {item.get('verdict', '')} (think gate {item.get('think_gate', '')})")
    lines.append("")
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
                   revoked: bool = False, revoked_at: str | None = None) -> dict[str, Any]:
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

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode()
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
            raise GbrainRejectedError(tool, str(arguments.get("slug", "")), str(envelope["error"])[:200])
        result = envelope.get("result") or {}
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
            published_at: str | None = None) -> dict[str, Any]:
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
                          grant_epoch=grant_epoch, published_at=published_at)
               for item in items]
    _reject_slug_collisions(entries)
    manifest = build_manifest(project_id, grant_epoch, version=version,
                              entries=entries, published_at=published_at)
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
            active.call("put_page", {
                "slug": entry["slug"],
                "content": entry["content"],
                "force": True,
                "ingested_via": INGESTED_VIA,
                "request_id": _request_id("put", entry["slug"], entry["content"]),
            })
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
        active.call("put_page", {
            "slug": tombstone["slug"],
            "content": tombstone["content"],
            "force": True,
            "ingested_via": INGESTED_VIA,
            "request_id": _request_id("put", tombstone["slug"], tombstone["content"]),
        })
        summary["tombstoneWritten"] = True
    except GbrainRejectedError as exc:
        summary["failed"] = {"slug": exc.slug, "reason": exc.reason}
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
    drop = sub.add_parser("revoke", help="invalidate one grant epoch's published pages")
    drop.add_argument("--project-id", required=True)
    drop.add_argument("--grant-epoch", required=True)
    drop.add_argument("--knowledge-root", help="project directory that produced the pages")
    drop.add_argument("--slugs", help="comma-separated explicit slug list instead")
    args = parser.parse_args()
    if args.action == "publish":
        result = publish(args.knowledge_root, args.project_id, args.version,
                         args.grant_epoch, dry_run=not args.apply,
                         base_url=args.url, creds=args.creds)
    else:
        slugs = [part.strip() for part in args.slugs.split(",") if part.strip()] if args.slugs else None
        result = revoke(args.project_id, args.grant_epoch,
                        knowledge_root=args.knowledge_root, slugs=slugs,
                        dry_run=not args.apply, base_url=args.url, creds=args.creds)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
