# Stage 10 — final MVP readiness verification

## Corrections

The historical-message issue was in presentation, not the stored reconciliation: cards already retained `observation.active=false`, but the PDF omitted that flag and called all cards added since the prior snapshot “New question”. UI and PDF now distinguish active questions, historical absence and the independent requirement to reassess previous conclusions. Missing legacy flags are explicitly unrecorded. No historical data is deleted, no financial question is automatically closed, and old calculations are never rerun. Comparison UI loads the selected immutable snapshot for original-question presence; export uses that same saved basis. PDF presentation is `reconciliation-pdf/2`; financial/comparison algorithms and database schema are unchanged.

Small usability changes explain invoice-first upload, fact/position checks, the boundary of recognition, slow processing, draft package saving versus running a recheck, and selected saved versions. Failed comparison loading can retry the intended selection. The new ordinary English fictional invoice has Wall painting, Floor protection and Skirting board installation. The existing parser finds monetary candidates but no invoice-position proposals; tests explicitly correct their meanings and add three page-linked manual positions. No demo values or new recognition engine are substituted.

## Evidence and reproduction

The deterministic regression drives real extraction, a temporary processing state, completion, checked saving, reconciliation and production PDF rendering. It preserves the inactive processing observation and owner decision, retains the active financial discrepancy and forbids calculation/reconciliation calls during export. Further tests cover legacy comparison labels, unknown presence and manual source-linked invoice composition.

Local verification: **414 Python tests passed**, domain/demo coverage **99.86%**; mypy, Ruff lint/format, TypeScript, frontend formatting and production build passed. **26 integration tests passed in 209.89 s**, with real PostgreSQL, private objects, OCR, restart and export checks. **15 guest browser journeys passed in 3.9 min** on 360/768/1440 px, including the new ordinary invoice, complete recheck/PDF route, comparison-load retry and export retry. **34 demo browser tests passed in 1.3 min**; two duplicate real-startup runs are intentionally skipped on smaller widths. The actual 55-second delayed-backend test passed. HTTP startup/BFF smoke and specification integrity passed; optional full JSON Schema/OpenAPI validators are not installed, so the latter remains its documented portable subset check.

Local downloaded PDFs were rendered with Poppler and all pages inspected: comparison **11 pages**, ordinary invoice **4 pages**. Active versus historical labels, independent reassessment, amounts, page citations and source register remain readable. All three viewport captures were visually inspected, including the historical-question panel. These are local checks, not public-release evidence. On 2026-11-15, anonymous requests without credentials/cookies returned HTTP 200 for the public site and repository; GitHub's anonymous API confirmed `private=false`.

Run the existing [local full-stack setup](DEPLOYMENT.md#local-full-stack), then:

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked ruff check services/backend tools tests/integration
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools tests/integration
npm run build
npm run typecheck
npm run format:check
$env:GUEST_API_URL='http://127.0.0.1:8106'
$env:GUEST_LOCAL_DB='1'
.\scripts\uv.ps1 run --locked pytest tests/integration -q
npm run test:guest
npm run test:e2e
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
```

Run integration and browsers serially: integration deliberately restarts the local API. The public mode starts no local servers:

```powershell
Remove-Item Env:GUEST_LOCAL_DB -ErrorAction SilentlyContinue
$env:GUEST_API_URL='https://renotrace-api.onrender.com'
.\scripts\uv.ps1 run --locked pytest tests/integration/test_guest_pdf_exports.py -k original_and_pinned -q
$env:RENOTRACE_BASE_URL='https://renotrace.vercel.app'
npm run test:guest -- --grep 'recheck corrected' --timeout=600000
npm run test:guest -- --grep 'ordinary invoice' --project guest-1440 --timeout=600000
npm run test:remote
```

## Presenter materials and limits

Follow the [short showcase guide](SHOWCASE_GUIDE.md). All documents are fictional. Main journey: initial request $6,200, recorded payment $1,200 and remainder $5,000; owner-entered reply; corrected invoice $5,000; explicit link to the existing payment; frozen comparison and PDF. This is a reflected prior payment, not new cash or proven savings. Reserve captures belong in `screenshots/stage10`; the final downloaded examples are listed with release evidence below. Announce prerecorded results as prerecorded. The original guest expiry is 24 hours; local PDFs remain after expiry/deletion.

English/USD recognition is restricted and needs owner review. Missing positions can be added with page citations only after a request candidate exists; the MVP cannot manually create a wholly unrecognised contract/request candidate. Free backend startup and multi-upload processing can take minutes. Sources are excerpts, not attached originals. Unresolved evidence stays preliminary. No registration, new services, pricing/checkout, extended access or universal parser were added. $99 and 60 days are future hypotheses, not an available offer. No application is sent to organisers.

## Release gate

Local checks are complete. Pending exact-SHA CI, deployment, public journeys and final public PDF visual inspection. Stage 10 is not yet declared complete. The built-in browser controller was rechecked and returns `Trusted RPC service is not configured: browser`; owner-operated Render/Vercel publication is required after successful CI. HTTP and browser behavior will be tested independently.
