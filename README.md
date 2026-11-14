# RenoTrace

**Understand your contractor's payment request.**

RenoTrace traces a renovation invoice back to recorded terms, changes, and payments. The requested amount, calculated remainder, payment conditions, and unresolved questions are separate concepts.

## Current status: stage 2

Implemented: a runnable Next.js/TypeScript shell, a FastAPI health endpoint, a pure Python ledger, and a pure structured-history normalization module. Normalization selects confirmed estimate versions, removes included changes, filters payments/refunds, reconciles bank identities, applies explicit user decisions, and returns unresolved questions and provenance. Both domain modules run without a browser, AI, database, or network.

Not implemented: raw document extraction/OCR, inferred document matching, cumulative billing, invoice allocations, authentication, persistence, worker queue, reports, checkout, or deployment. Bank deduplication requires a stable operation ID and account context; matching amounts alone do not merge events. The web page is only a placeholder. The original specification uses **RenoLedger**; its source files and schema identifiers are preserved as the baseline for RenoTrace.

## Install on Windows

Prerequisites: Node **24.11.0** with npm **11.x**, and an existing Python with pip for bootstrapping. All commands below run from this repository root.

```powershell
Set-Location 'D:\Новая папка\3 курс\Business Cup\renotrace'
.\scripts\setup.ps1
```

The script installs uv **0.13.8** into `.tools`, CPython **3.13.18** into `.runtime`, Python dependencies into `.venv`, and Node packages into `node_modules`. It uses `uv.lock` and `package-lock.json`, leaves the system Python unchanged, and requires internet access on the first installation. `.env.example` contains no secrets; stage 1 does not require an `.env` file or external accounts.

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

Health: [localhost:8000/healthz](http://127.0.0.1:8000/healthz). Only `/healthz` and FastAPI's generated documentation are exposed; the private financial routes in the design contract are not implemented.

Web, in another terminal:

```powershell
npm run dev
```

Open [localhost:3000](http://127.0.0.1:3000). To run the production build:

```powershell
npm run build
npm start
```

## Run the checks

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov-report=term-missing
.\scripts\uv.ps1 run --locked ruff check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked python tools/validate_spec.py
npm run build
npm run typecheck
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
```

The smoke check starts actual FastAPI and built Next.js servers on temporary loopback ports, checks HTTP 200 and expected response content, then stops both. Tests require local loopback sockets; a network sandbox that blocks Python's local socket pair can stall ASGI startup. Run these checks in a normal terminal. Pytest creates `.pytest_tmp` directly under the repository root, so a fresh checkout needs no pre-existing cache directory.

The stage 1 FIN-01…FIN-16 tests exercise the calculator with supplied normalized records. Stage 2 adds 130 tests of structured inputs, version/link decisions, estimate replacement and included changes, cash identity conflicts, review/origin separation, cutoff dates, invalid references, cycles, stale/conflicting decisions, CLI behavior and order independence. Hypothesis permutes records, sources, links and decisions; repeated normalization does not create financial events. The combined suite has 221 tests. Domain coverage includes branches and a 95% minimum gate.

**Limits of these tests:** the old ledger fixtures still do not establish normalization. The new structured fixtures independently test the rules implemented in stage 2, using explicit source metadata, links and decisions. They do not establish OCR accuracy, automatic interpretation of invoices, fuzzy duplicate detection, or the truth of a user's assertion. Cumulative billing, allocations, payment conditions and the complete set of issues from the original design remain outside this stage. Synthetic source references identify registry entries, not real source files.

GitHub Actions runs installation, tests, lint/type checks, a production build, and HTTP smoke checks on Windows and Linux. See [the workflow](.github/workflows/checks.yml), [stage 2 report](planning/STAGE_2_REPORT.md), and the historical [stage 1 report](planning/STAGE_1_REPORT.md) for verification scope.

## Structure and documentation

```text
apps/web/                    Next.js App Router / TypeScript shell
services/backend/app/        FastAPI, CLI, reference adapter
services/backend/app/ledger/ Pure models and deterministic calculator
services/backend/app/normalization/ Structured history, decisions and provenance
services/backend/tests/      Ledger, property, API and CLI tests
services/backend/migrations/ Reserved for future migrations
infra/                       Reserved for future deployment configuration
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
