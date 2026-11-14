# Stage 5 — first public deployment

Date: 2026-11-14. Synthetic demonstration only; decisions are calculated per request and not saved.

## Published services

| Component | Public address | Hosting |
| --- | --- | --- |
| Next.js frontend | https://renotrace.vercel.app | Vercel Hobby, scope `lias5`, project `renotrace` |
| Python API | https://renotrace-api.onrender.com | Render Hobby workspace, Free Docker web service `renotrace-api`, Ohio |
| Health | https://renotrace-api.onrender.com/healthz | HTTP 200, `renotrace-api` |

Both run release commit **`e76b358f9ef374a4f3f0f0ca0c81d147aabef06e`** (`feat: prepare public demo with bounded cold-start recovery and remote checks`). Documentation commits made after verification do not change this released SHA.

- Frontend deployment: `dpl_F3sDZ9nNAUQ89jreMbdGMuhZmUXH`, Ready / Production, Node **24.x**, Fluid Compute; function region `iad1`. Runtime version was checked in the deployment settings. Its immutable deployment hostname is `renotrace-mf8v306jt-lias5.vercel.app`; share the stable production domain above, since deployment URLs can require Vercel authentication.
- Backend deployment: `dep-dbs9ifd6e07s7397scug`, service `srv-dbs9iet6e07s7397sbog`, Live. Docker installs through `uv sync --locked --no-dev --no-editable`; logs confirm Uvicorn on `0.0.0.0:10000`, using Render's injected `PORT`, and successful `/healthz` probes.
- Public browser tests use fresh Chromium contexts with no login cookies, Vercel password or bypass secret. Hosting dashboards were operated through the built-in browser. The GitHub App was granted access only to `renotrace`, after explicit user approval.

## Cost and limits

Selected recurring cost: **$0/month**, within included quotas. No paid trial, domain, database, worker, disk, storage or card was added. A post-deployment Render billing check still showed no card, Services $0.00 and Pipeline Minutes $0.00 (usage reporting can lag). Accounts had no existing projects/services to reuse, so one frontend project and one backend service were created.

Render billing before creation: Hobby, no card on file, no pending charges; 750 free instance hours, 5 GB outbound bandwidth and 500 pipeline minutes per month, shared by the workspace. Free compute is 0.1 CPU / 512 MB. Quota exhaustion can suspend service/builds; this is not unlimited hosting. Vercel Hobby is for noncommercial personal use; reassess the plan before a commercial launch. See the primary provider references and account settings in [DEPLOYMENT.md](DEPLOYMENT.md).

## Changes and validation

The financial modules and demo API remain unchanged. Added a shared browser request helper with at most four attempts on temporary HTTP/transport failures, 20-second retry delays and cancellation on changed selections. Each attempt has a 25-second client deadline; BFF upstream deadline is 20 seconds and Vercel function limit is 30 seconds. The UI explains the free service wake-up, hides prior figures, and provides manual retry after exhaustion. No periodic requests keep the service awake.

Added `playwright.remote.config.ts` and `npm run test:remote`. An HTTPS base URL is required; this configuration has **no local webServer**, no service startup and no reused local endpoints. Ordinary `npm run test:e2e` retains its local servers.

| Check | Observed result |
| --- | --- |
| Python regression suite | **347 passed**; domain/demo coverage **99.86%** |
| Ruff / formatting / mypy / specification integrity | Passed |
| Next production build / TypeScript / Prettier | Passed |
| Local HTTP smoke | Real FastAPI + built Next BFF, FIN-16 $7,000 → $5,000 passed |
| Local Playwright | **34 passed**, two duplicate slow-start executions intentionally skipped; all UI tests run at 360/768/1440 |
| Actual delayed backend proxy | Real BFF timed out/retried, then Python normalization → ledger returned FIN-01 $4,700 after **55 seconds** of delayed readiness |
| Retry exhaustion/cancellation | Exactly four attempts, no subsequent background traffic, manual retry works, new answer cancels old retry |
| Published API over HTTPS | Health, three-scenario catalog, FIN-11 and FIN-16 POST for contractor/other/unknown passed |
| Published frontend, after Node 24 deployment and backend restart | **12 remote tests passed**, 46.0 seconds; clean contexts at 360/768/1440 |
| FIN-01 | Requested **$5,500**, remaining **$4,700**, disclosed **$800** material credit/source |
| FIN-16 | **$7,000 → $5,000 → $7,000**, unknown/provisional state and Reset/reload passed |
| FIN-11 | New charge **$8,500**, open balances **$10,500**, source disclosure passed |
| Independent visitors | One visitor's decision leaves the second visitor at provisional $7,000 |
| Visual review | Public captures inspected at 360/768/1440; readable figures, no horizontal overflow |
| Render restart | Dashboard recorded “Service restarted by you” at 22:26 GMT+5; the subsequent public suite passed |

Release CI: [RenoTrace checks #43620601353](https://github.com/IliasGalikhanov/renotrace/actions/runs/43620601353), both Linux and Windows succeeded before deployment. Linux built and ran the actual container, including health and FIN-11.

The final Vercel build used locked `npm ci` and succeeded. Its remaining npm warnings concern the platform-provided `cache-dir` environment setting; the unsupported Node engine warning was eliminated by selecting Node 24.

## Actual idle wake-up

All remote requests stopped at or before **17:29:38 UTC**. Render application logs show `Shutting down`, `Application shutdown complete` and `Finished server process [1]` at **17:44:36 UTC** (22:44:36 GMT+5), confirming actual idle shutdown. No user-generated health checks or keepalive requests were made during this interval. The first subsequent anonymous browser journey started at **17:45:43 UTC**, using the remote FIN-16 test at 360 px without a preceding warm-up request. **Passed**: the full FIN-16 journey took **51.1 seconds** (53.3 seconds including test runner setup), including the first FIN-01 page calculation, wake-up, $7,000 → $5,000 → $7,000, unknown/provisional state, Reset and reload. This is whole-journey timing, not an isolated API latency measurement. No manual retry or warm-up request was needed. The published site was then opened and verified in the built-in browser as well.

## Commands and operation

Local:

```powershell
.\scripts\uv.ps1 run --locked pytest --cov=app.ledger --cov=app.normalization --cov=app.demo
npm run build
npm run typecheck
npm run format:check
.\scripts\uv.ps1 run --locked python tools/smoke_test.py
npm run test:e2e
```

Public (no local servers):

```powershell
$env:RENOTRACE_BASE_URL = 'https://renotrace.vercel.app'
npm run test:remote
```

Backend local: `scripts/uv.ps1 run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000`. Frontend local: copy `.env.example` to `apps/web/.env.local`, then `npm run dev`. Full setup, release and rollback instructions: [DEPLOYMENT.md](DEPLOYMENT.md).

Auto-deploy is **off on both platforms**. Git push runs CI; manually select the exact successful SHA on Render and Vercel, then run public acceptance. Use the previous successful deployment or manually rebuild the previous known-good SHA for rollback. This is the first code release: there is no earlier production code version yet. Account environment/configuration must be restored separately. Free Render retains two previous deployments for instant rollback; no rollback was performed during this stage.

## Screenshots and limitations

Public captures: [FIN-01 desktop](screenshots/stage5/FIN-01-public-1440.png), [FIN-16 mobile](screenshots/stage5/FIN-16-public-360.png), [FIN-11 tablet](screenshots/stage5/FIN-11-public-768.png). All nine scenario/viewport combinations are in `planning/screenshots/stage5/`.

The URL is a persistent hosted project URL, not a developer-machine tunnel. Availability remains subject to free-plan quotas and provider outages. An idle backend may take about a minute to start; retries are bounded at approximately 160 seconds and can still end with a manual retry. Chromium desktop emulation was checked; real mobile hardware, Safari and Firefox were not tested. There is no registration, persistence, OCR, private case API, uploads, external AI or payment processing. No next-stage module was added.
