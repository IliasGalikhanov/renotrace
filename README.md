# RenoTrace

**Understand your contractor's payment request.**

RenoTrace helps homeowners trace a renovation invoice back to the estimate, agreed changes, payments, and supporting records. It separates the requested amount, the remaining amount under recorded terms, payment conditions, and unresolved questions.

## Project status

Repository preparation only. The application, calculation engine, document processing, and deployment are not implemented yet. Fixtures are synthetic; no customer results or commercial claims are established.

The supplied specification uses the working name **RenoLedger**. **RenoTrace** is the proposed product/repository name: renovation + traceability. Original specification files and schema identifiers are preserved to avoid silently changing the baseline. Name/domain/trademark availability has not been assessed.

## Documentation

- [Specification index](SPECIFICATION.md)
- [Full original specification](RENOLEDGER_FULL_SPEC.md)
- [Implementation analysis and chat handoff](planning/IMPLEMENTATION.md)
- [Financial rules](docs/04_LEDGER_RULES.md)
- [Architecture](docs/05_ARCHITECTURE.md)
- [Delivery backlog](docs/09_DELIVERY.md)
- [API contract](contracts/openapi.json)
- [Extraction schema](contracts/extraction.schema.json)
- [16 synthetic financial reference cases](fixtures/ledger_cases.json)

## Planned structure

```text
apps/web/                    Next.js UI and thin BFF
services/backend/app/        FastAPI modules and worker; pure ledger package
services/backend/migrations/ PostgreSQL migrations
services/backend/tests/      Domain, API, database, and worker tests
infra/                       Local and deployment configuration
contracts/                   API and extraction contracts
fixtures/                    Synthetic reference inputs
docs/                        Supplied specification sections
planning/                    Implementation analysis and handoff
tools/                       Supplied specification utilities
```

Application directories currently contain placeholders only. Runtime versions, dependencies, lockfiles, and CI belong to DEV-01.

## Validate the specification

From this repository root:

```sh
python tools/validate_spec.py
```

This checks documentation links, contract structure, extraction examples, and reference arithmetic. It does not execute an implemented ledger or evaluate OCR/LLM accuracy. Optional `jsonschema` and `openapi-spec-validator` packages enable additional standards validation.

The original utilities `tools/build_contracts.py` and `tools/package_docs.py` regenerate the original contracts and design package. Review their diff before committing generated output; the package utility retains the RenoLedger baseline name.

## Development workflow

The planning chat defines tasks, scope, and acceptance criteria. The implementation chat works in this repository, checks the relevant behavior, and makes meaningful commits. Each implementation task should reference the supplied DEV/FR/FIN identifiers where applicable.

Money uses integer cents. Unknown values remain unknown. AI proposes candidates; deterministic application code calculates results. Real source documents and secrets must stay outside Git.

GitHub repository creation and the first push are pending. See the handoff for the prepared publication commands.
