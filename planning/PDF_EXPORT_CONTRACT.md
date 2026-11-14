# Stage 9 - PDF reconciliation from frozen evidence

API `0.9.0`; PDF layout/content contract `reconciliation-pdf/1`. Calculation contract remains `guest-review/3`; comparison algorithm remains `invoice-comparison/1`. This extends [saved calculations](CASEWORK_CONTRACT.md) and [rechecks](RECHECK_CONTRACT.md), without changing financial semantics, retention or guest ownership.

## Selection and historical consistency

The export controls appear only inside an opened saved calculation or completed comparison. The date, saved version/revision and result reference are visible before download. A draft ID, arbitrary current `HistoryInput`, unsaved form or client-provided totals cannot be exported. Preliminary results are allowed, with prominent uncertainty next to the saved indicators.

An ordinary report reads exactly its selected immutable snapshot: project documents/choices, result and discussion stored at that save. For each saved reply it presents the last version that existed **in that snapshot**, not the latest version in today's case. A completed-recheck report reads both snapshot IDs from the immutable comparison, its saved changes/findings and its exact pinned `reply_versions`. The new-review discussion includes only pinned package replies; the previous-basis section clearly labels its own historical replies. An unpinned newer reply in the new snapshot is not silently substituted for the pinned answer. Later files, replies, owner decisions and source changes are never consulted for report content.

No `result_for`, normalization, ledger, reconciliation or comparison algorithm is run for export. Today's project is read only to enforce access before issuing a ticket, before rendering and again after rendering. The report is always labelled as a historical saved record, not a live applicability assessment. It shows separate review, comparison and PDF-generation times. A fresh PDF may have different generation metadata, but historical content stays fixed.

## Actual API and transport

| Route | Request / response |
| --- | --- |
| POST `/api/guest/projects/{project_id}/exports` | Owner Bearer session required. JSON `{ "kind": "snapshot" \| "comparison", "result_id": "UUID" }`; strict extra-field rejection. Returns `{ "token": "...", "expires_in": 300 }`. Validates the selected frozen result belongs to the project. |
| GET `/api/guest/export` | `Authorization: Bearer <single-use PDF ticket>`, never query-string credentials. Returns actual `application/pdf` bytes with attachment filename `renotrace-{kind}-{result_id}.pdf`. |

The same-origin Next.js BFF exposes the first route and adds a configured `transfer_url` pointing to the backend `/api/guest/export`. The browser fetches the binary directly with a PDF-only ticket in the Authorization header and initiates a Blob download. No PDF bytes pass through Vercel's BFF response limit. No session cookie is sent to the backend. The UI supports loading, errors and manual retry with a new ticket; leaving the selected result aborts the outstanding browser request. Blob URLs are revoked on replacement/unmount. No credentials appear in a URL, suggested filename or PDF.

Tickets reuse the existing `tickets` table with purpose `pdf`, target ID in `file_id` and validated target kind in `name`. Only the digest is persisted. Tickets expire after five minutes, are consumed once, and cannot be used for uploads or original downloads. An owner session token is not a PDF ticket. Access is checked again after rendering, so deletion/expiry during generation returns 404. A browser download already completed cannot be revoked remotely; the UI and report explain that the local copy remains after guest expiry.

Responses: 404 for missing/foreign/deleted/expired results, unusable/replayed tickets or drafts; 422 for malformed selection; 429 for the existing 20 active-ticket bound; 413 when PDF exceeds 300 pages or 16 MiB. Headers include `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, attachment disposition, sandbox CSP and no-referrer. CORS uses the existing exact frontend origin and allows the required Authorization header.

## Content and sources

The English A4 report contains report ID, dates, contract/algorithm versions; selected invoice and USD requested/C/P/R; documented conditions or Unknown; copied financial input records with source excerpts; checked invoice composition with review/origin states and unexplained difference; questions, replies and independent evidence/owner-decision states; comparison metrics/positions/payment reflections/conditions and remaining issues; both financial bases; and a numbered source register.

`[S3, p. 2]` references identify saved original files/pages. The register includes file name, immutable file ID/version, page count, extraction state/method, SHA-256 of original bytes, snapshot membership and short excerpts. Owner-review sources are identified separately as recorded owner input. Reply entries include explicit version, timestamp, owner-reported origin, reply ID, a SHA-256 of the original reply text and attachment references. Missing historical source/detail is stated explicitly rather than reconstructed. Source excerpts are partial and originals are **not** merged, embedded or attached.

Integer cents are formatted without float, preserving negatives and exact hundredths; null becomes **Unknown**. Formatting and rendering do not recalculate C/P/R. Requested deltas and saved comparison deltas remain separate. No reduction is presented as savings; R is not a safe-to-pay amount, and absence of questions is not a guarantee. A decision to stop clarification or accept an explanation does not hide unresolved evidence.

## Rendering, isolation and resource bounds

ReportLab `5.1.0` is pinned in **production** dependencies and in `uv.lock`; the non-editable backend wheel/container includes the font. DejaVu Sans is bundled with its [upstream license](https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/LICENSE) in `app/guest/fonts/LICENSE.txt`. No external font/resource fetch occurs during generation. Unsupported glyphs use explicit `[U+XXXX]` labels rather than invisible missing-character boxes. Font availability does not depend on the host OS.

User strings are escaped as text before Paragraph rendering. No HTML, JavaScript, attachments or active links are embedded. External addresses and recognizable credential-like strings are replaced in presentation; original source/checksum and snapshot remain unchanged. This is not a general-purpose sensitive-data detector for arbitrary text, so users must still inspect information they choose to share. Application credentials are absent by construction: only allowlisted fields of the frozen model are rendered, never runtime config, headers, tickets, storage locators or owner hashes.

PDF generation uses an in-memory buffer closed on success or failure. No export object, server file, export snapshot or audit mutation is saved; the existing five-minute ticket is the only added database row. Neither financial/discussion data nor the 24-hour expiry is extended. Ticket rows already cascade with deletion/expiry; no new schema migration, storage bucket, worker, environment variable or paid resource is needed. Bounds fail explicitly rather than returning a partial PDF.

Repeated table headers, wrapping paragraphs/long words, split rows and numbered pages support long saved content. Monetary summary tables remain together. Three fictional examples and a long-layout stress case are rendered and inspected in stage 9 QA; programmatic PDF extraction is additional evidence, not a substitute for that visual check.
