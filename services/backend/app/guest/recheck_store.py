"""Transactional owner-scoped recheck drafts and immutable comparisons."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .calculation import ProjectResponse
from .casework import fingerprint
from .casework_models import CaseworkView, Snapshot
from .casework_store import remember, replay, response, save_review
from .comparison import compare
from .database import Connection, Database
from .models import Problem, Project
from .recheck_models import (
    Comparison,
    ComparisonSummary,
    Package,
    RecheckDraft,
    RecheckView,
    RunRecheck,
    SavePackage,
    StartRecheck,
)


def basis(project: Project, state: CaseworkView) -> str:
    # Include reply revisions and evidence assessments; the frozen result never changes.
    return fingerprint(
        [
            project.model_dump(mode="json"),
            [r.model_dump(mode="json") for r in state.replies],
            [c.model_dump(mode="json") for c in state.cards],
        ]
    )


def recheck_view(connection: Connection, project: Project, state: CaseworkView) -> RecheckView:
    drafts = [
        RecheckDraft.model_validate(r["data"])
        for r in connection.execute(
            "SELECT data FROM guest_review.rechecks WHERE project_id=%s ORDER BY created_at,id",
            (project.id,),
        )
    ]
    rows = connection.execute(
        "SELECT data FROM guest_review.comparisons WHERE project_id=%s ORDER BY created_at DESC,id",
        (project.id,),
    )
    current_basis = basis(project, state)
    summaries = []
    for row in rows:
        saved = Comparison.model_validate(row["data"])
        summaries.append(
            ComparisonSummary(
                id=saved.id,
                base_snapshot_id=saved.base_snapshot_id,
                new_snapshot_id=saved.new_snapshot_id,
                created_at=saved.created_at,
                current=saved.basis_fingerprint == current_basis,
                preliminary=bool(saved.payload["result"]["preliminary"]),
            )
        )
    return RecheckView(drafts=drafts, comparisons=summaries)


def snapshot(connection: Connection, project_id: str, snapshot_id: str) -> Snapshot:
    row = connection.execute(
        "SELECT data FROM guest_review.snapshots WHERE project_id=%s AND id=%s",
        (project_id, snapshot_id),
    ).fetchone()
    if not row:
        raise Problem(404, "Calculation snapshot not found in this review")
    return Snapshot.model_validate(row["data"])


def validate_package(
    project: Project, state: CaseworkView, old: Snapshot, package: Package
) -> list[dict[str, Any]]:
    if len(package.file_ids) != len(set(package.file_ids)) or not set(package.file_ids) <= {
        d.id for d in project.documents
    }:
        raise Problem(404, "Package document not found in this review or duplicated")
    reply_map = {r.id: r for r in state.replies}
    versions = []
    seen: set[str] = set()
    for ref in package.replies:
        reply = reply_map.get(ref.reply_id)
        if reply is None or ref.version > len(reply.versions) or ref.reply_id in seen:
            raise Problem(404, "Reply/version not found in this review or duplicated")
        seen.add(ref.reply_id)
        versions.append(
            {
                "reply_id": reply.id,
                "question_ids": reply.question_ids,
                **reply.versions[ref.version - 1].model_dump(mode="json"),
            }
        )
    old_request = old.payload["project"].get("review", {}).get("command", {}).get("request_id")
    if package.old_request_id != old_request:
        raise Problem(422, "Compare the request actually selected in the base snapshot")
    current_candidates = {c.id: c for d in project.documents for c in d.candidates}
    if package.new_request_id not in current_candidates:
        raise Problem(404, "New request not found in this review")
    if current_candidates[package.new_request_id].file_id not in package.file_ids:
        raise Problem(422, "Include the compared invoice in the recheck package")
    same = package.old_request_id == package.new_request_id
    if (package.relationship == "same") != same:
        raise Problem(422, "Use 'same invoice' only when reviewing the original request")
    questions = {c["id"] for c in old.payload.get("discussion", {}).get("cards", [])}
    if not {link.question_id for link in package.question_links} <= questions:
        raise Problem(404, "Question does not belong to the selected base snapshot")
    return versions


class Rechecks:
    def __init__(self, db: Database) -> None:
        self.db = db

    def comparison(self, project_id: str, token: str, comparison_id: str) -> Comparison:
        with self.db.connection() as connection:
            self.db.load(connection, project_id, token, lock=True)
            row = connection.execute(
                "SELECT data FROM guest_review.comparisons WHERE project_id=%s AND id=%s",
                (project_id, comparison_id),
            ).fetchone()
            if not row:
                raise Problem(404, "Comparison not found")
            return Comparison.model_validate(row["data"])

    def mutate(
        self,
        project_id: str,
        token: str,
        command: StartRecheck | SavePackage | RunRecheck,
        draft_id: str = "",
    ) -> ProjectResponse:
        with self.db.connection() as connection:
            project = self.db.load(connection, project_id, token, lock=True)
            operation = type(command).__name__ + ":" + draft_id
            if replay(connection, project_id, command.mutation_id, operation, command):
                return response(connection, project)
            data = response(connection, project)
            now = datetime.now(UTC)
            if isinstance(command, StartRecheck):
                old = snapshot(connection, project_id, command.base_snapshot_id)
                if len(data.rechecks.drafts) >= 20:
                    raise Problem(429, "This temporary review supports at most 20 recheck packages")
                request = (
                    old.payload["project"].get("review", {}).get("command", {}).get("request_id")
                )
                draft = RecheckDraft(
                    id=str(uuid4()),
                    base_snapshot_id=old.summary.id,
                    created_at=now,
                    updated_at=now,
                    package=Package(
                        old_request_id=request, new_request_id=request, relationship="same"
                    ),
                )
            else:
                found = next((d for d in data.rechecks.drafts if d.id == draft_id), None)
                if found is None:
                    raise Problem(404, "Recheck package not found")
                draft = found
                if draft.status != "draft" or draft.version != command.expected_version:
                    raise Problem(
                        409, "Recheck package changed or is already completed. Reload it."
                    )
                old = snapshot(connection, project_id, draft.base_snapshot_id)
                if isinstance(command, SavePackage):
                    validate_package(project, data.casework, old, command.package)
                    draft.package = command.package
                else:
                    versions = validate_package(project, data.casework, old, draft.package)
                    if command.review.request_id != draft.package.new_request_id:
                        raise Problem(
                            422, "The financial review must select the compared current request"
                        )
                    expected_pair = (draft.package.old_request_id, draft.package.new_request_id)
                    links = {
                        (v.old_request_id, v.new_request_id)
                        for v in command.review.request_versions
                    }
                    if draft.package.relationship == "corrected" and expected_pair not in links:
                        raise Problem(
                            422, "Explicitly confirm this corrected request's predecessor"
                        )
                    if (
                        draft.package.relationship in ("unknown", "separate")
                        and expected_pair in links
                    ):
                        raise Problem(
                            422, "A separate/unknown invoice must not claim a confirmed replacement"
                        )
                    # All new source files are explicitly selected; original basis remains frozen.
                    old_files = {d["id"] for d in old.payload["project"]["documents"]}
                    if {d.id for d in project.documents} - old_files - set(draft.package.file_ids):
                        raise Problem(
                            422,
                            "Include every added source document in the package before rechecking",
                        )
                    data = save_review(connection, self.db, project, command.review)
                    frozen = snapshot(
                        connection, project_id, data.casework.latest_snapshot_id or ""
                    )
                    result = compare(old.payload, frozen.payload, draft.package)
                    saved = Comparison(
                        id=str(uuid4()),
                        base_snapshot_id=old.summary.id,
                        new_snapshot_id=frozen.summary.id,
                        created_at=now,
                        basis_fingerprint=basis(project, data.casework),
                        payload={
                            "package": draft.package.model_dump(mode="json"),
                            "reply_versions": versions,
                            "documents": [
                                d.model_dump(mode="json")
                                for d in project.documents
                                if d.id in draft.package.file_ids
                            ],
                            "result": result,
                        },
                    )
                    connection.execute(
                        "INSERT INTO guest_review.comparisons(id,project_id,data) VALUES "
                        "(%s,%s,%s::jsonb)",
                        (saved.id, project_id, saved.model_dump_json()),
                    )
                    draft.status, draft.comparison_id = "completed", saved.id
                draft.version += 1
                draft.updated_at = now
            connection.execute(
                "INSERT INTO guest_review.rechecks(id,project_id,data) VALUES (%s,%s,%s::jsonb) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (draft.id, project_id, draft.model_dump_json()),
            )
            remember(connection, project_id, command.mutation_id, operation, command, draft.id)
            return response(connection, project, data.result)
