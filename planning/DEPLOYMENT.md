# Deploying RenoTrace

See [stage 9 report](STAGE_9_REPORT.md) for the latest release gate. Stage 5 below is the prior stateless release; stage 6 adds private expiring guest reviews, PostgreSQL, object storage and real OCR. Stages 7/8 reuse these resources for question history, immutable calculations and invoice comparisons. Account registration is not required.

## Stage 9 PDF release

Published application SHA: `bd8e80ceb704f563fa7290c1c836a8ab2b0ee296`. Frontend: <https://renotrace.vercel.app/review>; backend: <https://renotrace-api.onrender.com>. The owner confirmed Render Live and Vercel Ready on 2026-11-15. OpenAPI reports `0.9.0`; public PDF acceptance and its verification boundaries are recorded in the [stage 9 release report](STAGE_9_REPORT.md#release-gate). Later report/screenshot commits do not change this deployed runtime. Existing Vercel Hobby, Render Free and Supabase Free resources are reused without paid additions.

No schema migration is needed: the existing project-owned single-use tickets table also carries PDF-only tickets. No new secret, service or paid resource is needed. The locked production dependencies now include ReportLab; the backend package includes the font/license. Keep existing `BACKEND_URL`, `FRONTEND_ORIGIN`, host/port and health checks. PDF binary responses go directly from FastAPI to the browser; the Vercel BFF handles only the small owner-authorized ticket response.

After CI passes, deploy the exact checked SHA to Render first. Verify `/healthz`, OpenAPI `0.9.0`, `POST /api/guest/projects/{project_id}/exports` and `GET /api/guest/export`; then deploy the same SHA to Vercel using existing production variables. Keep auto-deploy disabled. Run the public guest flow with real downloads at all three widths and the existing demo regression, using the commands in the [stage 9 report](STAGE_9_REPORT.md#reproduce-checks). Inspect the downloaded PDF contents and rendered pages, not only HTTP status. Do not set `GUEST_LOCAL_DB` for remote testing.

Rollback frontend first, then backend to the prior stage 8 SHA `3dba4d1b0d47ad3a315a02b96ca636fa1fb165b7`. Preserve existing tables, original documents, snapshots, comparisons and retention cleanup. Unused PDF tickets expire after five minutes; the previous backend ignores their purpose. No export files need restoring or purging. Previously downloaded user copies cannot be revoked.

## Stage 8 migration and release

Published application SHA: `3dba4d1b0d47ad3a315a02b96ca636fa1fb165b7`. Frontend: <https://renotrace.vercel.app/review>; backend: <https://renotrace-api.onrender.com>. The owner confirmed Render Live and Vercel Ready on 2026-11-15. The additive migration was applied before switching the backend; OpenAPI reports `0.8.0`. See [release evidence and verification boundaries](STAGE_8_REPORT.md#release-gate) for independent public checks. Later report/screenshot commits do not change the deployed runtime.

No new service or secret is needed. Existing Vercel Hobby, Render Free and Supabase Free resources are reused, without paid additions. After CI passes for the release SHA, use its checked checkout to apply the additive migration **before** deploying the new backend:

```powershell
.\scripts\uv.ps1 run --locked --env-file .env.guest.local python -m app.guest.manage migrate
```

The API does not migrate on startup. New `invoice_state`, `rechecks` and immutable `comparisons` tables reference existing projects with deletion cascades. Existing source/project data, stage 7 cards/replies/snapshots and original expiry are preserved; old snapshots are not backfilled. The original project JSON shape remains readable by the stage 7 backend; invoice additions live in the side table and are reattached only to their saved review ID.

Deploy the checked SHA to Render first, check `/healthz`, OpenAPI `0.8.0` and recheck routes, then deploy the same SHA to Vercel with existing production variables. Keep auto-deploy disabled. Run public stage 8 Playwright and the separate demo regression, without local servers:

```powershell
$env:RENOTRACE_BASE_URL='https://renotrace.vercel.app'
npm run test:guest -- --grep 'recheck corrected' --timeout=600000
npm run test:remote
```

Rollback: return Vercel to the previous stage 7 deployment first; then restore backend SHA `6cb667c5308a9cee98b722f7b3956dcd8ffd58dc` if needed. Preserve all additive tables and cleanup. Stage 7 deletion still cascades the new rows. Its interface does not expose comparisons. A review saved by the older backend has no stage 8 invoice assessment; on upgrade the older side-table assessment is not silently applied to that new review. Existing frozen comparisons remain readable after upgrade but require current-evidence rechecking. Never restore expired/deleted guest evidence or drop the new tables as a rollback shortcut.

Local integration tests validate populated migrations, legacy-compatible project JSON, concurrent saves, restart recovery and cascades. See [stage 8 contract](RECHECK_CONTRACT.md) for exact semantics and limits. Public release verification is recorded in the stage report; a local build alone is not a release.

## Stage 7 migration and release

Published application: `6cb667c5308a9cee98b722f7b3956dcd8ffd58dc` at <https://renotrace.vercel.app/review>, backend <https://renotrace-api.onrender.com>. Render Live and Vercel Ready were confirmed by the owner on 2026-11-15; public test evidence and verification boundaries are recorded in [the stage report](STAGE_7_REPORT.md#release-gate). Later report/CI commits do not change the deployed application.

No new service, environment variable or paid resource is needed. **Before deploying the stage 7 backend**, explicitly run the existing migration command from the checked checkout:

```powershell
.\scripts\uv.ps1 run --locked --env-file .env.guest.local python -m app.guest.manage migrate
```

API startup intentionally does not run migrations. This command adds four project-owned tables and the immutable-snapshot trigger under an advisory lock. Existing projects, sources and audit entries are retained. Old audit rows are not backfilled into full snapshots. Linux integration tests apply the migration again to a populated project, restart the API and verify frozen history and cascade deletion/expiry.

After both CI jobs pass for the release SHA, manually deploy that SHA to **Render first**, then Vercel, using the existing procedure below. The old frontend works with the additive backend response; the new frontend requires the stage 7 backend. Keep auto-deploy disabled. Run local integration and browser suites serially: the integration suite deliberately restarts the API.

Rollback: return the frontend to the previous deployment first, then redeploy the previous backend SHA if necessary. **Keep the additive database schema and all existing data**, and retain hourly cleanup. The stage 6 backend's project deletion still cascades the new FK tables. Do not restore expired/deleted guest data, drop the schema or replay old audit rows. Stage 7 snapshots and discussion remain in storage until normal expiry but are not exposed by the older frontend.

Public stage 7 verification (does not start local servers):

```powershell
$env:RENOTRACE_BASE_URL='https://renotrace.vercel.app'
npm run test:guest -- --grep 'persistent question' --timeout=600000
```

The test uses only repository synthetic files, stores a text reply, exercises a lost-response retry, reloads, checks old/new calculation amounts, and deletes its own test review. The existing remote demo suite remains separate. See [stage 7 contract](CASEWORK_CONTRACT.md) for limits and semantics.

## Stage 6 guest reviews

### Local full stack

Install the locked Python/Node dependencies as below, then start Docker Desktop. The Compose project is named `renotrace-guest-local` and binds test ports only on loopback. Its documented credentials are disposable local test values, never production secrets.

```powershell
docker compose -f infra/guest.compose.yml up -d --build
.\scripts\uv.ps1 run --locked python tools/setup_guest_local.py
npm run build
$env:BACKEND_URL='http://127.0.0.1:8106'
node node_modules/next/dist/bin/next start apps/web --hostname 127.0.0.1 --port 3106
```

Open `http://127.0.0.1:3106/review`. Compose persists PostgreSQL and private SeaweedFS S3 in named Docker volumes. The API has real Tesseract in its image. The source bind mount is **local development only**; the production image contains the checked package and no bind mount. No secret file is baked into either image.

```powershell
$env:GUEST_API_URL='http://127.0.0.1:8106'
$env:GUEST_LOCAL_DB='1'
.\scripts\uv.ps1 run --locked pytest tests/integration -q
npm run test:guest
```

Stop the manually started frontend before Playwright, which starts its own frontend. Remote mode: set `RENOTRACE_BASE_URL=https://renotrace.vercel.app`, then `npm run test:guest -- --timeout=600000`; no local servers are started in that mode. The larger whole-journey timeout accommodates the free backend under concurrent OCR load. The legacy `npm run test:e2e` / `npm run test:remote` retain their original demo behavior.

Public API checks use `GUEST_API_URL=https://renotrace-api.onrender.com` and `pytest tests/integration/test_guest_http.py`. The public oversized-upload transport can close the connection instead of returning HTTP 413. For that known diagnostic only, set `GUEST_ALLOW_OVERSIZE_DISCONNECT=1`: the test then still requires no saved document and a successful subsequent valid calculation. The opt-in never accepts transport failures for valid files. Keep it unset in local/CI checks, which require HTTP 413. The large-valid-original case uploads and downloads a PDF exceeding 9 MiB, checking exact bytes and real extraction. Do not set `GUEST_LOCAL_DB` for public tests; persistence tests intentionally target only disposable local services.

### Production configuration

Reuse existing Vercel `renotrace` and Render `renotrace-api`. Supabase Free organization **Lias**, project **renotrace**, Singapore (`zbedmuneynqvhzilobsz`); private `guest-originals` bucket, 10,485,760-byte limit, PDF/JPEG/PNG MIME allowlist. Data API is disabled, no Supabase Auth integration, no public bucket/read policy. Free allowances: 500 MB PostgreSQL and 1 GB object storage; the app caps reserved originals at 400 MiB and active reviews at ten. No paid services are authorized or required. See [Supabase pricing](https://supabase.com/pricing).

Render environment (backend only): `DATABASE_URL`, `PGPASSWORD`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REVIEW_STORAGE_BUCKET=guest-originals`, `FRONTEND_ORIGIN=https://renotrace.vercel.app`, `REVIEW_CLEANUP_SECRET`. Use the free IPv4 **session pooler** and TLS (`sslmode=require` or stronger). No dedicated IPv4 add-on. Service-role key is never exposed to Next.js or browser code. Configure the same cleanup secret in GitHub repository Actions secrets; it authorizes only expiry/outbox processing.

Secrets may be placed locally in ignored `.env.guest.local`; use `uv run --env-file .env.guest.local ...`. Never commit that file or include it in Docker. Apply the additive backend-only schema explicitly:

```powershell
.\scripts\uv.ps1 run --locked --env-file .env.guest.local python -m app.guest.manage migrate
.\scripts\uv.ps1 run --locked --env-file .env.guest.local python tools/check_guest_connection.py
```

The probe uses only a fictional fixture, verifies real storage/text extraction and deletes it. The worker runs in the API process by default (`REVIEW_WORKER=1`). Its job state and page checkpoints are in PostgreSQL, so closing a browser or replacing a container does not lose work. For another deployment topology, `python -m app.guest.manage worker` runs the same leased worker; do not provision a paid worker for this release.

Vercel remains Root Directory `apps/web`, Node 24.x, include files outside root, install `cd ../.. && npm ci`, build `cd ../.. && npm run build`; server `BACKEND_URL=https://renotrace-api.onrender.com`. Originals bypass the [4.5 MB Vercel Function payload limit](https://vercel.com/docs/functions/limitations) via single-use backend transfer tickets. The session secret stays in a Secure HttpOnly cookie. Keep the production domain publicly accessible without Vercel account protection.

### Retention, release and rollback

Project access expires 24 hours after creation. The API worker performs expiry and retryable object deletion while active. `.github/workflows/guest-retention.yml` runs at minute 37 hourly and also supports manual dispatch. It calls a protected cleanup operation with two bounded attempts to allow free-backend startup. This is scheduled retention work, not artificial keep-alive traffic. Verify a successful manual run after release and monitor scheduled failures. GitHub can delay schedules or disable inactive public-repository schedules; a provider pause/outage can delay physical purge, while the API's access cutoff remains enforced. Supabase Free projects may pause after a week without activity; do not assume a paid availability guarantee.

Release only a SHA whose Linux and Windows checks are green. Linux checks include actual PostgreSQL/S3/OCR, restart and guest-browser acceptance, in addition to all previous tests. Keep auto-deploy disabled. Preserve the previous deployed SHA and service configuration before updating. Stage 5 had no guest database/files to back up; the initial stage 6 schema is additive and contains only explicitly created test data before launch. Keep any database snapshots private and expire guest-content backups with the original 24-hour retention window.

Manual deployment/rollback controls remain as described below. Deploy backend first to the checked SHA, verify health/guest session/upload/recalculation/cleanup, then deploy frontend to that **same SHA**. Run both remote demo tests and remote guest tests. A code rollback normally keeps the database intact; do not restore old guest rows or originals and thereby undo a deletion or extend expiry. Rolling back to stage 5 removes the guest UI/API: run cleanup separately until all stage 6 reviews expire and their originals are purged. Do not delete the database/bucket as part of routine rollback.

Original browser downloads cannot be remotely recalled. No persistent files belong on Render disk; only temporary OCR scratch files are used. See [guest contract](GUEST_REVIEW_CONTRACT.md) for precise endpoints, limits and semantics.

Production frontend: [renotrace.vercel.app](https://renotrace.vercel.app)

Backend: [renotrace-api.onrender.com](https://renotrace-api.onrender.com/healthz)

## Local use

Install with `scripts/setup.ps1` on Windows or `uv sync --locked` plus `npm ci` on Linux/macOS. Python 3.13.18, Node 24.11.0 and pinned package lockfiles are used for validation.

From the repository root, in terminal 1:

```powershell
.\scripts\uv.ps1 run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In terminal 2:

```powershell
Copy-Item .env.example apps/web/.env.local
npm run dev
```

Open http://127.0.0.1:3000. `BACKEND_URL` is read by the Next.js server, not the browser. Root `.env` is not automatically the Next workspace's env file. The ignored `apps/web/.env.local` or a process environment variable is required. For a production preview use `npm run build` then `npm start` with the same backend setting.

## Container backend

Build context is the **repository root**:

```sh
docker build -f infra/backend.Dockerfile -t renotrace-demo:stage5 .
docker run --rm --name renotrace-demo -e PORT=8000 -p 8000:8000 renotrace-demo:stage5
```

The Dockerfile pins Python 3.13.18 and uv 0.13.8, installs application dependencies using `uv sync --locked --no-dev --no-editable`, packages inline samples, and runs as UID 10001. The synthetic demo alone needs no database or secrets; guest reviews require the external services and environment described above. No Node runtime or persistent volume belongs in the production backend container. `.dockerignore` excludes local environments, credentials, browser artifacts and private backups. Host is `0.0.0.0`; use the hosting platform's `PORT` variable (default 8000). Configure its HTTP health probe to `/healthz`. Docker also declares a localhost health check using the same port.

After hosting the container on a platform you choose, verify:

```sh
curl --fail https://renotrace-api.onrender.com/healthz
curl --fail https://renotrace-api.onrender.com/api/demo/scenarios
curl --fail https://renotrace-api.onrender.com/api/demo/scenarios/FIN-11
```

The public backend accepts only these synthetic-demo actions. Private routes are absent. Provider request/concurrency limits and TLS are hosting settings; application rate limiting is not implemented in this stage. No browser CORS configuration is needed because browsers call the same-origin Next BFF.

Local Docker Engine was unavailable during development. The Linux CI job builds the image and tests a running container on **PORT=8080**, including the packaged FIN-11 calculation; inspect that job's result for the committed revision.

## Vercel frontend

1. Import the existing IliasGalikhanov/renotrace repository, without cloning it into a new repository. Select **Next.js**, Root Directory **apps/web**, Node **24.x**.
2. Enable inclusion of source files outside the root directory so npm workspaces and the root lockfile are available.
3. `apps/web/vercel.json` sets install command `cd ../.. && npm ci`, build command `cd ../.. && npm run build`, and output directory `.next` relative to the frontend root.
4. Set server environment variable `BACKEND_URL=https://renotrace-api.onrender.com` for the intended Preview/Production environment. Do not prefix it with `NEXT_PUBLIC_`. Use a reachable HTTPS origin without `/api/demo` appended; loopback points to Vercel itself, not your computer.
5. After deployment, exercise Try sample → FIN-16 → The contractor → Another recipient → Reset. Check $7,000 → $5,000 → $7,000 and the restored provisional status.

The BFF needs a running Node/serverless runtime; this is not a static export. A missing backend setting returns 503, an unavailable backend 502. Those errors are surfaced with retry in the UI. Use the production domain for anonymous access; preview/deployment URLs may require Vercel Authentication.

Reference documentation: [Vercel monorepos](https://vercel.com/docs/monorepos), [Vercel build configuration](https://vercel.com/docs/builds/configure-a-build), [uv locking and synchronization](https://docs.astral.sh/uv/concepts/projects/sync/), [Playwright web servers](https://playwright.dev/docs/test-webserver).

## Browser verification

After installing dependencies:

```powershell
npx playwright install chromium
npm run build
npm run test:e2e
```

On Linux CI use `npx playwright install --with-deps chromium`. Tests start their own API (8100) and built Next server (3100) and stop both afterward. They refuse to reuse an existing server on those ports. Three Chromium projects cover widths 360, 768 and 1440; no Firefox/WebKit or real mobile device compatibility is claimed. Failure traces/screenshots are in `test-results`, HTML report in `playwright-report`.

To deliberately refresh committed visual examples, run with `RENOTRACE_CAPTURE_DIR=planning/screenshots/stage4` in the shell. Otherwise test screenshots stay in ignored test output. Inspect screenshots before committing; passing overflow assertions is not a substitute for visual review.

## Free hosting and cold starts

Account checks on 2026-11-14: Vercel scope `lias5` is Hobby; Render `My Workspace` is Hobby with no card, no services, no pending charges, and zero usage before this deployment. Render's displayed monthly allowance was 750 free instance hours, 5 GB outbound bandwidth and 500 pipeline minutes. Select **Free ($0/month), 0.1 CPU / 512 MB** explicitly: the create form defaults to a paid instance. No database, disk, worker, storage, domain purchase or paid trial is needed. Never attach a payment method or upgrade automatically.

[Vercel Hobby](https://vercel.com/docs/plans/hobby) is for personal noncommercial use; this is a synthetic educational/hackathon demonstration. Reassess the plan before commercial use. [Render Free](https://render.com/docs/free) sleeps after 15 minutes without inbound traffic and may take about a minute to wake. Workspace allowances are shared; without a payment method quota exhaustion can suspend service/builds. Free hosting has no availability guarantee. No recurring charges are authorized.

Render settings: public repository URL, branch `main`, Docker runtime, blank Root Directory, Dockerfile `infra/backend.Dockerfile`, build context `.`, default Docker command, health `/healthz`, Free instance, **Auto-Deploy Off**. The container reads Render's `PORT`; no additional environment or secrets are required.

BFF upstream timeout is 20 seconds, Vercel `maxDuration` is 30 seconds. Browser attempts time out after 25 seconds. Only user-initiated loads retry: at most four attempts, 20 seconds between attempts, approximately 160 seconds maximum. HTTP 502/503/504 and transport failures retry; other HTTP errors do not. Waiting text says up to three minutes; exhaustion exposes manual retry. Changing scenario/answer aborts both the old request and its retry timer; generation checks reject late responses. Previous figures stay hidden. There are **no scheduled pings or keepalive loops**.

`tests/e2e/startup.spec.ts` runs the real production Next BFF against a proxy that becomes available after 55 seconds, then forwards to the actual Python API. It verifies timeout, retry and a real $4,700 result. Browser-clock tests cover exhaustion and cancellation at every viewport.

## Public verification without local servers

```powershell
$env:RENOTRACE_BASE_URL = 'https://renotrace.vercel.app'
$env:RENOTRACE_CAPTURE_DIR = 'planning/screenshots/stage5'
npm run test:remote
```

`playwright.remote.config.ts` requires HTTPS and has **no webServer setting**. It runs real FIN-01/11/16 flows, Reset, separate browser contexts, sources and screenshots at 360/768/1440. It does not start or reuse local servers. Default `npm run test:e2e` stays local. Remote assertions allow the bounded cold-start window. Remove the capture variable for ordinary runs.

For a true sleep check, close demo tabs and stop tests for more than 15 minutes; do not poll the backend. Then run the remote FIN-16 journey. Record startup time and outcome. A simulated delay does not establish that Render actually slept. Separately use Render **Restart service**, wait for its platform status, then rerun remote checks.

## Release and rollback

Current verified application release (2026-11-15): **`61275bb8dae6827f7ebd1c208abd42d79c6c9bbd`** on both Vercel and Render. The owner confirmed platform Ready/Live; independent public browser and HTTP checks passed, including actual PDF downloads. See [stage 10 evidence](STAGE_10_REPORT.md). Later documentation/artifact commits do not change this live revision. No schema/environment change or paid resource was added.

Stage 10 changes presentation to API `0.10.0` / PDF `reconciliation-pdf/2`. No migration, environment variables, new services or paid resources are required. Publish the checked implementation SHA recorded in [stage 10 report](STAGE_10_REPORT.md), backend first and frontend after its HTTPS export check. Then run the public recheck/download journey on all three widths and the ordinary-invoice manual-entry journey on 1440 px, followed by `npm run test:remote`. Before this release both hosts used `bd8e80ceb704f563fa7290c1c836a8ab2b0ee296`; redeploy that SHA to both hosts if rollback is needed. Existing snapshots retain their data; PDF exports use the deployed renderer version. Already downloaded PDF/1 copies do not change.

1. Commit/push; require both `RenoTrace checks / verify` matrix jobs to succeed for that exact SHA, including Linux container smoke. Record the previously live frontend/backend revisions and deployment IDs.
2. Render: **Manual Deploy → Deploy a specific commit**, enter the checked SHA. Wait for Live; verify health, scenario list, FIN-11 and FIN-16 POST. Keep auto-deploy off.
3. Vercel: **Deployments → Create Deployment**, paste the full checked SHA in **Branch, Commit, or URL**, verify the resolved commit and **Production**, then choose **Deploy to Production** with `BACKEND_URL` set. Git-triggered deployments are disabled in `apps/web/vercel.json` (`git.deploymentEnabled: false`). Push runs CI but does not release. Manual deployment is an operator-controlled CI gate, not an automated integration.
4. Run `npm run test:remote` on the stable production domain in clean contexts. Record the tested SHA and results. A docs-only follow-up commit does not automatically change the live revision.
5. Roll back frontend using the previous successful production deployment / **Instant Rollback** where available; otherwise redeploy the previous known-good commit. Render Free retains only its two most recent previous deploys for rollback; alternatively deploy the previous known-good SHA manually. Repeat public checks. Restore environment/config changes separately: code rollback does not restore account settings.

References: [Vercel Git settings](https://vercel.com/docs/project-configuration/git-configuration), [function duration](https://vercel.com/docs/functions/configuring-functions/duration), [Render deploys](https://render.com/docs/deploys), [Render rollbacks](https://render.com/docs/rollbacks).

Observed project settings: Vercel `lias5/renotrace`, project `prj_Vu9x6NyLYKqrVPomRi339hmaN5nF`, Root Directory `apps/web`, include files outside root enabled, Basic build machine, on-demand concurrent builds disabled. Set **Node 24.x explicitly**; the platform default may select a newer major despite the root package engine range. Render `renotrace-api`, service `srv-dbs9iet6e07s7397sbog`, Ohio, Free, Auto-Deploy Off, `/healthz`, runtime bound to `0.0.0.0:10000` from the injected PORT. GitHub App access was granted only to RenoTrace with user confirmation.
