"""Real PDF parsing and normalization; OCR integration runs separately in Linux container."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.guest.calculation import result_for, validate_command
from app.guest.extraction import cents, extract_page, inspect, semantic_candidates
from app.guest.models import (
    Document,
    Page,
    Problem,
    Project,
    RecordChoice,
    ReviewCommand,
    SavedReview,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "uploads"


class NoOCR:
    def text(self, image):
        raise AssertionError("A text PDF must not need OCR")


def project_from(*names: str) -> Project:
    now = datetime.now(UTC)
    project = Project(id="test-case", created_at=now, expires_at=now + timedelta(hours=24))
    for name in names:
        data = (FIXTURES / name).read_bytes()
        media, count = inspect(data)
        page = extract_page(data, media, 1, NoOCR())
        project.documents.append(
            Document(
                id=name,
                name=name,
                checksum=name,
                size=len(data),
                media_type=media,
                page_count=count,
                pages=[page],
                candidates=semantic_candidates(name, page),
                status="ready",
            )
        )
    return project


def accepted(project: Project) -> ReviewCommand:
    rows = [
        RecordChoice(
            id=c.id,
            kind=c.kind,
            amount=c.amount,
            date=date.fromisoformat(c.date),
            answer="accept",
            recipient="contractor",
            state=c.state,
        )
        for d in project.documents
        for c in d.candidates
    ]
    return ReviewCommand(
        expected_revision=project.revision,
        records=rows,
        agreement_id=next((r.id for r in rows if r.kind == "agreement"), None),
        request_id=next((r.id for r in rows if r.kind == "payment_request"), None),
        cutoff_date=date(2026, 11, 14),
    )


def save(project: Project, command: ReviewCommand) -> None:
    validate_command(project, command)
    project.review = SavedReview(
        id="review-1",
        basis_revision=project.revision,
        created_at=datetime.now(UTC),
        command=command,
    )


@pytest.mark.parametrize(
    "value, expected", [("$10,000.00", 1000000), ("USD 0.01", 1), ("-123.45", -12345)]
)
def test_integer_cents(value, expected):
    assert cents(value) == expected


@pytest.mark.parametrize(
    "value", ["1.001", "NaN", "1e5", "10,00.00", "1 000", "€20", "90000000000.01", "", "1.20abc"]
)
def test_money_rejects_ambiguous_invalid_and_out_of_range(value):
    with pytest.raises(ValueError):
        cents(value)


@pytest.mark.parametrize("name", ["password.pdf", "too-many-pages.pdf"])
def test_invalid_pdfs(name):
    with pytest.raises(Problem):
        inspect((FIXTURES / name).read_bytes())


@pytest.mark.parametrize(
    "data", [b"", b"not a PDF", b"%PDF-1.7 corrupt", b"x" * (10 * 1024 * 1024 + 1)]
)
def test_invalid_content(data):
    with pytest.raises(Problem):
        inspect(data)


def test_content_drives_real_pipeline_and_source_provenance():
    for name, remainder in [("estimate.pdf", 700000), ("estimate-changed.pdf", 600000)]:
        project = project_from(name, "payment.pdf", "invoice.pdf")
        before = result_for(project)
        assert before.calculation.remaining_commitment_cents is None
        assert before.incomplete
        command = accepted(project)
        save(project, command)
        result = result_for(project)
        assert result.calculation.remaining_commitment_cents == remainder
        assert result.calculation.net_paid_cents == 300000
        assert result.calculation.requested_now_cents == 700000
        assert result.conditions[0].text == "Payment terms: after written approval"
        assert all(
            ref in {s.source_id for s in result.sources}
            for d in result.normalization.included
            for ref in d.evidence_refs
        )
        assert result_for(project).calculation == result.calculation
        assert project.documents[0].candidates[0].original_amount in (
            "USD 10,000.00",
            "USD 9,000.00",
        )


def test_unknown_base_and_invoice_deposit_are_not_money():
    project = project_from("payment.pdf", "balance.pdf")
    command = accepted(project)
    for row in command.records:
        if row.kind == "unknown":
            row.answer = "unknown"
    save(project, command)
    result = result_for(project)
    assert result.calculation.remaining_commitment_cents is None
    assert result.calculation.net_paid_cents == 300000
    assert result.incomplete


def test_review_revision_corrections_and_recipient_are_effective():
    project = project_from("estimate.pdf", "payment.pdf")
    command = accepted(project)
    command.records[0].amount = "12000.00"
    save(project, command)
    assert result_for(project).calculation.remaining_commitment_cents == 900000
    assert project.documents[0].candidates[0].amount == "10000.00"
    command.records[1].recipient = "other"
    assert result_for(project).calculation.remaining_commitment_cents == 1200000
    project.revision += 1
    stale = result_for(project)
    assert stale.calculation.remaining_commitment_cents is None
    assert any(q.code == "STALE_DECISION" for q in stale.questions)
    with pytest.raises(Problem, match="Documents changed"):
        validate_command(project, command)


def test_errors_are_explicit_and_links_not_guessed():
    project = project_from("estimate.pdf", "payment.pdf")
    command = accepted(project)
    command.records[0].amount = "10000.001"
    with pytest.raises(Problem):
        validate_command(project, command)
    command.records[0].amount = "10000"
    command.records[0].date = None
    with pytest.raises(Problem):
        validate_command(project, command)
    command.records.pop()
    with pytest.raises(Problem):
        validate_command(project, command)


def test_unreadable_and_unknown_currency_are_not_zero():
    page = Page(number=1, text="Unclear amount: EUR 100.00", method="tesseract")
    candidate = semantic_candidates("file", page)[0]
    assert candidate.amount is None
    assert candidate.kind == "unknown"
    assert semantic_candidates("file", Page(number=1, text="", method="tesseract")) == []


def test_bank_identity_survives_extraction_and_review():
    project = project_from("estimate.pdf", "payment.pdf", "payment-copy.pdf", "payment-second.pdf")
    save(project, accepted(project))
    result = result_for(project)
    assert result.calculation.net_paid_cents == 600000
    assert result.calculation.remaining_commitment_cents == 400000
    assert len(result.calculation.completed_cash_record_ids) == 2


def test_corrections_have_new_record_revision_and_separate_user_origin():
    project = project_from("estimate.pdf")
    command = accepted(project)
    save(project, command)
    initial = result_for(project)
    project.revision += 1
    command = accepted(project)
    command.records[0].amount = "12000.00"
    save(project, command)
    updated = result_for(project)
    assert initial.history.records[0].id != updated.history.records[0].id
    assert initial.history.records[0].record_id == updated.history.records[0].record_id
    assert updated.history.records[0].origin == "user_statement"
    assert updated.history.records[0].review.extraction_review == "corrected"
    assert project.documents[0].candidates[0].original_amount == "USD 10,000.00"


def test_mixed_currency_is_not_automatically_converted():
    page = Page(number=1, text="Invoice in USD\nAmount due: EUR 100.00", method="pdf_text")
    assert semantic_candidates("file", page)[0].amount is None


def test_truncated_jpeg_is_rejected_before_queueing():
    with pytest.raises(Problem):
        inspect((FIXTURES / "estimate.jpg").read_bytes()[:-200])
