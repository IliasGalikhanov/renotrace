# Stage 8 — invoice rechecks with explained, saved changes

## Implemented scope

An explicit **Recheck with new information** workflow starts from a saved calculation. It persists the package (files, pinned reply versions, request relationship, row correspondences and question links), then runs the shared financial-save path and stores a new immutable snapshot and immutable comparison. Reload/restart retains drafts and completed history. An explanation can be rechecked without a corrected PDF. Text remains owner-reported and does not automatically change evidence assessments or money.

Invoice composition supports works/charges, discounts/credits, reflected payments, conditions, unknown meaning, source/page provenance, stable proposal IDs, manual corrections and missing-row entry. It reports an unexplained difference rather than inventing a balancing row. Explicit current-request lineage is separate from estimate supersession, with ownership, kind, contractor, conflict and cycle validation. Rows never create another cash event or contract adjustment.

Comparison shows added/removed/changed/unchanged and unmatched positions; changed descriptions, amounts, conditions and reflected payments; independent requested/C/P/R differences; original-question evidence and new questions. A linked checked invoice credit can cite a canonical payment already in the base ledger. Lower totals alone do not prove a missing payment was reflected, establish savings or close questions. Old snapshots and comparison algorithms are never rerun when reading history. Changed evidence marks current applicability **Needs recheck**, retaining historical output.

No accounts, additional paid resources, PDF export, outgoing email, checkout or longer retention. Existing 24-hour expiry, private originals and separate demo remain.

## Recognition and comparison limits

The parser proposes explicitly labelled English invoice rows such as `Work [surface]: Surface preparation | USD 6,200.00` and `Payment reflected [advance]: Earlier bank transfer | USD 1,200.00`. It uses existing PDF text extraction and Tesseract for scans/images. It is not a general invoice-table or reply-understanding model. Arbitrary unrecognized rows require manual entry linked to a real page. Currency/amount ambiguity, unchecked rows, missing historical composition and reconciliation gaps remain explicit. Human checking is not independent authentication.

Matching by description/kind is only a suggestion. Different-document mappings and added/removed classifications require explicit owner choices; equal amounts do not create correspondence. New/changed work is fully shown and requires separate contractual approval evidence. Existing ledger/normalization exclusively determine C/P/R; invoice comparison only subtracts their stored values and reconciles checked document rows in integer cents.

Financial edits are saved by **Save review and calculate** or **Run recheck**; unsubmitted form changes are not automatically persisted. Packages have their own explicit Save action. Existing limits protect free resources: 20 saved calculations and 20 packages, 100 positions per invoice, original source quotas. See [the full contract](RECHECK_CONTRACT.md).

## Checks and findings

- Python suite: **401 passed**, core ledger/normalization/demo coverage **99.86%**. New tests use actual PDF bytes, extraction, normalization and ledger; no precomputed financial fixtures substitute for this chain.
- Full local PostgreSQL/private-object/Tesseract/HTTP integration suite: **23 passed**. Includes original guest flows plus corrected $6,200 → $5,000 invoices, unchanged $1,200 cash and $5,000 remainder; new work with a removed discount; equal totals with changed composition; an explanation-only contradictory reply; unmatched/ambiguous/incomplete composition; pinned reply versions; concurrent retries; foreign objects; source changes; snapshots and comparison immutability; deletion/expiry and API restart.
- A concurrent integration test exposed mixed MVCC reads after waiting for a project row lock. Fixed by loading invoice side data after acquiring the project lock; identical concurrent retries then return consistent state and one result.
- Final production frontend build, strict mypy/TypeScript checks, Ruff, Prettier and specification integrity checks passed. HTTP smoke passed through the real BFF, normalization and ledger. Final targeted Python checks: **45 passed**; final stage 8 integration rerun: **6 passed**.
- Full guest browser suite: **12 passed** at 360/768/1440 px, including an intentionally lost successful response and retry. After final presentation/provenance changes, the three recheck journeys passed again. Existing demo browser suite: **34 passed, 2 intentionally skipped** (viewport-specific checks).
- Visually inspected the final comparison at all three widths: readable amounts, wrapping controls and no horizontal overflow. Public-release screenshots: [360 px](screenshots/stage8/comparison-guest-360.png), [768 px](screenshots/stage8/comparison-guest-768.png), [1440 px](screenshots/stage8/comparison-guest-1440.png). The committed images now come from the final public run described below; all three were visually inspected again.

## Run and manually verify

Use [local full-stack setup](DEPLOYMENT.md#local-full-stack). Apply the migration before using the new backend. Regenerate fictional documents with `python tools/create_guest_recheck_fixtures.py`; export implemented API with `python tools/export_guest_openapi.py` through the locked uv environment.

1. Open `/review`, consent and upload `recheck-estimate.pdf`, `recheck-payment.pdf`, `recheck-original.pdf` from `fixtures/uploads`.
2. Check all financial candidates, assign the contractor, select the $6,200 estimate and original request. Choose **Review invoice composition**, check the work row and complete-source checkbox, then save. Requested **$6,200**, paid **$1,200**, remaining **$5,000**; the difference produces a neutral clarification, not an assertion of a missing payment.
3. Add a contractor explanation to the question without a new attachment. Choose this saved calculation and **Recheck with new information**. Reload to inspect the saved draft.
4. Upload `recheck-corrected.pdf`. Recheck financial candidates and select its $5,000 request. Review both composition rows, link the $1,200 reflected payment to the existing receipt, check completeness.
5. In the package select the new invoice and confirm it replaces the original for the same contractor. Include the reply version, match the work rows, mark the payment-reflection row added, and link that row to the original question. Save the package. This alone does not create a completed comparison.
6. **Run recheck and save comparison**. Open the comparison: request **$6,200 → $5,000**, C **$6,200 → $6,200**, P **$1,200 → $1,200**, R **$5,000 → $5,000**. Inspect row sources and both stored financial bases. Unresolved evidence/owner decisions remain independent.
7. Reload; reopen the same result. Edit the reply or upload new evidence: the old text and result remain frozen while applicability becomes **Needs recheck**. Delete the synthetic case when finished.

Explanation-only variant: select the same request and its existing file, include a reply version, save/run with the same reviewed facts. No corrected PDF is required and money does not change. For missing historical composition, the result states that the old detail is unavailable rather than reconstructing it.

```powershell
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
```

Run integration and browser suites serially: integration intentionally restarts the shared API. Public mode starts no local servers:

```powershell
$env:RENOTRACE_BASE_URL='https://renotrace.vercel.app'
npm run test:guest -- --grep 'recheck corrected' --timeout=600000
npm run test:remote
```

## Release gate

Published application SHA: `3dba4d1b0d47ad3a315a02b96ca636fa1fb165b7`. Frontend: <https://renotrace.vercel.app/review>; backend: <https://renotrace-api.onrender.com>. [Release CI 43645110425](https://github.com/IliasGalikhanov/renotrace/actions/runs/43645110425) passed on Linux and Windows: 401 Python tests, 34 demo browser tests with 2 intentional skips, 23 real integration tests and 12 guest browser tests. Later report/screenshot commits do not change the deployed application.

The explicit additive production migration completed successfully on 2026-11-15 **before** deploying the backend. The previous backend remained healthy with OpenAPI `0.7.0` after migration. Render was then deployed and checked independently: `/healthz` returned `ok`, OpenAPI `0.8.0` exposed all four recheck/comparison routes. Only after the public backend test passed was Vercel switched to the same SHA. Existing Vercel Hobby, Render Free and Supabase Free resources were reused; no paid additions, new services or secrets were introduced.

The owner confirmed Render Live and Vercel Ready for the exact SHA supplied above. Dashboard status is user-confirmed: the built-in browser controller returned `Trusted RPC service is not configured: browser` and its advertised skill file was unavailable, so final deployment IDs could not be independently captured. Public HTTPS behavior was tested independently, without local servers. Local test containers were stopped, retaining their volumes.

Public backend acceptance: **1 passed, 5 deselected in 285.20 seconds**. Real uploaded synthetic PDFs exercise $6,200 -> $5,000, unchanged P/R, concurrent retries, pinned reply versions, immutable history, source-change invalidation, isolation and deletion. Direct database-trigger/table checks and restart/expiry simulation run only against disposable local/CI services; they were not performed on production.

Public browser acceptance: **3 passed in 12.6 minutes**, one complete journey at each of **360/768/1440 px** (4.3 / 4.2 / 4.0 minutes). The tests use real PDF uploads, reviewed financial facts and invoice composition, a saved reply, a persisted draft restored after reload, explicit invoice replacement and row matching, payment evidence links, a saved package, and a separately triggered recheck. A deliberately lost successful response is retried without producing a second comparison. Reloaded history shows requested **$6,200 -> $5,000**, C **$6,200 -> $6,200**, P **$1,200 -> $1,200**, R **$5,000 -> $5,000**, with unresolved evidence still marked preliminary. Every test deletes its own review.

After the new journey, the public demo regression passed: **12 tests in 41.9 seconds**, covering FIN-01/11/16, source disclosure, reset, separate visitors and all three widths. Final public comparison screenshots are linked above; visual inspection confirmed readable amounts and controls, visible uncertainty and no horizontal overflow. These timings establish functional acceptance, not a low-latency claim: several uploads and database saves take minutes on the existing free resources. The backend can sleep; existing startup waiting/retry behavior remains, without artificial keepalive.

To reproduce the direct HTTPS backend check (no production credentials or local database access):

```powershell
$env:GUEST_API_URL='https://renotrace-api.onrender.com'
Remove-Item Env:GUEST_LOCAL_DB -ErrorAction SilentlyContinue
.\scripts\uv.ps1 run --locked pytest tests/integration/test_guest_recheck.py -k real_recheck -q --tb=short
```

The public browser commands are listed above. Previous runtime SHA: `6cb667c5308a9cee98b722f7b3956dcd8ffd58dc`; stage 7 final documentation/CI SHA: `28227f80cd8cd523a23d17c8ad1a67597c16b57f`. Preserve additive tables and history on rollback; follow [DEPLOYMENT.md](DEPLOYMENT.md#stage-8-migration-and-release). Stage 8 is complete; downloadable reconciliation packages remain a separate stage.
