from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from app.ledger.models import Cents, Identifier, LedgerResult, StrictModel
from app.normalization.models import HistoryInput, NormalizationResult


class RecipientAction(StrictModel):
    kind: Literal["assign_recipient"]
    record_id: Identifier
    answer: Literal["contractor", "other", "unknown"]


class RecalculateRequest(StrictModel):
    actions: Annotated[list[RecipientAction], Field(max_length=12)] = Field(default_factory=list)


class SourceContent(StrictModel):
    source_id: Identifier
    title: str
    excerpt: str


class Conditions(StrictModel):
    due_date: date | None = None
    condition_text: str | None = None
    satisfaction: Literal["unknown", "user_reported"] = "unknown"
    evidence_refs: tuple[Identifier, ...] = ()


class ActionOption(StrictModel):
    kind: Literal["assign_recipient"] = "assign_recipient"
    record_id: Identifier
    label: str
    answers: tuple[Literal["contractor", "other", "unknown"], ...]


class ScenarioSummary(StrictModel):
    id: Identifier
    title: str
    description: str


class Sample(StrictModel):
    summary: ScenarioSummary
    history: HistoryInput
    source_contents: tuple[SourceContent, ...]
    record_titles: dict[str, str]
    conditions: Conditions
    allowed_actions: tuple[ActionOption, ...] = ()
    explanation: str


class Catalog(StrictModel):
    synthetic: Literal[True]
    samples: tuple[Sample, ...]


class Trace(StrictModel):
    label: str
    amount_cents: Cents | None
    formula: str
    record_ids: tuple[Identifier, ...]
    source_ids: tuple[Identifier, ...]


class DemoResult(StrictModel):
    synthetic: Literal[True] = True
    persistence: Literal["none"] = "none"
    scenario: ScenarioSummary
    history: HistoryInput
    source_contents: tuple[SourceContent, ...]
    record_titles: dict[str, str]
    conditions: Conditions
    allowed_actions: tuple[ActionOption, ...]
    actions: tuple[RecipientAction, ...]
    explanation: str
    normalization: NormalizationResult
    calculation: LedgerResult
    traces: dict[str, Trace]
