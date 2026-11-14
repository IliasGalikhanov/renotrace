"use client";

import { useRef, useState } from "react";
import PdfDownload from "./pdf-download";
import type { Result, State } from "./review";

type Evidence =
  | "awaiting_explanation"
  | "answer_insufficient"
  | "explained_verified"
  | "contradiction_remains"
  | "needs_recheck";
type Decision =
  "continue_clarifying" | "accept_explanation" | "stop_unresolved";
type Card = {
  id: string;
  version: number;
  evidence_state: Evidence;
  owner_decision: Decision;
  reply_ids: string[];
  file_ids: string[];
  observation: {
    code: string;
    message: string;
    contractor_question: string;
    affects: string[];
    metric_values: Record<string, number | null>;
    amounts_cents: Record<string, number | null>;
    record_ids: string[];
    source_refs: string[];
    file_ids: string[];
    financial_revision: number;
    active: boolean;
  };
  events: {
    id: string;
    at: string;
    actor: string;
    kind: string;
    detail: string;
    evidence_state: Evidence;
    owner_decision: Decision;
    snapshot_id: string | null;
    source_refs: string[];
    financial_revision: number;
  }[];
};
type Reply = {
  id: string;
  question_ids: string[];
  versions: {
    source_id: string;
    version: number;
    text: string;
    file_ids: string[];
    added_by: string;
    added_at: string;
    origin: string;
  }[];
};
type Summary = {
  id: string;
  created_at: string;
  financial_revision: number;
  contract_version: string;
  remaining_cents: number | null;
  question_count: number;
};
export type CaseworkView = {
  cards: Card[];
  replies: Reply[];
  snapshots: Summary[];
  latest_snapshot_id: string | null;
  legacy_audit_count: number;
};
type Snapshot = {
  summary: Summary;
  payload: {
    project: State["project"];
    result: Result;
    discussion: { cards: Card[]; replies: Reply[] };
  };
};
const evidenceLabels: Record<Evidence, string> = {
  awaiting_explanation: "Awaiting explanation",
  answer_insufficient: "Answer received — evidence insufficient",
  explained_verified: "Explained with checked sources",
  contradiction_remains: "Contradiction remains",
  needs_recheck: "Needs recheck",
};
const decisionLabels: Record<Decision, string> = {
  continue_clarifying: "Continue clarifying",
  accept_explanation: "Accept explanation",
  stop_unresolved: "Stop clarifying — unresolved",
};
const money = (v: number | null) =>
  v === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(v / 100);
const metric = (v: string) => v.replaceAll("_", " ").replace(" cents", "");

export default function Casework({
  state,
  disabled,
  mutate,
  read,
  openSource,
}: {
  state: State;
  disabled: boolean;
  mutate: (path: string, body: unknown) => Promise<boolean>;
  read: <T>(path: string) => Promise<T>;
  openSource: (id: string, page?: number) => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const [editing, setEditing] = useState<Reply | null>(null);
  const [notice, setNotice] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const generation = useRef(0);
  const retry = useRef<{ key: string; id: string } | null>(null);
  const base = `projects/${state.project.id}`;
  const data = state.casework;
  const unresolved = data.cards.filter(
    (c) => c.evidence_state !== "explained_verified",
  );
  const toggle = (values: string[], id: string) =>
    values.includes(id) ? values.filter((v) => v !== id) : [...values, id];
  async function send(path: string, body: object) {
    const key = JSON.stringify([path, body]);
    if (retry.current?.key !== key)
      retry.current = { key, id: crypto.randomUUID() };
    const ok = await mutate(path, { ...body, mutation_id: retry.current.id });
    if (ok) retry.current = null;
    return ok;
  }
  async function saveReply() {
    const ok = await send(
      editing ? `${base}/replies/${editing.id}/edit` : `${base}/replies`,
      editing
        ? { expected_version: editing.versions.length, text, file_ids: files }
        : { question_ids: selected, text, file_ids: files },
    );
    if (ok) {
      setText("");
      setFiles([]);
      setEditing(null);
      setNotice(
        "Reply saved. This does not verify the explanation or change your calculation.",
      );
    }
  }
  async function openSnapshot(id: string) {
    const request = ++generation.current;
    setSnapshot(null);
    setLoading(true);
    setHistoryError("");
    try {
      const next = await read<Snapshot>(`${base}/snapshots/${id}`);
      if (request === generation.current) setSnapshot(next);
    } catch (e) {
      if (request === generation.current) setHistoryError((e as Error).message);
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }
  return (
    <section
      className="guest-panel casework"
      aria-label="Questions and review history"
    >
      <h2>4. Questions & review history</h2>
      <p>
        Keep the explanation separate from your decision. Replies are entered by
        you on behalf of the contractor; they are not independently verified
        messages.
      </p>
      <p>
        All history expires with this review,{" "}
        {new Date(state.project.expires_at).toLocaleString()}. New replies do
        not extend access.
      </p>
      {!!unresolved.length && (
        <p className="guest-preliminary" data-testid="unresolved-history">
          {unresolved.length} unresolved question
          {unresolved.length === 1 ? "" : "s"} in the review history. Owner
          acceptance or stopping clarification does not establish the evidence
          or payment conditions.
        </p>
      )}
      {disabled && (
        <p role="status">
          Finish processing and save your financial choices before updating the
          discussion. These cards show the last recorded review, not the result
          of your pending choices.
        </p>
      )}
      {!data.cards.length && (
        <p>
          No saved question cards yet. Save a review to record its questions.
        </p>
      )}
      {data.cards.map((card) => (
        <details
          className="question-card"
          key={card.id}
          data-question-code={card.observation.code}
        >
          <summary>
            {card.observation.message}{" "}
            <span>{evidenceLabels[card.evidence_state]}</span>
          </summary>
          <p>
            {card.observation.active
              ? "Present in the current calculation."
              : "Not present in the current calculation. Disappearance alone is not verified resolution."}
          </p>
          <p>
            <strong>Evidence:</strong> {evidenceLabels[card.evidence_state]}
            <br />
            <strong>Owner decision:</strong>{" "}
            {decisionLabels[card.owner_decision]}
          </p>
          <p>
            Financial basis: revision {card.observation.financial_revision}.
            Affects: {card.observation.affects.map(metric).join(", ")}.
          </p>
          <dl className="question-amounts">
            {Object.entries(card.observation.metric_values).map(
              ([key, value]) => (
                <div key={key}>
                  <dt>{metric(key)} (current recorded total)</dt>
                  <dd>{money(value)}</dd>
                </div>
              ),
            )}
          </dl>
          <details>
            <summary>Related records, amounts & source pages</summary>
            {Object.entries(card.observation.amounts_cents).map(
              ([id, amount]) => (
                <p key={id}>
                  <code>{id}</code> — {money(amount)}
                </p>
              ),
            )}
            <p>
              Record versions:{" "}
              {card.observation.record_ids.join(", ") ||
                "No financial record yet"}
            </p>
            {card.observation.source_refs.map((ref) => {
              const source = state.result.sources.find(
                (s) => s.source_id === ref,
              );
              return (
                source && (
                  <details key={ref}>
                    <summary>
                      {source.title} · page {source.page} · {source.origin}
                    </summary>
                    <pre>{source.text}</pre>
                    {source.file_id && (
                      <button
                        onClick={() =>
                          void openSource(source.file_id!, source.page ?? 1)
                        }
                      >
                        View related original page {source.page}
                      </button>
                    )}
                  </details>
                )
              );
            })}
          </details>
          <h3>Question to ask the contractor</h3>
          <p className="contractor-question">
            {card.observation.contractor_question}
          </p>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(
                  card.observation.contractor_question,
                );
                setNotice("Question copied. Nothing was sent.");
              } catch {
                setNotice(
                  "Copy is unavailable. Select and copy the question text above.",
                );
              }
            }}
          >
            Copy question
          </button>
          <label>
            <input
              type="checkbox"
              disabled={disabled || !!editing}
              checked={selected.includes(card.id)}
              onChange={() => setSelected(toggle(selected, card.id))}
            />
            Include this question in the reply or attachments below
          </label>
          <h3>Replies</h3>
          {!card.reply_ids.length && (
            <p>
              No reply recorded. A text explanation can be saved without a new
              invoice.
            </p>
          )}
          {data.replies
            .filter((r) => card.reply_ids.includes(r.id))
            .map((reply) => (
              <article className="saved-reply" key={reply.id}>
                <p>
                  <strong>Owner-reported contractor reply</strong> · version{" "}
                  {reply.versions.length}
                </p>
                <p className="reply-text">{reply.versions.at(-1)!.text}</p>
                <small>
                  Added by {reply.versions.at(-1)!.added_by} at{" "}
                  {new Date(reply.versions.at(-1)!.added_at).toLocaleString()}
                </small>
                <button
                  disabled={disabled}
                  onClick={() => {
                    setEditing(reply);
                    setText(reply.versions.at(-1)!.text);
                    setFiles(reply.versions.at(-1)!.file_ids);
                    setSelected(reply.question_ids);
                    setNotice(
                      "Editing reply below. The previous version will remain in history.",
                    );
                  }}
                >
                  Edit reply
                </button>
                <details>
                  <summary>Reply versions & provenance</summary>
                  {reply.versions.map((v) => (
                    <div key={v.source_id}>
                      <p>
                        Version {v.version} ·{" "}
                        {new Date(v.added_at).toLocaleString()} · {v.origin}
                      </p>
                      <code>{v.source_id}</code>
                      <p className="reply-text">{v.text}</p>
                      <p>
                        Documents:{" "}
                        {v.file_ids
                          .map(
                            (id) =>
                              state.project.documents.find((d) => d.id === id)
                                ?.name ?? id,
                          )
                          .join(", ") || "None"}
                      </p>
                    </div>
                  ))}
                </details>
              </article>
            ))}
          <h3>Attached documents</h3>
          {!card.file_ids.length && <p>None</p>}
          {card.file_ids.map((id) => (
            <button key={id} onClick={() => void openSource(id)}>
              {state.project.documents.find((d) => d.id === id)?.name ?? id}
            </button>
          ))}
          <Assessment
            key={`${card.id}:${card.version}`}
            card={card}
            disabled={disabled}
            latest={data.latest_snapshot_id}
            sources={state.result.sources}
            save={(body) => send(`${base}/questions/${card.id}/state`, body)}
          />
          <details>
            <summary>State history ({card.events.length})</summary>
            <ol>
              {card.events.map((e) => (
                <li key={e.id}>
                  <p>
                    {new Date(e.at).toLocaleString()} · {e.actor} · revision{" "}
                    {e.financial_revision}
                  </p>
                  <p>{e.detail}</p>
                  <p>
                    {evidenceLabels[e.evidence_state]} /{" "}
                    {decisionLabels[e.owner_decision]}
                  </p>
                  {!!e.source_refs.length && (
                    <p>Evidence: {e.source_refs.join(", ")}</p>
                  )}
                  {e.snapshot_id && (
                    <button onClick={() => void openSnapshot(e.snapshot_id!)}>
                      View supporting calculation
                    </button>
                  )}
                </li>
              ))}
            </ol>
          </details>
        </details>
      ))}
      {!!data.cards.length && (
        <fieldset disabled={disabled} className="reply-editor">
          <legend>
            {editing
              ? "Edit recorded reply"
              : "Record a contractor reply or attach documents"}
          </legend>
          <p>
            {selected.length} question(s) selected. Select one or more cards
            above.
          </p>
          <label>
            Contractor reply (entered by you)
            <textarea
              value={text}
              maxLength={4000}
              rows={5}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <p>
            No document is required for a text reply. For a new attachment, use
            Add a document above, wait for processing, review its facts, then
            select it here.
          </p>
          {state.project.documents.map((doc) => (
            <label key={doc.id}>
              <input
                type="checkbox"
                checked={files.includes(doc.id)}
                onChange={() => setFiles(toggle(files, doc.id))}
              />
              Attach {doc.name}
            </label>
          ))}
          <button
            disabled={!selected.length || !text.trim()}
            onClick={() => void saveReply()}
          >
            {editing ? "Save reply version" : "Save reply"}
          </button>
          {!editing && (
            <button
              disabled={!selected.length || !files.length}
              onClick={async () => {
                if (
                  await send(`${base}/attachments`, {
                    question_ids: selected,
                    file_ids: files,
                  })
                )
                  setNotice(
                    "Documents linked. Linking does not confirm their financial meaning.",
                  );
              }}
            >
              Attach selected documents only
            </button>
          )}
          {editing && (
            <button
              onClick={() => {
                setEditing(null);
                setText("");
                setFiles([]);
              }}
            >
              Cancel editing reply
            </button>
          )}
        </fieldset>
      )}
      {notice && <p role="status">{notice}</p>}
      <h3>Saved calculations</h3>
      <p>
        Frozen results, not recalculated by the current code. Viewing a snapshot
        does not restore or overwrite current choices.
      </p>
      {!!data.legacy_audit_count && (
        <p>
          {data.legacy_audit_count} older audit record(s) exist without a
          complete result snapshot. They are not presented as historical
          calculations.
        </p>
      )}
      {!data.snapshots.length && <p>No calculation snapshots saved yet.</p>}
      <ol className="snapshot-list">
        {data.snapshots.map((s) => (
          <li key={s.id}>
            <button onClick={() => void openSnapshot(s.id)}>
              View calculation · revision {s.financial_revision} ·{" "}
              {new Date(s.created_at).toLocaleString()}
            </button>
            <span>
              Remaining {money(s.remaining_cents)} · {s.question_count}{" "}
              calculation question(s)
            </span>
          </li>
        ))}
      </ol>
      {loading && <p role="status">Loading saved calculation…</p>}
      {historyError && (
        <p role="alert">
          {historyError} Select the calculation again to retry.
        </p>
      )}
      {snapshot && (
        <section
          className="historical-snapshot"
          aria-label="Historical calculation"
        >
          <h3>Historical snapshot — read only</h3>
          <PdfDownload
            key={snapshot.summary.id}
            projectId={state.project.id}
            kind="snapshot"
            resultId={snapshot.summary.id}
            savedAt={snapshot.summary.created_at}
            version={`${snapshot.summary.contract_version} / revision ${snapshot.summary.financial_revision}`}
            disabled={disabled}
          />
          <p>
            {snapshot.summary.contract_version} · revision{" "}
            {snapshot.summary.financial_revision} ·{" "}
            {new Date(snapshot.summary.created_at).toLocaleString()}
          </p>
          <button
            onClick={() => {
              ++generation.current;
              setSnapshot(null);
            }}
          >
            Close historical snapshot
          </button>
          {snapshot.payload.result.incomplete && (
            <p className="guest-preliminary">
              Preliminary at the time of this calculation.
            </p>
          )}
          <div className="guest-metrics">
            <article>
              <h4>Requested in this invoice</h4>
              <strong>
                {money(snapshot.payload.result.calculation.requested_now_cents)}
              </strong>
            </article>
            <article>
              <h4>Remaining under recorded terms</h4>
              <strong data-testid="snapshot-remaining">
                {money(
                  snapshot.payload.result.calculation
                    .remaining_commitment_cents,
                )}
              </strong>
            </article>
            <article>
              <h4>Current payment conditions</h4>
              {snapshot.payload.result.conditions.length ? (
                snapshot.payload.result.conditions.map((c) => (
                  <p key={c.source_id}>{c.text}</p>
                ))
              ) : (
                <strong>Unknown</strong>
              )}
            </article>
            <article>
              <h4>Needs clarification</h4>
              {snapshot.payload.result.questions.map((q) => (
                <p key={q.id}>{q.message}</p>
              ))}
              {!snapshot.payload.result.questions.length && (
                <p>
                  No calculation questions recorded. This does not confirm
                  payment conditions.
                </p>
              )}
            </article>
          </div>
          <p>
            Recorded commitments{" "}
            {money(snapshot.payload.result.calculation.commitment_total_cents)};
            net completed payments{" "}
            {money(snapshot.payload.result.calculation.net_paid_cents)}.
          </p>
          <p>
            Preliminary metrics:{" "}
            {snapshot.payload.result.incomplete_metrics
              .map(metric)
              .join(", ") || "None recorded"}
          </p>
          <details>
            <summary>
              Frozen inputs, decisions, normalization & discussion
            </summary>
            <pre>{JSON.stringify(snapshot.payload, null, 2)}</pre>
          </details>
          <h4>Sources saved with this result</h4>
          {snapshot.payload.result.sources.map((s) => (
            <details key={s.source_id}>
              <summary>
                {s.title} · page {s.page ?? "—"} · {s.origin}
              </summary>
              <code>{s.source_id}</code>
              <pre>{s.text}</pre>
              {s.file_id && (
                <button
                  onClick={() => void openSource(s.file_id!, s.page ?? 1)}
                >
                  View saved original page {s.page}
                </button>
              )}
            </details>
          ))}
        </section>
      )}
    </section>
  );
}

function Assessment({
  card,
  disabled,
  latest,
  sources,
  save,
}: {
  card: Card;
  disabled: boolean;
  latest: string | null;
  sources: Result["sources"];
  save: (body: object) => Promise<boolean>;
}) {
  const [evidence, setEvidence] = useState<Evidence | "">("");
  const [decision, setDecision] = useState<Decision | "">("");
  const [note, setNote] = useState("");
  const [refs, setRefs] = useState<string[]>([]);
  return (
    <fieldset disabled={disabled}>
      <legend>Record an assessment or your decision</legend>
      <label>
        Evidence assessment
        <select
          value={evidence}
          onChange={(e) => setEvidence(e.target.value as Evidence | "")}
        >
          <option value="">Keep current evidence state</option>
          {Object.entries(evidenceLabels).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Owner decision
        <select
          value={decision}
          onChange={(e) => setDecision(e.target.value as Decision | "")}
        >
          <option value="">Keep current owner decision</option>
          {Object.entries(decisionLabels).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {evidence === "explained_verified" && (
        <>
          <p>
            This is your explicit evidence assessment, not independent
            authentication. The server requires checked pages used by a current
            saved calculation, with this uncertainty no longer present.
          </p>
          {card.observation.source_refs.map((ref) => (
            <label key={ref}>
              <input
                type="checkbox"
                checked={refs.includes(ref)}
                onChange={() =>
                  setRefs(
                    refs.includes(ref)
                      ? refs.filter((r) => r !== ref)
                      : [...refs, ref],
                  )
                }
              />
              I checked {sources.find((s) => s.source_id === ref)?.title ?? ref}
              , page {sources.find((s) => s.source_id === ref)?.page}
            </label>
          ))}
        </>
      )}
      <label>
        Reason for this assessment or decision
        <textarea
          rows={2}
          maxLength={1000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <button
        disabled={!note.trim() || (!evidence && !decision)}
        onClick={() =>
          void save({
            expected_version: card.version,
            note,
            evidence_state: evidence || null,
            owner_decision: decision || null,
            ...(evidence === "explained_verified"
              ? { snapshot_id: latest, source_refs: refs }
              : {}),
          })
        }
      >
        Save assessment / decision
      </button>
    </fieldset>
  );
}
