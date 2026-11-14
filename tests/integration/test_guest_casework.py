"""Stage 7 real HTTP/PostgreSQL persistence, isolation and immutable history."""

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx2 as httpx
import pytest
import test_guest_http as http_tests
import test_guest_persistence as persistence_tests
from test_guest_http import BASE, command, ready, upload
from test_guest_persistence import ROOT

from app.guest.casework_store import Casework

pytestmark = pytest.mark.skipif(not BASE, reason="Requires guest integration API")
guest = http_tests.guest
service = persistence_tests.service


def uid():
    return str(uuid4())


def initial(client, project):
    for name in ("estimate.pdf", "payment.pdf", "invoice.pdf"):
        assert upload(client, project, name).status_code == 200
    data = ready(client, project)
    review = command(data)
    review["mutation_id"] = uid()
    next(r for r in review["records"] if r["kind"] == "payment")["recipient"] = "unknown"
    saved = client.post(f"/api/guest/projects/{project}/review", json=review)
    assert saved.status_code == 200, saved.text
    return saved.json(), review


def recipient(data):
    return next(
        c for c in data["casework"]["cards"] if c["observation"]["code"] == "UNRESOLVED_RECIPIENT"
    )


def post(client, url, body):
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_replies_retries_snapshots_and_decisions_are_independent(guest):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data, review = initial(client, project)
    card = recipient(data)
    frozen_id = data["casework"]["latest_snapshot_id"]
    frozen = client.get(base + "/snapshots/" + frozen_id).json()
    original_result = data["result"]
    revision, expiry = data["project"]["revision"], data["project"]["expires_at"]
    # An identical financial save retry is not a new financial event or snapshot.
    again = post(client, base + "/review", review)
    assert again == data
    body = {
        "mutation_id": uid(),
        "question_ids": [card["id"]],
        "text": "Part of this transfer may be ours; I do not have confirmation.",
        "file_ids": [],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: post(client, base + "/replies", body), range(2)))
    replied = attempts[0]
    assert attempts[1] == replied
    assert replied["project"]["revision"] == revision
    assert replied["project"]["expires_at"] == expiry
    assert replied["result"] == original_result
    assert recipient(replied)["evidence_state"] == "awaiting_explanation"
    assert post(client, base + "/replies", body) == replied
    assert client.post(base + "/replies", json={**body, "text": "Different"}).status_code == 409
    reply = replied["casework"]["replies"][0]
    edit = {
        "mutation_id": uid(),
        "expected_version": 1,
        "text": "The contractor says it is another recipient. No supporting evidence.",
        "file_ids": [],
    }
    edited = post(client, base + f"/replies/{reply['id']}/edit", edit)
    assert len(edited["casework"]["replies"][0]["versions"]) == 2
    assert post(client, base + f"/replies/{reply['id']}/edit", edit) == edited
    assert edited["casework"]["replies"][0]["versions"][0]["text"] == body["text"]
    for decision in ("accept_explanation", "stop_unresolved"):
        card = recipient(edited)
        edited = post(
            client,
            base + f"/questions/{card['id']}/state",
            {
                "mutation_id": uid(),
                "expected_version": card["version"],
                "evidence_state": "answer_insufficient",
                "owner_decision": decision,
                "note": "Owner choice does not establish who received the payment",
            },
        )
        assert edited["result"] == original_result
        assert recipient(edited)["observation"]["active"]
        assert recipient(edited)["evidence_state"] == "answer_insufficient"
    assert client.get(base).json() == edited
    # Same input and new review version retains the stable card and reply history.
    resave = {**review, "mutation_id": uid(), "expected_revision": revision}
    same = post(client, base + "/review", resave)
    assert recipient(same)["id"] == card["id"]
    assert recipient(same)["reply_ids"] == [reply["id"]]
    assert recipient(same)["evidence_state"] == "answer_insufficient"
    assert len(same["casework"]["snapshots"]) == 2
    changed = command(same)
    changed["mutation_id"] = uid()
    changed = post(client, base + "/review", changed)
    assert changed["result"]["calculation"]["remaining_commitment_cents"] == 700000
    assert recipient(changed)["id"] == card["id"]
    assert recipient(changed)["evidence_state"] == "needs_recheck"
    assert recipient(changed)["owner_decision"] == "stop_unresolved"
    assert not recipient(changed)["observation"]["active"]
    assert client.get(base + "/snapshots/" + frozen_id).json() == frozen
    assert frozen["payload"]["result"]["calculation"]["remaining_commitment_cents"] == 1000000
    assert len(client.get(base + "/snapshots").json()) == 3


def test_foreign_entities_and_multi_question_attachments(guest):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data, _ = initial(client, project)
    card = recipient(data)
    stranger = client.post("/api/guest/session", headers={"Authorization": ""}).json()
    auth = {"Authorization": "Bearer " + stranger["token"]}
    other_base = f"/api/guest/projects/{stranger['project_id']}"
    try:
        foreign = initial(
            httpx.Client(base_url=BASE, headers=auth, timeout=90), stranger["project_id"]
        )[0]
        foreign_file = foreign["project"]["documents"][0]["id"]
        body = {"mutation_id": uid(), "question_ids": [card["id"]], "text": "Explanation"}
        assert client.post(base + "/replies", headers=auth, json=body).status_code == 404
        assert client.post(other_base + "/replies", headers=auth, json=body).status_code == 404
        assert (
            client.post(base + "/replies", json={**body, "file_ids": [foreign_file]}).status_code
            == 404
        )
        snapshot = data["casework"]["latest_snapshot_id"]
        assert client.get(base + "/snapshots/" + snapshot, headers=auth).status_code == 404
        foreign_snapshot = foreign["casework"]["latest_snapshot_id"]
        assert client.get(base + "/snapshots/" + foreign_snapshot).status_code == 404
        other_card = recipient(foreign)
        foreign_reply = client.post(
            other_base + "/replies",
            headers=auth,
            json={
                "mutation_id": uid(),
                "question_ids": [other_card["id"]],
                "text": "Other guest",
            },
        ).json()["casework"]["replies"][0]["id"]
        assert (
            client.post(
                base + f"/replies/{foreign_reply}/edit",
                json={
                    "mutation_id": uid(),
                    "expected_version": 1,
                    "text": "Invalid edit",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                base + f"/questions/{other_card['id']}/state",
                json={
                    "mutation_id": uid(),
                    "expected_version": 1,
                    "note": "Invalid link",
                    "owner_decision": "accept_explanation",
                },
            ).status_code
            == 404
        )
        # Add a second real uncertainty and attach existing sources to both cards.
        revised = command(data)
        revised["agreement_id"] = None
        data = post(client, base + "/review", revised)
        ids = [c["id"] for c in data["casework"]["cards"]]
        assert len(ids) >= 2
        files = [d["id"] for d in data["project"]["documents"][:2]]
        attach = {"mutation_id": uid(), "question_ids": ids, "file_ids": files}
        attached = post(client, base + "/attachments", attach)
        assert post(client, base + "/attachments", attach) == attached
        assert attached["project"] == data["project"] and attached["result"] == data["result"]
        assert all(c["file_ids"] == sorted(files) for c in attached["casework"]["cards"])
    finally:
        client.delete(other_base, headers=auth)


@pytest.mark.skipif(os.environ.get("GUEST_LOCAL_DB") != "1", reason="Local DB only")
@pytest.mark.parametrize("expire", [False, True])
def test_restart_immutable_read_additive_migration_and_cascade(guest, service, monkeypatch, expire):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data, _ = initial(client, project)
    snapshot_id = data["casework"]["latest_snapshot_id"]
    card = recipient(data)
    data = post(
        client,
        base + "/replies",
        {
            "mutation_id": uid(),
            "question_ids": [card["id"]],
            "text": "Preserve this across restart",
        },
    )
    frozen = client.get(base + "/snapshots/" + snapshot_id).json()
    service.db.migrate()  # Reapplying the additive schema keeps existing projects and contents.
    with pytest.raises(Exception, match="cannot be updated"):
        with service.db.connection() as conn:
            conn.execute("UPDATE guest_review.snapshots SET data=data WHERE id=%s", (snapshot_id,))
    token = client.headers["Authorization"].removeprefix("Bearer ")
    # Historical reads must work even if today's calculator is broken or has changed.
    import app.guest.casework_store as store

    monkeypatch.setattr(store, "result_for", lambda _: (_ for _ in ()).throw(AssertionError()))
    assert (
        Casework(service.db).snapshot(project, token, snapshot_id).model_dump(mode="json") == frozen
    )
    subprocess.run(
        ["docker", "compose", "-f", "infra/guest.compose.yml", "restart", "api"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            restored = client.get(base)
            if restored.status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(1)
    else:
        pytest.fail("API did not restart")
    assert restored.json() == data
    assert client.get(base + "/snapshots/" + snapshot_id).json() == frozen
    if expire:
        with service.db.connection() as conn:
            conn.execute(
                "UPDATE guest_review.projects SET expires_at=now()-interval '1 second' WHERE id=%s",
                (project,),
            )
        assert client.get(base + "/snapshots/" + snapshot_id).status_code == 404
        assert (
            client.post(
                base + "/replies",
                json={"mutation_id": uid(), "question_ids": [card["id"]], "text": "Expired"},
            ).status_code
            == 404
        )
        service.cleanup()
    else:
        assert client.delete(base).status_code == 204
    with service.db.connection() as conn:
        from psycopg import sql

        for table in ("snapshots", "question_cards", "replies", "discussion_operations"):
            assert (
                conn.execute(
                    sql.SQL("SELECT count(*) AS n FROM guest_review.{} WHERE project_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (project,),
                ).fetchone()["n"]
                == 0
            )
