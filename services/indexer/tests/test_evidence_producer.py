"""KnowledgeEvidence producer tests (2026-10-18, first runtime producer).

Offline only: temp output/state roots, file-based AccessContext, the
search synthesis faked at the query_api seam and the ask LLM injected -
no Ollama, no HomeHub, no real knowledge store beyond fixtures.

Covers the four audit-driven acceptance points:

1. every emitted record carries the six frozen contract fields with
   correct values AND validates against the vendored
   harness_contracts KnowledgeEvidence model (the same class the
   frozen contract tests pin);
2. freshness is genuinely computed (fresh / stale / unknown from real
   timestamps, thresholds documented in knowledge_evidence);
3. permission_checked is true only on gated paths - a cited path that
   did not pass the scope gate produces NO record at all;
4. fact_type classification (semantic / structural / inferred), plus
   the frozen-six-field regression on the vendored contract itself.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import knowledge_evidence  # noqa: E402
import project_digest  # noqa: E402
import projects  # noqa: E402
import query_api  # noqa: E402
from harness_contracts import KnowledgeEvidence  # noqa: E402

NOW = time.time()
ENV_KEYS = ("UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_EVIDENCE_GRAPH_REFS")


class EvidenceFixture(unittest.TestCase):
    """Temp store + one anchored semantic item and one structure-only item."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / "output"
        self.state = root / "state"
        demo = self.out / "demo-project"
        demo.mkdir(parents=True)
        (demo / "src__main.py.knowledge.json").write_text(json.dumps({
            "file": "src/main.py",
            "version": {"mtime": int(NOW - 3600), "size": 512},
            "verdict": "quick-summary",
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 3600)),
            "derived": {"purpose": "Entry point wiring the CLI."},
            "anchor_top": "main L10-L42",
        }), encoding="utf-8")
        (demo / "lib__bare.py.knowledge.json").write_text(json.dumps({
            "file": "lib/bare.py",
            "version": {"mtime": int(NOW - 7200), "size": 32},
            "verdict": "structure-only",
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 7200)),
            "derived": {"lines": 3, "py_defs": ["helper"], "imports": []},
        }), encoding="utf-8")
        self.context_file = root / "access.json"
        self.context_file.write_text(json.dumps({
            "principalId": "p1", "sessionId": "s1", "jarvisNodeId": "jetson-test",
            "projectScopes": ["demo-project"], "sourceScopes": ["connector:demo-project"],
            "grantEpoch": "g1", "policyDigest": "pd1",
            "expiresAt": "2099-01-01T00:00:00Z", "auditId": "a1",
        }), encoding="utf-8")
        self.old = {key: os.environ.get(key) for key in ENV_KEYS}
        os.environ["UYP_OUTPUT_ROOT"] = str(self.out)
        os.environ["UYP_STATE_ROOT"] = str(self.state)
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(self.context_file)
        projects.reset_caches()
        project_digest._MANIFEST_CACHE.clear()

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        projects.reset_caches()
        self.tmp.cleanup()

    def context(self):
        return query_api.load_access_context()


class SixFrozenFieldTests(EvidenceFixture):
    def test_every_record_carries_the_frozen_six_with_correct_values(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}], scoped,
            gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual(len(records), 1)
        record = records[0]
        for field in ("source_id", "source_version", "locator", "content",
                      "permission_checked", "retrieved_at"):
            self.assertIn(field, record, field)
        self.assertEqual(record["source_id"], "connector:demo-project")
        self.assertEqual(record["source_version"],
                         f"mtime={int(NOW - 3600)};size=512")
        self.assertEqual(record["locator"], "src/main.py#L10-L42")
        self.assertEqual(record["content"], "Entry point wiring the CLI.")
        self.assertIs(record["permission_checked"], True)
        self.assertRegex(record["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T.+Z$")

    def test_records_validate_against_the_contract_model(self):
        # The vendored harness_contracts class is the same one the
        # frozen-contract tests pin; a record that fails this round
        # trip is not contract evidence, whatever its shape.
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}, {"file": "lib/bare.py", "match": 2.0}],
            scoped, gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual(len(records), 2)
        for record in records:
            restored = KnowledgeEvidence.model_validate(record)
            self.assertEqual(restored.model_dump(exclude_none=True), record)

    def test_locator_stays_a_bare_path_without_anchor(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "lib/bare.py", "match": 2.0}], scoped,
            gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual(records[0]["locator"], "lib/bare.py")

    def test_contract_frozen_six_field_regression(self):
        legacy = KnowledgeEvidence(
            source_id="connector:demo-project",
            source_version="mtime=1;size=2",
            locator="src/main.py#L10-L42",
            content="Entry point",
            permission_checked=True,
            retrieved_at="2026-10-18T09:15:00Z",
        )
        self.assertEqual(
            [f for f in legacy.model_dump() if legacy.model_dump()[f] is not None],
            ["schema_version", "source_id", "source_version", "locator",
             "content", "permission_checked", "retrieved_at"])
        with self.assertRaises(Exception):
            KnowledgeEvidence(
                source_id="s", source_version="v", locator="l", content="c",
                permission_checked=True, retrieved_at="t", surprise=1)


class FreshnessTests(EvidenceFixture):
    def _record_for(self, items):
        context = self.context()
        return knowledge_evidence.build_evidence(
            [{"file": items[0]["file"], "match": 1.0}],
            [dict(item, _out_path=str(self.out / "demo-project" / "x.knowledge.json"))
             for item in items],
            gate=lambda item: query_api.scope_allows(context, item))

    def test_recent_index_edition_is_fresh(self):
        records = self._record_for([{
            "file": "a.py", "version": {"mtime": int(NOW - 600)},
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 600))}])
        self.assertEqual(records[0]["freshness"], "fresh")
        self.assertIsNotNone(records[0]["index_as_of"])

    def test_old_index_edition_is_stale(self):
        records = self._record_for([{
            "file": "a.py", "version": {"mtime": int(NOW - 10 * 86400)},
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                         time.localtime(NOW - 10 * 86400))}])
        self.assertEqual(records[0]["freshness"], "stale")

    def test_undated_index_edition_is_unknown(self):
        records = self._record_for([{"file": "a.py", "analyzed_at": ""}])
        self.assertEqual(records[0]["freshness"], "unknown")
        self.assertIsNone(records[0].get("index_as_of"))


class PermissionGateTests(EvidenceFixture):
    def test_out_of_scope_citation_produces_no_record(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "other-project/secret.py", "match": 9.0},
             {"file": "src/main.py", "match": 4.0}],
            scoped, gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual([r["locator"].split("#")[0] for r in records],
                         ["src/main.py"])

    def test_gate_failure_drops_the_record_even_when_joined(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}], scoped,
            gate=lambda item: False)  # revocation mid-request
        self.assertEqual(records, [])

    def test_produced_records_never_claim_unchecked_permission(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}], scoped,
            gate=lambda item: query_api.scope_allows(context, item))
        self.assertTrue(records)
        self.assertTrue(all(r["permission_checked"] is True for r in records))


class FactTypeTests(EvidenceFixture):
    def test_purpose_item_is_semantic_and_structure_only_is_structural(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}, {"file": "lib/bare.py", "match": 2.0}],
            scoped, gate=lambda item: query_api.scope_allows(context, item))
        by_file = {r["locator"].split("#")[0]: r for r in records}
        self.assertEqual(by_file["src/main.py"]["fact_type"], "semantic")
        self.assertEqual(by_file["lib/bare.py"]["fact_type"], "structural")
        self.assertTrue(by_file["lib/bare.py"]["content"].startswith("structure-only"))

    def test_computed_cross_record_fact_is_inferred(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        statement = ("Index edition ends at 2026-10-18 09:00:00 (newest item: "
                     "src/main.py); the asked time window is beyond the indexed edition.")
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "ts": "2026-10-18 09:00:00"}], scoped,
            gate=lambda item: query_api.scope_allows(context, item),
            inferred_content={"src/main.py": statement})
        self.assertEqual(records[0]["fact_type"], "inferred")
        self.assertEqual(records[0]["content"], statement)


class GraphRefTests(EvidenceFixture):
    def test_graph_refs_tie_the_record_to_the_graph_edition(self):
        ua = self.state / "demo-project" / "ua"
        ua.mkdir(parents=True)
        (ua / "knowledge-graph.json").write_text(json.dumps({
            "version": "1.0.0",
            "nodes": [
                {"id": "file:src/main.py", "type": "file", "filePath": "src/main.py"},
                {"id": "function:src/main.py:main", "type": "function", "filePath": "src/main.py"},
            ],
            "edges": [{"source": "file:src/main.py",
                       "target": "function:src/main.py:main", "type": "contains"}],
        }), encoding="utf-8")
        context = self.context()
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}],
            query_api.scoped_items(context),
            gate=lambda item: query_api.scope_allows(context, item),
            graph_provider=query_api._graph_index_for)
        record = records[0]
        self.assertEqual(record["graph_version"], "1.0.0")
        self.assertEqual(record["node_ids"],
                         ["file:src/main.py", "function:src/main.py:main"])
        self.assertEqual(record["edge_ids"],
                         ["file:src/main.py->function:src/main.py:main"])


class SearchApiEvidenceTests(EvidenceFixture):
    """HTTP level: /api/knowledge/search returns the additive evidence[]."""

    def setUp(self):
        super().setUp()

        def fake_search_answer(question, items):
            return {"answer": "The CLI entry point lives in src/main.py.",
                    # Deterministic citation (glob order differs per fs).
                    "sources": [{"file": "src/main.py", "match": 4.0}],
                    "confidence": "high",
                    "index_as_of": "2026-10-18 09:00:00"}

        patcher = patch.object(query_api, "search_answer", fake_search_answer)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)

    def _post_search(self, body):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/knowledge/search" % self.api.server_address[1],
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def test_search_response_carries_contract_evidence(self):
        body = self._post_search({"query": "where is the entry point implemented"})
        self.assertTrue(body["ok"])
        self.assertEqual(body["sources"], [{"file": "src/main.py", "match": 4.0}])
        self.assertTrue(body["evidence"])
        record = body["evidence"][0]
        self.assertEqual(record["source_id"], "connector:demo-project")
        self.assertEqual(record["locator"], "src/main.py#L10-L42")
        self.assertIs(record["permission_checked"], True)
        self.assertEqual(record["provider"], "local")
        self.assertEqual(record["model_id"], "qwen3.5-route")
        KnowledgeEvidence.model_validate(record)
        # citations and sources are DERIVED from the same records now.
        self.assertEqual(body["citations"][0]["file"], "src/main.py")
        self.assertEqual(body["citations"][0]["sourceId"],
                         record["source_id"])

    def test_miss_returns_an_empty_evidence_array(self):
        def miss_answer(question, items):
            return {"answer": query_api.MISS_SENTENCE, "sources": [],
                    "confidence": "none"}
        with patch.object(query_api, "search_answer", miss_answer):
            body = self._post_search({"query": "quantum chromodynamics"})
        self.assertEqual(body["evidence"], [])
        self.assertEqual(body["sources"], [])


class AskEvidenceTests(EvidenceFixture):
    """/api/projects/{id}/ask (project_digest.ask) evidence path."""

    def setUp(self):
        super().setUp()
        # A second project item set shaped like the real ask fixtures:
        # tiered purposes, an embedded root, and a registered grant.
        self.state.mkdir(parents=True, exist_ok=True)
        self._write_item("commontasks", "README.md",
                         "Shared clinic task tracker with a voice assistant.", "A", 3)
        self._write_item("commontasks", "src/app.py",
                         "Flask entry point wiring routes and the scheduler.", "A", 1)
        self._write_item("commontasks", "src/db.py",
                         "SQLite persistence layer for tasks.", "B", 7,
                         mtime=int(NOW - 10 * 86400))
        (self.state / "commontasks.json").write_text(
            json.dumps({"grant": "g_ct", "root": "commontasks"}), encoding="utf-8")
        self.ctx = {"principalId": "robin", "projectScopes": ["commontasks"],
                    "sourceScopes": ["connector:commontasks"]}

    def _write_item(self, project, rel, purpose, tier, rank, mtime=None):
        directory = self.out / project
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (rel.replace("/", "__") + ".knowledge.json")).write_text(json.dumps({
            "file": rel,
            "version": {"mtime": int(mtime if mtime is not None else NOW - 3600), "size": 100},
            "verdict": "quick-summary" if purpose else "structure-only",
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 3600)),
            "derived": {"purpose": purpose, "key_points": [f"{rel} point"], "components": []},
            "keyfile": {"tier": tier, "score": 0.5, "rank": rank, "gate": None, "embedded": None},
        }), encoding="utf-8")

    def test_ask_returns_evidence_for_each_cited_file(self):
        result = project_digest.ask(
            self.ctx, "commontasks", "Where is the SQLite persistence?",
            member="robin", role="owner",
            llm=lambda prompt: "Tasks persist in src/db.py.",
            gbrain=lambda q, m, r: [])
        self.assertEqual(result["sources"], [{"file": "src/db.py"}])
        self.assertEqual(len(result["evidence"]), 1)
        record = result["evidence"][0]
        self.assertEqual(record["source_id"], "connector:commontasks")
        self.assertEqual(record["locator"], "src/db.py")
        self.assertEqual(record["content"], "SQLite persistence layer for tasks.")
        self.assertIs(record["permission_checked"], True)
        self.assertEqual(record["fact_type"], "semantic")
        # Freshness tracks the PROJECT index edition (max analyzed
        # mtime), not the single file: newer siblings keep the edition
        # fresh even when db.py itself is 10 days old.
        self.assertEqual(record["freshness"], "fresh")
        self.assertIsNotNone(record["index_as_of"])
        KnowledgeEvidence.model_validate(record)

    def test_ask_miss_keeps_evidence_empty(self):
        result = project_digest.ask(
            self.ctx, "commontasks", "quantum chromodynamics lattice",
            member="robin", role="owner",
            llm=lambda prompt: "made up",
            gbrain=lambda q, m, r: [])
        self.assertEqual(result["evidence"], [])


class StudioSnapshotTests(EvidenceFixture):
    def test_snapshot_evidence_is_projected_from_contract_records(self):
        snapshot = query_api.project_snapshot()
        self.assertEqual(len(snapshot["evidence"]), 2)
        entry = next(e for e in snapshot["evidence"] if e["locator"]["path"] == "src/main.py")
        # Legacy v3.2 Studio shape, now derived from the record itself.
        # (lib/bare.py sorts first, so src/main.py carries index 1.)
        self.assertEqual(entry["evidenceId"], "knowledge:demo-project:1")
        self.assertEqual(entry["kind"], "inference")
        self.assertEqual(entry["summary"], "Entry point wiring the CLI.")
        self.assertEqual(entry["anchorTop"], "main L10-L42")
        self.assertEqual(entry["knowledgeVersion"], str(int(NOW - 3600)))


if __name__ == "__main__":
    unittest.main()
