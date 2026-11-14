"""Pure comparison of frozen reviewed evidence; never calculates C/P/R."""

from typing import Any

from .invoices import bounded
from .models import Problem
from .recheck_models import Package


def composition(snapshot: dict[str, Any], request_id: str | None) -> dict[str, Any] | None:
    return next(
        (
            c
            for c in snapshot["result"].get("invoice_compositions", [])
            if c["request_id"] == request_id
        ),
        None,
    )


def compare(before: dict[str, Any], after: dict[str, Any], package: Package) -> dict[str, Any]:
    old, new = (
        composition(before, package.old_request_id),
        composition(after, package.new_request_id),
    )
    old_rows = (
        {r["value"]["id"]: r for r in old["lines"] if r["value"]["review"] != "excluded"}
        if old
        else {}
    )
    new_rows = (
        {r["value"]["id"]: r for r in new["lines"] if r["value"]["review"] != "excluded"}
        if new
        else {}
    )
    pairs = [(m.old_id, m.new_id) for m in package.matches]
    if package.relationship == "same" and not pairs:
        pairs = [(key, key) for key in sorted(old_rows.keys() & new_rows.keys())]
    used_old: set[str] = set()
    used_new: set[str] = set()
    changes: list[dict[str, Any]] = []
    issues: list[str] = []
    for left, right in pairs:
        if not left and not right:
            raise Problem(422, "A correspondence needs at least one position")
        if (left and (left not in old_rows or left in used_old)) or (
            right and (right not in new_rows or right in used_new)
        ):
            raise Problem(422, "Unknown or conflicting invoice-position correspondence")
        a, b = old_rows.get(left or ""), new_rows.get(right or "")
        if left:
            used_old.add(left)
        if right:
            used_new.add(right)
        checked = all(r is None or r["value"]["review"] == "checked" for r in (a, b))
        fields = []
        if a and b:
            fields = [
                key
                for key in (
                    "kind",
                    "description",
                    "amount",
                    "quantity",
                    "unit_price",
                    "cash_record_id",
                )
                if a["value"].get(key) != b["value"].get(key)
            ]
        if not checked:
            issues.append("A correspondence includes an unverified or excluded position.")
        change = (
            "changed"
            if a and b and fields
            else "unchanged"
            if a and b
            else "added"
            if b
            else "removed"
        )
        delta = (
            bounded(b["signed_cents"] - a["signed_cents"])
            if a and b and all(r["signed_cents"] is not None for r in (a, b))
            else None
        )
        changes.append(
            {
                "old": a,
                "new": b,
                "change": change,
                "fields": fields,
                "signed_delta_cents": delta,
                "checked": checked,
            }
        )
        if change == "added" and b and b["value"]["kind"] in ("work", "charge"):
            issues.append(
                "New work/charge appears in the invoice. Confirm its contractual "
                "approval separately; this row does not change C."
            )
        if change == "changed" and b and b["value"]["kind"] in ("work", "charge"):
            issues.append(
                "Changed work/charge details require checking scope and approval separately; "
                "a matched position does not amend the recorded contract."
            )
    unmatched_old = [old_rows[k] for k in sorted(old_rows.keys() - used_old)]
    unmatched_new = [new_rows[k] for k in sorted(new_rows.keys() - used_new)]
    if unmatched_old or unmatched_new:
        issues.append("Some positions are not matched or explicitly classified as added/removed.")
    if package.relationship == "unknown":
        issues.append(
            "Choose whether the new request corrects this invoice or is a separate invoice."
        )
    if package.relationship == "separate":
        issues.append("These are separate invoices, not a confirmed correction of the original.")
    for name, invoice in (("Previous", old), ("New", new)):
        if invoice is None:
            issues.append(
                f"{name} snapshot has no reviewed invoice composition. It cannot be "
                "reconstructed silently."
            )
        elif not invoice["complete"]:
            issues.append(f"{name} composition is incomplete: " + " ".join(invoice["issues"]))
    # Description/kind can suggest a pair, but never accept it, and never match by amount.
    suggestions = []
    for a in unmatched_old:
        candidates = [
            b
            for b in unmatched_new
            if b["value"]["kind"] == a["value"]["kind"]
            and b["value"]["description"].strip().casefold()
            == a["value"]["description"].strip().casefold()
        ]
        if candidates:
            suggestions.append(
                {
                    "old_id": a["value"]["id"],
                    "new_ids": [b["value"]["id"] for b in candidates],
                    "basis": "same description and kind; owner confirmation required",
                }
            )
    metric_changes = {}
    for metric in (
        "requested_now_cents",
        "commitment_total_cents",
        "net_paid_cents",
        "remaining_commitment_cents",
    ):
        a, b = (
            before["result"]["calculation"].get(metric),
            after["result"]["calculation"].get(metric),
        )
        metric_changes[metric] = {
            "before": a,
            "after": b,
            "delta": bounded(b - a) if a is not None and b is not None else None,
        }
    old_cards = {c["id"]: c for c in before.get("discussion", {}).get("cards", [])}
    current_cards = {c["id"]: c for c in after.get("discussion", {}).get("cards", [])}
    original_cash = {
        d["record"]["record_id"]: d["canonical_record_id"]
        for group in ("included", "excluded")
        for d in before["result"]["normalization"][group]
        if d.get("canonical_record_id") and d["record"]["kind"] == "cash"
    }
    base_events = {
        e["id"] for e in before["result"]["normalization"]["ledger_input"]["cash_events"]
    }
    question_findings = []
    for link in package.question_links:
        if link.question_id not in old_cards or link.new_line_id not in new_rows:
            raise Problem(
                422, "Question evidence must reference the selected base snapshot and new invoice"
            )
    for qid, card in sorted(old_cards.items()):
        evidence = [
            new_rows[link.new_line_id] for link in package.question_links if link.question_id == qid
        ]
        reflections = [
            r
            for r in evidence
            if r["value"]["review"] == "checked"
            and r["value"]["kind"] in ("credit", "reflected_payment")
            and r.get("cash_event_id")
            and original_cash.get(r["value"].get("cash_record_id")) in base_events
            and (r["amount_cents"] or 0) > 0
        ]
        now = current_cards.get(qid)
        linked_ids = {row["value"]["id"] for row in evidence}
        checked_evidence = any(row["value"]["review"] == "checked" for row in evidence)
        payment_question = card["observation"]["code"] in {
            "REQUEST_RECONCILIATION",
            "UNRESOLVED_TRANSACTION",
            "UNRESOLVED_RECIPIENT",
        }
        question_findings.append(
            {
                "question_id": qid,
                "original_question": card["observation"]["message"],
                "evidence": evidence,
                "payment_reflection": reflections,
                "linked_changes": [
                    change
                    for change in changes
                    if change["new"] and change["new"]["value"]["id"] in linked_ids
                ],
                "affected_metric_changes": {
                    key: value
                    for key, value in metric_changes.items()
                    if key in card["observation"]["affects"]
                },
                "finding": "Checked invoice position explicitly cites a payment already in the "
                "original ledger. No additional payment is created."
                if reflections
                else "No checked invoice credit linked to an existing original payment "
                "establishes that it was reflected. A lower total or an explanation "
                "alone is insufficient."
                if payment_question
                else "The linked checked positions and their changes are shown below. "
                "They require an explicit assessment against this original question."
                if checked_evidence
                else "No checked invoice position has been explicitly linked "
                "to this question. An explanation or disappearance alone does not resolve it.",
                "still_unknown": "Evidence assessment and owner decision remain independent. "
                "Inspect remaining questions and source completeness.",
                "requires_recheck": bool(now and now["evidence_state"] == "needs_recheck"),
                "current_evidence_state": now["evidence_state"] if now else "needs_recheck",
                "owner_decision": now["owner_decision"] if now else card["owner_decision"],
            }
        )
    if package.replies:
        issues.append(
            "Replies are owner-reported explanations, not independently verified "
            "evidence. Their truth or contradictions are not automatically "
            "inferred."
        )
    if after["result"]["incomplete"]:
        issues.append("The current calculation still has unresolved financial/source questions.")
    unresolved = [c for c in current_cards.values() if c["evidence_state"] != "explained_verified"]
    if unresolved:
        issues.append(
            "Unresolved question history remains; disappearance or owner "
            "acceptance is not resolution."
        )
    return {
        "metrics": metric_changes,
        "old_composition": old,
        "new_composition": new,
        "changes": changes,
        "unmatched_old": unmatched_old,
        "unmatched_new": unmatched_new,
        "suggestions": suggestions,
        "question_findings": question_findings,
        "new_questions": [c for key, c in current_cards.items() if key not in old_cards],
        "conditions_before": before["result"].get("conditions", []),
        "conditions_after": after["result"].get("conditions", []),
        "explanation_only": package.relationship == "same"
        and all(v["delta"] == 0 for v in metric_changes.values())
        and not any(c["change"] != "unchanged" for c in changes),
        "issues": sorted(set(issues)),
        "preliminary": bool(issues),
        "notice": "Invoice differences are not savings. C/P/R come only from the "
        "recorded normalization and ledger results.",
    }
