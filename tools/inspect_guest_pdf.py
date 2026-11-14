"""Content verification for a downloaded synthetic browser-test report, not a renderer."""

import json
import sys

from pypdf import PdfReader

reader = PdfReader(sys.argv[1])
assert not reader.attachments
assert not reader.trailer["/Root"].get("/OpenAction")
assert all(not page.get("/Annots") for page in reader.pages)
print(
    json.dumps(
        {
            "pages": len(reader.pages),
            "text": " ".join(" ".join(page.extract_text() for page in reader.pages).split()),
        }
    )
)
