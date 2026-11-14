import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reference_cases import reference_input

ROOT = Path(__file__).resolve().parents[3]


def test_health_endpoint_and_no_unimplemented_private_routes():
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "renotrace-api"}
        assert client.get("/api/v1/cases").status_code == 404


def test_cli_runs_fin_01_as_real_subprocess():
    process = subprocess.run(
        [sys.executable, "-m", "app.cli", "--case", "FIN-01"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["remaining_commitment_cents"] == 470_000
    assert result["requested_now_cents"] == 550_000


@pytest.mark.parametrize("args", [["--case", "FIN-99"], ["--fixtures", "missing.json"]])
def test_cli_errors_have_nonzero_exit(args):
    process = subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 2
    assert "error:" in process.stderr
    assert not process.stdout


def test_cli_accepts_normalized_json_and_rejects_fractional_cent(tmp_path):
    case = json.loads((ROOT / "fixtures/ledger_cases.json").read_text(encoding="utf-8"))["cases"][0]
    payload = reference_input(case).model_dump(mode="json")
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    command = [sys.executable, "-m", "app.cli", "--input", str(path)]
    valid = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["remaining_commitment_cents"] == 470_000
    payload["agreement"]["amount_cents"] = 100.5
    path.write_text(json.dumps(payload), encoding="utf-8")
    invalid = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert invalid.returncode == 2
    assert not invalid.stdout


def test_reference_adapter_refuses_nonsynthetic_or_ambiguous_empty_base():
    with pytest.raises(ValueError, match="synthetic"):
        reference_input({"synthetic": False})
    with pytest.raises(ValueError, match="unknown base"):
        reference_input(
            {"synthetic": True, "id": "empty", "normalized": {"commitment_terms_cents": []}}
        )
