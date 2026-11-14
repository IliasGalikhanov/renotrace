# RenoTrace

**Understand your contractor's payment request.**

RenoTrace traces a renovation invoice back to recorded terms, changes, and payments. The requested amount, calculated remainder, payment conditions, and unresolved questions are separate concepts.

## Current status: stage 7

The primary path is **Review my invoice**: upload your own invoice, estimate and payment evidence without an account; check extracted candidates and relationships; calculate using the real Python normalization → ledger. A Secure HttpOnly guest cookie authorizes a private project for 24 hours. PostgreSQL persists review state, audit and durable jobs; original files live in private object storage. Text PDFs are parsed by page; scanned PDFs and PNG/JPEG use real local Tesseract OCR. English labelled USD documents require explicit user review.

**Try sample** remains the separate synthetic demo. See [guest setup and deployment](planning/DEPLOYMENT.md#stage-6-guest-reviews), [the guest contract](planning/GUEST_REVIEW_CONTRACT.md) and [stage 6 results and release status](planning/STAGE_6_REPORT.md).

Guest reviews now retain stable question cards, owner-reported contractor replies (including edit history), document attachments, separate evidence assessments and owner decisions, and immutable calculation snapshots. Replies and decisions do not change money or resolve uncertainty automatically. Changed financial evidence requires rechecking the conclusion. Saved calculations open read-only from stored results, never from a new calculation. All of this shares the existing project's original 24-hour lifetime. See [stage 7 contract](planning/CASEWORK_CONTRACT.md) and [stage 7 report](planning/STAGE_7_REPORT.md).

Implemented: an interactive English synthetic demo, a restricted public FastAPI demo API, a server-side Next.js BFF, a pure Python ledger, and a pure structured-history normalization module. Normalization selects confirmed estimate versions, removes included changes, filters payments/refunds, reconciles bank identities, applies explicit user decisions, and returns unresolved questions and provenance. Stage 3 adds typed billing, comparable cumulative valuations, targeted credit notes, explicit partial payment/refund allocations, invoice balances and unallocated cash. Both domain modules run without a browser, AI, database, or network. The demo calls them on the server for every recalculation; browser code only formats returned amounts.

Not implemented: account registration, general-purpose LLM document understanding, automatic inferred document matching, exports or checkout. Bank deduplication requires a stable operation ID and account context; matching amounts alone do not merge events. The synthetic demo never saves visitor decisions. The original specification uses **RenoLedger**; its source files and schema identifiers are preserved as the baseline for RenoTrace.

## Try the interactive demo

Public site: **[renotrace.vercel.app](https://renotrace.vercel.app)**. No account needed. Backend: [health endpoint](https://renotrace-api.onrender.com/healthz). The free backend sleeps when idle; the first calculation may take about a minute, with bounded retries for up to three minutes. This is a synthetic demo without saved decisions.

For local development, start the backend and frontend using the commands below, then open [localhost:3000](http://127.0.0.1:3000) and select **Try sample**. FIN-01 explains the $800 credit and $4,700 remainder. FIN-16 lets you assign the unknown $2,000 transfer: the remainder changes **$7,000 → $5,000 → $7,000**; “I don't know” restores the provisional state. FIN-11 traces the $8,500 cumulative increment and $10,500 open invoice balances.

Each amount can be opened to inspect participating records and inline synthetic source excerpts. Conditions without supplied evidence display **Unknown**. Reset/reload discards decisions; two visitors do not share state. Loading hides old figures, and errors have retry controls.

See the [actual demo API contract](planning/DEMO_API_CONTRACT.md), [exported implemented OpenAPI](contracts/demo.openapi.json), [deployment and rollback runbook](planning/DEPLOYMENT.md), [stage 5 deployment report](planning/STAGE_5_REPORT.md) and [stage 4 report with screenshots](planning/STAGE_4_REPORT.md). The original private OpenAPI remains a design document, not implemented routes.

## Install on Windows

Prerequisites: Node **24.11.0** with npm **11.x**, and an existing Python with pip for bootstrapping. All commands below run from this repository root.

```powershell
Set-Location 'D:\Новая папка\3 курс\Business Cup\renotrace'
.\scripts\setup.ps1
```

The script installs uv **0.13.8** into `.tools`, CPython **3.13.18** into `.runtime`, Python dependencies into `.venv`, and Node packages into `node_modules`. It uses `uv.lock` and `package-lock.json`, leaves the system Python unchanged, and requires internet access on the first installation. `.env.example` contains no secrets; the domain modules do not require an `.env` file or external accounts.

On macOS/Linux with Node 24.11.0 and uv 0.13.8 available:

```sh
uv sync --locked
npm ci
```

For the following commands on macOS/Linux, replace `.\scripts\uv.ps1` with `uv`.

## Normalize structured history, then calculate

```powershell
.\scripts\uv.ps1 run --locked renotrace-normalize --case FIN-01
.\scripts\uv.ps1 run --locked renotrace-normalize --case FIN-03
.\scripts\uv.ps1 run --locked renotrace-normalize --case NORM-VERSION-CONFLICT
```

These commands use [13 new structured scenarios](fixtures/normalization_cases.json), not the stage 1 normalized numeric arrays. Output contains `normalization` (LedgerInput, included/excluded records and reasons, questions, incomplete metrics, source registry, links and applied decisions) and `calculation` from the real ledger.

FIN-01 yields $12,700 in commitments, $8,000 paid, $4,700 remaining, and a separate $5,500 request. FIN-03 confirms the $13,500 replacement includes the $1,500 change, so commitments remain $13,500. An unconfirmed conflicting estimate leaves the baseline and remainder `null` and returns a question.

Stage 3 has [9 additional structured billing scenarios](fixtures/billing_cases.json):

```powershell
.\scripts\uv.ps1 run --locked renotrace-normalize --fixtures fixtures/billing_cases.json --case FIN-11
.\scripts\uv.ps1 run --locked renotrace-normalize --fixtures fixtures/billing_cases.json --case PARTIAL
.\scripts\uv.ps1 run --locked renotrace-normalize --fixtures fixtures/billing_cases.json --case FIN-13
.\scripts\uv.ps1 run --locked renotrace-normalize --fixtures fixtures/billing_cases.json --case REFUND
```

FIN-11 yields an $8,500 increment, $13,500 billed and $10,500 of positive invoice balances. PARTIAL leaves $500 unallocated. FIN-13 retains a $2,000 unallocated advance and an $8,000 contract remainder. REFUND reverses an explicit allocation and clears a $1,000 invoice credit. The ledger reports `billed_total_cents`, `charge_balances`, separate positive/credit totals, `net_allocations_cents`, `unallocated_cents` and per-event `cash_balances`. Changing allocations never changes C/P/R or the request.

For your own structured JSON using [HistoryInput](services/backend/app/normalization/models.py):

```powershell
.\scripts\uv.ps1 run --locked renotrace-normalize --input path/to/history.json
```

Read the [normalization contract](planning/NORMALIZATION_CONTRACT.md) for identifiers, audit fields, decision scopes, cutoff semantics and failure behavior. Dangling references, duplicate object IDs and replacement cycles fail before calculation with a stable error code. Ambiguous facts produce questions and a provisional result that omits the disputed contribution. Callers must retain the completeness flags when displaying financial totals.

## Run the ledger alone (stage 1 reference adapter)

```powershell
.\scripts\uv.ps1 run --locked renotrace-ledger --case FIN-01
```

The actual ledger returns integer cents:

```json
{
  "commitment_total_cents": 1270000,
  "net_paid_cents": 800000,
  "remaining_commitment_cents": 470000,
  "requested_now_cents": 550000
}
```

That is **$12,700** in recorded commitments, **$8,000** in net completed payments, **$4,700** remaining, and a separate **$5,500** request. CLI output also includes gross payments/refunds, record IDs, revision, rule version, and an order-independent input fingerprint.

For an explicit normalized input conforming to [LedgerInput](services/backend/app/ledger/models.py):

```powershell
.\scripts\uv.ps1 run --locked renotrace-ledger --input path/to/input.json
```

This is an internal domain input format, not an implementation of the future case API. Invalid input exits with code 2 and does not emit a financial result.

## Run the applications

API, in one terminal:

```powershell
.\scripts\uv.ps1 run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health: [localhost:8000/healthz](http://127.0.0.1:8000/healthz). Also available: `/api/demo/scenarios`, `/api/demo/scenarios/{id}`, and POST `/api/demo/scenarios/{id}/calculate`. The actual schema is `/openapi.json`; private financial routes remain unimplemented.

Web, in another terminal (copy the example once, or set BACKEND_URL in the process environment):

```powershell
Copy-Item .env.example apps/web/.env.local
npm run dev
```

Open [localhost:3000](http://127.0.0.1:3000). To run the production build:

```powershell
npm run build
npm start
```

## Run the checks

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo --cov-report=term-missing
.\scripts\uv.ps1 run --locked ruff check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked python tools/validate_spec.py
npm run build
npm run typecheck
npm run format:check
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
npx playwright install chromium
npm run test:e2e
```

The smoke check starts actual FastAPI and built Next.js servers on temporary loopback ports, checks HTTP 200 and expected response content, verifies a real BFF recipient recalculation ($7,000 → $5,000), then stops both. Tests require local loopback sockets; a network sandbox that blocks Python's local socket pair can stall ASGI startup. Run these checks in a normal terminal. Pytest creates `.pytest_tmp` directly under the repository root, so a fresh checkout needs no pre-existing cache directory.

The stage 1 FIN-01…FIN-16 tests exercise the calculator with supplied normalized records. Stage 2 adds 130 tests of structured inputs, version/link decisions, estimate replacement and included changes, cash identity conflicts, review/origin separation, cutoff dates, invalid references, cycles, stale/conflicting decisions, CLI behavior and order independence. Hypothesis permutes records, sources, links and decisions; repeated normalization does not create financial events. Stage 2.1 adds 8 regression/property tests and enforces that every UNRESOLVED_TRANSACTION exclusion has a paid/remainder question and provisional flags. Stage 3 adds 93 tests covering billing coverage, cumulative predecessors, credit notes, partial allocations, canonical cash capacity, refund limits, versions, dates, evidence, CLI, order/repeat invariance and per-payment conservation. Stage 4 adds 25 API tests, bringing the Python suite to 347 tests, plus 30 Playwright checks across three viewport sizes. Browser tests exercise the real API/BFF, isolation, reset, errors, forbidden actions, late replies, keyboard controls and source disclosures. Domain coverage includes branches and a 95% minimum gate.

**Limits of these tests:** the old ledger fixtures still do not establish normalization. The new structured fixtures independently test the rules implemented in stages 2 and 3, using explicit source metadata, links and decisions. They do not establish OCR accuracy, automatic interpretation of invoices, fuzzy duplicate detection, or the truth of a user's assertion. Coverage is explicitly supplied as confirmed atomic work/period IDs; automatic overlap recognition and payment conditions remain outside this stage. Cumulative valuations are gross of separately recorded credit notes; documents with credits already embedded must be resolved before creating this input. Synthetic source references identify registry entries, not real source files.

GitHub Actions runs installation, tests, lint/type checks, a production build, HTTP smoke and Playwright checks on Windows and Linux, plus a container build/runtime check on Linux. See [the workflow](.github/workflows/checks.yml), [stage 4 report](planning/STAGE_4_REPORT.md), [stage 3 report](planning/STAGE_3_REPORT.md), [stage 2.1 correction report](planning/STAGE_2_1_REPORT.md), [stage 2 report](planning/STAGE_2_REPORT.md), and the historical [stage 1 report](planning/STAGE_1_REPORT.md) for verification scope.

## Structure and documentation

```text
apps/web/                    Next.js demo UI and server-side BFF
services/backend/app/        FastAPI, CLI, reference adapter
services/backend/app/ledger/ Pure models and deterministic calculator
services/backend/app/normalization/ Structured history, decisions and provenance
services/backend/app/demo/   Stateless sample API and inline synthetic sources
services/backend/tests/      Ledger, property, API and CLI tests
tests/e2e/                   Playwright journeys and responsive captures
services/backend/migrations/ Reserved for future migrations
infra/backend.Dockerfile     Container backend configuration
contracts/ fixtures/ docs/  Supplied design baseline
planning/                    Implementation handoff and verification report
scripts/                     Windows local tooling wrappers
tools/                       Specification validation and HTTP smoke check
```

- [Specification index](SPECIFICATION.md) and [full original specification](RENOLEDGER_FULL_SPEC.md)
- [Financial rules](docs/04_LEDGER_RULES.md), [architecture](docs/05_ARCHITECTURE.md), [delivery backlog](docs/09_DELIVERY.md)
- [API design](contracts/openapi.json), [extraction schema](contracts/extraction.schema.json), [financial fixtures](fixtures/ledger_cases.json)
- [Planning handoff](planning/IMPLEMENTATION.md), [normalization contract](planning/NORMALIZATION_CONTRACT.md), and [development/testing agreement](CONTRIBUTING.md)

The original `tools/build_contracts.py` and `tools/package_docs.py` regenerate design artifacts, not running application contracts. Review their output before committing. Real source documents, secrets, environments and build output stay outside Git.
