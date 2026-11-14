"""Deterministic fictional, labelled invoice PDFs for the real upload/recheck path."""

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "uploads"


def pdf(name: str, heading: str, lines: list[str]) -> None:
    canvas = Canvas(str(ROOT / name), pagesize=(595, 842), invariant=1)
    canvas.setTitle("RenoTrace fictional recheck evidence")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(36, 800, "FICTIONAL TEST DOCUMENT - No real person or transaction")
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(36, 760, heading)
    canvas.setFont("Helvetica", 11)
    for index, line in enumerate(lines):
        canvas.drawString(36, 720 - index * 26, line)
    canvas.save()


pdf(
    "recheck-estimate.pdf",
    "Renovation estimate",
    ["Date: 2026-11-01", "Estimate total: USD 6,200.00"],
)
pdf(
    "recheck-payment.pdf",
    "Payment receipt",
    [
        "Date: 2026-11-02",
        "Status: completed",
        "Total: USD 1,200.00",
        "Account: SYNTHETIC-RECHECK",
        "Transaction ID: RECHECK-TRANSFER-1",
    ],
)
pdf(
    "recheck-original.pdf",
    "Invoice original",
    [
        "Date: 2026-11-03",
        "Work [surface]: Surface preparation | USD 6,200.00",
        "Amount due: USD 6,200.00",
        "Payment terms: after written approval",
    ],
)
pdf(
    "recheck-corrected.pdf",
    "Invoice corrected",
    [
        "Date: 2026-11-04",
        "Work [surface]: Surface preparation | USD 6,200.00",
        "Payment reflected [advance]: Earlier bank transfer | USD 1,200.00",
        "Amount due: USD 5,000.00",
        "Payment terms: after written approval",
    ],
)
pdf(
    "recheck-discount.pdf",
    "Invoice with discount",
    [
        "Date: 2026-11-03",
        "Work [surface]: Surface preparation | USD 6,500.00",
        "Discount [loyalty]: Agreed discount | USD 300.00",
        "Amount due: USD 6,200.00",
        "Payment terms: after written approval",
    ],
)
pdf(
    "recheck-new-work.pdf",
    "Invoice revised scope",
    [
        "Date: 2026-11-04",
        "Work [surface]: Surface preparation | USD 6,500.00",
        "Work [extra]: New tile work | USD 500.00",
        "Credit [allowance]: Price allowance | USD 2,500.00",
        "Amount due: USD 4,500.00",
        "Payment terms: after milestone inspection",
    ],
)
pdf(
    "recheck-equal.pdf",
    "Invoice changed composition",
    [
        "Date: 2026-11-04",
        "Work [tiles]: Tile replacement | USD 6,200.00",
        "Amount due: USD 6,200.00",
        "Payment terms: after milestone inspection",
    ],
)
pdf(
    "recheck-incomplete.pdf",
    "Invoice incomplete composition",
    [
        "Date: 2026-11-04",
        "Work [surface]: Surface preparation | USD 6,000.00",
        "Amount due: USD 5,000.00",
        "Payment terms: after written approval",
    ],
)
pdf(
    "recheck-unlabelled.pdf",
    "Invoice manual composition",
    ["Date: 2026-11-04", "Surface preparation: USD 6,200.00", "Amount due: USD 6,200.00"],
)
print("Created nine fictional PDF recheck fixtures")
