"""A fictional ordinary invoice, deliberately not the parser's labelled-row grammar."""

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

root = Path(__file__).resolve().parents[1]
path = root / "fixtures/uploads/showcase-ordinary-invoice.pdf"
canvas = Canvas(str(path), pagesize=(595, 842), invariant=1)
canvas.setTitle("FICTIONAL - ordinary renovation invoice for RenoTrace acceptance")
canvas.setFont("Helvetica-Bold", 11)
canvas.drawString(40, 800, "FICTIONAL TEST DOCUMENT - No real person or transaction")
canvas.setFont("Helvetica-Bold", 22)
canvas.drawString(40, 746, "Invoice - living room renovation")
canvas.setFont("Helvetica", 12)
for y, line in enumerate(
    [
        "Fictional contractor: Willow Workshop | Invoice FICTIONAL-010",
        "Date: 2026-11-03",
        "Currency: USD",
        "Description                                                   Amount",
        "Wall painting                                                3,800.00",
        "Floor protection                                              400.00",
        "Skirting board installation                              2,000.00",
        "Amount due: USD 6,200.00",
        "Payment terms: after written approval",
        "Check this invoice against the estimate and payment receipt.",
    ]
):
    canvas.drawString(40, 704 - y * 31, line)
canvas.save()
print(path)
