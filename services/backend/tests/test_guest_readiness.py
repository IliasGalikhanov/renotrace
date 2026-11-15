"""Saved question presence and ordinary-document limitations, through the real modules."""

from copy import deepcopy

from test_guest_extraction import accepted, project_from, save
from test_guest_pdf import NOW, example_basis, freeze, read
from test_guest_recheck import checked_invoice

from app.guest.calculation import result_for
from app.guest.casework import reconcile
from app.guest.extraction import invoice_proposals
from app.guest.invoice_models import InvoiceLine, InvoiceReview
from app.guest.pdf_report import ReportBasis, question_presence, render_pdf


def test_processing_completion_save_and_pdf_preserve_historical_observation(monkeypatch):
    ready = project_from("recheck-estimate.pdf", "recheck-payment.pdf", "recheck-original.pdf")
    project = ready.model_copy(deep=True)
    for doc in project.documents:
        doc.status, doc.pages, doc.candidates = "processing", [], []
    cards = reconcile(project, result_for(project), [])
    processing = next(c for c in cards if c.observation.code.startswith("DOCUMENT_NOT_READY"))
    assert processing.observation.active
    project.documents = ready.documents
    project.revision += 1
    command = accepted(project)
    command.invoices = [checked_invoice(project, "recheck-original.pdf", command)]
    save(project, command)
    result = result_for(project)
    cards = reconcile(project, result, cards)
    historical = next(c for c in cards if c.id == processing.id)
    assert not historical.observation.active
    assert historical.evidence_state == "needs_recheck"
    assert historical.owner_decision == "continue_clarifying"
    basis = ReportBasis(
        freeze(
            {
                "project": project.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "discussion": {"cards": [c.model_dump(mode="json") for c in cards], "replies": []},
            },
            "processing-history",
        )
    )
    frozen = deepcopy(basis)

    def forbidden(*args, **kwargs):
        raise AssertionError("Presentation must not rerun a saved calculation or reconciliation")

    monkeypatch.setattr("app.guest.casework.reconcile", forbidden)
    monkeypatch.setattr("app.guest.calculation.result_for", forbidden)
    _, text = read(render_pdf(basis, NOW))
    assert "HISTORICAL - absent from this selected calculation" in text
    assert historical.observation.message in text
    assert "not a current processing or eligibility status" in text
    assert "Previous conclusion requires reassessment" in text
    assert "ACTIVE in this selected calculation" in text  # Request discrepancy remains active.
    assert "$5,000.00" in text and "PRELIMINARY" in text
    assert basis == frozen


def test_old_comparison_new_cards_are_not_all_active_and_missing_presence_is_unknown():
    basis = example_basis()
    card = deepcopy(basis.selected.payload["discussion"]["cards"][0])
    card["observation"].update(active=False, message="Old processing message")
    basis.comparison.payload["result"]["new_questions"] = [card]
    original = deepcopy(basis)
    _, text = read(render_pdf(basis, NOW))
    assert "HISTORICAL - absent from this selected calculation: Old processing message" in text
    assert "New question: Old processing message" not in text
    assert basis == original
    del card["observation"]["active"]
    assert "not recorded" in question_presence(card)


def test_ordinary_invoice_requires_manual_rows_and_preserves_source_evidence():
    project = project_from(
        "showcase-ordinary-invoice.pdf", "recheck-estimate.pdf", "recheck-payment.pdf"
    )
    doc = project.documents[0]
    assert invoice_proposals(doc.id, doc.pages[0]) == []  # Honest recognition boundary.
    command = accepted(project)
    request = next(c for c in doc.candidates if "Amount due:" in c.snippet)
    command.request_id = request.id
    for c in doc.candidates:
        if c.id != request.id and c.kind != "condition":
            row = next(r for r in command.records if r.id == c.id)
            row.kind, row.answer = "unknown", "reject"  # Rows are not separate requests.
    command.invoices = [
        InvoiceReview(
            file_id=doc.id,
            request_id=request.id,
            complete=True,
            lines=[
                InvoiceLine(
                    id=f"manual-{i}",
                    page=1,
                    kind="work",
                    description=name,
                    amount=amount,
                    review="checked",
                )
                for i, (name, amount) in enumerate(
                    [
                        ("Wall painting", "3800.00"),
                        ("Floor protection", "400.00"),
                        ("Skirting board installation", "2000.00"),
                    ]
                )
            ],
        )
    ]
    save(project, command)
    result = result_for(project)
    composition = result.invoice_compositions[0]
    assert composition.accounted_cents == 620000
    assert composition.unexplained_cents == 0
    assert result.calculation.net_paid_cents == 120000
    assert result.calculation.remaining_commitment_cents == 500000
    assert all(row.source_ref == f"page:{doc.id}:1" for row in composition.lines)
    assert all(row.value.proposal_id is None for row in composition.lines)
