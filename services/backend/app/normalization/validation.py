"""Reject corrupt references before any financial history is emitted."""

from collections import defaultdict

from .models import (
    Agreement,
    AssignContractor,
    ConfirmSemantics,
    HistoryInput,
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
