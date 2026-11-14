"""Versioned, owner-scoped discussion and immutable calculation snapshot contracts."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from .models import Model

CONTRACT_VERSION = "guest-review/2"
MutationID = Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")]
EntityIDs = Annotated[list[str], Field(min_length=1, max_length=20)]
EvidenceState = Literal[
    "awaiting_explanation",
    "answer_insufficient",
    "explained_verified",
    "contradiction_remains",
    "needs_recheck",
]
OwnerDecision = Literal["continue_clarifying", "accept_explanation", "stop_unresolved"]


class Observation(Model):
    code: str
    anchors: list[str]
    message: str
    contractor_question: str
    affects: list[str]
    metric_values: dict[str, int | None]
    amounts_cents: dict[str, int | None]
    record_ids: list[str]
    source_refs: list[str]
    file_ids: list[str]
    financial_revision: int
    basis_fingerprint: str
    active: bool = True


class CardEvent(Model):
    id: str
    at: datetime
    actor: str
    kind: str
    detail: str
    evidence_state: EvidenceState
    owner_decision: OwnerDecision
    financial_revision: int
    basis_fingerprint: str
    record_ids: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class QuestionCard(Model):
    id: str
    version: int = 1
    created_at: datetime
    updated_at: datetime
    observation: Observation
    evidence_state: EvidenceState = "awaiting_explanation"
    owner_decision: OwnerDecision = "continue_clarifying"
    reply_ids: list[str] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    events: list[CardEvent] = Field(default_factory=list)
    verified_snapshot_id: str | None = None
    verified_source_refs: list[str] = Field(default_factory=list)


class ReplyVersion(Model):
    source_id: str
    version: int
    text: str
    file_ids: list[str]
    added_by: str
    added_at: datetime
    origin: Literal["owner_reported_contractor"] = "owner_reported_contractor"


class Reply(Model):
    id: str
    question_ids: list[str]
    versions: list[ReplyVersion]


class SnapshotSummary(Model):
    id: str
    created_at: datetime
    financial_revision: int
    contract_version: str
    remaining_cents: int | None
    question_count: int


class Snapshot(Model):
    summary: SnapshotSummary
    # Stored JSON is served verbatim, never passed through today's domain calculator.
    payload: dict[str, Any]


class CaseworkView(Model):
    cards: list[QuestionCard] = Field(default_factory=list)
    replies: list[Reply] = Field(default_factory=list)
    snapshots: list[SnapshotSummary] = Field(default_factory=list)
    latest_snapshot_id: str | None = None
    legacy_audit_count: int = 0


class ReplyCommand(Model):
    mutation_id: MutationID
    question_ids: EntityIDs
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    file_ids: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)


class ReplyEdit(Model):
    mutation_id: MutationID
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    file_ids: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)


class AttachmentCommand(Model):
    mutation_id: MutationID
    question_ids: EntityIDs
    file_ids: EntityIDs


class CardCommand(Model):
    mutation_id: MutationID
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    evidence_state: EvidenceState | None = None
    owner_decision: OwnerDecision | None = None
    note: Annotated[str, Field(min_length=1, max_length=1000)]
    snapshot_id: str | None = None
    source_refs: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)
