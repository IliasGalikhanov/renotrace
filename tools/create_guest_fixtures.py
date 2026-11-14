"""Rebuild fictional source documents used by extraction and browser acceptance tests."""

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "uploads"
ROOT.mkdir(parents=True, exist_ok=True)


def document(name: str, heading: str, lines: list[str]) -> None:
    canvas = Canvas(str(ROOT / name), pagesize=(595, 842), invariant=1)
    canvas.setTitle("RenoTrace fictional test evidence")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(48, 790, "FICTIONAL TEST DOCUMENT - No real person or transaction")
    canvas.setFont("Helvetica-Bold", 24)
    canvas.drawString(48, 730, heading)
    canvas.setFont("Helvetica", 16)
    for index, line in enumerate(lines):
        canvas.drawString(48, 675 - index * 36, line)
    canvas.save()


document(
    "estimate.pdf", "Renovation estimate", ["Date: 2026-11-01", "Estimate total: USD 10,000.00"]
)
document(
    "estimate-changed.pdf",
    "Renovation estimate",
    ["Date: 2026-11-01", "Estimate total: USD 9,000.00"],
)
document(
    "payment.pdf",
    "Payment receipt",
    [
        "Date: 2026-11-02",
        "Status: completed",
        "Total: USD 3,000.00",
        "Account: TEST-ACCOUNT",
        "Transaction ID: TEST-TRANSFER",
    ],
)
document(
    "payment-copy.pdf",
    "Payment receipt copy",
    [
        "Date: 2026-11-02",
        "Status: completed",
        "Total: USD 3,000.00",
        "Account: TEST-ACCOUNT",
        "Transaction ID: TEST-TRANSFER",
    ],
)
document(
    "payment-second.pdf",
    "Payment receipt second transfer",
    [
        "Date: 2026-11-02",
        "Status: completed",
        "Total: USD 3,000.00",
        "Account: TEST-ACCOUNT",
        "Transaction ID: TEST-TRANSFER-SECOND",
    ],
)
document(
    "invoice.pdf",
    "Current invoice",
    ["Date: 2026-11-03", "Amount due: USD 7,000.00", "Payment terms: after written approval"],
)
document(
    "balance.pdf",
    "Invoice balance",
    ["Date: 2026-11-03", "Deposit mentioned: USD 3,000.00", "Balance: USD 7,000.00"],
)
pdf = pdfium.PdfDocument(str(ROOT / "estimate.pdf"))
bitmap = pdf[0].render(scale=2)
image = bitmap.to_pil().convert("RGB")
image.save(ROOT / "estimate.png")
image.save(ROOT / "estimate.jpg", quality=95)
scan = Canvas(str(ROOT / "estimate-scan.pdf"), pagesize=(595, 842), invariant=1)
scan.drawImage(ImageReader(image), 0, 0, 595, 842)
scan.save()
image.close()
bitmap.close()
pdf.close()
Image.new("RGB", (800, 600), "white").save(ROOT / "unreadable.png")
writer = PdfWriter()
writer.append(PdfReader(ROOT / "estimate.pdf"))
writer.encrypt("test-password")
writer.write(ROOT / "password.pdf")
writer = PdfWriter()
for _ in range(21):
    writer.add_blank_page(595, 842)
writer.write(ROOT / "too-many-pages.pdf")
print("Created fictional text PDFs, scanned PDF, PNG/JPEG and rejection fixtures")
