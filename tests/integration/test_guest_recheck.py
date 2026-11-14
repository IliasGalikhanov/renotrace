"""Stage 8 real uploads, PostgreSQL, persisted drafts and immutable comparisons."""

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx2 as httpx
import psycopg
import pytest
import test_guest_http as http_tests
import test_guest_persistence as persistence_tests
from test_guest_http import BASE, command, ready, upload
from test_guest_persistence import ROOT

from app.guest.models import Problem

pytestmark = pytest.mark.skipif(not BASE, reason="Requires guest integration API")
guest = http_tests.guest
service = persistence_tests.service


def uid():
    return str(uuid4())


def differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        return [
            difference
            for key in left.keys() | right.keys()
            for difference in differences(left.get(key), right.get(key), path + "/" + key)
        ]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [
            difference
            for index, (a, b) in enumerate(zip(left, right, strict=True))
            for difference in differences(a, b, path + f"/{index}")
        ]
    return [] if left == right else [(path, left, right)]


def post(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def invoice(data, name):
    doc = next(d for d in data["project"]["documents"] if d["name"] == name)
    payment = next(
        c["id"]
        for d in data["project"]["documents"]
        for c in d["candidates"]
        if c["kind"] == "payment"
    )
    return {
        "file_id": doc["id"],
        "request_id": next(c["id"] for c in doc["candidates"] if c["kind"] == "payment_request"),
        "complete": True,
        "lines": [
            {
                "id": p["id"],
                "proposal_id": p["id"],
                "page": p["page"],
                "kind": p["kind"],
                "description": p["description"],
                "amount": p["amount"],
                "review": "checked",
                "cash_record_id": payment if p["kind"] == "reflected_payment" else None,
            }
            for p in doc["invoice_proposals"]
        ],
    }


def initial(client, project, invoice_name="recheck-original.pdf"):
    for name in ("recheck-estimate.pdf", "recheck-payment.pdf", invoice_name):
        assert upload(client, project, name).status_code == 200
    data = ready(client, project)
    review = command(data)
    original = invoice(data, invoice_name)
    review.update(mutation_id=uid(), invoices=[original], request_id=original["request_id"])
    return post(client, f"/api/guest/projects/{project}/review", review)


def package_for(data, original, corrected, question):
    return {
        "file_ids": [corrected["file_id"]],
        "replies": [],
        "old_request_id": original["request_id"],
        "new_request_id": corrected["request_id"],
        "relationship": "corrected",
        "matches": [
            {"old_id": original["lines"][0]["id"], "new_id": corrected["lines"][0]["id"]},
            {"new_id": corrected["lines"][1]["id"]},
        ],
        "question_links": [
            {
                "question_id": question,
                "new_line_id": corrected["lines"][1]["id"],
                "note": "Checked bank transfer credit",
            }
        ],
    }


def test_real_recheck_reply_versions_duplicate_upload_and_immutable_comparison(guest, service):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project)
    original = invoice(data, "recheck-original.pdf")
    base_id = data["casework"]["latest_snapshot_id"]
    frozen = client.get(base + "/snapshots/" + base_id).json()
    card = next(
        c for c in data["casework"]["cards"] if c["observation"]["code"] == "REQUEST_RECONCILIATION"
    )
    data = post(
        client,
        base + "/replies",
        {
            "mutation_id": uid(),
            "question_ids": [card["id"]],
            "text": "The earlier transfer is reflected in the revision.",
        },
    )
    reply = data["casework"]["replies"][0]
    start = {"mutation_id": uid(), "base_snapshot_id": base_id}
    data = post(client, base + "/rechecks", start)
    assert post(client, base + "/rechecks", start) == data
    draft = data["rechecks"]["drafts"][0]
    added = upload(client, project, "recheck-corrected.pdf")
    assert added.status_code == 200
    assert upload(client, project, "recheck-corrected.pdf").json()["id"] == added.json()["id"]
    data = ready(client, project)
    corrected = invoice(data, "recheck-corrected.pdf")
    package = package_for(data, original, corrected, card["id"])
    package["replies"] = [{"reply_id": reply["id"], "version": 1}]
    body = {"mutation_id": uid(), "expected_version": draft["version"], "package": package}
    data = post(client, base + f"/rechecks/{draft['id']}/package", body)
    assert post(client, base + f"/rechecks/{draft['id']}/package", body) == data
    assert (
        len(data["casework"]["snapshots"]) == 1
    )  # Upload/package save is not a completed recheck.
    assert client.get(base).json()["rechecks"] == data["rechecks"]
    review = command(data)
    review.update(
        invoices=[original, corrected],
        request_id=corrected["request_id"],
        request_versions=[
            {"old_request_id": original["request_id"], "new_request_id": corrected["request_id"]}
        ],
    )
    run = {"mutation_id": uid(), "expected_version": 2, "review": review}
    endpoint = base + f"/rechecks/{draft['id']}/run"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(client, endpoint, run), range(2)))
    delta = differences(results[0], results[1])
    assert results[0] == results[1], delta[:8]
    data = results[0]
    assert len(data["casework"]["snapshots"]) == 2
    assert len(data["rechecks"]["comparisons"]) == 1
    assert data["rechecks"]["comparisons"][0]["current"]
    assert data["result"]["calculation"]["requested_now_cents"] == 500000
    assert data["result"]["calculation"]["net_paid_cents"] == 120000
    assert data["result"]["calculation"]["remaining_commitment_cents"] == 500000
    comparison_id = data["rechecks"]["comparisons"][0]["id"]
    comparison = client.get(base + "/comparisons/" + comparison_id).json()
    assert comparison["payload"]["result"]["question_findings"][0]["payment_reflection"]
    assert client.get(base + "/snapshots/" + base_id).json() == frozen
    assert upload(client, project, "recheck-equal.pdf").status_code == 200
    changed_source = ready(client, project)
    assert not changed_source["rechecks"]["comparisons"][0]["current"]
    assert client.get(base + "/comparisons/" + comparison_id).json() == comparison
    edited = post(
        client,
        base + f"/replies/{reply['id']}/edit",
        {
            "mutation_id": uid(),
            "expected_version": 1,
            "text": "Correction: only a partial explanation; confirmation is still needed.",
        },
    )
    assert not edited["rechecks"]["comparisons"][0]["current"]
    assert client.get(base + "/comparisons/" + comparison_id).json() == comparison
    assert comparison["payload"]["reply_versions"][0]["version"] == 1
    assert "earlier transfer" in comparison["payload"]["reply_versions"][0]["text"]
    if os.environ.get("GUEST_LOCAL_DB") == "1":
        with pytest.raises(psycopg.errors.RaiseException), service.db.connection() as connection:
            connection.execute(
                "UPDATE guest_review.comparisons SET data=data WHERE id=%s", (comparison_id,)
            )
    assert client.post(endpoint, json={**run, "mutation_id": uid()}).status_code == 409
    stranger = client.post("/api/guest/session", headers={"Authorization": ""}).json()
    auth = {"Authorization": "Bearer " + stranger["token"]}
    try:
        assert client.get(base + "/comparisons/" + comparison_id, headers=auth).status_code == 404
        assert (
            client.post(
                base + f"/rechecks/{draft['id']}/package", headers=auth, json=body
            ).status_code
            == 404
        )
        other = f"/api/guest/projects/{stranger['project_id']}"
        assert client.post(other + "/rechecks", headers=auth, json=start).status_code == 404
        assert client.get(other + "/comparisons/" + comparison_id, headers=auth).status_code == 404
    finally:
        client.delete(f"/api/guest/projects/{stranger['project_id']}", headers=auth)
    assert client.delete(base).status_code == 204
    assert client.get(base + "/comparisons/" + comparison_id).status_code == 404
    if os.environ.get("GUEST_LOCAL_DB") == "1":
        with service.db.connection() as connection:
            for table in ("comparisons", "rechecks", "invoice_state"):
                assert (
                    connection.execute(
                        f"SELECT count(*) AS n FROM guest_review.{table} WHERE project_id=%s",
                        (project,),
                    ).fetchone()["n"]
                    == 0
                )


def test_explanation_without_new_document_and_conflicting_answer_stays_uncertain(guest):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project)
    original = invoice(data, "recheck-original.pdf")
    baseline = data["result"]["calculation"]
    old_id = data["casework"]["latest_snapshot_id"]
    card = next(
        c for c in data["casework"]["cards"] if c["observation"]["code"] == "REQUEST_RECONCILIATION"
    )
    data = post(
        client,
        base + "/replies",
        {
            "mutation_id": uid(),
            "question_ids": [card["id"]],
            "text": "Partial answer: no payment was received, "
            "but I have not checked the bank receipt.",
        },
    )
    card = next(c for c in data["casework"]["cards"] if c["id"] == card["id"])
    reply = data["casework"]["replies"][0]
    data = post(
        client,
        base + f"/questions/{card['id']}/state",
        {
            "mutation_id": uid(),
            "expected_version": card["version"],
            "evidence_state": "contradiction_remains",
            "owner_decision": "accept_explanation",
            "note": "Reply contradicts the checked payment receipt.",
        },
    )
    data = post(client, base + "/rechecks", {"mutation_id": uid(), "base_snapshot_id": old_id})
    draft = data["rechecks"]["drafts"][0]
    package = {
        "file_ids": [original["file_id"]],
        "replies": [{"reply_id": reply["id"], "version": 1}],
        "old_request_id": original["request_id"],
        "new_request_id": original["request_id"],
        "relationship": "same",
        "matches": [],
        "question_links": [],
    }
    endpoint = base + f"/rechecks/{draft['id']}/package"
    assert (
        client.post(
            endpoint,
            json={
                "mutation_id": uid(),
                "expected_version": 1,
                "package": {**package, "file_ids": [uid()]},
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            endpoint,
            json={
                "mutation_id": uid(),
                "expected_version": 1,
                "package": {**package, "replies": [{"reply_id": uid(), "version": 1}]},
            },
        ).status_code
        == 404
    )
    data = post(client, endpoint, {"mutation_id": uid(), "expected_version": 1, "package": package})
    review = command(data)
    review.update(invoices=[original], request_id=original["request_id"])
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/run",
        {"mutation_id": uid(), "expected_version": 2, "review": review},
    )
    assert len(data["project"]["documents"]) == 3
    result = data["result"]["calculation"]
    for metric in (
        "commitment_total_cents",
        "net_paid_cents",
        "remaining_commitment_cents",
        "requested_now_cents",
    ):
        assert result[metric] == baseline[metric]
    card = next(c for c in data["casework"]["cards"] if c["id"] == card["id"])
    assert card["evidence_state"] == "contradiction_remains"
    assert card["owner_decision"] == "accept_explanation"
    assert data["result"]["incomplete"]
    comparison = client.get(
        base + "/comparisons/" + data["rechecks"]["comparisons"][0]["id"]
    ).json()
    assert comparison["payload"]["result"]["explanation_only"]
    assert comparison["payload"]["result"]["preliminary"]


@pytest.mark.parametrize(
    "old_name,new_name,requested",
    [
        ("recheck-discount.pdf", "recheck-new-work.pdf", 450000),
        ("recheck-original.pdf", "recheck-equal.pdf", 620000),
        ("recheck-original.pdf", "recheck-incomplete.pdf", 500000),
    ],
)
def test_uploaded_invoice_composition_changes_and_ambiguity(guest, old_name, new_name, requested):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project, old_name)
    original = invoice(data, old_name)
    data = post(
        client,
        base + "/rechecks",
        {"mutation_id": uid(), "base_snapshot_id": data["casework"]["latest_snapshot_id"]},
    )
    draft = data["rechecks"]["drafts"][0]
    assert upload(client, project, new_name).status_code == 200
    data = ready(client, project)
    corrected = invoice(data, new_name)
    ambiguous = new_name == "recheck-incomplete.pdf"
    matches = (
        []
        if ambiguous
        else [{"old_id": original["lines"][0]["id"], "new_id": corrected["lines"][0]["id"]}]
    )
    if not ambiguous:
        matches += [{"old_id": row["id"]} for row in original["lines"][1:]]
        matches += [{"new_id": row["id"]} for row in corrected["lines"][1:]]
    package = {
        "file_ids": [corrected["file_id"]],
        "old_request_id": original["request_id"],
        "new_request_id": corrected["request_id"],
        "relationship": "unknown" if ambiguous else "corrected",
        "matches": matches,
    }
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/package",
        {"mutation_id": uid(), "expected_version": 1, "package": package},
    )
    review = command(data)
    review.update(
        invoices=[original, corrected],
        request_id=corrected["request_id"],
        request_versions=[]
        if ambiguous
        else [
            {"old_request_id": original["request_id"], "new_request_id": corrected["request_id"]}
        ],
    )
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/run",
        {"mutation_id": uid(), "expected_version": 2, "review": review},
    )
    saved = client.get(base + "/comparisons/" + data["rechecks"]["comparisons"][0]["id"]).json()[
        "payload"
    ]["result"]
    assert saved["metrics"]["requested_now_cents"]["after"] == requested
    assert all(
        saved["metrics"][key]["delta"] == 0
        for key in ("commitment_total_cents", "net_paid_cents", "remaining_commitment_cents")
    )
    if new_name == "recheck-new-work.pdf":
        assert {row["change"] for row in saved["changes"]} >= {"added", "removed"}
        assert any("contractual approval" in issue for issue in saved["issues"])
    elif new_name == "recheck-equal.pdf":
        assert saved["metrics"]["requested_now_cents"]["delta"] == 0
        assert saved["changes"][0]["fields"] == ["description"]
    else:
        assert saved["new_composition"]["unexplained_cents"] == -100000
        assert saved["unmatched_old"] and saved["unmatched_new"] and saved["preliminary"]


@pytest.mark.skipif(
    os.environ.get("GUEST_LOCAL_DB") != "1", reason="Disposable local PostgreSQL only"
)
def test_draft_restart_expiry_migration_and_rollback_compatible_json(guest, service):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project)
    old_id = data["casework"]["latest_snapshot_id"]
    data = post(client, base + "/rechecks", {"mutation_id": uid(), "base_snapshot_id": old_id})
    draft = data["rechecks"]["drafts"][0]
    original = invoice(data, "recheck-original.pdf")
    package = {
        "file_ids": [original["file_id"]],
        "old_request_id": original["request_id"],
        "new_request_id": original["request_id"],
        "relationship": "same",
    }
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/package",
        {"mutation_id": uid(), "expected_version": 1, "package": package},
    )
    review = command(data)
    review.update(invoices=[original], request_id=original["request_id"])
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/run",
        {"mutation_id": uid(), "expected_version": 2, "review": review},
    )
    comparison_id = data["rechecks"]["comparisons"][0]["id"]
    frozen = client.get(base + "/comparisons/" + comparison_id).json()
    data = post(client, base + "/rechecks", {"mutation_id": uid(), "base_snapshot_id": old_id})
    saved = data["rechecks"]
    service.db.migrate()
    subprocess.run(
        ["docker", "compose", "-f", "infra/guest.compose.yml", "restart", "api"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    for _ in range(50):
        try:
            if client.get("/healthz").status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    assert client.get(base).json()["rechecks"] == saved
    assert client.get(base + "/comparisons/" + comparison_id).json() == frozen
    with service.db.connection() as connection:
        row = connection.execute(
            "SELECT data FROM guest_review.projects WHERE id=%s", (project,)
        ).fetchone()["data"]
        assert "invoices" not in row["review"]["command"]
        assert all("invoice_proposals" not in d for d in row["documents"])
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM guest_review.comparisons WHERE project_id=%s", (project,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM guest_review.invoice_state WHERE project_id=%s",
                (project,),
            ).fetchone()["n"]
            == 1
        )
        connection.execute(
            "UPDATE guest_review.projects SET expires_at=now()-interval '1 second' WHERE id=%s",
            (project,),
        )
    with pytest.raises(Problem):
        service.project(project, client.headers["Authorization"][7:])
    service.cleanup()
    with service.db.connection() as connection:
        for table in ("rechecks", "comparisons", "invoice_state", "snapshots"):
            assert (
                connection.execute(
                    f"SELECT count(*) AS n FROM guest_review.{table} WHERE project_id=%s",
                    (project,),
                ).fetchone()["n"]
                == 0
            )
