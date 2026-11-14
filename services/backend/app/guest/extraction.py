"""Real page extraction, bounded local OCR, and conservative semantic candidates.

English labelled USD documents are supported. These are proposals, never verified facts.
The OCR adapter does not perform accounting and never calls an external model.
"""

import hashlib
import io
import re
import subprocess
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.ledger.models import MAX_CENTS

from .models import Candidate, Kind, Page, Problem

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
MONEY = re.compile(r"^(?:USD\s*|\$\s*)?(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)$")
AMOUNT = re.compile(r"(?:USD\s*|\$\s*)-?[\d,.]+|(?<![\d.])-?[\d,]+\.\d+(?!\d)")


def cents(value: str) -> int:
    match = MONEY.fullmatch(value.strip())
    if not match:
        raise ValueError("Use a USD amount such as 10000.00; fractional cents are not allowed")
    result = int(Decimal(match[1].replace(",", "")) * 100)
    if abs(result) > MAX_CENTS:
        raise ValueError("Amount exceeds the supported range")
    return result


def amount_text(value: str) -> str | None:
    try:
        number = cents(value)
    except ValueError:
        return None
    sign = "-" if number < 0 else ""
    return f"{sign}{abs(number) // 100}.{abs(number) % 100:02d}"


class OCR(Protocol):
    def text(self, image: Image.Image) -> str: ...


class Tesseract:
    def __init__(self, executable: str = "tesseract") -> None:
        self.executable = executable

    def text(self, image: Image.Image) -> str:
        with tempfile.TemporaryDirectory(prefix="renotrace-ocr-") as directory:
            path = Path(directory) / "page.png"
            image.save(path)
            result = subprocess.run(
                [self.executable, str(path), "stdout", "-l", "eng", "--psm", "6"],
                capture_output=True,
                timeout=45,
                check=True,
            )
            return result.stdout.decode("utf-8", errors="replace")[:30_000]


def inspect(data: bytes) -> tuple[str, int]:
    if not data or len(data) > MAX_BYTES:
        raise Problem(413, "Each file must be nonempty and at most 10 MiB")
    try:
        if data.startswith(b"%PDF-"):
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise Problem(422, "Password-protected PDFs are not supported")
            count = len(reader.pages)
            if not 1 <= count <= 20:
                raise Problem(422, "A file must contain between 1 and 20 pages")
            for page in reader.pages:
                width, height = float(page.mediabox.width), float(page.mediabox.height)
                if min(width, height) <= 0 or width * height * 4 > MAX_PIXELS:
                    raise Problem(422, "Page dimensions exceed the safe rendering limit")
            return "application/pdf", count
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
                raise Problem(422, "Use a single-frame PNG, JPEG or a PDF")
            if image.width * image.height > MAX_PIXELS:
                raise Problem(422, "Image exceeds 16 million pixels")
            media_type = "image/png" if image.format == "PNG" else "image/jpeg"
            image.verify()
        with Image.open(io.BytesIO(data)) as decoded:
            decoded.load()
        return media_type, 1
    except Problem:
        raise
    except (Exception, UnidentifiedImageError) as error:
        raise Problem(422, "The file is damaged or is not a supported PDF, PNG or JPEG") from error


def page_image(data: bytes, media_type: str, number: int) -> Image.Image:
    if media_type != "application/pdf":
        with Image.open(io.BytesIO(data)) as image:
            return image.convert("RGB")
    document = pdfium.PdfDocument(data)
    try:
        page = document[number - 1]
        try:
            bitmap = page.render(scale=2)
            try:
                return cast(Image.Image, bitmap.to_pil().convert("RGB"))
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def extract_page(data: bytes, media_type: str, number: int, ocr: OCR) -> Page:
    text = ""
    method = "tesseract"
    if media_type == "application/pdf":
        text = PdfReader(io.BytesIO(data), strict=True).pages[number - 1].extract_text() or ""
        if len(re.sub(r"\W", "", text)) >= 20:
            method = "pdf_text"
    if method == "tesseract":
        with page_image(data, media_type, number) as image:
            text = ocr.text(image)
    truncated = len(text) > 12_000
    text = text.replace("\x00", "")[:12_000].strip()
    return Page(
        number=number,
        text=text,
        method="pdf_text" if method == "pdf_text" else "tesseract",
        warning=(
            "Page text was truncated; review the original for omitted facts"
            if truncated
            else None
            if len(re.sub(r"\W", "", text)) >= 10
            else "Unreadable page; review the original"
        ),
    )


def semantic_candidates(file_id: str, page: Page) -> list[Candidate]:
    text = page.text
    low = text.lower()
    default: Kind = (
        "refund"
        if "refund" in low
        else "payment"
        if any(t in low for t in ("payment receipt", "bank transfer", "payment confirmation"))
        else "adjustment"
        if any(t in low for t in ("change order", "cost change", "variation"))
        else "agreement"
        if any(t in low for t in ("estimate", "contract price", "quotation"))
        else "payment_request"
        if "invoice" in low
        else "unknown"
    )
    dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text))
    parsed_date: str | None = None
    if len(dates) == 1:
        try:
            parsed_date = date.fromisoformat(next(iter(dates))).isoformat()
        except ValueError:
            pass
    completed = bool(re.search(r"\b(?:status\s*:\s*completed|payment completed|settled)\b", low))
    account_match = re.search(r"(?im)^\s*Account(?: ID)?\s*:\s*([\w-]{1,80})\s*$", text)
    transaction_match = re.search(r"(?im)^\s*Transaction(?: ID)?\s*:\s*([\w-]{1,80})\s*$", text)
    result: list[Candidate] = []
    usd_document = bool(re.search(r"\bUSD\b|\$", text))
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        label = line.lower()
        kind = default
        condition = bool(re.match(r"(?:payment terms|payment conditions|due date)\s*:", label))
        if condition:
            kind = "condition"
        elif any(word in label for word in ("deposit", "balance", "subtotal", "tax")):
            # An invoice's deposit/balance is not a new cash movement or contract price.
            kind = "unknown"
        elif "amount due" in label or "requested" in label:
            kind = "payment_request"
        elif "contract price" in label or "estimate total" in label:
            kind = "agreement"
        amounts = list(AMOUNT.finditer(line))
        if not condition and not amounts:
            continue
        for ordinal, match in enumerate([None] if condition else amounts):
            original = match[0] if match else None
            other_currency = bool(re.search(r"\b(?:EUR|GBP|CAD|AUD|KZT|RUB)\b|[€£₸₽]", line))
            value = (
                amount_text(original) if original and usd_document and not other_currency else None
            )
            if kind == "refund" and value is not None:
                value = "-" + value.lstrip("-")
            digest = hashlib.sha256(
                f"{file_id}:{page.number}:{index}:{ordinal}".encode()
            ).hexdigest()[:24]
            result.append(
                Candidate(
                    id=f"candidate-{digest}",
                    file_id=file_id,
                    page=page.number,
                    kind=kind,
                    original_amount=original,
                    amount=value,
                    date=parsed_date,
                    snippet=line[:600],
                    state="completed" if completed else "pending",
                    account=account_match[1] if account_match and transaction_match else None,
                    transaction=transaction_match[1]
                    if account_match and transaction_match
                    else None,
                )
            )
    return result
