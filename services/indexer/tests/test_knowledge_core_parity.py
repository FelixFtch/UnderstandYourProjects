"""Cross-front-door behavioral comparison (Knowledge Core extraction, A4).

The UYP query API (:8787) and the household knowledge-service (:8790) now
share one authorized_search pipeline (knowledge_core).  This suite pins the
extraction acceptance points that live ACROSS the two trees:

1. the vendored knowledge_core copy in this tree is byte-identical to the
   canonical package in the jarvis-homehub repo (no silent drift between
   the two deployments);
2. the same underlying content produces the SAME contract evidence
   semantics through the :8787 wiring (items -> knowledge_evidence
   producer via the core) and the :8790 wiring (blocks ->
   evidence_from_blocks via the core): content, permission_checked,
   freshness, index_as_of, provider, and the six frozen field names all
   agree;
3. both wirings are deterministic (repeated runs are byte-identical).

Offline only; the composition seam is faked so no Ollama call happens.
The jarvis-homehub-dependent assertions skip gracefully when that checkout
is absent (set JARVIS_HOMEHUB_REPO to point at it).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import knowledge_core  # noqa: E402
import knowledge_evidence  # noqa: E402
import query_api  # noqa: E402

_HH_CANDIDATES = [
    os.environ.get("JARVIS_HOMEHUB_REPO", ""),
    os.path.expanduser("~/projects/jarvis-homehub"),
]
_HH_ROOT = next((p for p in _HH_CANDIDATES if p and os.path.isdir(p)), None)
_CANONICAL = (os.path.join(_HH_ROOT, "jetson", "packages", "knowledge_core", "src")
              if _HH_ROOT else None)
_SERVICE = (os.path.join(_HH_ROOT, "jetson", "services", "knowledge-service", "service.py")
            if _HH_ROOT else None)
_VENDORED = Path(__file__).parents[1] / "src" / "knowledge_core"

FROZEN = {"schema_version", "source_id", "source_version", "locator",
          "content", "permission_checked", "retrieved_at"}


def _load_service_module():
    spec = importlib.util.spec_from_file_location("hh_knowledge_service", _SERVICE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hh_knowledge_service"] = module
    spec.loader.exec_module(module)
    return module


def _context(scopes: dict):
    return {
        "principalId": "felix",
        "sessionId": "sess-1",
        "jarvisNodeId": "node-1",
        "projectScopes": scopes.get("projects", ["demo"]),
        "sourceScopes": scopes.get("sources", ["connector:demo"]),
        "grantEpoch": "7",
        "policyDigest": "sha256:x",
        "expiresAt": "2999-01-01T00:00:00Z",
        "auditId": "audit-1",
    }


def _write_store(root: str):
    demo = os.path.join(root, "demo")
    os.makedirs(demo, exist_ok=True)
    # one epoch, used for the item's mtime AND the mirrored page's
    # effective_date, so both producers compute freshness from the
    # same provenable date
    stamp_epoch = time.mktime(time.strptime("2026-10-18 10:00:00",
                                            "%Y-%m-%d %H:%M:%S"))
    item = {
        "file": "src/signing.py",
        "source": "connector:demo",
        "derived": {"purpose": "hmac delegation signing helper"},
        "version": {"mtime": stamp_epoch, "size": 1234},
        "analyzed_at": "2026-10-18 10:00:00",
    }
    with open(os.path.join(demo, "a.knowledge.json"), "w", encoding="utf-8") as fh:
        json.dump(item, fh)
    return item


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="kcore-parity-")
        cls._old = os.environ.get("UYP_OUTPUT_ROOT")
        os.environ["UYP_OUTPUT_ROOT"] = cls._tmp.name
        cls.item = _write_store(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        if cls._old is None:
            os.environ.pop("UYP_OUTPUT_ROOT", None)
        else:
            os.environ["UYP_OUTPUT_ROOT"] = cls._old
        cls._tmp.cleanup()

    def _items_result(self, retrieved_at: str):
        """The :8787 wiring: query_api's core call (composer faked at the
        same seam test_evidence_producer patches)."""
        context = _context({})
        request = knowledge_core.KnowledgeQueryRequest(
            request_id="req-parity",
            session_id="sess-1",
            principal_id=context["principalId"],
            auth_level="second_factor_verified",
            grants=context["projectScopes"],
            grant_epoch=7,
            source_scope=context["sourceScopes"],
            query="where is signing",
        )
        with patch.object(query_api, "search_answer",
                          lambda q, items: {
                              "answer": "Signing lives in src/signing.py.",
                              "sources": [{"file": "src/signing.py", "match": 5.0}],
                              "confidence": "high",
                              "index_as_of": "2026-10-18 10:00:00"}), \
             patch.object(query_api, "search_will_synthesize", lambda q, i: False):
            return knowledge_core.authorized_search(
                request,
                composer=lambda q, items: query_api.search_answer(q, items),
                will_synthesize=lambda q, items: query_api.search_will_synthesize(q, items),
                graph_provider=lambda root: None,
                retrieved_at=retrieved_at,
            )

    def _blocks_result(self, retrieved_at: str):
        """The :8790 wiring: the same content as a mirrored project page,
        run through the shared blocks producer."""
        stamp_epoch = time.mktime(time.strptime("2026-10-18 10:00:00",
                                                "%Y-%m-%d %H:%M:%S"))
        blocks = [{
            "brain": "project_knowledge",
            "source": "project_knowledge/demo/7/src/signing.py",
            "text": "hmac delegation signing helper",
            "score": "5.0",
            "effective_date": time.strftime("%Y-%m-%d", time.localtime(stamp_epoch)),
        }]
        return knowledge_core.authorized_search(
            knowledge_core.KnowledgeQueryRequest(
                request_id="req-parity", session_id="", principal_id="felix",
                auth_level="voice_verified",
                grants=["personal_felix", "project_knowledge"], grant_epoch=0,
                source_scope=["project_knowledge/demo/7/"],
                query="where is signing"),
            blocks_retriever=lambda req, scope: (
                [b for b in blocks
                 if b["source"].startswith(tuple(scope.prefixes))], 2),
            retrieved_at=retrieved_at,
        )

    def test_same_content_same_contract_semantics(self):
        stamp = "2026-10-19T00:00:00Z"
        left = self._items_result(stamp).evidence
        right = self._blocks_result(stamp).evidence
        self.assertEqual(len(left), 1)
        self.assertEqual(len(right), 1)
        l, r = left[0], right[0]
        self.assertTrue(FROZEN.issubset(l), l)
        self.assertTrue(FROZEN.issubset(r), r)
        for field in ("content", "permission_checked", "freshness",
                      "provider", "retrieved_at", "schema_version"):
            self.assertEqual(l[field], r[field], field)
        # same edition, expressed in each producer's pin syntax
        self.assertTrue(l["source_version"].startswith("mtime="))
        self.assertTrue(l["source_version"].endswith(";size=1234"))
        self.assertEqual(r["source_version"], "2026-10-18")
        self.assertEqual(l["locator"].split("#")[0].endswith("src/signing.py"), True)
        self.assertTrue(r["locator"].endswith("src/signing.py"))

    def test_both_wirings_deterministic(self):
        for builder in (self._items_result, self._blocks_result):
            one = builder("2026-10-19T00:00:00Z").evidence
            two = builder("2026-10-19T00:00:00Z").evidence
            self.assertEqual(json.dumps(one, sort_keys=True),
                             json.dumps(two, sort_keys=True))

    def test_items_wiring_matches_query_api_projection(self):
        # The adapter must not corrupt records: query_api's own scope
        # helpers and the core produce the same evidence list here.
        result = self._items_result("2026-10-19T00:00:00Z")
        context = _context({})
        direct = knowledge_evidence.build_evidence(
            [{"file": "src/signing.py", "match": 5.0}],
            query_api.scoped_items(context),
            gate=lambda item: query_api.scope_allows(context, item),
            graph_provider=lambda root: None,
            retrieved_at="2026-10-19T00:00:00Z")
        self.assertEqual(json.dumps(result.evidence, sort_keys=True),
                         json.dumps(direct, sort_keys=True))

    @unittest.skipUnless(_CANONICAL and os.path.isdir(
        os.path.join(_CANONICAL, "knowledge_core")),
        "jarvis-homehub checkout not present")
    def test_vendored_core_is_byte_identical_to_canonical(self):
        for name in ("__init__.py", "core.py", "evidence.py"):
            with open(os.path.join(_CANONICAL, "knowledge_core", name),
                      encoding="utf-8") as fh:
                canonical = fh.read()
            with open(_VENDORED / name, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), canonical, name)

    @unittest.skipUnless(_SERVICE and os.path.isfile(_SERVICE),
                         "jarvis-homehub checkout not present")
    def test_8790_service_delegates_to_the_same_producer(self):
        ks = _load_service_module()
        blocks = [{"brain": "family", "source": "cal/1", "text": "note",
                   "score": "0.5", "effective_date": "2026-10-18"}]
        via_service = ks.to_evidence(blocks, retrieved_at="2026-10-19T00:00:00Z")
        via_core = knowledge_core.evidence_from_blocks(
            blocks, retrieved_at="2026-10-19T00:00:00Z")
        self.assertEqual(via_service, via_core)


if __name__ == "__main__":
    unittest.main()
