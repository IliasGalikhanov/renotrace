"""Billing reconciliation over selected revisions; no cash or contract inference."""

from typing import TYPE_CHECKING

from app.ledger.models import Allocation, AmountRecord, BillingCredit, CashEvent

from .models import Billing, FinancialRecord, Metric, PaymentAllocation
from .validation import NormalizationError

if TYPE_CHECKING:
    from .engine import _Context

ALLOCATION_METRICS: tuple[Metric, ...] = (
    "charge_balances",
    "positive_outstanding_cents",
    "credit_balance_cents",
    "net_allocations_cents",
    "unallocated_cents",
    "cash_balances",
)
BILLING_METRICS: tuple[Metric, ...] = ("billed_total_cents", *ALLOCATION_METRICS)


def billing(
    ctx: "_Context",
    candidates: list[FinancialRecord],
    cash: tuple[CashEvent, ...],
) -> tuple[tuple[AmountRecord, ...], tuple[BillingCredit, ...], tuple[Allocation, ...]]:
    rows = {r.id: r for r in candidates if isinstance(r, Billing) and ctx.usable(r)}
    charges: dict[str, AmountRecord] = {}
    credits: list[BillingCredit] = []

    def unresolved(row: Billing | PaymentAllocation, code: str, *related: str) -> None:
        ids = (row.id, *related)
        ctx.question(
            code,
            ids,
            "Confirm the billing coverage or allocation relationship before including it.",
            BILLING_METRICS if isinstance(row, Billing) else ALLOCATION_METRICS,
            decision_ids=tuple(d.id for d in ctx.history.decisions if set(ids) & set(ctx.scope(d))),
        )
        ctx.disposition(row, code)

    eligible: dict[str, Billing] = {}
    for row in rows.values():
        if row.basis == "balance_statement":
            ctx.disposition(row, "BALANCE_STATEMENT_ONLY")
        elif row.basis == "unknown":
            unresolved(row, "UNKNOWN_BILLING_BASIS")
        elif row.basis_revision != ctx.history.case_revision:
            unresolved(row, "STALE_BILLING_BASIS")
        elif row.relationship_review == "rejected":
            ctx.disposition(row, "RELATIONSHIP_REJECTED")
        elif row.relationship_review != "accepted":
            unresolved(row, "BILLING_RELATIONSHIP_REQUIRED")
        elif row.basis == "credit_note":
            continue
        elif not row.coverage_confirmed or not row.coverage:
            unresolved(row, "BILLING_COVERAGE_REQUIRED")
        elif row.basis == "cumulative_valuation" and (
            row.previous_id is None and not row.starts_at_zero
        ):
            unresolved(row, "PREVIOUS_BILLING_REQUIRED")
        else:
            eligible[row.id] = row

    def ancestors(row: Billing) -> set[str]:
        result: set[str] = set()
        previous = row.previous_id
        while previous is not None:
            result.add(previous)
            parent = ctx.records[previous]
            assert isinstance(parent, Billing)
            previous = parent.previous_id
        return result

    # Two independent roots or branches covering the same work are not additive.
    overlapping: set[str] = set()
    values = sorted(eligible.values(), key=lambda r: r.id)
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if (
                set(left.coverage) & set(right.coverage)
                and left.id not in ancestors(right)
                and right.id not in ancestors(left)
            ):
                overlapping.update((left.id, right.id))
                unresolved(left, "BILLING_COVERAGE_OVERLAP", right.id)
                unresolved(right, "BILLING_COVERAGE_OVERLAP", left.id)
    pending = {key: row for key, row in eligible.items() if key not in overlapping}
    while pending:
        for key, row in list(pending.items()):
            if row.previous_id in pending:
                continue
            del pending[key]
            amount = row.amount_cents
            assert amount is not None
            if row.previous_id is not None:
                parent = ctx.records[row.previous_id]
                assert isinstance(parent, Billing)
                if parent.id not in charges or set(parent.coverage) != set(row.coverage):
                    unresolved(row, "CUMULATIVE_COMPARABILITY_REQUIRED", parent.id)
                    continue
                assert parent.amount_cents is not None
                amount -= parent.amount_cents
                ctx.refs[row.id].update(charges[parent.id].evidence_refs)
                ctx.used[row.id].update(ctx.used[parent.id])
            value = AmountRecord(
                id=f"record:{row.id}",
                amount_cents=amount,
                evidence_refs=tuple(sorted(ctx.refs[row.id])),
                origin="derived" if row.basis == "cumulative_valuation" else row.origin,
            )
            charges[row.id] = value
            ctx.disposition(row, "ACCEPTED_CHARGE", included=True, canonical=value.id)

    for row in rows.values():
        if (
            row.basis != "credit_note"
            or row.basis_revision != ctx.history.case_revision
            or row.relationship_review != "accepted"
        ):
            continue
        if row.credit_target_id not in charges:
            unresolved(
                row,
                "CREDIT_TARGET_UNRESOLVED",
                *(() if row.credit_target_id is None else (row.credit_target_id,)),
            )
            continue
        target = charges[row.credit_target_id]
        if ctx.records[row.credit_target_id].effective_date > row.effective_date:
            raise NormalizationError("INVALID_CREDIT_DATE", row.id)
        ctx.refs[row.id].update(target.evidence_refs)
        ctx.used[row.id].update(ctx.used[row.credit_target_id])
        credit = BillingCredit(**ctx.amount(row).model_dump(), charge_id=target.id)
        credits.append(credit)
        ctx.disposition(row, "ACCEPTED_BILLING_CREDIT", included=True, canonical=credit.id)

    events = {event.id: event for event in cash}
    allocations: dict[str, Allocation] = {}
    allocation_rows = [r for r in candidates if isinstance(r, PaymentAllocation) and ctx.usable(r)]
    # Positive allocations must exist before refund corrections are examined.
    for allocation_row in sorted(allocation_rows, key=lambda r: ((r.amount_cents or 0) < 0, r.id)):
        if allocation_row.basis_revision != ctx.history.case_revision:
            unresolved(allocation_row, "STALE_ALLOCATION")
            continue
        if allocation_row.relationship_review == "rejected":
            ctx.disposition(allocation_row, "RELATIONSHIP_REJECTED")
            continue
        if allocation_row.relationship_review != "accepted":
            unresolved(allocation_row, "ALLOCATION_RELATIONSHIP_REQUIRED")
            continue
        cash_disposition = ctx.included.get(allocation_row.cash_id) or ctx.excluded.get(
            allocation_row.cash_id
        )
        canonical = None if cash_disposition is None else cash_disposition.canonical_record_id
        event = events.get(canonical or "")
        allocation_target = charges.get(allocation_row.charge_id)
        if event is None or allocation_target is None:
            unresolved(
                allocation_row,
                "ALLOCATION_ENDPOINT_UNRESOLVED",
                allocation_row.cash_id,
                allocation_row.charge_id,
            )
            continue
        if any(
            ctx.records[key].effective_date > allocation_row.effective_date
            for key in (
                allocation_row.cash_id,
                allocation_row.charge_id,
            )
        ):
            raise NormalizationError("INVALID_ALLOCATION_DATE", allocation_row.id)
        original = allocations.get(allocation_row.reverses_allocation_id or "")
        if allocation_row.reverses_allocation_id is not None and original is None:
            unresolved(
                allocation_row,
                "REFUND_ALLOCATION_UNRESOLVED",
                allocation_row.reverses_allocation_id,
            )
            continue
        if original is not None:
            assert allocation_row.reverses_allocation_id is not None
            if (
                ctx.records[allocation_row.reverses_allocation_id].effective_date
                > allocation_row.effective_date
            ):
                raise NormalizationError("INVALID_REFUND_ALLOCATION_DATE", allocation_row.id)
            ctx.refs[allocation_row.id].update(original.evidence_refs)
        ctx.refs[allocation_row.id].update(event.evidence_refs)
        ctx.refs[allocation_row.id].update(allocation_target.evidence_refs)
        for dependency_id in (
            allocation_row.cash_id,
            allocation_row.charge_id,
            allocation_row.reverses_allocation_id,
        ):
            if dependency_id is not None:
                ctx.used[allocation_row.id].update(ctx.used[dependency_id])
        allocation = Allocation(
            **ctx.amount(allocation_row).model_dump(),
            cash_event_id=event.id,
            charge_id=allocation_target.id,
            reverses_allocation_id=None if original is None else original.id,
        )
        allocations[allocation_row.id] = allocation
        ctx.disposition(
            allocation_row, "ACCEPTED_ALLOCATION", included=True, canonical=allocation.id
        )
    return (
        tuple(sorted(charges.values(), key=lambda r: r.id)),
        tuple(sorted(credits, key=lambda r: r.id)),
        tuple(sorted(allocations.values(), key=lambda r: r.id)),
    )
