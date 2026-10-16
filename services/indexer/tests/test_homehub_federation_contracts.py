import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import connector_registry  # noqa: E402
from federation_protocol import (  # noqa: E402
    AGENT_IDENTITY_VERSION,
    FederationProtocolError,
    PROTOCOL_VERSION,
    validate_agent_card,
    validate_agent_message,
    validate_group_invite,
    validate_group_invite_result,
    validate_peer_metadata,
    validate_query_request,
    validate_query_response,
)
from homehub_adapter import (  # noqa: E402
    AccessContextError,
    load_context,
    load_context_for_member,
    public_projection,
    scope_allows,
    validate_context,
)
from pairing_protocol import PairingProtocolError, validate_pairing_approval  # noqa: E402


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")


def issued() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")


class AgentIdentityMessagingTests(unittest.TestCase):
    """The shared skill is shape/confidentiality validation only.

    HomeHub still owns signature verification, audience resolution, grants,
    and revocation; these tests pin that UYP never treats a legacy discovery
    card or a transport envelope as authority.
    """

    def card(self):
        return {
            "schemaVersion": AGENT_IDENTITY_VERSION,
            "cardId": "card:felix-1",
            "jarvisNodeId": "jetson-1",
            "agentUrn": "urn:jarvis:felix",
            "jarvisNumber": "J-1234-5678",
            "displayLabel": "Felix's Jarvis",
            "capabilities": ["project.search", "group.message"],
            "issuer": "homehub",
            "audience": "nanda-town",
            "issuedAt": issued(),
            "expiresAt": future(),
            "revocationRef": "homehub:card:felix-1",
            "keyFingerprint": "sha256:key",
            "signature": "homehub-signature",
        }

    def message(self):
        return {
            "schemaVersion": AGENT_IDENTITY_VERSION,
            "messageId": "msg:1",
            "kind": "agent.ask",
            "requestId": "req:1",
            "senderNodeId": "jetson-1",
            "receiverNodeId": "robin-jetson",
            "nonce": "nonce:1",
            "issuedAt": issued(),
            "expiresAt": future(),
            "audience": "robin-jetson",
            "authorizationRef": "homehub:delegation:1",
            "contactId": "contact:robin",
            "scope": {"sharePolicy": "summary_only", "projectScopes": ["project:alpha"]},
            "body": {"question": "Which project has the parser?"},
        }

    def test_verified_card_shape_is_normalized_but_not_trusted(self):
        normalized = validate_agent_card(self.card(), audience="nanda-town")
        self.assertEqual(normalized["agentUrn"], "urn:jarvis:felix")
        # A HomeHub signature is data here; UYP has no issuer key and makes no
        # claim that this card is verified merely because the shape is valid.
        legacy = {"display": "Felix's Jarvis", "number": "J-1234-5678",
                  "urn": "urn:jarvis:felix", "town": {"participant": "home"}}
        with self.assertRaises(FederationProtocolError):
            validate_agent_card(legacy)

    def test_card_rejects_wrong_audience_or_revocation(self):
        with self.assertRaises(FederationProtocolError):
            validate_agent_card(self.card(), audience="other-town")
        revoked = self.card()
        revoked["revoked"] = True
        with self.assertRaises(FederationProtocolError):
            validate_agent_card(revoked)

    def test_message_requires_scope_and_never_carries_authority(self):
        normalized = validate_agent_message(self.message())
        self.assertEqual(normalized["scope"]["sharePolicy"], "summary_only")
        forbidden = self.message()
        forbidden["token"] = "secret"
        with self.assertRaises(FederationProtocolError):
            validate_agent_message(forbidden)
        forbidden = self.message()
        forbidden["body"] = {"filesystemPath": "/private/source"}
        with self.assertRaises(FederationProtocolError):
            validate_agent_message(forbidden)

    def test_message_requires_conversation_binding_and_expiry(self):
        no_contact = self.message()
        del no_contact["contactId"]
        with self.assertRaises(FederationProtocolError):
            validate_agent_message(no_contact)
        expired = self.message()
        expired["expiresAt"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(FederationProtocolError):
            validate_agent_message(expired)

    def test_message_dual_reads_legacy_type_and_normalizes_both_aliases(self):
        legacy = self.message()
        del legacy["kind"]
        legacy["type"] = "agent.ask"
        normalized = validate_agent_message(legacy)
        self.assertEqual(normalized["kind"], "agent.ask")
        self.assertEqual(normalized["type"], "agent.ask")

        dual = self.message()
        dual["type"] = dual["kind"]
        normalized = validate_agent_message(dual)
        self.assertEqual(normalized["kind"], normalized["type"])

    def test_message_rejects_conflicting_kind_and_type(self):
        conflicting = self.message()
        conflicting["type"] = "group.message"
        with self.assertRaisesRegex(FederationProtocolError, "kind/type mismatch"):
            validate_agent_message(conflicting)
        missing = self.message()
        del missing["kind"]
        with self.assertRaisesRegex(FederationProtocolError, "kind or type"):
            validate_agent_message(missing)


class HomeHubContextTests(unittest.TestCase):
    def context(self):
        return {
            "principalId": "p1",
            "sessionId": "s1",
            "jarvisNodeId": "jetson-1",
            "projectScopes": ["project-a", "project-a"],
            "sourceScopes": ["connector:a"],
            "grantEpoch": "epoch-1",
            "policyDigest": "sha256:policy",
            "expiresAt": future(),
            "auditId": "audit-1",
        }

    def test_context_is_normalized_and_capability_scoped(self):
        checked = validate_context(self.context())
        self.assertEqual(checked["projectScopes"], ["project-a"])
        self.assertTrue(scope_allows(checked, "project-a", "connector:a"))
        self.assertFalse(scope_allows(checked, "project-b", "connector:a"))
        self.assertEqual(public_projection(checked)["projectScopeCount"], 1)

    def test_expired_or_incomplete_context_fails_closed(self):
        value = self.context()
        value["expiresAt"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(AccessContextError):
            validate_context(value)
        value = self.context()
        del value["auditId"]
        with self.assertRaises(AccessContextError):
            validate_context(value)

    def test_http_projection_uses_token_file_and_validates_homehub_shape(self):
        payload = json.dumps(self.context()).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return payload

        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "homehub.token"
            token_file.write_text("session-token\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5120/api/uyp/access-context",
                    "UYP_HOMEHUB_TOKEN_FILE": str(token_file),
                    "UYP_ACCESS_CONTEXT_FILE": "",
                },
                clear=False,
            ), patch("homehub_adapter.urllib.request.urlopen", return_value=Response()) as opened:
                checked = load_context()
            self.assertEqual(checked["principalId"], "p1")
            request = opened.call_args.args[0]
            self.assertEqual(request.headers.get("Authorization"), "Bearer session-token")

    def test_http_projection_accepts_homehub_transport_envelope(self):
        payload = json.dumps({"status": "ok", "accessContext": self.context()}).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return payload

        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "homehub.token"
            token_file.write_text("session-token\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5120/api/uyp/access-context",
                    "UYP_HOMEHUB_TOKEN_FILE": str(token_file),
                    "UYP_ACCESS_CONTEXT_FILE": "",
                },
                clear=False,
            ), patch("homehub_adapter.urllib.request.urlopen", return_value=Response()):
                checked = load_context()
            self.assertEqual(checked["projectScopes"], ["project-a"])

    def test_http_projection_failure_remains_unavailable(self):
        with patch.dict(
            "os.environ",
            {"UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5120/api/uyp/access-context", "UYP_ACCESS_CONTEXT_FILE": ""},
            clear=False,
        ), patch("homehub_adapter.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(load_context())

    def test_http_projection_takes_precedence_over_local_projection(self):
        remote = self.context()
        remote["grantEpoch"] = "remote-epoch"
        payload = json.dumps(remote).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return payload

        with tempfile.TemporaryDirectory() as directory:
            local_file = Path(directory) / "access-context.json"
            local = self.context()
            local["grantEpoch"] = "stale-local-epoch"
            local_file.write_text(json.dumps(local), encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "UYP_ACCESS_CONTEXT_FILE": str(local_file),
                    "UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5120/api/uyp/access-context",
                },
                clear=False,
            ), patch("homehub_adapter.urllib.request.urlopen", return_value=Response()):
                checked = load_context()
            self.assertEqual(checked["grantEpoch"], "remote-epoch")


class MemberContextResolutionTests(unittest.TestCase):
    """load_context_for_member: the box credential resolves the member's
    own projection, or nothing - never the box context."""

    def member_context(self, member, projects=("project-a",)):
        return {
            "principalId": member,
            "sessionId": "s1",
            "jarvisNodeId": "jetson-1",
            "projectScopes": list(projects),
            "sourceScopes": [f"connector:{project}" for project in projects],
            "grantEpoch": "epoch-1",
            "policyDigest": "sha256:policy",
            "expiresAt": future(),
            "auditId": "audit-1",
        }

    def _resolve(self, payload, member="ly"):
        body = json.dumps({"status": "ok", "accessContext": payload}).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return body

        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "homehub.token"
            token_file.write_text("box-token\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5121/api/uyp/access-context",
                    "UYP_HOMEHUB_TOKEN_FILE": str(token_file),
                    "UYP_ACCESS_CONTEXT_FILE": "",
                },
                clear=False,
            ), patch("homehub_adapter.urllib.request.urlopen", return_value=Response()) as opened:
                result = load_context_for_member(member)
            request = opened.call_args.args[0]
        return result, request

    def test_member_context_sends_box_bearer_and_member_selector(self):
        result, request = self._resolve(self.member_context("ly"))
        self.assertEqual(result["principalId"], "ly")
        self.assertEqual(result["projectScopes"], ["project-a"])
        # The SERVICE bearer is presented unchanged; only the subject
        # selector travels with the request.
        self.assertTrue(request.full_url.endswith("member=ly"))
        self.assertEqual(request.headers.get("Authorization"), "Bearer box-token")

    def test_member_context_for_another_principal_is_denied(self):
        # HomeHub answering a member request with the BOX's own context
        # (or any other principal) is the bug class: it must deny here.
        result, _ = self._resolve(self.member_context("jetson-box"))
        self.assertIsNone(result)

    def test_member_context_with_empty_scopes_is_denied(self):
        # A valid projection with no project scopes is this member's
        # honest denial, never a fallback to the service-level context.
        result, _ = self._resolve(self.member_context("ly", projects=()))
        self.assertIsNone(result)

    def test_member_context_requires_url_and_member(self):
        with patch.dict(
            "os.environ", {"UYP_HOMEHUB_ACCESS_CONTEXT_URL": ""}, clear=False
        ), patch("homehub_adapter.urllib.request.urlopen") as opened:
            self.assertIsNone(load_context_for_member("ly"))
            opened.assert_not_called()
        with patch.dict(
            "os.environ",
            {"UYP_HOMEHUB_ACCESS_CONTEXT_URL": "http://127.0.0.1:5121/api/uyp/access-context"},
            clear=False,
        ), patch("homehub_adapter.urllib.request.urlopen") as opened:
            self.assertIsNone(load_context_for_member("   "))
            opened.assert_not_called()


class ConnectorRegistryContractTests(unittest.TestCase):
    def test_registry_is_atomic_and_refuses_secrets_or_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_path = str(Path(directory) / "nested" / "registry.json")
            entry = connector_registry.upsert_connector({
                "connectorId": "connector:mac",
                "nodeId": "jetson-1",
                "label": "Mac source",
                "transport": "cloudflare",
                "state": "pending",
                "manifestState": "pending",
                "sourceIds": ["source:mac"],
                "capabilities": ["manifest", "read_range"],
                "endpoint": "https://example.test",
            }, registry_path)
            self.assertEqual(connector_registry.load_registry(registry_path)["connectors"][0]["state"], "pending")
            # The registry intentionally drops credentials, source paths, and
            # unsupported fields rather than persisting them.
            connector_registry.upsert_connector({**entry, "token": "do-not-store", "path": "/Users/private"}, registry_path)
            saved = connector_registry.load_registry(registry_path)
            self.assertNotIn("token", json.dumps(saved))
            self.assertNotIn("/Users/private", json.dumps(saved))


class FederationProtocolTests(unittest.TestCase):
    def request(self):
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": "req-1",
            "groupId": "group-1",
            "senderNodeId": "jetson-a",
            "recipientNodeId": "jetson-b",
            "operation": "project.search",
            "query": "find the onboarding path",
            "nonce": "nonce-1",
            "expiresAt": future(),
            "audience": "owner-group",
        }

    def test_request_and_public_peer(self):
        checked = validate_query_request(self.request())
        self.assertEqual(checked["operation"], "project.search")
        peer = validate_peer_metadata({
            "peerId": "peer-1", "nodeId": "jetson-b", "displayLabel": "Research Jarvis",
            "transport": "cloudflare", "status": "discoverable", "capabilities": ["project.search"],
        })
        self.assertEqual(peer["nodeId"], "jetson-b")

    def test_request_expiry_and_response_source_leak_fail(self):
        request = self.request()
        request["expiresAt"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(FederationProtocolError):
            validate_query_request(request)
        with self.assertRaises(FederationProtocolError):
            validate_query_response({
                "protocolVersion": PROTOCOL_VERSION, "requestId": "req-1", "producingJarvis": "jetson-b",
                "status": "ok", "visibility": "summary", "knowledgeVersion": "v1", "auditId": "audit-1",
                "rawSource": "private bytes",
            })

    def test_group_invite_is_a_draft_and_result_carries_no_grant(self):
        invite = validate_group_invite({
            "protocolVersion": PROTOCOL_VERSION, "inviteId": "invite-1", "groupId": "group-1",
            "inviterNodeId": "jetson-a", "inviteeNodeId": "jetson-b", "audience": "owner-group",
            "sharePolicy": "summary_and_evidence_refs", "nonce": "nonce-1", "expiresAt": future(),
            "auditId": "audit-1", "requestedProjectScopes": ["project:a"],
            "requestedSourceScopes": ["connector:a"],
        })
        self.assertEqual(invite["requestedProjectScopes"], ["project:a"])
        result = validate_group_invite_result({
            "protocolVersion": PROTOCOL_VERSION, "inviteId": "invite-1", "groupId": "group-1",
            "status": "pending", "auditId": "audit-2",
        })
        self.assertEqual(result["status"], "pending")
        with self.assertRaises(FederationProtocolError):
            validate_group_invite({
                "protocolVersion": PROTOCOL_VERSION, "inviteId": "invite-1", "groupId": "group-1",
                "inviterNodeId": "jetson-a", "inviteeNodeId": "jetson-b", "audience": "owner-group",
                "sharePolicy": "summary_only", "nonce": "nonce-1", "expiresAt": future(),
                "auditId": "audit-1", "grant": {"projectScopes": ["*"]},
            })


class PairingProtocolTests(unittest.TestCase):
    def approval(self):
        return {
            "approvalId": "approval-1", "homeHubDeviceId": "home-1", "jetsonNodeId": "jetson-1",
            "connectorId": "connector:mac", "nonce": "nonce-1", "grantEpoch": "epoch-1",
            "auditId": "audit-1", "expiresAt": future(), "transport": "cloudflare",
            "endpoint": "https://jarvis.example.test:443/status?token=secret",
        }

    def test_pairing_approval_is_metadata_only(self):
        value = self.approval()
        # A deployment controller should pass an origin; query parameters are
        # rejected so a token cannot be smuggled into the registry.
        value["endpoint"] = "https://jarvis.example.test:443/status"
        checked = validate_pairing_approval(value)
        self.assertEqual(checked["endpoint"], "https://jarvis.example.test:443")
        with self.assertRaises(PairingProtocolError):
            validate_pairing_approval({**value, "pairing_code": "123456"})

    def test_cloudflare_requires_https_and_expiry(self):
        value = self.approval()
        value["endpoint"] = "http://192.0.2.1:8787"
        with self.assertRaises(PairingProtocolError):
            validate_pairing_approval(value)


if __name__ == "__main__":
    unittest.main()
