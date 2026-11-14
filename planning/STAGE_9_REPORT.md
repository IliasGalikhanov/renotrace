# Stage 9 - downloadable saved reconciliation PDFs

## Delivered scope

The guest can open a saved calculation or completed recheck, inspect its date/version and download a real standalone PDF. The report includes requested/C/P/R, documented conditions, source excerpts and original checksums, checked invoice rows and differences, original questions, historical or pinned owner-reported replies, separate evidence and owner decisions, and remaining uncertainty. A recheck includes both frozen financial bases and the already stored comparison. Export never calls the financial or comparison algorithms, and never blends later changes into older history.

Downloads use owner-authorized five-minute single-use tickets and go directly from FastAPI to the browser, bypassing Vercel binary-size limits. Generation is in memory; there are no saved export files in the backend and no retention extension. PDF metadata/filenames contain no credentials, and source text cannot execute markup or fetch resources. ReportLab and the licensed font are included in the locked production image. See [PDF export contract](PDF_EXPORT_CONTRACT.md) and [deployment/rollback](DEPLOYMENT.md).

The initial public runtime before this release is stage 8 SHA `3dba4d1b0d47ad3a315a02b96ca636fa1fb165b7`. No schema migration, new service, secret or paid resource is needed. PDF export from the separate synthetic demo, checkout, $99 pricing, registration, email and extended access are not implemented.

## Tests and visual checks

Local Python regression: **411 passed** (18.92 s), including 10 PDF unit tests. Ledger/normalization/demo coverage is **99.86%**; this coverage figure does not claim whole-application coverage. Full real PostgreSQL/private-object integration: **26 passed** (202.73 s), including three PDF access/immutability/revocation tests. After tightening UUID validation, the three export integration tests passed again (27.85 s), including malformed IDs and rejection of client-supplied totals. Production web build, mypy (38 source files), Ruff lint/format, frontend type/format checks and specification integrity passed. The production Docker image was checked without development dependencies: ReportLab and its bundled font are available.

Guest browser regression: **12 passed** (3.1 min), covering actual PDF downloads and content inspection at **360/768/1440 px**. At every width, the test downloads the initial saved report, recovers from a failed ticket request, downloads the completed comparison, then re-exports the original after later replies/files/calculation and verifies unchanged historical text. All three final browser screenshots were visually inspected: [360](screenshots/stage9/pdf-download-guest-360.png), [768](screenshots/stage9/pdf-download-guest-768.png), [1440](screenshots/stage9/pdf-download-guest-1440.png).

Existing demo regression: **34 passed, 2 intentionally skipped** (1.3 min); the real 55-second delayed-backend check runs once on desktop, while bounded retry behaviour is checked at every width. HTTP smoke passed against actual FastAPI and the built Next.js BFF, including FIN-16 $7,000 -> $5,000.

New checks use actual parsed synthetic documents and saved normalization/ledger output. They cover exact $6,200 -> $5,000 while P=$1,200/R=$5,000 stay unchanged; new work and a removed discount; Unknown and negative cents; partial replies with stop-unresolved; explicit historical/pinned reply versions; long text/filenames/tables; non-execution of markup; credential-like text omission; and resource bounds. Real PostgreSQL/HTTP tests check no data/expiry change, old PDFs after later replies/files, foreign/draft/deleted/expired denial, one-use/purpose-scoped tickets and revocation during rendering. Browser acceptance adds real downloads and PDF text inspection on 360/768/1440 px, including retry after an API failure and re-exporting the old result after new data.

Examples (all clearly fictional, not real financial records):

- [Initial saved calculation](../output/pdf/renotrace-fictional-snapshot.pdf).
- [Completed recheck](../output/pdf/renotrace-fictional-comparison.pdf).
- [Long-layout stress example](../output/pdf/renotrace-fictional-long.pdf): unverified added layout rows deliberately remain Unknown; this is pagination evidence, not an additional financial acceptance fixture.

All examples are generated with production `render_pdf`, rendered using Poppler and inspected as page images: initial report **3 pages**, comparison **7 pages**, long-layout stress **19 pages**. Long tables repeat headers, long replies continue across pages, and historical bases remain separate. Intermediate PNG/contact sheets live in ignored `tmp/pdfs`; selected final captures are in [stage 9 screenshots](screenshots/stage9/). During validation, a ReportLab exception-wrapping incompatibility in the page bound was corrected and covered by a regression test. Browser error assertions were narrowed to the relevant error region to avoid Next.js's separate route announcer.

## Manual scenario

1. Open `/review`, consent and upload `recheck-estimate.pdf`, `recheck-payment.pdf`, `recheck-original.pdf` from `fixtures/uploads` (each labelled FICTIONAL TEST DOCUMENT).
2. Check the candidates, contractor and complete invoice composition; select the $6,200 estimate/request and save. Open the saved calculation in **Saved calculations**. Confirm its revision and date, then **Download calculation PDF**. It shows requested $6,200, P=$1,200, R=$5,000, preliminary questions and source register.
3. Follow the [stage 8 recheck scenario](STAGE_8_REPORT.md#run-and-manually-verify): add an owner-reported reply, start from that saved result, upload/check the corrected invoice, explicitly confirm replacement, match rows and link the $1,200 reflected payment. Save the package, then separately run the recheck.
4. Open **View comparison**, inspect the selected date/algorithm/reference and **Download recheck PDF**. It shows requested $6,200 -> $5,000 while C=$6,200, P=$1,200 and R=$5,000 remain unchanged, with evidence status separate from owner decisions.
5. Edit a reply or add a document. Reopen the old calculation/comparison and download again: only the PDF-generation time changes, not the selected historical content. To include new evidence, save another review first. The downloaded copy remains on your device after guest access expires; originals are not bundled.
6. Delete the test review. Its old tickets/results no longer download. Previously downloaded local files remain with you.

## Reproduce checks

Use the existing [local full-stack setup](DEPLOYMENT.md#local-full-stack). Run integration and browser suites serially because integration deliberately restarts the local API.

```powershell
.\scripts\uv.ps1 sync --locked
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked ruff check services/backend tools tests/integration
npm run build
npm run typecheck
npm run format:check
$env:GUEST_API_URL='http://127.0.0.1:8106'
$env:GUEST_LOCAL_DB='1'
.\scripts\uv.ps1 run --locked pytest tests/integration -q
npm run test:guest
npm run test:e2e
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
.\scripts\uv.ps1 run --locked python tools/create_guest_pdf_examples.py
pdftoppm -r 100 -png output/pdf/renotrace-fictional-comparison.pdf tmp/pdfs/comparison
```

Public mode does not start local servers:

```powershell
$env:RENOTRACE_BASE_URL='https://renotrace.vercel.app'
npm run test:guest -- --grep 'recheck corrected' --timeout=600000
npm run test:remote
```

## Limits

This is an English USD saved-evidence report, not independent authentication or payment approval. Existing extraction/owner-review limitations remain. Sources are excerpted, not appended in full. Reply interpretation is not automated. Historical snapshots without invoice composition cannot gain reconstructed detail during export. Unicode outside the embedded font uses explicit code-point labels. External addresses and recognizable credentials are omitted from displayed text. PDF bounds are 300 pages/16 MiB and the existing case/ticket quotas; no partial report is returned on exceeding a bound. Free-backend startup and remote storage can make a full multi-upload journey slow. No server-side export archive or delivery email is created.

## Release gate

Implementation and local acceptance are complete. CI and public deployment remain pending; do not treat local PDFs as public-release evidence. The built-in browser controller was rechecked and returns `Trusted RPC service is not configured: browser`, so hosting buttons may require the owner's manual action after CI passes. The release record will include the exact checked SHA, hosting confirmation and independently downloaded public PDF. No database migration is needed for this release.
