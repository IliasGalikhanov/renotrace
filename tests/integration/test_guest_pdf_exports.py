"""Actual PDFs from owner-authorized HTTPS tickets and immutable PostgreSQL snapshots."""

import os
import re
from io import BytesIO

import pytest
import test_guest_http as http_tests
import test_guest_persistence as persistence_tests
from pypdf import PdfReader
from test_guest_http import BASE, command, ready, upload
from test_guest_recheck import initial, invoice, package_for, post, uid

pytestmark = pytest.mark.skipif(not BASE, reason="Requires guest integration API")
guest = http_tests.guest
service = persistence_tests.service


def ticket(client, base, kind, identifier):
    return client.post(base + "/exports", json={"kind": kind, "result_id": identifier})


def pdf(client, value):
    response = client.get("/api/guest/export", headers={"Authorization": "Bearer " + value})
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.pdf"')
    reader = PdfReader(BytesIO(response.content))
    content = " ".join(" ".join(p.extract_text() for p in reader.pages).split())
    assert value not in content and value not in str(reader.metadata)
    assert client.headers["Authorization"][7:] not in content
    assert all(not p.get("/Annots") for p in reader.pages)
    assert not reader.attachments
    return re.sub(r"PDF generated: .*? UTC", "PDF generated: [time]", content)


def test_export_original_and_pinned_recheck_after_later_changes_and_private_tickets(guest):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project)
    original = invoice(data, "recheck-original.pdf")
    old_id = data["casework"]["latest_snapshot_id"]
    old_frozen = client.get(base + "/snapshots/" + old_id).json()
    before = client.get(base).json()
    issued = ticket(client, base, "snapshot", old_id)
    assert issued.status_code == 200
    transfer = issued.json()["token"]
    # Purpose isolation does not consume a PDF ticket as an original-document ticket.
    assert (
        client.get(
            "/api/guest/transfer", headers={"Authorization": "Bearer " + transfer}
        ).status_code
        == 404
    )
    original_pdf = pdf(client, transfer)
    assert "Historical messages are not current document status" in original_pdf
    assert "$6,200.00" in original_pdf and "$1,200.00" in original_pdf
    assert (
        client.get("/api/guest/export", headers={"Authorization": "Bearer " + transfer}).status_code
        == 404
    )
    assert client.get(base).json() == before  # No review, discussion, revision or expiry mutation.
    card = next(
        c for c in data["casework"]["cards"] if c["observation"]["code"] == "REQUEST_RECONCILIATION"
    )
    data = post(
        client,
        base + "/replies",
        {
            "mutation_id": uid(),
            "question_ids": [card["id"]],
            "text": "PINNED-EXPLANATION: partial answer about the original transfer.",
        },
    )
    answer = data["casework"]["replies"][0]
    data = post(
        client,
        base + f"/replies/{answer['id']}/edit",
        {
            "mutation_id": uid(),
            "expected_version": 1,
            "text": "UNPINNED-ANSWER: this newer reply must not enter the package.",
        },
    )
    data = post(client, base + "/rechecks", {"mutation_id": uid(), "base_snapshot_id": old_id})
    draft = data["rechecks"]["drafts"][0]
    assert ticket(client, base, "comparison", draft["id"]).status_code == 404
    assert upload(client, project, "recheck-corrected.pdf").status_code == 200
    data = ready(client, project)
    corrected = invoice(data, "recheck-corrected.pdf")
    package = package_for(data, original, corrected, card["id"])
    package["replies"] = [{"reply_id": answer["id"], "version": 1}]
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/package",
        {"mutation_id": uid(), "expected_version": 1, "package": package},
    )
    review = command(data)
    review.update(
        invoices=[original, corrected],
        request_id=corrected["request_id"],
        request_versions=[
            {"old_request_id": original["request_id"], "new_request_id": corrected["request_id"]}
        ],
    )
    data = post(
        client,
        base + f"/rechecks/{draft['id']}/run",
        {"mutation_id": uid(), "expected_version": 2, "review": review},
    )
    comparison_id = data["rechecks"]["comparisons"][0]["id"]
    result_pdf = pdf(client, ticket(client, base, "comparison", comparison_id).json()["token"])
    assert "PINNED-EXPLANATION" in result_pdf and "UNPINNED-ANSWER" not in result_pdf
    assert "No additional payment is created" in result_pdf
    assert "source unavailable" not in result_pdf
    assert "New question:" not in result_pdf
    assert "Previous conclusion requires reassessment" in result_pdf
    assert "$5,000.00" in result_pdf and "-$1,200.00" in result_pdf
    post(
        client,
        base + f"/replies/{answer['id']}/edit",
        {
            "mutation_id": uid(),
            "expected_version": 2,
            "text": "LATER-SECRET-MATERIAL should never change an old export.",
        },
    )
    assert upload(client, project, "recheck-equal.pdf").status_code == 200
    ready(client, project)
    assert pdf(client, ticket(client, base, "snapshot", old_id).json()["token"]) == original_pdf
    assert (
        pdf(client, ticket(client, base, "comparison", comparison_id).json()["token"]) == result_pdf
    )
    assert client.get(base + "/snapshots/" + old_id).json() == old_frozen
    assert client.get("/api/guest/export").status_code == 404  # Owner token is not a ticket.
    assert ticket(client, base, "snapshot", uid()).status_code == 404
    for malformed in ("-" * 36, "a" * 36, "not-a-uuid"):
        assert ticket(client, base, "snapshot", malformed).status_code == 422
    assert (
        client.post(
            base + "/exports",
            json={"kind": "snapshot", "result_id": old_id, "totals": {"remaining": 0}},
        ).status_code
        == 422
    )
    assert (
        client.post(base + "/exports", json={"kind": "draft", "result_id": old_id}).status_code
        == 422
    )
    stranger = client.post("/api/guest/session", headers={"Authorization": ""}).json()
    auth = {"Authorization": "Bearer " + stranger["token"]}
    try:
        assert (
            client.post(
                base + "/exports", headers=auth, json={"kind": "snapshot", "result_id": old_id}
            ).status_code
            == 404
        )
        foreign = f"/api/guest/projects/{stranger['project_id']}"
        assert (
            client.post(
                foreign + "/exports",
                headers=auth,
                json={"kind": "comparison", "result_id": comparison_id},
            ).status_code
            == 404
        )
    finally:
        client.delete(f"/api/guest/projects/{stranger['project_id']}", headers=auth)
    pending = ticket(client, base, "comparison", comparison_id).json()["token"]
    assert client.delete(base).status_code == 204
    assert (
        client.get("/api/guest/export", headers={"Authorization": "Bearer " + pending}).status_code
        == 404
    )
    assert ticket(client, base, "snapshot", old_id).status_code == 404


@pytest.mark.skipif(os.environ.get("GUEST_LOCAL_DB") != "1", reason="Local expiry only")
def test_export_rechecks_expiry_and_does_not_write_report_files(guest, service):
    client, project = guest
    base = f"/api/guest/projects/{project}"
    data = initial(client, project)
    identifier = data["casework"]["latest_snapshot_id"]
    transfer = ticket(client, base, "snapshot", identifier).json()["token"]
    with service.db.connection() as connection:
        before = connection.execute(
            "SELECT count(*) AS n FROM guest_review.objects WHERE project_id=%s", (project,)
        ).fetchone()["n"]
    pdf(client, transfer)
    expired_ticket = ticket(client, base, "snapshot", identifier).json()["token"]
    from app.guest.database import digest

    with service.db.connection() as connection:
        connection.execute(
            "UPDATE guest_review.tickets SET expires_at=now()-interval '1 second' "
            "WHERE secret_hash=%s",
            (digest(expired_ticket),),
        )
    assert (
        client.get(
            "/api/guest/export", headers={"Authorization": "Bearer " + expired_ticket}
        ).status_code
        == 404
    )
    pending = ticket(client, base, "snapshot", identifier).json()["token"]
    with service.db.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM guest_review.objects WHERE project_id=%s", (project,)
            ).fetchone()["n"]
            == before
        )
        connection.execute(
            "UPDATE guest_review.projects SET expires_at=now()-interval '1 second' WHERE id=%s",
            (project,),
        )
    assert (
        client.get("/api/guest/export", headers={"Authorization": "Bearer " + pending}).status_code
        == 404
    )
    assert ticket(client, base, "snapshot", identifier).status_code == 404
    service.cleanup()


@pytest.mark.skipif(os.environ.get("GUEST_LOCAL_DB") != "1", reason="Local revocation only")
def test_access_revoked_during_pdf_generation_is_rechecked(guest, service, monkeypatch):
    from app.guest.export_store import ExportRequest, Exports
    from app.guest.models import Problem
    from app.guest.pdf_report import render_pdf

    client, project = guest
    data = initial(client, project)
    exporter = Exports(service.db)
    issued = exporter.ticket(
        project,
        client.headers["Authorization"][7:],
        ExportRequest(kind="snapshot", result_id=data["casework"]["latest_snapshot_id"]),
    )
    transfer = service.consume(issued.token, "pdf")

    def render_and_delete(basis):
        content = render_pdf(basis)
        with service.db.connection() as connection:
            service.db.remove(connection, project)
        return content

    monkeypatch.setattr("app.guest.export_store.render_pdf", render_and_delete)
    with pytest.raises(Problem) as revoked:
        exporter.download(transfer)
    assert revoked.value.status == 404
    service.cleanup()
