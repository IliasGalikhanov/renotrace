"""Typed structured history. These are domain inputs, not an OCR or HTTP schema."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.ledger.models import CashState, Cents, Identifier, LedgerInput, Origin, StrictModel

Revision = Annotated[int, Field(strict=True, ge=1)]
CaseRevision = Annotated[int, Field(strict=True, ge=0)]
References = Annotated[tuple[Identifier, ...], Field(min_length=1)]
Metric = Literal[
    "commitment_total_cents",
    "net_paid_cents",
    "remaining_commitment_cents",
    "requested_now_cents",
    "billed_total_cents",
    "charge_balances",
    "positive_outstanding_cents",
    "credit_balance_cents",
    "net_allocations_cents",
    "unallocated_cents",
    "cash_balances",
]


def utc(value: datetime | None) -> None:
    if value is not None and value.utcoffset() != timedelta(0):
        raise ValueError("Audit timestamps must include UTC timezone")


class Source(StrictModel):
    id: Identifier
    case_id: Identifier
    version: Revision
    origin: Origin
    locator: Identifier
    actor_id: Identifier | None = None


class Review(StrictModel):
    extraction_review: Literal["unreviewed", "checked", "corrected"] = "unreviewed"
    extraction_actor_id: Identifier | None = None
    extraction_reviewed_at: datetime | None = None
    semantic_review: Literal["unknown", "user_asserted", "reviewed_for_calculation"] = "unknown"
    semantic_actor_id: Identifier | None = None
    semantic_reviewed_at: datetime | None = None
    lifecycle: Literal["active", "superseded", "void", "stale"] = "active"

    @model_validator(mode="after")
    def audit_metadata(self) -> Self:
        utc(self.extraction_reviewed_at)
        utc(self.semantic_reviewed_at)
        if self.extraction_review != "unreviewed" and (
            self.extraction_actor_id is None or self.extraction_reviewed_at is None
        ):
            raise ValueError("Extraction review requires actor and timestamp")
        if self.semantic_review != "unknown" and (
            self.semantic_actor_id is None or self.semantic_reviewed_at is None
        ):
            raise ValueError("Semantic review requires actor and timestamp")
        return self


class Record(StrictModel):
    id: Identifier  # immutable revision ID, referenced by links and decisions
    record_id: Identifier  # stable logical identity shared by revisions
    version: Revision
    effective_date: date
    amount_cents: Cents | None
    contractor_id: Identifier | None
    evidence_refs: References
    origin: Origin
    review: Review = Review()


class Agreement(Record):
    kind: Literal["agreement"] = "agreement"


class Adjustment(Record):
    kind: Literal["adjustment"] = "adjustment"


class Cash(Record):
    kind: Literal["cash"] = "cash"
    state: CashState
    bank_account_id: Identifier | None = None
    bank_transaction_id: Identifier | None = None

    @model_validator(mode="after")
    def bank_identity_pair(self) -> Self:
        if (self.bank_account_id is None) != (self.bank_transaction_id is None):
            raise ValueError("Bank identity requires both account context and transaction ID")
        return self


class PaymentRequest(Record):
    kind: Literal["payment_request"] = "payment_request"
    mentioned_deposit_cents: Cents | None = None  # descriptive only; never a cash event


class RelatedRecord(Record):
    basis_revision: CaseRevision
    relationship_review: Literal["proposed", "accepted", "rejected", "invalidated"] = "proposed"
    relationship_actor_id: Identifier | None = None
    relationship_reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def relationship_audit(self) -> Self:
        utc(self.relationship_reviewed_at)
        if self.relationship_review in ("accepted", "rejected") and (
            self.relationship_actor_id is None or self.relationship_reviewed_at is None
        ):
            raise ValueError("Relationship review requires actor and timestamp")
        return self


class Billing(RelatedRecord):
    kind: Literal["billing"] = "billing"
    basis: Literal[
        "incremental_charge", "cumulative_valuation", "balance_statement", "credit_note", "unknown"
    ]
    # Explicitly confirmed atomic work/period IDs; equal IDs mean overlapping coverage.
    coverage: tuple[Identifier, ...] = ()
    coverage_confirmed: bool = False
    previous_id: Identifier | None = None
    starts_at_zero: bool = False
    credit_target_id: Identifier | None = None


class PaymentAllocation(RelatedRecord):
    kind: Literal["allocation"] = "allocation"
    cash_id: Identifier
    charge_id: Identifier
    reverses_allocation_id: Identifier | None = None

    @model_validator(mode="after")
    def allocation_direction(self) -> Self:
        if self.amount_cents == 0:
            raise ValueError("Allocation direction must be nonzero")
        if self.amount_cents is not None:
            if self.amount_cents > 0 and self.reverses_allocation_id is not None:
                raise ValueError("Only refunds can reverse allocations")
            if self.amount_cents < 0 and self.reverses_allocation_id is None:
                raise ValueError("Refund allocation direction must reverse an original allocation")
        return self


FinancialRecord = Annotated[
    Agreement | Adjustment | Cash | PaymentRequest | Billing | PaymentAllocation,
    Field(discriminator="kind"),
]


class Link(StrictModel):
    id: Identifier
    kind: Literal["supersedes", "includes_adjustment"]
    from_id: Identifier
    to_id: Identifier
    review: Literal["proposed", "accepted", "rejected", "invalidated"]
    basis_revision: CaseRevision
    evidence_refs: References
    actor_id: Identifier | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def link_audit(self) -> Self:
        utc(self.reviewed_at)
        if self.review in ("accepted", "rejected") and (
            self.actor_id is None or self.reviewed_at is None
        ):
            raise ValueError("Reviewed link requires actor and timestamp")
        return self


class DecisionBase(StrictModel):
    id: Identifier
    target_id: Identifier
    basis_revision: CaseRevision
    actor_id: Identifier
    decided_at: datetime
    evidence_refs: References

    @model_validator(mode="after")
    def decision_time(self) -> Self:
        utc(self.decided_at)
        return self


class SelectVersion(DecisionBase):
    kind: Literal["select_version"] = "select_version"
    selected_id: Identifier | None  # target_id is a logical record_id


class SelectAgreement(DecisionBase):
    kind: Literal["select_agreement"] = "select_agreement"
    selected_id: Identifier | None  # target_id is the case_id


class AssignContractor(DecisionBase):
    kind: Literal["assign_contractor"] = "assign_contractor"
    contractor_id: Identifier | None  # target_id is a record revision ID


class ConfirmSemantics(DecisionBase):
    kind: Literal["confirm_semantics"] = "confirm_semantics"
    answer: Literal["accept", "reject", "unknown"]


class ReviewLink(DecisionBase):
    kind: Literal["review_link"] = "review_link"
    answer: Literal["accept", "reject", "unknown"]


Decision = Annotated[
    SelectVersion | SelectAgreement | AssignContractor | ConfirmSemantics | ReviewLink,
    Field(discriminator="kind"),
]


class HistoryInput(StrictModel):
    case_id: Identifier
    case_revision: CaseRevision
    contractor_id: Identifier
    cutoff_date: date
    currency: Literal["USD"] = "USD"
    current_request_id: Identifier | None = None
    sources: tuple[Source, ...]
    records: tuple[FinancialRecord, ...]
    links: tuple[Link, ...] = ()
    decisions: tuple[Decision, ...] = ()


class Question(StrictModel):
    id: Identifier
    code: Identifier
    record_ids: tuple[Identifier, ...]
    decision_ids: tuple[Identifier, ...] = ()
    affects: tuple[Metric, ...]
    message: str


class Disposition(StrictModel):
    record: FinancialRecord
    reason: Identifier
    canonical_record_id: Identifier | None = None
    evidence_refs: References
    decision_ids: tuple[Identifier, ...]
    effective_contractor_id: Identifier | None
    effective_semantic_review: Literal["unknown", "user_asserted", "reviewed_for_calculation"]


class NormalizationResult(StrictModel):
    normalization_version: str
    ledger_input: LedgerInput
    included: tuple[Disposition, ...]
    excluded: tuple[Disposition, ...]
    questions: tuple[Question, ...]
    incomplete: bool
    incomplete_metrics: tuple[Metric, ...]
    sources: tuple[Source, ...]
    links: tuple[Link, ...]
    applied_decisions: tuple[Decision, ...]
