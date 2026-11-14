"""PDF content, frozen-version boundaries, hostile text and pagination, using real evidence."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5

import pytest
from pypdf import PdfReader
from test_guest_extraction import FIXTURES, save
from test_guest_recheck import evidence, pair

from app.guest.calculation import result_for
from app.guest.casework_models import Snapshot, SnapshotSummary
from app.guest.comparison import compare
from app.guest.models import Problem
from app.guest.pdf_report import ReportBasis, money, render_pdf
from app.guest.recheck_models import Comparison, Match, QuestionLink

NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


def freeze(payload, label):
    payload = deepcopy(payload)
    identifier = str(uuid5(NAMESPACE_URL, "renotrace-fictional-" + label))
    payload = json.loads(json.dumps(payload).replace("review-1", identifier))
    for doc in payload["project"]["documents"]:
        doc["checksum"] = hashlib.sha256((FIXTURES / doc["name"]).read_bytes()).hexdigest()
    return Snapshot(
        summary=SnapshotSummary(
            id=identifier,
            created_at=NOW,
            financial_revision=payload["project"]["revision"],
            contract_version="guest-review/3",
            remaining_cents=payload["result"]["calculation"]["remaining_commitment_cents"],
            question_count=len(payload["result"]["questions"]),
        ),
        payload=payload,
    )


def reply(card, text, version=1):
    return {
        "reply_id": "fictional-reply",
        "question_ids": [card["id"]],
        "source_id": f"reply:fictional-reply:v{version}",
        "version": version,
        "text": text,
        "file_ids": [],
        "added_by": "guest:fictional-owner",
        "added_at": NOW.isoformat(),
        "origin": "owner_reported_contractor",
    }


def example_basis(kind="comparison", old="recheck-original.pdf", new="recheck-corrected.pdf"):
    if kind == "snapshot":
        _, _, payload = evidence()
        return ReportBasis(freeze(payload, "initial"))
    _, command, before, after, package = pair(old, new)
    package.matches = [
        Match(old_id=command.invoices[0].lines[0].id, new_id=command.invoices[1].lines[0].id)
    ]
    package.matches += [Match(old_id=line.id) for line in command.invoices[0].lines[1:]]
    package.matches += [Match(new_id=line.id) for line in command.invoices[1].lines[1:]]
    if new == "recheck-corrected.pdf":
        package.question_links = [
            QuestionLink(
                question_id=before["discussion"]["cards"][0]["id"],
                new_line_id=command.invoices[1].lines[1].id,
                note="Checked original cash evidence",
            )
        ]
    pinned = reply(
        after["discussion"]["cards"][0],
        "Partial answer: the earlier transfer is reflected; scope still needs checking.",
    )
    # A later version exists in the new snapshot, but the package explicitly pins v1.
    after["discussion"]["replies"] = [
        {
            "id": pinned["reply_id"],
            "question_ids": pinned["question_ids"],
            "versions": [
                pinned,
                reply(after["discussion"]["cards"][0], "LATER-UNPINNED-ANSWER", 2),
            ],
        }
    ]
    after["discussion"]["cards"][0]["owner_decision"] = "stop_unresolved"
    previous, selected = freeze(before, "previous"), freeze(after, "new")
    comparison = Comparison(
        id=str(uuid5(NAMESPACE_URL, "fictional-comparison")),
        base_snapshot_id=previous.summary.id,
        new_snapshot_id=selected.summary.id,
        created_at=NOW,
        basis_fingerprint="fictional-fingerprint",
        payload={
            "package": package.model_dump(mode="json"),
            "documents": [],
            "reply_versions": [pinned],
            "result": compare(previous.payload, selected.payload, package),
        },
    )
    if kind == "long":
        pinned["text"] = (
            "Long owner-reported partial answer <b>not markup</b>: uncertain scope. " * 70
            + "END-OF-LONG-ANSWER"
        )
        rows = selected.payload["result"]["invoice_compositions"][-1]["lines"]
        prototype = deepcopy(rows[0])
        for i in range(85):
            row = deepcopy(prototype)
            row["value"]["id"] = f"fictional-layout-row-{i}"
            row["value"]["description"] = (
                "Fictional layout-only example " + str(i) + " - " + "long description " * 10
            )
            row["value"]["review"] = "unknown"
            row["signed_cents"] = row["amount_cents"] = None
            rows.append(row)
        selected.payload["result"]["invoice_compositions"][-1]["complete"] = False
        selected.payload["result"]["invoice_compositions"][-1]["issues"] = [
            "Fictional unverified layout rows; values unknown."
        ]
        selected.payload["project"]["documents"][0]["name"] = (
            "FICTIONAL " + "long filename " * 12 + ".pdf"
        )
    return ReportBasis(selected, previous, comparison)


def read(content):
    reader = PdfReader(BytesIO(content))
    return reader, " ".join(" ".join(p.extract_text() for p in reader.pages).split())


def test_initial_pdf_uses_real_saved_values_and_checksums_without_recalculation(monkeypatch):
    basis = example_basis("snapshot")
    unchanged = deepcopy(basis.selected)

    def forbidden(*args, **kwargs):
        raise AssertionError("Export must never calculate")

    for target in (
        "app.guest.calculation.result_for",
        "app.guest.calculation.normalize",
        "app.guest.calculation.calculate",
        "app.guest.comparison.compare",
    ):
        monkeypatch.setattr(target, forbidden)
    reader, content = read(render_pdf(basis, NOW))
    for required in (
        "FICTIONAL EXAMPLE",
        "$6,200.00",
        "$1,200.00",
        "$5,000.00",
        "guest-review/3",
        "Source register",
        "PRELIMINARY",
        "p. 1",
        "after written approval",
        "originals are not attached",
    ):
        assert required in content
    for doc in basis.selected.payload["project"]["documents"]:
        assert doc["checksum"] in content
    assert basis.selected == unchanged
    assert not reader.attachments
    assert not reader.trailer["/Root"].get("/OpenAction")
    assert all(not p.get("/Annots") for p in reader.pages)


def test_comparison_pins_reply_version_and_preserves_two_financial_bases():
    basis = example_basis()
    _, content = read(render_pdf(basis, NOW))
    for required in (
        "$6,200.00",
        "$5,000.00",
        "-$1,200.00",
        "$1,200.00",
        "$0.00",
        "No additional payment is created",
        "stop unresolved",
        "Partial answer",
        "version 1",
        "Previous calculation",
        "invoice-comparison/1",
    ):
        assert required in content
    assert "LATER-UNPINNED-ANSWER" not in content
    assert "source unavailable" not in content
    assert basis.previous.summary.id in content and basis.selected.summary.id in content


def test_new_work_removed_discount_are_visible_even_when_request_falls():
    _, content = read(
        render_pdf(example_basis(old="recheck-discount.pdf", new="recheck-new-work.pdf"), NOW)
    )
    for required in ("removed", "added", "discount", "$4,500.00", "New work/charge", "not savings"):
        assert required in content


def test_reply_versions_are_labelled_by_their_historical_snapshot_or_pinned_package():
    basis = example_basis()
    card = basis.previous.payload["discussion"]["cards"][0]
    old_reply = reply(card, "OLD-ANSWER-VERSION-ONE", 1)
    basis.previous.payload["discussion"]["replies"] = [
        {
            "id": old_reply["reply_id"],
            "question_ids": old_reply["question_ids"],
            "versions": [old_reply],
        }
    ]
    basis.comparison.payload["reply_versions"] = [reply(card, "NEW-PINNED-VERSION-TWO", 2)]
    _, content = read(render_pdf(basis, NOW))
    split = content.index("Previous calculation - historical basis")
    assert content.index("NEW-PINNED-VERSION-TWO") < split < content.index("OLD-ANSWER-VERSION-ONE")
    assert "version 2" in content[:split] and "version 1" in content[split:]
    assert "LATER-UNPINNED-ANSWER" not in content


def test_snapshot_keeps_partial_reply_and_separate_stop_decision():
    basis = example_basis("snapshot")
    card = basis.selected.payload["discussion"]["cards"][0]
    card["evidence_state"] = "answer_insufficient"
    card["owner_decision"] = "stop_unresolved"
    card["events"].append(
        {"kind": "assessment", "detail": "I stop, but the evidence remains incomplete."}
    )
    answer = reply(card, "Only a partial explanation is available.")
    basis.selected.payload["discussion"]["replies"] = [
        {
            "id": answer["reply_id"],
            "question_ids": answer["question_ids"],
            "versions": [answer],
        }
    ]
    _, content = read(render_pdf(basis, NOW))
    for expected in (
        "answer insufficient",
        "stop unresolved",
        "Only a partial explanation",
        "the evidence remains incomplete",
        "PRELIMINARY",
    ):
        assert expected in content


def test_unknown_and_negative_exact_cents_come_from_real_ledger():
    project, command, payload = evidence()
    cash = next(r for r in command.records if r.kind == "payment")
    cash.amount = "7000.01"
    save(project, command)
    payload["project"] = project.model_dump(mode="json")
    payload["result"] = result_for(project).model_dump(mode="json")
    _, content = read(render_pdf(ReportBasis(freeze(payload, "overpaid")), NOW))
    assert "-$800.01" in content and "$7,000.01" in content
    command.agreement_id = None
    save(project, command)
    payload["project"] = project.model_dump(mode="json")
    payload["result"] = result_for(project).model_dump(mode="json")
    _, content = read(render_pdf(ReportBasis(freeze(payload, "unknown")), NOW))
    assert "Contract basis: Unknown" in content
    assert "Unknown" in content and "PRELIMINARY" in content
    assert money(None) == "Unknown" and money(-1) == "-$0.01"
    with pytest.raises(Problem):
        money(1.5)


def test_plain_text_no_external_actions_credentials_or_metadata_leaks():
    basis = example_basis()
    hostile = '<b>literal-tag</b><img src="https://secret.example/private?token=sentinel-url"/> '
    hostile += (
        "Authorization: Bearer sentinel-bearer PGPASSWORD=sentinel-password Cookie=sentinel-cookie "
    )
    hostile += (
        "postgresql://user:sentinel-db@example/db Русский текст 中文 & "
        "<script>literal-script</script>"
    )
    basis.comparison.payload["reply_versions"][0]["text"] = hostile
    reader, content = read(render_pdf(basis, NOW))
    assert "<b>literal-tag</b>" in content and "Русский текст" in content
    assert "literal-script" in content
    assert "[U+4E2D]" in content and "[U+6587]" in content
    for secret in (
        "sentinel-url",
        "sentinel-bearer",
        "sentinel-password",
        "sentinel-cookie",
        "sentinel-db",
    ):
        assert secret not in content
        assert secret not in str(reader.metadata)
    assert all(not p.get("/Annots") for p in reader.pages)


def test_long_rows_repeat_table_headers_and_keep_end_of_long_answer():
    reader, content = read(render_pdf(example_basis("long"), NOW))
    assert len(reader.pages) > 10
    assert "END-OF-LONG-ANSWER" in content
    assert "fictional-layout-row-84" in content
    assert content.count("Signed USD / review") >= 3
    for i, page in enumerate(reader.pages, 1):
        assert f"Page {i}" in page.extract_text()


def test_export_size_and_page_limits_fail_without_partial_pdf(monkeypatch):
    monkeypatch.setattr("app.guest.pdf_report.MAX_PDF_BYTES", 100)
    with pytest.raises(Problem, match="16 MiB"):
        render_pdf(example_basis("snapshot"), NOW)
    monkeypatch.setattr("app.guest.pdf_report.MAX_PAGES", 1)
    with pytest.raises(Problem, match="300-page"):
        render_pdf(example_basis("snapshot"), NOW)


def test_older_snapshot_without_composition_does_not_reconstruct_it():
    basis = example_basis("snapshot")
    basis.selected.payload["result"].pop("invoice_compositions")
    basis.selected.payload["result"]["conditions"] = []
    basis.selected.summary.contract_version = "guest-review/2"
    _, content = read(render_pdf(basis, NOW))
    assert "guest-review/2" in content
    assert "Unknown - this snapshot has no checked invoice composition" in content
    assert "Unknown - no checked payment conditions" in content
