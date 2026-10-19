"""E0 frozen protocol models for the Jarvis harness (final architecture
v2.1, part 2 "five frozen protocols", field-level canon).

Five wire shapes carry a request from the single entry point to the
single execution fact source:

    IngressEnvelope -> PolicyContext -> RouteProposal
                     -> ActionProposal -> ExecutionReceipt

Plus the identity helper models (EndpointIdentity, SpeakerObservation)
and the PendingAction helper for the missing-slot flow.

Discipline pinned here and in tests/test_contract_freeze.py:
- Every model is frozen and closed (extra="forbid"): issued contracts
  are immutable, and unknown fields are rejected on the wire.
- Every top-level protocol carries schema_version pinned to the literal
  "harness-v1" (SCHEMA_VERSION). Bumping the protocol means bumping the
  literal and the freeze tests in the same commit.
- IngressEnvelope has NO principal_id field by design (hard rule 1:
  identity and permissions are decided by the control plane). The
  speaker block is an observation only; the Context Gate recomputes
  principal_id and auth_level.
- ExecutionReceipt encodes hard rule 4 (Ack != Completed) as a model
  invariant: final_status=completed requires ack.received and a
  non-null read_back.

Timestamps are plain ISO 8601 strings, matching the agent_contracts
convention.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Single source of truth for the protocol version stamp.
SCHEMA_VERSION = "harness-v1"


class ContractModel(BaseModel):
    """Shared config: immutable, no extra fields (freeze discipline)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class VersionedContract(ContractModel):
    """Top-level protocol base: stamps the frozen schema version.

    Nested fragments (EndpointIdentity, SpeakerObservation, Ack) are
    plain ContractModel: the version stamps the wire unit, not every
    nested block.
    """

    schema_version: Literal["harness-v1"] = SCHEMA_VERSION


# --- Enumerations (value sets pinned by the freeze tests). ---


class Source(str, Enum):
    """Entry channel of an IngressEnvelope."""

    VOICE = "voice"
    WEB = "web"
    MOBILE = "mobile"
    NANDATOWN = "nandatown"
    SCHEDULE = "schedule"
    CLI = "cli"


class EndpointStatus(str, Enum):
    """Pairing status of a registered endpoint."""

    ACTIVE = "active"
    DISABLED = "disabled"


class SpeakerStatus(str, Enum):
    """What the speaker-recognition front-end observed.

    An observation, never an authorization: the Context Gate turns this
    into principal_id + auth_level.
    """

    MATCHED = "matched"
    UNCERTAIN = "uncertain"
    NO_MATCH = "no_match"


class AuthLevel(str, Enum):
    """Identity assurance levels (final architecture part 6)."""

    GUEST = "guest"
    VOICE_CANDIDATE = "voice_candidate"
    VOICE_VERIFIED = "voice_verified"
    SECOND_FACTOR_VERIFIED = "second_factor_verified"


class NetworkState(str, Enum):
    """Connectivity snapshot used by policy decisions."""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class RouteType(str, Enum):
    """Router outcome classes (final architecture part 3)."""

    ACTION = "action"
    KNOWLEDGE = "knowledge"
    CHAT = "chat"
    COMPOSITE = "composite"
    CLARIFICATION = "clarification"
    UNKNOWN = "unknown"


class FinalStatus(str, Enum):
    """ExecutionReceipt final status state machine (part 2.5)."""

    RECEIVED = "received"
    AWAITING_SLOT = "awaiting_slot"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DENIED = "denied"
    DISPATCHED = "dispatched"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    QUEUED = "queued"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PendingState(str, Enum):
    """PendingAction lifecycle (part 5)."""

    AWAITING_SLOT = "awaiting_slot"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    READY = "ready"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# --- Identity helper models (the three identity layers). ---


class EndpointIdentity(ContractModel):
    """Endpoint layer of identity: the physical entry point.

    room_id comes from the endpoint pairing (part 2.1 iron rule), never
    from the request payload.
    """

    endpoint_id: str
    room_id: str
    mic_id: str | None = None
    terminal_id: str | None = None
    public_key: str | None = None
    status: EndpointStatus = EndpointStatus.ACTIVE


class SpeakerObservation(ContractModel):
    """Speaker layer of identity: a recognition observation.

    candidate_id is a hint for the Context Gate, not a principal claim;
    IngressEnvelope cannot assert a principal (hard rule 1).
    """

    candidate_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: SpeakerStatus


# --- The five frozen protocols. ---


class IngressEnvelope(VersionedContract):
    """The single entry envelope (part 2.1).

    request_id is minted at the Gateway; raw audio stays out of the
    long-term store (audio_ref points at tmpfs); every downstream event
    carries request_id. There is deliberately no principal_id field:
    extra="forbid" turns a submitted principal into a validation error.
    """

    request_id: str
    session_id: str
    source: Source
    received_at: str  # ISO 8601
    endpoint: EndpointIdentity
    text: str
    audio_ref: str | None = None
    speaker_observation: SpeakerObservation | None = None


class PolicyContext(VersionedContract):
    """The immutable identity/permission snapshot (part 2.2).

    Fixed once by the Context Gate; the router reads it but cannot
    mutate it (hard rule 1). The Broker re-reads grant_epoch before
    dispatch so a mid-request revocation blocks execution.

    principal_id=None means unidentified: the request is handled as
    guest regardless of what any speaker observation claimed.
    """

    request_id: str
    session_id: str
    principal_id: str | None
    room_id: str
    endpoint_id: str
    auth_level: AuthLevel
    grants: list[str]
    grant_epoch: int
    pending_action_id: str | None = None
    network_state: NetworkState
    policy_version: str
    capability_registry_version: str


class RouteProposal(VersionedContract):
    """Router output (part 2.3).

    A proposal, never an authorization: hard rule 2 requires the Policy
    Engine before any execution.
    """

    route_id: str
    route_type: RouteType
    domain: str
    candidate_capabilities: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    ood: float = Field(ge=0.0, le=1.0)


class ActionProposal(VersionedContract):
    """A parsed capability call (part 2.4).

    capability_id must come from the Capability Registry; slots are
    free-form JSON values validated against the manifest input_schema
    downstream.
    """

    action_id: str
    capability_id: str
    slots: dict[str, Any]
    missing_slots: list[str]
    requires_confirmation: bool


class Ack(ContractModel):
    """Connector acknowledgement block of an ExecutionReceipt."""

    received: bool
    connector: str | None = None
    connector_request_id: str | None = None


class ExecutionReceipt(VersionedContract):
    """The single execution fact source (part 2.5).

    Hard rule 4 as a model invariant: final_status=completed requires
    ack.received AND a non-null read_back. Ack without read-back is
    accepted - the expression layer may only say "the command was sent,
    the device did not confirm its final state", never "it is on".
    """

    request_id: str
    action_id: str
    capability_id: str
    principal_id: str
    authorized: bool
    dispatched: bool
    ack: Ack
    read_back: dict[str, Any] | None
    final_status: FinalStatus
    error: str | None = None
    audit_ref: str
    policy_version: str
    registry_version: str

    @model_validator(mode="after")
    def _completed_requires_ack_and_read_back(self) -> "ExecutionReceipt":
        if self.final_status is FinalStatus.COMPLETED and (
            not self.ack.received or self.read_back is None
        ):
            raise ValueError(
                "final_status=completed requires ack.received and a "
                "non-null read_back (Ack != Completed)"
            )
        return self

    @classmethod
    def conclude(
        cls,
        *,
        request_id: str,
        action_id: str,
        capability_id: str,
        principal_id: str,
        authorized: bool,
        dispatched: bool,
        ack: Ack,
        read_back: dict[str, Any] | None,
        error: str | None = None,
        audit_ref: str,
        policy_version: str,
        registry_version: str,
    ) -> "ExecutionReceipt":
        """Derive the terminal final_status from the dispatch outcome.

        denied when not authorized; completed only when ack.received and
        read_back are both present; ack without read-back is accepted.
        """
        if not authorized:
            final_status = FinalStatus.DENIED
        elif not dispatched:
            final_status = FinalStatus.FAILED
        elif ack.received and read_back is not None:
            final_status = FinalStatus.COMPLETED
        elif ack.received:
            final_status = FinalStatus.ACCEPTED
        else:
            final_status = FinalStatus.FAILED
        return cls(
            request_id=request_id,
            action_id=action_id,
            capability_id=capability_id,
            principal_id=principal_id,
            authorized=authorized,
            dispatched=dispatched,
            ack=ack,
            read_back=read_back,
            final_status=final_status,
            error=error,
            audit_ref=audit_ref,
            policy_version=policy_version,
            registry_version=registry_version,
        )


# --- E5 plan step helper (PlanExecutor, part 7) ---


class StepCondition(str, Enum):
    """E5 plan step condition (v1: two judges only).

    ``none`` runs the step once its dependencies completed.  ``if_free``
    runs it only when the dependency's calendar read-back says the
    speaker is free; the judge is deterministic code over the prior
    step's ExecutionReceipt read-back, never the planner model.
    """

    NONE = "none"
    IF_FREE = "if_free"


class PlanStep(VersionedContract):
    """One step of an E5 composite plan (PlanExecutor, part 7).

    The planner model PROPOSES this shape and nothing else; the harness
    validates everything before any execution: capability existence and
    ring visibility, slot schemas against the capability manifest,
    dependency closure (forward edges only), and condition legality.
    A step never carries free-form instructions - only a capability_id
    from the registry and slots the manifest can check.
    """

    step_id: str
    capability_id: str
    slots: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    condition: StepCondition = StepCondition.NONE


class PendingAction(VersionedContract):
    """Suspended action waiting for slots or confirmation (part 5).

    Bound to principal + session (+ TTL via expires_at): an isolated
    "yes" / "At eight" / "cancel that" is never accepted (hard rule 5),
    and a follow-up turn fills only the currently-missing slots instead
    of becoming a new request.
    """

    pending_action_id: str
    request_id: str
    session_id: str
    principal_id: str
    capability_id: str
    slots: dict[str, Any]
    missing_slots: list[str]
    state: PendingState
    expires_at: str  # ISO 8601; TTL is mandatory
    # E6 risk-tiered confirmation: WHY the action is suspended (both
    # default False - the slot and confirmation states above remain the
    # lifecycle; these carry the policy reason so the resume path knows
    # which confirmation strength unlocks it: an affirmation (R3) or a
    # second factor (R4, PIN / phone).
    confirmation_required: bool = False
    second_factor_required: bool = False

    def with_filled_slots(self, fills: dict[str, Any]) -> "PendingAction":
        """Return a copy with only currently-missing slots filled.

        Filling anything not in missing_slots is an error: a follow-up
        turn may complete the pending action, never rewrite it.
        """
        unknown = set(fills) - set(self.missing_slots)
        if unknown:
            raise ValueError(
                f"cannot fill slots that are not missing: {sorted(unknown)}"
            )
        slots = {**self.slots, **fills}
        missing_slots = [s for s in self.missing_slots if s not in fills]
        state = (
            PendingState.READY if not missing_slots else self.state
        )
        return self.model_copy(
            update={
                "slots": slots,
                "missing_slots": missing_slots,
                "state": state,
            }
        )
