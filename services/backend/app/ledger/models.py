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


class BillingCredit(AmountRecord):
    charge_id: Identifier


class Allocation(AmountRecord):
    cash_event_id: Identifier
    charge_id: Identifier
    reverses_allocation_id: Identifier | None = None


class ChargeBalance(StrictModel):
    charge_id: Identifier
    charge_cents: Cents
    net_allocation_cents: Cents
    remaining_cents: Cents


class CashBalance(StrictModel):
    cash_event_id: Identifier
    amount_cents: Cents
    net_allocation_cents: Cents
    unallocated_cents: Cents


class LedgerInput(StrictModel):
    case_id: Identifier
    case_revision: Annotated[int, Field(strict=True, ge=0)]
    currency: Literal["USD"] = "USD"
    agreement: AmountRecord | None
    adjustments: tuple[AmountRecord, ...] = ()
    cash_events: tuple[CashEvent, ...]
    requested_now_cents: Cents | None
    charges: tuple[AmountRecord, ...] = ()
    billing_credits: tuple[BillingCredit, ...] = ()
    allocations: tuple[Allocation, ...] = ()

    @model_validator(mode="after")
    def unique_record_ids(self) -> Self:
        records: list[AmountRecord] = [
            *self.adjustments,
            *self.cash_events,
            *self.charges,
            *self.billing_credits,
            *self.allocations,
        ]
        if self.agreement is not None:
            records.append(self.agreement)
        ids = [record.id for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Each normalized record id must occur once; resolve duplicates upstream"
            )
        charges = {row.id for row in self.charges}
        cash = {row.id: row for row in self.cash_events}
        allocations = {row.id: row for row in self.allocations}
        allocated: dict[str, int] = {}
        reversed_amount: dict[str, int] = {}
        for credit in self.billing_credits:
            if credit.charge_id not in charges or credit.amount_cents >= 0:
                raise ValueError("Billing credit must be negative and reference an existing charge")
        for allocation in self.allocations:
            event = cash.get(allocation.cash_event_id)
            if event is None or event.state != "completed" or allocation.charge_id not in charges:
                raise ValueError(
                    "Allocation requires a completed cash event and an existing charge"
                )
            if allocation.amount_cents == 0 or allocation.amount_cents * event.amount_cents <= 0:
                raise ValueError("Allocation direction must match cash direction and be nonzero")
            allocated[event.id] = allocated.get(event.id, 0) + allocation.amount_cents
            original = allocations.get(allocation.reverses_allocation_id or "")
            if allocation.amount_cents < 0:
                if (
                    original is None
                    or original.amount_cents <= 0
                    or original.charge_id != allocation.charge_id
                ):
                    raise ValueError(
                        "Refund allocation must reverse an allocation to the same charge"
                    )
                reversed_amount[original.id] = (
                    reversed_amount.get(original.id, 0) - allocation.amount_cents
                )
            elif allocation.reverses_allocation_id is not None:
                raise ValueError("Only refunds can reverse allocations")
        if any(abs(amount) > abs(cash[key].amount_cents) for key, amount in allocated.items()):
            raise ValueError("Allocation exceeds available cash")
        if any(amount > allocations[key].amount_cents for key, amount in reversed_amount.items()):
            raise ValueError("Refund exceeds the original allocation")
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
    billed_total_cents: Cents
    charge_balances: tuple[ChargeBalance, ...]
    positive_outstanding_cents: Cents
    credit_balance_cents: Cents
    net_allocations_cents: Cents
    unallocated_cents: Cents
    cash_balances: tuple[CashBalance, ...]
