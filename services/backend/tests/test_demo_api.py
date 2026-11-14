import json
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.demo.service import catalog
from app.ledger import calculate
from app.main import app
from app.normalization import HistoryInput, normalize

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def action(answer="contractor", **changes):
    return {"kind": "assign_recipient", "record_id": "unknown", "answer": answer, **changes}


def recalculate(client, actions, scenario="FIN-16"):
    return client.post(f"/api/demo/scenarios/{scenario}/calculate", json={"actions": actions})


def test_catalog_and_no_persistent_routes(client):
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [s["id"] for s in response.json()] == ["FIN-01", "FIN-16", "FIN-11"]
    assert client.get("/api/v1/cases").status_code == 404


@pytest.mark.parametrize(
    "scenario,remaining,requested",
    [
        ("FIN-01", 470000, 550000),
        ("FIN-16", 700000, None),
        ("FIN-11", 1050000, 1050000),
    ],
)
def test_api_calls_real_domain_and_provides_sources(client, scenario, remaining, requested):
    response = client.get(f"/api/demo/scenarios/{scenario}")
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic"] is True and data["persistence"] == "none"
    history = HistoryInput.model_validate_json(json.dumps(data["history"]))
    normalized = normalize(history)
    assert data["normalization"] == normalized.model_dump(mode="json")
    assert data["calculation"] == calculate(normalized.ledger_input).model_dump(mode="json")
    assert data["calculation"]["remaining_commitment_cents"] == remaining
    assert data["calculation"]["requested_now_cents"] == requested
    assert data["conditions"] == {
        "due_date": None,
        "condition_text": None,
        "satisfaction": "unknown",
        "evidence_refs": [],
    }
    registry = {s["id"] for s in data["history"]["sources"]}
    content = {s["source_id"] for s in data["source_contents"]}
    assert registry == content
    assert all(s["title"] and s["excerpt"] for s in data["source_contents"])
    assert set(data["record_titles"]) == {r["id"] for r in data["history"]["records"]}
    for trace in data["traces"].values():
        assert set(trace["source_ids"]) <= registry
        assert set(trace["record_ids"]) <= set(data["record_titles"])
        if trace["amount_cents"]:
            assert trace["source_ids"]


def test_credit_and_cumulative_ancestry(client):
    first = client.get("/api/demo/scenarios/FIN-01").json()
    assert "credit" in first["traces"]["commitment_total_cents"]["record_ids"]
    assert "credit" not in first["traces"]["net_paid_cents"]["record_ids"]
    cumulative = client.get("/api/demo/scenarios/FIN-11").json()
    assert cumulative["traces"]["charge:record:current"]["amount_cents"] == 850000
    assert set(cumulative["traces"]["charge:record:current"]["source_ids"]) == {
        "source:first",
        "source:current",
    }
    assert cumulative["calculation"]["positive_outstanding_cents"] == 1050000
    assert set(cumulative["traces"]["charge:record:current"]["record_ids"]) == {"current", "first"}
    assert set(cumulative["traces"]["balance:record:first"]["record_ids"]) == {
        "first",
        "allocation",
        "payment",
    }


@pytest.mark.parametrize(
    "answer,remaining,incomplete",
    [
        ("contractor", 500000, False),
        ("other", 700000, False),
        ("unknown", 700000, True),
    ],
)
def test_recipient_changes_real_calculation_and_preserves_uncertainty(
    client, answer, remaining, incomplete
):
    response = recalculate(client, [action(answer)])
    assert response.status_code == 200
    data = response.json()
    assert data["calculation"]["remaining_commitment_cents"] == remaining
    assert data["normalization"]["incomplete"] is incomplete
    assert bool(data["normalization"]["questions"]) is incomplete
    assert (
        "remaining_commitment_cents" in data["normalization"]["incomplete_metrics"]
    ) is incomplete
    assert data["history"]["case_revision"] == 2
    assert data["history"]["decisions"][0]["basis_revision"] == 2
    assert data["source_contents"][-1]["source_id"] == "demo-decision:unknown"
    assert "set-cookie" not in response.headers


def test_last_answer_replaces_previous_scope_and_reset(client):
    response = recalculate(client, [action(), action("other"), action("unknown")]).json()
    assert response["actions"] == [action("unknown")]
    assert len(response["history"]["decisions"]) == 1
    assert response["calculation"]["remaining_commitment_cents"] == 700000
    reset = recalculate(client, []).json()
    assert reset == client.get("/api/demo/scenarios/FIN-16").json()


def test_requests_are_isolated_and_never_mutate_bundled_sources(client):
    source = files("app.demo").joinpath("samples.json")
    before = source.read_bytes()
    baseline = catalog().model_dump_json()

    def call(answer):
        with TestClient(app) as visitor:
            return recalculate(visitor, [action(answer)]).json()["calculation"][
                "remaining_commitment_cents"
            ]

    answers = ["contractor", "unknown", "other"] * 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(call, answers)) == [500000, 700000, 700000] * 4
    assert catalog().model_dump_json() == baseline
    assert source.read_bytes() == before
    assert (
        client.get("/api/demo/scenarios/FIN-16").json()["calculation"]["remaining_commitment_cents"]
        == 700000
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"actions": [action(record_id="missing")]},
        {"actions": [action(record_id="known")]},
        {"actions": [action(kind="set_total")]},
        {"actions": [action("accept")]},
        {"actions": [action(), {"kind": "assign_recipient"}]},
        {"actions": [action(amount_cents=1)]},
        {"actions": [action()] * 13},
        {"actions": "contractor"},
        {"history": {}},
        {"remaining_commitment_cents": 1},
        {"actions": None},
    ],
)
def test_unknown_or_untyped_actions_are_rejected(client, payload):
    response = client.post("/api/demo/scenarios/FIN-16/calculate", json=payload)
    assert response.status_code == 422
    assert "calculation" not in response.json()


@pytest.mark.parametrize("id", ["FIN-01", "FIN-11"])
def test_actions_are_scenario_scoped(client, id):
    assert recalculate(client, [action()], id).status_code == 422


def test_unknown_scenarios_and_malformed_json(client):
    assert client.get("/api/demo/scenarios/unknown").status_code == 404
    assert recalculate(client, [], "FIN-99").status_code == 404
    assert client.post("/api/demo/scenarios/FIN-16/calculate", content="{").status_code == 422


def test_actual_openapi_is_exported_and_only_claims_implemented_routes(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/healthz",
        "/api/demo/scenarios",
        "/api/demo/scenarios/{scenario_id}",
        "/api/demo/scenarios/{scenario_id}/calculate",
        "/api/guest/session",
        "/api/guest/projects/{project_id}",
        "/api/guest/projects/{project_id}/review",
        "/api/guest/projects/{project_id}/snapshots",
        "/api/guest/projects/{project_id}/snapshots/{snapshot_id}",
        "/api/guest/projects/{project_id}/replies",
        "/api/guest/projects/{project_id}/replies/{reply_id}/edit",
        "/api/guest/projects/{project_id}/questions/{question_id}/state",
        "/api/guest/projects/{project_id}/attachments",
        "/api/guest/projects/{project_id}/rechecks",
        "/api/guest/projects/{project_id}/rechecks/{draft_id}/package",
        "/api/guest/projects/{project_id}/rechecks/{draft_id}/run",
        "/api/guest/projects/{project_id}/comparisons/{comparison_id}",
        "/api/guest/projects/{project_id}/tickets",
        "/api/guest/transfer",
        "/api/guest/maintenance/cleanup",
    }
    assert schema == json.loads((ROOT / "contracts/demo.openapi.json").read_text(encoding="utf-8"))
    assert schema["components"]["schemas"]["RecipientAction"]["additionalProperties"] is False
