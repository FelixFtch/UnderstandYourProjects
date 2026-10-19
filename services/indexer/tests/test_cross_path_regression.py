"""Cross-path evidence & permission regression (live audit 2026-10-18).

The 2026-10-18 live cross-path run (see
docs/CROSS_PATH_EVIDENCE_AUDIT_2026-10-18.md and the raw probe JSONs in
docs/evidence-crosspath-20261018/) established, for the SAME question,
SAME user and SAME source (jarvis-homehub), that the three knowledge
paths agree on some invariants and diverge on others:

  Path 1 Studio : Bearer -> HomeHub AccessContext -> query_api scoped_items
                  (scope filter BEFORE retrieval) + contract KnowledgeEvidence.
  Path 2 voice  : knowledge-service :8790 (separate deployment, not this
                  repo) - request-body identity, brain-level grant filter
                  pre-retrieval, project_knowledge blocks masked AFTER
                  retrieval; blocks are {score, source, brain, text} only.
  Path 3 group  : group context -> scoped_retrieval (validate -> membership
                  -> view intersection -> scoped_items) BEFORE retrieval;
                  answers carry NO contract evidence records by design.

These tests pin the invariants that live in THIS repo's shared seams so a
future change that breaks the horizontal contract fails here first:

  1. same authorized view -> same admitted items on the Studio tier and
     the group tier (cross-path scope equivalence);
  2. every negative that failed closed on the box on 2026-10-18 still
     fails closed offline: non-member, expired context, revoked context,
     unknown group, out-of-scope source;
  3. the KnowledgeEvidence producer stays honest across tiers: an
     out-of-scope cited file produces NO record (dropped, never
     permission_checked=false), an in-scope one carries the frozen six;
  4. the group tier's post-answer source_overlap scrub still refuses an
     answer whose citations fall outside the enforced view;
  5. the voice tier's live block shape does NOT satisfy the frozen
     KnowledgeEvidence contract (documents the semantic gap as a
     tripwire: update this test when :8790 adopts the contract).

Offline only: temp output/state roots and a file AccessContext, exactly
like test_evidence_producer; no Ollama, no HomeHub, no gbrain.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import groups  # noqa: E402
import knowledge_evidence  # noqa: E402
import projects  # noqa: E402
import query_api  # noqa: E402
from harness_contracts import KnowledgeEvidence  # noqa: E402

NOW = time.time()
ENV_KEYS = ("UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_EVIDENCE_GRAPH_REFS")

# One live block exactly as :8790 returned it on 2026-10-18 (felix, Q1,
# unscoped): the voice tier's entire evidence vocabulary is these four
# keys - no permission, version, audit, or freshness story.
VOICE_BLOCK_FIXTURE = {
    "score": "0.857467",
    "source": "municipal/municipal_board-19069",
    "brain": "public",
    "text": "# Boston News: Council Supports Tenant First Right of Refusal...",
}


def group_context(member="felix", project_ids=("demo-project",),
                  source_ids=("*",), expires=None, revoked=False):
    ctx = {
        "group_id": "family",
        "member_id": member,
        "jarvis_node_id": "jetson-test",
        "project_ids": list(project_ids),
        "source_ids": list(source_ids),
        "grant_epoch": "epoch-test",
        "policy_digest": "sha256:test",
        "expires_at": (expires or "2099-01-01T00:00:00Z"),
        "audit_id": "audit-test",
    }
    if revoked:
        ctx["revoked"] = True
    return ctx


def registry_document(members=("felix", "mom"), view=None):
    return {"groups": [{
        "group_id": "family",
        "name": "Family",
        "owner_member": "felix",
        "member_members": list(members),
        "knowledge_view": view or {"project_ids": ["demo-project"],
                                   "source_ids": ["*"]},
        "grant_epoch": "epoch-test",
        "created_at": "2026-10-11T04:35:44Z",
    }]}


class CrossPathFixture(unittest.TestCase):
    """Two projects in the store; the context only sees demo-project."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / "output"
        self.state = root / "state"
        # Distinct file paths per project: source_overlap is deliberately
        # fail-closed for a path that exists in several projects (it
        # cannot attribute the citation uniquely), so the fixture must
        # not create that ambiguity while testing the view check itself.
        for project, relpath in (("demo-project", "src/main.py"),
                                 ("other-project", "vendor/lib.py")):
            home = self.out / project
            home.mkdir(parents=True)
            slug = relpath.replace("/", "__") + ".knowledge.json"
            (home / slug).write_text(json.dumps({
                "file": relpath,
                "version": {"mtime": int(NOW - 3600), "size": 512},
                "verdict": "quick-summary",
                "analyzed_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 3600)),
                "derived": {"purpose": f"Entry point of {project}."},
                "anchor_top": "main L10-L42",
            }), encoding="utf-8")
        self.context_file = root / "access.json"
        self.context_file.write_text(json.dumps({
            "principalId": "felix", "sessionId": "s1",
            "jarvisNodeId": "jetson-test",
            "projectScopes": ["demo-project"],
            "sourceScopes": ["connector:demo-project"],
            "grantEpoch": "g1", "policyDigest": "pd1",
            "expiresAt": "2099-01-01T00:00:00Z", "auditId": "a1",
        }), encoding="utf-8")
        self.old = {key: os.environ.get(key) for key in ENV_KEYS}
        os.environ["UYP_OUTPUT_ROOT"] = str(self.out)
        os.environ["UYP_STATE_ROOT"] = str(self.state)
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(self.context_file)
        projects.reset_caches()

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

    def all_items(self):
        return [item for values in query_api.grouped_items().values()
                for item in values]


class ScopeEquivalenceTests(CrossPathFixture):
    """Path 1 (Studio tier) and path 3 (group tier) must agree per view."""

    def test_same_view_admits_the_same_items_on_both_tiers(self):
        context = self.context()
        studio = query_api.scoped_items(context)
        group = groups.scoped_retrieval(
            self.all_items(), group_context(), registry_document())
        self.assertEqual([i["file"] for i in studio],
                         [i["file"] for i in group])
        self.assertEqual([i["file"] for i in group], ["src/main.py"])

    def test_out_of_scope_project_hidden_on_both_tiers(self):
        context = self.context()
        for item in query_api.scoped_items(context):
            self.assertNotIn("other-project", item["file"])
        for item in groups.scoped_retrieval(
                self.all_items(), group_context(), registry_document()):
            self.assertNotIn("other-project", item["file"])
        # and the store really holds the other project (guard the fixture)
        self.assertEqual(len(self.all_items()), 2)

    def test_wildcard_group_view_still_clamped_to_registered_view(self):
        # A group context claiming "*" must not widen past the group's
        # registered view (the registered demo-project only).
        group = groups.scoped_retrieval(
            self.all_items(), group_context(project_ids=["*"]),
            registry_document())
        self.assertEqual([i["file"] for i in group], ["src/main.py"])


class FailClosedNegativeTests(CrossPathFixture):
    """The negatives that failed closed live on 2026-10-18 (Q3)."""

    def test_non_member_sees_nothing(self):
        # ly is not in the registry's member list - live: 200 + miss.
        self.assertEqual(groups.scoped_retrieval(
            self.all_items(), group_context(member="ly"),
            registry_document()), [])

    def test_expired_context_fail_closed(self):
        past = (datetime.now(timezone.utc)
                - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        self.assertEqual(groups.scoped_retrieval(
            self.all_items(),
            group_context(expires=past.replace("Z", "") + "Z"),
            registry_document()), [])

    def test_revoked_context_fail_closed(self):
        self.assertEqual(groups.scoped_retrieval(
            self.all_items(), group_context(revoked=True),
            registry_document()), [])

    def test_unknown_group_fail_closed(self):
        self.assertEqual(groups.scoped_retrieval(
            self.all_items(),
            group_context(member="felix") | {"group_id": "ghost"},
            registry_document()), [])

    def test_no_context_no_items(self):
        self.assertEqual(groups.scoped_retrieval(self.all_items(), None), [])


class EvidenceHonestyTests(CrossPathFixture):
    """The producer's cross-tier rules: gated-in or dropped, never faked."""

    def test_in_scope_citation_yields_frozen_six_with_permission_true(self):
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
        self.assertIs(record["permission_checked"], True)

    def test_out_of_scope_citation_produces_no_record(self):
        context = self.context()
        scoped = query_api.scoped_items(context)
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0},
             {"file": "vendor/lib.py", "match": 9.0}],
            scoped, gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual([r["locator"] for r in records], ["src/main.py#L10-L42"])
        for record in records:
            self.assertIs(record["permission_checked"], True)

    def test_group_tier_sources_would_gate_the_same_way(self):
        # Feeding the GROUP tier's retrieval result through the same
        # producer yields the same single record as the Studio tier -
        # one evidence semantics wherever the producer is wired in.
        context = self.context()
        group_items = groups.scoped_retrieval(
            self.all_items(), group_context(), registry_document())
        records = knowledge_evidence.build_evidence(
            [{"file": "src/main.py", "match": 4.0}], group_items,
            gate=lambda item: query_api.scope_allows(context, item))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "connector:demo-project")


class GroupScrubTests(CrossPathFixture):
    """Path 3's defense-in-depth: out-of-view citations are refused."""

    def _view(self):
        return {"project_ids": ["demo-project"], "source_ids": ["*"]}

    def test_in_view_citation_is_clean(self):
        overlap = groups.source_overlap(
            [{"file": "src/main.py"}], self._view(), self.all_items())
        self.assertTrue(overlap["clean"])
        self.assertEqual(overlap["out_of_view"], [])

    def test_out_of_view_citation_is_not_clean(self):
        overlap = groups.source_overlap(
            [{"file": "vendor/lib.py"}], self._view(),
            self.all_items())
        self.assertFalse(overlap["clean"])

    def test_unresolvable_citation_is_not_clean(self):
        overlap = groups.source_overlap(
            [{"file": "nowhere/x.py"}], self._view(), self.all_items())
        self.assertFalse(overlap["clean"])


class VoiceShapeDivergenceTests(CrossPathFixture):
    """Path 2's live shape is NOT the frozen contract (documented gap)."""

    def test_live_voice_block_is_not_contract_evidence(self):
        # If :8790 ever adopts the contract this must start failing -
        # that is the point: the divergence is pinned, not accidental.
        with self.assertRaises(Exception):
            KnowledgeEvidence.model_validate(VOICE_BLOCK_FIXTURE)

    def test_voice_block_lacks_every_frozen_field(self):
        for field in ("source_id", "source_version", "locator",
                      "permission_checked", "retrieved_at"):
            self.assertNotIn(field, VOICE_BLOCK_FIXTURE)


if __name__ == "__main__":
    unittest.main()
