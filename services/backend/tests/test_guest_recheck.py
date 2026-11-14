"""Real PDF extraction and real normalization/ledger, plus pure comparison invariants."""

from copy import deepcopy

import pytest
from test_guest_extraction import accepted, project_from, save

from app.guest.calculation import result_for, validate_command
from app.guest.casework import reconcile
from app.guest.comparison import compare
from app.guest.extraction import invoice_proposals
from app.guest.invoice_models import InvoiceLine, InvoiceReview, RequestVersion
from app.guest.models import Problem
from app.guest.recheck_models import Match, Package, QuestionLink, ReplyRef


def checked_invoice(project, file_id, command):
    doc = next(d for d in project.documents if d.id == file_id)
    doc.invoice_proposals = [p for page in doc.pages for p in invoice_proposals(doc.id, page)]
    request = next(c.id for c in doc.candidates if c.kind == "payment_request")
    payment = next((r.id for r in command.records if r.kind == "payment"), None)
    return InvoiceReview(
        file_id=doc.id,
        request_id=request,
        complete=True,
        lines=[
            InvoiceLine(
                id=p.id,
                proposal_id=p.id,
                page=p.page,
                kind=p.kind,
                description=p.description,
                amount=p.amount,
                quantity=p.quantity,
                unit_price=p.unit_price,
                review="checked",
                cash_record_id=payment if p.kind == "reflected_payment" else None,
            )
            for p in doc.invoice_proposals
        ],
    )


def evidence(name="recheck-original.pdf", extra=()):
    p = project_from("recheck-estimate.pdf", "recheck-payment.pdf", name, *extra)
    cmd = accepted(p)
    invoice = checked_invoice(p, name, cmd)
    cmd.request_id = invoice.request_id
    cmd.invoices = [invoice]
    save(p, cmd)
    result = result_for(p)
    cards = reconcile(p, result, [])
    return (
        p,
        cmd,
        {
            "project": p.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "discussion": {"cards": [c.model_dump(mode="json") for c in cards], "replies": []},
        },
    )


def pair(old="recheck-original.pdf", new="recheck-corrected.pdf"):
    _, old_command, before = evidence(old)
    project, command, _ = evidence(old, (new,))
    invoice = checked_invoice(project, new, command)
    command.request_id = invoice.request_id
    command.invoices.append(invoice)
    command.request_versions = [
        RequestVersion(old_request_id=old_command.request_id, new_request_id=command.request_id)
    ]
    save(project, command)
    result = result_for(project)
    from app.guest.casework_models import QuestionCard

    cards = reconcile(
        project, result, [QuestionCard.model_validate(c) for c in before["discussion"]["cards"]]
    )
    after = {
        "project": project.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "discussion": {"cards": [c.model_dump(mode="json") for c in cards], "replies": []},
    }
    pack = Package(
        file_ids=[new],
        old_request_id=old_command.request_id,
        new_request_id=command.request_id,
        relationship="corrected",
    )
    return project, command, before, after, pack


def test_6200_to_5000_is_reflection_not_second_payment():
    p, cmd, old, new, pack = pair()
    old_line = cmd.invoices[0].lines[0]
    work, credit = cmd.invoices[1].lines
    pack.matches = [Match(old_id=old_line.id, new_id=work.id), Match(new_id=credit.id)]
    pack.question_links = [
        QuestionLink(
            question_id=old["discussion"]["cards"][0]["id"],
            new_line_id=credit.id,
            note="Explicit original payment credit",
        )
    ]
    frozen = deepcopy(old)
    result = compare(old, new, pack)
    assert result["metrics"]["requested_now_cents"] == {
        "before": 620000,
        "after": 500000,
        "delta": -120000,
    }
    for key in ("commitment_total_cents", "net_paid_cents", "remaining_commitment_cents"):
        assert result["metrics"][key]["delta"] == 0
    assert new["result"]["calculation"]["net_paid_cents"] == 120000
    assert new["result"]["calculation"]["remaining_commitment_cents"] == 500000
    assert len(new["result"]["normalization"]["ledger_input"]["cash_events"]) == 1
    assert result["question_findings"][0]["payment_reflection"]
    reflection = result["question_findings"][0]["payment_reflection"][0]
    source_ids = {source["source_id"] for source in new["result"]["sources"]}
    assert reflection["source_ref"] in source_ids
    assert reflection["review_source_ref"] in source_ids
    assert reflection["cash_evidence_refs"]
    assert set(reflection["cash_evidence_refs"]) <= source_ids
    assert result["question_findings"][0]["requires_recheck"]
    assert result["preliminary"]  # Disappearance never auto-closes evidence assessment.
    assert old == frozen
    # Semantic extraction did not turn invoice lines into financial records.
    assert len(next(d for d in p.documents if d.id == "recheck-corrected.pdf").candidates) == 2
    # Order of reviewed records/lines and mapping decisions does not affect totals.
    cmd.records.reverse()
    cmd.invoices[1].lines.reverse()
    save(p, cmd)
    assert result_for(p).calculation.model_dump(mode="json") == new["result"]["calculation"]
    assert result_for(p).invoice_compositions[1].accounted_cents == 500000


def test_lower_total_with_new_work_and_removed_discount():
    _, cmd, old, new, pack = pair("recheck-discount.pdf", "recheck-new-work.pdf")
    a, b = cmd.invoices
    pack.matches = [
        Match(old_id=a.lines[0].id, new_id=b.lines[0].id),
        Match(old_id=a.lines[1].id),
        Match(new_id=b.lines[1].id),
        Match(new_id=b.lines[2].id),
    ]
    out = compare(old, new, pack)
    assert out["metrics"]["requested_now_cents"]["delta"] == -170000
    assert {c["change"] for c in out["changes"]} >= {"added", "removed"}
    assert any("contractual approval" in issue for issue in out["issues"])
    assert out["metrics"]["commitment_total_cents"]["delta"] == 0
    assert out["conditions_before"] != out["conditions_after"]


def test_equal_total_different_description_is_visible():
    _, cmd, old, new, pack = pair(new="recheck-equal.pdf")
    pack.matches = [Match(old_id=cmd.invoices[0].lines[0].id, new_id=cmd.invoices[1].lines[0].id)]
    out = compare(old, new, pack)
    assert out["metrics"]["requested_now_cents"]["delta"] == 0
    assert out["changes"][0]["fields"] == ["description"]
    assert not out["explanation_only"]


def test_explanation_only_and_partial_reply_never_certify_truth():
    _, cmd, old = evidence()
    pack = Package(
        file_ids=["recheck-original.pdf"],
        old_request_id=cmd.request_id,
        new_request_id=cmd.request_id,
        relationship="same",
        replies=[ReplyRef(reply_id="reply-1", version=1)],
    )
    out = compare(old, deepcopy(old), pack)
    assert out["explanation_only"]
    assert all(v["delta"] == 0 for v in out["metrics"].values())
    assert out["preliminary"]
    assert not out["question_findings"][0]["payment_reflection"]
    assert any("not independently verified" in issue for issue in out["issues"])


def test_unknown_lineage_unmatched_and_unexplained_difference_remain_open():
    _, _, old, new, pack = pair(new="recheck-incomplete.pdf")
    pack.relationship = "unknown"
    out = compare(old, new, pack)
    assert out["new_composition"]["unexplained_cents"] == -100000
    assert out["unmatched_old"] and out["unmatched_new"] and out["preliminary"]
    assert out["suggestions"]  # Description, not matching amount; still requires confirmation.
    assert not out["changes"]


def test_equal_amount_alone_does_not_suggest_match():
    _, _, old, new, pack = pair(new="recheck-equal.pdf")
    out = compare(old, new, pack)
    assert not out["suggestions"]
    assert out["unmatched_new"]


@pytest.mark.parametrize(
    "mode",
    [
        "foreign_page",
        "fraction",
        "range",
        "duplicate_id",
        "bad_proposal",
        "cash_kind",
        "cycle",
        "branch",
        "wrong_contractor",
        "selected_old",
    ],
)
def test_invalid_sources_values_and_request_versions(mode):
    p, cmd, _, _, _ = pair()
    row = cmd.invoices[1].lines[0]
    if mode == "foreign_page":
        row.page = 19
    if mode == "fraction":
        row.amount = "1.001"
    if mode == "range":
        row.amount = "90000000000.01"
    if mode == "duplicate_id":
        cmd.invoices[1].lines.append(row.model_copy())
    if mode == "bad_proposal":
        row.proposal_id = "another-case-line"
    if mode == "cash_kind":
        row.cash_record_id = cmd.agreement_id
    if mode == "cycle":
        cmd.request_versions.append(
            RequestVersion(old_request_id=cmd.request_id, new_request_id=cmd.invoices[0].request_id)
        )
    if mode == "branch":
        cmd.request_versions.append(cmd.request_versions[0].model_copy())
    if mode == "wrong_contractor":
        next(r for r in cmd.records if r.id == cmd.request_id).recipient = "other"
    if mode == "selected_old":
        cmd.request_id = cmd.invoices[0].request_id
    with pytest.raises(Problem):
        validate_command(p, cmd)


def test_unfinished_payment_and_manual_missing_rows():
    p, cmd, _, _, _ = pair()
    next(r for r in cmd.records if r.kind == "payment").state = "pending"
    save(p, cmd)
    composition = result_for(p).invoice_compositions[1]
    assert not composition.lines[1].cash_event_id
    assert not composition.complete
    p, cmd, _ = evidence("recheck-unlabelled.pdf")
    assert not cmd.invoices[0].lines
    doc = p.documents[-1]
    cmd.invoices[0].lines = [
        InvoiceLine(
            id="manual-1",
            page=1,
            kind="work",
            description="Surface preparation",
            amount="6200.00",
            review="checked",
        )
    ]
    save(p, cmd)
    row = result_for(p).invoice_compositions[0].lines[0]
    assert row.origin == "manual_entry" and row.original_text is None
    assert row.source_ref == f"page:{doc.id}:1"


def test_over_reflection_and_conflicting_correspondence_rejected():
    p, cmd, old, new, pack = pair()
    cmd.invoices[1].lines[1].amount = "1200.01"
    save(p, cmd)
    with pytest.raises(Problem):
        result_for(p)
    row = cmd.invoices[0].lines[0].id
    pack.matches = [Match(old_id=row), Match(old_id=row)]
    with pytest.raises(Problem):
        compare(old, new, pack)


def test_missing_historical_composition_is_not_backfilled():
    _, _, old, new, pack = pair()
    del old["result"]["invoice_compositions"]
    out = compare(old, new, pack)
    assert out["old_composition"] is None and out["preliminary"]
    assert any("reconstructed" in issue for issue in out["issues"])


def test_deliberately_excluded_proposal_is_not_an_unmatched_actual_position():
    _, command, original = evidence()
    updated = deepcopy(original)
    ignored = deepcopy(updated["result"]["invoice_compositions"][0]["lines"][0])
    ignored["value"].update(id="ignored-proposal", review="excluded")
    updated["result"]["invoice_compositions"][0]["lines"].append(ignored)
    package = Package(
        file_ids=["recheck-original.pdf"],
        old_request_id=command.request_id,
        new_request_id=command.request_id,
        relationship="same",
    )
    result = compare(original, updated, package)
    assert not result["unmatched_new"]
    assert len(result["changes"]) == 1
