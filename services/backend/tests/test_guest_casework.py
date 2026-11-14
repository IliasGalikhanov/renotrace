"""Stable identity and evidence assessments against the real financial pipeline."""

from uuid import uuid4

import pytest
from test_guest_extraction import accepted, project_from, save

from app.guest.calculation import result_for
from app.guest.casework import assess, reconcile
from app.guest.casework_models import CardCommand
from app.guest.models import Problem


def ambiguous():
    project = project_from("estimate.pdf", "payment.pdf", "invoice.pdf")
    command = accepted(project)
    next(r for r in command.records if r.kind == "payment").recipient = "unknown"
    save(project, command)
    result = result_for(project)
    cards = reconcile(project, result, [])
    card = next(c for c in cards if c.observation.code == "UNRESOLVED_RECIPIENT")
    return project, command, result, cards, card


def test_stable_identity_resave_reorder_and_no_fake_resolution():
    project, command, result, cards, card = ambiguous()
    card.reply_ids.append("reply-1")
    card.owner_decision = "stop_unresolved"
    initial = card.id
    project.revision += 1
    command.expected_revision = project.revision
    command.records.reverse()
    project.documents.reverse()
    save(project, command)
    again = reconcile(project, result_for(project), cards)
    same = next(c for c in again if c.id == initial)
    assert same.reply_ids == ["reply-1"]
    assert same.evidence_state == "awaiting_explanation"
    assert same.version == card.version
    next(r for r in command.records if r.kind == "payment").recipient = "contractor"
    save(project, command)
    changed = reconcile(project, result_for(project), again)
    same = next(c for c in changed if c.id == initial)
    assert not same.observation.active
    assert same.evidence_state == "needs_recheck"
    assert same.owner_decision == "stop_unresolved"
    assert same.reply_ids == ["reply-1"]
    assert result.calculation.remaining_commitment_cents == 1000000
    assert result_for(project).calculation.remaining_commitment_cents == 700000


@pytest.mark.parametrize("decision", ["accept_explanation", "stop_unresolved"])
def test_owner_choice_is_not_evidence_or_money(decision):
    project, _, result, _, card = ambiguous()
    before = result.model_dump()
    assess(
        card,
        CardCommand(
            mutation_id=str(uuid4()),
            expected_version=card.version,
            owner_decision=decision,
            note="My decision, still no evidence",
        ),
        project,
        result,
        "saved",
    )
    assert card.evidence_state == "awaiting_explanation"
    assert result_for(project).model_dump() == before
    assert result.incomplete
    assert card.observation.active


def test_positive_evidence_requires_current_specific_checked_sources_and_stales():
    project, command, result, cards, card = ambiguous()

    def positive(target, refs, snapshot="saved"):
        return CardCommand(
            mutation_id=str(uuid4()),
            expected_version=target.version,
            evidence_state="explained_verified",
            note="Checked original",
            snapshot_id=snapshot,
            source_refs=refs,
        )

    with pytest.raises(Problem):
        assess(card, positive(card, card.observation.source_refs), project, result, "saved")
    next(r for r in command.records if r.kind == "payment").recipient = "contractor"
    save(project, command)
    current = result_for(project)
    changed = reconcile(project, current, cards)
    card = next(c for c in changed if c.id == card.id)
    for refs, snapshot in [
        ([], "saved"),
        (["page:foreign:1"], "saved"),
        (card.observation.source_refs, "old"),
    ]:
        with pytest.raises(Problem):
            assess(card, positive(card, refs, snapshot), project, current, "saved")
    assess(card, positive(card, card.observation.source_refs), project, current, "saved")
    assert card.evidence_state == "explained_verified"
    assert card.verified_snapshot_id == "saved"
    next(r for r in command.records if r.kind == "payment").amount = "2000.00"
    save(project, command)
    stale = next(c for c in reconcile(project, result_for(project), changed) if c.id == card.id)
    assert stale.evidence_state == "needs_recheck"
    assert any(e.evidence_state == "explained_verified" for e in stale.events)


def test_insufficient_answer_needs_answer_and_does_not_resolve():
    project, _, result, _, card = ambiguous()
    command = CardCommand(
        mutation_id=str(uuid4()),
        expected_version=card.version,
        evidence_state="answer_insufficient",
        note="No supporting evidence",
    )
    with pytest.raises(Problem):
        assess(card, command, project, result, "saved")
    card.reply_ids = ["reply-1"]
    assess(card, command, project, result, "saved")
    assert card.observation.active and result.incomplete


def test_checked_payment_condition_has_specific_evidence_without_cash_record():
    project = project_from("estimate.pdf", "payment.pdf", "invoice.pdf")
    command = accepted(project)
    condition = next(r for r in command.records if r.kind == "condition")
    condition.answer = "unknown"
    save(project, command)
    cards = reconcile(project, result_for(project), [])
    card = next(c for c in cards if c.observation.code == "REVIEW_CONDITION")
    condition.answer = "accept"
    save(project, command)
    result = result_for(project)
    card = next(c for c in reconcile(project, result, cards) if c.id == card.id)
    assess(
        card,
        CardCommand(
            mutation_id=str(uuid4()),
            expected_version=card.version,
            evidence_state="explained_verified",
            note="Checked the payment condition on the invoice",
            snapshot_id="current",
            source_refs=card.observation.source_refs,
        ),
        project,
        result,
        "current",
    )
    assert card.evidence_state == "explained_verified"
    assert result.conditions[0].source_id in card.verified_source_refs
