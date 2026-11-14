# Stage 7: question history and calculation snapshots

Stage 7 introduced contract `guest-review/2`, API version `0.7.0`. Stage 8 adds [explicit rechecks and invoice comparisons](RECHECK_CONTRACT.md) with `guest-review/3` / API `0.8.0`; old snapshots retain their original contract. Extends the [guest contract](GUEST_REVIEW_CONTRACT.md). No accounts, payments, email delivery, longer retention, financial agreement actions or PDF export. Existing normalization and ledger remain the only financial calculation path.

## Actual owner-scoped routes

All routes below start `/api/guest/projects/{project_id}`. Bearer ownership and unexpired project are checked before reading entities, replaying an operation or mutating data. The BFF retains the secret in its HttpOnly cookie and only forwards its explicit route allowlist. Same-origin checks also apply to these JSON mutations.

| Method / suffix | Contract |
| --- | --- |
| GET project | Existing `project` and `result`, plus `casework`: cards, replies, snapshot summaries, latest snapshot ID, legacy audit count. Reconciles question observations after the first saved review. |
| POST `/review` | Existing typed command plus optional UUID `mutation_id`. Successful save atomically writes audit, financial revision, card observations and full immutable snapshot. UI always supplies the UUID. Legacy clients without it retain stale-revision rejection. |
| GET `/snapshots` | Newest-first summaries: ID, timestamp, financial revision, calculation contract version, recorded remainder, question count. |
| GET `/snapshots/{snapshot_id}` | `summary` plus frozen JSON `payload`: project/input review decisions, immutable file composition and extraction pages, source registry with versions, normalization, ledger, questions, incomplete metrics, payment conditions, discussion state at save time. Never calls `result_for`, normalization or ledger. |
| POST `/replies` | `mutation_id`, one or more `question_ids`, text (1–4000 characters), optional existing `file_ids`. Whitespace-only text rejected. One reply can belong to several cards. |
| POST `/replies/{reply_id}/edit` | `mutation_id`, `expected_version`, text, optional `file_ids`. Appends an immutable reply version; old text, attachments, author and timestamp remain. No in-place replacement of old text. |
| POST `/attachments` | `mutation_id`, nonempty `question_ids` and `file_ids`. Both sets must belong to this project. Linking is not financial approval. Existing links are not duplicated. |
| POST `/questions/{question_id}/state` | `mutation_id`, `expected_version`, explanatory `note`, optional `evidence_state` and/or `owner_decision`. At least one state action required. A positive evidence assessment additionally requires current `snapshot_id` and checked `source_refs`. |

Unknown/foreign/expired entities: 404. Conflicting retry ID, stale financial revision or card/reply version: 409. Invalid assessment or financial input: 422. History capacity: 429. OpenAPI in `contracts/demo.openapi.json` describes these implemented routes; the original account API design is not implemented.

## Immutable results, additive migration

`snapshots`, `question_cards`, `replies`, `discussion_operations` are new PostgreSQL tables referencing the existing project with `ON DELETE CASCADE`. Migration uses the existing advisory lock and `CREATE TABLE IF NOT EXISTS`; it does not rewrite or delete existing projects or audit rows. A database trigger rejects all snapshot updates. Deletes remain allowed for project deletion/expiry. There is no snapshot restore operation.

Only newly saved calculations receive full snapshots. Old audit commands are counted separately and never reconstructed using today's calculator or labelled historical results. Frozen JSON is returned without parsing through today's financial input/output models, so a future domain version cannot silently recalculate it. Source bytes stay immutable in the existing private bucket; frozen page text, checksums, composition and version IDs remain in each snapshot until project expiry/deletion.

## Stable identity and invalidation

A card ID hashes project, question code and stable entity anchors: original candidate ID, immutable file ID, account + stable bank transaction context, or the case for case-wide questions. It does not hash display wording or versioned financial record IDs. The current observation separately records financial revision, record versions, source pages, known amounts, affected metrics and their current totals. The totals are not estimates of the monetary impact of an answer.

The dependency fingerprint covers related candidate values, reviewed choices, source content/checksums, document processing state, cutoff, selected agreement, applicable selected request, relationships and review freshness. Resaving unchanged facts or reordering inputs does not invalidate the card. Changed financial basis or changed presence in the calculation sets `needs_recheck` and appends a system event. The old owner decision and every previous assessment remain in history. Disappearance does not imply resolution. Case-wide questions conservatively depend on the whole source set.

## Two independent states

Evidence: `awaiting_explanation`, `answer_insufficient`, `explained_verified`, `contradiction_remains`, `needs_recheck`.

Owner: `continue_clarifying`, `accept_explanation`, `stop_unresolved`.

Reply text, edits, file links, copy actions and owner decisions do not write the project, financial revision, saved review or ledger. They do not change domain `incomplete` or its metrics. Replies do not automatically change the evidence state either. An owner may explicitly mark an answer insufficient or a contradiction unresolved. The UI retains these cards in an unresolved history count even if an owner accepts the explanation or stops asking. Historical unresolved discussion is shown separately from current domain uncertainty; it is not invented as a new ledger event.

`explained_verified` means an explicit assessment by the guest owner, not independent authentication. It requires a saved review on the current financial revision, the latest snapshot, no active instance of this question, no unresolved domain metric affected by it, and specific checked document page citations covering the related financial records or the checked payment condition. Unknown, stale, foreign, rejected or reply-only evidence cannot satisfy this gate. Assessment events record actor, time, source refs, record versions, snapshot, revision and basis fingerprint. New financial evidence invalidates that conclusion without erasing its history.

## Reply provenance, attachments and idempotency

Each reply version has a distinct `reply:{id}:v{n}` source ID, `owner_reported_contractor` origin, adding guest actor and server timestamp. It is discussion evidence, never an independently received contractor message and never an input to the ledger. Original file attachments use the existing private upload, validation, OCR and review pipeline. Upload increments the financial revision and invalidates old financial decisions as before. Merely linking an already uploaded document does not do so.

Project row locks serialize discussion and financial saves. A successful mutation records its UUID, canonical payload fingerprint and resource ID in the same transaction. Repeating it returns the current project state without another reply/version/event/snapshot. Reusing the UUID for different content or another action returns 409. The browser retains the same UUID when retrying the same failed submission; a browser test deliberately drops the response after the server commits. No automatic retry applies a different financial action.

Capacity per temporary project: 20 saved calculations, 300 cards, 200 idempotent mutations, 20 versions per reply; up to 20 question/file IDs per discussion command. Existing file/page/project quotas are unchanged. Exceeding a limit rolls back the whole operation. These finite limits protect the free database tier; the UI surfaces the server error.

## Retention and limitations

All entities inherit the original project expiry, 24 hours from creation. Discussion never renews it. Server expiry checks deny access immediately; cleanup cascades all new tables and uses the existing retryable object deletion outbox. No persistent files or new storage services are added to Render. Browser-local copies already downloaded cannot be recalled.

No semantic analysis of reply text is claimed. Supporting sources are checked explicitly by the user; OCR and manual correction are not independent document authentication. Stage 8 provides explicit corrected-invoice comparison; it does not automatically confirm document matches, renegotiate contracts or guarantee payment safety. Missing questions alone do not establish payment conditions.
