"""Authenticated guest APIs. The frontend BFF keeps the session secret HttpOnly."""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .calculation import ProjectResponse
from .casework_models import (
    AttachmentCommand,
    CardCommand,
    ReplyCommand,
    ReplyEdit,
    Snapshot,
    SnapshotSummary,
)
from .export_store import ExportRequest, Exports
from .extraction import MAX_BYTES
from .models import Document, ReviewCommand, Session, Ticket, TicketRequest
from .recheck_models import Comparison, RunRecheck, SavePackage, StartRecheck
from .recheck_store import Rechecks
from .service import Reviews

router = APIRouter(prefix="/api/guest", tags=["guest reviews"])
bearer = HTTPBearer(auto_error=False)


def token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    return credentials.credentials if credentials else ""


def service(request: Request) -> Reviews:
    reviews: Reviews | None = getattr(request.app.state, "reviews", None)
    if reviews is None:
        raise HTTPException(503, "Private review storage is not configured")
    return reviews


Service = Annotated[Reviews, Depends(service)]
Secret = Annotated[str, Depends(token)]


@router.post("/session", response_model=Session)
def start(reviews: Service, secret: Secret) -> Session:
    """For the trusted BFF: move token to a Secure HttpOnly cookie; never return it to JS."""
    return reviews.db.start(secret or None)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def project(project_id: str, reviews: Service, secret: Secret) -> ProjectResponse:
    return reviews.project(project_id, secret)


@router.post("/projects/{project_id}/review", response_model=ProjectResponse)
def review(
    project_id: str, command: ReviewCommand, reviews: Service, secret: Secret
) -> ProjectResponse:
    return reviews.review(project_id, secret, command)


@router.get("/projects/{project_id}/snapshots", response_model=list[SnapshotSummary])
def snapshots(project_id: str, reviews: Service, secret: Secret) -> list[SnapshotSummary]:
    return reviews.casework.snapshots(project_id, secret)


@router.get("/projects/{project_id}/snapshots/{snapshot_id}", response_model=Snapshot)
def snapshot(project_id: str, snapshot_id: str, reviews: Service, secret: Secret) -> Snapshot:
    """Read the stored calculation verbatim. No current normalization or ledger call."""
    return reviews.casework.snapshot(project_id, secret, snapshot_id)


@router.post("/projects/{project_id}/replies", response_model=ProjectResponse)
def reply(
    project_id: str, command: ReplyCommand, reviews: Service, secret: Secret
) -> ProjectResponse:
    return reviews.casework.mutate(project_id, secret, "reply", command)


@router.post("/projects/{project_id}/replies/{reply_id}/edit", response_model=ProjectResponse)
def edit_reply(
    project_id: str, reply_id: str, command: ReplyEdit, reviews: Service, secret: Secret
) -> ProjectResponse:
    return reviews.casework.mutate(project_id, secret, "edit_reply", command, reply_id)


@router.post("/projects/{project_id}/questions/{question_id}/state", response_model=ProjectResponse)
def question_state(
    project_id: str, question_id: str, command: CardCommand, reviews: Service, secret: Secret
) -> ProjectResponse:
    return reviews.casework.mutate(project_id, secret, "question_state", command, question_id)


@router.post("/projects/{project_id}/attachments", response_model=ProjectResponse)
def attachments(
    project_id: str, command: AttachmentCommand, reviews: Service, secret: Secret
) -> ProjectResponse:
    return reviews.casework.mutate(project_id, secret, "attachments", command)


@router.post("/projects/{project_id}/rechecks", response_model=ProjectResponse)
def start_recheck(
    project_id: str, command: StartRecheck, reviews: Service, secret: Secret
) -> ProjectResponse:
    return Rechecks(reviews.db).mutate(project_id, secret, command)


@router.post("/projects/{project_id}/rechecks/{draft_id}/package", response_model=ProjectResponse)
def save_package(
    project_id: str, draft_id: str, command: SavePackage, reviews: Service, secret: Secret
) -> ProjectResponse:
    return Rechecks(reviews.db).mutate(project_id, secret, command, draft_id)


@router.post("/projects/{project_id}/rechecks/{draft_id}/run", response_model=ProjectResponse)
def run_recheck(
    project_id: str, draft_id: str, command: RunRecheck, reviews: Service, secret: Secret
) -> ProjectResponse:
    return Rechecks(reviews.db).mutate(project_id, secret, command, draft_id)


@router.get("/projects/{project_id}/comparisons/{comparison_id}", response_model=Comparison)
def comparison(project_id: str, comparison_id: str, reviews: Service, secret: Secret) -> Comparison:
    """Serve the immutable comparison without rerunning its algorithm or the ledger."""
    return Rechecks(reviews.db).comparison(project_id, secret, comparison_id)


@router.post("/projects/{project_id}/tickets", response_model=Ticket)
def ticket(project_id: str, command: TicketRequest, reviews: Service, secret: Secret) -> Ticket:
    return reviews.ticket(project_id, secret, command)


@router.post("/projects/{project_id}/exports", response_model=Ticket)
def export_ticket(
    project_id: str, command: ExportRequest, reviews: Service, secret: Secret
) -> Ticket:
    """Authorize an immutable snapshot/comparison PDF; not a draft or current form."""
    return Exports(reviews.db).ticket(project_id, secret, command)


@router.get(
    "/export",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def export_download(reviews: Service, secret: Secret) -> Response:
    """Direct binary download using a single-use PDF-only Authorization ticket (never a URL)."""
    content, name = Exports(reviews.db).download(reviews.consume(secret, "pdf"))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Security-Policy": "sandbox",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.delete("/projects/{project_id}", status_code=204)
def delete(project_id: str, reviews: Service, secret: Secret) -> Response:
    reviews.delete(project_id, secret)
    return Response(status_code=204)


@router.put(
    "/transfer",
    response_model=Document,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(request: Request, reviews: Service, secret: Secret) -> Document:
    """Single-use, upload-only ticket. Actual format and all quotas are checked server-side."""
    transfer = await run_in_threadpool(reviews.consume, secret, "upload")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Each file must be at most 10 MiB")
        body.extend(chunk)
    return await run_in_threadpool(reviews.upload, transfer, bytes(body))


@router.get(
    "/transfer",
    responses={200: {"content": {"application/pdf": {}, "image/png": {}, "image/jpeg": {}}}},
)
def download(reviews: Service, secret: Secret) -> Response:
    """Single-use, file-scoped ticket; access is rechecked after deletion/expiry."""
    transfer = reviews.consume(secret, "download")
    content, media_type = reviews.download(transfer)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment; filename=original",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/maintenance/cleanup", status_code=204, tags=["maintenance"])
def cleanup(reviews: Service, x_cleanup_secret: Annotated[str, Header()] = "") -> Response:
    configured = os.environ.get("REVIEW_CLEANUP_SECRET", "")
    if len(configured) < 32 or not secrets.compare_digest(x_cleanup_secret, configured):
        raise HTTPException(404, "Not found")
    reviews.cleanup()
    return Response(status_code=204)
