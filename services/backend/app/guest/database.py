"""PostgreSQL transactions, ownership, revision checks, durable jobs and deletion outbox."""

import hashlib
import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .models import Problem, Project, Session

Connection = psycopg.Connection[dict[str, Any]]


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Database:
    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with psycopg.connect(
            self.url, row_factory=dict_row, connect_timeout=8, options="-c statement_timeout=30000"
        ) as connection:
            yield connection

    def migrate(self) -> None:
        with self.connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(631600)")
            connection.execute(files(__package__).joinpath("schema.sql").read_text("utf-8"))

    def start(self, token: str | None) -> Session:
        with self.connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(631601)")
            if token:
                found = connection.execute(
                    "SELECT id FROM guest_review.projects WHERE owner_hash=%s AND expires_at>now()",
                    (digest(token),),
                ).fetchone()
                if found:
                    return Session(token=token, project_id=found["id"])
            count = connection.execute(
                "SELECT count(*) AS n FROM guest_review.projects WHERE expires_at>now()"
            ).fetchone()
            if count and count["n"] >= 10:
                raise Problem(429, "The free review service is at capacity. Please try later.")
            token = secrets.token_urlsafe(32)
            now = datetime.now(UTC)
            expiry = now + timedelta(hours=24)
            project = Project(id=str(uuid4()), created_at=now, expires_at=expiry)
            connection.execute(
                "INSERT INTO guest_review.sessions VALUES (%s,%s)", (digest(token), expiry)
            )
            connection.execute(
                "INSERT INTO guest_review.projects VALUES (%s,%s,%s,%s::jsonb)",
                (project.id, digest(token), expiry, project.model_dump_json()),
            )
            return Session(token=token, project_id=project.id)

    def load(
        self,
        connection: Connection,
        project_id: str,
        token: str | None,
        *,
        lock: bool = False,
        worker: bool = False,
    ) -> Project:
        sql = (
            "SELECT data,(SELECT data FROM guest_review.invoice_state "
            "WHERE project_id=guest_review.projects.id) AS invoice_state "
            "FROM guest_review.projects WHERE id=%s AND expires_at>now()"
        )
        if lock:
            # Read sidecar after obtaining the project lock. A correlated subquery in
            # SELECT FOR UPDATE can see the pre-wait MVCC snapshot while PostgreSQL
            # returns the newly committed project row after a concurrent save.
            sql = "SELECT data FROM guest_review.projects WHERE id=%s AND expires_at>now()"
        parameters: tuple[str, ...] = (project_id,)
        if not worker:
            sql += " AND owner_hash=%s"
            parameters += (digest(token or ""),)
        if lock:
            sql += " FOR UPDATE"
        row = connection.execute(sql, parameters).fetchone()
        if row is None:
            raise Problem(404, "Review not found or expired")
        data = row["data"]
        if lock:
            saved = connection.execute(
                "SELECT data FROM guest_review.invoice_state WHERE project_id=%s", (project_id,)
            ).fetchone()
            sidecar = saved["data"] if saved else {}
        else:
            sidecar = row.get("invoice_state") or {}
        for document in data["documents"]:
            document["invoice_proposals"] = sidecar.get("proposals", {}).get(document["id"], [])
        if data.get("review") and data["review"]["id"] == sidecar.get("review_id"):
            data["review"]["command"].update(sidecar.get("review_fields", {}))
        return Project.model_validate_json(json.dumps(data))

    def save(self, connection: Connection, project: Project) -> None:
        # Keep the original JSON shape readable by stage 7 during a rollback.
        data = project.model_dump(mode="json")
        proposals = {d["id"]: d.pop("invoice_proposals") for d in data["documents"]}
        review = data.get("review")
        fields = (
            {key: review["command"].pop(key) for key in ("invoices", "request_versions")}
            if review
            else {}
        )
        sidecar = {
            "proposals": proposals,
            "review_id": review["id"] if review else None,
            "review_fields": fields,
        }
        connection.execute(
            "WITH saved AS (UPDATE guest_review.projects SET data=%s::jsonb "
            "WHERE id=%s RETURNING id) "
            "INSERT INTO guest_review.invoice_state(project_id,data) "
            "SELECT id,%s::jsonb FROM saved "
            "ON CONFLICT(project_id) DO UPDATE SET data=excluded.data",
            (json.dumps(data), project.id, json.dumps(sidecar)),
        )

    def read(self, project_id: str, token: str) -> Project:
        with self.connection() as connection:
            return self.load(connection, project_id, token)

    def remove(self, connection: Connection, project_id: str) -> None:
        # Access and all content/decisions/jobs disappear in this transaction.
        # Object keys remain only in the retryable deletion outbox.
        connection.execute(
            "UPDATE guest_review.objects SET state='garbage', "
            "created_at=now()-interval '1 day' WHERE project_id=%s",
            (project_id,),
        )
        owner = connection.execute(
            "DELETE FROM guest_review.projects WHERE id=%s RETURNING owner_hash", (project_id,)
        ).fetchone()
        if owner:
            connection.execute(
                "DELETE FROM guest_review.sessions s WHERE secret_hash=%s AND NOT EXISTS "
                "(SELECT 1 FROM guest_review.projects p WHERE p.owner_hash=s.secret_hash)",
                (owner["owner_hash"],),
            )

    def expire(self) -> None:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM guest_review.projects WHERE expires_at<=now() "
                "FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for row in rows:
                self.remove(connection, row["id"])
            connection.execute("DELETE FROM guest_review.tickets WHERE expires_at<=now()")
            connection.execute(
                "DELETE FROM guest_review.sessions s WHERE expires_at<=now() "
                "AND NOT EXISTS (SELECT 1 FROM guest_review.projects p "
                "WHERE p.owner_hash=s.secret_hash)"
            )
