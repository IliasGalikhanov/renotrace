"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Casework, { type CaseworkView } from "./casework";

type Kind =
  | "agreement"
  | "adjustment"
  | "payment_request"
  | "payment"
  | "refund"
  | "condition"
  | "unknown";
type Choice = {
  id: string;
  kind: Kind;
  amount: string | null;
  date: string | null;
  answer: "accept" | "reject" | "unknown";
  recipient: "contractor" | "other" | "unknown";
  state: string;
};
type Candidate = Omit<Choice, "answer" | "recipient"> & {
  file_id: string;
  page: number;
  snippet: string;
  original_amount: string | null;
};
type Document = {
  id: string;
  name: string;
  checksum: string;
  page_count: number;
  pages: {
    number: number;
    text: string;
    method: string;
    warning: string | null;
  }[];
  candidates: Candidate[];
  status: string;
  error: string | null;
};
type LinkChoice = {
  kind: "supersedes" | "includes_adjustment";
  from_id: string;
  to_id: string;
};
type Command = {
  expected_revision: number;
  records: Choice[];
  agreement_id: string | null;
  request_id: string | null;
  cutoff_date: string;
  links: LinkChoice[];
};
type Source = {
  source_id: string;
  file_id: string | null;
  page: number | null;
  title: string;
  text: string;
  origin: string;
};
export type Result = {
  calculation: {
    requested_now_cents: number | null;
    remaining_commitment_cents: number | null;
    commitment_total_cents: number | null;
    net_paid_cents: number;
    commitment_record_ids: string[];
    completed_cash_record_ids: string[];
  };
  incomplete: boolean;
  incomplete_metrics: string[];
  questions: {
    id: string;
    message: string;
    affects: string[];
    record_ids: string[];
  }[];
  sources: Source[];
  conditions: Source[];
  normalization: {
    included: {
      record: { id: string };
      evidence_refs: string[];
      reason: string;
    }[];
    excluded: {
      record: { id: string };
      evidence_refs: string[];
      reason: string;
    }[];
  };
};
export type State = {
  project: {
    id: string;
    revision: number;
    expires_at: string;
    documents: Document[];
    review: { basis_revision: number; command: Command } | null;
  };
  result: Result;
  casework: CaseworkView;
};
const labels: Record<Kind, string> = {
  agreement: "Estimate / contract price",
  adjustment: "Change in contract price",
  payment_request: "Current invoice / payment request",
  payment: "Payment",
  refund: "Refund (negative amount)",
  condition: "Payment condition",
  unknown: "Unknown meaning",
};
const money = (value: number | null) =>
  value === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(value / 100);

async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/guest/${path}`, {
    method,
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(28_000),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.detail || "Request failed. Please retry.");
  return data as T;
}

function draft(state: State): Command {
  const saved = state.project.review;
  const choices = new Map(saved?.command.records.map((r) => [r.id, r]));
  const current = saved?.basis_revision === state.project.revision;
  return {
    expected_revision: state.project.revision,
    records: state.project.documents.flatMap((d) =>
      d.candidates.map((c) => ({
        id: c.id,
        kind: choices.get(c.id)?.kind ?? c.kind,
        amount: choices.get(c.id)?.amount ?? c.amount,
        date: choices.get(c.id)?.date ?? c.date,
        state: choices.get(c.id)?.state ?? c.state,
        recipient: choices.get(c.id)?.recipient ?? "unknown",
        answer: current ? (choices.get(c.id)?.answer ?? "unknown") : "unknown",
      })),
    ),
    agreement_id: saved?.command.agreement_id ?? null,
    request_id: saved?.command.request_id ?? null,
    cutoff_date:
      saved?.command.cutoff_date ?? new Date().toISOString().slice(0, 10),
    links: current ? (saved?.command.links ?? []) : [],
  };
}

export default function GuestReview() {
  const [state, setState] = useState<State | null>(null);
  const [command, setCommand] = useState<Command | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [consent, setConsent] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [preview, setPreview] = useState<{
    url: string;
    name: string;
    type: string;
    page: number;
  } | null>(null);
  const generation = useRef(0);
  const reviewRetry = useRef<{ key: string; id: string } | null>(null);
  const active = useRef(false);
  const pending = !!state?.project.documents.some((d) =>
    ["queued", "processing"].includes(d.status),
  );

  const accept = useCallback((next: State) => {
    setState(next);
    setCommand(draft(next));
    setDirty(false);
  }, []);
  const start = useCallback(async () => {
    if (active.current) return;
    active.current = true;
    const id = ++generation.current;
    setBusy("Opening your private review…");
    setError("");
    try {
      const session = await api<{ project_id: string }>("session", "POST");
      const next = await api<State>(`projects/${session.project_id}`);
      if (id === generation.current) {
        accept(next);
        setDeleted(false);
      }
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
    } finally {
      if (id === generation.current) setBusy("");
      active.current = false;
    }
  }, [accept]);

  useEffect(() => {
    void start();
  }, [start]);
  useEffect(() => {
    if (!pending || busy || !state) return;
    const id = generation.current;
    const timer = setTimeout(
      async () => {
        try {
          const next = await api<State>(`projects/${state.project.id}`);
          if (id === generation.current) accept(next);
        } catch (e) {
          if (id === generation.current) setError((e as Error).message);
        }
      },
      error ? 15_000 : 3_000,
    );
    return () => clearTimeout(timer);
  }, [pending, busy, state, error, accept]);
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview.url);
    },
    [preview],
  );

  async function upload(file: File) {
    if (!state || !consent) return;
    const id = ++generation.current;
    setBusy(`Uploading ${file.name}…`);
    setError("");
    setDirty(true);
    try {
      const ticket = await api<{ token: string; transfer_url: string }>(
        `projects/${state.project.id}/tickets`,
        "POST",
        { purpose: "upload", name: file.name },
      );
      const response = await fetch(ticket.transfer_url, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${ticket.token}`,
          "Content-Type": "application/octet-stream",
        },
        body: file,
        signal: AbortSignal.timeout(90_000),
      });
      if (!response.ok) {
        const failure = await response.json();
        throw new Error(failure.detail ?? "Upload failed");
      }
      const next = await api<State>(`projects/${state.project.id}`);
      if (id === generation.current) accept(next);
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
    } finally {
      if (id === generation.current) setBusy("");
    }
  }

  async function save() {
    if (!state || !command) return;
    const id = ++generation.current;
    setBusy("Checking your choices and calculating…");
    setError("");
    const key = JSON.stringify(command);
    if (reviewRetry.current?.key !== key)
      reviewRetry.current = { key, id: crypto.randomUUID() };
    try {
      const next = await api<State>(
        `projects/${state.project.id}/review`,
        "POST",
        { ...command, mutation_id: reviewRetry.current.id },
      );
      if (id === generation.current) {
        accept(next);
        reviewRetry.current = null;
      }
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
    } finally {
      if (id === generation.current) setBusy("");
    }
  }

  async function openSource(fileId: string, page = 1) {
    if (!state) return;
    setError("");
    const id = generation.current;
    try {
      const ticket = await api<{ token: string; transfer_url: string }>(
        `projects/${state.project.id}/tickets`,
        "POST",
        { purpose: "download", file_id: fileId },
      );
      const response = await fetch(ticket.transfer_url, {
        headers: { Authorization: `Bearer ${ticket.token}` },
        signal: AbortSignal.timeout(45_000),
      });
      if (!response.ok)
        throw new Error(
          "The original is unavailable or this review has expired.",
        );
      const blob = await response.blob();
      if (id === generation.current)
        setPreview({
          url: URL.createObjectURL(blob),
          type: blob.type,
          name:
            state.project.documents.find((d) => d.id === fileId)?.name ??
            "Original",
          page,
        });
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
    }
  }

  async function discuss(path: string, body: unknown): Promise<boolean> {
    if (busy || dirty || pending) return false;
    const id = ++generation.current;
    setBusy("Saving discussion history…");
    setError("");
    try {
      const next = await api<State>(path, "POST", body);
      if (id === generation.current) accept(next);
      return true;
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
      return false;
    } finally {
      if (id === generation.current) setBusy("");
    }
  }

  async function remove() {
    if (!state) return;
    ++generation.current;
    setBusy("Deleting your review…");
    setError("");
    try {
      await api(`projects/${state.project.id}`, "DELETE");
      setState(null);
      setCommand(null);
      setPreview(null);
      setDeleted(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  function update(id: string, patch: Partial<Choice>) {
    if (busy || pending) return;
    setCommand((previous) =>
      previous
        ? {
            ...previous,
            records: previous.records.map((r) =>
              r.id === id ? { ...r, ...patch } : r,
            ),
          }
        : null,
    );
    setDirty(true);
  }
  function change(patch: Partial<Command>) {
    if (busy || pending) return;
    setCommand((previous) => (previous ? { ...previous, ...patch } : null));
    setDirty(true);
  }
  const candidates =
    state?.project.documents.flatMap((d) => d.candidates) ?? [];
  const title = (id: string) =>
    candidates.find((c) => c.id === id.split(":r")[0])?.snippet ?? id;

  async function reloadReview() {
    if (!state) {
      await start();
      return;
    }
    const id = ++generation.current;
    setBusy("Reloading your review…");
    setError("");
    try {
      const next = await api<State>(`projects/${state.project.id}`);
      if (id === generation.current) accept(next);
    } catch (e) {
      if (id === generation.current) setError((e as Error).message);
    } finally {
      if (id === generation.current) setBusy("");
    }
  }

  return (
    <div className="guest-workspace">
      <ol className="guest-steps">
        <li>1. Upload documents</li>
        <li>2. Check facts & links</li>
        <li>3. Review calculation</li>
      </ol>
      <section className="guest-notice">
        <strong>Private, temporary, no account.</strong> Your review expires 24
        hours after creation
        {state
          ? ` (${new Date(state.project.expires_at).toLocaleString("en-US")})`
          : ""}
        . Continue in this browser while its session cookie remains. Delete your
        review at any time. Access ends at expiry; scheduled cleanup removes
        expired originals. Files are stored privately in Supabase and processed
        on the RenoTrace backend (Render) using local Tesseract OCR. No external
        AI receives them.
        <p>
          PDF, JPEG or PNG · 10 MiB per file · 20 pages per file · 50 pages per
          review. USD / English labelled documents. Recognition can be
          incomplete; you must check the originals.
        </p>
      </section>
      {busy && (
        <p role="status" className="guest-status">
          {busy} The service may take a moment to start.
        </p>
      )}
      {error && (
        <div role="alert" className="guest-error">
          {error}{" "}
          <button disabled={!!busy} onClick={() => void reloadReview()}>
            Retry / reload review
          </button>
        </div>
      )}
      {deleted && (
        <section>
          <h2>Your review has been deleted.</h2>
          <p>Its documents, decisions and results are no longer accessible.</p>
          <button onClick={() => void start()}>Start a new review</button>
        </section>
      )}
      {state && (
        <>
          <section className="guest-panel">
            <h2>1. Your documents</h2>
            <p>
              Start with the current invoice, then add the estimate and payment
              confirmations.
            </p>
            <label className="guest-consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />{" "}
              I understand the processing services and 24-hour retention above.
            </label>
            <label className="guest-upload">
              Add a document
              <input
                aria-label="Add a document"
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                disabled={!consent || !!busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                  e.target.value = "";
                }}
              />
            </label>
            {state.project.documents.map((d) => (
              <article key={d.id} className="guest-document">
                <div>
                  <strong>{d.name}</strong>
                  <span>
                    {d.page_count} page(s) · {d.status} · {d.pages.length}{" "}
                    processed
                  </span>
                  {d.error && <p role="alert">{d.error}</p>}
                </div>
                <button disabled={!!busy} onClick={() => void openSource(d.id)}>
                  View {d.name}
                </button>
                <details>
                  <summary>Checksum & extracted pages</summary>
                  <code>{d.checksum}</code>
                  {d.pages.map((p) => (
                    <div key={p.number}>
                      <h4>
                        Page {p.number} · {p.method}
                      </h4>
                      <pre>{p.text || "Unknown — unreadable page"}</pre>
                    </div>
                  ))}
                </details>
              </article>
            ))}
            {pending && (
              <p role="status">
                Processing your documents. You may close this tab; progress is
                saved. A sleeping free server resumes pending work on its next
                wake.
              </p>
            )}
          </section>
          {preview && (
            <section className="guest-panel" aria-label="Original document">
              <h2>
                {preview.name} · page {preview.page}
              </h2>
              <button onClick={() => setPreview(null)}>Close original</button>
              <a
                href={`${preview.url}#page=${preview.page}`}
                target="_blank"
                rel="noreferrer"
              >
                Open original in a new tab
              </a>
              {preview.type === "application/pdf" ? (
                <iframe
                  title="Original document preview"
                  src={`${preview.url}#page=${preview.page}`}
                />
              ) : (
                <img alt="Uploaded original" src={preview.url} />
              )}
            </section>
          )}
          {command && candidates.length > 0 && (
            <section className="guest-panel">
              <h2>2. Check facts & links</h2>
              <p>
                Nothing is automatically confirmed. Compare each candidate with
                its source, correct mistakes, then choose Include, Exclude or
                Unknown. A deposit mentioned on an invoice is not proof of
                another transfer.
              </p>
              {command.records.map((r, index) => {
                const c = candidates.find((c) => c.id === r.id)!;
                return (
                  <fieldset
                    className="guest-fact"
                    key={r.id}
                    disabled={!!busy || pending}
                    data-testid={`fact-${index}`}
                  >
                    <legend>Record {index + 1}</legend>
                    <blockquote>{c.snippet}</blockquote>
                    <p>
                      Original amount:{" "}
                      <strong>{c.original_amount ?? "Unknown"}</strong> ·{" "}
                      <button
                        type="button"
                        onClick={() => void openSource(c.file_id, c.page)}
                      >
                        Source page {c.page}
                      </button>
                    </p>
                    <div className="guest-fields">
                      <label>
                        Meaning
                        <select
                          value={r.kind}
                          onChange={(e) =>
                            update(r.id, { kind: e.target.value as Kind })
                          }
                        >
                          {Object.entries(labels).map(([key, label]) => (
                            <option key={key} value={key}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Amount (USD)
                        <input
                          inputMode="decimal"
                          value={r.amount ?? ""}
                          placeholder="Unknown"
                          onChange={(e) =>
                            update(r.id, { amount: e.target.value || null })
                          }
                        />
                      </label>
                      <label>
                        Record date
                        <input
                          type="date"
                          value={r.date ?? ""}
                          onChange={(e) =>
                            update(r.id, { date: e.target.value || null })
                          }
                        />
                      </label>
                      <label>
                        Belongs to
                        <select
                          value={r.recipient}
                          onChange={(e) =>
                            update(r.id, {
                              recipient: e.target.value as Choice["recipient"],
                            })
                          }
                        >
                          <option value="unknown">Unknown</option>
                          <option value="contractor">
                            Contractor in this review
                          </option>
                          <option value="other">
                            Another recipient / contractor
                          </option>
                        </select>
                      </label>
                      {(r.kind === "payment" || r.kind === "refund") && (
                        <label>
                          Payment status
                          <select
                            value={r.state}
                            onChange={(e) =>
                              update(r.id, { state: e.target.value })
                            }
                          >
                            {[
                              "pending",
                              "completed",
                              "scheduled",
                              "failed",
                              "reversed",
                            ].map((s) => (
                              <option key={s}>{s}</option>
                            ))}
                          </select>
                        </label>
                      )}
                      <label>
                        Your decision
                        <select
                          value={r.answer}
                          onChange={(e) =>
                            update(r.id, {
                              answer: e.target.value as Choice["answer"],
                            })
                          }
                        >
                          <option value="unknown">Unknown / not checked</option>
                          <option value="accept">
                            Include — I checked this record
                          </option>
                          <option value="reject">Exclude this record</option>
                        </select>
                      </label>
                    </div>
                  </fieldset>
                );
              })}
              <fieldset disabled={!!busy || pending} className="guest-fields">
                <legend>Current terms & relationships</legend>
                <label>
                  Active estimate
                  <select
                    value={command.agreement_id ?? ""}
                    onChange={(e) =>
                      change({ agreement_id: e.target.value || null })
                    }
                  >
                    <option value="">Unknown / not selected</option>
                    {command.records
                      .filter((r) => r.kind === "agreement")
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {title(r.id)}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Current invoice
                  <select
                    aria-label="Current invoice"
                    value={command.request_id ?? ""}
                    onChange={(e) =>
                      change({ request_id: e.target.value || null })
                    }
                  >
                    <option value="">Unknown / not selected</option>
                    {command.records
                      .filter((r) => r.kind === "payment_request")
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {title(r.id)}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Calculation cutoff
                  <input
                    type="date"
                    value={command.cutoff_date}
                    onChange={(e) => change({ cutoff_date: e.target.value })}
                  />
                </label>
              </fieldset>
              <details>
                <summary>Estimate versions and included changes</summary>
                <p>Add only relationships you checked against the documents.</p>
                {command.links.map((link, index) => (
                  <div className="guest-fields" key={index}>
                    <label>
                      New estimate
                      <select
                        value={link.from_id}
                        onChange={(e) =>
                          change({
                            links: command.links.map((l, i) =>
                              i === index
                                ? { ...l, from_id: e.target.value }
                                : l,
                            ),
                          })
                        }
                      >
                        <option value="">Choose record</option>
                        {command.records
                          .filter((r) => r.kind === "agreement")
                          .map((r) => (
                            <option key={r.id} value={r.id}>
                              {title(r.id)}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      Relationship
                      <select
                        value={link.kind}
                        onChange={(e) =>
                          change({
                            links: command.links.map((l, i) =>
                              i === index
                                ? {
                                    ...l,
                                    kind: e.target.value as LinkChoice["kind"],
                                  }
                                : l,
                            ),
                          })
                        }
                      >
                        <option value="supersedes">
                          Replaces old estimate
                        </option>
                        <option value="includes_adjustment">
                          Already includes cost change
                        </option>
                      </select>
                    </label>
                    <label>
                      Related record
                      <select
                        value={link.to_id}
                        onChange={(e) =>
                          change({
                            links: command.links.map((l, i) =>
                              i === index ? { ...l, to_id: e.target.value } : l,
                            ),
                          })
                        }
                      >
                        <option value="">Choose record</option>
                        {command.records
                          .filter(
                            (r) =>
                              r.kind ===
                              (link.kind === "supersedes"
                                ? "agreement"
                                : "adjustment"),
                          )
                          .map((r) => (
                            <option key={r.id} value={r.id}>
                              {title(r.id)}
                            </option>
                          ))}
                      </select>
                    </label>
                    <button
                      onClick={() =>
                        change({
                          links: command.links.filter((_, i) => i !== index),
                        })
                      }
                    >
                      Remove relationship {index + 1}
                    </button>
                  </div>
                ))}
                <button
                  disabled={!!busy || pending}
                  onClick={() =>
                    change({
                      links: [
                        ...command.links,
                        { kind: "supersedes", from_id: "", to_id: "" },
                      ],
                    })
                  }
                >
                  Add relationship
                </button>
              </details>
              <p>
                Saving records these choices against the current document set.
                Corrections remain separate from your immutable originals.
              </p>
              <button
                className="guest-primary"
                disabled={!!busy || pending}
                onClick={() => void save()}
              >
                Save review and calculate
              </button>
            </section>
          )}
          <section className="guest-panel" aria-label="Your calculation">
            <h2>3. Your calculation</h2>
            {busy || dirty || pending ? (
              <p role="status">
                {dirty
                  ? "Your choices have changed. Save the review to calculate."
                  : "Waiting for the current documents and choices."}{" "}
                Previous figures are hidden.
              </p>
            ) : (
              <>
                {state.result.incomplete && (
                  <p className="guest-preliminary">
                    Preliminary — unresolved evidence affects this calculation.
                  </p>
                )}
                <div className="guest-metrics">
                  <article>
                    <h3>Requested in this invoice</h3>
                    <strong data-testid="guest-requested">
                      {money(state.result.calculation.requested_now_cents)}
                    </strong>
                  </article>
                  <article>
                    <h3>Remaining under recorded terms</h3>
                    <strong data-testid="guest-remaining">
                      {money(
                        state.result.calculation.remaining_commitment_cents,
                      )}
                    </strong>
                  </article>
                  <article>
                    <h3>Current payment conditions</h3>
                    {state.result.conditions.length ? (
                      state.result.conditions.map((c) => (
                        <p key={c.source_id}>{c.text}</p>
                      ))
                    ) : (
                      <strong>Unknown</strong>
                    )}
                  </article>
                  <article>
                    <h3>Needs clarification</h3>
                    <strong>
                      {state.result.questions.length ||
                        "No current calculation questions"}
                    </strong>
                    <p>
                      {
                        state.casework.cards.filter(
                          (c) => c.evidence_state !== "explained_verified",
                        ).length
                      }{" "}
                      unresolved in review history below.
                    </p>
                    <small>
                      Absence of questions does not confirm payment conditions.
                    </small>
                  </article>
                </div>
                <ul>
                  {state.result.questions.map((q) => (
                    <li key={q.id}>
                      {q.message}
                      <small>Affects: {q.affects.join(", ")}</small>
                    </li>
                  ))}
                </ul>
                <details>
                  <summary>
                    Calculation, participating records & sources
                  </summary>
                  <p>
                    Recorded commitments:{" "}
                    {money(state.result.calculation.commitment_total_cents)}.
                    Net completed payments:{" "}
                    {money(state.result.calculation.net_paid_cents)}. Remaining
                    = commitments − net payments. The requested amount is
                    separate.
                  </p>
                  <h4>Included records</h4>
                  {state.result.normalization.included.map((d) => (
                    <p key={d.record.id}>
                      {title(d.record.id)} · {d.reason}
                      <small>Sources: {d.evidence_refs.join(", ")}</small>
                    </p>
                  ))}
                  <h4>Excluded records</h4>
                  {state.result.normalization.excluded.map((d) => (
                    <p key={d.record.id}>
                      {title(d.record.id)} · {d.reason}
                    </p>
                  ))}
                  {state.result.sources.map((source) => (
                    <details key={source.source_id}>
                      <summary>
                        {source.title} · {source.origin}
                      </summary>
                      <code>{source.source_id}</code>
                      <pre>{source.text}</pre>
                      {source.file_id && (
                        <button
                          onClick={() =>
                            void openSource(source.file_id!, source.page ?? 1)
                          }
                        >
                          View source page {source.page}
                        </button>
                      )}
                    </details>
                  ))}
                </details>
              </>
            )}
          </section>
          <Casework
            state={state}
            disabled={!!busy || dirty || pending}
            mutate={discuss}
            read={api}
            openSource={openSource}
          />
          <section className="guest-delete">
            <p>
              This review is temporary. Deletion revokes access and removes your
              records and originals.
            </p>
            <button disabled={!!busy} onClick={() => void remove()}>
              Delete my review
            </button>
          </section>
        </>
      )}
    </div>
  );
}
