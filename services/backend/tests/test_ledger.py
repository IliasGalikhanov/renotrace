import json
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.ledger import MAX_CENTS, AmountRecord, CashEvent, LedgerInput, calculate
from app.reference_cases import reference_input

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "fixtures/ledger_cases.json").read_text(encoding="utf-8"))["cases"]


def record(amount=10_000, id="base"):
    return AmountRecord(id=id, amount_cents=amount, evidence_refs=("source:1",), origin="document")


def cash(amount=2_000, id="cash", state="completed"):
    return CashEvent(
        id=id, amount_cents=amount, evidence_refs=("source:2",), origin="bank_record", state=state
    )


def history(**changes):
    return LedgerInput(
        **{
            "case_id": "case-1",
            "case_revision": 1,
            "agreement": record(),
            "cash_events": (),
            "requested_now_cents": None,
            **changes,
        }
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_financial_reference_case_uses_actual_ledger(case):
    result = calculate(reference_input(case))
    for field, expected in case["expected"].items():
        assert getattr(result, field) == expected
    assert result.requested_now_cents == case["normalized"]["requested_now_cents"]
    assert result.completed_outgoing_cents - result.completed_refunds_cents == result.net_paid_cents


def test_fin_01_acceptance_values_and_provenance():
    result = calculate(reference_input(CASES[0]))
    assert result.commitment_total_cents == 1_270_000
    assert result.net_paid_cents == 800_000
    assert result.remaining_commitment_cents == 470_000
    assert result.requested_now_cents == 550_000
    assert len(result.commitment_record_ids) == 3
    assert len(result.completed_cash_record_ids) == 2


@pytest.mark.parametrize("state", ["pending", "scheduled", "failed", "reversed"])
@pytest.mark.parametrize("amount", [2_000, -2_000])
def test_noncompleted_outgoing_or_refund_never_changes_paid(state, amount):
    result = calculate(history(cash_events=(cash(3_000, "paid"), cash(amount, "excluded", state))))
    assert result.net_paid_cents == 3_000
    assert result.remaining_commitment_cents == 7_000
    assert result.completed_cash_record_ids == ("paid",)
    assert result.excluded_cash_record_ids == ("excluded",)


def test_refund_changes_paid_not_commitment():
    result = calculate(history(cash_events=(cash(11_000, "payment"), cash(-1_000, "refund"))))
    assert result.commitment_total_cents == 10_000
    assert result.completed_outgoing_cents == 11_000
    assert result.completed_refunds_cents == 1_000
    assert result.net_paid_cents == 10_000
    assert result.remaining_commitment_cents == 0


def test_unknown_base_remains_unknown_even_with_known_adjustments():
    result = calculate(history(agreement=None, adjustments=(record(500, "change"),)))
    assert result.commitment_total_cents is None
    assert result.remaining_commitment_cents is None
    assert result.commitment_record_ids == ()


def test_known_zero_base_is_not_unknown_and_negative_balance_is_retained():
    result = calculate(history(agreement=record(0), cash_events=(cash(100),)))
    assert result.commitment_total_cents == 0
    assert result.remaining_commitment_cents == -100


def test_genuine_equal_payments_remain_separate():
    result = calculate(history(cash_events=(cash(3_000, "tx1"), cash(3_000, "tx2"))))
    assert result.net_paid_cents == 6_000
    assert result.completed_cash_record_ids == ("tx1", "tx2")


@pytest.mark.parametrize("location", ["agreement", "adjustment", "cash", "request"])
@pytest.mark.parametrize(
    "invalid", [True, False, 1.0, 1.5, "100", Decimal("1"), MAX_CENTS + 1, -MAX_CENTS - 1]
)
def test_money_is_strict_integer_cents_with_bounds(location, invalid):
    with pytest.raises(ValidationError):
        match location:
            case "agreement":
                history(agreement=record(invalid))
            case "adjustment":
                history(adjustments=(record(invalid, "adjustment"),))
            case "cash":
                history(cash_events=(cash(invalid),))
            case "request":
                history(requested_now_cents=invalid)


@pytest.mark.parametrize("amount", [-MAX_CENTS, 0, MAX_CENTS])
def test_exact_range_boundaries(amount):
    result = calculate(history(agreement=record(amount), requested_now_cents=amount))
    assert result.remaining_commitment_cents == amount
    assert result.requested_now_cents == amount


@pytest.mark.parametrize(
    "changes",
    [
        {"agreement": record(MAX_CENTS), "adjustments": (record(1, "delta"),)},
        {"agreement": record(-MAX_CENTS), "adjustments": (record(-1, "delta"),)},
        {"cash_events": (cash(MAX_CENTS, "one"), cash(1, "two"))},
        {"cash_events": (cash(-MAX_CENTS, "one"), cash(-1, "two"))},
        {"agreement": record(MAX_CENTS), "cash_events": (cash(-1),)},
        {"agreement": record(-MAX_CENTS), "cash_events": (cash(1),)},
    ],
)
def test_out_of_range_aggregates_are_rejected(changes):
    with pytest.raises(ValidationError):
        calculate(history(**changes))


def test_intermediate_integer_sum_is_exact_and_order_independent():
    first = history(agreement=record(MAX_CENTS), adjustments=(record(1, "a"), record(-1, "b")))
    second = history(agreement=record(MAX_CENTS), adjustments=tuple(reversed(first.adjustments)))
    assert calculate(first) == calculate(second)
    assert calculate(first).commitment_total_cents == MAX_CENTS


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "EUR"},
        {"case_revision": True},
        {"case_revision": -1},
        {"case_id": " "},
        {"unexpected": 1},
        {"adjustments": (record(1),)},
        {"cash_events": (cash(id="base"),)},
        {"cash_events": (cash(id="same"), cash(id="same"))},
    ],
)
def test_invalid_context_or_duplicate_record_ids_are_rejected(changes):
    with pytest.raises(ValidationError):
        history(**changes)


def test_empty_evidence_unknown_state_missing_money_are_rejected():
    with pytest.raises(ValidationError):
        AmountRecord(id="r", amount_cents=100, evidence_refs=(), origin="document")
    with pytest.raises(ValidationError):
        cash(state="unknown")
    with pytest.raises(ValidationError):
        cash(amount=None)


def test_json_input_validation_and_null_output():
    raw = history(agreement=None).model_dump_json()
    result = calculate(LedgerInput.model_validate_json(raw))
    assert json.loads(result.model_dump_json())["remaining_commitment_cents"] is None
    payload = json.loads(raw)
    payload["requested_now_cents"] = 1.5
    with pytest.raises(ValidationError):
        LedgerInput.model_validate_json(json.dumps(payload))


def test_inputs_are_immutable_and_plain_dict_is_not_calculable():
    value = history()
    before = value.model_dump_json()
    assert calculate(value) == calculate(value)
    assert value.model_dump_json() == before
    with pytest.raises(ValidationError):
        value.case_revision = 2
    with pytest.raises(TypeError):
        calculate({})


@given(
    adjustments=st.lists(st.integers(-100_000, 100_000), max_size=12),
    cash_amounts=st.lists(st.integers(-100_000, 100_000), max_size=12),
    data=st.data(),
)
def test_record_order_does_not_change_result_or_fingerprint(adjustments, cash_amounts, data):
    terms = tuple(record(v, f"change-{i}") for i, v in enumerate(adjustments))
    events = tuple(cash(v, f"cash-{i}") for i, v in enumerate(cash_amounts))
    original = history(adjustments=terms, cash_events=events)
    reordered = history(
        adjustments=tuple(data.draw(st.permutations(terms))),
        cash_events=tuple(data.draw(st.permutations(events))),
    )
    assert calculate(original) == calculate(reordered)


@given(
    base=st.integers(-1_000_000, 1_000_000),
    paid=st.integers(-1_000_000, 1_000_000),
    request=st.one_of(st.none(), st.integers(-MAX_CENTS, MAX_CENTS)),
)
def test_requested_amount_does_not_change_financial_totals(base, paid, request):
    original = calculate(history(agreement=record(base), cash_events=(cash(paid),)))
    changed = calculate(
        history(agreement=record(base), cash_events=(cash(paid),), requested_now_cents=request)
    )
    assert changed.commitment_total_cents == original.commitment_total_cents
    assert changed.net_paid_cents == original.net_paid_cents
    assert changed.remaining_commitment_cents == original.remaining_commitment_cents
    assert changed.requested_now_cents == request


def test_evidence_order_is_canonical_but_changed_source_changes_fingerprint():
    def input_with_refs(refs):
        return history(
            agreement=AmountRecord(
                id="base", amount_cents=100, evidence_refs=refs, origin="document"
            )
        )

    first = calculate(input_with_refs(("page1", "page2")))
    assert first == calculate(input_with_refs(("page2", "page1")))
    assert first.input_fingerprint != calculate(input_with_refs(("page3",))).input_fingerprint
