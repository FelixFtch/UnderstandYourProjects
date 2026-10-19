"""E7 Phase 0 connector-facing contracts (final architecture v2.1,
connector receipt unification).

Three frozen shapes cover every result a connector can return; a
connector picks by what the request IS, never by what it wishes were
true:

    action    -> ConnectorReceipt   (something was asked to happen)
    knowledge -> KnowledgeEvidence  (something was looked up)
    long task -> TaskStatus         (work that outlives the turn)

Iron rules pinned here and in the freeze tests:

- accepted means the connector RECEIVED the instruction; completed
  means real completion evidence exists (e.g. a device read-back
  match).  A remote "request accepted" is never voiced or recorded as
  completed (hard rule 4 at the connector boundary).
- KnowledgeEvidence is retrieval evidence, not action completion:
  there is no completed concept on the query path.
- TaskStatus never fakes a synchronous completion: long work is
  returned queued/running and finishes by later TaskStatus records.

The connector plane is deliberately narrower than the E0 harness
plane: ConnectorReceipt is what a CONNECTOR returns; the harness
broker projects it into the E0 ExecutionReceipt (adding principal_id,
policy_version, registry_version) when the outcome enters the single
execution fact source.  Ack is reused from the E0 sheet so both
planes speak one acknowledgement vocabulary.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from harness_contracts.models import Ack, VersionedContract


# --- Enumerations (value sets pinned by the freeze tests). ---


class ConnectorStatus(str, Enum):
    """ConnectorReceipt state machine (E7 Phase 0).

    queued / accepted / running / completed / failed / denied /
    expired / cancelled.  Async work walks queued -> running -> a
    terminal state.  The pre-dispatch harness states (received,
    awaiting_slot, awaiting_confirmation, dispatched) do not exist at
    the connector boundary: a connector only ever sees dispatched
    work.
    """

    QUEUED = "queued"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TaskState(str, Enum):
    """Long-task lifecycle (E7 Phase 0): queued -> running -> terminal."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --- The three E7 connector contracts. ---


class ConnectorReceipt(VersionedContract):
    """The unified return shape of every ACTION connector (E7 target):

        {"request_id": "req_123", "action_id": "act_123",
         "capability_id": "some.capability", "authorized": true,
         "dispatched": true,
         "ack": {"received": true, "connector_request_id": "remote_456"},
         "read_back": {}, "final_status": "accepted", "error": null,
         "audit_ref": "audit_123"}

    Semantics (iron rules):

    - accepted = the instruction was received by the connector.
      Nothing more.  completed = real completion evidence was
      obtained (e.g. the device read_back matches the requested
      state).  A remote replying "request accepted" is NEVER voiced
      or recorded as completed.
    - completed requires ack.received AND a NON-EMPTY read_back.
      Whether a capability may reach completed at all is declared by
      the capability manifest's readback_required flag: a capability
      that cannot read its effect back can only ever honestly be
      accepted, never completed.
    - audit_ref ties the receipt to the audit row that recorded the
      dispatch (local audit id, remote operation id, or both).

    Validation rules (model invariants):

    - authorized=false requires dispatched=false AND
      final_status=denied: a denial dispatches nothing.
    - final_status in (queued, accepted, running, completed)
      requires dispatched=true and ack.received=true: the connector
      cannot hold, run or finish work it never received.
    """

    request_id: str
    action_id: str
    capability_id: str
    authorized: bool
    dispatched: bool
    ack: Ack
    read_back: dict[str, Any] | None
    final_status: ConnectorStatus
    error: str | None = None
    audit_ref: str

    @model_validator(mode="after")
    def _invariants(self) -> "ConnectorReceipt":
        if not self.authorized:
            if self.dispatched:
                raise ValueError(
                    "authorized=false requires dispatched=false "
                    "(a denial dispatches nothing)"
                )
            if self.final_status is not ConnectorStatus.DENIED:
                raise ValueError(
                    "authorized=false requires final_status=denied"
                )
        if self.final_status in (
            ConnectorStatus.QUEUED,
            ConnectorStatus.ACCEPTED,
            ConnectorStatus.RUNNING,
            ConnectorStatus.COMPLETED,
        ):
            if not self.dispatched or not self.ack.received:
                raise ValueError(
                    f"final_status={self.final_status.value} requires "
                    "dispatched=true and ack.received=true"
                )
        if self.final_status is ConnectorStatus.COMPLETED and not (
            self.read_back
        ):
            raise ValueError(
                "final_status=completed requires a non-empty read_back "
                "(accepted != completed)"
            )
        return self

    @classmethod
    def conclude(
        cls,
        *,
        request_id: str,
        action_id: str,
        capability_id: str,
        authorized: bool,
        dispatched: bool,
        ack: Ack,
        read_back: dict[str, Any] | None = None,
        error: str | None = None,
        audit_ref: str,
    ) -> "ConnectorReceipt":
        """Derive the honest final_status from the dispatch outcome.

        denied when not authorized; failed when never dispatched;
        completed only when ack.received AND a non-empty read_back;
        accepted when acked without read-back evidence.  Adapters
        that own a live remote lifecycle (queued / running / expired /
        cancelled) construct the model directly instead of
        concluding.
        """
        if not authorized:
            final_status = ConnectorStatus.DENIED
        elif not dispatched:
            final_status = ConnectorStatus.FAILED
        elif ack.received and read_back:
            final_status = ConnectorStatus.COMPLETED
        elif ack.received:
            final_status = ConnectorStatus.ACCEPTED
        else:
            final_status = ConnectorStatus.FAILED
        return cls(
            request_id=request_id,
            action_id=action_id,
            capability_id=capability_id,
            authorized=authorized,
            dispatched=dispatched,
            ack=ack,
            read_back=read_back,
            final_status=final_status,
            error=error,
            audit_ref=audit_ref,
        )


class Freshness(str, Enum):
    """Age of the edition a KnowledgeEvidence record was read from.

    Computed by the PRODUCER from real metadata (never asserted by the
    caller): ``fresh`` when the index/snapshot edition is within the
    producer's freshness threshold, ``stale`` when it is older but
    dated, ``unknown`` when no timestamp can be proven at all.
    """

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class FactType(str, Enum):
    """How the cited content came to exist (producer-classified).

    ``structural``  - deterministic structure metadata (symbols,
    imports, layout) extracted from the source; no model judgment.
    ``semantic``    - a model-authored summary stored in the index and
    re-read verbatim (derived purpose / key points).
    ``inferred``    - a statement the producer computed across records
    (e.g. an index-boundary/staleness fact derived from metadata),
    grounded in cited locators but not quoted from any one of them.
    ``runtime``     - a live observation read at answer time (sensor,
    device state, queue depth); reserved for runtime producers.
    """

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    INFERRED = "inferred"
    RUNTIME = "runtime"


class KnowledgeEvidence(VersionedContract):
    """The unified return shape of every QUERY connector (E7 target):

        {"source_id": ..., "source_version": ..., "locator": ...,
         "content": ..., "permission_checked": true,
         "retrieved_at": "2026-10-18T09:15:00Z"}

    Query-type connectors (gbrain, project knowledge, meetings,
    sensors, Oura, power history, files) return this INSTEAD of a
    receipt: a query is retrieval, not an action, so there is no
    completed concept and no state machine here at all.

    Semantics (iron rules):

    - This is retrieval EVIDENCE, not action completion.  A knowledge
      answer that could not be grounded produces no evidence record,
      never a fabricated one.
    - permission_checked records whether the member's grant for
      source_id was actually verified before retrieval.  Evidence
      with permission_checked=false must never be surfaced to the
      expression layer; the field exists so audits can see the gap.
    - locator names WHERE the content lives (page id, entity id,
      message id, URI) so a later verification can re-read the same
      place; content is what that place said, verbatim, never
      model-reworded.
    - source_version pins which edition of the source produced the
      content (page revision, index build, API version) so stale
      evidence is detectable.

    Additive extension (2026-10-18, first runtime producer = UYP
    query-api): the eight OPTIONAL fields below trail the six frozen
    fields.  They change no frozen name, order, or semantic above, and
    all default to None, so every legacy six-field construction and
    dump still validates.  The freeze tests pin them in an open
    extension allowlist (fields may only be added there, never
    renamed or made required).

    - graph_version / node_ids / edge_ids tie the record to the
      knowledge-graph edition it was read against, when one exists.
    - index_as_of is the newest timestamp the producing index can
      prove (ISO 8601); freshness is the producer's real age verdict
      of that edition against its own threshold.
    - fact_type classifies HOW the content came to exist; provider /
      model_id name the local pipeline that produced the record.
    """

    source_id: str
    source_version: str
    locator: str
    content: Any
    permission_checked: bool
    retrieved_at: str  # ISO 8601
    # --- optional runtime enrichment (additive, all default None) ---
    graph_version: str | None = None
    node_ids: list[str] | None = None
    edge_ids: list[str] | None = None
    index_as_of: str | None = None  # ISO 8601; newest provable index timestamp
    freshness: Freshness | None = None
    fact_type: FactType | None = None
    provider: str | None = None
    model_id: str | None = None


class TaskStatus(VersionedContract):
    """The unified shape for work that outlives the turn (E7 target):

        {"task_id": "task_1", "status": "queued", "progress": null,
         "started_at": null, "finished_at": null}

    For long work (large indexing, long parsing, waiting on a remote
    agent's reply) the submission returns a ConnectorReceipt with
    final_status=queued plus this handle; every later observation of
    the same task is another TaskStatus record.  The submission never
    pretends the work finished synchronously.

    Iron rules:

    - Never fake a synchronous completion: unfinished work is
      returned queued/running, whatever the caller hoped for.
    - Terminal records (completed/failed) MUST carry finished_at.
    - running/completed/failed MUST carry started_at; only queued may
      still have started_at=null (not started yet).
    - finished_at on a non-terminal record is a contradiction and is
      rejected here.
    - task_id lives in the same id space as ConnectorReceipt
      ack.connector_request_id: the connector's own task reference.

    progress is a 0.0-1.0 fraction when the task can measure itself
    and None when it cannot; an absent number is honest, an invented
    one is not.
    """

    task_id: str
    status: TaskState
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    started_at: str | None = None  # ISO 8601; null only while queued
    finished_at: str | None = None  # ISO 8601; terminal records only

    @model_validator(mode="after")
    def _invariants(self) -> "TaskStatus":
        terminal = self.status in (TaskState.COMPLETED, TaskState.FAILED)
        if terminal and self.finished_at is None:
            raise ValueError(
                f"status={self.status.value} requires finished_at"
            )
        if not terminal and self.finished_at is not None:
            raise ValueError(
                f"status={self.status.value} cannot carry finished_at"
            )
        if self.status is not TaskState.QUEUED and self.started_at is None:
            raise ValueError(
                f"status={self.status.value} requires started_at"
            )
        return self
