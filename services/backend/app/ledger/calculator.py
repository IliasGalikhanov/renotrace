"""Deterministic integer arithmetic over validated normalized records."""

import hashlib
import json
from typing import Any

from .models import CashBalance, ChargeBalance, LedgerInput, LedgerResult

RULES_VERSION = "ledger-0.2.0"


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def calculate(history: LedgerInput) -> LedgerResult:
    """Calculate C, P and R; requested_now never participates in these equations.

    Python integers keep intermediate sums exact. Result validation rejects any
    published amount outside the supported range, including aggregate overflow.
    """
    if not isinstance(history, LedgerInput):
        raise TypeError("calculate requires a validated LedgerInput")

    completed = tuple(event for event in history.cash_events if event.state == "completed")
    outgoing = sum(event.amount_cents for event in completed if event.amount_cents > 0)
    refunds = -sum(event.amount_cents for event in completed if event.amount_cents < 0)
    paid = outgoing - refunds
    commitment = (
        None
        if history.agreement is None
        else history.agreement.amount_cents + sum(row.amount_cents for row in history.adjustments)
    )
    commitment_ids = (
        ()
        if history.agreement is None
        else tuple(sorted([history.agreement.id, *(row.id for row in history.adjustments)]))
    )
    canonical = json.dumps(
        {"rules_version": RULES_VERSION, "input": _canonical(history.model_dump(mode="json"))},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    balances = []
    for charge in sorted(history.charges, key=lambda row: row.id):
        billed = charge.amount_cents + sum(
            credit.amount_cents
            for credit in history.billing_credits
            if credit.charge_id == charge.id
        )
        allocated = sum(a.amount_cents for a in history.allocations if a.charge_id == charge.id)
        balances.append(
            ChargeBalance(
                charge_id=charge.id,
                charge_cents=billed,
                net_allocation_cents=allocated,
                remaining_cents=billed - allocated,
            )
        )
    cash_balances = []
    for event in sorted(completed, key=lambda row: row.id):
        allocated = sum(a.amount_cents for a in history.allocations if a.cash_event_id == event.id)
        cash_balances.append(
            CashBalance(
                cash_event_id=event.id,
                amount_cents=event.amount_cents,
                net_allocation_cents=allocated,
                unallocated_cents=event.amount_cents - allocated,
            )
        )
    net_allocations = sum(a.amount_cents for a in history.allocations)
    return LedgerResult(
        case_id=history.case_id,
        case_revision=history.case_revision,
        rules_version=RULES_VERSION,
        input_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        commitment_total_cents=commitment,
        completed_outgoing_cents=outgoing,
        completed_refunds_cents=refunds,
        net_paid_cents=paid,
        remaining_commitment_cents=None if commitment is None else commitment - paid,
        requested_now_cents=history.requested_now_cents,
        billed_total_cents=sum(b.charge_cents for b in balances),
        charge_balances=tuple(balances),
        positive_outstanding_cents=sum(max(b.remaining_cents, 0) for b in balances),
        credit_balance_cents=-sum(min(b.remaining_cents, 0) for b in balances),
        net_allocations_cents=net_allocations,
        unallocated_cents=paid - net_allocations,
        cash_balances=tuple(cash_balances),
        commitment_record_ids=commitment_ids,
        completed_cash_record_ids=tuple(sorted(event.id for event in completed)),
        excluded_cash_record_ids=tuple(
            sorted(event.id for event in history.cash_events if event.state != "completed")
        ),
    )
