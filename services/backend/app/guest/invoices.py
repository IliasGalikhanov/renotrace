"""Checked document arithmetic and lineage validation, not another ledger."""

from decimal import Decimal, InvalidOperation

from pydantic import Field

from app.ledger.models import MAX_CENTS

from .extraction import cents
from .invoice_models import InvoiceLine, InvoiceReview
from .models import Model, Problem, Project, ReviewCommand


class CheckedLine(Model):
    value: InvoiceLine
    amount_cents: int | None
    signed_cents: int | None
    source_ref: str
    review_source_ref: str
    origin: str
    original_text: str | None
    cash_event_id: str | None = None
    cash_evidence_refs: list[str] = Field(default_factory=list)


class Composition(Model):
    file_id: str
    request_id: str
    requested_cents: int | None
    accounted_cents: int
    unexplained_cents: int | None
    complete: bool
    lines: list[CheckedLine]
    issues: list[str] = Field(default_factory=list)


def bounded(value: int) -> int:
    if abs(value) > MAX_CENTS:
        raise Problem(422, "Invoice arithmetic exceeds the supported range")
    return value


def validate_invoices(project: Project, command: ReviewCommand) -> None:
    choices = {r.id: r for r in command.records}
    files = {c.id: d.id for d in project.documents for c in d.candidates}
    if len({i.file_id for i in command.invoices}) != len(command.invoices):
        raise Problem(422, "Review each invoice document only once")
    all_ids: set[str] = set()
    for invoice in command.invoices:
        document = next((d for d in project.documents if d.id == invoice.file_id), None)
        if document is None or files.get(invoice.request_id) != document.id:
            raise Problem(404, "Invoice/request not found in this review")
        if choices[invoice.request_id].kind != "payment_request":
            raise Problem(422, "Invoice composition requires a payment request")
        proposals = {p.id: p for p in document.invoice_proposals}
        proposal_ids = [line.proposal_id for line in invoice.lines if line.proposal_id]
        if len(proposal_ids) != len(set(proposal_ids)) or not set(proposal_ids) <= proposals.keys():
            raise Problem(422, "Invalid or duplicate original invoice position")
        for line in invoice.lines:
            if line.id in proposals and line.proposal_id != line.id:
                raise Problem(422, "Keep the original proposal reference when correcting a row")
            if line.id in all_ids or (line.proposal_id and line.id != line.proposal_id):
                raise Problem(422, "Invoice position IDs must be unique and stable")
            all_ids.add(line.id)
            if line.page not in {p.number for p in document.pages}:
                raise Problem(404, "Invoice source page not found")
            if not line.description.strip():
                raise Problem(422, "Describe the invoice position")
            for amount in (line.amount, line.unit_price):
                if amount is not None:
                    try:
                        if cents(amount) < 0:
                            raise ValueError(
                                "Use positive amounts; the position kind sets direction"
                            )
                    except ValueError as error:
                        raise Problem(422, str(error)) from error
            if line.quantity is not None:
                try:
                    quantity = Decimal(line.quantity)
                    if not quantity.is_finite() or quantity <= 0 or quantity > 1000000:
                        raise InvalidOperation
                except InvalidOperation as error:
                    raise Problem(422, "Use a positive finite quantity from the source") from error
            if line.kind == "condition" and line.amount is not None:
                raise Problem(422, "A condition is text, not an invoice charge")
            if line.cash_record_id:
                cash = choices.get(line.cash_record_id)
                if line.kind not in ("credit", "reflected_payment") or cash is None:
                    raise Problem(
                        422, "Only a credit/reflected payment can cite an existing payment"
                    )
                if cash.kind != "payment" or cash.recipient != "contractor":
                    raise Problem(422, "The linked record must be a payment to this contractor")
    # Persisted old links cannot be silently rewritten or removed by another review.
    previous = project.review.command.request_versions if project.review else []
    links = {(v.old_request_id, v.new_request_id) for v in command.request_versions}
    if not {(v.old_request_id, v.new_request_id) for v in previous} <= links:
        raise Problem(409, "Preserve the recorded request-version history")
    if len(links) != len(command.request_versions):
        raise Problem(422, "Duplicate request-version relationship")
    next_ids: dict[str, str] = {}
    prev_ids: dict[str, str] = {}
    for old, new in sorted(links):
        if old == new or old not in choices or new not in choices:
            raise Problem(422, "Request versions must reference different existing requests")
        if files[old] == files[new] or any(
            choices[rid].kind != "payment_request"
            or choices[rid].recipient != "contractor"
            or choices[rid].answer != "accept"
            for rid in (old, new)
        ):
            raise Problem(422, "Confirm two invoice documents for the same contractor")
        if old in next_ids or new in prev_ids:
            raise Problem(422, "Conflicting request replacements")
        next_ids[old], prev_ids[new] = new, old
    for start in next_ids:
        visited: set[str] = set()
        current = start
        while current in next_ids:
            if current in visited:
                raise Problem(422, "Request replacement cycle")
            visited.add(current)
            current = next_ids[current]
    if command.request_id in next_ids:
        raise Problem(422, "Select the active request, not a confirmed replaced version")


def compose(project: Project, invoice: InvoiceReview) -> Composition:
    assert project.review is not None
    document = next(d for d in project.documents if d.id == invoice.file_id)
    choice = next(r for r in project.review.command.records if r.id == invoice.request_id)
    requested = (
        cents(choice.amount) if choice.amount is not None and choice.answer == "accept" else None
    )
    proposals = {p.id: p for p in document.invoice_proposals}
    rows: list[CheckedLine] = []
    total = 0
    issues = []
    for line in invoice.lines:
        original = proposals.get(line.proposal_id or "")
        amount = cents(line.amount) if line.amount is not None else None
        sign = -1 if line.kind in ("discount", "credit", "reflected_payment") else 1
        signed = (
            amount * sign
            if amount is not None and line.kind not in ("condition", "unknown")
            else None
        )
        if line.review == "checked" and signed is not None:
            total += signed
        if line.review == "unknown" or (
            line.review == "checked" and line.kind != "condition" and signed is None
        ):
            issues.append(
                f"Position {line.id} is not fully checked or has an unknown amount/meaning."
            )
        if (
            line.kind == "reflected_payment"
            and line.review == "checked"
            and not line.cash_record_id
        ):
            issues.append(
                "Link the reflected payment to its existing cash evidence; "
                "an invoice mention is not a transfer."
            )
        if line.quantity is not None and line.unit_price is not None and amount is not None:
            if Decimal(line.quantity) * cents(line.unit_price) != amount:
                issues.append(f"Position {line.id}: quantity × unit price differs from its amount.")
        rows.append(
            CheckedLine(
                value=line,
                amount_cents=amount,
                signed_cents=signed,
                source_ref=f"page:{document.id}:{line.page}",
                review_source_ref=f"review:{project.review.id}",
                origin="manual_entry"
                if original is None
                else "manual_correction"
                if any(
                    getattr(line, key) != getattr(original, key)
                    for key in ("kind", "description", "amount", "quantity", "unit_price", "page")
                )
                else "checked_extraction",
                original_text=original.original_text if original else None,
            )
        )
    if not invoice.complete or not invoice.lines:
        issues.append("The owner has not confirmed the complete invoice composition.")
    if set(proposals) - {r.proposal_id for r in invoice.lines}:
        issues.append("Some extracted positions have not been reviewed.")
    if any(p.warning for p in document.pages) or document.status != "ready":
        issues.append("Source extraction is incomplete; inspect the original.")
    total = bounded(total)
    difference = bounded(requested - total) if requested is not None else None
    if difference != 0:
        issues.append("The checked composition does not reconcile with the requested total.")
    return Composition(
        file_id=document.id,
        request_id=invoice.request_id,
        requested_cents=requested,
        accounted_cents=total,
        unexplained_cents=difference,
        complete=not issues,
        lines=rows,
        issues=issues,
    )
