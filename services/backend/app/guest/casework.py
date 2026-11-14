"""Pure question identity, financial dependency fingerprints and evidence checks."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.normalization.models import Question

from .calculation import ReviewResult
from .casework_models import CardCommand, CardEvent, Observation, QuestionCard
from .models import Problem, Project


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def stable_record(project: Project, record_id: str) -> str:
    for document in project.documents:
        for candidate in document.candidates:
            if record_id == candidate.id or record_id.startswith(candidate.id + ":r"):
                if candidate.account and candidate.transaction:
                    return "bank:" + fingerprint([candidate.account, candidate.transaction])
                return "record:" + candidate.id
    return "record:" + record_id


def anchors_for(project: Project, question: Question) -> list[str]:
    anchors = {stable_record(project, rid) for rid in question.record_ids}
    if question.code in {"NO_BASELINE", "STALE_REVIEW", "AMBIGUOUS_BASELINE"}:
        return ["case"]
    # Guest extraction questions carry immutable file/page IDs, not financial record IDs.
    for document in project.documents:
        if document.id in question.id:
            anchors.add("file:" + document.id)
    if question.code == "LINK_NOT_READY" and project.review:
        try:
            link = project.review.command.links[int(question.id.rsplit(":", 1)[1])]
            anchors.update(["record:" + link.from_id, "record:" + link.to_id])
        except (ValueError, IndexError):
            pass
    return sorted(anchors or {"case"})


def card_id(project: Project, code: str, anchors: list[str]) -> str:
    return "q-" + fingerprint([project.id, code, sorted(anchors)])[:32]


def observation(
    project: Project,
    result: ReviewResult,
    code: str,
    anchors: list[str],
    message: str,
    affects: list[str],
    *,
    active: bool,
) -> Observation:
    related = [
        r
        for r in result.history.records
        if "case" in anchors
        or stable_record(project, r.id) in anchors
        or any(
            "file:" + d.id in anchors and any(r.record_id == c.id for c in d.candidates)
            for d in project.documents
        )
    ]
    file_ids = {
        d.id
        for d in project.documents
        if "case" in anchors
        or "file:" + d.id in anchors
        or any(stable_record(project, c.id) in anchors for c in d.candidates)
    }
    sources = [s for s in result.sources if s.file_id in file_ids]
    choices = (
        {r.id: r.model_dump(mode="json") for r in project.review.command.records}
        if project.review
        else {}
    )
    records_basis: list[dict[str, Any]] = [
        {"candidate": c.model_dump(mode="json"), "choice": choices.get(c.id)}
        for d in project.documents
        if d.id in file_ids
        for c in d.candidates
    ]
    command = project.review.command if project.review else None
    basis = {
        "records": sorted(records_basis, key=lambda item: item["candidate"]["id"]),
        "files": sorted(
            (d.id, d.checksum, d.status, len(d.pages))
            for d in project.documents
            if d.id in file_ids
        ),
        "sources": sorted((s.source_id, fingerprint(s.text)) for s in sources),
        "cutoff": str(result.history.cutoff_date),
        "review_current": bool(
            project.review and project.review.basis_revision == project.revision
        ),
        "agreement": command.agreement_id if command else None,
        "request": command.request_id if command and "requested_now_cents" in affects else None,
        "links": sorted((link.kind, link.from_id, link.to_id) for link in command.links)
        if command
        else [],
    }
    prompt = message + " Please explain and identify the supporting document or page, if available."
    if code == "UNRESOLVED_RECIPIENT" and len(related) == 1:
        row = related[0]
        amount = (
            "this transfer"
            if row.amount_cents is None
            else (f"the USD {row.amount_cents // 100:,}.{abs(row.amount_cents) % 100:02d} transfer")
        )
        prompt = (
            f"Who received {amount} dated {row.effective_date.isoformat()}? "
            "Please explain its relationship to this renovation and identify supporting evidence."
        )
    values = result.calculation.model_dump(mode="json")
    return Observation(
        code=code,
        anchors=anchors,
        message=message,
        contractor_question=prompt,
        affects=affects,
        metric_values={m: values.get(m) for m in affects if m.endswith("_cents")},
        amounts_cents={r.record_id: r.amount_cents for r in related},
        record_ids=sorted(r.id for r in related),
        source_refs=sorted(s.source_id for s in sources),
        file_ids=sorted(file_ids),
        financial_revision=project.revision,
        basis_fingerprint=fingerprint(basis),
        active=active,
    )


def event(
    card: QuestionCard,
    kind: str,
    detail: str,
    actor: str,
    snapshot_id: str | None = None,
    source_refs: list[str] | None = None,
) -> None:
    now = datetime.now(UTC)
    card.updated_at = now
    card.events.append(
        CardEvent(
            id=str(uuid4()),
            at=now,
            actor=actor,
            kind=kind,
            detail=detail,
            evidence_state=card.evidence_state,
            owner_decision=card.owner_decision,
            financial_revision=card.observation.financial_revision,
            basis_fingerprint=card.observation.basis_fingerprint,
            record_ids=card.observation.record_ids,
            snapshot_id=snapshot_id,
            source_refs=source_refs if source_refs is not None else card.observation.source_refs,
        )
    )


def reconcile(
    project: Project, result: ReviewResult, existing: list[QuestionCard]
) -> list[QuestionCard]:
    cards = {c.id: c.model_copy(deep=True) for c in existing}
    current: dict[str, Observation] = {}
    for question in result.questions:
        anchors = anchors_for(project, question)
        key = card_id(project, question.code, anchors)
        current[key] = observation(
            project,
            result,
            question.code,
            anchors,
            question.message,
            list(question.affects),
            active=True,
        )
    for key, seen in current.items():
        if key not in cards:
            now = datetime.now(UTC)
            card = QuestionCard(id=key, created_at=now, updated_at=now, observation=seen)
            event(card, "opened", "Question observed in the calculation.", "system")
            cards[key] = card
    for key, card in cards.items():
        previous = card.observation
        seen = current.get(key) or observation(
            project,
            result,
            previous.code,
            previous.anchors,
            previous.message,
            previous.affects,
            active=False,
        )
        changed = seen.basis_fingerprint != previous.basis_fingerprint
        presence_changed = seen.active != previous.active
        card.observation = seen
        if changed or presence_changed:
            card.version += 1
            card.evidence_state = "needs_recheck"
            event(
                card,
                "basis_changed" if changed else "presence_changed",
                "Financial evidence changed; recheck the conclusion."
                if changed
                else "Question disappeared or returned; resolution is not verified.",
                "system",
            )
    return sorted(cards.values(), key=lambda c: (c.created_at, c.id))


def assess(
    card: QuestionCard,
    command: CardCommand,
    project: Project,
    result: ReviewResult,
    latest_snapshot_id: str | None,
) -> None:
    if command.expected_version != card.version:
        raise Problem(409, "This question changed. Reload before recording a decision.")
    if not command.note.strip() or not (command.evidence_state or command.owner_decision):
        raise Problem(422, "Provide a note and an evidence assessment or owner decision")
    if command.evidence_state == "explained_verified":
        if (
            not project.review
            or project.review.basis_revision != project.revision
            or command.snapshot_id != latest_snapshot_id
            or latest_snapshot_id is None
            or card.observation.active
            or set(card.observation.affects) & set(result.incomplete_metrics)
        ):
            raise Problem(422, "A current saved calculation without this uncertainty is required")
        rows = {r.id: r for r in result.history.records}
        checked = {
            item.record.id: {ref for ref in item.evidence_refs if ref.startswith("page:")}
            for item in (*result.normalization.included, *result.normalization.excluded)
            if item.record.id in card.observation.record_ids
            and item.effective_semantic_review in ("user_asserted", "reviewed_for_calculation")
            and item.reason != "REJECTED_BY_USER"
            and rows[item.record.id].review.extraction_review in ("checked", "corrected")
        }
        # Payment conditions have checked source pages but no ledger record.
        choices = {r.id: r for r in project.review.command.records}
        for document in project.documents:
            for candidate in document.candidates:
                if stable_record(project, candidate.id) not in card.observation.anchors:
                    continue
                choice = choices.get(candidate.id)
                ref = f"page:{document.id}:{candidate.page}"
                if (
                    choice
                    and choice.kind == "condition"
                    and choice.answer == "accept"
                    and ref in {c.source_id for c in result.conditions}
                ):
                    checked[candidate.id] = {ref}
        verified_refs = set().union(*checked.values()) if checked else set()
        if (
            not command.source_refs
            or not set(command.source_refs) <= verified_refs
            or not set(card.observation.record_ids) <= checked.keys()
            or any(not refs.intersection(command.source_refs) for refs in checked.values())
        ):
            raise Problem(422, "Select checked pages used by the related financial records")
        card.verified_snapshot_id = latest_snapshot_id
        card.verified_source_refs = sorted(set(command.source_refs))
    elif command.source_refs or command.snapshot_id:
        raise Problem(422, "Evidence citations are only accepted for a verified explanation")
    if command.evidence_state == "answer_insufficient" and not card.reply_ids:
        raise Problem(422, "Record an answer before assessing it as insufficient")
    if command.evidence_state:
        card.evidence_state = command.evidence_state
    if command.owner_decision:
        card.owner_decision = command.owner_decision
    card.version += 1
    event(
        card,
        "assessment",
        command.note.strip(),
        f"guest:{project.id}",
        command.snapshot_id,
        command.source_refs,
    )
