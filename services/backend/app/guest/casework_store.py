"""Owner-locked PostgreSQL casework; discussion never writes financial inputs."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from .calculation import ProjectResponse, ReviewResult, result_for, validate_command
from .casework import assess, event, fingerprint, reconcile
from .casework_models import (
    CONTRACT_VERSION,
    AttachmentCommand,
    CardCommand,
    CaseworkView,
    QuestionCard,
    Reply,
    ReplyCommand,
    ReplyEdit,
    ReplyVersion,
    Snapshot,
    SnapshotSummary,
)
from .database import Connection, Database
from .models import Model, Problem, Project, ReviewCommand, SavedReview


def view(connection: Connection, project_id: str) -> CaseworkView:
    cards = [
        QuestionCard.model_validate(r["data"])
        for r in connection.execute(
            "SELECT data FROM guest_review.question_cards WHERE project_id=%s ORDER BY id",
            (project_id,),
        )
    ]
    replies = [
        Reply.model_validate(r["data"])
        for r in connection.execute(
            "SELECT data FROM guest_review.replies WHERE project_id=%s ORDER BY id",
            (project_id,),
        )
    ]
    snapshots = [
        SnapshotSummary.model_validate(r["summary"])
        for r in connection.execute(
            "SELECT data->'summary' AS summary FROM guest_review.snapshots "
            "WHERE project_id=%s ORDER BY created_at DESC,id",
            (project_id,),
        )
    ]
    legacy = connection.execute(
        "SELECT count(*) AS n FROM guest_review.audit a WHERE a.project_id=%s AND NOT EXISTS "
        "(SELECT 1 FROM guest_review.snapshots s WHERE s.id=a.id)",
        (project_id,),
    ).fetchone()
    return CaseworkView(
        cards=cards,
        replies=replies,
        snapshots=snapshots,
        latest_snapshot_id=snapshots[0].id if snapshots else None,
        legacy_audit_count=legacy["n"] if legacy else 0,
    )


def save_cards(connection: Connection, project: Project, cards: list[QuestionCard]) -> None:
    if len(cards) > 300:
        raise Problem(429, "This temporary review has reached its question history limit")
    # One round trip even for many cards on the remote free database.
    connection.execute(
        "INSERT INTO guest_review.question_cards(id,project_id,data) "
        "SELECT item->>'id',%s,item FROM jsonb_array_elements(%s::jsonb) AS item "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data "
        "WHERE guest_review.question_cards.data IS DISTINCT FROM excluded.data",
        (project.id, json.dumps([card.model_dump(mode="json") for card in cards])),
    )


def response(
    connection: Connection, project: Project, result: ReviewResult | None = None
) -> ProjectResponse:
    result = result or result_for(project)
    state = view(connection, project.id)
    if project.review:
        state.cards = reconcile(project, result, state.cards)
    save_cards(connection, project, state.cards)
    from .recheck_store import recheck_view

    return ProjectResponse(
        project=project,
        result=result,
        casework=state,
        rechecks=recheck_view(connection, project, state),
    )


def save_review(
    connection: Connection, db: Database, project: Project, command: ReviewCommand
) -> ProjectResponse:
    """One financial save path shared by initial reviews and explicit rechecks."""
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
    db.save(connection, project)
    connection.execute(
        "INSERT INTO guest_review.audit(id,project_id,data) VALUES (%s,%s,%s::jsonb)",
        (saved.id, project.id, saved.model_dump_json()),
    )
    data = response(connection, project, result)
    freeze(connection, data)
    return data


def replay(
    connection: Connection, project_id: str, mutation_id: str | None, operation: str, command: Model
) -> str | None:
    if mutation_id is None:
        return None
    row = connection.execute(
        "SELECT fingerprint,resource_id FROM guest_review.discussion_operations "
        "WHERE project_id=%s AND id=%s",
        (project_id, mutation_id),
    ).fetchone()
    if row:
        if row["fingerprint"] != fingerprint([operation, command.model_dump(mode="json")]):
            raise Problem(409, "This retry identifier was already used for different content")
        return str(row["resource_id"])
    count = connection.execute(
        "SELECT count(*) AS n FROM guest_review.discussion_operations WHERE project_id=%s",
        (project_id,),
    ).fetchone()
    if count and count["n"] >= 200:
        raise Problem(429, "This temporary review has reached its discussion operation limit")
    return None


def remember(
    connection: Connection,
    project_id: str,
    mutation_id: str | None,
    operation: str,
    command: Model,
    resource_id: str,
) -> None:
    if mutation_id:
        connection.execute(
            "INSERT INTO guest_review.discussion_operations VALUES (%s,%s,%s,%s)",
            (
                project_id,
                mutation_id,
                fingerprint([operation, command.model_dump(mode="json")]),
                resource_id,
            ),
        )


def freeze(connection: Connection, data: ProjectResponse) -> None:
    project = data.project
    if project.review is None:
        raise ValueError("A saved review is required")
    if len(data.casework.snapshots) >= 20:
        raise Problem(429, "This temporary review supports at most 20 saved calculations")
    summary = SnapshotSummary(
        id=project.review.id,
        created_at=project.review.created_at,
        financial_revision=project.revision,
        contract_version=CONTRACT_VERSION,
        remaining_cents=data.result.calculation.remaining_commitment_cents,
        question_count=len(data.result.questions),
    )
    frozen = Snapshot(
        summary=summary,
        payload={
            "project": project.model_dump(mode="json"),
            "result": data.result.model_dump(mode="json"),
            "discussion": {
                "cards": [c.model_dump(mode="json") for c in data.casework.cards],
                "replies": [r.model_dump(mode="json") for r in data.casework.replies],
            },
        },
    )
    connection.execute(
        "INSERT INTO guest_review.snapshots(id,project_id,data) VALUES (%s,%s,%s::jsonb)",
        (summary.id, project.id, frozen.model_dump_json()),
    )
    data.casework.snapshots.insert(0, summary)
    data.casework.latest_snapshot_id = summary.id
    data.casework.legacy_audit_count -= 1  # This audit row now has its full snapshot.


class Casework:
    def __init__(self, db: Database) -> None:
        self.db = db

    def snapshot(self, project_id: str, token: str, snapshot_id: str) -> Snapshot:
        with self.db.connection() as connection:
            self.db.load(connection, project_id, token, lock=True)
            row = connection.execute(
                "SELECT data FROM guest_review.snapshots WHERE project_id=%s AND id=%s",
                (project_id, snapshot_id),
            ).fetchone()
            if not row:
                raise Problem(404, "Calculation snapshot not found")
            return Snapshot.model_validate(row["data"])

    def snapshots(self, project_id: str, token: str) -> list[SnapshotSummary]:
        with self.db.connection() as connection:
            self.db.load(connection, project_id, token, lock=True)
            return view(connection, project_id).snapshots

    def mutate(
        self,
        project_id: str,
        token: str,
        operation: str,
        command: ReplyCommand | ReplyEdit | AttachmentCommand | CardCommand,
        entity_id: str = "",
    ) -> ProjectResponse:
        with self.db.connection() as connection:
            project = self.db.load(connection, project_id, token, lock=True)
            op = operation + ":" + entity_id
            if replay(connection, project_id, command.mutation_id, op, command):
                return response(connection, project)
            data = response(connection, project)
            cards = {c.id: c for c in data.casework.cards}
            replies = {r.id: r for r in data.casework.replies}
            file_ids = getattr(command, "file_ids", [])
            if not set(file_ids) <= {d.id for d in project.documents}:
                raise Problem(404, "Attachment not found in this review")
            question_ids = getattr(command, "question_ids", [entity_id])
            if isinstance(command, ReplyEdit):
                if entity_id not in replies:
                    raise Problem(404, "Reply not found")
                question_ids = replies[entity_id].question_ids
            if not set(question_ids) <= cards.keys():
                raise Problem(404, "Question not found in this review")
            resource_id = entity_id or str(uuid4())
            if isinstance(command, (ReplyCommand, ReplyEdit)):
                if not command.text.strip():
                    raise Problem(422, "Reply text must not be blank")
                if isinstance(command, ReplyEdit):
                    reply = replies[entity_id]
                    if command.expected_version != len(reply.versions):
                        raise Problem(409, "Reply changed. Reload before editing.")
                else:
                    reply = Reply(
                        id=resource_id, question_ids=sorted(set(question_ids)), versions=[]
                    )
                if len(reply.versions) >= 20:
                    raise Problem(429, "This reply has reached its version limit")
                version = len(reply.versions) + 1
                reply.versions.append(
                    ReplyVersion(
                        source_id=f"reply:{reply.id}:v{version}",
                        version=version,
                        text=command.text.strip(),
                        file_ids=sorted(set(file_ids)),
                        added_by=f"guest:{project.id}",
                        added_at=datetime.now(UTC),
                    )
                )
                connection.execute(
                    "INSERT INTO guest_review.replies VALUES (%s,%s,%s::jsonb) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (reply.id, project_id, reply.model_dump_json()),
                )
                for qid in reply.question_ids:
                    card = cards[qid]
                    card.reply_ids = sorted(set(card.reply_ids + [reply.id]))
                    card.file_ids = sorted(set(card.file_ids + file_ids))
                    card.version += 1
                    event(
                        card,
                        "reply_added" if version == 1 else "reply_edited",
                        f"Owner-reported contractor reply, version {version}.",
                        f"guest:{project.id}",
                        source_refs=[reply.versions[-1].source_id],
                    )
            elif isinstance(command, AttachmentCommand):
                for qid in set(question_ids):
                    card = cards[qid]
                    if set(file_ids) - set(card.file_ids):
                        card.file_ids = sorted(set(card.file_ids + file_ids))
                        card.version += 1
                        event(
                            card,
                            "files_attached",
                            "Existing documents linked for discussion; "
                            "financial facts still require review.",
                            f"guest:{project.id}",
                        )
            else:
                assess(
                    cards[entity_id],
                    command,
                    project,
                    data.result,
                    data.casework.latest_snapshot_id,
                )
            save_cards(connection, project, list(cards.values()))
            remember(connection, project_id, command.mutation_id, op, command, resource_id)
            return response(connection, project, data.result)
