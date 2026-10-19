#!/usr/bin/env python3
"""Run vendored Understand Anything behind the Connector boundary.

The bridge stages only bounded, Connector-authorized bytes into a persistent
per-project cache under ``state_root`` (``<safe_root>/ua-cache/files`` plus a
parallel ``meta/`` sidecar tree). UA reads that staging tree and writes its
intermediate files and graph under ``state_root``; the source connector is
never modified and no analysis artifact is written into a source project.
The cache outlives a single run -- the enrichment worker (index_project.py)
fills the same layout -- so a retried UA pass redownloads only entries whose
size/mtime moved instead of the whole manifest.

This is deliberately a separate command while the IndexJob worker contract is
being finalized. The worker can call the same ``run`` function after a
HomeHub grant has moved an IndexJob into ``AUTHORIZED``.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


READ_CAP = 16 * 1024 * 1024


def api(host: str, token: str, path: str, *, binary: bool = False, timeout: int = 90):
    request = urllib.request.Request(
        host.rstrip("/") + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return payload if binary else json.loads(payload)


def safe_relative_path(value: str) -> str:
    candidate = posixpath.normpath(value.replace("\\", "/"))
    if candidate in {"", ".", ".."} or candidate.startswith("../") or candidate.startswith("/"):
        raise ValueError(f"unsafe connector path: {value!r}")
    return candidate


def _cache_entry_matches(meta_path: Path, target: Path, size: int, entry_mtime) -> bool:
    """True when the cached copy still matches this manifest entry.

    Reuse requires manifest-pinned agreement: same size, same mtime (when the
    manifest carries one), and the bytes present.  Any unreadable or partial
    cache state falls through to a fresh download, so a corrupted sidecar can
    never poison the staged tree.
    """
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or int(meta.get("size", -1)) != size:
            return False
        if not target.exists():
            return False
        if entry_mtime is None:
            return True  # entry validates on size alone
        cached = meta.get("mtime")
        # Manifests have carried both numeric epochs and formatted strings;
        # compare in whichever type both sides share so cross-writer cache
        # entries (the enrichment worker also fills this tree) validate.
        if isinstance(entry_mtime, (int, float)) and isinstance(cached, (int, float)):
            return abs(float(entry_mtime) - float(cached)) < 1e-6
        return str(entry_mtime) == str(cached)
    except (OSError, TypeError, ValueError):
        return False


def stage_manifest_files(
    files: list[dict],
    *,
    cache_root: Path,
    host: str,
    token: str,
    grant: str,
    max_file_bytes: int = READ_CAP,
) -> tuple[Path, int, int, list[str]]:
    """Fill the shared UA staging cache.

    Returns ``(files_root, staged, reused, skipped_large)``: ``files_root`` is
    the tree node phases scan, ``staged`` counts files downloaded this pass and
    ``reused`` counts cache hits.  ``cache_root`` holds a ``files/`` tree of
    full source bytes plus a parallel ``meta/`` tree of ``{"size", "mtime"}``
    sidecars pinned to the manifest entry that produced them.  Bytes are
    written before their sidecar: a crash between the two leaves data without
    metadata, which simply re-downloads on the next pass.
    """
    files_root = cache_root / "files"
    meta_root = cache_root / "meta"
    staged = reused = 0
    skipped_large: list[str] = []
    for entry in files:
        rel = safe_relative_path(str(entry.get("relpath", "")))
        size = int(entry.get("size") or 0)
        if size > max_file_bytes:
            skipped_large.append(rel)
            continue
        target = files_root / rel
        meta_path = meta_root / (rel + ".json")
        if _cache_entry_matches(meta_path, target, size, entry.get("mtime")):
            reused += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        if size == 0:
            target.touch()
        else:
            try:
                data = api(
                    host,
                    token,
                    "/read?grant=" + urllib.parse.quote(grant, safe="")
                    + "&relpath=" + urllib.parse.quote(rel, safe="/")
                    + "&length=" + str(min(size, max_file_bytes)),
                    binary=True,
                )
            except urllib.error.HTTPError as error:
                if error.code == 413:
                    skipped_large.append(rel)
                    continue
                raise
            target.write_bytes(data)
        meta_path.write_text(
            json.dumps({"size": size, "mtime": entry.get("mtime")}), encoding="utf-8")
        staged += 1
    return files_root, staged, reused, skipped_large


def run_checked(command: list[str], *, env: dict[str, str], attempts: int = 3, backoff_s: float = 2.0) -> None:
    """Run a UA pipeline stage with a bounded retry.

    Field evidence 2026-10-12: node intermittently failed to load an entry
    script that verifiably existed on disk (Cannot find module, ENOENT-class,
    no kernel errors) -- same command, same env, same binary, success and
    failure interleaved across minutes.  Transient, so retry with backoff
    instead of failing a multi-hour job at the last stage.
    """
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(command, check=True, env=env)
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            time.sleep(backoff_s * attempt)


def _indexer_run_flags(state: Path, root_name: str) -> dict:
    """Operator-visible flags from the enrichment worker's run-state JSON
    (<state_root>/<root>.json) — UA 云端分析模式 (2026-10-15): "ua_mode"
    records which enrichment path ran, and "cloud_enrich_broken" is set when
    5 consecutive cloud failures degraded the rest of the job to
    structure-only.  Surfacing them on the job's uaSummary keeps an
    all-structure-only degradation visible instead of silent.  Missing or
    unreadable state -> {} (a standalone CLI run has no worker file)."""
    try:
        data = json.loads((state / (root_name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in ("ua_mode", "cloud_enrich_broken") if data.get(k)}


def run(
    *,
    host: str,
    token_file: str,
    grant: str,
    ua_root: str,
    state_root: str,
    limit: int = 0,
    max_file_bytes: int = READ_CAP,
    project_name: str | None = None,
    knowledge_root: str | None = None,
) -> dict:
    token = Path(os.path.expanduser(token_file)).read_text(encoding="utf-8").strip()
    manifest = api(host, token, "/manifest?grant=" + urllib.parse.quote(grant, safe=""))
    # Follow the page cursor (connector PAGE_CAP 2000); the first page alone
    # silently dropped every file sorting after entry 2000.
    all_files = list(manifest.get("files", []))
    while manifest.get("has_more") and manifest.get("next_cursor"):
        manifest = api(host, token, "/manifest?grant=" + urllib.parse.quote(grant, safe="")
                       + "&cursor=" + urllib.parse.quote(manifest["next_cursor"], safe=""))
        all_files.extend(manifest.get("files", []))
    manifest = {**manifest, "files": all_files, "has_more": False}
    root_name = str(project_name or manifest.get("root_name") or "authorized-project")
    safe_root = safe_relative_path(root_name).replace("/", "__")
    state = Path(os.path.expanduser(state_root)).resolve()
    project_state = state / safe_root / "ua"
    intermediate = project_state / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    manifest_path = project_state / "connector-manifest.json"
    manifest_path.write_text(json.dumps({
        "grant": grant,
        "rootName": root_name,
        "sourceEpoch": manifest.get("source_epoch") or manifest.get("generated_at"),
        "total": manifest.get("total"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    files = [entry for entry in manifest.get("files", []) if entry.get("kind") == "file"]
    files.sort(key=lambda entry: str(entry.get("relpath", "")))
    if limit > 0:
        files = files[:limit]
    ua_env = dict(os.environ)
    ua_env["UYP_UA_ROOT"] = os.path.realpath(os.path.expanduser(ua_root))

    # Persistent staging replaces the old per-process TemporaryDirectory: the
    # tree survives this run (and is shared with the enrichment worker), so a
    # retried UA pass redownloads only entries whose size/mtime moved instead
    # of the whole manifest.
    staging, staged, reused, skipped_large = stage_manifest_files(
        files,
        cache_root=state / safe_root / "ua-cache",
        host=host,
        token=token,
        grant=grant,
        max_file_bytes=max_file_bytes,
    )
    # One journal-observable line so the cache hit rate is visible without
    # opening the summary file.
    print(f"ua-cache: staged={staged} reused={reused} skipped_large={len(skipped_large)}", flush=True)

    scan_path = intermediate / "scan-result.json"
    batches_path = intermediate / "batches.json"
    run_checked(["node", f"{ua_env['UYP_UA_ROOT']}/skills/understand/scan-project.mjs", str(staging), str(scan_path), "--exclude-analysis-data"], env=ua_env)
    # scan-project deliberately emits no importMap (the interactive skill's
    # scanner agent merges Step C itself); compute-batches reads
    # scan.importMap, so without this stage batchImportData is all-empty and
    # the built graph has zero imports edges -- dependency/impact questions
    # lose their graph and Louvain module batching degenerates to singletons.
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    import_input_path = intermediate / "import-input.json"
    import_map_path = intermediate / "import-map.json"
    import_input_path.write_text(json.dumps({
        "projectRoot": str(staging),
        "files": scan.get("files", []),
    }, ensure_ascii=False), encoding="utf-8")
    run_checked(["node", f"{ua_env['UYP_UA_ROOT']}/skills/understand/extract-import-map.mjs", str(import_input_path), str(import_map_path)], env=ua_env)
    scan["importMap"] = json.loads(import_map_path.read_text(encoding="utf-8")).get("importMap", {})
    scan_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")
    run_checked(["node", f"{ua_env['UYP_UA_ROOT']}/skills/understand/compute-batches.mjs", str(staging), f"--scan-result={scan_path}", f"--output={batches_path}"], env=ua_env)
    batches = json.loads(batches_path.read_text(encoding="utf-8"))
    all_results: list[dict] = []
    imports_by_path: dict[str, list] = {}
    for batch in batches.get("batches", []):
        batch_index = int(batch.get("batchIndex", 0))
        input_path = intermediate / f"extract-input-{batch_index}.json"
        output_path = intermediate / f"extract-result-{batch_index}.json"
        input_path.write_text(json.dumps({
            "projectRoot": str(staging),
            "batchFiles": batch.get("files", []),
            "batchImportData": batch.get("batchImportData", {}),
        }, ensure_ascii=False), encoding="utf-8")
        run_checked(["node", f"{ua_env['UYP_UA_ROOT']}/skills/understand/extract-structure.mjs", str(input_path), str(output_path)], env=ua_env)
        extracted = json.loads(output_path.read_text(encoding="utf-8"))
        all_results.extend(extracted.get("results", []))
        imports_by_path.update(batch.get("batchImportData", {}))

    # Laya/Qwen enrichment is already a Connector-scoped artifact in the
    # worker staging directory.  Pass only bounded derived metadata to UA;
    # source bytes remain in the persistent Connector staging cache.
    semantic_by_path: dict[str, dict] = {}
    if knowledge_root:
        root = Path(os.path.expanduser(knowledge_root)).resolve()
        for item_path in root.glob("*.knowledge.json"):
            try:
                item = json.loads(item_path.read_text(encoding="utf-8"))
                rel = safe_relative_path(str(item.get("file", "")))
                derived = item.get("derived")
                if isinstance(derived, dict):
                    semantic_by_path[rel] = {
                        "purpose": str(derived.get("purpose", ""))[:512],
                        "keyPoints": [str(v)[:256] for v in derived.get("key_points", [])[:3]] if isinstance(derived.get("key_points"), list) else [],
                        "components": [str(v)[:256] for v in derived.get("components", [])[:3]] if isinstance(derived.get("components"), list) else [],
                    }
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue

    bundle_path = intermediate / "graph-input.json"
    bundle_path.write_text(json.dumps({
        "projectName": root_name,
        "contentDigest": json.loads(scan_path.read_text(encoding="utf-8")).get("contentDigest"),
        "results": all_results,
        "importsByPath": imports_by_path,
        "semanticByPath": semantic_by_path,
    }, ensure_ascii=False), encoding="utf-8")
    graph_path = project_state / "knowledge-graph.json"
    run_checked(["node", str(Path(__file__).with_name("ua_graph_builder.mjs")), str(bundle_path), str(graph_path)], env=ua_env)

    graph = json.loads((project_state / "knowledge-graph.json").read_text(encoding="utf-8"))
    summary = {
        "project": root_name,
        "grant": grant,
        "stagedFiles": staged,
        "cache_reused": reused,
        "skippedLarge": skipped_large,
        "graphPath": str(project_state / "knowledge-graph.json"),
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "importEdges": sum(1 for edge in graph.get("edges", []) if edge.get("type") == "imports"),
        "languages": graph.get("project", {}).get("languages", []),
    }
    # Merge the enrichment worker's UA-mode flags (cloud_enrich_broken) so the
    # job's uaSummary tells the operator when cloud enrichment degraded.
    summary.update(_indexer_run_flags(state, str(manifest.get("root_name") or root_name)))
    (project_state / "run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:7121")
    parser.add_argument("--token-file", default="~/.config/uyp/token")
    parser.add_argument("--grant", required=True)
    parser.add_argument("--ua-root", required=True)
    parser.add_argument("--state-root", default="~/dev/uyp/state")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-file-bytes", type=int, default=READ_CAP)
    parser.add_argument("--project-name")
    parser.add_argument("--knowledge-root")
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
