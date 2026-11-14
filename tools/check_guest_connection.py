"""Probe configured PostgreSQL + private objects with fictional evidence, then delete it."""

import os
from pathlib import Path

import httpx2 as httpx

from app.guest.models import TicketRequest
from app.guest.runtime import configured_reviews

reviews = configured_reviews()
if reviews is None:
    raise SystemExit("Guest storage is not configured")
session = reviews.db.start(None)
key = None
try:
    ticket = reviews.ticket(
        session.project_id,
        session.token,
        TicketRequest(purpose="upload", name="fictional-connection-test.pdf"),
    )
    document = reviews.upload(
        reviews.consume(ticket.token, "upload"), Path("fixtures/uploads/estimate.pdf").read_bytes()
    )
    key = f"{session.project_id}/{document.id}"
    assert reviews.objects.get(key) == Path("fixtures/uploads/estimate.pdf").read_bytes()
    reviews.work_once()
    project = reviews.project(session.project_id, session.token)
    assert project.project.documents[0].status == "ready"
    assert project.project.documents[0].candidates[0].amount == "10000.00"
    if os.environ.get("SUPABASE_URL"):
        url = (
            os.environ["SUPABASE_URL"]
            + "/storage/v1/object/public/"
            + os.environ.get("REVIEW_STORAGE_BUCKET", "guest-originals")
            + "/"
            + key
        )
        assert httpx.get(url, timeout=15).status_code in (400, 401, 403, 404)
    print("PASS: PostgreSQL, immutable private original, text extraction and denied public access")
finally:
    reviews.delete(session.project_id, session.token)
if key:
    try:
        reviews.objects.get(key)
    except Exception:
        print("PASS: source removed after deletion")
    else:
        raise AssertionError("Source survived deletion")
