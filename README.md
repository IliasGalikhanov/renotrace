# RenoTrace

**Understand your contractor's payment request.**

RenoTrace traces a renovation invoice back to recorded terms, changes, and payments. The requested amount, calculated remainder, payment conditions, and unresolved questions are separate concepts.

## Stage 1

Implemented: a runnable Next.js/TypeScript shell, a FastAPI health endpoint, a pure Python ledger, a JSON command-line calculator, locked dependencies, and automated tests. The financial module runs without a browser, AI, database, or network.

Not implemented: document normalization, OCR, duplicate detection, version selection, allocations, issue generation, authentication, persistence, worker queue, reports, checkout, or deployment. The web page is only a placeholder. The original specification uses **RenoLedger**; its source files and schema identifiers are preserved as the baseline for RenoTrace.

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

## Calculate a synthetic example

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
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov-report=term-missing
.\scripts\uv.ps1 run --locked ruff check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked ruff format --check services/backend tools/smoke_test.py
.\scripts\uv.ps1 run --locked mypy
.\scripts\uv.ps1 run --locked python tools/validate_spec.py
npm run build
npm run typecheck
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
```

The smoke check starts actual FastAPI and built Next.js servers on temporary loopback ports, checks HTTP 200 and expected response content, then stops both. Tests require local loopback sockets; a network sandbox that blocks Python's local socket pair can stall ASGI startup. Run these checks in a normal terminal. Pytest temporary files stay under `.cache/pytest`.

FIN-01…FIN-16 exercise the actual calculator with the supplied normalized records. Additional tests cover pending/failed/reversed payments and refunds, unknown/zero bases, negative remainders, strict integers, range/aggregate overflow, unique record IDs, source references, CLI errors, arbitrary record order, and request independence. Hypothesis generates multiple inputs for the invariants. Ledger coverage is measured with branches and a 95% minimum gate.

**Limits of these tests:** fixture normalization is supplied, not discovered by the application. Passing FIN-03/07/08/11/15/16 does not prove version selection, duplicate detection, cumulative invoice interpretation, recipient matching, or OCR. `expected_issue_codes`, billing entries and stage conditions are not implemented or asserted in stage 1. Synthetic evidence references are identifiers, not real source documents.

GitHub Actions runs installation, tests, lint/type checks, a production build, and HTTP smoke checks on Windows and Linux. See [the workflow](.github/workflows/checks.yml) and [stage 1 report](planning/STAGE_1_REPORT.md) for verification scope.

## Structure and documentation

```text
apps/web/                    Next.js App Router / TypeScript shell
services/backend/app/        FastAPI, CLI, reference adapter
services/backend/app/ledger/ Pure models and deterministic calculator
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
- [Planning handoff](planning/IMPLEMENTATION.md) and [development/testing agreement](CONTRIBUTING.md)

The original `tools/build_contracts.py` and `tools/package_docs.py` regenerate design artifacts, not running application contracts. Review their output before committing. Real source documents, secrets, environments and build output stay outside Git.
