"""Adapter for supplied synthetic, already normalized fixtures; NOT normalization.

The first commitment term is the selected base; subsequent terms are accepted
adjustments. Cash arrays already exclude duplicates, unrelated and pending events.
Billing, stage conditions, and expected_issue_codes are outside stage 1.
"""

from typing import Any

from .ledger import AmountRecord, CashEvent, LedgerInput


def reference_input(case: dict[str, Any]) -> LedgerInput:
    if case.get("synthetic") is not True:
        raise ValueError("Reference adapter accepts explicitly synthetic fixtures only")
    case_id = case["id"]
    normalized = case["normalized"]
    terms = normalized["commitment_terms_cents"]
    if terms == []:
        raise ValueError("An unknown base must be null; a known zero base must be [0]")

    def term(index: int, amount: int) -> AmountRecord:
        return AmountRecord(
            id=f"{case_id}:term:{index}",
            amount_cents=amount,
            evidence_refs=(f"synthetic:{case_id}:commitment:{index}",),
            origin="derived",
        )

    return LedgerInput(
        case_id=case_id,
        case_revision=0,
        agreement=None if terms is None else term(0, terms[0]),
        adjustments=() if terms is None else tuple(term(i, v) for i, v in enumerate(terms[1:], 1)),
        cash_events=tuple(
            CashEvent(
                id=f"{case_id}:cash:{i}",
                amount_cents=amount,
                evidence_refs=(f"synthetic:{case_id}:cash:{i}",),
                origin="derived",
                state="completed",
            )
            for i, amount in enumerate(normalized["completed_cash_cents"])
        ),
        requested_now_cents=normalized["requested_now_cents"],
    )
