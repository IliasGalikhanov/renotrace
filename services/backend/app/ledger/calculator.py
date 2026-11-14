"""Deterministic integer arithmetic over validated normalized records."""

import hashlib
import json
from typing import Any

from .models import LedgerInput, LedgerResult

RULES_VERSION = "ledger-0.1.0"


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
        commitment_record_ids=commitment_ids,
        completed_cash_record_ids=tuple(sorted(event.id for event in completed)),
        excluded_cash_record_ids=tuple(
            sorted(event.id for event in history.cash_events if event.state != "completed")
        ),
    )
