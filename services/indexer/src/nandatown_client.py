#!/usr/bin/env python3
"""NandaTown transport for Jarvis Groups: peer discovery + group mailbox.

``groups.py`` owns the local half of a group's promise (who is in it,
which knowledge view it opens).  This module owns the transport half:
how real Jarvis boxes find each other and exchange group messages over
the NandaTown coordinator (``town.mofangpi.net``, a FastAPI coordinator
over SQLite on the home Jetson).  It is stdlib-only and deliberately
thin - no local group state, no grants, no policy.  HomeHub stays the
only authority for identity and revocation; the town stays a discovery
and delivery layer (AGENTS.md rule 1).

Honest mapping onto town semantics (the town is a run-scoped mailbox,
not a chat server):

* A town *run* is a group's coordination scope.  ``run_id`` is the
  transport-level group id; a local group record's ``group_id`` travels
  inside each message envelope, not in the URL.
* "Registration" is a *join*: participants are pre-provisioned by the
  town admin at run creation with one join token per name, and joining
  exchanges that token for a stable session (idempotent - a re-join
  returns the same session).  Capabilities are provisioned at run
  creation and cannot be self-declared, so ``register_peer`` records
  the caller's advertised capabilities locally and never widens town
  truth.  A name joined without its own token is refused by the town.
* The directory (``GET .../participants``) is the peer list.  It
  carries no liveness or verification signal, so every entry is
  projected as ``trust="advertised"``, ``status="available"`` (listed)
  - never ``"verified"``, never a HomeHub grant.
* Messages are per-recipient (no broadcast primitive): a group send
  fans out one message per group peer, each with its own message_id,
  so town delivery identity stays per-message.
* Delivery is a claim/ack mailbox with leases.  ``poll_group_messages``
  claims each pending message and acks it ``received`` (consumed).  A
  message whose envelope names a *different* group is re-offered with
  ``retryable`` instead of consumed, so it is not lost to this poller.
  Delivery is at-least-once after a lease expiry; callers dedupe on
  ``message_id``.

Fail-closed: every public method returns a safe value (``[]``,
``None``, ``False``) and records what happened (``error_code``,
``last_error``, ``unreachable``); none ever raises for transport,
auth, or malformed-response conditions.  Every request is bounded by a
5-second default timeout.

Configuration (environment, the UYP deployment convention):

* ``UYP_NANDATOWN_URL`` - coordinator base URL
  (default ``https://town.mofangpi.net``).
* ``UYP_NANDATOWN_RUN_ID`` - the active town run (the group scope).
* ``UYP_NANDATOWN_JOIN_TOKEN`` - this process's join token.  One token
  belongs to exactly one participant name; two processes that poll the
  same name compete for the same inbox, so give each consuming process
  its own town-provisioned name and token.
* ``UYP_NANDATOWN_PARTICIPANT`` - the name this client joins as
  (default ``home``; must match the join token's provisioning).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

DEFAULT_BASE_URL = "https://town.mofangpi.net"
DEFAULT_RUN_ID = "run-4a76172d8ed6"
DEFAULT_PARTICIPANT = "home"
DEFAULT_TIMEOUT = 5.0
DEFAULT_POLL_LIMIT = 50
MESSAGE_KIND = "group.message"
ACK_RECEIVED = "received"
ACK_RETRYABLE = "retryable"
# The town's public edge (Cloudflare) refuses the stdlib's default
# "Python-urllib/x.y" signature with Error 1010 (browser_signature_banned),
# so every request identifies itself as this client instead.
USER_AGENT = "uyp-nandatown/0.1"

# Transport-level error codes every caller can branch on.  They describe
# this client's view of the failure, never the town's internals.
ERROR_UNREACHABLE = "nandatown_unreachable"
ERROR_UNAUTHORIZED = "nandatown_unauthorized"
ERROR_UNKNOWN_RUN = "nandatown_unknown_run"
ERROR_RUN_FINISHED = "nandatown_run_finished"
ERROR_UNCONFIGURED = "nandatown_unconfigured"
ERROR_BAD_RESPONSE = "nandatown_bad_response"

_TRANSPORT_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp the envelopes carry; None if absent."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


class NandaTownClient:
    """One process's fail-closed HTTP session with the town coordinator.

    Instances are cheap and hold no locks; construct one per operation
    (the query API does) or reuse one for a join/register + send/poll
    sequence.  ``error_code`` / ``last_error`` / ``unreachable``
    describe the *most recent* public call, mirroring how
    ``registry_health`` reports the connector registry.
    """

    def __init__(self, base_url: str | None = None, run_id: str | None = None,
                 join_token: str | None = None,
                 participant: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = (base_url or os.environ.get("UYP_NANDATOWN_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.run_id = run_id or os.environ.get("UYP_NANDATOWN_RUN_ID") or DEFAULT_RUN_ID
        self.join_token = join_token if join_token is not None \
            else os.environ.get("UYP_NANDATOWN_JOIN_TOKEN")
        self.participant = (participant or os.environ.get("UYP_NANDATOWN_PARTICIPANT")
                            or DEFAULT_PARTICIPANT).strip()
        self.timeout = max(0.05, float(timeout))
        self.error_code: str | None = None
        self.last_error: str | None = None
        self.unreachable = False
        self._session: str | None = None

    # -- failure bookkeeping -------------------------------------------

    def _fail(self, code: str, message: str) -> None:
        self.error_code = code
        self.last_error = message
        self.unreachable = code == ERROR_UNREACHABLE

    def _clear_error(self) -> None:
        self.error_code = None
        self.last_error = None
        self.unreachable = False

    # -- transport -----------------------------------------------------

    def _request(self, method: str, path: str, body: Any = None,
                 session: str | None = None) -> tuple[int, Any] | None:
        """One bounded HTTP call; ``(status, parsed_json)`` or None.

        Never raises.  Transport failures (DNS, refused, timeout) map
        to ``ERROR_UNREACHABLE``; HTTP error statuses are surfaced with
        a code chosen by the caller-visible meaning of that endpoint.
        This method records ``ERROR_BAD_RESPONSE`` for a body that is
        not valid JSON; endpoint methods refine status-specific codes.
        """
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if session:
            headers["X-Town-Session"] = session
        request = urllib.request.Request(url, data=data, headers=headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(512).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - diagnostics only
                pass
            self._fail(ERROR_BAD_RESPONSE,
                       f"{method} {path} -> HTTP {exc.code}: {detail}".strip())
            return exc.code, None
        except _TRANSPORT_ERRORS as exc:
            self._fail(ERROR_UNREACHABLE, f"{method} {path} failed: {exc}")
            return None
        except ValueError as exc:  # invalid URL
            self._fail(ERROR_UNREACHABLE, f"{method} {path} invalid: {exc}")
            return None
        if not raw:
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._fail(ERROR_BAD_RESPONSE, f"{method} {path} returned invalid JSON")
            return None

    @staticmethod
    def _refine_status(status: int, fallback: str) -> str:
        """The caller-visible meaning of a town refusal status."""
        if status == 401 or status == 403:
            return ERROR_UNAUTHORIZED
        if status == 404:
            return ERROR_UNKNOWN_RUN
        if status == 409:
            return ERROR_RUN_FINISHED
        return fallback

    # -- session -------------------------------------------------------

    def _join(self) -> str | None:
        """Exchange the join token for a session (cached per instance).

        A join is the town's registration: idempotent, and it mints the
        same session for the same name on every re-join, so caching the
        session per instance never forks identity.
        """
        if self._session:
            return self._session
        if not self.join_token:
            self._fail(ERROR_UNCONFIGURED,
                       "UYP_NANDATOWN_JOIN_TOKEN is not set; ask the town admin "
                       "for this participant's provisioned join token")
            return None
        result = self._request("POST", f"/runs/{self.run_id}/join",
                               {"name": self.participant,
                                "token": self.join_token})
        if result is None:
            return None
        status, payload = result
        session = payload.get("session") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(session, str) or not session:
            self._fail(self._refine_status(status, ERROR_BAD_RESPONSE),
                       f"join as {self.participant!r} refused "
                       f"(HTTP {status}); the name and join token must match "
                       "the town's provisioning")
            return None
        self._session = session
        self._clear_error()
        return session

    # -- public surface ------------------------------------------------

    def health(self) -> bool:
        """Whether the coordinator answers ``GET /health`` at all."""
        result = self._request("GET", "/health")
        ok = bool(result and result[0] == 200
                  and isinstance(result[1], dict) and result[1].get("ok") is True)
        if result is not None and ok:
            self._clear_error()
        return ok

    def register_peer(self, node_id: str, name: str | None = None,
                      capabilities: Any = None) -> dict | None:
        """Join the run under ``name``; the town's registration act.

        ``node_id`` and ``capabilities`` are this node's self-declared
        metadata: they are returned in the registration record and are
        NOT written to the town (capabilities are provisioned by the
        town admin at run creation; a self-declared list never widens
        town truth).  Returns ``None`` (with ``error_code`` set) when
        the join is refused or the town is unreachable.
        """
        participant = str(name or self.participant or "").strip()
        if not participant:
            self._fail(ERROR_UNCONFIGURED, "register_peer requires a name")
            return None
        self.participant = participant
        session = self._join()
        if session is None:
            return None
        advertised = [str(item) for item in capabilities if str(item or "").strip()] \
            if isinstance(capabilities, (list, tuple)) else []
        record = self._request("GET", f"/runs/{self.run_id}/participants",
                               session=session)
        if record is not None and record[0] == 200 and isinstance(record[1], list):
            town_entry = next((entry for entry in record[1]
                               if isinstance(entry, dict)
                               and entry.get("name") == participant), None)
        else:
            town_entry = None
        return {
            "peer_id": participant,
            "node_id": str(node_id or participant),
            "name": participant,
            "session": True,
            "advertised_capabilities": advertised,
            "town_capabilities": list(town_entry.get("capabilities") or [])
            if isinstance(town_entry, dict) else [],
            "role": town_entry.get("role") if isinstance(town_entry, dict) else None,
            "run_id": self.run_id,
            "registered_at": now_iso(),
        }

    def list_peers(self) -> list[dict]:
        """The run directory projected onto the Studio peer contract.

        The town directory carries names, roles, and provisioned
        capabilities - no liveness, no trust.  Every entry is therefore
        ``trust="advertised"`` / ``status="available"`` (listed), which
        the Studio renders as directory metadata, never as a grant.
        Returns ``[]`` on any failure, with ``error_code`` set.
        """
        session = self._join()
        if session is None:
            return []
        result = self._request("GET", f"/runs/{self.run_id}/participants",
                               session=session)
        if result is None:
            return []
        status, payload = result
        if status != 200 or not isinstance(payload, list):
            self._fail(self._refine_status(status, ERROR_BAD_RESPONSE),
                       f"participant directory unavailable (HTTP {status})")
            return []
        peers = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            role = str(entry.get("role") or "").strip()
            capabilities = [str(item) for item in (entry.get("capabilities") or [])
                            if str(item or "").strip()]
            if role and role not in capabilities:
                capabilities = [role] + capabilities
            peers.append({
                "peerId": f"town:{self.run_id}:{name}",
                "nodeId": name,
                "displayLabel": name,
                "transport": "nandatown",
                "trust": "advertised",
                "status": "available",
                "capabilities": capabilities,
            })
        peers.sort(key=lambda peer: peer["nodeId"])
        self._clear_error()
        return peers

    def send_group_message(self, group_id: str, sender: str,
                           message: Any, recipients: list[str] | None = None) -> list[dict]:
        """Fan a group message out to every peer in the directory.

        The town has no broadcast primitive: each recipient gets one
        message with its own ``message_id`` (so town delivery identity
        stays per-message).  ``sender`` is recorded in the envelope as
        the declared sender; the town attributes delivery to the joined
        session's owner, which is the name this client joined as.
        ``message`` is plain text or a JSON object; the envelope also
        carries ``group_id`` and ``sent_at`` for downstream filtering.
        Returns one result row per recipient (``ok`` flags delivery);
        ``[]`` means no recipients were reachable - check
        ``error_code`` for why the directory itself failed.
        """
        if isinstance(message, dict):
            body: dict[str, Any] = dict(message)
        else:
            body = {"text": str(message)}
        body.setdefault("group_id", str(group_id or ""))
        body.setdefault("sender", str(sender or self.participant))
        body.setdefault("sent_at", now_iso())
        session = self._join()
        if session is None:
            return []
        if recipients is None:
            recipients = [peer["nodeId"] for peer in self.list_peers()
                          if peer["nodeId"] != self.participant]
            if self.error_code is not None:
                return []
        results = []
        for recipient in recipients:
            recipient = str(recipient or "").strip()
            if not recipient:
                continue
            message_id = f"msg-{uuid.uuid4().hex}"
            result = self._request(
                "POST", f"/runs/{self.run_id}/messages", session=session,
                body={"message_id": message_id, "to": recipient,
                      "kind": MESSAGE_KIND, "body": body})
            status = result[0] if result else None
            payload = result[1] if result else None
            accepted = (status == 202 or status == 200) and isinstance(payload, dict)
            row = {"to": recipient, "message_id": message_id, "ok": accepted,
                   "accepted_at": payload.get("accepted_at") if accepted else None,
                   "replay": bool(payload.get("replay")) if accepted else None}
            if not accepted:
                row["error"] = self._refine_status(
                    status or 0, self.error_code or ERROR_BAD_RESPONSE)
            results.append(row)
        return results

    def poll_group_messages(self, group_id: str,
                            since_ts: float = 0.0) -> list[dict]:
        """Claim and consume this participant's pending group messages.

        Each claimed message is acked ``received`` (consumed; the lease
        would otherwise re-offer it after expiry - delivery is
        at-least-once, dedupe on ``message_id``).  A message whose
        envelope names a different group is re-offered (``retryable``)
        instead of consumed, so it is not lost to this poller.
        ``since_ts`` filters on the envelope's sender-declared
        ``sent_at`` (the town exposes no participant-visible delivery
        timestamps); messages without a parseable ``sent_at`` are kept.
        Returns ``[]`` on failure or an empty inbox; ``error_code``
        distinguishes the two.
        """
        session = self._join()
        if session is None:
            return []
        cutoff = float(since_ts or 0.0)
        messages: list[dict] = []
        drained = False
        for _ in range(DEFAULT_POLL_LIMIT):
            result = self._request("POST", f"/runs/{self.run_id}/inbox/claim",
                                   session=session)
            if result is None:
                return messages  # transport failure is already recorded
            status, payload = result
            if status == 204:
                drained = True
                break
            if status != 200 or not isinstance(payload, dict):
                self._fail(self._refine_status(status, ERROR_BAD_RESPONSE),
                           f"inbox claim refused (HTTP {status})")
                break
            body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
            declared_group = str(body.get("group_id") or "")
            row = {
                "message_id": payload.get("message_id"),
                "from": payload.get("from"),
                "kind": payload.get("kind"),
                "group_id": declared_group or str(group_id or ""),
                "sent_at": body.get("sent_at"),
                "received_at": now_iso(),
                "body": body,
                "duplicate": bool(payload.get("duplicate")),
            }
            ack_status = ACK_RECEIVED
            include = True
            if declared_group and group_id and declared_group != str(group_id):
                # Not this group's message: put it back, never consume it.
                ack_status = ACK_RETRYABLE
                include = False
            elif cutoff > 0.0:
                sent = _epoch(body.get("sent_at"))
                if sent is not None and sent < cutoff:
                    include = False  # delivered, but older than the window
            row["acknowledged"] = self._ack(payload.get("message_id"),
                                            payload.get("fence"), ack_status)
            if include:
                messages.append(row)
        if drained:
            # An inbox drained to 204 is the normal end state, not an
            # error; a mid-loop failure keeps its honest error_code.
            self._clear_error()
        return messages

    def _ack(self, message_id: Any, fence: Any, status: str) -> bool:
        """Acknowledge one claimed message; never raises."""
        if not isinstance(message_id, str) or not isinstance(fence, str):
            return False
        result = self._request("POST", f"/runs/{self.run_id}/inbox/ack",
                               session=self._session or "",
                               body={"message_id": message_id, "fence": fence,
                                     "status": status, "note": {}})
        return bool(result and result[0] == 200
                    and isinstance(result[1], dict) and result[1].get("recorded") is True)


def default_client() -> NandaTownClient:
    """A client configured from the deployment environment."""
    return NandaTownClient()
