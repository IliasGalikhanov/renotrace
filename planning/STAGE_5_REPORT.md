# Stage 5 — public deployment

Deployment is in progress. No public URL is claimed by this preparation commit.

Implemented: bounded cold-start retries, explicit waiting with hidden previous figures, cancellation of superseded retry timers, and a separate HTTPS-only remote Playwright configuration without local servers. The real BFF startup test delays backend readiness by 55 seconds and then calculates through the actual Python normalization/ledger chain. Financial modules and demo action validation are unchanged.

Local validation: 347 Python tests passed, coverage 99.86%; production build, TypeScript, Prettier, Ruff, mypy, specification integrity and real HTTP smoke passed. Playwright: 34 passed, two intentionally skipped duplicate startup runs (the 55-second real startup runs once, while UI retry tests run at all three widths). Hosted deployment evidence will be recorded after completion.

Cost selection: Vercel Hobby and Render Free, no additional recurring cost, no card attached to Render. Account allowances and release/rollback instructions are in DEPLOYMENT.md. Automatic deployment is disabled so publication follows successful CI for the selected SHA. No persistence, OCR, authentication, private cases or external AI was introduced.
