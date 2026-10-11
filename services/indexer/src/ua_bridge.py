#!/usr/bin/env python3
"""Run vendored Understand Anything behind the Connector boundary.

The bridge stages only bounded, Connector-authorized bytes into a temporary
directory under ``state_root``. UA reads that staging directory and writes its
intermediate files and graph under ``state_root``; the source connector is
never modified and no analysis artifact is written into a source project.

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
import tempfile
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


def run_checked(command: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


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
    staged = 0
    skipped_large: list[str] = []
    ua_env = dict(os.environ)
    ua_env["UYP_UA_ROOT"] = os.path.realpath(os.path.expanduser(ua_root))

    with tempfile.TemporaryDirectory(prefix="uyp-ua-", dir=str(state)) as staging_raw:
        staging = Path(staging_raw)
        for entry in files:
            rel = safe_relative_path(str(entry.get("relpath", "")))
            size = int(entry.get("size") or 0)
            if size > max_file_bytes:
                skipped_large.append(rel)
                continue
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if size == 0:
                target.touch()
                staged += 1
                continue
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
            staged += 1

        scan_path = intermediate / "scan-result.json"
        batches_path = intermediate / "batches.json"
        run_checked(["node", f"{ua_env['UYP_UA_ROOT']}/skills/understand/scan-project.mjs", str(staging), str(scan_path), "--exclude-analysis-data"], env=ua_env)
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
        # source bytes remain in the temporary Connector staging tree.
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
        "skippedLarge": skipped_large,
        "graphPath": str(project_state / "knowledge-graph.json"),
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "languages": graph.get("project", {}).get("languages", []),
    }
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
