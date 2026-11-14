"""Export three explicitly fictional QA examples from the real saved-evidence test path."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/backend/tests"))
from test_guest_pdf import NOW, example_basis  # noqa: E402

from app.guest.pdf_report import render_pdf  # noqa: E402

destination = ROOT / "output/pdf"
destination.mkdir(parents=True, exist_ok=True)
for kind in ("snapshot", "comparison", "long"):
    path = destination / f"renotrace-fictional-{kind}.pdf"
    path.write_bytes(render_pdf(example_basis(kind), NOW))
    print(path)
