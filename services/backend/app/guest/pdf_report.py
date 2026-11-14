"""A presentation of immutable evidence. No calculator, storage URL or network access."""

import hashlib
import re
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from importlib.resources import files
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from .casework_models import Snapshot
from .models import Problem
from .recheck_models import Comparison

EXPORT_VERSION = "reconciliation-pdf/1"
MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_PAGES = 300


class PageLimitExceeded(ValueError):
    """ReportLab can annotate this single-argument exception before it escapes."""


FONT = "RenoTraceDejaVu"
pdfmetrics.registerFont(TTFont(FONT, str(files(__package__).joinpath("fonts/DejaVuSans.ttf"))))
INK = colors.HexColor("#163c45")
MUTED = colors.HexColor("#48646a")
TEAL = colors.HexColor("#12695d")
PALE = colors.HexColor("#edf4f1")
WARN = colors.HexColor("#fff0cd")
METRICS = {
    "requested_now_cents": "Requested in selected invoice",
    "commitment_total_cents": "C - recorded commitments",
    "net_paid_cents": "P - net payments",
    "remaining_commitment_cents": "R - remaining under recorded terms",
}


def money(value: Any) -> str:
    if value is None:
        return "Unknown"
    if type(value) is not int:
        raise Problem(422, "Saved monetary value is not integer cents")
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value) // 100:,}.{abs(value) % 100:02d}"


def text(value: Any) -> str:
    """Plain user text only. Never embed URLs, credentials, HTML or external resources."""
    value = "Unknown" if value is None else str(value)
    value = re.sub(
        r"(?i)\b(?:https?|file|postgres(?:ql)?|s3)://[^\s<>]+", "[address omitted]", value
    )
    value = re.sub(r"(?i)\bbearer\s+[^\s<]+", "[credential omitted]", value)
    value = re.sub(
        r"(?i)\b(cookie|authorization|pgpassword|password|service_role|api[_-]?key|"
        r"access[_-]?token|download[_-]?ticket)\s*[:=]\s*[^\s<]+",
        "[credential omitted]",
        value,
    )
    value = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[credential omitted]", value
    )
    return "".join(c for c in value if c in "\n\t" or ord(c) >= 32)


def date_label(value: Any) -> str:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return dt.astimezone(UTC).strftime("%d %b %Y, %H:%M:%S UTC")
    except (ValueError, TypeError):
        return "Unknown date"


@dataclass(frozen=True)
class ReportBasis:
    selected: Snapshot
    previous: Snapshot | None = None
    comparison: Comparison | None = None

    @property
    def report_id(self) -> str:
        return "RT-" + (self.comparison.id if self.comparison else self.selected.summary.id)

    @property
    def snapshots(self) -> list[Snapshot]:
        return ([self.previous] if self.previous else []) + [self.selected]


class Sources:
    def __init__(self, basis: ReportBasis) -> None:
        self.entries: list[dict[str, Any]] = []
        self.documents: dict[tuple[str, str], int] = {}
        self.refs: dict[tuple[str, str], str] = {}
        for snapshot in basis.snapshots:
            for doc in snapshot.payload["project"]["documents"]:
                key = (doc["id"], doc["checksum"])
                if key not in self.documents:
                    self.entries.append({"document": doc, "snapshots": []})
                    self.documents[key] = len(self.entries)
                number = self.documents[key]
                self.entries[number - 1]["snapshots"].append(snapshot.summary.id)
            for source in snapshot.payload["result"].get("sources", []):
                if source.get("file_id"):
                    citation = self.file(snapshot, source["file_id"], source.get("page"))
                else:
                    self.entries.append({"review": snapshot.summary})
                    citation = f"[S{len(self.entries)}]"
                self.refs[(snapshot.summary.id, source["source_id"])] = citation

    def file(self, snapshot: Snapshot, file_id: str, page: Any = None) -> str:
        doc = next(
            (d for d in snapshot.payload["project"]["documents"] if d["id"] == file_id), None
        )
        if doc is None:
            return "[source unavailable in this saved result]"
        number = self.documents[(doc["id"], doc["checksum"])]
        return f"[S{number}" + (f", p. {page}" if page else "") + "]"

    def citations(self, snapshot: Snapshot, refs: list[str]) -> str:
        return (
            " ".join(
                dict.fromkeys(
                    self.refs.get(
                        (snapshot.summary.id, ref), "[source unavailable in this saved result]"
                    )
                    for ref in refs
                )
            )
            or "Source not recorded"
        )

    def excerpt(self, snapshot: Snapshot, refs: list[str]) -> str:
        sources = {s["source_id"]: s for s in snapshot.payload["result"].get("sources", [])}
        excerpts = []
        for ref in refs:
            source = sources.get(ref)
            if source and source.get("file_id") and source.get("text"):
                excerpts.append(text(source["text"])[:350].strip())
        return " / ".join(dict.fromkeys(excerpts)) or "No document excerpt recorded."


class Report:
    def __init__(self, basis: ReportBasis, generated_at: datetime) -> None:
        self.basis = basis
        self.generated_at = generated_at
        self.sources = Sources(basis)
        self.story: list[Any] = []
        self.styles = {
            "body": ParagraphStyle(
                "body",
                fontName=FONT,
                fontSize=9,
                leading=13,
                textColor=INK,
                spaceAfter=5,
                splitLongWords=True,
                alignment=TA_LEFT,
            ),
            "small": ParagraphStyle(
                "small",
                fontName=FONT,
                fontSize=7.5,
                leading=10.5,
                textColor=MUTED,
                spaceAfter=4,
                splitLongWords=True,
            ),
            "metric": ParagraphStyle(
                "metric",
                fontName=FONT,
                fontSize=10.5,
                leading=15,
                textColor=INK,
                spaceAfter=3,
                splitLongWords=True,
            ),
            "title": ParagraphStyle(
                "title", fontName=FONT, fontSize=24, leading=30, textColor=INK, spaceAfter=12
            ),
            "heading": ParagraphStyle(
                "heading",
                fontName=FONT,
                fontSize=14,
                leading=19,
                textColor=TEAL,
                spaceBefore=15,
                spaceAfter=7,
                keepWithNext=True,
            ),
            "sub": ParagraphStyle(
                "sub",
                fontName=FONT,
                fontSize=10,
                leading=14,
                textColor=TEAL,
                spaceBefore=8,
                spaceAfter=5,
                keepWithNext=True,
            ),
            "warning": ParagraphStyle(
                "warning",
                fontName=FONT,
                fontSize=10,
                leading=14,
                textColor=INK,
                backColor=WARN,
                borderPadding=9,
                spaceBefore=10,
                spaceAfter=14,
            ),
        }

    def paragraph(self, value: Any, style: str = "body") -> Any:
        supported = pdfmetrics.getFont(FONT).face.charWidths
        plain = "".join(
            c if c in "\n\t" or ord(c) in supported else f"[U+{ord(c):04X}]" for c in text(value)
        )
        return Paragraph(escape(plain).replace("\n", "<br/>"), self.styles[style])

    def add(self, value: Any, style: str = "body") -> None:
        self.story.append(self.paragraph(value, style))

    def table(
        self,
        headers: list[str],
        rows: list[list[Any]],
        widths: list[float],
        *,
        metric: bool = False,
    ) -> None:
        if not rows:
            self.add("None recorded.")
            return
        cells = [
            [self.paragraph(c, "small" if i == 0 or not metric else "metric") for c in row]
            for i, row in enumerate([headers, *rows])
        ]
        table = LongTable(cells, colWidths=widths, repeatRows=1, splitInRow=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd9d3")),
                ]
            )
        )
        self.story.extend([KeepTogether([table]) if metric else table, Spacer(1, 8)])

    def warning(self, snapshot: Snapshot) -> None:
        result = snapshot.payload["result"]
        cards = snapshot.payload.get("discussion", {}).get("cards", [])
        unresolved = [c for c in cards if c.get("evidence_state") != "explained_verified"]
        comparison = self.basis.comparison if snapshot is self.basis.selected else None
        preliminary = bool(
            result.get("incomplete")
            or unresolved
            or (comparison and comparison.payload["result"].get("preliminary"))
        )
        self.add(
            "PRELIMINARY - unresolved evidence or unknown values remain."
            if preliminary
            else "RECORDED RESULT - absence of questions is not a guarantee of correctness.",
            "warning",
        )
        if result.get("incomplete_metrics"):
            self.add(
                "Preliminary indicators: "
                + ", ".join(
                    METRICS.get(k, k.replace("_", " ")) for k in result["incomplete_metrics"]
                )
            )
        questions = result.get("questions", [])
        for q in questions[:4]:
            self.add("Open question: " + q["message"])
        if len(questions) > 4:
            self.add(f"{len(questions) - 4} additional calculation questions appear below.")
        if unresolved:
            self.add(
                f"{len(unresolved)} discussion question(s) still lack verified evidence. "
                "Accepting an explanation or stopping clarification does not resolve them."
            )

    def metric_table(self, snapshot: Snapshot) -> None:
        calculation = snapshot.payload["result"]["calculation"]
        self.table(
            ["Indicator (USD)", "Saved value"],
            [[label, money(calculation.get(key))] for key, label in METRICS.items()],
            [345, 160],
            metric=True,
        )
        self.add(
            "R is the remainder under recorded terms, not an instruction or a safe amount "
            "to pay. Invoice reductions are not automatically savings. Unknown is not zero.",
            "small",
        )

    def conditions(self, snapshot: Snapshot) -> None:
        self.add("Documented payment conditions", "sub")
        conditions = snapshot.payload["result"].get("conditions", [])
        if not conditions:
            self.add("Unknown - no checked payment conditions were recorded.")
        for c in conditions:
            self.add(self.sources.citations(snapshot, [c["source_id"]]) + " " + c["text"])

    def financial_basis(self, snapshot: Snapshot) -> None:
        result = snapshot.payload["result"]
        ledger = result["normalization"]["ledger_input"]
        self.add("Where the amounts come from", "heading")
        self.add(
            "Values below are copied from the saved normalized input and result. "
            "No financial calculation was rerun for this PDF."
        )
        rows = []
        groups = [
            ("Contract basis", [ledger["agreement"]] if ledger.get("agreement") else []),
            ("Contract adjustment", ledger.get("adjustments", [])),
            ("Cash event", ledger.get("cash_events", [])),
        ]
        completed = set(result["calculation"].get("completed_cash_record_ids", []))
        for kind, records in groups:
            for r in records:
                state = "Counted" if kind != "Cash event" or r["id"] in completed else "Not counted"
                refs = r.get("evidence_refs", [])
                rows.append(
                    [
                        kind + "\n" + state + "\n" + r["id"],
                        money(r.get("amount_cents")),
                        self.sources.citations(snapshot, refs)
                        + "\n"
                        + self.sources.excerpt(snapshot, refs),
                    ]
                )
        self.table(["Saved record / treatment", "USD", "Evidence excerpt"], rows, [145, 80, 280])
        if not ledger.get("agreement"):
            self.add("Contract basis: Unknown. No determined base was recorded.", "warning")
        project = snapshot.payload["project"]
        request_id = (project.get("review") or {}).get("command", {}).get("request_id")
        candidate = next(
            (c for d in project["documents"] for c in d["candidates"] if c["id"] == request_id),
            None,
        )
        self.add("Selected invoice request", "sub")
        self.add("Requested: " + money(result["calculation"].get("requested_now_cents")))
        if candidate:
            self.add(
                self.sources.file(snapshot, candidate["file_id"], candidate["page"])
                + " Original extract: "
                + candidate["snippet"]
            )
            self.add(
                "The selected amount reflects the owner's saved review; original text "
                "is evidence, not a second payment.",
                "small",
            )
        else:
            self.add("No selected invoice source was recorded. Requested amount may be Unknown.")
        self.add(
            "R uses the saved C and P above. Refunds adjust P, not contract cost. "
            "Payments mentioned inside invoices do not create additional cash events.",
            "small",
        )

    def composition(self, snapshot: Snapshot) -> None:
        self.add("Checked invoice composition", "heading")
        compositions = snapshot.payload["result"].get("invoice_compositions", [])
        if not compositions:
            self.add(
                "Unknown - this snapshot has no checked invoice composition. "
                "Historical detail is not reconstructed during export.",
                "warning",
            )
        for invoice in compositions:
            self.add(
                self.sources.file(snapshot, invoice["file_id"])
                + " Invoice "
                + invoice["request_id"],
                "sub",
            )
            self.add(
                "Checked composition: "
                + money(invoice.get("accounted_cents"))
                + " | Requested: "
                + money(invoice.get("requested_cents"))
                + " | Unexplained difference: "
                + money(invoice.get("unexplained_cents"))
            )
            if not invoice.get("complete"):
                self.add(
                    "Incomplete composition. " + " ".join(invoice.get("issues", [])), "warning"
                )
            rows = []
            for line in invoice.get("lines", []):
                value = line["value"]
                description = value["description"] + "\n" + value["kind"].replace("_", " ")
                if value.get("quantity") is not None:
                    description += "\nQuantity: " + str(value["quantity"])
                if value.get("unit_price") is not None:
                    description += "\nStated unit price (USD): " + str(value["unit_price"])
                refs = [
                    line["source_ref"],
                    line["review_source_ref"],
                    *line.get("cash_evidence_refs", []),
                ]
                provenance = (
                    self.sources.citations(snapshot, refs) + "\n" + line["origin"].replace("_", " ")
                )
                provenance += "\nOriginal: " + (
                    line.get("original_text") or "No extracted row; manual entry."
                )
                if line.get("cash_event_id"):
                    provenance += (
                        "\nExisting cash event: " + line["cash_event_id"] + "; not a new payment."
                    )
                rows.append(
                    [
                        description + "\nPosition: " + value["id"],
                        money(line.get("signed_cents")) + "\n" + value["review"],
                        provenance,
                    ]
                )
            self.table(
                ["Position", "Signed USD / review", "Source and provenance"], rows, [185, 95, 225]
            )

    def discussion(self, snapshot: Snapshot, *, pinned: bool = False) -> None:
        self.add("Questions, evidence and owner decisions", "heading")
        discussion = snapshot.payload.get("discussion", {})
        cards = discussion.get("cards", [])
        for question in snapshot.payload["result"].get("questions", []):
            self.add(question["code"] + ": " + question["message"])
            self.add(
                "Affects: " + ", ".join(METRICS.get(k, k) for k in question.get("affects", [])),
                "small",
            )
        if not cards:
            self.add("No saved discussion cards. Absence of questions is not proof of correctness.")
        if pinned and self.basis.comparison:
            replies = self.basis.comparison.payload.get("reply_versions", [])
            self.add(
                "Only reply versions pinned to this completed recheck are included here. "
                "Other replies visible in the case are not implicitly part of this package."
            )
        else:
            replies = [
                {"reply_id": r["id"], "question_ids": r["question_ids"], **r["versions"][-1]}
                for r in discussion.get("replies", [])
                if r.get("versions")
            ]
            self.add(
                "Replies below are the versions present in this saved calculation. "
                "Later edits are not included."
            )
        for index, card in enumerate(cards, 1):
            observation = card["observation"]
            self.add(f"Q{index} - " + observation["message"], "sub")
            self.add(
                "Evidence: "
                + card["evidence_state"].replace("_", " ")
                + " | Owner decision: "
                + card["owner_decision"].replace("_", " ")
            )
            self.add("Question reference: " + card["id"], "small")
            refs = list(
                dict.fromkeys(
                    observation.get("source_refs", []) + card.get("verified_source_refs", [])
                )
            )
            if refs:
                self.add(
                    self.sources.citations(snapshot, refs)
                    + " "
                    + self.sources.excerpt(snapshot, refs),
                    "small",
                )
            for file_id in card.get("file_ids", []):
                self.add("Linked material: " + self.sources.file(snapshot, file_id), "small")
            notes = [e for e in card.get("events", []) if e.get("kind") == "assessment"]
            for event in notes[-1:]:
                self.add("Owner assessment note: " + event["detail"])
            related = [r for r in replies if card["id"] in r.get("question_ids", [])]
            for r in related:
                self.add(
                    "Owner-reported contractor reply - version "
                    + str(r["version"])
                    + " | entered "
                    + date_label(r["added_at"]),
                    "sub",
                )
                # Keep a long answer readable across pages without moving the entire
                # paragraph to a nearly empty page just to keep its heading with it.
                for chunk in textwrap.wrap(
                    r["text"],
                    width=1200,
                    break_long_words=False,
                    replace_whitespace=False,
                    drop_whitespace=False,
                ):
                    self.add(chunk)
                self.add(
                    "Reply reference: "
                    + r["reply_id"]
                    + " | Text SHA-256: "
                    + hashlib.sha256(r["text"].encode()).hexdigest(),
                    "small",
                )
                for file_id in r.get("file_ids", []):
                    self.add("Reply attachment: " + self.sources.file(snapshot, file_id), "small")
            if not related:
                self.add("No reply included for this question in this selected version.", "small")

    def changes(self) -> None:
        comparison = self.basis.comparison
        if comparison is None:
            return
        self.story.append(PageBreak())
        result = comparison.payload["result"]
        self.add("What changed in the completed recheck", "heading")
        self.add(
            "Relationship: "
            + comparison.payload["package"]["relationship"]
            + " | Algorithm: "
            + comparison.algorithm
        )
        self.add("Explanation-only review: " + ("Yes" if result.get("explanation_only") else "No"))
        self.table(
            ["Indicator", "Before", "After", "Change"],
            [
                [
                    label,
                    money(result["metrics"][key]["before"]),
                    money(result["metrics"][key]["after"]),
                    money(result["metrics"][key]["delta"]),
                ]
                for key, label in METRICS.items()
            ],
            [205, 100, 100, 100],
        )
        self.add(result.get("notice", "Invoice differences are not savings."), "warning")
        rows = []
        for change in result.get("changes", []):
            descriptions = []
            for label, field, snap in (
                ("Before", "old", self.basis.previous),
                ("After", "new", self.basis.selected),
            ):
                row = change.get(field)
                if row and snap:
                    descriptions.append(
                        label
                        + ": "
                        + row["value"]["description"]
                        + "\n"
                        + row["value"]["kind"].replace("_", " ")
                        + "; "
                        + money(row.get("signed_cents"))
                        + "\n"
                        + self.sources.citations(snap, [row["source_ref"]])
                    )
                else:
                    descriptions.append(label + ": position absent")
            rows.append(
                [
                    change["change"] + "\nFields: " + ", ".join(change.get("fields", [])),
                    "\n".join(descriptions),
                    money(change.get("signed_delta_cents")),
                ]
            )
        self.table(["Classification", "Compared positions", "Signed change"], rows, [105, 310, 90])
        for label, key in (("Before", "unmatched_old"), ("After", "unmatched_new")):
            for row in result.get(key, []):
                self.add(
                    label
                    + " unmatched position: "
                    + row["value"]["description"]
                    + " | "
                    + money(row.get("signed_cents"))
                )
        self.add("Unresolved comparison issues", "sub")
        for issue in result.get("issues", []):
            self.add(issue)
        self.add("Findings against original questions", "sub")
        for finding in result.get("question_findings", []):
            self.add(finding["original_question"], "sub")
            self.add(finding["finding"])
            self.add(finding["still_unknown"])
            self.add(
                "Evidence: "
                + finding["current_evidence_state"].replace("_", " ")
                + " | Owner decision: "
                + finding["owner_decision"].replace("_", " ")
            )
            for row in finding.get("evidence", []):
                refs = [row["source_ref"], *row.get("cash_evidence_refs", [])]
                self.add(
                    self.sources.citations(self.basis.selected, refs)
                    + " "
                    + row["value"]["description"]
                    + " | "
                    + money(row.get("signed_cents"))
                )
                self.add(
                    "Original extract: " + (row.get("original_text") or "Manual entry"), "small"
                )
        for card in result.get("new_questions", []):
            self.add("New question: " + card["observation"]["message"])
        self.add("Payment conditions - before / after", "sub")
        for label, key, snap in (
            ("Before", "conditions_before", self.basis.previous),
            ("After", "conditions_after", self.basis.selected),
        ):
            self.add(label + ":")
            if not result.get(key):
                self.add("Unknown")
            for c in result.get(key, []):
                self.add(
                    (self.sources.citations(snap, [c["source_id"]]) if snap else "")
                    + " "
                    + c["text"]
                )

    def register(self) -> None:
        self.story.append(CondPageBreak(240))
        self.add("Source register", "heading")
        self.add(
            "References such as [S3, p. 2] point to this register. File checksums identify "
            "the stored original bytes; originals are not attached to this PDF."
        )
        for number, entry in enumerate(self.sources.entries, 1):
            if "document" in entry:
                doc = entry["document"]
                self.add(f"S{number} - " + doc["name"], "sub")
                self.add(
                    f"Original version: immutable uploaded file {doc['id']}. "
                    f"Pages: {doc['page_count']}. Extraction state: {doc['status']}."
                )
                self.add("SHA-256: " + doc["checksum"], "small")
                self.add("Included in snapshot(s): " + ", ".join(entry["snapshots"]), "small")
                for page in doc.get("pages", []):
                    self.add(
                        f"p. {page['number']} | {page['method']} | excerpt: "
                        + text(page["text"])[:280].strip(),
                        "small",
                    )
                    if page.get("warning"):
                        self.add("Extraction limitation: " + page["warning"])
            else:
                summary = entry["review"]
                self.add(f"S{number} - Owner's recorded review", "sub")
                self.add(
                    f"Revision {summary.financial_revision}; {date_label(summary.created_at)}. "
                    f"Snapshot {summary.id}. Owner input, not independent verification."
                )

    def page(self, canvas: Any, doc: Any) -> None:
        if doc.page > MAX_PAGES:
            raise PageLimitExceeded("This saved report exceeds the 300-page export limit")
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(45, 815, "RENOTRACE  /  SAVED RECONCILIATION")
        canvas.drawString(45, 25, "Historical record - originals not attached")
        canvas.drawRightString(550, 25, f"Page {doc.page}")
        canvas.restoreState()

    def build(self) -> bytes:
        selected = self.basis.selected
        self.add("RenoTrace", "title")
        documents = selected.payload["project"]["documents"]
        if documents and all(
            any("FICTIONAL TEST DOCUMENT" in p["text"] for p in d.get("pages", []))
            for d in documents
        ):
            self.add("FICTIONAL EXAMPLE - source files are labelled test documents.", "warning")
        self.add("Saved reconciliation report", "heading")
        self.add(
            "Historical record - completed recheck"
            if self.basis.comparison
            else "Historical record - saved calculation"
        )
        self.add("Report ID: " + self.basis.report_id, "small")
        self.add("Review saved: " + date_label(selected.summary.created_at))
        self.add("PDF generated: " + date_label(self.generated_at))
        self.add(
            f"Snapshot: {selected.summary.id} | revision {selected.summary.financial_revision}",
            "small",
        )
        self.add(
            f"Contract: {selected.summary.contract_version} | Ledger rules: "
            + str(selected.payload["result"]["calculation"].get("rules_version", "Unknown"))
            + f" | PDF format: {EXPORT_VERSION}",
            "small",
        )
        if self.basis.comparison:
            comparison = self.basis.comparison
            self.add("Comparison saved: " + date_label(comparison.created_at), "small")
            self.add(
                f"Comparison {comparison.algorithm}: {comparison.base_snapshot_id} -> "
                f"{comparison.new_snapshot_id}",
                "small",
            )
        self.add(
            "This PDF contains the selected saved evidence, not a live case status. "
            "Later files, replies and owner decisions are not included. Save a new review "
            "to include them. Access checks do not update the historical content.",
            "small",
        )
        self.warning(selected)
        self.metric_table(selected)
        request_id = (
            selected.payload["project"].get("review", {}).get("command", {}).get("request_id")
        )
        invoice = next(
            (d for d in documents if any(c["id"] == request_id for c in d["candidates"])), None
        )
        self.add(
            "Selected invoice: "
            + (
                invoice["name"] + " " + self.sources.file(selected, invoice["id"])
                if invoice
                else "Unknown - no invoice selected"
            )
        )
        self.conditions(selected)
        self.add(
            "A reconciliation with source references, not the full set of original documents. "
            "The downloaded copy remains with its recipient after guest access expires.",
            "small",
        )
        self.changes()
        self.financial_basis(selected)
        self.composition(selected)
        self.discussion(selected, pinned=self.basis.comparison is not None)
        if self.basis.previous:
            self.story.append(PageBreak())
            previous = self.basis.previous
            self.add("Previous calculation - historical basis", "heading")
            self.add(
                f"Snapshot {previous.summary.id} | revision {previous.summary.financial_revision} "
                f"| {date_label(previous.summary.created_at)} | {previous.summary.contract_version}"
            )
            self.warning(previous)
            self.metric_table(previous)
            self.conditions(previous)
            self.financial_basis(previous)
            self.composition(previous)
            self.discussion(previous)
        self.add("Limits of this report", "heading")
        self.add(
            "This is not independent authentication or a payment authorization. "
            "Extraction and owner checking can be incomplete. Reply text was entered by the "
            "owner and is not automatically verified. Unknown values, negative balances and "
            "unresolved evidence are preserved. Source excerpts are partial; obtain original "
            "documents separately. Addresses and credential-like strings are omitted from "
            "rendered text. No attachments, executable markup or external links are embedded."
            " Unsupported glyphs use explicit Unicode code-point labels instead of missing boxes."
        )
        self.register()
        output = BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=A4,
            rightMargin=45,
            leftMargin=45,
            topMargin=48,
            bottomMargin=46,
            title="RenoTrace saved reconciliation",
            author="RenoTrace",
            subject="Historical saved evidence",
            creator="RenoTrace " + EXPORT_VERSION,
            pageCompression=1,
        )
        try:
            doc.build(self.story, onFirstPage=self.page, onLaterPages=self.page)
            content = output.getvalue()
        except PageLimitExceeded as error:
            raise Problem(413, "This saved report exceeds the 300-page export limit") from error
        finally:
            output.close()
        if len(content) > MAX_PDF_BYTES:
            raise Problem(413, "This saved report exceeds the 16 MiB export limit")
        return content


def render_pdf(basis: ReportBasis, generated_at: datetime | None = None) -> bytes:
    return Report(basis, generated_at or datetime.now(UTC)).build()
