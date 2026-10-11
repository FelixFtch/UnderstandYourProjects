"""Groups HTTP surface contracts (P10 query_api integration, 2026-10).

These tests pin the wiring between the groups engine (groups.py) and the
query API: groups are created and dissolved by their owner over HTTP,
listed by owner (all) or member (own), and searched through the same
fail-closed pipeline - validate context -> registry membership -> view
intersection -> pre-retrieval filter -> synthesis -> source-overlap
post-check.  "不同群看到不同知识": a member's search answers only from the
group's knowledge view, a non-member gets the canonical miss sentence, and
an answer citing files outside the view is refused with that same sentence.

All servers are loopback; the search synthesis is faked at the query_api
seam (no Ollama) while the scoping, validation, and overlap checks run
real.  The registry is a real GroupRegistry over a temp state file.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402


def future_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**(delta or {"minutes": 10}))).isoformat().replace("+00:00", "Z")


def group_context(**overrides) -> dict:
    """A HomeHub-issued group context projection for the X-Group-Context path."""
    base = {
        "group_id": "group:demo",
        "member_id": "ly",
        "jarvis_node_id": "jetson-1",
        "project_ids": ["*"],
        "source_ids": ["*"],
        "grant_epoch": "epoch-homehub",
        "policy_digest": "sha256:policy",
        "expires_at": future_iso(),
        "audit_id": "audit-group",
    }
    base.update(overrides)
    return base


class QueryApiGroupsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for project, relpath, purpose in (
            ("demo-project", "src/main.py", "Entry point with 委托签名 signing"),
            ("other-project", "lib/other.py", "Memory store implementation"),
        ):
            project_dir = root / "output" / project
            project_dir.mkdir(parents=True)
            stem = relpath.replace("/", "__")
            (project_dir / f"{stem}.knowledge.json").write_text(json.dumps({
                "file": relpath,
                "version": {"mtime": "2026-10-09T12:00:00Z"},
                "verdict": "quick-summary",
                "analyzed_at": "2026-10-09T12:00:00Z",
                "derived": {"purpose": purpose},
            }), encoding="utf-8")
        self.context_file = root / "access.json"
        self._write_principal("felix")
        self.groups_file = root / "state" / "groups.json"
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_ACCESS_CONTEXT_FILE", "UYP_HOMEHUB_ACCESS_CONTEXT_URL",
            "UYP_HOMEHUB_TOKEN_FILE", "UYP_OWNER_MEMBER")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(self.groups_file)
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(self.context_file)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        os.environ.pop("UYP_OWNER_MEMBER", None)
        # The preemptive lock is global (/tmp): make each test start clean.
        for path in (query_api.INTERACTIVE_LOCK,):
            try:
                os.remove(path)
            except OSError:
                pass
        # Fake search synthesis at the query_api seam: no Ollama, and the
        # scoped items it receives are recorded so tests can assert the
        # group view actually filtered the store.
        self.search_calls: list = []

        def fake_search_answer(question, items):
            self.search_calls.append({"question": question, "items": list(items)})
            if not items:
                return {"answer": query_api.MISS_SENTENCE, "sources": [], "confidence": "none"}
            return {
                "answer": f"{question} 在 {items[0]['file']} 附近。",
                "sources": [{"file": item["file"], "match": 4.0} for item in items[:2]],
                "confidence": "high",
            }

        patcher = patch.object(query_api, "search_answer", fake_search_answer)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Real query API on an ephemeral loopback port, voice guard ON.
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            os.remove(query_api.INTERACTIVE_LOCK)
        except OSError:
            pass
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------

    def _write_principal(self, principal: str) -> None:
        self.context_file.write_text(json.dumps({
            "principalId": principal,
            "sessionId": f"session-{principal}",
            "jarvisNodeId": "jetson-1",
            "projectScopes": ["*"],
            "sourceScopes": ["*"],
            "grantEpoch": f"epoch-{principal}",
            "policyDigest": "sha256:policy",
            "expiresAt": "2099-01-01T00:00:00Z",
            "auditId": f"audit-{principal}",
        }), encoding="utf-8")

    def _request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.api.server_address[1], path),
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _create_group(self, **overrides):
        body = {
            "group_id": "group:demo",
            "name": "Demo group",
            "owner_member": "felix",
            "member_members": ["felix", "ly"],
            "knowledge_view": {"project_ids": ["demo-project"], "source_ids": ["connector:demo-project"]},
        }
        body.update(overrides)
        return self._request("POST", "/api/groups", body)

    def _group_search(self, group_id="group:demo", query="哪里实现了委托签名", **extra):
        body = {"query": query}
        body.update(extra)
        return self._request("POST", f"/api/groups/{group_id}/search", body)

    # ---- create / list / delete cycle ---------------------------------------

    def test_create_list_delete_cycle(self):
        status, body = self._create_group()
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        record = body["group"]
        self.assertEqual(record["group_id"], "group:demo")
        self.assertEqual(record["owner_member"], "felix")
        self.assertEqual(record["member_members"], ["felix", "ly"])
        self.assertEqual(record["knowledge_view"], {"project_ids": ["demo-project"], "source_ids": ["connector:demo-project"]})
        self.assertTrue(record["created_at"])
        self.assertTrue(record["grant_epoch"])
        # The registry is durable state, not just a response echo.
        on_disk = json.loads(self.groups_file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema_version"], "uyp.groups.v1")
        self.assertEqual([item["group_id"] for item in on_disk["groups"]], ["group:demo"])
        # Owner (a member of the group) lists it.
        status, listing = self._request("GET", "/api/groups")
        self.assertEqual(status, 200)
        self.assertTrue(listing["ok"])
        self.assertEqual([item["group_id"] for item in listing["groups"]], ["group:demo"])
        # Dissolve (owner only), then the listing is empty again.
        status, dissolved = self._request("DELETE", "/api/groups/group:demo")
        self.assertEqual(status, 200)
        self.assertTrue(dissolved["ok"])
        self.assertTrue(dissolved["revoked"])
        status, listing = self._request("GET", "/api/groups")
        self.assertEqual(listing["groups"], [])

    def test_create_requires_owner_principal_match(self):
        # A member cannot mint a group in someone else's name.
        status, body = self._create_group(owner_member="lee")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "owner_session_required")
        # Both id spellings of the same member are the same owner.
        status, body = self._create_group(owner_member="member:felix")
        self.assertEqual(status, 201)
        # No HomeHub context at all: fail closed, no anonymous creation.
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        status, body = self._create_group()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "access_context_unavailable")

    def test_create_rejects_invalid_records(self):
        status, body = self._create_group(knowledge_view=None)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_group")
        status, body = self._create_group(knowledge_view={"project_ids": 5, "source_ids": []})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_group")
        status, body = self._create_group(group_id="bad id with spaces")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_group")
        status, _ = self._request("GET", "/api/groups")
        self.assertEqual(status, 200)

    def test_delete_requires_group_owner(self):
        self._create_group()
        self._write_principal("ly")
        status, body = self._request("DELETE", "/api/groups/group:demo")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "owner_session_required")
        # The group survives a non-owner delete attempt.
        self._write_principal("felix")
        status, listing = self._request("GET", "/api/groups")
        self.assertEqual([item["group_id"] for item in listing["groups"]], ["group:demo"])

    def test_delete_unknown_group_is_404(self):
        status, body = self._request("DELETE", "/api/groups/group:ghost")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "group_not_found")

    # ---- group search: "不同群看到不同知识" --------------------------------

    def test_member_search_scopes_to_group_view(self):
        self._create_group()
        status, body = self._group_search(member_id="ly")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["groupId"], "group:demo")
        self.assertEqual(body["memberId"], "ly")
        # ly is a member: she sees exactly the group's view - the
        # demo-project slice, never other-project.
        self.assertEqual(len(self.search_calls), 1)
        self.assertEqual([item["file"] for item in self.search_calls[0]["items"]], ["src/main.py"])
        self.assertEqual(body["sources"][0]["file"], "src/main.py")
        self.assertNotEqual(body["answer"], query_api.MISS_SENTENCE)

    def test_non_member_search_gets_miss_sentence(self):
        self._create_group()
        status, body = self._group_search(member_id="stranger")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["answer"], query_api.MISS_SENTENCE)
        self.assertEqual(body["sources"], [])
        # scoped_retrieval failed the membership check: synthesis saw nothing.
        self.assertEqual(self.search_calls[0]["items"], [])

    def test_wildcard_view_sees_all_projects(self):
        self._create_group(
            group_id="group:wide",
            knowledge_view={"project_ids": "*", "source_ids": "*"},
        )
        status, body = self._group_search(group_id="group:wide", member_id="ly")
        self.assertEqual(status, 200)
        # The wildcard group opens the whole store: both projects reach
        # synthesis, in contrast with the scoped group above.
        self.assertEqual(sorted(item["file"] for item in self.search_calls[0]["items"]),
                         ["lib/other.py", "src/main.py"])
        self.assertEqual(len(body["sources"]), 2)

    def test_homehub_context_header_is_clamped_to_registered_view(self):
        # HomeHub issues a wildcard grant (X-Group-Context); the registered
        # view clamps it back to the demo-project slice - the core P10
        # primitive, now over HTTP.
        self._create_group()
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Group-Context": json.dumps(group_context())},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["memberId"], "ly")
        self.assertEqual([item["file"] for item in self.search_calls[0]["items"]], ["src/main.py"])

    def test_invalid_group_context_header_is_denied(self):
        self._create_group()
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Group-Context": json.dumps(group_context(expires_at="2020-01-01T00:00:00Z"))},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "group_context_invalid")
        self.assertEqual(self.search_calls, [])
        # A header speaking for a different group than the path is refused.
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Group-Context": json.dumps(group_context(group_id="group:other"))},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "group_context_mismatch")

    def test_dissolved_group_search_is_denied(self):
        self._create_group()
        self._request("DELETE", "/api/groups/group:demo")
        status, body = self._group_search(member_id="ly")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "group_not_found")
        self.assertEqual(self.search_calls, [])
        # A still-presented HomeHub projection for the dissolved group also
        # yields nothing - the registry no longer knows it, so no fallback.
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Group-Context": json.dumps(group_context())},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["answer"], query_api.MISS_SENTENCE)

    def test_out_of_view_citation_is_replaced_with_miss_sentence(self):
        self._create_group()
        with patch.object(query_api, "search_answer", return_value={
            "answer": "委托签名在 lib/other.py 实现。",
            "sources": [{"file": "lib/other.py", "match": 9.0}],
            "confidence": "high",
        }):
            status, body = self._group_search(member_id="ly")
        self.assertEqual(status, 200)
        # The synthesis cited a file outside the group view (other-project):
        # refuse with the canonical miss sentence, share no paths, no partials.
        self.assertEqual(body["answer"], query_api.MISS_SENTENCE)
        self.assertEqual(body["sources"], [])
        self.assertEqual(body["confidence"], "none")
        self.assertTrue(body["scrubbed"])
        self.assertNotIn("lib/other.py", json.dumps(body))

    def test_group_search_touches_preemptive_lock(self):
        # 语音>查询>索引: group search sets the same in-flight flag
        # knowledge_search does before synthesis, so indexing yields.
        self._create_group()
        lock_state: list = []

        def probing_answer(question, items):
            lock_state.append(os.path.exists(query_api.INTERACTIVE_LOCK))
            return {"answer": "ok", "sources": [], "confidence": "high"}

        with patch.object(query_api, "search_answer", probing_answer):
            status, body = self._group_search(member_id="ly")
        self.assertEqual(status, 200)
        self.assertEqual(lock_state, [True])

    def test_voice_member_header_selects_requesting_member(self):
        # The voice chain (the pin) calls with X-Agent-Member on loopback
        # and no body member: that header is the requesting member, and
        # registry membership still decides what they see.
        self._create_group()
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Agent-Member": "ly"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["memberId"], "ly")
        self.assertEqual([item["file"] for item in self.search_calls[0]["items"]], ["src/main.py"])
        # A non-member voice member gets the miss sentence, not the view.
        status, body = self._request(
            "POST", "/api/groups/group:demo/search",
            body={"query": "哪里实现了委托签名"},
            headers={"X-Agent-Member": "stranger"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["answer"], query_api.MISS_SENTENCE)

    def test_search_requires_query_and_member(self):
        self._create_group()
        status, body = self._group_search(query="  ")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "query_required")
        # No member resolvable (no body member, no caller principal): the
        # group tier fails closed instead of assuming the box.
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        status, body = self._group_search()
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "member_required")
        self.assertEqual(self.search_calls, [])

    # ---- listing visibility --------------------------------------------------

    def test_owner_sees_all_member_sees_own(self):
        self._create_group(member_members=["felix"])  # ly is NOT a member
        self._write_principal("ly")
        status, body = self._create_group(
            group_id="group:ly", name="Ly's group", owner_member="ly",
            member_members=["ly"],
            knowledge_view={"project_ids": ["other-project"], "source_ids": ["connector:other-project"]},
        )
        self.assertEqual(status, 201)
        # ly (not the owner pin) sees only her own group.
        status, listing = self._request("GET", "/api/groups")
        self.assertEqual([item["group_id"] for item in listing["groups"]], ["group:ly"])
        self.assertFalse(listing["ownerView"])
        # The deployment's owner pin sees the whole registry.
        os.environ["UYP_OWNER_MEMBER"] = "felix"
        self._write_principal("felix")
        status, listing = self._request("GET", "/api/groups")
        self.assertTrue(listing["ownerView"])
        self.assertEqual(sorted(item["group_id"] for item in listing["groups"]),
                         ["group:demo", "group:ly"])
        # The owner pin is exact-member, not a prefix match.
        os.environ["UYP_OWNER_MEMBER"] = "fe"
        status, listing = self._request("GET", "/api/groups")
        self.assertFalse(listing["ownerView"])

    def test_listing_requires_access_context(self):
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        status, body = self._request("GET", "/api/groups")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "access_context_unavailable")


if __name__ == "__main__":
    unittest.main()
