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
- **9 actual HTTP integration tests passed** with PostgreSQL, private SeaweedFS S3 and Tesseract: text PDF, scanned PDF, PNG/JPEG, changed contents, file dedup, ownership, deletion, malformed/encrypted/oversized inputs, the 50-page project quota and unknown base.
- **3 persistence/concurrency tests passed**: concurrent duplicate uploads, expiry and actual object removal, real API restart and abandoned-lease recovery, late upload cannot recreate a deleted project.
- **6 Playwright guest tests passed**, at 360/768/1440 px: upload → review → $7,000 → other recipient → $10,000 → contractor → $7,000; reload; HttpOnly cookie; independent visitor; original preview; deletion; prohibited BFF actions.
- Actual **Supabase** probe passed: schema, private upload/read, real text extraction, denied public read and source removal after deletion. Uploads disable caching and reads bypass intermediary caches.
- Static checks and production build passed during development. Final release-gate results are recorded below after execution.

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

For public browser acceptance set `RENOTRACE_BASE_URL` to the public HTTPS origin before `npm run test:guest`; this mode starts no local servers. Only fictional test documents are used.

## Limits

Manual review is required. Semantic extraction supports labelled English USD records, not arbitrary layouts/languages or automatic document matching. Missing/ambiguous dates and currency remain unknown. Conditions use reviewed source text; work completion is not invented. Resource caps and exact API behavior are in the [guest contract](GUEST_REVIEW_CONTRACT.md).

The free backend can sleep, so jobs resume on wake; restart recovery can wait for a 120-second lease. Heavy/corrupt documents can fail bounded processing and remain preliminary. Access ends after 24 hours; physical purge occurs on active-worker/hourly maintenance runs and can be delayed by provider outages or GitHub scheduling. Already downloaded browser copies cannot be recalled. Losing the guest cookie loses continuation access.

## Public release gate

The public frontend/backend remain on stage 5 until the checked stage 6 SHA is manually deployed. Prior release: `e76b358f9ef374a4f3f0f0ca0c81d147aabef06e`. Stage 5 had no persistent guest data. Backup, final CI, deployed SHA and public acceptance evidence will be appended after execution.
