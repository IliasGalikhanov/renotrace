# Private guest document review

Stage 7 extends this foundation with [persistent questions, replies and immutable calculation snapshots](CASEWORK_CONTRACT.md). The separate contract documents the new routes, two state axes, idempotency and additive migration. The original 24-hour lifetime and financial freshness checks are unchanged.

The main flow is **Review my invoice** → upload current invoice and supporting documents → check candidates and links → calculate. No account, email, password form or Supabase Auth. **Try sample** remains a separate, stateless synthetic demo. Guest calculations never load demo fixtures.

## Actual HTTP contract

FastAPI `/openapi.json` is authoritative; `contracts/demo.openapi.json` now exports both implemented demo and guest routes (the filename is historical). `contracts/openapi.json` remains an unimplemented account/case design.

| Method / backend route | Input and behavior |
| --- | --- |
| POST `/api/guest/session` | Returns a random session secret and project ID; existing valid secret resumes its project. The Next.js BFF removes the secret from the JSON and stores it in `__Host-renotrace`, Secure, HttpOnly, SameSite=Strict, Path=/, 24 hours. |
| GET `/api/guest/projects/{id}` | Owner bearer secret required. Returns immutable file metadata, extraction pages/candidates, latest review, actual domain history, normalization, ledger result, questions, affected metrics and source content. |
| POST `/api/guest/projects/{id}/tickets` | Owner only; typed upload or file-scoped download request; 256-bit, single-use ticket, 5-minute lifetime. |
| PUT `/api/guest/transfer` | Raw file bytes; upload ticket in Authorization. Checks actual content and quotas. Returns existing document on SHA-256 duplicate. |
| GET `/api/guest/transfer` | File-scoped ticket in Authorization. Rechecks project existence/expiry; returns original bytes with no-store and attachment headers. No signed object-store URLs are exposed. |
| POST `/api/guest/projects/{id}/review` | Revision, exactly one choice for each candidate, active estimate, current request, cutoff and explicit estimate relationships. Rejects unknown IDs, invalid amounts, wrong kinds, cycles and stale revision. Saves separate audit evidence and runs the real normalization → ledger. |
| DELETE `/api/guest/projects/{id}` | Owner only. Atomically revokes access and deletes project data, jobs, tickets and audit entries; removes originals through a durable deletion outbox. |
| POST `/api/guest/maintenance/cleanup` | Backend-only cleanup credential. Expires reviews and retries object removal. Not forwarded by the frontend BFF. |
| GET `/healthz` | Existing availability check; does not claim PostgreSQL/OCR readiness. |

Project IDs are not credentials. Missing/wrong owners receive the same 404 as absent/expired projects. Jobs are exposed only inside their authorized project. JSON mutations through the BFF require a same-origin request. All browser JSON responses are no-store. Successful backend transfer responses are no-store; Supabase uploads also disable caching, and authenticated source reads use a fresh cache nonce.

Vercel Functions have a 4.5 MB payload limit. Therefore large originals go directly between the browser and FastAPI using short-lived, narrowly scoped tickets; the permanent guest secret remains HttpOnly in Next.js. CORS permits only the configured frontend origin, no credentialed wildcard. Ticket secrets never appear in URLs. React previews use browser-local blob URLs and revoke them on close/delete.

## Persistence and concurrency

PostgreSQL `guest_review` is a backend-only schema, separate from Supabase's public/Data API schemas. Tables: sessions (SHA-256 of random secrets), projects (typed versioned state), jobs, tickets, immutable review audit, object deletion outbox. No public schema grants. Original bytes live only in private object storage. Render uses temporary files solely as bounded OCR scratch space, never as persistent storage.

Project row locks serialize quota checks, deduplication, saves and deletion. Upload reserves an outbox key before object creation; an interrupted transaction leaves an eventually removable key, not an invisible permanent orphan. Identical file bytes create one document and one job, even concurrently. No match based only on amount. Stable bank account + transaction IDs, when explicitly present in the source, are passed to the existing domain deduplicator.

Jobs use PostgreSQL leases, SKIP LOCKED, fencing tokens and per-page checkpoints. A completed page's stable candidate IDs survive retries. Up to two processing attempts per file; each parser/OCR subprocess is time- and memory-bounded. Every checkpoint rechecks project existence, expiry and lease ownership. Deletion cascades jobs, so late results cannot recreate a review. A free Render instance can sleep: pending jobs resume on the next wake. Closing the tab does not cancel a job.

Retention begins at project creation, not last activity: access ends at exactly 24 hours. The active worker removes expired records; an hourly GitHub Actions maintenance request performs real retention work even when no visitors arrive. It is not a keep-alive loop. Physical deletion can lag the access cutoff until that job runs; GitHub scheduling/provider outages can delay it. Failed object deletions remain in an outbox for retry. Browser downloads already saved by the visitor cannot be recalled.

## Extraction and review semantics

- PDF: pypdf page text; scanned pages and PNG/JPEG: PDFium/Pillow → real local Tesseract (English). The OCR protocol is replaceable; no external LLM is called and no paid OCR key is needed.
- Conservative, deterministic English-label extraction proposes estimates, price changes, payment requests, payments, refunds and conditions. Unknown currency, ambiguous dates and unsupported text stay unknown. USD only. A deposit/balance mentioned in an invoice is not evidence of new cash.
- Candidates retain original amount text, page, snippet, extraction method and immutable file checksum. Financial strings are parsed with Decimal into bounded integer cents, with no float accounting or fractional-cent rounding.
- The review retains original candidates unchanged. Corrections, inclusion/exclusion, contractor membership, payment state, chosen estimate/request and links are saved as a separate timestamped user statement. The API creates domain sources and typed records; all accepted values trace to an existing page plus any review statement.
- Saving is an explicit review of the current revision. Adding/extracting documents advances the revision. Previous decisions are not silently rebased: the domain sees stale decisions and the UI resets confirmation choices for rechecking. A stale browser save returns 409.
- Original-source truth is not certified by OCR or a user's click. Extraction review, semantic review, provenance and relationship decisions remain distinct. No automatic completion/payment-condition satisfaction is inferred.
- Results include the actual `HistoryInput`, `NormalizationResult`, `LedgerResult`, source content and additional extraction questions. Unknown remainder stays null/Unknown; unresolved evidence remains preliminary. Browser code formats money only. Changing choices hides previous amounts until a new successful calculation.

## Bounds and resource policy

10 MiB/file; 20 pages/file; 50 pages/project. Additional free-service safety caps: 20 files and 100 MiB/project, 150 candidates/project, 16 million pixels/page, 12,000 extracted characters/page, 20 outstanding tickets/project, 10 concurrent unexpired projects, 400 MiB reserved original storage globally. Oversized/unsupported inputs fail explicitly. The first version requires labelled English USD documents and manual correction; it is not a general document-understanding model.

Parser subprocess: 20 seconds for validation; 70 seconds/page, including Tesseract's 45-second timeout; Linux address-space cap 768 MiB and CPU cap 60 seconds. Production Render's instance memory limit remains lower and can terminate resource-heavy processing; saved jobs retry within the same bounds, then expose failure. No unbounded provider retries or usage-based OCR charges.

## Verification boundaries

Unit tests parse real fictional PDF bytes and call the real domain. Container integration tests use real PostgreSQL, private SeaweedFS S3 and Tesseract for PDF text/scans/PNG/JPEG. A separate connection probe exercises actual Supabase PostgreSQL/Storage, denies public reads, and deletes its fictional source. Playwright uploads documents through the cookie BFF and transfer tickets, checks $7,000, changes payment membership, reloads, isolates a second visitor, previews an original and deletes the review. Remote mode uses an explicit public URL and never launches local servers. Fault-injection tests do not count as proof of OCR/provider connectivity.
