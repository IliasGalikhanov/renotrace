# Stage 6 — guest uploads and review

RenoTrace: `D:\Новая папка\3 курс\Business Cup\renotrace`.

## Implemented

Own-document review at `/review`, primary homepage action, private HttpOnly guest sessions, PostgreSQL state and durable leased jobs, immutable private originals, actual format/page/size validation, checksum deduplication, real PDF text/Tesseract OCR, conservative semantic candidates, separate review audit and actual normalization → ledger results with sources and preliminary metrics. The synthetic demo remains separate.

An English fictional estimate for $10,000 and completed payment for $3,000 produce $7,000 after explicit review. Changing the estimate document to $9,000 produces $6,000. Missing base/unreadable evidence remains unknown. Changed payment membership changes the result. Repeat upload/reprocessing does not mint another payment. Project IDs alone do not authorize access.

## Services / cost

- Existing Vercel `renotrace`, Hobby; existing Render `renotrace-api`, Free. No paid upgrade, disk or separate worker service. The worker runs in the backend; its queue and leases are persisted.
- Supabase organization **Lias**, project **renotrace** (`zbedmuneynqvhzilobsz`), Free, Singapore: 500 MB database / 1 GB private storage allowance. Data API disabled; private bucket `guest-originals`, exact 10 MiB limit, only PDF/PNG/JPEG, no public read policy.
- Tesseract **5.5.0** verified in Linux. No external LLM, paid OCR provider or usage-based AI charges.
- Hourly GitHub Actions maintenance removes expired data with a cleanup-only secret; it is not a keep-alive loop.

## Development verification

- **374 Python tests passed**: 347 previous + 27 extraction/review checks. Existing domain/demo coverage is **99.86%**; this is not guest-module coverage.
- **10 actual HTTP integration cases passed locally** with PostgreSQL, private SeaweedFS S3 and Tesseract: text PDF, scanned PDF, PNG/JPEG, changed contents, file dedup, ownership, deletion, malformed/encrypted/oversized inputs, the 50-page project quota, unknown base and an original exceeding 9 MiB with byte-identical download.
- **3 persistence/concurrency tests passed**: concurrent duplicate uploads, expiry and actual object removal, real API restart and abandoned-lease recovery, late upload cannot recreate a deleted project.
- **6 Playwright guest tests passed**, at 360/768/1440 px: upload → review → $7,000 → other recipient → $10,000 → contractor → $7,000; reload; HttpOnly cookie; independent visitor; original preview; deletion; prohibited BFF actions.
- Actual **Supabase** probe passed: schema, private upload/read, real text extraction, denied public read and source removal after deletion. Uploads disable caching and reads bypass intermediary caches.
- Final local checks: **374 Python tests**, **34 legacy Playwright tests** (two intentional duplicate cold-start skips), **6 guest Playwright tests**, production build, HTTP smoke, ruff, mypy, TypeScript, Prettier and specification integrity passed. The real 55-second cold-start test passed. Responsive captures at 360/768/1440 px were inspected.
- The staged changes were checked against all configured private credential values; none were present. Local secret files and private backups are excluded from Git and Docker.

## Run

```powershell
docker compose -f infra/guest.compose.yml up -d --build
.\scripts\uv.ps1 run --locked python tools/setup_guest_local.py
$env:GUEST_API_URL='http://127.0.0.1:8106'
$env:GUEST_LOCAL_DB='1'
.\scripts\uv.ps1 run --locked pytest tests/integration -q
npm run build
npm run test:guest
```

For public browser acceptance set `RENOTRACE_BASE_URL` to the public HTTPS origin before `npm run test:guest -- --timeout=600000`; this mode starts no local servers. The larger whole-journey budget allows concurrent processing on the free 0.1-CPU backend; individual assertions remain bounded. Only fictional test documents are used.

## Limits

Manual review is required. Semantic extraction supports labelled English USD records, not arbitrary layouts/languages or automatic document matching. Missing/ambiguous dates and currency remain unknown. Conditions use reviewed source text; work completion is not invented. Resource caps and exact API behavior are in the [guest contract](GUEST_REVIEW_CONTRACT.md).

The free backend can sleep, so jobs resume on wake; restart recovery can wait for a 120-second lease. Heavy/corrupt documents can fail bounded processing and remain preliminary. Access ends after 24 hours; physical purge occurs on active-worker/hourly maintenance runs and can be delayed by provider outages or GitHub scheduling. Already downloaded browser copies cannot be recalled. Losing the guest cookie loses continuation access.

The public transport closed a 10 MiB + 1 byte upload instead of returning the application's expected HTTP 413. The initial public suite reported **8 passes and this one transport failure**. This is recorded separately from the strict local HTTP 413 check. A dedicated opt-in probe (`GUEST_ALLOW_OVERSIZE_DISCONNECT=1`) allows only that oversized-request `ReadError`, then requires unchanged project state and successful subsequent valid uploads/calculation. All other transport failures still fail. Connection termination for oversized content is allowed by [RFC 9110 §15.5.14](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.14); this observation alone does not identify which public intermediary closed it. The UI checks file size before requesting a transfer.

## Public release gate

Stage 6 was manually released on 2026-11-15 (Asia/Qyzylorda) after both Linux and Windows CI passed. Public frontend: [renotrace.vercel.app/review](https://renotrace.vercel.app/review); backend: [renotrace-api.onrender.com](https://renotrace-api.onrender.com/healthz). Both deploy **`fa3f23a37399098de978b7de84e81d55a81238e9`**, containing implementation commit `7fcf6792082bc64349f896af2fcfc7f70fc0e6d1` and a tested CI storage-readiness fix. Auto-deploy remains off.

- [Release CI: Linux and Windows successful](https://github.com/IliasGalikhanov/renotrace/actions/runs/43630968655).
- Render deployment `dep-dbsb84rrjlhs73dncs8g`: Live, 54 seconds; OpenAPI version 0.6.0 and `/healthz` verified remotely.
- Vercel deployment `dpl_CVXsoVFPGaSYxQ9gvEExoFqSikfQ`: Ready, Production, 30 seconds. Public guest page opens without login.
- [Manual retention check successful](https://github.com/IliasGalikhanov/renotrace/actions/runs/43631729571), with the repository secret and live backend. Hourly schedule is configured.
- **12 public demo Playwright tests passed**, covering FIN-01, FIN-11, FIN-16 changes/reset, independent contexts and 360/768/1440 px.
- **6 public guest Playwright tests passed** in clean contexts at 360/768/1440 px (11.5 minutes total). Each full journey took 2.9–4.7 minutes with concurrent API/OCR checks on Free. The real result changed $7,000 → $10,000 → $7,000 as payment membership changed. Refresh, independent visitors, original preview, deletion, CSRF and forbidden routes passed. Public screenshots in `planning/screenshots/stage6` were inspected.
- Public API acceptance: eight cases passed in the initial suite (all five real extraction variants, ownership, deletion and page quota); the negative/unknown-base case then passed in the explicit oversized-disconnect diagnostic mode. A valid **9,438,803-byte PDF** passed real upload, byte-identical download and amount extraction after the test helper was aligned with the UI's `application/octet-stream` header. The full local/CI suite keeps strict HTTP 413 expectations; public 413 delivery remains unverified because that oversized request is closed in transit, including with the correct header. The exact intermediary responsible is not established.
- Local Compose services were stopped without deleting volumes; public checks continued against the hosted services.

Prior release for code rollback: `e76b358f9ef374a4f3f0f0ca0c81d147aabef06e`. Stage 5 had no persistent guest data. New guest data must retain its original expiry and deletion status during any rollback.

Before release, `tools/snapshot_stage5_release.py` verified that the new guest database and object outbox were empty and saved a private release/configuration manifest and initial schema under ignored `backups/stage6-before-release`. The prior deployment IDs are preserved there. No guest-content snapshot was needed for the stateless prior release. Code rollback must preserve deletion and expiry rules.
