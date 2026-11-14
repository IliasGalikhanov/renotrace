"""Real HTTP, PostgreSQL, S3 and Tesseract checks. No provider mocks.

Set GUEST_API_URL after starting infra/guest.compose.yml and setup_guest_local.py.
"""

import os
import time
from pathlib import Path

import httpx2 as httpx
import pytest

BASE = os.environ.get("GUEST_API_URL")
pytestmark = pytest.mark.skipif(
    not BASE, reason="Requires explicitly started guest integration services"
)
FILES = Path(__file__).resolve().parents[2] / "fixtures" / "uploads"


@pytest.fixture
def guest():
    with httpx.Client(base_url=BASE, timeout=90) as client:
        session = client.post("/api/guest/session").json()
        client.headers["Authorization"] = "Bearer " + session["token"]
        project_id = session["project_id"]
        yield client, project_id
        client.delete(f"/api/guest/projects/{project_id}")


def upload(client, project, name, content=None):
    ticket = client.post(
        f"/api/guest/projects/{project}/tickets", json={"purpose": "upload", "name": name}
    )
    assert ticket.status_code == 200, ticket.text
    response = client.put(
        "/api/guest/transfer",
        headers={"Authorization": "Bearer " + ticket.json()["token"]},
        content=content if content is not None else (FILES / name).read_bytes(),
    )
    return response


def ready(client, project):
    deadline = time.monotonic() + 160
    while time.monotonic() < deadline:
        response = client.get(f"/api/guest/projects/{project}")
        assert response.status_code == 200, response.text
        data = response.json()
        if all(d["status"] not in ("queued", "processing") for d in data["project"]["documents"]):
            return data
        time.sleep(0.5)
    pytest.fail("Durable extraction job did not finish")


def command(data):
    records = [
        {
            "id": c["id"],
            "kind": c["kind"],
            "amount": c["amount"],
            "date": c["date"],
            "state": c["state"],
            "recipient": "contractor",
            "answer": "accept",
        }
        for d in data["project"]["documents"]
        for c in d["candidates"]
    ]
    return {
        "expected_revision": data["project"]["revision"],
        "records": records,
        "agreement_id": next((r["id"] for r in records if r["kind"] == "agreement"), None),
        "request_id": next((r["id"] for r in records if r["kind"] == "payment_request"), None),
        "cutoff_date": "2026-11-14",
        "links": [],
    }


@pytest.mark.parametrize(
    "estimate,expected,method",
    [
        ("estimate.pdf", 700000, "pdf_text"),
        ("estimate-changed.pdf", 600000, "pdf_text"),
        ("estimate-scan.pdf", 700000, "tesseract"),
        ("estimate.png", 700000, "tesseract"),
        ("estimate.jpg", 700000, "tesseract"),
    ],
)
def test_real_documents_ocr_dedup_calculation(guest, estimate, expected, method):
    client, project = guest
    original = upload(client, project, estimate)
    assert original.status_code == 200, original.text
    assert upload(client, project, "payment.pdf").status_code == 200
    assert upload(client, project, "invoice.pdf").status_code == 200
    duplicate = upload(client, project, estimate)
    assert duplicate.json()["id"] == original.json()["id"]
    data = ready(client, project)
    assert len(data["project"]["documents"]) == 3
    assert all(d["status"] == "ready" for d in data["project"]["documents"]), data
    assert data["project"]["documents"][0]["pages"][0]["method"] == method
    assert data["result"]["calculation"]["remaining_commitment_cents"] is None
    assert data["result"]["incomplete"]
    review = command(data)
    response = client.post(f"/api/guest/projects/{project}/review", json=review)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["calculation"]["remaining_commitment_cents"] == expected
    assert result["calculation"]["net_paid_cents"] == 300000
    assert result["calculation"]["requested_now_cents"] == 700000
    assert client.post(f"/api/guest/projects/{project}/review", json=review).status_code == 409
    assert client.get(f"/api/guest/projects/{project}").json()["result"] == result
    new_review = command(response.json())
    next(r for r in new_review["records"] if r["kind"] == "payment")["recipient"] = "other"
    changed = client.post(f"/api/guest/projects/{project}/review", json=new_review)
    assert (
        changed.json()["result"]["calculation"]["remaining_commitment_cents"] == expected + 300000
    )


def test_sessions_cannot_read_change_download_or_delete_each_other(guest):
    client, project = guest
    assert upload(client, project, "estimate.pdf").status_code == 200
    doc = ready(client, project)["project"]["documents"][0]
    stranger = client.post("/api/guest/session", headers={"Authorization": ""}).json()
    auth = {"Authorization": "Bearer " + stranger["token"]}
    path = f"/api/guest/projects/{project}"
    assert client.get(path, headers=auth).status_code == 404
    assert client.delete(path, headers=auth).status_code == 404
    assert (
        client.post(
            path + "/review", headers=auth, json=command(ready(client, project))
        ).status_code
        == 404
    )
    assert (
        client.post(
            path + "/tickets", headers=auth, json={"purpose": "download", "file_id": doc["id"]}
        ).status_code
        == 404
    )
    assert client.get(path, headers={"Authorization": ""}).status_code == 404
    assert (
        client.delete(f"/api/guest/projects/{stranger['project_id']}", headers=auth).status_code
        == 204
    )


def test_delete_revokes_pending_tickets_and_removes_objects(guest):
    client, project = guest
    doc = upload(client, project, "payment.pdf").json()
    ticket = client.post(
        f"/api/guest/projects/{project}/tickets", json={"purpose": "download", "file_id": doc["id"]}
    ).json()
    assert client.delete(f"/api/guest/projects/{project}").status_code == 204
    assert client.get(f"/api/guest/projects/{project}").status_code == 404
    assert (
        client.get(
            "/api/guest/transfer", headers={"Authorization": "Bearer " + ticket["token"]}
        ).status_code
        == 404
    )
    time.sleep(3)
    assert client.get(f"/api/guest/projects/{project}").status_code == 404


def test_rejections_unreadable_and_missing_base(guest):
    client, project = guest
    for name in ("password.pdf", "too-many-pages.pdf"):
        assert upload(client, project, name).status_code == 422
    assert upload(client, project, "wrong.pdf", b"not a pdf").status_code == 422
    assert upload(client, project, "large.pdf", b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert upload(client, project, "unreadable.png").status_code == 200
    data = ready(client, project)
    assert data["project"]["documents"][0]["candidates"] == []
    assert data["result"]["calculation"]["remaining_commitment_cents"] is None
    assert data["result"]["incomplete"]
    assert upload(client, project, "payment.pdf").status_code == 200
    data = ready(client, project)
    result = client.post(f"/api/guest/projects/{project}/review", json=command(data)).json()[
        "result"
    ]
    assert result["calculation"]["remaining_commitment_cents"] is None
    assert result["calculation"]["net_paid_cents"] == 300000


def test_project_page_quota_is_enforced_by_server(guest):
    import io

    from pypdf import PdfWriter

    client, project = guest
    for index, (pages, expected) in enumerate(
        [(20, 200), (20, 200), (11, 422), (10, 200), (1, 422)]
    ):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=595 + index, height=842)
        buffer = io.BytesIO()
        writer.write(buffer)
        response = upload(client, project, f"quota-{index}.pdf", buffer.getvalue())
        assert response.status_code == expected, response.text
