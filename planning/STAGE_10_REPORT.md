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

Implementation SHA: `61275bb8dae6827f7ebd1c208abd42d79c6c9bbd` (`fix: distinguish saved question history and verify MVP showcase journeys`), pushed to main. [CI run 43658731825](https://github.com/IliasGalikhanov/renotrace/actions/runs/43658731825) passed on Linux and Windows. Linux logs confirm 414 Python tests, 99.86% domain/demo coverage, 34 demo browser tests, 26 real integration tests (148.14 s), 15 guest browser tests (3.2 min), production container build and health checks. Windows also passed 414 Python and 34 demo browser tests.

The owner confirmed Render Live for the checked implementation SHA on 2026-11-15. Independent HTTPS checks confirmed healthy `/healthz` and OpenAPI `0.10.0`. The actual public PDF integration journey passed: **1 passed, 2 local-only tests deselected, 332.35 s**. It checked initial and completed-recheck exports, pinned reply versions, old-report immutability after later evidence, one-use/purpose-isolated tickets, forbidden selections and denial after deletion. Its synthetic guest case was deleted. Local test containers were stopped; no volumes were removed. Expiry/revocation simulations remain local/CI evidence, not production database mutations.

The owner confirmed Vercel Ready for the same implementation SHA on 2026-11-15. Public browser acceptance passed without local servers: **3/3 complete recheck/PDF journeys on 360/768/1440 px, 15.6 min total** (5.5/5.2/4.9 min), **1/1 ordinary-invoice manual-entry journey, 3.3 min**, and **12/12 demo regression checks, 44.9 s**. The ordinary invoice ran in a separate guest context alongside the primary journey, with separate artifacts and data. These timings describe whole journeys, not just PDF generation. Checks include unchanged P=$1,200/R=$5,000 while the corrected request becomes $5,000, lost-response retry without duplicate comparison, comparison-load and export failures/retry, old-report immutability, page-linked manual positions and actual browser downloads. Synthetic projects were deleted. The demo still passes FIN-01/11/16, Unknown, Reset and independent browser contexts.

An additional clean 360 px browser entered through the anonymous homepage's **Review my invoice** link and verified the invoice-first instructions; its empty project was deleted. Anonymous requests without credentials/cookies returned HTTP 200 for `/review` and the GitHub repository, whose API reports `private=false`. Public UI captures at all three widths were visually inspected, including the historical-question labels and saved version/download panel.

## Final artifacts and visual inspection

These are actual browser downloads from the published application, not local replacements:

| Example | Pages | SHA-256 |
| --- | --- | --- |
| [Completed recheck](../output/pdf/renotrace-stage10-public-recheck.pdf) | 11 | `6ed6b08e30fcf398bfd3e6b9742d12748b5e8233765942ab0cf3a8be6a16a4b3` |
| [Ordinary invoice with manual positions](../output/pdf/renotrace-stage10-ordinary.pdf) | 4 | `93f645c4ab6a16f46d23923926cbe473a7642091819090b326eeb16ef8929ed2` |

Both were rendered again with Poppler and every page inspected, with full-page review of historical labels and manual composition. Text, amounts, table wrapping, pagination and sources remain readable. All four original-file hashes in the recheck and all three in the ordinary report match repository fixtures. No missing-source markers, attachments, annotations or OpenAction are present. The three originally confusing messages (processing, changed documents and ineligible request) remain in the final report, explicitly HISTORICAL; previous-conclusion reassessment is separate. The previous saved basis still shows its ACTIVE financial discrepancy. No financial question was automatically closed. The older PDF/1 example remains unchanged and is labelled historical in README.

[Stage 10 captures](screenshots/stage10/) provide the fallback: `pdf-download-guest-*` and `question-history-guest-*` are public captures at all three widths; `ordinary-guest-1440` is public, while ordinary 360/768 are local verification. `new-review-public-360` shows anonymous entry. `public-recheck-pdf-page-1`, `public-recheck-pdf-page-3` and `public-ordinary-pdf-page-2` are rendered pages of the final downloaded files. Intermediate complete page renders remain in ignored `tmp/pdfs/stage10`. All examples are fictional and prerecorded; test cases are no longer available on the server after deletion.

## Readiness decision

No blocking issue was found in the scoped acceptance. **Stage 10 is complete; the MVP is ready for demonstration and submission preparation**, with the limits above. Public site: https://renotrace.vercel.app/review . Backend: https://renotrace-api.onrender.com . Both run implementation SHA `61275bb8dae6827f7ebd1c208abd42d79c6c9bbd`; later report/artifact commits do not change runtime. The built-in browser controller still returns `Trusted RPC service is not configured: browser`, so platform status/SHA selection is owner-confirmed; actual public HTTPS behavior and downloads were independently tested. No migration, environment change or paid resource was added. A 24-hour production expiry and actual idle-sleep experiment were not repeated; local/CI expiry tests and the real delayed-start test are recorded above. Recognition is still restricted, financial evidence can remain preliminary, and the service is not payment authorization. No organiser application was sent. Stop feature development here; next work is presentation and submission.
