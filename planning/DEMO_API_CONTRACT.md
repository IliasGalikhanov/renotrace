# Public synthetic demo — stage 4

This is an unsaved demonstration calculation, not an implementation of persistent cases, transactions or snapshots. No account, cookie, database, upload, external AI or session is involved. The server owns three examples packaged in `app/demo/samples.json`: FIN-01, FIN-16 and FIN-11. The file includes readable fictional source excerpts, not links to missing PDFs.

## Implemented routes

| Method | FastAPI route | Result |
|---|---|---|
| GET | `/healthz` | Service health |
| GET | `/api/demo/scenarios` | IDs, titles and descriptions of the three allowed examples |
| GET | `/api/demo/scenarios/{scenario_id}` | Fresh baseline history, inline sources, conditions, actual normalization and ledger result |
| POST | `/api/demo/scenarios/{scenario_id}/calculate` | Fresh baseline with allowed actions applied, then normalization → ledger |

The actual FastAPI OpenAPI is served at `/openapi.json` and exported to [demo.openapi.json](../contracts/demo.openapi.json). A test compares the exported schema with the running app. The older `contracts/openapi.json` remains the **design specification** for private APIs, which are not registered in the app.

The Next.js BFF exposes the same `/api/demo/...` paths. It forwards only these GET/POST routes to the server-only `BACKEND_URL`, does not forward cookies/credentials, disables caching and follows no redirects. The backend origin is never accepted from the browser. Request bodies are capped at 8 KiB at the BFF; backend action lists are limited to 12 typed items. A backend timeout (8 seconds) or failure returns a generic 502, missing configuration 503, malformed JSON 400, oversized body 413, forbidden route/scenario 404 and invalid/forbidden action 422. Domain validation details are not exposed by the BFF.

## Recalculation input

```json
{
  "actions": [
    {"kind": "assign_recipient", "record_id": "unknown", "answer": "contractor"}
  ]
}
```

Only FIN-16 accepts this action, only for record `unknown`. Answers are `contractor`, `other`, `unknown`. All extra fields, unsupported action kinds/answers and foreign/unknown record IDs are rejected. The client cannot supply amounts, results, evidence, contractor IDs, revisions or a HistoryInput.

Every request reparses the bundled example into an independent typed history. Send the complete current list of selections each time; for repeated actions in the same `(kind, record_id)` scope, the final item wins. This is an explicit UI command list, **not** a change to the domain rule that conflicting historical confirmations require a question. Reset uses a fresh GET or POST with an empty actions list. Actions never alter the fixture or another request.

For the permitted FIN-16 edit, the adapter creates one current `assign_contractor` decision and an inline `user_statement` source. This isolated draft has baseline case revision + 1 and a matching decision basis revision. Its actor is `demo-visitor`, and its UTC timestamp is the request time; neither identifies an authenticated person. No old decision or relationship is rebased. Existing domain freshness checks remain unchanged. Repeated equal requests have equal financial results and ledger fingerprints; audit timestamps can differ. The draft revision is not a persistent version counter or a concurrency token.

## Response and source tracing

`DemoResult` contains:

- `synthetic: true`, `persistence: "none"`, scenario metadata and canonical current actions;
- `history`: the structured input used for this request;
- `source_contents`: source ID, title and readable excerpt; source origins come from the history registry;
- `record_titles`, `allowed_actions`, and `conditions` with nullable due date/text, satisfaction and evidence refs;
- `normalization`: the original included/excluded dispositions, questions, incomplete and incomplete_metrics, decisions and source registry;
- `calculation`: the complete result of the real ledger;
- `traces`: backend result amounts, explanatory formulas and participating record/source IDs, including cumulative predecessors and allocation dependencies.

No alternative arithmetic is implemented in TypeScript. It formats integer cents as USD and displays the returned fields. The three samples do not supply payment dates/conditions; the interface shows **Unknown**, and never asserts that work is complete. Absence of questions means only that the supplied sample has no unresolved facts.

FIN-01 keeps request $5,500 separate from remainder $4,700; the $800 material credit reduces commitments, not cash. FIN-16 starts at provisional $7,000, becomes $5,000 for contractor, $7,000 without recipient uncertainty for other, and provisional $7,000 for unknown. FIN-11 explains $8,500 new gross billing and $10,500 positive invoice balances.

## Browser state and errors

Selections live only in React memory. Switching/resetting/reloading starts over. Each calculation clears the prior numeric result immediately, sets a loading message, and keeps no stale figures labelled as a new result. AbortController cancels superseded requests; an independent monotonically increasing request number also rejects stale responses if transport cancellation is ineffective. Errors show a retry button that repeats the pending selection. Scenario selection and recipient controls remain usable during requests.

The persistent header badge says **Synthetic demo**. Native buttons, radios, details/summary, visible focus and live loading/error announcements support keyboard navigation. The view adapts to 360, 768 and 1440 px. Tests include actual API/BFF/browser flows, explicit delayed replies with transport abort disabled, concurrent visitors, forbidden inputs and source disclosures.
