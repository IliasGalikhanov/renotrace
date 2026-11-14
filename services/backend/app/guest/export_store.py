"""Single-use PDF tickets and read-only access to frozen, owner-scoped evidence."""

import secrets
from typing import Annotated, Any, Literal

from pydantic import Field

from .database import Connection, Database, digest
from .models import Model, Problem, Ticket
from .pdf_report import ReportBasis, render_pdf
from .recheck_models import Comparison
from .recheck_store import snapshot


class ExportRequest(Model):
    kind: Literal["snapshot", "comparison"]
    result_id: Annotated[
        str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    ]


def load_basis(connection: Connection, project_id: str, request: ExportRequest) -> ReportBasis:
    if request.kind == "snapshot":
        return ReportBasis(snapshot(connection, project_id, request.result_id))
    row = connection.execute(
        "SELECT data FROM guest_review.comparisons WHERE project_id=%s AND id=%s",
        (project_id, request.result_id),
    ).fetchone()
    if row is None:
        raise Problem(404, "Completed comparison not found")
    comparison = Comparison.model_validate(row["data"])
    return ReportBasis(
        selected=snapshot(connection, project_id, comparison.new_snapshot_id),
        previous=snapshot(connection, project_id, comparison.base_snapshot_id),
        comparison=comparison,
    )


class Exports:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ticket(self, project_id: str, secret: str, request: ExportRequest) -> Ticket:
        with self.db.connection() as connection:
            self.db.load(connection, project_id, secret, lock=True)
            load_basis(connection, project_id, request)
            count = connection.execute(
                "SELECT count(*) AS n FROM guest_review.tickets "
                "WHERE project_id=%s AND expires_at>now()",
                (project_id,),
            ).fetchone()
            if count and count["n"] >= 20:
                raise Problem(429, "Too many pending transfers. Wait a few minutes.")
            token = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO guest_review.tickets VALUES (%s,%s,'pdf',%s,%s,"
                "now()+interval '5 minutes')",
                (digest(token), project_id, request.result_id, request.kind),
            )
            return Ticket(token=token)

    def download(self, ticket: dict[str, Any]) -> tuple[bytes, str]:
        request = ExportRequest(kind=ticket["name"], result_id=ticket["file_id"])
        with self.db.connection() as connection:
            # Only authorization reads today's project. All content comes from frozen rows.
            self.db.load(connection, ticket["project_id"], None, lock=True, worker=True)
            basis = load_basis(connection, ticket["project_id"], request)
        content = render_pdf(basis)
        # Revocation/expiry during rendering must also fail closed, with no saved PDF file.
        with self.db.connection() as connection:
            self.db.load(connection, ticket["project_id"], None, lock=True, worker=True)
        return content, f"renotrace-{request.kind}-{request.result_id}.pdf"
