"""Reject corrupt references before any financial history is emitted."""

from collections import defaultdict
from collections.abc import Mapping

from .models import (
    Agreement,
    AssignContractor,
    Billing,
    Cash,
    ConfirmSemantics,
    HistoryInput,
    PaymentAllocation,
    PaymentRequest,
    ReviewLink,
    SelectAgreement,
    SelectVersion,
)


class NormalizationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def validate_history(history: HistoryInput) -> None:
    for name, collection in (
        ("source", history.sources),
        ("record", history.records),
        ("link", history.links),
        ("decision", history.decisions),
    ):
        ids = [item.id for item in collection]
        if len(ids) != len(set(ids)):
            raise NormalizationError("DUPLICATE_ID", name)
    records = {record.id: record for record in history.records}
    sources = {source.id: source for source in history.sources}
    links = {link.id: link for link in history.links}
    relations = [(link.kind, link.from_id, link.to_id) for link in history.links]
    if len(relations) != len(set(relations)):
        raise NormalizationError("DUPLICATE_RELATION", "one link per relationship is required")
    logical = {record.record_id for record in history.records}
    versions = [(record.record_id, record.version) for record in history.records]
    if len(versions) != len(set(versions)):
        raise NormalizationError("DUPLICATE_VERSION", "logical record/version must be unique")
    kinds: dict[str, set[str]] = defaultdict(set)
    for record in history.records:
        kinds[record.record_id].add(record.kind)
    if any(len(value) != 1 for value in kinds.values()):
        raise NormalizationError("RECORD_KIND_CONFLICT", "logical record changes kind")
    for source in history.sources:
        if source.case_id != history.case_id:
            raise NormalizationError("CROSS_CASE_SOURCE", source.id)
    for item in (*history.records, *history.links, *history.decisions):
        for ref in item.evidence_refs:
            if ref not in sources:
                raise NormalizationError("UNKNOWN_SOURCE", f"{item.id} -> {ref}")
    for record in history.records:
        if record.origin != "derived" and not any(
            sources[ref].origin == record.origin for ref in record.evidence_refs
        ):
            raise NormalizationError("ORIGIN_SOURCE_MISMATCH", record.id)
    validate_billing_references(records)

    # Validate even proposed replacement graphs; never silently repair cycles.
    edges: dict[str, set[str]] = defaultdict(set)
    for link in history.links:
        if link.from_id not in records or link.to_id not in records:
            raise NormalizationError("UNKNOWN_RECORD", link.id)
        parent, child = records[link.from_id], records[link.to_id]
        if parent.kind != "agreement" or child.kind != (
            "agreement" if link.kind == "supersedes" else "adjustment"
        ):
            raise NormalizationError("INVALID_LINK_KIND", link.id)
        if link.kind == "supersedes":
            edges[link.from_id].add(link.to_id)
    pending = {key: set(value) for key, value in edges.items()}
    while pending:
        leaves = {key for key, children in pending.items() if not (children & pending.keys())}
        if not leaves:
            raise NormalizationError("REPLACEMENT_CYCLE", ",".join(sorted(pending)))
        for key in leaves:
            del pending[key]
    for link in history.links:
        parent, child = records[link.from_id], records[link.to_id]
        if link.kind == "supersedes" and (
            parent.effective_date < child.effective_date
            or (parent.record_id == child.record_id and parent.version <= child.version)
        ):
            raise NormalizationError("INVALID_REPLACEMENT_ORDER", link.id)

    request = history.current_request_id
    if request is not None and not isinstance(records.get(request), PaymentRequest):
        raise NormalizationError("INVALID_CURRENT_REQUEST", request)
    for decision in history.decisions:
        if isinstance(decision, SelectVersion):
            selected = records.get(decision.selected_id or "")
            if decision.target_id not in logical or (
                decision.selected_id is not None
                and (selected is None or selected.record_id != decision.target_id)
            ):
                raise NormalizationError("INVALID_VERSION_SELECTION", decision.id)
        elif isinstance(decision, SelectAgreement):
            if decision.target_id != history.case_id or (
                decision.selected_id is not None
                and not isinstance(records.get(decision.selected_id), Agreement)
            ):
                raise NormalizationError("INVALID_AGREEMENT_SELECTION", decision.id)
        elif isinstance(decision, ReviewLink):
            if decision.target_id not in links:
                raise NormalizationError("UNKNOWN_LINK", decision.id)
        elif isinstance(decision, (AssignContractor, ConfirmSemantics)):
            if decision.target_id not in records:
                raise NormalizationError("UNKNOWN_RECORD", decision.id)


def validate_billing_references(records: Mapping[str, object]) -> None:
    edges: dict[str, set[str]] = defaultdict(set)
    for item in records.values():
        if isinstance(item, Billing):
            if len(item.coverage) != len(set(item.coverage)):
                raise NormalizationError("DUPLICATE_COVERAGE", item.id)
            if item.previous_id is not None:
                previous = records.get(item.previous_id)
                if (
                    item.basis != "cumulative_valuation"
                    or item.starts_at_zero
                    or not isinstance(previous, Billing)
                    or previous.basis not in ("incremental_charge", "cumulative_valuation")
                ):
                    raise NormalizationError("INVALID_PREVIOUS_BILLING", item.id)
                edges[item.id].add(previous.id)
            if item.starts_at_zero and item.basis != "cumulative_valuation":
                raise NormalizationError("INVALID_ZERO_BASELINE", item.id)
            if item.credit_target_id is not None:
                target = records.get(item.credit_target_id)
                if (
                    item.basis != "credit_note"
                    or not isinstance(target, Billing)
                    or target.basis not in ("incremental_charge", "cumulative_valuation")
                ):
                    raise NormalizationError("INVALID_CREDIT_TARGET", item.id)
            if item.amount_cents is not None and (
                (item.basis == "credit_note" and item.amount_cents >= 0)
                or (
                    item.basis in ("incremental_charge", "cumulative_valuation")
                    and item.amount_cents < 0
                )
            ):
                raise NormalizationError("INVALID_BILLING_DIRECTION", item.id)
        elif isinstance(item, PaymentAllocation):
            charge = records.get(item.charge_id)
            if (
                not isinstance(records.get(item.cash_id), Cash)
                or not isinstance(charge, Billing)
                or charge.basis not in ("incremental_charge", "cumulative_valuation")
            ):
                raise NormalizationError("INVALID_ALLOCATION_REFERENCE", item.id)
            if item.reverses_allocation_id is not None and not isinstance(
                records.get(item.reverses_allocation_id), PaymentAllocation
            ):
                raise NormalizationError("INVALID_REFUND_REFERENCE", item.id)
    pending = {key: set(value) for key, value in edges.items()}
    while pending:
        leaves = {key for key, children in pending.items() if not (children & pending.keys())}
        if not leaves:
            raise NormalizationError("BILLING_CYCLE", ",".join(sorted(pending)))
        for key in leaves:
            del pending[key]
    for item in records.values():
        if isinstance(item, Billing) and item.previous_id is not None:
            previous = records[item.previous_id]
            assert isinstance(previous, Billing)
            if previous.effective_date > item.effective_date:
                raise NormalizationError("INVALID_BILLING_ORDER", item.id)
