"""Destructive checks confined to the named local test database and private bucket."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2 as httpx
import pytest
from botocore.exceptions import ClientError

from app.guest.database import Database
from app.guest.models import Problem, TicketRequest
from app.guest.service import Reviews
from app.guest.storage import S3Objects

pytestmark = pytest.mark.skipif(
    os.environ.get("GUEST_LOCAL_DB") != "1", reason="Local Compose integration only"
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def service():
    db = Database("postgresql://renotrace_test:local-test-only@127.0.0.1:55432/renotrace_test")
    objects = S3Objects(
        "http://127.0.0.1:59000", "renotrace-local", "local-object-test-only", "guest-originals"
    )
    return Reviews(db, objects)


def test_concurrent_duplicate_expiry_and_object_purge(service):
    session = service.db.start(None)
    project = session.project_id
    try:
        data = (ROOT / "fixtures/uploads/estimate.pdf").read_bytes()

        def upload(_):
            ticket = service.ticket(project, session.token, TicketRequest(purpose="upload"))
            return service.upload(service.consume(ticket.token, "upload"), data)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(upload, range(2)))
        assert results[0].id == results[1].id
        assert len(service.project(project, session.token).project.documents) == 1
        key = f"{project}/{results[0].id}"
        assert service.objects.get(key) == data
        with service.db.connection() as connection:
            connection.execute(
                "UPDATE guest_review.projects SET expires_at=now()-interval '1 second' WHERE id=%s",
                (project,),
            )
        with pytest.raises(Problem):
            service.project(project, session.token)
        service.cleanup()
        with pytest.raises(ClientError) as missing:
            service.objects.get(key)
        assert missing.value.response["Error"]["Code"] == "NoSuchKey"
        with service.db.connection() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) AS n FROM guest_review.jobs WHERE project_id=%s", (project,)
                ).fetchone()["n"]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) AS n FROM guest_review.objects WHERE project_id=%s", (project,)
                ).fetchone()["n"]
                == 0
            )
    finally:
        with service.db.connection() as connection:
            service.db.remove(connection, project)
        service.cleanup()


def test_api_restart_retains_project_and_recovers_abandoned_job(service):
    session = service.db.start(None)
    project = session.project_id
    try:
        ticket = service.ticket(project, session.token, TicketRequest(purpose="upload"))
        document = service.upload(
            service.consume(ticket.token, "upload"),
            (ROOT / "fixtures/uploads/estimate-scan.pdf").read_bytes(),
        )
        with service.db.connection() as connection:
            connection.execute(
                "UPDATE guest_review.jobs SET status='processing',attempts=1, "
                "lease_token='abandoned-test-lease',lease_until=now()-interval '1 second' "
                "WHERE project_id=%s",
                (project,),
            )
        subprocess.run(
            ["docker", "compose", "-f", "infra/guest.compose.yml", "restart", "api"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=60,
        )
        import time

        deadline = time.monotonic() + 90
        with httpx.Client(
            base_url="http://127.0.0.1:8106",
            headers={"Authorization": "Bearer " + session.token},
            timeout=10,
        ) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(f"/api/guest/projects/{project}")
                    if (
                        response.status_code == 200
                        and response.json()["project"]["documents"][0]["status"] == "ready"
                    ):
                        break
                except httpx.TransportError:
                    pass
                time.sleep(1)
            else:
                pytest.fail("Job did not recover after API restart")
            data = response.json()
            assert data["project"]["documents"][0]["id"] == document.id
            assert data["project"]["documents"][0]["candidates"][0]["amount"] == "10000.00"
    finally:
        service.delete(project, session.token)


def test_deleted_project_cannot_be_resurrected_by_worker(service):
    session = service.db.start(None)
    ticket = service.ticket(session.project_id, session.token, TicketRequest(purpose="upload"))
    pending = service.consume(ticket.token, "upload")
    service.delete(session.project_id, session.token)
    with pytest.raises(Problem):
        service.upload(pending, (ROOT / "fixtures/uploads/estimate.pdf").read_bytes())
    with service.db.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM guest_review.projects WHERE id=%s", (session.project_id,)
            ).fetchone()["n"]
            == 0
        )
        connection.execute(
            "UPDATE guest_review.objects SET created_at=now()-interval '1 hour' "
            "WHERE project_id=%s",
            (session.project_id,),
        )
    service.cleanup()
