"""Structured source history -> normalization -> real ledger, including rejection paths."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from test_normalization import decision, duplicate_record, row, run

from app.ledger import MAX_CENTS, LedgerInput
from app.normalization import HistoryInput, NormalizationError, normalize

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "fixtures/billing_cases.json").read_text(encoding="utf-8"))["cases"]


def payload(case="FIN-11"):
    return copy.deepcopy(next(c["input"] for c in CASES if c["id"] == case))


def assert_conservation(result):
    assert sum(b.amount_cents for b in result.cash_balances) == result.net_paid_cents
    assert sum(b.unallocated_cents for b in result.cash_balances) == result.unallocated_cents
    assert sum(b.net_allocation_cents for b in result.cash_balances) == result.net_allocations_cents
    assert result.net_paid_cents == result.net_allocations_cents + result.unallocated_cents
    for cash in result.cash_balances:
        assert cash.amount_cents == cash.net_allocation_cents + cash.unallocated_cents
        assert abs(cash.net_allocation_cents) <= abs(cash.amount_cents)
    for charge in result.charge_balances:
        assert charge.remaining_cents == charge.charge_cents - charge.net_allocation_cents
    assert sum(b.remaining_cents for b in result.charge_balances) == (
        result.positive_outstanding_cents - result.credit_balance_cents
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_source_scenarios(case):
    normalized, result = run(case["input"])
    for field, expected in case["expected"].items():
        assert getattr(result, field) == expected
    assert {q.code for q in normalized.questions} == set(case["expected_question_codes"])
    assert normalized.incomplete == bool(normalized.questions)
    dispositions = (*normalized.included, *normalized.excluded)
    assert len(dispositions) == len(case["input"]["records"])
    assert len({d.record.id for d in dispositions}) == len(dispositions)
    sources = {s.id for s in normalized.sources}
    for value in (
        *normalized.ledger_input.charges,
        *normalized.ledger_input.billing_credits,
        *normalized.ledger_input.allocations,
    ):
        assert value.evidence_refs and set(value.evidence_refs) <= sources
    assert_conservation(result)


def test_fin11_subtracts_previous_billing_never_payments():
    normalized, result = run(payload())
    current = next(c for c in normalized.ledger_input.charges if c.id == "record:current")
    assert current.amount_cents == 850000
    assert set(current.evidence_refs) == {"source:current", "source:first"}
    assert [(b.charge_id, b.remaining_cents) for b in result.charge_balances] == [
        ("record:current", 850000),
        ("record:first", 200000),
    ]
    data = payload()
    row(data, "payment")["amount_cents"] = 400000
    assert run(data)[1].billed_total_cents == 1350000


@given(st.sampled_from([c["id"] for c in CASES]), st.data())
@settings(max_examples=40)
def test_order_repeat_and_input_immutability(case, draw):
    data = payload(case)
    original = copy.deepcopy(data)
    first = run(data)
    for key in ("records", "sources", "links", "decisions"):
        data[key] = list(draw.draw(st.permutations(data[key])))
    assert run(data) == first
    assert run(original) == first
    assert (
        first[0].ledger_input
        == normalize(HistoryInput.model_validate_json(json.dumps(original))).ledger_input
    )


@given(st.integers(min_value=0, max_value=300000), st.integers(min_value=0, max_value=300000))
def test_partial_splits_conserve_cash_and_do_not_change_contract(a, b):
    b = min(b, 300000 - a)
    data = payload("PARTIAL")
    before = run(data)[1]
    row(data, "a1")["amount_cents"] = a
    row(data, "a2")["amount_cents"] = b
    data["records"] = [r for r in data["records"] if r["kind"] != "allocation" or r["amount_cents"]]
    result = run(data)[1]
    assert result.unallocated_cents == 300000 - a - b
    assert (
        result.commitment_total_cents,
        result.net_paid_cents,
        result.remaining_commitment_cents,
        result.requested_now_cents,
    ) == (
        before.commitment_total_cents,
        before.net_paid_cents,
        before.remaining_commitment_cents,
        before.requested_now_cents,
    )
    assert_conservation(result)


def test_many_payments_to_one_charge_and_equal_amount_no_implicit_link():
    data = payload("PARTIAL")
    duplicate_record(data, "payment", "payment2", bank_transaction_id="second-transfer")
    row(data, "a2")["cash_id"] = "payment2"
    row(data, "a2")["charge_id"] = "first"
    result = run(data)[1]
    assert result.net_paid_cents == 600000
    assert result.unallocated_cents == 350000
    assert result.credit_balance_cents == 150000
    assert result.positive_outstanding_cents == 150000
    assert_conservation(result)


def test_duplicate_import_uses_same_canonical_cash_and_does_not_multiply_capacity():
    data = payload("PARTIAL")
    original = run(data)[1]
    duplicate_record(data, "payment", "import2")
    row(data, "a2")["cash_id"] = "import2"
    assert run(data)[1] == original
    row(data, "a2")["amount_cents"] = 250000
    with pytest.raises(ValidationError, match="exceeds available cash"):
        run(data)


def test_refund_without_link_stays_unallocated_and_signed():
    data = payload("REFUND")
    data["records"] = [r for r in data["records"] if r["id"] != "r1"]
    result = run(data)[1]
    assert result.credit_balance_cents == 100000
    assert result.unallocated_cents == -100000
    assert result.net_paid_cents == 1000000
    assert_conservation(result)


def test_credit_changes_only_billing_and_can_create_negative_charge_balance():
    data = payload("CREDIT")
    row(data, "credit")["amount_cents"] = -1100000
    normalized, result = run(data)
    assert result.billed_total_cents == -100000
    assert result.credit_balance_cents == 100000
    assert result.net_paid_cents == 0
    assert result.commitment_total_cents == result.remaining_commitment_cents == 1000000
    credit = normalized.ledger_input.billing_credits[0]
    assert set(credit.evidence_refs) == {"source:credit", "source:invoice"}


def test_cumulative_chain_and_negative_increment():
    data = payload()
    duplicate_record(data, "current", "last", previous_id="current", amount_cents=1200000)
    normalized, result = run(data)
    assert result.billed_total_cents == 1200000
    assert (
        next(c.amount_cents for c in normalized.ledger_input.charges if c.id == "record:last")
        == -150000
    )
    assert_conservation(result)


def test_explicit_zero_baseline_is_required_for_first_cumulative():
    data = payload("UNKNOWN-PREVIOUS")
    row(data, "current")["starts_at_zero"] = True
    normalized, result = run(data)
    assert not normalized.incomplete
    assert result.billed_total_cents == 1350000


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("basis", "unknown", "UNKNOWN_BILLING_BASIS"),
        ("coverage", [], "BILLING_COVERAGE_REQUIRED"),
        ("coverage_confirmed", False, "BILLING_COVERAGE_REQUIRED"),
        ("basis_revision", 0, "STALE_BILLING_BASIS"),
        ("relationship_review", "proposed", "BILLING_RELATIONSHIP_REQUIRED"),
        ("relationship_review", "invalidated", "BILLING_RELATIONSHIP_REQUIRED"),
    ],
)
def test_uncertain_billing_is_provisional(field, value, code):
    data = payload("CREDIT")
    row(data, "invoice")[field] = value
    if field == "basis":
        # The target's type changed, so remove the structurally invalid dependent credit.
        data["records"] = [r for r in data["records"] if r["id"] != "credit"]
    normalized, result = run(data)
    question = next(q for q in normalized.questions if q.code == code)
    assert "billed_total_cents" in question.affects
    assert "remaining_commitment_cents" not in question.affects
    assert normalized.incomplete
    assert result.billed_total_cents == 0


@pytest.mark.parametrize("change", ["scope", "inactive", "unknown_amount", "unreviewed", "other"])
def test_cumulative_requires_eligible_comparable_previous(change):
    data = payload()
    previous = row(data, "first")
    if change == "scope":
        previous["coverage"] = ["different"]
    if change == "inactive":
        previous["review"]["lifecycle"] = "superseded"
    if change == "unknown_amount":
        previous["amount_cents"] = None
    if change == "unreviewed":
        previous["review"]["semantic_review"] = "unknown"
    if change == "other":
        previous["contractor_id"] = "another-builder"
    normalized, result = run(data)
    assert "CUMULATIVE_COMPARABILITY_REQUIRED" in {q.code for q in normalized.questions}
    assert "record:current" not in {c.charge_id for c in result.charge_balances}


@pytest.mark.parametrize("record_id", ["invoice", "credit"])
def test_rejected_relationship_is_intentional(record_id):
    data = payload("CREDIT")
    if record_id == "invoice":
        data["records"] = [r for r in data["records"] if r["id"] != "credit"]
    row(data, record_id)["relationship_review"] = "rejected"
    normalized, _ = run(data)
    assert not normalized.incomplete
    assert any(d.reason == "RELATIONSHIP_REJECTED" for d in normalized.excluded)


@pytest.mark.parametrize(
    "case,record_id,field,value,code",
    [
        ("CREDIT", "credit", "credit_target_id", None, "CREDIT_TARGET_UNRESOLVED"),
        ("CREDIT", "credit", "basis_revision", 0, "STALE_BILLING_BASIS"),
        ("PARTIAL", "a1", "basis_revision", 0, "STALE_ALLOCATION"),
        ("PARTIAL", "a1", "relationship_review", "proposed", "ALLOCATION_RELATIONSHIP_REQUIRED"),
    ],
)
def test_unresolved_relationships(case, record_id, field, value, code):
    data = payload(case)
    row(data, record_id)[field] = value
    normalized, _ = run(data)
    assert code in {q.code for q in normalized.questions}
    assert normalized.incomplete


@pytest.mark.parametrize("change", ["pending", "excluded", "cutoff", "version", "contractor"])
def test_unavailable_cash_cannot_be_allocated(change):
    data = payload("PARTIAL")
    payment = row(data, "payment")
    if change == "pending":
        payment["state"] = "pending"
    if change == "excluded":
        payment["review"]["lifecycle"] = "void"
    if change == "cutoff":
        payment["effective_date"] = "2026-11-15"
    if change == "version":
        newer = duplicate_record(data, "payment", "newer", version=2)
        newer["record_id"] = "payment"
        decision(data, "select_version", "payment", selected_id="newer")
    if change == "contractor":
        payment["contractor_id"] = "other-builder"
    normalized, result = run(data)
    assert result.net_allocations_cents == 0
    assert "ALLOCATION_ENDPOINT_UNRESOLVED" in {q.code for q in normalized.questions}


def test_refund_to_unresolved_original_allocation_is_provisional():
    data = payload("REFUND")
    row(data, "a1")["relationship_review"] = "proposed"
    normalized, result = run(data)
    assert "REFUND_ALLOCATION_UNRESOLVED" in {q.code for q in normalized.questions}
    assert result.net_allocations_cents == 0


def test_allocation_review_rejection_and_decisions_are_applied_without_changing_cash():
    data = payload("PARTIAL")
    row(data, "a1")["relationship_review"] = "rejected"
    normalized, result = run(data)
    assert not normalized.incomplete
    assert result.unallocated_cents == 150000
    decision(data, "confirm_semantics", "a2", answer="unknown")
    normalized, result = run(data)
    assert normalized.incomplete
    assert "unallocated_cents" in normalized.incomplete_metrics
    assert "net_paid_cents" not in normalized.incomplete_metrics
    assert result.net_paid_cents == 300000
    assert result.unallocated_cents == 300000


@pytest.mark.parametrize(
    "case,id,changes,code",
    [
        ("FIN-11", "current", {"previous_id": "missing"}, "INVALID_PREVIOUS_BILLING"),
        ("FIN-11", "current", {"starts_at_zero": True}, "INVALID_PREVIOUS_BILLING"),
        ("FIN-11", "current", {"effective_date": "2026-10-01"}, "INVALID_BILLING_ORDER"),
        ("FIN-11", "first", {"starts_at_zero": True}, "INVALID_ZERO_BASELINE"),
        ("FIN-11", "first", {"coverage": ["work", "work"]}, "DUPLICATE_COVERAGE"),
        ("FIN-11", "first", {"amount_cents": -1}, "INVALID_BILLING_DIRECTION"),
        ("CREDIT", "credit", {"credit_target_id": "base"}, "INVALID_CREDIT_TARGET"),
        ("CREDIT", "credit", {"amount_cents": 1}, "INVALID_BILLING_DIRECTION"),
        ("PARTIAL", "a1", {"cash_id": "missing"}, "INVALID_ALLOCATION_REFERENCE"),
        ("PARTIAL", "a1", {"charge_id": "payment"}, "INVALID_ALLOCATION_REFERENCE"),
        (
            "PARTIAL",
            "a1",
            {"reverses_allocation_id": "missing", "amount_cents": -1},
            "INVALID_REFUND_REFERENCE",
        ),
        ("PARTIAL", "a1", {"effective_date": "2026-10-01"}, "INVALID_ALLOCATION_DATE"),
        ("PARTIAL", "a1", {"evidence_refs": ["missing"]}, "UNKNOWN_SOURCE"),
    ],
)
def test_invalid_structured_references_fail_before_result(case, id, changes, code):
    data = payload(case)
    row(data, id).update(changes)
    with pytest.raises(NormalizationError) as error:
        run(data)
    assert error.value.code == code


def test_cumulative_cycles_are_rejected():
    data = payload()
    row(data, "first").update(basis="cumulative_valuation", previous_id="current")
    with pytest.raises(NormalizationError, match="BILLING_CYCLE"):
        run(data)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"amount_cents": 300001}, "exceeds available cash"),
        ({"amount_cents": -1}, "direction"),
        ({"amount_cents": 0}, "direction"),
        ({"reverses_allocation_id": "a2"}, "Only refunds"),
    ],
)
def test_invalid_allocation_amounts_rejected(changes, match):
    data = payload("PARTIAL")
    row(data, "a1").update(changes)
    with pytest.raises(ValidationError, match=match):
        run(data)


@pytest.mark.parametrize(
    "change,match",
    [
        ("over_cash", "exceeds available cash"),
        ("over_original", "exceeds the original allocation"),
        ("missing_original", "must reverse"),
        ("other_charge", "same charge"),
    ],
)
def test_refund_allocation_limits(change, match):
    data = payload("REFUND")
    if change == "over_cash":
        row(data, "r1")["amount_cents"] = -100001
    if change == "over_original":
        row(data, "refund")["amount_cents"] = -1200000
        row(data, "r1")["amount_cents"] = -1200000
    if change == "missing_original":
        row(data, "r1")["reverses_allocation_id"] = None
    if change == "other_charge":
        duplicate_record(data, "invoice", "second", coverage=["another-room"])
        row(data, "r1")["charge_id"] = "second"
    with pytest.raises(ValidationError, match=match):
        run(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_cents", 0.5),
        ("amount_cents", MAX_CENTS + 1),
        ("amount_cents", True),
        ("relationship_actor_id", None),
        ("relationship_reviewed_at", None),
    ],
)
def test_strict_cents_and_independent_relationship_audit(field, value):
    data = payload("PARTIAL")
    row(data, "a1")[field] = value
    with pytest.raises(ValidationError):
        run(data)


@pytest.mark.parametrize(
    "target,field,value,match",
    [
        ("allocations", "cash_event_id", "missing", "completed cash"),
        ("allocations", "charge_id", "missing", "existing charge"),
        ("cash_events", "state", "pending", "completed cash"),
        ("billing_credits", "charge_id", "missing", "Billing credit"),
        ("billing_credits", "amount_cents", 1, "Billing credit"),
    ],
)
def test_direct_ledger_cannot_bypass_validation(target, field, value, match):
    normalized, _ = run(payload("CREDIT" if target == "billing_credits" else "OVERPAID"))
    data = normalized.ledger_input.model_dump(mode="json")
    data[target][0][field] = value
    with pytest.raises(ValidationError, match=match):
        LedgerInput.model_validate_json(json.dumps(data))


def test_billing_aggregate_overflow_rejected():
    data = payload("PARTIAL")
    row(data, "first")["amount_cents"] = MAX_CENTS
    row(data, "second")["amount_cents"] = MAX_CENTS
    with pytest.raises(ValidationError):
        run(data)


@pytest.mark.parametrize("case", ["FIN-11", "FIN-13", "PARTIAL", "REFUND"])
def test_cli_billing_examples(case):
    output = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.normalize_cli",
            "--fixtures",
            "fixtures/billing_cases.json",
            "--case",
            case,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(output.stdout)
    assert result["calculation"] == run(payload(case))[1].model_dump(mode="json")


def test_two_cumulative_branches_are_not_added_as_independent_work():
    data = payload()
    duplicate_record(data, "current", "branch", amount_cents=1400000)
    normalized, result = run(data)
    assert result.billed_total_cents == 500000
    assert "BILLING_COVERAGE_OVERLAP" in {q.code for q in normalized.questions}


@pytest.mark.parametrize("id", ["first", "allocation"])
def test_billing_and_allocation_versions_require_explicit_selection(id):
    data = payload()
    newer = duplicate_record(data, id, "revision2", version=2)
    newer["record_id"] = id
    unresolved, _ = run(data)
    assert "RECORD_VERSION_CONFLICT" in {q.code for q in unresolved.questions}
    decision(data, "select_version", id, selected_id=id)
    accepted, result = run(data)
    assert not accepted.incomplete
    assert result.positive_outstanding_cents == 1050000
    allocation = accepted.ledger_input.allocations[0]
    assert "source:decision-0" in allocation.evidence_refs
    data["records"].reverse()
    data["decisions"].reverse()
    assert run(data) == (accepted, result)


def test_billing_does_not_require_known_contract_baseline():
    data = payload()
    data["records"] = [r for r in data["records"] if r["id"] != "base"]
    _, result = run(data)
    assert result.remaining_commitment_cents is None
    assert result.billed_total_cents == 1350000


@pytest.mark.parametrize("id", ["a1", "first"])
def test_new_record_cutoff_keeps_other_dimensions_unchanged(id):
    data = payload("PARTIAL")
    row(data, id)["effective_date"] = "2026-11-15"
    normalized, result = run(data)
    assert any(d.record.id == id and d.reason == "AFTER_CUTOFF" for d in normalized.excluded)
    assert result.net_allocations_cents == 150000
    assert result.net_paid_cents == 300000


@pytest.mark.parametrize(
    "case,id,date,code",
    [
        ("CREDIT", "credit", "2026-10-31", "INVALID_CREDIT_DATE"),
        ("REFUND", "a1", "2026-11-12", "INVALID_REFUND_ALLOCATION_DATE"),
    ],
)
def test_credit_and_refund_relationship_dates(case, id, date, code):
    data = payload(case)
    row(data, id)["effective_date"] = date
    with pytest.raises(NormalizationError, match=code):
        run(data)


def test_multiple_refunds_cannot_reverse_the_same_allocation_twice():
    data = payload("REFUND")
    row(data, "a1")["amount_cents"] = 100000
    duplicate_record(data, "refund", "refund2", bank_transaction_id="refund2")
    duplicate_record(data, "r1", "r2", cash_id="refund2")
    with pytest.raises(ValidationError, match="exceeds the original allocation"):
        run(data)


@given(st.integers(min_value=1, max_value=100000))
def test_partial_refunds_preserve_each_cash_event(amount):
    data = payload("REFUND")
    row(data, "r1")["amount_cents"] = -amount
    _, result = run(data)
    assert result.unallocated_cents == amount - 100000
    assert result.credit_balance_cents == 100000 - amount
    assert_conservation(result)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"amount_cents": -1}, "direction"),
        ({"reverses_allocation_id": "record:a1"}, "Only refunds"),
    ],
)
def test_direct_ledger_rejects_allocation_direction(changes, match):
    normalized, _ = run(payload("OVERPAID"))
    data = normalized.ledger_input.model_dump(mode="json")
    data["allocations"][0].update(changes)
    with pytest.raises(ValidationError, match=match):
        LedgerInput.model_validate_json(json.dumps(data))


def test_unknown_allocation_amount_is_not_zero():
    data = payload("PARTIAL")
    row(data, "a1")["amount_cents"] = None
    normalized, result = run(data)
    assert "MISSING_AMOUNT" in {q.code for q in normalized.questions}
    assert result.unallocated_cents == 150000


def test_cli_invalid_allocation_has_no_financial_output(tmp_path):
    data = payload("PARTIAL")
    row(data, "a1")["amount_cents"] = 300001
    input_file = tmp_path / "invalid.json"
    input_file.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.normalize_cli",
            "--input",
            str(input_file),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "exceeds available cash" in result.stderr
