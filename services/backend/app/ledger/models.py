"""Strict, immutable inputs for an already selected normalized history.

No document parsing, matching, version selection, or legal verification occurs here.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_CENTS = 9_000_000_000_000
Cents = Annotated[int, Field(strict=True, ge=-MAX_CENTS, le=MAX_CENTS)]
Identifier = Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]
Origin = Literal["document", "bank_record", "user_statement", "derived"]
CashState = Literal["completed", "pending", "scheduled", "failed", "reversed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class AmountRecord(StrictModel):
    id: Identifier
    amount_cents: Cents
    evidence_refs: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    origin: Origin


class CashEvent(AmountRecord):
    # Positive = outgoing payment; negative = refund received from the contractor.
    # Normalization must already establish the contractor and selected record revision.
    state: CashState


class LedgerInput(StrictModel):
    case_id: Identifier
    case_revision: Annotated[int, Field(strict=True, ge=0)]
    currency: Literal["USD"] = "USD"
    agreement: AmountRecord | None
    adjustments: tuple[AmountRecord, ...] = ()
    cash_events: tuple[CashEvent, ...]
    requested_now_cents: Cents | None

    @model_validator(mode="after")
    def unique_record_ids(self) -> Self:
        records: list[AmountRecord] = [*self.adjustments, *self.cash_events]
        if self.agreement is not None:
            records.append(self.agreement)
        ids = [record.id for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Each normalized record id must occur once; resolve duplicates upstream"
            )
        return self


class LedgerResult(StrictModel):
    case_id: Identifier
    case_revision: Annotated[int, Field(strict=True, ge=0)]
    currency: Literal["USD"] = "USD"
    rules_version: str
    input_fingerprint: str
    commitment_total_cents: Cents | None
    completed_outgoing_cents: Annotated[int, Field(strict=True, ge=0, le=MAX_CENTS)]
    completed_refunds_cents: Annotated[int, Field(strict=True, ge=0, le=MAX_CENTS)]
    net_paid_cents: Cents
    remaining_commitment_cents: Cents | None
    requested_now_cents: Cents | None
    commitment_record_ids: tuple[Identifier, ...]
    completed_cash_record_ids: tuple[Identifier, ...]
    excluded_cash_record_ids: tuple[Identifier, ...]
