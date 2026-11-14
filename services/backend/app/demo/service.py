"""Load only bundled synthetic data; a request owns its entire calculation history."""

from datetime import UTC, datetime
from importlib.resources import files

from fastapi import HTTPException

from app.ledger import calculate
from app.normalization import normalize
from app.normalization.models import AssignContractor, Billing, PaymentAllocation, Source

from .models import Catalog, DemoResult, RecipientAction, Sample, SourceContent, Trace


def catalog() -> Catalog:
    # Parse afresh: no mutable singleton, visitor session, database or shared draft.
    return Catalog.model_validate_json(
        files(__package__).joinpath("samples.json").read_text("utf-8")
    )


def sample_by_id(scenario_id: str) -> Sample:
    for sample in catalog().samples:
        if sample.summary.id == scenario_id:
            return sample
    raise HTTPException(404, "Unknown demo scenario")


def demo_result(scenario_id: str, actions: list[RecipientAction]) -> DemoResult:
    sample = sample_by_id(scenario_id)
    history = sample.history
    selected: dict[tuple[str, str], RecipientAction] = {}
    for action in actions:
        if not any(
            option.kind == action.kind
            and option.record_id == action.record_id
            and action.answer in option.answers
            for option in sample.allowed_actions
        ):
            raise HTTPException(422, "This action is not allowed for this demo record")
        selected[(action.kind, action.record_id)] = action
    contents = list(sample.source_contents)
    canonical_actions = tuple(selected[key] for key in sorted(selected))
    if canonical_actions:
        # Only FIN-16's unlinked recipient can be edited. We do not rebase old
        # decisions/relations or weaken the domain's revision checks.
        revision = history.case_revision + 1
        sources = list(history.sources)
        decisions = list(history.decisions)
        for action in canonical_actions:
            source_id = f"demo-decision:{action.record_id}"
            sources.append(
                Source(
                    id=source_id,
                    case_id=history.case_id,
                    version=1,
                    origin="user_statement",
                    locator=f"inline:{source_id}",
                    actor_id="demo-visitor",
                )
            )
            contents.append(
                SourceContent(
                    source_id=source_id,
                    title="Your demo decision",
                    excerpt=(
                        f"Recipient selected: {action.answer}. "
                        "Applies only to this calculation; not saved."
                    ),
                )
            )
            decisions.append(
                AssignContractor(
                    id=f"decision:{action.record_id}",
                    target_id=action.record_id,
                    basis_revision=revision,
                    actor_id="demo-visitor",
                    decided_at=datetime.now(UTC),
                    evidence_refs=(source_id,),
                    contractor_id=(
                        history.contractor_id
                        if action.answer == "contractor"
                        else "demo-other-recipient"
                        if action.answer == "other"
                        else None
                    ),
                )
            )
        history = history.model_copy(
            update={
                "case_revision": revision,
                "sources": tuple(sources),
                "decisions": tuple(decisions),
            }
        )
    normalized = normalize(history)
    result = calculate(normalized.ledger_input)
    dispositions = (*normalized.included, *normalized.excluded)
    traces: dict[str, Trace] = {}
    records = {r.id: r for r in history.records}

    def trace(key: str, label: str, amount: int | None, formula: str, ids: set[str]) -> None:
        ids = set(ids)
        pending = list(ids)
        while pending:
            record = records[pending.pop()]
            dependencies: tuple[str | None, ...] = ()
            if isinstance(record, Billing):
                dependencies = (record.previous_id, record.credit_target_id)
            elif isinstance(record, PaymentAllocation):
                dependencies = (record.cash_id, record.charge_id, record.reverses_allocation_id)
            for dependency in dependencies:
                if dependency is not None and dependency not in ids:
                    ids.add(dependency)
                    pending.append(dependency)
        entries = [d for d in dispositions if d.record.id in ids]
        traces[key] = Trace(
            label=label,
            amount_cents=amount,
            formula=formula,
            record_ids=tuple(sorted(ids)),
            source_ids=tuple(sorted({ref for d in entries for ref in d.evidence_refs})),
        )

    def raw_ids(canonical_ids: tuple[str, ...]) -> set[str]:
        return {d.record.id for d in dispositions if d.canonical_record_id in canonical_ids}

    commitments = raw_ids(result.commitment_record_ids)
    cash = raw_ids(result.completed_cash_record_ids)
    billed = {d.record.id for d in normalized.included if d.record.kind == "billing"}
    allocations = {d.record.id for d in normalized.included if d.record.kind == "allocation"}
    trace(
        "requested_now_cents",
        "Invoice request",
        result.requested_now_cents,
        "Taken from the current request; kept separate from the calculated remainder.",
        set() if history.current_request_id is None else {history.current_request_id},
    )
    trace(
        "commitment_total_cents",
        "Recorded commitments",
        result.commitment_total_cents,
        "Selected agreement + effective changes and credits.",
        commitments,
    )
    trace(
        "net_paid_cents",
        "Net payments",
        result.net_paid_cents,
        "Completed payments to this contractor − completed refunds.",
        cash,
    )
    trace(
        "remaining_commitment_cents",
        "Remaining under recorded terms",
        result.remaining_commitment_cents,
        "Recorded commitments − net payments.",
        commitments | cash,
    )
    trace(
        "billed_total_cents",
        "Total billed",
        result.billed_total_cents,
        "Distinct charges and cumulative increments + billing credits.",
        billed,
    )
    trace(
        "positive_outstanding_cents",
        "Open invoice balances",
        result.positive_outstanding_cents,
        "Sum of positive charge balances after explicit allocations.",
        billed | allocations,
    )
    trace(
        "credit_balance_cents",
        "Invoice credit balances",
        result.credit_balance_cents,
        "Credit balances are shown separately, without clamping individual balances.",
        billed | allocations,
    )
    trace(
        "unallocated_cents",
        "Unallocated cash",
        result.unallocated_cents,
        "Net payments − net allocations to charges.",
        cash | allocations,
    )
    for charge in normalized.ledger_input.charges:
        trace(
            f"charge:{charge.id}",
            "New charge",
            charge.amount_cents,
            "For a cumulative valuation: current gross valuation − previous gross valuation. "
            "Payments are not subtracted in this step.",
            raw_ids((charge.id,)),
        )
    for balance in result.charge_balances:
        trace(
            f"balance:{balance.charge_id}",
            "Charge balance",
            balance.remaining_cents,
            "Charge with billing credits − net allocations.",
            raw_ids(
                (
                    balance.charge_id,
                    *(
                        row.id
                        for row in normalized.ledger_input.allocations
                        if row.charge_id == balance.charge_id
                    ),
                    *(
                        credit.id
                        for credit in normalized.ledger_input.billing_credits
                        if credit.charge_id == balance.charge_id
                    ),
                )
            ),
        )
    return DemoResult(
        scenario=sample.summary,
        history=history,
        source_contents=tuple(contents),
        record_titles=sample.record_titles,
        conditions=sample.conditions,
        allowed_actions=sample.allowed_actions,
        actions=canonical_actions,
        explanation=sample.explanation,
        normalization=normalized,
        calculation=result,
        traces=traces,
    )
