"""Groups engine contracts (P10 first slice, 2026-10).

These tests pin the fail-closed discipline of Jarvis Groups: an invalid
group context yields no results (never a fallback to the unscoped store),
a group's knowledge view is the only slice of the output store its members
may retrieve, membership/view changes re-issue the grant epoch so caches
can be invalidated, and a proposed answer's cited files are checked
against the view before anything is shared.  No HomeHub, NandaTown, or
model service is needed - the registry is a local file, everything else
is pure functions over projections.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import groups  # noqa: E402
from groups import (  # noqa: E402
    GroupContextError,
    GroupRecordError,
    GroupRegistry,
    GroupViewError,
    membership_snapshot,
    membership_stale,
    normalize_view,
    scoped_items,
    scoped_retrieval,
    source_overlap,
    validate_group_context,
    view_allows,
)


def future_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**(delta or {"minutes": 10}))).isoformat().replace("+00:00", "Z")


def group_record(**overrides) -> dict:
    base = {
        "group_id": "group:research",
        "name": "Research group",
        "owner_member": "member:lee",
        "member_members": ["member:lee", "member:chen"],
        "knowledge_view": {"project_ids": ["project:alpha"], "source_ids": ["connector:alpha"]},
        "created_at": "2026-10-10T00:00:00Z",
        "grant_epoch": "epoch-1",
    }
    base.update(overrides)
    return base


def group_context(**overrides) -> dict:
    base = {
        "group_id": "group:research",
        "member_id": "member:chen",
        "jarvis_node_id": "jetson-1",
        "project_ids": ["project:alpha"],
        "source_ids": ["connector:alpha"],
        "grant_epoch": "epoch-1",
        "policy_digest": "sha256:policy",
        "expires_at": future_iso(),
        "audit_id": "audit-1",
    }
    base.update(overrides)
    return base


def knowledge_item(project: str, file: str, source: str = "mac-connector") -> dict:
    """A KnowledgeItem shaped like the output store (query_api.grouped_items)."""
    return {
        "file": file,
        "source": source,
        "derived": {"purpose": f"{file} in {project}"},
        "_out_path": f"/dev/uyp/output/{project}/{file.replace('/', '__')}.knowledge.json",
    }


class GroupRegistryTests(unittest.TestCase):
    def registry(self, directory) -> GroupRegistry:
        return GroupRegistry(str(Path(directory) / "state" / "groups.json"))

    def test_create_read_update_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            self.assertEqual(registry.load()["groups"], [], "missing file reads as empty, not an error")
            self.assertFalse(registry.path.exists(), "a read must never create the file")
            created = registry.upsert(group_record())
            self.assertEqual(created["group_id"], "group:research")
            self.assertEqual(registry.get("group:research")["name"], "Research group")
            self.assertIsNone(registry.get("group:missing"))
            self.assertTrue(registry.remove("group:research"))
            self.assertIsNone(registry.get("group:research"))
            self.assertFalse(registry.remove("group:research"))

    def test_upsert_rejects_missing_or_malformed_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            for bad in (
                {"name": "n", "owner_member": "member:lee", "knowledge_view": {"project_ids": [], "source_ids": []}},
                {**group_record(), "group_id": "not a safe id!"},
                {**group_record(), "name": "   "},
                {**group_record(), "owner_member": ""},
                {**group_record(), "member_members": "member:lee"},
                {**group_record(), "member_members": ["member:lee", 42]},
                {**group_record(), "knowledge_view": None},
                {**group_record(), "knowledge_view": {"project_ids": ["project:alpha"]}},
                {**group_record(), "knowledge_view": {"project_ids": ["bad id!"], "source_ids": []}},
            ):
                with self.assertRaises(GroupRecordError, msg=repr(bad)):
                    registry.upsert(bad)
            self.assertEqual(registry.load()["groups"], [], "rejected records are never persisted")

    def test_upsert_drops_unknown_and_secret_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            saved = registry.upsert({**group_record(), "token": "do-not-store",
                                     "accessContext": {"projectScopes": ["*"]},
                                     "filesystemPath": "/Users/private"})
            self.assertNotIn("token", saved)
            stored = json.dumps(registry.load())
            self.assertNotIn("do-not-store", stored)
            self.assertNotIn("/Users/private", stored)
            self.assertNotIn("accessContext", stored)

    def test_member_mutators_bump_epoch_only_on_real_change(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            registry.upsert(group_record(member_members=["member:lee"]))
            baseline = registry.get("group:research")
            # A no-op add/remove must not invalidate caches.
            registry.add_member("group:research", "member:lee")
            registry.remove_member("group:research", "member:ghost")
            self.assertEqual(registry.get("group:research")["grant_epoch"], baseline["grant_epoch"])
            # A real membership change re-issues the epoch and keeps created_at.
            changed = registry.add_member("group:research", "member:chen")
            self.assertIn("member:chen", changed["member_members"])
            self.assertNotEqual(changed["grant_epoch"], baseline["grant_epoch"])
            self.assertEqual(changed["created_at"], baseline["created_at"])
            shrunk = registry.remove_member("group:research", "member:chen")
            self.assertEqual(shrunk["member_members"], ["member:lee"])
            self.assertNotEqual(shrunk["grant_epoch"], changed["grant_epoch"])
            with self.assertRaises(KeyError):
                registry.add_member("group:ghost", "member:chen")

    def test_upsert_membership_edit_without_epoch_still_reissues(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            first = registry.upsert(group_record(member_members=["member:lee"], grant_epoch=None))
            edited = registry.upsert(group_record(member_members=["member:lee", "member:chen"], grant_epoch=None))
            self.assertNotEqual(edited["grant_epoch"], first["grant_epoch"], "membership edit bumps the epoch")
            repeated = registry.upsert(group_record(member_members=["member:lee", "member:chen"], grant_epoch=None))
            self.assertEqual(repeated["grant_epoch"], edited["grant_epoch"], "unchanged membership inherits the epoch")
            self.assertEqual(repeated["created_at"], first["created_at"], "created_at survives updates")
            explicit = registry.upsert(group_record(member_members=["member:lee"], grant_epoch="epoch-homehub"))
            self.assertEqual(explicit["grant_epoch"], "epoch-homehub", "an explicit reissue epoch wins")

    def test_set_view_reissues_epoch_and_is_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            registry.upsert(group_record())
            baseline = registry.get("group:research")
            unchanged = registry.set_view("group:research", group_record()["knowledge_view"])
            self.assertEqual(unchanged["grant_epoch"], baseline["grant_epoch"])
            widened = registry.set_view("group:research", {"project_ids": ["*"], "source_ids": ["*"]})
            self.assertNotEqual(widened["grant_epoch"], baseline["grant_epoch"])
            self.assertEqual(widened["knowledge_view"], {"project_ids": ["*"], "source_ids": ["*"]})
            with self.assertRaises(GroupViewError):
                registry.set_view("group:research", {"project_ids": ["*"]})

    def test_load_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            good = group_record()
            broken = group_record(group_id="group:broken", grant_epoch=None)
            registry.upsert(good)
            document = json.loads(registry.path.read_text(encoding="utf-8"))
            document["groups"].append(broken)
            registry.path.write_text(json.dumps(document), encoding="utf-8")
            loaded = registry.load()
            self.assertEqual([item["group_id"] for item in loaded["groups"]], ["group:research"],
                             "an incomplete record is dropped, not repaired")
            registry.path.write_text("{not json", encoding="utf-8")
            self.assertEqual(registry.load()["groups"], [])
            self.assertIn("warning", registry.load())
            registry.path.write_text(json.dumps({"schema_version": "something.else", "groups": [good]}), encoding="utf-8")
            self.assertEqual(registry.load()["groups"], [])

    def test_path_resolution_uses_env_and_state_root(self):
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / "explicit" / "groups.json"
            with patch.dict("os.environ", {"UYP_GROUPS_FILE": str(explicit)}, clear=False):
                self.assertEqual(GroupRegistry().path, explicit.resolve())
            with patch.dict("os.environ", {"UYP_GROUPS_FILE": "", "UYP_STATE_ROOT": directory}, clear=False):
                self.assertEqual(GroupRegistry().path, (Path(directory) / "groups.json").resolve())

    def test_members_alias_is_accepted_and_canonicalized(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registry(directory)
            saved = registry.upsert(group_record(member_members=None, members=["member:lee", "member:lee", "member:chen"]))
            self.assertEqual(saved["member_members"], ["member:lee", "member:chen"])


class GroupContextTests(unittest.TestCase):
    def test_valid_context_is_normalized(self):
        checked = validate_group_context(group_context(
            project_ids=["project:alpha", "project:alpha", "project:beta"],
            issued_at="2026-10-10T00:00:00Z",
            share_policy="summary_and_evidence_refs",
        ))
        self.assertEqual(checked["project_ids"], ["project:alpha", "project:beta"])
        self.assertEqual(checked["member_id"], "member:chen")
        self.assertTrue(checked["expires_at"].endswith("Z"))
        self.assertEqual(checked["share_policy"], "summary_and_evidence_refs")

    def test_wildcard_scopes_accepted_in_both_spellings(self):
        for spelling in ("*", ["*"], ["*", "project:alpha"]):
            checked = validate_group_context(group_context(project_ids=spelling, source_ids=spelling))
            self.assertEqual(checked["project_ids"], ["*"])
            self.assertEqual(checked["source_ids"], ["*"])

    def test_missing_fields_rejected(self):
        for field in ("group_id", "member_id", "jarvis_node_id", "project_ids", "source_ids",
                      "grant_epoch", "policy_digest", "expires_at", "audit_id"):
            value = group_context()
            del value[field]
            with self.assertRaises(GroupContextError, msg=field):
                validate_group_context(value)
        with self.assertRaises(GroupContextError):
            validate_group_context("not-an-object")

    def test_revoked_markers_rejected(self):
        for marker in ({"revoked": True}, {"validation": "revoked"}, {"validation": "expired"}):
            with self.assertRaises(GroupContextError, msg=repr(marker)):
                validate_group_context(group_context(**marker))

    def test_expired_or_malformed_expiry_rejected(self):
        now = datetime.now(timezone.utc)
        self.assertIsInstance(validate_group_context(group_context(expires_at=future_iso()), now=now), dict)
        with self.assertRaises(GroupContextError):
            validate_group_context(group_context(expires_at=future_iso()), now=now + timedelta(hours=1))
        with self.assertRaises(GroupContextError):
            validate_group_context(group_context(expires_at=future_iso(minutes=-10)))
        with self.assertRaises(GroupContextError):  # naive datetime: no timezone
            validate_group_context(group_context(expires_at="2027-01-01T00:00:00"))
        with self.assertRaises(GroupContextError):
            validate_group_context(group_context(expires_at="next tuesday"))

    def test_scope_shapes_rejected(self):
        for bad in ("project:alpha", 42, [42], [""], ["  "]):
            with self.assertRaises(GroupContextError, msg=repr(bad)):
                validate_group_context(group_context(project_ids=bad))

    def test_invalid_share_policy_rejected(self):
        with self.assertRaises(GroupContextError):
            validate_group_context(group_context(share_policy="raw_source"))


class ViewAndScopedItemsTests(unittest.TestCase):
    ITEMS = [
        knowledge_item("alpha", "src/delegation.py"),
        knowledge_item("alpha", "src/other.py"),
        knowledge_item("beta", "src/secret.py"),
    ]

    def test_view_normalization_is_strict_about_shape(self):
        self.assertEqual(normalize_view({"project_ids": [], "source_ids": []}),
                         {"project_ids": [], "source_ids": []})
        self.assertEqual(normalize_view({"project_ids": "*", "source_ids": ["connector:alpha"]}),
                         {"project_ids": ["*"], "source_ids": ["connector:alpha"]})
        self.assertEqual(normalize_view({"project_ids": ["*", "project:alpha"], "source_ids": ["*"]}),
                         {"project_ids": ["*"], "source_ids": ["*"]}, "wildcard collapses redundant ids")
        for bad in (None, [], "project:alpha", {"project_ids": ["project:alpha"]},
                    {"project_ids": ["bad id!"], "source_ids": []}):
            with self.assertRaises(GroupViewError, msg=repr(bad)):
                normalize_view(bad)

    def test_scoped_items_filters_by_project_and_source(self):
        view = {"project_ids": ["alpha"], "source_ids": ["*"]}
        self.assertEqual([item["file"] for item in scoped_items(self.ITEMS, view)],
                         ["src/delegation.py", "src/other.py"])
        view = {"project_ids": ["*"], "source_ids": ["mac-connector"]}
        self.assertEqual(len(scoped_items(self.ITEMS, view)), 3)
        view = {"project_ids": ["*"], "source_ids": ["connector:other"]}
        self.assertEqual(scoped_items(self.ITEMS, view), [])

    def test_scope_matching_accepts_both_spelling_conventions(self):
        # A view written in HomeHub capability spelling (project:/connector:)
        # must match items whose project is the bare output-root directory,
        # exactly like query_api.scope_allows.
        view = {"project_ids": ["project:alpha"], "source_ids": ["connector:alpha"]}
        self.assertEqual(len(scoped_items(self.ITEMS, view)), 2)
        self.assertTrue(view_allows(view, "alpha", "mac-connector"))
        self.assertFalse(view_allows(view, "beta", "mac-connector"))
        self.assertTrue(view_allows({"project_ids": ["*"], "source_ids": ["source:mac-connector"]},
                                    "alpha", "mac-connector"))

    def test_wildcard_semantics(self):
        everything = {"project_ids": ["*"], "source_ids": ["*"]}
        self.assertEqual(len(scoped_items(self.ITEMS, everything)), 3)
        unattributable = {"file": "src/unknown.py", "source": "mac-connector"}
        self.assertEqual(scoped_items([unattributable], everything), [unattributable],
                         "wildcard shows everything, like homehub_adapter.scope_allows")
        specific = {"project_ids": ["alpha"], "source_ids": ["mac-connector"]}
        self.assertEqual(scoped_items([unattributable], specific), [],
                         "an unattributable item is never visible under a specific view")

    def test_none_view_or_items_yield_empty_and_malformed_raises(self):
        self.assertEqual(scoped_items(self.ITEMS, None), [])
        self.assertEqual(scoped_items(None, {"project_ids": ["*"], "source_ids": ["*"]}), [])
        with self.assertRaises(GroupViewError):
            scoped_items(self.ITEMS, {"project_ids": ["*"]})

    def test_order_is_preserved(self):
        view = {"project_ids": ["*"], "source_ids": ["*"]}
        self.assertEqual([item["file"] for item in scoped_items(self.ITEMS, view)],
                         [item["file"] for item in self.ITEMS])


class IntersectViewsTests(unittest.TestCase):
    def test_wildcard_defers_to_the_other_side(self):
        meet = groups.intersect_views({"project_ids": ["*"], "source_ids": ["*"]},
                                      {"project_ids": ["project:alpha"], "source_ids": ["connector:alpha"]})
        self.assertEqual(meet, {"project_ids": ["project:alpha"], "source_ids": ["connector:alpha"]})

    def test_disjoint_views_meet_to_nothing(self):
        meet = groups.intersect_views({"project_ids": ["project:alpha"], "source_ids": ["*"]},
                                      {"project_ids": ["project:beta"], "source_ids": ["*"]})
        self.assertEqual(meet, {"project_ids": [], "source_ids": ["*"]},
                         "only the disjoint dimension empties; both-wildcard stays wildcard")
        self.assertEqual(scoped_items(SourceOverlapTests.ITEMS, meet), [],
                         "an empty project dimension scopes everything out")


class SourceOverlapTests(unittest.TestCase):
    ITEMS = [
        knowledge_item("alpha", "src/delegation.py"),
        knowledge_item("beta", "src/secret.py"),
    ]
    VIEW = {"project_ids": ["alpha"], "source_ids": ["*"]}

    def test_all_cited_sources_inside_the_view_are_clean(self):
        report = source_overlap([{"file": "src/delegation.py"}], self.VIEW, self.ITEMS)
        self.assertEqual(report["in_view"], ["src/delegation.py"])
        self.assertEqual(report["out_of_view"], [])
        self.assertEqual(report["unresolved"], [])
        self.assertTrue(report["clean"])

    def test_out_of_view_source_is_reported(self):
        report = source_overlap([{"file": "src/delegation.py"}, {"file": "src/secret.py"}], self.VIEW, self.ITEMS)
        self.assertEqual(report["in_view"], ["src/delegation.py"])
        self.assertEqual(report["out_of_view"], ["src/secret.py"])
        self.assertFalse(report["clean"])

    def test_unresolvable_citation_is_fail_closed(self):
        report = source_overlap([{"file": "src/hallucinated.py"}], self.VIEW, self.ITEMS)
        self.assertEqual(report["unresolved"], ["src/hallucinated.py"])
        self.assertFalse(report["clean"], "a citation we cannot place is never clean")

    def test_ambiguous_relpath_is_out_of_view(self):
        items = [knowledge_item("alpha", "src/shared.py"), knowledge_item("beta", "src/shared.py")]
        report = source_overlap([{"file": "src/shared.py"}], self.VIEW, items)
        self.assertEqual(report["out_of_view"], ["src/shared.py"],
                         "the same relpath in an out-of-view project is not provably safe")
        self.assertFalse(report["clean"])

    def test_bare_strings_dedup_and_declared_scope_is_honored(self):
        report = source_overlap(["src/delegation.py", "src/delegation.py"], self.VIEW, self.ITEMS)
        self.assertEqual(report["in_view"], ["src/delegation.py"])
        report = source_overlap([{"file": "src/x.py", "project_id": "alpha", "source_id": "mac-connector"}],
                                self.VIEW, self.ITEMS)
        self.assertEqual(report["in_view"], ["src/x.py"], "a declared scope resolves without an item match")
        report = source_overlap([{"file": "src/x.py", "project_id": "beta"}], self.VIEW, self.ITEMS)
        self.assertEqual(report["out_of_view"], ["src/x.py"])
        self.assertEqual(source_overlap(["src/ghost.py"], None, self.ITEMS)["unresolved"], ["src/ghost.py"],
                         "a missing view is treated as an empty view")


class MembershipInvalidationTests(unittest.TestCase):
    def test_fresh_snapshot_is_not_stale(self):
        record = group_record()
        snapshot = membership_snapshot(record)
        self.assertFalse(membership_stale(record, snapshot))

    def test_membership_change_through_registry_makes_cache_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = GroupRegistry(str(Path(directory) / "groups.json"))
            registry.upsert(group_record())
            snapshot = membership_snapshot(registry.get("group:research"))
            self.assertFalse(membership_stale(registry.get("group:research"), snapshot))
            registry.add_member("group:research", "member:park")
            self.assertTrue(membership_stale(registry.get("group:research"), snapshot))
            fresh = membership_snapshot(registry.get("group:research"))
            self.assertFalse(membership_stale(registry.get("group:research"), fresh))
            registry.remove_member("group:research", "member:park")
            self.assertTrue(membership_stale(registry.get("group:research"), fresh))

    def test_view_change_alone_makes_cache_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = GroupRegistry(str(Path(directory) / "groups.json"))
            registry.upsert(group_record())
            snapshot = membership_snapshot(registry.get("group:research"))
            registry.set_view("group:research", {"project_ids": ["*"], "source_ids": ["*"]})
            self.assertTrue(membership_stale(registry.get("group:research"), snapshot))

    def test_epoch_or_member_change_without_registry_is_caught(self):
        record = group_record()
        snapshot = membership_snapshot(record)
        self.assertTrue(membership_stale(group_record(grant_epoch="epoch-2"), snapshot),
                        "a hand-edited epoch mismatch is stale even with identical members")
        self.assertTrue(membership_stale(group_record(member_members=["member:lee", "member:chen", "member:park"]), snapshot),
                        "a member-set mismatch is stale even with an unchanged epoch")

    def test_missing_group_or_malformed_snapshot_is_stale(self):
        snapshot = membership_snapshot(group_record())
        self.assertTrue(membership_stale(None, snapshot), "a deleted group invalidates its caches")
        self.assertTrue(membership_stale("not-a-record", snapshot))
        self.assertTrue(membership_stale(group_record(), None))
        self.assertTrue(membership_stale(group_record(), {"group_id": "group:research"}), "an incomplete snapshot is stale")
        poisoned = membership_snapshot({"nope": True})
        self.assertTrue(membership_stale(group_record(), poisoned), "a poisoned snapshot never validates")


class ScopedRetrievalTests(unittest.TestCase):
    ITEMS = [
        knowledge_item("alpha", "src/delegation.py"),
        knowledge_item("alpha", "src/other.py"),
        knowledge_item("beta", "src/secret.py"),
    ]

    def test_invalid_contexts_yield_no_results_never_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = GroupRegistry(str(Path(directory) / "groups.json"))
            registry.upsert(group_record())
            for bad in (
                group_context(revoked=True),
                group_context(validation="revoked"),
                group_context(expires_at=future_iso(minutes=-5)),
                {key: value for key, value in group_context().items() if key != "audit_id"},
                "not-an-object",
                None,
            ):
                self.assertEqual(scoped_retrieval(self.ITEMS, bad, registry), [], msg=repr(bad))

    def test_context_view_is_clamped_to_the_registered_view(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = GroupRegistry(str(Path(directory) / "groups.json"))
            registry.upsert(group_record(knowledge_view={"project_ids": ["project:alpha"],
                                                         "source_ids": ["*"]}))
            # HomeHub handed the box a wildcard grant; the group still only
            # opens its registered project.
            result = scoped_retrieval(self.ITEMS, group_context(project_ids="*", source_ids="*"), registry)
            self.assertEqual([item["file"] for item in result], ["src/delegation.py", "src/other.py"])

    def test_non_member_and_unknown_group_yield_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = GroupRegistry(str(Path(directory) / "groups.json"))
            registry.upsert(group_record())
            self.assertEqual(scoped_retrieval(self.ITEMS, group_context(member_id="member:mallory"), registry), [])
            # The owner is allowed even when not listed in member_members.
            owner_view = group_context(member_id="member:lee", project_ids="*", source_ids="*")
            self.assertEqual(len(scoped_retrieval(self.ITEMS, owner_view, registry)), 2)
            self.assertEqual(scoped_retrieval(self.ITEMS, group_context(group_id="group:ghost"), registry), [])

    def test_registry_none_uses_the_context_view_only(self):
        result = scoped_retrieval(self.ITEMS, group_context(project_ids="*", source_ids="*"))
        self.assertEqual(len(result), 3)

    def test_mapping_document_registry_is_accepted_and_incomplete_records_dropped(self):
        document = {"groups": [group_record(), group_record(group_id="group:broken", grant_epoch=None)]}
        result = scoped_retrieval(self.ITEMS, group_context(project_ids="*", source_ids="*"), document)
        self.assertEqual([item["file"] for item in result], ["src/delegation.py", "src/other.py"])
        self.assertEqual(scoped_retrieval(self.ITEMS, group_context(group_id="group:broken"), document), [])


if __name__ == "__main__":
    unittest.main()
