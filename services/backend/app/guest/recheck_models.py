"""Saved recheck packages and frozen comparisons. Money is computed on the server."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from .casework_models import MutationID
from .invoice_models import ID
from .models import Model, ReviewCommand

ALGORITHM = "invoice-comparison/1"


class ReplyRef(Model):
    reply_id: ID
    version: Annotated[int, Field(strict=True, ge=1)]


class Match(Model):
    old_id: ID | None = None
    new_id: ID | None = None


class QuestionLink(Model):
    question_id: ID
    new_line_id: ID
    note: Annotated[str, Field(min_length=1, max_length=1000)]


class Package(Model):
    file_ids: Annotated[list[ID], Field(max_length=20)] = Field(default_factory=list)
    replies: Annotated[list[ReplyRef], Field(max_length=20)] = Field(default_factory=list)
    old_request_id: ID | None = None
    new_request_id: ID | None = None
    relationship: Literal["same", "corrected", "separate", "unknown"] = "unknown"
    matches: Annotated[list[Match], Field(max_length=200)] = Field(default_factory=list)
    question_links: Annotated[list[QuestionLink], Field(max_length=100)] = Field(
        default_factory=list
    )


class RecheckDraft(Model):
    id: str
    base_snapshot_id: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    package: Package = Field(default_factory=Package)
    status: Literal["draft", "completed"] = "draft"
    comparison_id: str | None = None


class StartRecheck(Model):
    mutation_id: MutationID
    base_snapshot_id: ID


class SavePackage(Model):
    mutation_id: MutationID
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    package: Package


class RunRecheck(Model):
    mutation_id: MutationID
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    review: ReviewCommand


class Comparison(Model):
    id: str
    base_snapshot_id: str
    new_snapshot_id: str
    created_at: datetime
    algorithm: str = ALGORITHM
    basis_fingerprint: str
    # Deliberately frozen JSON, not revalidated through today's comparison algorithm.
    payload: dict[str, Any]


class ComparisonSummary(Model):
    id: str
    base_snapshot_id: str
    new_snapshot_id: str
    created_at: datetime
    current: bool
    preliminary: bool


class RecheckView(Model):
    drafts: list[RecheckDraft] = Field(default_factory=list)
    comparisons: list[ComparisonSummary] = Field(default_factory=list)
