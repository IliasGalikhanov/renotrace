import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.ledger import MAX_CENTS, calculate
from app.normalization import HistoryInput, NormalizationError, normalize

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "fixtures/normalization_cases.json").read_text(encoding="utf-8"))[
    "cases"
]
AT = "2026-11-14T10:00:00Z"


def payload(case_id="FIN-01"):
    return copy.deepcopy(next(case["input"] for case in CASES if case["id"] == case_id))


def row(data, id):
    return next(record for record in data["records"] if record["id"] == id)


def run(data):
    normalized = normalize(HistoryInput.model_validate_json(json.dumps(data)))
    assert_unresolved_cash_has_question(normalized)
    return normalized, calculate(normalized.ledger_input)


def assert_unresolved_cash_has_question(normalized):
    metrics = {"net_paid_cents", "remaining_commitment_cents"}
    for entry in normalized.excluded:
        if entry.reason == "UNRESOLVED_TRANSACTION":
            assert normalized.incomplete
            assert metrics <= set(normalized.incomplete_metrics)
            assert any(
                entry.record.id in question.record_ids and metrics <= set(question.affects)
                for question in normalized.questions
            ), f"Unresolved cash {entry.record.id} has no question covering paid and remaining"


def codes(result):
    return {question.code for question in result.questions}


def decision(data, kind, target, **values):
    id = values.pop("id", "decision-" + str(len(data["decisions"])))
    source_id = "source:" + id
    data["sources"].append(
        {
            "id": source_id,
            "case_id": data["case_id"],
            "version": 1,
            "origin": "user_statement",
            "locator": "synthetic:decision",
            "actor_id": "owner-1",
        }
    )
    value = {
        "id": id,
        "kind": kind,
        "target_id": target,
        "basis_revision": data["case_revision"],
        "actor_id": "owner-1",
        "decided_at": AT,
        "evidence_refs": [source_id],
        **values,
    }
    data["decisions"].append(value)
    return value


def duplicate_record(data, original, new_id, **changes):
    copied = copy.deepcopy(row(data, original))
    copied.update(id=new_id, record_id=new_id, **changes)
    data["records"].append(copied)
    return copied


@pytest.mark.parametrize("case", CASES, ids=lambda value: value["id"])
def test_structured_scenarios_normalize_then_calculate(case):
    normalized, result = run(case["input"])
    for field, expected in case["expected"].items():
        assert getattr(result, field) == expected
    assert codes(normalized) == set(case["expected_question_codes"])
    assert normalized.incomplete == bool(case["expected_question_codes"])
    included = {entry.record.id for entry in normalized.included}
    excluded = {entry.record.id for entry in normalized.excluded}
    assert included.isdisjoint(excluded)
    assert included | excluded == {record["id"] for record in case["input"]["records"]}
    sources = {source.id for source in normalized.sources}
    for entry in (*normalized.included, *normalized.excluded):
        assert set(entry.evidence_refs) <= sources
    for event in normalized.ledger_input.cash_events:
        assert set(event.evidence_refs) <= sources
    if normalized.ledger_input.agreement is not None:
        assert set(normalized.ledger_input.agreement.evidence_refs) <= sources


def test_deposit_mention_alone_does_not_create_cash():
    data = payload("FIN-02")
    data["records"] = [record for record in data["records"] if record["kind"] != "cash"]
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert result.remaining_commitment_cents == 1_000_000
    assert result.requested_now_cents == 700_000
    assert not normalized.ledger_input.cash_events


def test_included_change_and_replacement_reasons():
    normalized, result = run(payload("FIN-03"))
    assert result.commitment_total_cents == 1_350_000
    assert not normalized.ledger_input.adjustments
    reasons = {entry.record.id: entry.reason for entry in normalized.excluded}
    assert reasons["estimate-v1"] == "SUPERSEDED"
    assert reasons["extra"] == "INCLUDED_IN_BASE"
    assert {
        "source:estimate-v2",
        "source:included-work",
        "source:extra",
        "source:replacement",
    } <= set(normalized.ledger_input.agreement.evidence_refs)


@pytest.mark.parametrize(
    "answer,total", [("accept", 1_350_000), ("reject", 1_500_000), ("unknown", 1_350_000)]
)
def test_inclusion_decision_changes_terms_without_double_counting(answer, total):
    data = payload("FIN-03")
    decision(data, "review_link", "included-work", answer=answer)
    normalized, result = run(data)
    assert result.commitment_total_cents == total
    assert ("ADJUSTMENT_INCLUSION_UNRESOLVED" in codes(normalized)) == (answer == "unknown")


@pytest.mark.parametrize(
    "contractor,paid", [("contractor-1", 500_000), ("other", 300_000), (None, 300_000)]
)
def test_explicit_recipient_decision_recalculates_real_ledger(contractor, paid):
    data = payload("FIN-16")
    d = decision(data, "assign_contractor", "unknown", contractor_id=contractor)
    normalized, result = run(data)
    assert result.net_paid_cents == paid
    assert result.remaining_commitment_cents == 1_000_000 - paid
    assert ("UNRESOLVED_RECIPIENT" in codes(normalized)) == (contractor is None)
    assert d["id"] in {item.id for item in normalized.applied_decisions}
    for item in normalized.included:
        if item.record.id == "unknown":
            assert item.record.contractor_id is None
            assert item.effective_contractor_id == contractor
            assert d["evidence_refs"][0] in item.evidence_refs


@pytest.mark.parametrize(
    "answer,paid", [("accept", 800_000), ("reject", 300_000), ("unknown", 300_000)]
)
def test_semantic_decision_does_not_claim_extraction_checked(answer, paid):
    data = payload()
    decision(data, "confirm_semantics", "payment-1", answer=answer)
    normalized, result = run(data)
    assert result.net_paid_cents == paid
    entry = next(
        item
        for item in (*normalized.included, *normalized.excluded)
        if item.record.id == "payment-1"
    )
    assert entry.record.review.extraction_review == "unreviewed"
    assert entry.record.origin == "bank_record"
    assert entry.effective_semantic_review == ("user_asserted" if answer == "accept" else "unknown")


def test_unknown_semantics_needs_review_and_checked_extraction_is_independent():
    data = payload()
    row(data, "base")["review"] = {
        "extraction_review": "checked",
        "extraction_actor_id": "reader",
        "extraction_reviewed_at": AT,
    }
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "SEMANTIC_REVIEW_REQUIRED" in codes(normalized)


@pytest.mark.parametrize(
    "kind,target,values",
    [
        (
            "assign_contractor",
            "payment-1",
            [{"contractor_id": "contractor-1"}, {"contractor_id": "other"}],
        ),
        ("confirm_semantics", "payment-1", [{"answer": "accept"}, {"answer": "reject"}]),
        ("select_agreement", "FIN-01", [{"selected_id": "base"}, {"selected_id": None}]),
        ("select_version", "base", [{"selected_id": "base"}, {"selected_id": None}]),
    ],
)
def test_conflicting_current_decisions_block_their_scope(kind, target, values):
    data = payload()
    for value in values:
        decision(data, kind, target, **value)
    normalized, result = run(data)
    assert "DECISION_CONFLICT" in codes(normalized)
    if target == "payment-1":
        assert result.net_paid_cents == 300_000
    else:
        assert result.commitment_total_cents is None


def test_conflicting_link_decisions_do_not_choose_last():
    data = payload("FIN-03")
    decision(data, "review_link", "replacement", answer="accept")
    decision(data, "review_link", "replacement", answer="reject")
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "DECISION_CONFLICT" in codes(normalized)


def test_stale_decision_blocks_scope_but_current_decision_can_replace_it():
    data = payload("FIN-16")
    d = decision(
        data, "assign_contractor", "unknown", contractor_id="contractor-1", basis_revision=0
    )
    normalized, result = run(data)
    assert result.net_paid_cents == 300_000
    assert "STALE_DECISION" in codes(normalized)
    decision(data, "assign_contractor", "unknown", contractor_id="contractor-1")
    normalized, result = run(data)
    assert result.net_paid_cents == 500_000
    assert "STALE_DECISION" not in codes(normalized)
    assert d["id"] not in {item.id for item in normalized.applied_decisions}


def test_duplicate_identical_decisions_are_consistent_and_keep_both_sources():
    data = payload("FIN-16")
    first = decision(data, "assign_contractor", "unknown", contractor_id="contractor-1")
    second = decision(data, "assign_contractor", "unknown", contractor_id="contractor-1")
    normalized, result = run(data)
    assert result.net_paid_cents == 500_000
    entry = next(item for item in normalized.included if item.record.id == "unknown")
    assert set(entry.decision_ids) == {first["id"], second["id"]}


@pytest.mark.parametrize(
    "selection,total", [("estimate-v1", 1_200_000), ("estimate-v2", 1_350_000), (None, None)]
)
@pytest.mark.parametrize("kind", ["select_version", "select_agreement"])
def test_explicit_estimate_selection_resolves_proposed_versions(kind, selection, total):
    data = payload("NORM-VERSION-CONFLICT")
    target = "estimate" if kind == "select_version" else data["case_id"]
    decision(data, kind, target, selected_id=selection)
    normalized, result = run(data)
    assert result.commitment_total_cents == total
    assert normalized.incomplete == (selection is None)


def test_selection_of_replaced_or_future_agreement_does_not_resurrect_it():
    data = payload("FIN-03")
    decision(data, "select_agreement", data["case_id"], selected_id="estimate-v1")
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "AGREEMENT_SELECTION_REQUIRED" in codes(normalized)
    data = payload("NORM-VERSION-CONFLICT")
    row(data, "estimate-v2")["effective_date"] = "2026-12-01"
    decision(data, "select_version", "estimate", selected_id="estimate-v2")
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "VERSION_SELECTION_REQUIRED" in codes(normalized)


def test_multiple_cash_revisions_require_selection():
    data = payload("FIN-07")
    second = duplicate_record(data, "paid", "paid-v2", version=2)
    second["record_id"] = row(data, "paid")["record_id"]
    second["amount_cents"] = 400_000
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert "RECORD_VERSION_CONFLICT" in codes(normalized)
    decision(data, "select_version", "paid", selected_id="paid-v2")
    normalized, result = run(data)
    assert result.net_paid_cents == 400_000
    assert "RECORD_VERSION_CONFLICT" not in codes(normalized)


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_cents", 200_000),
        ("state", "pending"),
        ("effective_date", "2026-11-15"),
        ("contractor_id", "other"),
    ],
)
def test_conflicting_bank_observations_are_not_silently_deduplicated(field, value):
    data = payload("FIN-08")
    row(data, "import-b")[field] = value
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert "TRANSACTION_CONFLICT" in codes(normalized)


def test_account_context_prevents_false_bank_deduplication():
    data = payload("FIN-08")
    row(data, "import-b")["bank_account_id"] = "another-bank/account-1"
    normalized, result = run(data)
    assert result.net_paid_cents == 600_000
    assert len(normalized.ledger_input.cash_events) == 2


def test_equal_amount_without_stable_bank_identity_is_not_merged():
    data = payload("FIN-09")
    for record in data["records"]:
        record.pop("bank_account_id", None)
        record.pop("bank_transaction_id", None)
    normalized, result = run(data)
    assert result.net_paid_cents == 600_000
    assert len(normalized.ledger_input.cash_events) == 2


def test_additional_import_does_not_create_new_canonical_cash_event():
    data = payload("FIN-08")
    before, before_result = run(data)
    duplicate_record(data, "import-a", "aaa-new-import")
    after, after_result = run(data)
    assert after.ledger_input.cash_events == before.ledger_input.cash_events
    assert after_result == before_result
    assert sum(item.reason == "DUPLICATE_BANK_OPERATION" for item in after.excluded) == 2


def test_conflicting_or_unreviewed_member_cannot_be_hidden_by_valid_duplicate():
    data = payload("FIN-08")
    row(data, "import-b")["review"] = {}
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert "SEMANTIC_REVIEW_REQUIRED" in codes(normalized)
    assert {entry.reason for entry in normalized.excluded} == {
        "UNREVIEWED_SEMANTICS",
        "UNRESOLVED_TRANSACTION",
    }


@pytest.mark.parametrize("state", ["pending", "scheduled", "failed", "reversed"])
def test_uncompleted_refund_is_not_paid_back(state):
    data = payload("FIN-04")
    row(data, "refund")["state"] = state
    _, result = run(data)
    assert result.net_paid_cents == 1_100_000
    assert result.remaining_commitment_cents == -100_000


def test_manual_origin_and_review_fields_survive_normalization():
    normalized, _ = run(payload("NORM-MANUAL"))
    assert normalized.ledger_input.cash_events[0].origin == "user_statement"
    manual = next(entry for entry in normalized.included if entry.record.id == "manual")
    assert manual.record.review.semantic_actor_id == "reviewer-1"
    assert manual.record.review.extraction_review == "unreviewed"


@pytest.mark.parametrize("id", ["base", "extra", "payment-1", "invoice"])
def test_cutoff_excludes_every_financial_kind(id):
    data = payload()
    row(data, id)["effective_date"] = "2026-11-15"
    normalized, result = run(data)
    assert any(
        item.record.id == id and item.reason == "AFTER_CUTOFF" for item in normalized.excluded
    )
    if id == "base":
        assert result.commitment_total_cents is None
    elif id == "extra":
        assert result.commitment_total_cents == 1_120_000
    elif id == "payment-1":
        assert result.net_paid_cents == 300_000
    else:
        assert result.requested_now_cents is None
        assert "CURRENT_REQUEST_UNRESOLVED" in codes(normalized)


@pytest.mark.parametrize("lifecycle", ["void", "stale", "superseded"])
def test_inactive_records_are_explicitly_excluded(lifecycle):
    data = payload()
    row(data, "payment-1")["review"]["lifecycle"] = lifecycle
    normalized, result = run(data)
    assert result.net_paid_cents == 300_000
    assert any(
        item.record.id == "payment-1" and item.reason == "INACTIVE_RECORD"
        for item in normalized.excluded
    )


@pytest.mark.parametrize("id", ["base", "extra", "payment-1", "invoice"])
def test_unknown_amount_never_becomes_zero(id):
    data = payload()
    row(data, id)["amount_cents"] = None
    normalized, _ = run(data)
    assert "MISSING_AMOUNT" in codes(normalized)
    assert any(
        item.record.id == id and item.reason == "UNKNOWN_AMOUNT" for item in normalized.excluded
    )


def test_noncurrent_invoice_does_not_change_requested_or_cash():
    data = payload("FIN-02")
    duplicate_record(data, "invoice", "other-invoice", amount_cents=9_999)
    normalized, result = run(data)
    assert result.requested_now_cents == 700_000
    assert result.net_paid_cents == 300_000
    assert any(item.reason == "NOT_CURRENT_REQUEST" for item in normalized.excluded)


@given(st.sampled_from(CASES), st.data())
def test_all_input_collection_orders_and_repeated_processing_are_stable(case, random):
    data = copy.deepcopy(case["input"])
    # Exercise real decision permutations as well as record/source/link permutations.
    for record in data["records"][:2]:
        decision(data, "confirm_semantics", record["id"], answer="accept")
    first, first_calculation = run(data)
    for key in ("records", "sources", "links", "decisions"):
        data[key] = list(random.draw(st.permutations(data[key])))
    repeated, repeated_calculation = run(data)
    assert repeated == first
    assert repeated_calculation == first_calculation
    assert run(data) == (repeated, repeated_calculation)


def test_decision_order_is_stable_and_input_is_immutable():
    data = payload("FIN-16")
    decision(data, "assign_contractor", "unknown", contractor_id="contractor-1")
    decision(data, "confirm_semantics", "unknown", answer="accept")
    typed = HistoryInput.model_validate_json(json.dumps(data))
    original = typed.model_dump_json()
    first = normalize(typed)
    assert typed.model_dump_json() == original
    data["decisions"].reverse()
    assert run(data)[0] == first


def test_empty_history_has_unknown_base_not_zero():
    data = payload("FIN-06")
    data.update(records=[], sources=[], current_request_id=None)
    normalized, result = run(data)
    assert result.remaining_commitment_cents is None
    assert result.net_paid_cents == 0
    assert codes(normalized) == {"MISSING_AGREEMENT"}


@pytest.mark.parametrize("case_id", ["FIN-01", "FIN-02", "FIN-03", "FIN-08"])
def test_cli_executes_structured_pipeline(case_id):
    process = subprocess.run(
        [sys.executable, "-m", "app.normalize_cli", "--case", case_id],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    expected = next(case["expected"] for case in CASES if case["id"] == case_id)
    for field, value in expected.items():
        assert result["calculation"][field] == value
    assert result["normalization"]["included"]


def test_cli_input_mode_and_invalid_links_fail_without_result(tmp_path):
    data = payload("FIN-03")
    path = tmp_path / "history.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cmd = [sys.executable, "-m", "app.normalize_cli", "--input", str(path)]
    good = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert good.returncode == 0
    data["links"][0]["to_id"] = "missing"
    path.write_text(json.dumps(data), encoding="utf-8")
    bad = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert bad.returncode == 2
    assert "UNKNOWN_RECORD" in bad.stderr
    assert not bad.stdout


@pytest.mark.parametrize("args", [["--case", "missing"], ["--fixtures", "missing.json"]])
def test_cli_invalid_case_and_missing_file(args):
    process = subprocess.run(
        [sys.executable, "-m", "app.normalize_cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 2
    assert not process.stdout


@pytest.mark.parametrize("collection", ["sources", "records", "links", "decisions"])
def test_duplicate_object_ids_are_rejected_before_calculation(collection):
    data = payload("FIN-03")
    decision(data, "review_link", "replacement", answer="accept")
    data[collection].append(copy.deepcopy(data[collection][0]))
    with pytest.raises(NormalizationError, match="DUPLICATE_ID"):
        run(data)


@pytest.mark.parametrize("collection", ["records", "links", "decisions"])
def test_dangling_evidence_reference_is_rejected_even_for_unused_record(collection):
    data = payload("FIN-03")
    decision(data, "review_link", "replacement", answer="accept")
    data[collection][0]["evidence_refs"] = ["missing-source"]
    if collection == "records":
        data[collection][0]["review"]["lifecycle"] = "void"
    with pytest.raises(NormalizationError, match="UNKNOWN_SOURCE"):
        run(data)


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("duplicate_version", "DUPLICATE_VERSION"),
        ("kind_change", "RECORD_KIND_CONFLICT"),
        ("cross_case", "CROSS_CASE_SOURCE"),
        ("origin", "ORIGIN_SOURCE_MISMATCH"),
        ("unknown_record", "UNKNOWN_RECORD"),
        ("link_kind", "INVALID_LINK_KIND"),
        ("self_cycle", "REPLACEMENT_CYCLE"),
        ("cycle", "REPLACEMENT_CYCLE"),
        ("reversed_dates", "INVALID_REPLACEMENT_ORDER"),
        ("reversed_versions", "INVALID_REPLACEMENT_ORDER"),
        ("duplicate_relation", "DUPLICATE_RELATION"),
        ("unknown_request", "INVALID_CURRENT_REQUEST"),
        ("wrong_request_kind", "INVALID_CURRENT_REQUEST"),
    ],
)
def test_structural_errors_are_explicit(problem, expected):
    data = payload("FIN-03")
    match problem:
        case "duplicate_version":
            row(data, "estimate-v2")["version"] = 1
        case "kind_change":
            row(data, "estimate-v2")["kind"] = "adjustment"
        case "cross_case":
            data["sources"][0]["case_id"] = "another-case"
        case "origin":
            row(data, "estimate-v1")["origin"] = "bank_record"
        case "unknown_record":
            data["links"][0]["to_id"] = "missing"
        case "link_kind":
            data["links"][0]["from_id"] = "payment"
        case "self_cycle":
            data["links"][0]["to_id"] = "estimate-v2"
        case "cycle":
            backward = copy.deepcopy(data["links"][0])
            backward.update(id="cycle", from_id="estimate-v1", to_id="estimate-v2")
            data["links"].append(backward)
        case "reversed_dates":
            row(data, "estimate-v2")["effective_date"] = "2026-10-01"
        case "reversed_versions":
            row(data, "estimate-v1")["version"] = 3
        case "duplicate_relation":
            duplicate = copy.deepcopy(data["links"][0])
            duplicate.update(id="other-link", review="rejected")
            data["links"].append(duplicate)
        case "unknown_request":
            data["current_request_id"] = "missing"
        case "wrong_request_kind":
            data["current_request_id"] = "payment"
    with pytest.raises(NormalizationError) as failure:
        run(data)
    assert failure.value.code == expected


@pytest.mark.parametrize(
    "kind,target,values,code",
    [
        ("select_version", "missing", {"selected_id": None}, "INVALID_VERSION_SELECTION"),
        ("select_version", "base", {"selected_id": "missing"}, "INVALID_VERSION_SELECTION"),
        ("select_version", "base", {"selected_id": "payment-1"}, "INVALID_VERSION_SELECTION"),
        (
            "select_agreement",
            "another-case",
            {"selected_id": "base"},
            "INVALID_AGREEMENT_SELECTION",
        ),
        ("select_agreement", "FIN-01", {"selected_id": "payment-1"}, "INVALID_AGREEMENT_SELECTION"),
        ("select_agreement", "FIN-01", {"selected_id": "missing"}, "INVALID_AGREEMENT_SELECTION"),
        ("assign_contractor", "missing", {"contractor_id": "contractor-1"}, "UNKNOWN_RECORD"),
        ("confirm_semantics", "missing", {"answer": "accept"}, "UNKNOWN_RECORD"),
        ("review_link", "missing", {"answer": "accept"}, "UNKNOWN_LINK"),
    ],
)
def test_invalid_decision_targets_are_rejected(kind, target, values, code):
    data = payload()
    decision(data, kind, target, **values)
    with pytest.raises(NormalizationError) as failure:
        run(data)
    assert failure.value.code == code


@pytest.mark.parametrize("invalid", [1.5, 1.0, True, "100", MAX_CENTS + 1, -MAX_CENTS - 1])
def test_structured_money_rejects_coercion_and_out_of_range(invalid):
    data = payload()
    row(data, "base")["amount_cents"] = invalid
    with pytest.raises(ValidationError):
        run(data)


@pytest.mark.parametrize(
    "problem",
    [
        "bank_pair",
        "extraction_actor",
        "semantic_actor",
        "link_actor",
        "naive_time",
        "non_utc_time",
        "unsupported_kind",
        "unknown_field",
    ],
)
def test_strict_model_and_audit_fields(problem):
    data = payload("FIN-03")
    match problem:
        case "bank_pair":
            row(data, "payment")["bank_transaction_id"] = "tx"
        case "extraction_actor":
            row(data, "payment")["review"]["extraction_review"] = "checked"
        case "semantic_actor":
            row(data, "payment")["review"]["semantic_actor_id"] = None
        case "link_actor":
            data["links"][0]["actor_id"] = None
        case "naive_time":
            decision(
                data,
                "review_link",
                "replacement",
                answer="accept",
                decided_at="2026-11-14T10:00:00",
            )
        case "non_utc_time":
            row(data, "payment")["review"]["semantic_reviewed_at"] = "2026-11-14T10:00:00+05:00"
        case "unsupported_kind":
            row(data, "payment")["kind"] = "billing_entry"
        case "unknown_field":
            row(data, "payment")["verified"] = True
    with pytest.raises(ValidationError):
        run(data)


def test_untyped_input_is_not_accepted():
    with pytest.raises(TypeError, match="HistoryInput"):
        normalize({})


@pytest.mark.parametrize("review", ["proposed", "invalidated"])
def test_unconfirmed_inclusion_keeps_change_out_and_marks_terms_incomplete(review):
    data = payload("FIN-03")
    data["links"][1]["review"] = review
    normalized, result = run(data)
    assert result.commitment_total_cents == 1_350_000
    assert "ADJUSTMENT_INCLUSION_UNRESOLVED" in codes(normalized)
    assert "commitment_total_cents" in normalized.incomplete_metrics


def test_stale_link_does_not_replace_estimate_until_reconfirmed():
    data = payload("FIN-03")
    data["links"][0]["basis_revision"] = 0
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "STALE_LINK" in codes(normalized)
    decision(data, "review_link", "replacement", answer="accept")
    normalized, result = run(data)
    assert result.commitment_total_cents == 1_350_000
    assert not normalized.incomplete


def test_transitive_replacements_do_not_assume_inherited_change_coverage():
    data = payload("FIN-03")
    newest = duplicate_record(
        data, "estimate-v2", "estimate-v3", version=3, effective_date="2026-11-10"
    )
    newest["record_id"] = "estimate"
    replacement = copy.deepcopy(data["links"][0])
    replacement.update(id="second-replacement", from_id="estimate-v3", to_id="estimate-v2")
    data["links"].append(replacement)
    normalized, result = run(data)
    assert result.commitment_total_cents == 1_350_000
    assert normalized.ledger_input.agreement.id == "record:estimate-v3"
    assert "ADJUSTMENT_INCLUSION_UNRESOLVED" in codes(normalized)
    explicit = copy.deepcopy(data["links"][1])
    explicit.update(id="confirmed-new-inclusion", from_id="estimate-v3")
    data["links"].append(explicit)
    normalized, result = run(data)
    assert result.commitment_total_cents == 1_350_000
    assert not normalized.incomplete


def test_distinct_conflicting_decision_scopes_return_their_decision_ids():
    data = payload("FIN-16")
    for value in ("contractor-1", "other"):
        decision(data, "assign_contractor", "unknown", contractor_id=value)
    for answer in ("accept", "reject"):
        decision(data, "confirm_semantics", "unknown", answer=answer)
    normalized, result = run(data)
    conflicts = [q for q in normalized.questions if q.code == "DECISION_CONFLICT"]
    assert len(conflicts) == 2
    assert {id for q in conflicts for id in q.decision_ids} == {d["id"] for d in data["decisions"]}
    assert result.net_paid_cents == 300_000


def test_mixed_origins_are_not_promoted_to_bank_verified():
    data = payload("FIN-08")
    row(data, "import-b")["origin"] = "user_statement"
    next(source for source in data["sources"] if source["id"] == "source:import-b")["origin"] = (
        "user_statement"
    )
    normalized, result = run(data)
    assert result.net_paid_cents == 300_000
    assert normalized.ledger_input.cash_events[0].origin == "derived"
    assert {
        entry.record.origin
        for entry in (*normalized.included, *normalized.excluded)
        if entry.record.kind == "cash"
    } == {"bank_record", "user_statement"}


def test_cli_refuses_unlabelled_fixture_file(tmp_path):
    path = tmp_path / "unlabelled.json"
    path.write_text('{"synthetic": false, "cases": []}', encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "app.normalize_cli", "--fixtures", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 2
    assert "synthetic" in process.stderr
    assert not process.stdout


def test_version_selection_cannot_contradict_confirmed_replacement():
    data = payload("FIN-03")
    decision(data, "select_version", "estimate", selected_id="estimate-v1")
    normalized, result = run(data)
    assert result.commitment_total_cents is None
    assert "SELECTION_LINK_CONFLICT" in codes(normalized)
    decision(data, "review_link", "replacement", answer="reject")
    normalized, result = run(data)
    assert result.commitment_total_cents == 1_350_000  # old base + standalone change
    assert "SELECTION_LINK_CONFLICT" not in codes(normalized)


@pytest.mark.parametrize("selection", ["absent", "unknown", "conflicting"])
def test_ambiguous_cash_revision_cannot_be_bypassed_by_another_bank_import(selection):
    data = payload("FIN-08")
    revised = duplicate_record(data, "import-a", "import-a-v2", version=2, amount_cents=200_000)
    revised["record_id"] = "import-a"
    if selection != "absent":
        decision(data, "select_version", "import-a", selected_id=None)
    if selection == "conflicting":
        decision(data, "select_version", "import-a", selected_id="import-a")
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert "TRANSACTION_VERSION_UNRESOLVED" in codes(normalized)


@pytest.mark.parametrize("explicit_accept", [False, True])
def test_rejected_bank_confirmation_makes_entire_group_provisional(explicit_accept):
    data = payload("FIN-08")
    if explicit_accept:
        decision(data, "confirm_semantics", "import-a", answer="accept")
    decision(data, "confirm_semantics", "import-b", answer="reject")
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert result.remaining_commitment_cents == 1_000_000
    question = next(q for q in normalized.questions if q.code == "TRANSACTION_REVIEW_CONFLICT")
    assert question.record_ids == ("import-a", "import-b")
    assert set(question.decision_ids) == {d["id"] for d in data["decisions"]}
    assert set(question.affects) == {
        "net_paid_cents",
        "remaining_commitment_cents",
        "charge_balances",
        "positive_outstanding_cents",
        "credit_balance_cents",
        "net_allocations_cents",
        "unallocated_cents",
        "cash_balances",
    }
    assert {entry.record.id: entry.reason for entry in normalized.excluded} == {
        "import-a": "UNRESOLVED_TRANSACTION",
        "import-b": "REJECTED_BY_USER",
    }


def test_payment_review_conflict_is_independent_of_record_and_decision_order():
    data = payload("FIN-08")
    decision(data, "confirm_semantics", "import-a", answer="accept")
    decision(data, "confirm_semantics", "import-b", answer="reject")
    expected = run(data)
    data["records"].reverse()
    data["decisions"].reverse()
    assert run(data) == expected


def test_agreeing_confirmations_clear_question_and_count_payment_once():
    data = payload("FIN-08")
    decision(data, "confirm_semantics", "import-a", answer="accept")
    decision(data, "confirm_semantics", "import-b", answer="reject")
    assert run(data)[0].incomplete
    # A new case revision invalidates the old choices; explicitly reconfirm both.
    data["case_revision"] += 1
    for id in ("import-a", "import-b"):
        decision(data, "confirm_semantics", id, answer="accept")
    normalized, result = run(data)
    assert result.net_paid_cents == 300_000
    assert result.remaining_commitment_cents == 700_000
    assert len(normalized.ledger_input.cash_events) == 1
    assert not normalized.incomplete
    assert not normalized.questions
    assert not normalized.incomplete_metrics


def test_all_confirmations_deliberately_rejected_are_not_an_unresolved_conflict():
    data = payload("FIN-08")
    for id in ("import-a", "import-b"):
        decision(data, "confirm_semantics", id, answer="reject")
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    assert result.remaining_commitment_cents == 1_000_000
    assert {entry.reason for entry in normalized.excluded} == {"REJECTED_BY_USER"}
    assert not normalized.incomplete
    assert not normalized.questions


@pytest.mark.parametrize("review", ["unreviewed", "stale"])
def test_unreviewed_or_stale_confirmation_keeps_group_question(review):
    data = payload("FIN-08")
    decision(data, "confirm_semantics", "import-a", answer="accept")
    if review == "unreviewed":
        row(data, "import-b")["review"] = {}
    else:
        decision(data, "confirm_semantics", "import-b", answer="accept", basis_revision=0)
    normalized, result = run(data)
    assert result.net_paid_cents == 0
    question = next(q for q in normalized.questions if q.code == "TRANSACTION_REVIEW_CONFLICT")
    assert question.record_ids == ("import-a", "import-b")
    assert set(question.decision_ids) == {d["id"] for d in data["decisions"]}
    assert ("STALE_DECISION" if review == "stale" else "SEMANTIC_REVIEW_REQUIRED") in codes(
        normalized
    )


@given(
    st.tuples(
        *[st.sampled_from(["accept", "reject", "unknown", "unreviewed", "stale", "conflicting"])]
        * 2
    )
)
def test_unresolved_transaction_invariant_across_confirmation_combinations(states):
    data = payload("FIN-08")
    for id, state in zip(("import-a", "import-b"), states, strict=True):
        if state == "unreviewed":
            row(data, id)["review"] = {}
        elif state == "stale":
            decision(data, "confirm_semantics", id, answer="accept", basis_revision=0)
        elif state == "conflicting":
            decision(data, "confirm_semantics", id, answer="accept")
            decision(data, "confirm_semantics", id, answer="reject")
        else:
            decision(data, "confirm_semantics", id, answer=state)
    expected = run(data)  # applies the common unresolved-cash invariant
    data["records"].reverse()
    data["decisions"].reverse()
    assert run(data) == expected
