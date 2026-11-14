"""Guest operations and a restartable, leased PostgreSQL extraction queue."""

import json
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

from .calculation import ProjectResponse, result_for, validate_command
from .database import Database, digest
from .extraction import semantic_candidates
from .models import Document, Page, Problem, ReviewCommand, SavedReview, Ticket, TicketRequest
from .storage import Objects


def parse_process(data: bytes, operation: str, page: int = 1) -> dict[str, Any]:
    try:
        process = subprocess.run(
            [sys.executable, "-m", "app.guest.file_worker", operation, str(page)],
            input=data,
            capture_output=True,
            timeout=70 if operation == "page" else 20,
            check=True,
        )
        result: dict[str, Any] = json.loads(process.stdout)
        return result
    except (subprocess.SubprocessError, ValueError) as error:
        raise Problem(
            422,
            "Unable to read this document safely. Check that it is not damaged, "
            "password-protected, over 20 pages or oversized.",
        ) from error


class Reviews:
    def __init__(self, database: Database, objects: Objects) -> None:
        self.db = database
        self.objects = objects

    def project(self, project_id: str, token: str) -> ProjectResponse:
        project = self.db.read(project_id, token)
        return ProjectResponse(project=project, result=result_for(project))

    def ticket(self, project_id: str, token: str, command: TicketRequest) -> Ticket:
        with self.db.connection() as connection:
            project = self.db.load(connection, project_id, token, lock=True)
            if command.purpose == "download" and command.file_id not in {
                d.id for d in project.documents
            }:
                raise Problem(404, "Document not found")
            count = connection.execute(
                "SELECT count(*) AS n FROM guest_review.tickets "
                "WHERE project_id=%s AND expires_at>now()",
                (project_id,),
            ).fetchone()
            if count and count["n"] >= 20:
                raise Problem(429, "Too many pending transfers. Wait a few minutes.")
            secret = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO guest_review.tickets VALUES (%s,%s,%s,%s,%s,"
                "now()+interval '5 minutes')",
                (digest(secret), project_id, command.purpose, command.file_id, command.name),
            )
            return Ticket(token=secret)

    def consume(self, token: str, purpose: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute(
                "DELETE FROM guest_review.tickets t USING guest_review.projects p "
                "WHERE t.project_id=p.id AND t.secret_hash=%s AND t.purpose=%s "
                "AND t.expires_at>now() AND p.expires_at>now() RETURNING t.*",
                (digest(token), purpose),
            ).fetchone()
            if row is None:
                raise Problem(404, "Transfer not found or expired. Request a new transfer.")
            return row

    def upload(self, ticket: dict[str, Any], data: bytes) -> Document:
        import hashlib

        inspected = parse_process(data, "inspect")
        checksum = hashlib.sha256(data).hexdigest()
        file_id = str(uuid4())
        project_id = ticket["project_id"]
        key = f"{project_id}/{file_id}"
        # Reserve an outbox key before writing an object. A DB failure cannot orphan private files.
        with self.db.connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(631602)")
            total = connection.execute(
                "SELECT coalesce(sum(size),0) AS n FROM guest_review.objects"
            ).fetchone()
            if total and total["n"] + len(data) > 400 * 1024 * 1024:
                raise Problem(429, "The free storage allowance is full. Please try later.")
            connection.execute(
                "INSERT INTO guest_review.objects(key,project_id,file_id,size,state) "
                "VALUES (%s,%s,%s,%s,'garbage')",
                (key, project_id, file_id, len(data)),
            )
        with self.db.connection() as connection:
            project = self.db.load(connection, project_id, None, lock=True, worker=True)
            for existing in project.documents:
                if existing.checksum == checksum:
                    connection.execute("DELETE FROM guest_review.objects WHERE key=%s", (key,))
                    return existing
            if (
                len(project.documents) >= 20
                or sum(d.size for d in project.documents) + len(data) > 100 * 1024 * 1024
            ):
                raise Problem(422, "A review supports at most 20 files and 100 MiB in total")
            if sum(d.page_count for d in project.documents) + inspected["pages"] > 50:
                raise Problem(422, "A review supports at most 50 pages")
            document = Document(
                id=file_id,
                name=ticket["name"],
                checksum=checksum,
                size=len(data),
                media_type=inspected["media_type"],
                page_count=inspected["pages"],
            )
            self.objects.put(key, data, document.media_type)
            project.documents.append(document)
            project.revision += 1
            self.db.save(connection, project)
            connection.execute(
                "UPDATE guest_review.objects SET state='active' WHERE key=%s", (key,)
            )
            connection.execute(
                "INSERT INTO guest_review.jobs(id,project_id,file_id) VALUES (%s,%s,%s)",
                (str(uuid4()), project_id, file_id),
            )
            return document

    def download(self, ticket: dict[str, Any]) -> tuple[bytes, str]:
        with self.db.connection() as connection:
            # Hold the project lock so deletion cannot revoke access midway through authorization.
            project = self.db.load(connection, ticket["project_id"], None, lock=True, worker=True)
            document = next((d for d in project.documents if d.id == ticket["file_id"]), None)
            if document is None:
                raise Problem(404, "Document not found")
            return self.objects.get(f"{project.id}/{document.id}"), document.media_type

    def review(self, project_id: str, token: str, command: ReviewCommand) -> ProjectResponse:
        with self.db.connection() as connection:
            project = self.db.load(connection, project_id, token, lock=True)
            if any(d.status in ("queued", "processing") for d in project.documents):
                raise Problem(409, "Wait for document processing before saving your review")
            validate_command(project, command)
            project.revision += 1
            saved = SavedReview(
                id=str(uuid4()),
                basis_revision=project.revision,
                created_at=datetime.now(UTC),
                command=command,
            )
            project.review = saved
            try:
                result = result_for(project)
            except ValueError as error:
                raise Problem(
                    422, "These records or relationships conflict. Check their meanings and links."
                ) from error
            self.db.save(connection, project)
            connection.execute(
                "INSERT INTO guest_review.audit(id,project_id,data) VALUES (%s,%s,%s::jsonb)",
                (saved.id, project.id, saved.model_dump_json()),
            )
            return ProjectResponse(project=project, result=result)

    def delete(self, project_id: str, token: str) -> None:
        with self.db.connection() as connection:
            self.db.load(connection, project_id, token, lock=True)
            self.db.remove(connection, project_id)
        self.cleanup()

    def cleanup(self) -> None:
        self.db.expire()
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT key FROM guest_review.objects WHERE state='garbage' "
                "AND created_at<now()-interval '10 minutes' FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for row in rows:
                self.objects.delete(row["key"])
                connection.execute("DELETE FROM guest_review.objects WHERE key=%s", (row["key"],))

    def work_once(self) -> bool:
        with self.db.connection() as connection:
            job = connection.execute(
                "SELECT j.* FROM guest_review.jobs j JOIN guest_review.projects p "
                "ON p.id=j.project_id WHERE p.expires_at>now() AND (j.status='queued' OR "
                "(j.status='processing' AND j.lease_until<now())) ORDER BY j.id "
                "FOR UPDATE OF j SKIP LOCKED LIMIT 1"
            ).fetchone()
            if job is None:
                return False
            lease = secrets.token_hex(16)
            connection.execute(
                "UPDATE guest_review.jobs SET status='processing', attempts=attempts+1, "
                "lease_token=%s, lease_until=now()+interval '120 seconds' WHERE id=%s",
                (lease, job["id"]),
            )
        try:
            if job["attempts"] >= 2:
                raise Problem(422, "Processing retry limit reached")
            with self.db.connection() as connection:
                project = self.db.load(connection, job["project_id"], None, lock=True, worker=True)
                document = next(d for d in project.documents if d.id == job["file_id"])
                document.status = "processing"
                self.db.save(connection, project)
            data = self.objects.get(f"{project.id}/{document.id}")
            for number in range(len(document.pages) + 1, document.page_count + 1):
                page = Page.model_validate(parse_process(data, "page", number))
                candidates = semantic_candidates(document.id, page)
                with self.db.connection() as connection:
                    # Every checkpoint rechecks existence, expiration and lease fencing.
                    project = self.db.load(
                        connection, job["project_id"], None, lock=True, worker=True
                    )
                    owned = connection.execute(
                        "UPDATE guest_review.jobs SET lease_until=now()+interval '120 seconds' "
                        "WHERE id=%s AND lease_token=%s AND status='processing' RETURNING id",
                        (job["id"], lease),
                    ).fetchone()
                    if owned is None:
                        return True
                    document = next(d for d in project.documents if d.id == job["file_id"])
                    if sum(len(d.candidates) for d in project.documents) + len(candidates) > 150:
                        raise Problem(422, "Too many candidate values; use a shorter document")
                    document.pages.append(page)
                    document.candidates.extend(candidates)
                    project.revision += 1
                    self.db.save(connection, project)
            with self.db.connection() as connection:
                project = self.db.load(connection, job["project_id"], None, lock=True, worker=True)
                owned = connection.execute(
                    "UPDATE guest_review.jobs SET status='done' "
                    "WHERE id=%s AND lease_token=%s RETURNING id",
                    (job["id"], lease),
                ).fetchone()
                if owned:
                    document = next(d for d in project.documents if d.id == job["file_id"])
                    document.status = "ready"
                    self.db.save(connection, project)
        except Exception:
            # Never log provider responses, file contents, tokens or connection strings.
            with self.db.connection() as connection:
                exists = connection.execute(
                    "SELECT id FROM guest_review.projects WHERE id=%s "
                    "AND expires_at>now() FOR UPDATE",
                    (job["project_id"],),
                ).fetchone()
                if exists:
                    status = "queued" if job["attempts"] < 1 else "failed"
                    owned = connection.execute(
                        "UPDATE guest_review.jobs SET status=%s WHERE id=%s "
                        "AND lease_token=%s RETURNING id",
                        (status, job["id"], lease),
                    ).fetchone()
                    if owned:
                        project = self.db.load(connection, job["project_id"], None, worker=True)
                        document = next(d for d in project.documents if d.id == job["file_id"])
                        document.status = "queued" if status == "queued" else "failed"
                        document.error = (
                            "Extraction failed after bounded retries. Upload a clearer document."
                            if status == "failed"
                            else None
                        )
                        self.db.save(connection, project)
        return True

    def run(self, stop: Event) -> None:
        cleanup_counter = 0
        while not stop.is_set():
            try:
                if cleanup_counter % 30 == 0:
                    self.cleanup()
                worked = self.work_once()
            except Exception:
                worked = False
            cleanup_counter += 1
            stop.wait(0.2 if worked else 2)
