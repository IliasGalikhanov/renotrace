"""Persisted extraction evidence and explicit review commands."""

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .invoice_models import InvoiceProposal, InvoiceReview, RequestVersion

Kind = Literal[
    "agreement", "adjustment", "payment_request", "payment", "refund", "condition", "unknown"
]
ShortText = Annotated[str, Field(max_length=300)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidate(Model):
    id: str
    file_id: str
    page: int
    kind: Kind
    original_amount: str | None = None
    amount: str | None = None
    date: str | None = None
    snippet: str
    state: Literal["completed", "pending", "scheduled", "failed", "reversed"] = "pending"
    account: str | None = None
    transaction: str | None = None


class Page(Model):
    number: int
    text: str
    method: Literal["pdf_text", "tesseract"]
    warning: str | None = None


class Document(Model):
    id: str
    name: str
    checksum: str
    size: int
    media_type: str
    page_count: int
    pages: list[Page] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    invoice_proposals: list[InvoiceProposal] = Field(default_factory=list)
    status: Literal["queued", "processing", "ready", "failed"] = "queued"
    error: str | None = None


class RecordChoice(Model):
    id: ShortText
    kind: Kind
    amount: Annotated[str, Field(max_length=40)] | None = None
    date: Date | None = None
    answer: Literal["accept", "reject", "unknown"] = "unknown"
    recipient: Literal["contractor", "other", "unknown"] = "unknown"
    state: Literal["completed", "pending", "scheduled", "failed", "reversed"] = "pending"


class LinkChoice(Model):
    kind: Literal["supersedes", "includes_adjustment"]
    from_id: ShortText
    to_id: ShortText


class ReviewCommand(Model):
    mutation_id: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")] | None = None
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    records: Annotated[list[RecordChoice], Field(max_length=150)]
    agreement_id: ShortText | None = None
    request_id: ShortText | None = None
    cutoff_date: Date
    links: Annotated[list[LinkChoice], Field(max_length=100)] = Field(default_factory=list)
    invoices: Annotated[list[InvoiceReview], Field(max_length=20)] = Field(default_factory=list)
    request_versions: Annotated[list[RequestVersion], Field(max_length=20)] = Field(
        default_factory=list
    )


class SavedReview(Model):
    id: str
    basis_revision: int
    created_at: datetime
    command: ReviewCommand


class Project(Model):
    id: str
    revision: int = 0
    created_at: datetime
    expires_at: datetime
    documents: list[Document] = Field(default_factory=list)
    review: SavedReview | None = None


class TicketRequest(Model):
    purpose: Literal["upload", "download"]
    file_id: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")] | None = None
    name: Annotated[str, Field(min_length=1, max_length=120)] = "document"


class Ticket(Model):
    token: str
    expires_in: int = 300


class Session(Model):
    token: str
    project_id: str


class Problem(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)
