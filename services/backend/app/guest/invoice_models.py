"""Invoice composition describes a document; it never creates ledger events."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

LineKind = Literal[
    "work", "charge", "discount", "credit", "reflected_payment", "condition", "unknown"
]
Text = Annotated[str, Field(min_length=1, max_length=600)]
ID = Annotated[str, Field(min_length=1, max_length=160)]


class InvoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvoiceProposal(InvoiceModel):
    id: ID
    page: Annotated[int, Field(strict=True, ge=1, le=20)]
    kind: LineKind
    description: Text
    amount: str | None = None
    source_key: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    original_text: str
    origin: Literal["pdf_text", "tesseract"]


class InvoiceLine(InvoiceModel):
    id: ID
    proposal_id: ID | None = None
    page: Annotated[int, Field(strict=True, ge=1, le=20)]
    kind: LineKind
    description: Text
    amount: Annotated[str, Field(max_length=40)] | None = None
    quantity: Annotated[str, Field(max_length=40)] | None = None
    unit_price: Annotated[str, Field(max_length=40)] | None = None
    review: Literal["checked", "unknown", "excluded"] = "unknown"
    cash_record_id: ID | None = None


class InvoiceReview(InvoiceModel):
    file_id: ID
    request_id: ID
    complete: bool = False
    lines: Annotated[list[InvoiceLine], Field(max_length=100)] = Field(default_factory=list)


class RequestVersion(InvoiceModel):
    """Explicit current-request lineage, separate from agreement supersession."""

    old_request_id: ID
    new_request_id: ID
