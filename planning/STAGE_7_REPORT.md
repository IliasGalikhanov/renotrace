# Stage 7 — persistent question cards, replies and calculation snapshots

## Scope

Implemented within the existing RenoTrace guest flow: PostgreSQL question cards with stable entity identity and financial-basis fingerprints; separate evidence and owner-decision states; owner-reported contractor text replies with immutable edit versions; same-project document links; idempotent mutation retries; immutable successful calculation snapshots with source composition, inputs, decisions, normalization, ledger, conditions and discussion at save time. Historical calculations are served from frozen JSON and displayed read-only.

The English interface keeps the four financial blocks, adds prepared questions/copy, reply and attachment controls, assessment reasons and history, and a saved-calculation list. Missing evidence and historical unresolved issues remain visible. A new document still invalidates the financial review; discussion text and owner choices do not change money or extend access.

No new hosting service, paid resource, account system, outgoing message, financial agreement action, corrected-invoice comparison or PDF export. Existing synthetic demos remain separate.

## Validation

Local development checks:

- Python domain/API/CLI suite: **381 passed**, ledger/normalization/demo coverage **99.86%**. Windows TestClient requires the normal unrestricted local process environment; a sandboxed attempt stalled and was stopped, then the full suite passed. Final review added a regression for a negative USD 3,000.45 refund: prepared clarification text preserves exact signed cents and uses a neutral counterparty question.
- Real local PostgreSQL/private S3/Tesseract integration: **17 passed**, including financial independence of replies/decisions, same-key retries, frozen result reads, ownership isolation, additive migration, API restart recovery and deletion/expiry cascades.
- Guest browser suite: **9 passed** at 360/768/1440 px, including the new history path and all existing guest journeys. A lost reply response after server commit is retried without duplication. The first test iteration exposed an overly strict label locator; selecting the named accessible combobox fixed the test.
- Existing demo browser suite: **34 passed, 2 intentionally skipped** duplicate viewport cold-start runs. The real 55-second backend-start test passed. Run browser suites serially because they share the Playwright output directory.
- Production Next.js build, Python strict types/lint/format, frontend format/types, specification integrity and HTTP smoke passed.
- Visual inspection: question cards and read-only history are readable at all three widths without horizontal overflow. [Mobile card](screenshots/stage7/history-guest-360.png), [tablet snapshot](screenshots/stage7/snapshot-guest-768.png), [desktop card](screenshots/stage7/history-guest-1440.png).
- Production pre-migration inspection returned zero projects, objects, jobs and audits. Populated-project preservation is separately exercised in PostgreSQL integration tests; no existing production data is rewritten or deleted by the migration.

## Run and manually verify

Use the existing [local setup](DEPLOYMENT.md#local-full-stack): locked dependencies, Docker Compose, `tools/setup_guest_local.py`, `npm run build`, frontend with `BACKEND_URL=http://127.0.0.1:8106`.

1. Open `/review`; accept processing and upload synthetic `fixtures/uploads/estimate.pdf`, `payment.pdf`, `invoice.pdf`.
2. Include all four extracted facts. Select the estimate and invoice. Leave the payment recipient Unknown; other facts belong to the contractor. Save: remaining **$10,000**, requested **$7,000**, explicit unknown-recipient question.
3. Open that card. Copy its $3,000 transfer question. Select the card, paste a partial explanation, save without an attachment. Reload: reply and history remain; remaining stays **$10,000**.
4. Mark evidence insufficient and independently accept the explanation or stop clarifying. The card remains unresolved and the amount stays unchanged. Edit the reply: the previous version remains visible.
5. Review the payment recipient as contractor and save the financial review: remaining becomes **$7,000**. The same card/replies remain, with **Needs recheck** and the previous owner decision.
6. Open the first saved calculation: its frozen remaining stays **$10,000**, with the original questions and sources. Close it to return to the current $7,000 result.
7. Link existing checked documents to selected cards, or upload a new document through the existing controls and recheck facts before calculating. Delete the test review at the end.

Commands from the repository root (Windows; replace the uv wrapper with `uv` on Linux):

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo
.\scripts\uv.ps1 run --locked ruff check services/backend tools tests/integration
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools tests/integration
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked python tools/validate_spec.py
npm run build
npm run typecheck
npm run format:check
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
npm run test:e2e
$env:GUEST_API_URL='http://127.0.0.1:8106'
$env:GUEST_LOCAL_DB='1'
.\scripts\uv.ps1 run --locked pytest tests/integration -q
npm run test:guest
```

Run integration and guest browser suites serially: integration deliberately restarts the shared local API. Public browser mode uses `RENOTRACE_BASE_URL` and no local server; do not set `GUEST_LOCAL_DB` for public checks.

## Limits

Original 24-hour expiry and existing upload/OCR restrictions remain. Maximum 20 saved calculations, 300 cards, 200 idempotent mutations and 20 versions per reply protect the free database. Sources are checked by the guest, not independently authenticated. Reply text is not semantically interpreted. Positive evidence status requires explicit page citations and a current saved calculation without the affected uncertainty. Historical unresolved discussion does not invent a new ledger event. Old audit commands have no reconstructed snapshots.

Render Free can sleep and OCR can be slow. No keepalive or paid resources are introduced. Existing free-tier limits and the known public oversized-upload transport limitation from stage 6 remain applicable.

## Release gate

Pending final browser checks, exact-SHA CI and manual release. Before this release, both public services run `fa3f23a37399098de978b7de84e81d55a81238e9`; backend deployment `dep-dbsb84rrjlhs73dncs8g`, frontend deployment `dpl_CVXsoVFPGaSYxQ9gvEExoFqSikfQ`. The additive rollback procedure is in [DEPLOYMENT.md](DEPLOYMENT.md#stage-7-migration-and-release).
