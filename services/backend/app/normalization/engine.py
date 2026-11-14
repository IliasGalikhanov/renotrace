"""Deterministic selection and reconciliation of structured financial history."""

import hashlib
import json
from collections import defaultdict

from app.ledger import AmountRecord, CashEvent, LedgerInput

from .models import (
    Adjustment,
    Agreement,
    AssignContractor,
    Cash,
    ConfirmSemantics,
    Decision,
    Disposition,
    FinancialRecord,
    HistoryInput,
    Metric,
    NormalizationResult,
    Question,
    ReviewLink,
    SelectAgreement,
    SelectVersion,
)
from .validation import validate_history

NORMALIZATION_VERSION = "normalization-0.1.1"
TERMS: tuple[Metric, ...] = ("commitment_total_cents", "remaining_commitment_cents")
CASH: tuple[Metric, ...] = ("net_paid_cents", "remaining_commitment_cents")
REQUEST: tuple[Metric, ...] = ("requested_now_cents",)


class _Context:
    def __init__(self, history: HistoryInput) -> None:
        self.history = history
        self.records = {row.id: row for row in history.records}
        self.refs = {row.id: set(row.evidence_refs) for row in history.records}
        self.used: dict[str, set[str]] = {row.id: set() for row in history.records}
        self.contractors = {row.id: row.contractor_id for row in history.records}
        self.semantics = {row.id: row.review.semantic_review for row in history.records}
        self.questions: dict[str, Question] = {}
        self.included: dict[str, Disposition] = {}
        self.excluded: dict[str, Disposition] = {}
        self.resolved: dict[tuple[str, str], Decision] = {}
        self.decision_sets: dict[tuple[str, str], tuple[Decision, ...]] = {}
        self.blocked: set[tuple[str, str]] = set()
        self.link_states: dict[str, str] = {}
        self.uncertain_transactions: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._decisions()
        self._links()

    def question(
        self,
        code: str,
        ids: tuple[str, ...],
        message: str,
        affects: tuple[Metric, ...] | None = None,
        decision_ids: tuple[str, ...] = (),
    ) -> None:
        ids = tuple(sorted(set(ids)))
        metrics: set[Metric] = set()
        for record_id in ids:
            row = self.records[record_id]
            metrics.update(
                CASH if row.kind == "cash" else REQUEST if row.kind == "payment_request" else TERMS
            )
        decision_ids = tuple(sorted(decision_ids))
        digest = hashlib.sha256(json.dumps([code, ids, decision_ids]).encode()).hexdigest()[:20]
        key = f"question:{digest}"
        self.questions[key] = Question(
            id=key,
            code=code,
            record_ids=ids,
            decision_ids=decision_ids,
            affects=tuple(sorted(metrics if affects is None else affects)),
            message=message,
        )

    def scope(self, decision: Decision) -> tuple[str, ...]:
        if isinstance(decision, SelectVersion):
            return tuple(
                row.id for row in self.records.values() if row.record_id == decision.target_id
            )
        if isinstance(decision, SelectAgreement):
            return tuple(row.id for row in self.records.values() if row.kind == "agreement")
        if isinstance(decision, ReviewLink):
            link = next(link for link in self.history.links if link.id == decision.target_id)
            return (link.from_id, link.to_id)
        return (decision.target_id,)

    def _decisions(self) -> None:
        groups: dict[tuple[str, str], list[Decision]] = defaultdict(list)
        for decision in self.history.decisions:
            groups[(decision.kind, decision.target_id)].append(decision)
        for key, group in sorted(groups.items()):
            current = sorted(
                (d for d in group if d.basis_revision == self.history.case_revision),
                key=lambda d: d.id,
            )
            if not current:
                self.blocked.add(key)
                self.question(
                    "STALE_DECISION",
                    self.scope(group[0]),
                    "Review this decision against the current history revision.",
                    decision_ids=tuple(d.id for d in group),
                )
                continue
            signatures = {
                d.model_dump_json(
                    include={"kind", "target_id", "selected_id", "contractor_id", "answer"}
                )
                for d in current
            }
            if len(signatures) != 1:
                self.blocked.add(key)
                self.question(
                    "DECISION_CONFLICT",
                    self.scope(current[0]),
                    "Conflicting current decisions need an explicit resolution.",
                    decision_ids=tuple(d.id for d in current),
                )
                continue
            self.resolved[key] = current[0]
            self.decision_sets[key] = tuple(current)

    def use(self, key: tuple[str, str], ids: tuple[str, ...]) -> Decision | None:
        for decision in self.decision_sets.get(key, ()):
            for record_id in ids:
                self.used[record_id].add(decision.id)
                self.refs[record_id].update(decision.evidence_refs)
        return self.resolved.get(key)

    def _links(self) -> None:
        for link in sorted(self.history.links, key=lambda link: link.id):
            key = ("review_link", link.id)
            decision = self.use(key, (link.from_id, link.to_id))
            if key in self.blocked:
                state = "unknown"
            elif isinstance(decision, ReviewLink):
                state = {"accept": "accepted", "reject": "rejected", "unknown": "unknown"}[
                    decision.answer
                ]
            elif link.basis_revision != self.history.case_revision:
                state = "unknown"
                self.question(
                    "STALE_LINK",
                    (link.from_id, link.to_id),
                    "Recheck the relationship after the history changed.",
                )
            else:
                state = link.review if link.review in ("accepted", "rejected") else "unknown"
            self.link_states[link.id] = state

    def disposition(
        self,
        row: FinancialRecord,
        reason: str,
        *,
        included: bool = False,
        canonical: str | None = None,
    ) -> None:
        result = Disposition(
            record=row,
            reason=reason,
            canonical_record_id=canonical,
            evidence_refs=tuple(sorted(self.refs[row.id])),
            decision_ids=tuple(sorted(self.used[row.id])),
            effective_contractor_id=self.contractors[row.id],
            effective_semantic_review=self.semantics[row.id],
        )
        (self.included if included else self.excluded)[row.id] = result

    def candidates(self) -> list[FinancialRecord]:
        groups: dict[str, list[FinancialRecord]] = defaultdict(list)
        for row in sorted(self.records.values(), key=lambda row: row.id):
            assign = self.use(("assign_contractor", row.id), (row.id,))
            if isinstance(assign, AssignContractor):
                self.contractors[row.id] = assign.contractor_id
            semantic = self.use(("confirm_semantics", row.id), (row.id,))
            if isinstance(semantic, ConfirmSemantics):
                self.semantics[row.id] = (
                    "user_asserted" if semantic.answer == "accept" else "unknown"
                )
            if row.review.lifecycle != "active":
                if row.review.lifecycle == "stale":
                    self.question(
                        "STALE_RECORD", (row.id,), "Review this record against its changed source."
                    )
                self.disposition(row, "INACTIVE_RECORD")
            elif row.kind != "cash" and row.effective_date > self.history.cutoff_date:
                self.disposition(row, "AFTER_CUTOFF")
            else:
                groups[row.record_id].append(row)
        candidates: list[FinancialRecord] = []

        def uncertain(group: list[FinancialRecord]) -> None:
            for item in group:
                if (
                    isinstance(item, Cash)
                    and item.bank_account_id is not None
                    and item.bank_transaction_id is not None
                ):
                    self.uncertain_transactions[
                        (item.bank_account_id, item.bank_transaction_id)
                    ].add(item.id)

        for logical_id, group in sorted(groups.items()):
            key = ("select_version", logical_id)
            selection = self.use(key, tuple(row.id for row in group))
            if key in self.blocked:
                uncertain(group)
                for row in group:
                    self.disposition(row, "INVALID_DECISION")
            elif isinstance(selection, SelectVersion):
                contradiction = any(
                    link.kind == "supersedes"
                    and link.to_id == selection.selected_id
                    and link.from_id in {row.id for row in group}
                    and self.link_states[link.id] == "accepted"
                    for link in self.history.links
                )
                if contradiction:
                    self.question(
                        "SELECTION_LINK_CONFLICT",
                        tuple(row.id for row in group),
                        "The selected revision is replaced by a confirmed relationship. "
                        "Resolve that relationship first.",
                    )
                    for row in group:
                        self.disposition(row, "VERSION_CONFLICT")
                    continue
                if selection.selected_id not in {row.id for row in group}:
                    uncertain(group)
                    self.question(
                        "VERSION_SELECTION_REQUIRED",
                        tuple(row.id for row in group),
                        "Select an eligible record revision for this history.",
                    )
                for row in group:
                    if row.id == selection.selected_id:
                        candidates.append(row)
                    else:
                        self.disposition(row, "VERSION_NOT_SELECTED")
            elif len(group) > 1 and group[0].kind != "agreement":
                uncertain(group)
                self.question(
                    "RECORD_VERSION_CONFLICT",
                    tuple(row.id for row in group),
                    "Choose the record revision; upload order is not a selection.",
                )
                for row in group:
                    self.disposition(row, "VERSION_CONFLICT")
            else:
                candidates.extend(group)
        return candidates

    def usable(self, row: FinancialRecord) -> bool:
        if any(
            (kind, row.id) in self.blocked for kind in ("assign_contractor", "confirm_semantics")
        ):
            self.disposition(row, "INVALID_DECISION")
            return False
        semantic = self.resolved.get(("confirm_semantics", row.id))
        if isinstance(semantic, ConfirmSemantics) and semantic.answer == "reject":
            self.disposition(row, "REJECTED_BY_USER")
            return False
        if self.semantics[row.id] == "unknown":
            self.question(
                "SEMANTIC_REVIEW_REQUIRED", (row.id,), "Confirm what this financial record means."
            )
            self.disposition(row, "UNREVIEWED_SEMANTICS")
            return False
        contractor = self.contractors[row.id]
        if contractor is None:
            self.question(
                "UNRESOLVED_RECIPIENT", (row.id,), "Identify the contractor for this record."
            )
            self.disposition(row, "UNKNOWN_CONTRACTOR")
            return False
        if contractor != self.history.contractor_id:
            self.disposition(row, "OTHER_CONTRACTOR")
            return False
        if row.amount_cents is None:
            self.question(
                "MISSING_AMOUNT",
                (row.id,),
                "Provide the amount with a source before including this record.",
            )
            self.disposition(row, "UNKNOWN_AMOUNT")
            return False
        return True

    def amount(self, row: FinancialRecord) -> AmountRecord:
        assert row.amount_cents is not None
        return AmountRecord(
            id=f"record:{row.id}",
            amount_cents=row.amount_cents,
            evidence_refs=tuple(sorted(self.refs[row.id])),
            origin=row.origin,
        )

    def agreements(
        self, candidates: list[FinancialRecord]
    ) -> tuple[AmountRecord | None, tuple[AmountRecord, ...]]:
        bases = [row for row in candidates if isinstance(row, Agreement) and self.usable(row)]
        by_id = {row.id: row for row in bases}
        edges: dict[str, set[str]] = defaultdict(set)
        for link in self.history.links:
            if link.kind == "supersedes" and self.link_states[link.id] == "accepted":
                edges[link.from_id].add(link.to_id)

        def ancestors(start: str) -> set[str]:
            seen: set[str] = set()
            todo = list(edges[start])
            while todo:
                value = todo.pop()
                if value not in seen:
                    seen.add(value)
                    todo.extend(edges[value])
            return seen

        replaced = set().union(*(ancestors(row.id) for row in bases))
        heads = [row for row in bases if row.id not in replaced]
        key = ("select_agreement", self.history.case_id)
        selection = self.use(key, tuple(row.id for row in bases))
        selected: Agreement | None = None
        if key in self.blocked:
            pass
        elif isinstance(selection, SelectAgreement):
            if selection.selected_id in by_id and selection.selected_id not in replaced:
                selected = by_id[selection.selected_id]
            else:
                self.question(
                    "AGREEMENT_SELECTION_REQUIRED",
                    tuple(row.id for row in bases),
                    "Select an eligible, non-replaced agreement.",
                    TERMS,
                )
        elif len(heads) == 1:
            selected = heads[0]
        elif len(heads) > 1:
            self.question(
                "AGREEMENT_VERSION_CONFLICT",
                tuple(row.id for row in heads),
                "Confirm which agreement applies; the latest upload is not chosen automatically.",
                TERMS,
            )
        if selected is None:
            self.question(
                "MISSING_AGREEMENT", (), "No definite agreement baseline is selected.", TERMS
            )
        for base_record in bases:
            if selected is None or base_record.id != selected.id:
                self.disposition(
                    base_record,
                    "SUPERSEDED" if base_record.id in replaced else "AGREEMENT_NOT_SELECTED",
                )

        lineage = set() if selected is None else {selected.id, *ancestors(selected.id)}
        if selected is not None:
            for link in self.history.links:
                if (
                    link.kind == "supersedes"
                    and link.from_id in lineage
                    and self.link_states[link.id] == "accepted"
                ):
                    self.refs[selected.id].update(link.evidence_refs)
                    self.refs[selected.id].update(self.refs[link.from_id])
                    self.refs[selected.id].update(self.refs[link.to_id])
                    self.used[selected.id].update(self.used[link.from_id] | self.used[link.to_id])
        adjustments: list[AmountRecord] = []
        for row in candidates:
            if not isinstance(row, Adjustment) or not self.usable(row):
                continue
            relations = [
                link
                for link in self.history.links
                if link.kind == "includes_adjustment"
                and link.to_id == row.id
                and link.from_id in lineage
                and self.link_states[link.id] != "rejected"
            ]
            direct = [
                link for link in relations if selected is not None and link.from_id == selected.id
            ]
            if any(self.link_states[link.id] == "accepted" for link in direct):
                assert selected is not None
                self.refs[selected.id].update(self.refs[row.id])
                for link in direct:
                    self.refs[selected.id].update(link.evidence_refs)
                self.disposition(row, "INCLUDED_IN_BASE", canonical=f"record:{selected.id}")
            elif relations:
                self.question(
                    "ADJUSTMENT_INCLUSION_UNRESOLVED",
                    (row.id,),
                    "Clarify whether this change is already included in the selected estimate.",
                    TERMS,
                )
                self.disposition(row, "UNRESOLVED_INCLUSION")
            elif selected is None:
                self.disposition(row, "NO_AGREEMENT_BASE")
            else:
                value = self.amount(row)
                adjustments.append(value)
                self.disposition(row, "ACCEPTED_ADJUSTMENT", included=True, canonical=value.id)
        base = None if selected is None else self.amount(selected)
        if selected is not None:
            self.disposition(
                selected, "SELECTED_AGREEMENT", included=True, canonical=base.id if base else None
            )
        return base, tuple(sorted(adjustments, key=lambda row: row.id))

    def transaction_question(self, code: str, record_ids: tuple[str, ...], message: str) -> None:
        affected = set(record_ids)
        self.question(
            code,
            record_ids,
            message,
            CASH,
            decision_ids=tuple(
                decision.id
                for decision in self.history.decisions
                if affected.intersection(self.scope(decision))
            ),
        )

    def cash(self, candidates: list[FinancialRecord]) -> tuple[CashEvent, ...]:
        groups: dict[tuple[str, ...], list[Cash]] = defaultdict(list)
        identity: tuple[str, ...]
        for row in candidates:
            if isinstance(row, Cash):
                identity = (
                    ("bank", row.bank_account_id, row.bank_transaction_id)
                    if row.bank_account_id is not None and row.bank_transaction_id is not None
                    else ("record", row.id)
                )
                groups[identity].append(row)
        result: list[CashEvent] = []
        for identity, group in sorted(groups.items()):
            group.sort(key=lambda row: row.id)
            unresolved = (
                self.uncertain_transactions.get((identity[1], identity[2]), set())
                if identity[0] == "bank"
                else set()
            )
            if unresolved:
                self.transaction_question(
                    "TRANSACTION_VERSION_UNRESOLVED",
                    tuple(unresolved | {row.id for row in group}),
                    "Resolve the ambiguous revisions of this bank operation "
                    "before using another import.",
                )
                for row in group:
                    self.disposition(row, "UNRESOLVED_TRANSACTION")
                continue
            signatures = {
                (row.amount_cents, row.effective_date, row.state, self.contractors[row.id])
                for row in group
            }
            if len(signatures) > 1:
                self.question(
                    "TRANSACTION_CONFLICT",
                    tuple(row.id for row in group),
                    "Sources disagree about one bank operation. Resolve it before counting it.",
                    CASH,
                )
                for row in group:
                    self.disposition(row, "TRANSACTION_CONFLICT")
                continue
            first = group[0]
            reason = (
                "AFTER_CUTOFF"
                if first.effective_date > self.history.cutoff_date
                else "NOT_COMPLETED"
                if first.state != "completed"
                else None
            )
            if reason is not None:
                for row in group:
                    self.disposition(row, reason)
                continue
            usable = [self.usable(row) for row in group]
            if not all(usable):
                if any(usable):
                    self.transaction_question(
                        "TRANSACTION_REVIEW_CONFLICT",
                        tuple(row.id for row in group),
                        "Confirmations of this bank operation disagree or are unresolved. "
                        "Clarify them before counting the payment.",
                    )
                for row, accepted in zip(group, usable, strict=True):
                    if accepted:
                        self.disposition(row, "UNRESOLVED_TRANSACTION")
                continue
            canonical = (
                "bank:" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
                if identity[0] == "bank"
                else f"record:{first.id}"
            )
            refs = tuple(sorted(set().union(*(self.refs[row.id] for row in group))))
            origins = {row.origin for row in group}
            assert first.amount_cents is not None
            result.append(
                CashEvent(
                    id=canonical,
                    amount_cents=first.amount_cents,
                    evidence_refs=refs,
                    origin=first.origin if len(origins) == 1 else "derived",
                    state="completed",
                )
            )
            for row in group:
                self.disposition(
                    row,
                    "ACCEPTED_CASH" if row is first else "DUPLICATE_BANK_OPERATION",
                    included=row is first,
                    canonical=canonical,
                )
        return tuple(sorted(result, key=lambda row: row.id))

    def run(self) -> NormalizationResult:
        candidates = self.candidates()
        agreement, adjustments = self.agreements(candidates)
        cash_events = self.cash(candidates)
        requested = None
        for row in candidates:
            if row.kind != "payment_request":
                continue
            if row.id != self.history.current_request_id:
                self.disposition(row, "NOT_CURRENT_REQUEST")
            elif self.usable(row):
                requested = row.amount_cents
                self.disposition(row, "CURRENT_REQUEST", included=True)
        if self.history.current_request_id is not None and requested is None:
            self.question(
                "CURRENT_REQUEST_UNRESOLVED",
                (self.history.current_request_id,),
                "The selected payment request is not eligible for this history.",
                REQUEST,
            )
        ledger = LedgerInput(
            case_id=self.history.case_id,
            case_revision=self.history.case_revision,
            agreement=agreement,
            adjustments=adjustments,
            cash_events=cash_events,
            requested_now_cents=requested,
        )
        questions = tuple(sorted(self.questions.values(), key=lambda q: (q.code, q.record_ids)))
        applied = set().union(*self.used.values())
        return NormalizationResult(
            normalization_version=NORMALIZATION_VERSION,
            ledger_input=ledger,
            included=tuple(self.included[key] for key in sorted(self.included)),
            excluded=tuple(self.excluded[key] for key in sorted(self.excluded)),
            questions=questions,
            incomplete=bool(questions),
            incomplete_metrics=tuple(sorted({m for q in questions for m in q.affects})),
            sources=tuple(sorted(self.history.sources, key=lambda source: source.id)),
            links=tuple(sorted(self.history.links, key=lambda link: link.id)),
            applied_decisions=tuple(
                sorted((d for d in self.history.decisions if d.id in applied), key=lambda d: d.id)
            ),
        )


def normalize(history: HistoryInput) -> NormalizationResult:
    if not isinstance(history, HistoryInput):
        raise TypeError("normalize requires a validated HistoryInput")
    validate_history(history)
    return _Context(history).run()
