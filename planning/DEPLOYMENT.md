# Preparing the synthetic demo for deployment

These are deployment instructions and checked-in configuration; no hosted project, paid service or public deployment was created in stage 4. The app serves only bundled synthetic data. It is not a private case service, and has no persistence or upload route.

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
docker build -f infra/backend.Dockerfile -t renotrace-demo:stage4 .
docker run --rm --name renotrace-demo -e PORT=8000 -p 8000:8000 renotrace-demo:stage4
```

The Dockerfile pins Python 3.13.18 and uv 0.13.8, installs application dependencies using `uv sync --locked --no-dev --no-editable`, packages inline samples, and runs as UID 10001. No Node runtime, database, secrets or volume is needed. `.dockerignore` excludes local environments, credentials, browser artifacts and private runtime data. Host is `0.0.0.0`; use the hosting platform's `PORT` variable (default 8000). Configure its HTTP health probe to `/healthz`. Docker also declares a localhost health check using the same port.

After hosting the container on a platform you choose, verify:

```sh
curl --fail https://YOUR-BACKEND/healthz
curl --fail https://YOUR-BACKEND/api/demo/scenarios
curl --fail https://YOUR-BACKEND/api/demo/scenarios/FIN-11
```

The public backend accepts only these synthetic-demo actions. Private routes are absent. Provider request/concurrency limits and TLS are hosting settings; application rate limiting is not implemented in this stage. No browser CORS configuration is needed because browsers call the same-origin Next BFF.

Local Docker Engine was unavailable during development. The Linux CI job builds the image and tests a running container on **PORT=8080**, including the packaged FIN-11 calculation; inspect that job's result for the committed revision.

## Vercel frontend

1. Import this repository when deployment is separately authorized. Select **Next.js**, Root Directory **apps/web**, Node **24.x**.
2. Enable inclusion of source files outside the root directory so npm workspaces and the root lockfile are available.
3. `apps/web/vercel.json` sets install command `cd ../.. && npm ci`, build command `cd ../.. && npm run build`, and output directory `.next` relative to the frontend root.
4. Set server environment variable `BACKEND_URL=https://YOUR-BACKEND` for the intended Preview/Production environment. Do not prefix it with `NEXT_PUBLIC_`. Use a reachable HTTPS origin without `/api/demo` appended; loopback points to Vercel itself, not your computer.
5. After deployment, exercise Try sample → FIN-16 → The contractor → Another recipient → Reset. Check $7,000 → $5,000 → $7,000 and the restored provisional status.

The BFF needs a running Node/serverless runtime; this is not a static export. A missing backend setting returns 503, an unavailable backend 502. Those errors are surfaced with retry in the UI. Vercel deployment itself has not been verified against an account in this stage.

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
