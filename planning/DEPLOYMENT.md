# Deploying the synthetic demo

See STAGE_5_REPORT.md for the observed deployment status and released revisions. The app serves only bundled synthetic data. It is not a private case service, and has no persistence or upload route.

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

The Dockerfile pins Python 3.13.18 and uv 0.13.8, installs application dependencies using `uv sync --locked --no-dev --no-editable`, packages inline samples, and runs as UID 10001. No Node runtime, database, secrets or volume is needed. `.dockerignore` excludes local environments, credentials, browser artifacts and private runtime data. Host is `0.0.0.0`; use the hosting platform's `PORT` variable (default 8000). Configure its HTTP health probe to `/healthz`. Docker also declares a localhost health check using the same port.

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

1. Commit/push; require both `RenoTrace checks / verify` matrix jobs to succeed for that exact SHA, including Linux container smoke. Record the previously live frontend/backend revisions and deployment IDs.
2. Render: **Manual Deploy → Deploy a specific commit**, enter the checked SHA. Wait for Live; verify health, scenario list, FIN-11 and FIN-16 POST. Keep auto-deploy off.
3. Vercel: **Deployments → Create Deployment**, paste the full checked SHA in **Branch, Commit, or URL**, verify the resolved commit and **Production**, then choose **Deploy to Production** with `BACKEND_URL` set. Git-triggered deployments are disabled in `apps/web/vercel.json` (`git.deploymentEnabled: false`). Push runs CI but does not release. Manual deployment is an operator-controlled CI gate, not an automated integration.
4. Run `npm run test:remote` on the stable production domain in clean contexts. Record the tested SHA and results. A docs-only follow-up commit does not automatically change the live revision.
5. Roll back frontend using the previous successful production deployment / **Instant Rollback** where available; otherwise redeploy the previous known-good commit. Render Free retains only its two most recent previous deploys for rollback; alternatively deploy the previous known-good SHA manually. Repeat public checks. Restore environment/config changes separately: code rollback does not restore account settings.

References: [Vercel Git settings](https://vercel.com/docs/project-configuration/git-configuration), [function duration](https://vercel.com/docs/functions/configuring-functions/duration), [Render deploys](https://render.com/docs/deploys), [Render rollbacks](https://render.com/docs/rollbacks).

Observed project settings: Vercel `lias5/renotrace`, project `prj_Vu9x6NyLYKqrVPomRi339hmaN5nF`, Root Directory `apps/web`, include files outside root enabled, Basic build machine, on-demand concurrent builds disabled. Set **Node 24.x explicitly**; the platform default may select a newer major despite the root package engine range. Render `renotrace-api`, service `srv-dbs9iet6e07s7397sbog`, Ohio, Free, Auto-Deploy Off, `/healthz`, runtime bound to `0.0.0.0:10000` from the injected PORT. GitHub App access was granted only to RenoTrace with user confirmation.
