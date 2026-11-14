"""Translate reviewed evidence into the existing normalization → ledger pipeline."""

from datetime import UTC, date, datetime

from pydantic import Field

from app.ledger import calculate
from app.ledger.models import LedgerResult
from app.normalization import normalize
from app.normalization.models import (
    Adjustment,
    Agreement,
    Cash,
    ConfirmSemantics,
    Decision,
    FinancialRecord,
    HistoryInput,
    Link,
    Metric,
    NormalizationResult,
    PaymentRequest,
    Question,
    Review,
    SelectAgreement,
    Source,
)

from .extraction import cents
from .models import Model, Problem, Project, RecordChoice, ReviewCommand


class Evidence(Model):
    source_id: str
    file_id: str | None = None
    page: int | None = None
    title: str
    text: str
    origin: str


class ReviewResult(Model):
    history: HistoryInput
    normalization: NormalizationResult
    calculation: LedgerResult
    questions: list[Question]
    incomplete: bool
    incomplete_metrics: list[Metric]
    sources: list[Evidence]
    conditions: list[Evidence] = Field(default_factory=list)


class ProjectResponse(Model):
    project: Project
    result: ReviewResult


def validate_command(project: Project, command: ReviewCommand) -> None:
    if command.expected_revision != project.revision:
        raise Problem(409, "Documents changed. Reload and review the current revision.")
    candidates = {c.id: c for d in project.documents for c in d.candidates}
    ids = [r.id for r in command.records]
    if len(ids) != len(set(ids)) or set(ids) != set(candidates):
        raise Problem(422, "Review each current candidate exactly once")
    kinds = {r.id: r.kind for r in command.records}
    for row in command.records:
        if row.amount is not None:
            try:
                value = cents(row.amount)
            except ValueError as error:
                raise Problem(422, str(error)) from error
            if row.kind in ("agreement", "payment_request", "payment") and value < 0:
                raise Problem(422, "This record requires a nonnegative amount")
            if row.kind == "refund" and value >= 0:
                raise Problem(422, "A refund must be negative")
        if row.answer == "accept" and row.kind != "condition":
            if row.kind == "unknown" or row.amount is None or row.date is None:
                raise Problem(422, "An accepted financial record needs a meaning, amount and date")
    for selected, kind in (
        (command.agreement_id, "agreement"),
        (command.request_id, "payment_request"),
    ):
        if selected is not None and kinds.get(selected) != kind:
            raise Problem(422, "The selected record has the wrong meaning or does not exist")
    pairs: set[tuple[str, str, str]] = set()
    for link in command.links:
        if link.from_id == link.to_id or link.from_id not in kinds or link.to_id not in kinds:
            raise Problem(422, "A relationship must reference two different existing records")
        if kinds[link.from_id] != "agreement" or kinds[link.to_id] != (
            "agreement" if link.kind == "supersedes" else "adjustment"
        ):
            raise Problem(422, "A relationship must connect compatible record meanings")
        pair = (link.kind, link.from_id, link.to_id)
        if pair in pairs:
            raise Problem(422, "Duplicate relationship")
        pairs.add(pair)


def result_for(project: Project) -> ReviewResult:
    review = project.review
    actor = f"guest:{project.id}"
    sources: list[Source] = []
    evidence: list[Evidence] = []
    records: list[FinancialRecord] = []
    record_ids: dict[str, str] = {}
    decisions: list[Decision] = []
    links: list[Link] = []
    questions: list[Question] = []
    conditions: list[Evidence] = []
    choices = {r.id: r for r in review.command.records} if review else {}
    current = review is not None and review.basis_revision == project.revision
    all_metrics: tuple[Metric, ...] = (
        "commitment_total_cents",
        "net_paid_cents",
        "remaining_commitment_cents",
        "requested_now_cents",
    )

    def question(key: str, message: str, ids: tuple[str, ...] = ()) -> None:
        questions.append(
            Question(
                id=key, code=key.split(":")[0], record_ids=ids, affects=all_metrics, message=message
            )
        )

    audit_ref: str | None = None
    if review:
        audit_ref = f"review:{review.id}"
        sources.append(
            Source(
                id=audit_ref,
                case_id=project.id,
                version=1,
                origin="user_statement",
                locator=f"audit:{review.id}",
                actor_id=actor,
            )
        )
        evidence.append(
            Evidence(
                source_id=audit_ref,
                title="Your recorded review",
                text=review.command.model_dump_json(),
                origin="user_statement",
            )
        )
        if not current:
            question(
                "STALE_REVIEW",
                "The documents changed. Recheck your choices before relying on this result.",
            )
    for document in project.documents:
        if document.status != "ready":
            question(
                f"DOCUMENT_NOT_READY:{document.id}",
                f"{document.name}: {document.status}. "
                "The calculation does not yet include all document evidence.",
            )
        if document.status == "ready" and not document.candidates:
            question(
                f"NO_CANDIDATES:{document.id}",
                f"No financial facts were recognized in {document.name}. "
                "Upload a clearer, labelled document. Unknown amounts are not zero.",
            )
        for page in document.pages:
            source_id = f"page:{document.id}:{page.number}"
            sources.append(
                Source(
                    id=source_id,
                    case_id=project.id,
                    version=1,
                    origin="document",
                    locator=f"file:{document.id}#page={page.number}",
                )
            )
            evidence.append(
                Evidence(
                    source_id=source_id,
                    file_id=document.id,
                    page=page.number,
                    title=f"{document.name} · page {page.number}",
                    text=page.text,
                    origin=page.method,
                )
            )
            if page.warning:
                question(f"UNREADABLE:{source_id}", page.warning)
        for candidate in document.candidates:
            choice = choices.get(candidate.id)
            if choice is None:
                choice = RecordChoice(
                    id=candidate.id,
                    kind=candidate.kind,
                    amount=candidate.amount,
                    date=date.fromisoformat(candidate.date) if candidate.date else None,
                    state=candidate.state,
                )
            refs: tuple[str, ...] = (f"page:{document.id}:{candidate.page}",)
            if candidate.id in choices and audit_ref:
                refs += (audit_ref,)
            if choice.answer == "reject" and current:
                # Keep known dated records in the domain for bank-ID conflict reconciliation.
                if choice.date is None or choice.kind in ("condition", "unknown"):
                    continue
            if choice.kind == "condition":
                if choice.answer == "accept" and current:
                    conditions.append(
                        Evidence(
                            source_id=refs[0],
                            file_id=document.id,
                            page=candidate.page,
                            title=document.name,
                            text=candidate.snippet,
                            origin="document",
                        )
                    )
                elif choice.answer != "reject":
                    question(
                        f"REVIEW_CONDITION:{candidate.id}",
                        "Check the payment condition against the original.",
                        (candidate.id,),
                    )
                continue
            if choice.kind == "unknown" or choice.date is None:
                question(
                    f"MISSING_FACT:{candidate.id}",
                    "Confirm this record's meaning and date.",
                    (candidate.id,),
                )
                continue
            value = cents(choice.amount) if choice.amount is not None else None
            corrected = (choice.amount, choice.date.isoformat(), choice.kind) != (
                candidate.amount,
                candidate.date,
                candidate.kind,
            )
            extraction_review = Review()
            if review and candidate.id in choices and choice.answer == "accept":
                extraction_review = Review(
                    extraction_review="corrected" if corrected else "checked",
                    extraction_actor_id=actor,
                    extraction_reviewed_at=review.created_at,
                )
            record_version = review.basis_revision + 1 if review and candidate.id in choices else 1
            fields = dict(
                id=f"{candidate.id}:r{record_version}",
                record_id=candidate.id,
                version=record_version,
                effective_date=choice.date,
                amount_cents=value,
                contractor_id=(
                    actor
                    if choice.recipient == "contractor"
                    else "other"
                    if choice.recipient == "other"
                    else None
                ),
                evidence_refs=refs,
                origin="user_statement" if corrected and audit_ref else "document",
                review=extraction_review.model_dump(mode="json"),
            )
            # JSON validation preserves the strict domain contract (date and tuples).
            import json

            payload = json.dumps(fields, default=str)
            if choice.kind == "agreement":
                record: FinancialRecord = Agreement.model_validate_json(payload)
            elif choice.kind == "adjustment":
                record = Adjustment.model_validate_json(payload)
            elif choice.kind == "payment_request":
                record = PaymentRequest.model_validate_json(payload)
            else:
                fields.update(
                    state=choice.state,
                    bank_account_id=candidate.account,
                    bank_transaction_id=candidate.transaction,
                )
                record = Cash.model_validate_json(json.dumps(fields, default=str))
            records.append(record)
            record_ids[candidate.id] = record.id
            if review and audit_ref and candidate.id in choices:
                decisions.append(
                    ConfirmSemantics(
                        id=f"decision:{review.id}:{candidate.id}",
                        target_id=record.id,
                        basis_revision=review.basis_revision,
                        actor_id=actor,
                        decided_at=review.created_at,
                        evidence_refs=(audit_ref,),
                        answer=choice.answer,
                    )
                )
    if review and audit_ref:
        if review.command.agreement_id is None or review.command.agreement_id in record_ids:
            decisions.append(
                SelectAgreement(
                    id=f"selection:{review.id}",
                    target_id=project.id,
                    basis_revision=review.basis_revision,
                    actor_id=actor,
                    decided_at=review.created_at,
                    evidence_refs=(audit_ref,),
                    selected_id=record_ids.get(review.command.agreement_id or ""),
                )
            )
        for index, link in enumerate(review.command.links):
            if link.from_id in record_ids and link.to_id in record_ids:
                links.append(
                    Link(
                        id=f"link:{review.id}:{index}",
                        kind=link.kind,
                        from_id=record_ids[link.from_id],
                        to_id=record_ids[link.to_id],
                        review="accepted",
                        basis_revision=review.basis_revision,
                        evidence_refs=(audit_ref,),
                        actor_id=actor,
                        reviewed_at=review.created_at,
                    )
                )
            else:
                question(
                    f"LINK_NOT_READY:{index}",
                    "Complete both linked records before using this relationship.",
                )
    request_id = review.command.request_id if review else None
    history = HistoryInput(
        case_id=project.id,
        case_revision=project.revision,
        contractor_id=actor,
        cutoff_date=review.command.cutoff_date if review else datetime.now(UTC).date(),
        current_request_id=record_ids.get(request_id or ""),
        sources=tuple(sources),
        records=tuple(records),
        links=tuple(links),
        decisions=tuple(decisions),
    )
    normalized = normalize(history)
    calculation = calculate(normalized.ledger_input)
    questions.extend(normalized.questions)
    metrics = set(normalized.incomplete_metrics)
    for q in questions:
        metrics.update(q.affects)
    return ReviewResult(
        history=history,
        normalization=normalized,
        calculation=calculation,
        sources=evidence,
        questions=questions,
        conditions=conditions,
        incomplete=bool(questions),
        incomplete_metrics=sorted(metrics),
    )
