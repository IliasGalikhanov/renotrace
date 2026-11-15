"use client";

import { useEffect, useRef, useState } from "react";
import PdfDownload from "./pdf-download";
import QuestionPresence from "./question-presence";
import type { Command, Result, State } from "./review";
import {
  type CheckedLine,
  type Composition,
  lineLabels,
  money,
} from "./invoice-types";

type Package = {
  file_ids: string[];
  replies: { reply_id: string; version: number }[];
  old_request_id: string | null;
  new_request_id: string | null;
  relationship: "same" | "corrected" | "separate" | "unknown";
  matches: { old_id: string | null; new_id: string | null }[];
  question_links: { question_id: string; new_line_id: string; note: string }[];
};
type Draft = {
  id: string;
  base_snapshot_id: string;
  version: number;
  package: Package;
  status: "draft" | "completed";
  comparison_id: string | null;
};
export type RecheckView = {
  drafts: Draft[];
  comparisons: {
    id: string;
    base_snapshot_id: string;
    new_snapshot_id: string;
    created_at: string;
    current: boolean;
    preliminary: boolean;
  }[];
};
type Base = {
  payload: {
    result: Result;
    project: State["project"];
    discussion: State["casework"];
  };
};
type Comparison = {
  id: string;
  base_snapshot_id: string;
  new_snapshot_id: string;
  created_at: string;
  algorithm: string;
  payload: {
    package: Package;
    reply_versions: {
      source_id: string;
      text: string;
      version: number;
      origin: string;
    }[];
    result: {
      metrics: Record<
        string,
        { before: number | null; after: number | null; delta: number | null }
      >;
      old_composition: Composition | null;
      new_composition: Composition | null;
      changes: {
        old: CheckedLine | null;
        new: CheckedLine | null;
        change: string;
        fields: string[];
        signed_delta_cents: number | null;
        checked: boolean;
      }[];
      unmatched_old: CheckedLine[];
      unmatched_new: CheckedLine[];
      suggestions: { old_id: string; new_ids: string[]; basis: string }[];
      question_findings: {
        question_id: string;
        original_question: string;
        finding: string;
        still_unknown: string;
        requires_recheck: boolean;
        linked_changes?: { change: string; fields: string[] }[];
        affected_metric_changes?: Record<
          string,
          { before: number | null; after: number | null; delta: number | null }
        >;
        current_evidence_state: string;
        evidence: CheckedLine[];
      }[];
      new_questions: State["casework"]["cards"];
      conditions_before: Result["conditions"];
      conditions_after: Result["conditions"];
      issues: string[];
      preliminary: boolean;
      explanation_only: boolean;
      notice: string;
    };
  };
};
const toggle = (values: string[], id: string) =>
  values.includes(id) ? values.filter((v) => v !== id) : [...values, id];

export default function Rechecks({
  state,
  command,
  disabled,
  mutate,
  read,
  openSource,
}: {
  state: State;
  command: Command;
  disabled: boolean;
  mutate: (path: string, body: unknown) => Promise<boolean>;
  read: <T>(path: string) => Promise<T>;
  openSource: (id: string, page?: number) => Promise<void>;
}) {
  const [baseId, setBaseId] = useState("");
  const [selected, setSelected] = useState("");
  const [pack, setPack] = useState<Package | null>(null);
  const [base, setBase] = useState<Base | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonTarget, setComparisonTarget] = useState<string | null>(null);
  const [comparisonCards, setComparisonCards] = useState<
    State["casework"]["cards"]
  >([]);
  const [financialEvidence, setFinancialEvidence] = useState<Base | null>(null);
  const [error, setError] = useState("");
  const [retryEpoch, setRetryEpoch] = useState(0);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const retry = useRef<{ key: string; id: string } | null>(null);
  const url = `projects/${state.project.id}`;
  const active =
    state.rechecks.drafts.find((d) => d.id === selected) ??
    state.rechecks.drafts.filter((d) => d.status === "draft").at(-1);
  useEffect(() => {
    setPack(active?.package ?? null);
  }, [active?.id, active?.version]);
  useEffect(() => {
    const id = ++generation.current;
    setBase(null);
    setError("");
    if (!active) return;
    setLoading(true);
    void read<Base>(`${url}/snapshots/${active.base_snapshot_id}`)
      .then((b) => {
        if (id === generation.current) setBase(b);
      })
      .catch((e) => {
        if (id === generation.current) setError((e as Error).message);
      })
      .finally(() => {
        if (id === generation.current) setLoading(false);
      });
    return () => {
      ++generation.current;
    };
  }, [active?.base_snapshot_id, url, read, retryEpoch]);
  async function send(path: string, body: object) {
    const key = JSON.stringify([path, body]);
    if (retry.current?.key !== key)
      retry.current = { key, id: crypto.randomUUID() };
    const ok = await mutate(path, { ...body, mutation_id: retry.current.id });
    if (ok) retry.current = null;
    return ok;
  }
  async function open(id: string) {
    const gen = ++generation.current;
    setLoading(true);
    setError("");
    setComparison(null);
    setComparisonTarget(id);
    setComparisonCards([]);
    setFinancialEvidence(null);
    try {
      const saved = await read<Comparison>(`${url}/comparisons/${id}`);
      const snapshot = await read<Base>(
        `${url}/snapshots/${saved.new_snapshot_id}`,
      );
      if (gen === generation.current) {
        setComparisonCards(snapshot.payload.discussion.cards);
        setComparison(saved);
      }
    } catch (e) {
      if (gen === generation.current) setError((e as Error).message);
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }
  async function openFinancialEvidence(id: string) {
    const gen = ++generation.current;
    setLoading(true);
    setError("");
    setFinancialEvidence(null);
    try {
      const saved = await read<Base>(`${url}/snapshots/${id}`);
      if (gen === generation.current) setFinancialEvidence(saved);
    } catch (e) {
      if (gen === generation.current) setError((e as Error).message);
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }
  const oldInvoice = base?.payload.result.invoice_compositions?.find(
    (i) => i.request_id === pack?.old_request_id,
  );
  const newInvoice = command.invoices.find(
    (i) => i.request_id === pack?.new_request_id,
  );
  const oldRows =
    oldInvoice?.lines.filter((row) => row.value.review !== "excluded") ?? [];
  const newRows =
    newInvoice?.lines.filter((row) => row.review !== "excluded") ?? [];
  const packageDirty =
    !!pack && JSON.stringify(pack) !== JSON.stringify(active?.package);
  const result = comparison?.payload.result;
  const summary = state.rechecks.comparisons.find(
    (c) => c.id === comparison?.id,
  );
  const patch = (value: Partial<Package>) =>
    pack && setPack({ ...pack, ...value });
  const candidates = state.project.documents.flatMap((d) => d.candidates);
  const oldQuestions = base?.payload.discussion.cards ?? [];
  return (
    <section
      className="guest-panel rechecks"
      aria-label="Recheck with new information"
    >
      <h2>5. Recheck with new information</h2>
      <p>
        Choose a saved calculation, collect explanations and documents, check
        the facts above, then explicitly run a recheck. Uploading alone does not
        complete a check. An explanation without a corrected invoice is
        supported.
      </p>
      <label>
        Previous calculation
        <select
          value={baseId}
          disabled={disabled}
          onChange={(e) => setBaseId(e.target.value)}
        >
          <option value="">Choose saved calculation</option>
          {state.casework.snapshots.map((s) => (
            <option value={s.id} key={s.id}>
              Revision {s.financial_revision} · {money(s.remaining_cents)} ·{" "}
              {new Date(s.created_at).toLocaleString("en-US")}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={disabled || !baseId}
        onClick={() =>
          void send(`${url}/rechecks`, { base_snapshot_id: baseId }).then(
            (ok) => {
              if (ok) {
                setSelected("");
                setComparison(null);
              }
            },
          )
        }
      >
        Recheck with new information
      </button>
      {state.rechecks.drafts.length > 0 && (
        <label>
          Saved recheck package
          <select
            value={active?.id ?? ""}
            onChange={(e) => setSelected(e.target.value)}
            disabled={disabled}
          >
            {state.rechecks.drafts.map((d) => (
              <option value={d.id} key={d.id}>
                {d.status} · {d.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {loading && <p role="status">Loading saved evidence…</p>}
      {error && (
        <p role="alert">
          {error}
          <button
            onClick={() =>
              comparisonTarget
                ? void open(comparisonTarget)
                : setRetryEpoch((value) => value + 1)
            }
          >
            Retry saved evidence
          </button>
        </p>
      )}
      {active && pack && (
        <fieldset
          disabled={disabled || active.status === "completed" || loading}
          className="recheck-package"
        >
          <legend>
            Recheck package · version {active.version} · {active.status}
          </legend>
          <p>
            Package changes are saved separately from financial choices.
            Original files remain in the case. Replies are pinned to the version
            selected here.
          </p>
          <div className="guest-fields">
            <label>
              Invoice to compare
              <select
                value={pack.new_request_id ?? ""}
                onChange={(e) => {
                  const candidate = candidates.find(
                    (c) => c.id === e.target.value,
                  );
                  patch({
                    new_request_id: e.target.value || null,
                    relationship:
                      e.target.value === pack.old_request_id
                        ? "same"
                        : "unknown",
                    matches: [],
                    question_links: [],
                    file_ids: candidate
                      ? [...new Set([...pack.file_ids, candidate.file_id])]
                      : pack.file_ids,
                  });
                }}
              >
                <option value="">Choose request</option>
                {command.records
                  .filter((r) => r.kind === "payment_request")
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {
                        state.project.documents.find((d) =>
                          d.candidates.some((c) => c.id === r.id),
                        )?.name
                      }{" "}
                      · {candidates.find((c) => c.id === r.id)?.snippet}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Invoice relationship
              <select
                value={pack.relationship}
                onChange={(e) =>
                  patch({
                    relationship: e.target.value as Package["relationship"],
                  })
                }
              >
                <option value="unknown">
                  Unknown — requires clarification
                </option>
                <option value="same">
                  Same invoice — explanation / recheck only
                </option>
                <option value="corrected">
                  I confirm: replaces the original invoice for this contractor
                </option>
                <option value="separate">
                  Separate new invoice, not a correction
                </option>
              </select>
            </label>
          </div>
          <h3>Documents in this package</h3>
          {state.project.documents.map((d) => (
            <label className="guest-consent" key={d.id}>
              <input
                type="checkbox"
                checked={pack.file_ids.includes(d.id)}
                onChange={() =>
                  patch({ file_ids: toggle(pack.file_ids, d.id) })
                }
              />
              {d.name} · {d.status}
            </label>
          ))}
          <h3>Reply versions</h3>
          {!state.casework.replies.length && (
            <p>
              No reply yet. You can save an explanation in Questions & review
              history without uploading a new invoice.
            </p>
          )}
          {state.casework.replies.map((reply) => {
            const picked = pack.replies.find((r) => r.reply_id === reply.id);
            return (
              <div key={reply.id}>
                <label className="guest-consent">
                  <input
                    type="checkbox"
                    checked={!!picked}
                    onChange={() =>
                      patch({
                        replies: picked
                          ? pack.replies.filter((r) => r.reply_id !== reply.id)
                          : [
                              ...pack.replies,
                              {
                                reply_id: reply.id,
                                version: reply.versions.length,
                              },
                            ],
                      })
                    }
                  />
                  Include reply · {reply.versions.at(-1)?.text}
                </label>
                {picked && (
                  <label>
                    Reply version
                    <select
                      value={picked.version}
                      onChange={(e) =>
                        patch({
                          replies: pack.replies.map((r) =>
                            r.reply_id === reply.id
                              ? { ...r, version: Number(e.target.value) }
                              : r,
                          ),
                        })
                      }
                    >
                      {reply.versions.map((v) => (
                        <option key={v.version} value={v.version}>
                          Version {v.version} · {v.text}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            );
          })}
          <h3>Position correspondences</h3>
          <p>
            Check the current invoice composition above first. A similar amount
            never establishes a match. Unmatched positions keep the comparison
            preliminary.
          </p>
          {!oldInvoice && (
            <p className="guest-preliminary">
              The selected historical calculation has no checked composition.
              Its missing details will not be reconstructed.
            </p>
          )}
          {oldRows.map((row) => {
            const match = pack.matches.find((m) => m.old_id === row.value.id);
            return (
              <label key={row.value.id}>
                Match previous: {row.value.description}
                <select
                  value={match ? (match.new_id ?? "removed") : ""}
                  onChange={(e) =>
                    patch({
                      matches: [
                        ...pack.matches.filter(
                          (m) => m.old_id !== row.value.id,
                        ),
                        ...(e.target.value
                          ? [
                              {
                                old_id: row.value.id,
                                new_id:
                                  e.target.value === "removed"
                                    ? null
                                    : e.target.value,
                              },
                            ]
                          : []),
                      ],
                    })
                  }
                >
                  <option value="">Unmatched / not confirmed</option>
                  <option value="removed">
                    I confirm this position was removed
                  </option>
                  {newRows.map((r) => (
                    <option key={r.id} value={r.id}>
                      {lineLabels[r.kind]} · {r.description}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
          {newRows
            .filter(
              (r) => !pack.matches.some((m) => m.old_id && m.new_id === r.id),
            )
            .map((row) => (
              <label className="guest-consent" key={row.id}>
                <input
                  type="checkbox"
                  checked={pack.matches.some(
                    (m) => !m.old_id && m.new_id === row.id,
                  )}
                  onChange={() =>
                    patch({
                      matches: pack.matches.some(
                        (m) => !m.old_id && m.new_id === row.id,
                      )
                        ? pack.matches.filter(
                            (m) => m.old_id || m.new_id !== row.id,
                          )
                        : [...pack.matches, { old_id: null, new_id: row.id }],
                    })
                  }
                />
                I confirm added position: {lineLabels[row.kind]} ·{" "}
                {row.description}
              </label>
            ))}
          <h3>Evidence for original questions</h3>
          {oldQuestions.map((card) => (
            <label key={card.id}>
              {card.observation.message}
              <select
                aria-label={`Evidence for question ${card.observation.code}`}
                value={
                  pack.question_links.find((l) => l.question_id === card.id)
                    ?.new_line_id ?? ""
                }
                onChange={(e) =>
                  patch({
                    question_links: [
                      ...pack.question_links.filter(
                        (l) => l.question_id !== card.id,
                      ),
                      ...(e.target.value
                        ? [
                            {
                              question_id: card.id,
                              new_line_id: e.target.value,
                              note: "Owner explicitly linked this invoice position to the original question.",
                            },
                          ]
                        : []),
                    ],
                  })
                }
              >
                <option value="">No position establishes an answer yet</option>
                {newRows.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.description}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <button
            onClick={() =>
              void send(`${url}/rechecks/${active.id}/package`, {
                expected_version: active.version,
                package: pack,
              })
            }
          >
            Save recheck package
          </button>
          <p>
            Step 1 saves your document links and reply versions as a draft. It
            does not calculate or produce a completed comparison. Step 2 below
            runs the checked calculation and saves a comparison you can
            download.
          </p>
          {packageDirty && (
            <p role="status">
              Package has unsaved changes. Save it before running the recheck.
            </p>
          )}
          <p>
            Run uses your current checked facts above, selects this invoice as
            the current request, and records the explicit replacement only if
            confirmed here. Invoice rows do not create payments or change
            contract price.
          </p>
          <button
            className="guest-primary"
            disabled={packageDirty || !pack.new_request_id}
            onClick={() => {
              const versions = [...command.request_versions];
              if (
                pack.relationship === "corrected" &&
                pack.old_request_id &&
                pack.new_request_id &&
                !versions.some(
                  (v) =>
                    v.old_request_id === pack.old_request_id &&
                    v.new_request_id === pack.new_request_id,
                )
              )
                versions.push({
                  old_request_id: pack.old_request_id,
                  new_request_id: pack.new_request_id,
                });
              void send(`${url}/rechecks/${active.id}/run`, {
                expected_version: active.version,
                review: {
                  ...command,
                  request_id: pack.new_request_id,
                  request_versions: versions,
                },
              });
            }}
          >
            Run recheck and save comparison
          </button>
        </fieldset>
      )}
      <h3>Saved comparisons</h3>
      {!state.rechecks.comparisons.length && <p>No completed recheck yet.</p>}
      {state.rechecks.comparisons.map((c) => (
        <div key={c.id}>
          <button
            disabled={disabled || loading}
            onClick={() => void open(c.id)}
          >
            View comparison · {new Date(c.created_at).toLocaleString("en-US")}
          </button>
          <p>
            {c.current
              ? "Current saved evidence"
              : "Needs recheck — source or discussion changed"}{" "}
            ·{" "}
            {c.preliminary
              ? "Preliminary"
              : "No comparison gaps detected; not a payment-safety guarantee"}
          </p>
        </div>
      ))}
      {comparison && result && (
        <section
          className="historical-snapshot"
          aria-label="Saved invoice comparison"
        >
          <h3>Saved invoice comparison — read only</h3>
          <PdfDownload
            key={comparison.id}
            projectId={state.project.id}
            kind="comparison"
            resultId={comparison.id}
            savedAt={comparison.created_at}
            version={comparison.algorithm}
            disabled={disabled}
          />
          <details>
            <summary>Calculation references</summary>
            <p>
              {comparison.algorithm} · {comparison.base_snapshot_id} →{" "}
              {comparison.new_snapshot_id}
            </p>
          </details>
          <p>
            {summary?.current
              ? "Saved for the current evidence"
              : "Needs recheck: this historical result is unchanged; current evidence differs."}
          </p>
          <button onClick={() => setComparison(null)}>Close comparison</button>
          <button
            disabled={loading}
            onClick={() =>
              void openFinancialEvidence(comparison.base_snapshot_id)
            }
          >
            View previous financial basis
          </button>
          <button
            disabled={loading}
            onClick={() =>
              void openFinancialEvidence(comparison.new_snapshot_id)
            }
          >
            View new financial basis
          </button>
          {financialEvidence && (
            <details open>
              <summary>Saved financial basis and original sources</summary>
              <p>
                Read only. C{" "}
                {money(
                  financialEvidence.payload.result.calculation
                    .commitment_total_cents,
                )}
                ; P{" "}
                {money(
                  financialEvidence.payload.result.calculation.net_paid_cents,
                )}
                ; R{" "}
                {money(
                  financialEvidence.payload.result.calculation
                    .remaining_commitment_cents,
                )}
                .
              </p>
              {financialEvidence.payload.result.sources.map((source) => (
                <details key={source.source_id}>
                  <summary>
                    {source.title} · {source.origin}
                  </summary>
                  <pre>{source.text}</pre>
                  {source.file_id && (
                    <button
                      onClick={() =>
                        void openSource(source.file_id!, source.page ?? 1)
                      }
                    >
                      View financial source page
                    </button>
                  )}
                </details>
              ))}
              <details>
                <summary>Stored normalization and ledger evidence</summary>
                <pre>
                  {JSON.stringify(financialEvidence.payload.result, null, 2)}
                </pre>
              </details>
            </details>
          )}
          {result.explanation_only && (
            <p>
              Explanation-only recheck: requested amount and C/P/R are
              unchanged.
            </p>
          )}
          <p className="guest-preliminary">
            {result.preliminary
              ? "Preliminary — unresolved evidence remains."
              : "Document comparison completed; this does not guarantee payment is due."}
          </p>
          <div className="guest-metrics">
            {[
              "requested_now_cents",
              "commitment_total_cents",
              "net_paid_cents",
              "remaining_commitment_cents",
            ]
              .map((key) => [key, result.metrics[key]] as const)
              .map(([key, value]) => (
                <article key={key}>
                  <h4>
                    {key === "requested_now_cents"
                      ? "Requested amount"
                      : key === "commitment_total_cents"
                        ? "Recorded commitments C"
                        : key === "net_paid_cents"
                          ? "Net payments P"
                          : "Remaining commitment R"}
                  </h4>
                  <strong data-testid={`comparison-${key}`}>
                    {money(value.before)} → {money(value.after)}
                  </strong>
                  <p>Change: {money(value.delta)}</p>
                </article>
              ))}
          </div>
          <p>{result.notice}</p>
          {[result.old_composition, result.new_composition].map(
            (invoice, index) =>
              invoice && (
                <p key={index}>
                  {index ? "New" : "Previous"} invoice: checked composition{" "}
                  {money(invoice.accounted_cents)}; unexplained difference{" "}
                  {money(invoice.unexplained_cents)}.{" "}
                  {invoice.complete
                    ? "Composition reconciles"
                    : "Composition incomplete"}
                </p>
              ),
          )}
          <h4>What changed</h4>
          {result.changes.map((c, index) => (
            <article className="comparison-change" key={index}>
              <strong>
                {c.change} · {c.fields.join(", ")}
              </strong>
              {([c.old, c.new] as const).map(
                (row, i) =>
                  row && (
                    <div key={i}>
                      <p>
                        {i ? "New" : "Previous"}: {lineLabels[row.value.kind]} ·{" "}
                        {row.value.description} · {money(row.amount_cents)} ·{" "}
                        {row.value.review}
                      </p>
                      <button
                        onClick={() =>
                          void openSource(
                            (i
                              ? result.new_composition
                              : result.old_composition)!.file_id,
                            row.value.page,
                          )
                        }
                      >
                        View {i ? "new" : "previous"} position source
                      </button>
                      <details>
                        <summary>Original text and reviewed value</summary>
                        <p>
                          {row.original_text ??
                            "Manual entry linked to source page"}
                        </p>
                        <pre>{JSON.stringify(row.value, null, 2)}</pre>
                      </details>
                    </div>
                  ),
              )}
            </article>
          ))}
          <h4>Unmatched positions</h4>
          {[...result.unmatched_old, ...result.unmatched_new].map((r, i) => (
            <p key={i}>
              {r.value.description} · {money(r.amount_cents)} · not confirmed as
              matched/added/removed
            </p>
          ))}
          {result.suggestions.map((s) => (
            <p key={s.old_id}>
              Matching suggestion: {s.old_id} → {s.new_ids.join(", ")}.{" "}
              {s.basis}
            </p>
          ))}
          <h4>Original questions</h4>
          <p>
            These are questions from the previous saved calculation, not current
            document-status messages. Reassessment and owner decisions remain
            separate from their presence in a calculation.
          </p>
          {result.question_findings.map((q) => (
            <article key={q.question_id}>
              {comparisonCards.find((c) => c.id === q.question_id) ? (
                <QuestionPresence
                  card={comparisonCards.find((c) => c.id === q.question_id)!}
                />
              ) : (
                <p>Presence not recorded in the selected snapshot.</p>
              )}
              <strong>{q.original_question}</strong>
              <p>{q.finding}</p>
              {q.linked_changes?.map((change, index) => (
                <p key={index}>
                  Detected: {change.change} ·{" "}
                  {change.fields.join(", ") || "position composition"}
                </p>
              ))}
              {Object.entries(q.affected_metric_changes ?? {}).map(
                ([key, value]) => (
                  <p key={key}>
                    {key.replaceAll("_", " ").replace(" cents", "")}:{" "}
                    {money(value.before)} → {money(value.after)}; change{" "}
                    {money(value.delta)}.
                  </p>
                ),
              )}
              <p>
                {q.still_unknown}{" "}
                {q.requires_recheck ? "Previous conclusion needs recheck." : ""}
              </p>
              {q.evidence.map((e) => (
                <p key={e.value.id}>
                  {e.value.description} · {money(e.amount_cents)} ·{" "}
                  {e.source_ref} ·{" "}
                  {e.cash_event_id ?? "No verified payment link"}
                </p>
              ))}
            </article>
          ))}
          <h4>Questions first recorded since the previous snapshot</h4>
          <p>
            First recorded does not mean currently active. These labels come
            from the saved comparison, not today's case.
          </p>
          {result.new_questions.map((q) => (
            <article key={q.id}>
              <QuestionPresence card={q} />
              <p>Recorded question: {q.observation.message}</p>
            </article>
          ))}
          <h4>Payment conditions</h4>
          <p>
            Previous:{" "}
            {result.conditions_before.map((c) => c.text).join("; ") ||
              "Unknown"}
          </p>
          <p>
            New:{" "}
            {result.conditions_after.map((c) => c.text).join("; ") || "Unknown"}
          </p>
          <h4>Still unknown / requires checking</h4>
          <ul>
            {result.issues.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
          <h4>Replies saved with this comparison</h4>
          {comparison.payload.reply_versions.map((v) => (
            <blockquote key={v.source_id}>
              {v.text}
              <small>
                Version {v.version} · {v.origin}
              </small>
            </blockquote>
          ))}
          <details>
            <summary>
              Frozen package, sources and correspondence decisions
            </summary>
            <pre>{JSON.stringify(comparison.payload, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
