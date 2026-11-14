"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Action, Answer, Demo, Scenario, Trace } from "./demo-types";

const money = (cents: number | null) =>
  cents === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(cents / 100);
const humanize = (text: string) => text.toLowerCase().replaceAll("_", " ");
const metricLabels: Record<string, string> = {
  cash_balances: "payment balances",
  charge_balances: "invoice balances",
  credit_balance_cents: "invoice credits",
  net_allocations_cents: "allocated payments",
  net_paid_cents: "net payments",
  positive_outstanding_cents: "open invoice balances",
  remaining_commitment_cents: "remaining under recorded terms",
  unallocated_cents: "unallocated cash",
};
const labels: Record<Answer, string> = {
  contractor: "The contractor",
  other: "Another recipient",
  unknown: "I don't know",
};

function Sources({ demo, ids }: { demo: Demo; ids: string[] }) {
  return (
    <div className="sources">
      {ids.length === 0 ? (
        <p>No supporting source is supplied in this sample.</p>
      ) : (
        ids.map((id) => {
          const source = demo.source_contents.find((s) => s.source_id === id);
          const origin = demo.history.sources.find((s) => s.id === id)?.origin;
          return (
            <blockquote key={id}>
              <div className="source-heading">
                <strong>{source?.title ?? "Source unavailable"}</strong>
                <span>{humanize(origin ?? "unknown")}</span>
              </div>
              <p>{source?.excerpt ?? "This source could not be displayed."}</p>
              <small>Synthetic source · {id}</small>
            </blockquote>
          );
        })
      )}
    </div>
  );
}

function Evidence({
  demo,
  trace,
  title = "Trace this amount",
}: {
  demo: Demo;
  trace: Trace;
  title?: string;
}) {
  return (
    <details className="evidence">
      <summary>
        {title}
        <span aria-hidden="true">↗</span>
      </summary>
      <p>{trace.formula}</p>
      {trace.record_ids.length > 0 && (
        <p className="record-refs">
          Records:{" "}
          {trace.record_ids
            .map((id) => demo.record_titles[id] ?? id)
            .join(" · ")}
        </p>
      )}
      <Sources demo={demo} ids={trace.source_ids} />
    </details>
  );
}

function Metric({
  demo,
  name,
  label,
  description,
  accent = false,
}: {
  demo: Demo;
  name: string;
  label: string;
  description: string;
  accent?: boolean;
}) {
  const preliminary = demo.normalization.incomplete_metrics.includes(name);
  return (
    <article
      className={`metric ${accent ? "metric-primary" : ""}`}
      aria-label={label}
    >
      <p className="card-label">{label}</p>
      <div className="amount">{money(demo.traces[name].amount_cents)}</div>
      <span className={`status-pill ${preliminary ? "warning" : ""}`}>
        {preliminary
          ? "Provisional"
          : demo.traces[name].amount_cents === null
            ? "Not supplied"
            : "Recorded"}
      </span>
      <p className="card-description">{description}</p>
      <Evidence demo={demo} trace={demo.traces[name]} />
    </article>
  );
}

export default function DemoExperience() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [catalogError, setCatalogError] = useState(false);
  const [scenario, setScenario] = useState("FIN-01");
  const [actions, setActions] = useState<Action[]>([]);
  const [demo, setDemo] = useState<Demo | null>(null);
  const [options, setOptions] = useState<Demo["allowed_actions"]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const currentScenario = useRef("FIN-01");
  const load = useCallback(async (id: string, nextActions: Action[]) => {
    const generation = ++sequence.current;
    controller.current?.abort();
    const requestController = new AbortController();
    controller.current = requestController;
    if (currentScenario.current !== id) setOptions([]);
    currentScenario.current = id;
    setScenario(id);
    setActions(nextActions);
    setDemo(null);
    setError("");
    setLoading(true);
    try {
      const response = await fetch(
        `/api/demo/scenarios/${id}${nextActions.length ? "/calculate" : ""}`,
        {
          method: nextActions.length ? "POST" : "GET",
          headers: { "Content-Type": "application/json" },
          body: nextActions.length
            ? JSON.stringify({ actions: nextActions })
            : undefined,
          cache: "no-store",
          signal: requestController.signal,
        },
      );
      if (!response.ok)
        throw new Error("We couldn't calculate this sample. Please try again.");
      const data: Demo = await response.json();
      if (
        data?.synthetic !== true ||
        data.scenario?.id !== id ||
        !data.normalization ||
        !data.traces
      )
        throw new Error(
          "The demo returned an unexpected response. Please retry.",
        );
      if (
        generation === sequence.current &&
        !requestController.signal.aborted
      ) {
        setDemo(data);
        setOptions(data.allowed_actions);
        setActions(data.actions);
      }
    } catch (failure) {
      if (generation === sequence.current && !requestController.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "The demo is unavailable. Please retry.",
        );
    } finally {
      if (generation === sequence.current && !requestController.signal.aborted)
        setLoading(false);
    }
  }, []);
  const loadCatalog = useCallback(async (signal?: AbortSignal) => {
    setCatalogError(false);
    try {
      const response = await fetch("/api/demo/scenarios", {
        signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error();
      const items: Scenario[] = await response.json();
      if (!Array.isArray(items) || !items.length) throw new Error();
      if (!signal?.aborted) setScenarios(items);
    } catch {
      if (!signal?.aborted) setCatalogError(true);
    }
  }, []);
  useEffect(() => {
    const catalogController = new AbortController();
    void loadCatalog(catalogController.signal);
    void load("FIN-01", []);
    return () => {
      catalogController.abort();
      controller.current?.abort();
      sequence.current++;
    };
  }, [load, loadCatalog]);
  const title =
    scenarios.find((s) => s.id === scenario)?.title ?? "Your sample history";
  return (
    <section
      id="workspace"
      className="workspace"
      aria-labelledby="workspace-title"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">THE WORKSPACE</p>
          <h2 id="workspace-title">Follow the money. Find the context.</h2>
        </div>
        <span className="quiet">No sign-up. No saved data.</span>
      </div>
      <div className="scenario-bar">
        <div
          className="scenario-list"
          role="group"
          aria-label="Choose a sample"
        >
          {scenarios.map((sample, index) => (
            <button
              key={sample.id}
              type="button"
              aria-pressed={scenario === sample.id}
              onClick={() => void load(sample.id, [])}
            >
              <span className="sample-number">0{index + 1}</span>
              <span>
                <small>{sample.id}</small>
                {sample.title}
              </span>
            </button>
          ))}
        </div>
        <button
          className="reset-button"
          onClick={() => void load(scenario, [])}
        >
          <span aria-hidden="true">↺</span> Reset sample
        </button>
      </div>
      {catalogError && (
        <div className="error" role="alert">
          The sample list couldn't load.{" "}
          <button onClick={() => void loadCatalog()}>Retry sample list</button>
        </div>
      )}
      <div className="sample-heading">
        <div>
          <p className="eyebrow">RENOVATION REVIEW / {scenario}</p>
          <h3>{title}</h3>
        </div>
        <p>
          One contractor · USD{demo && <> · As of {demo.history.cutoff_date}</>}
        </p>
      </div>
      <div role="status" aria-live="polite" className="live-status">
        {loading
          ? "Recalculating sample… Previous figures are hidden until this decision is calculated."
          : error
            ? "Calculation unavailable."
            : "Calculation updated from the sample records."}
      </div>
      {options.length > 0 && (
        <div className="decision-panel" id="recipient-decision">
          <div>
            <span className="eyebrow">YOUR DECISION</span>
            <h4>{options[0].label}</h4>
            <p>
              This answer changes the calculation, only in this browser view.
            </p>
          </div>
          {options.map((option) => (
            <fieldset key={option.record_id}>
              <legend className="sr-only">{option.label}</legend>
              {option.answers.map((answer) => (
                <label key={answer}>
                  <input
                    type="radio"
                    name={`recipient-${option.record_id}`}
                    value={answer}
                    checked={
                      (actions.find((a) => a.record_id === option.record_id)
                        ?.answer ?? "unknown") === answer
                    }
                    onChange={() =>
                      void load(scenario, [
                        {
                          kind: option.kind,
                          record_id: option.record_id,
                          answer,
                        },
                      ])
                    }
                  />
                  {labels[answer]}
                </label>
              ))}
            </fieldset>
          ))}
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          <strong>Calculation unavailable</strong>
          <p>{error}</p>
          <button
            className="button"
            onClick={() => void load(scenario, actions)}
          >
            Retry calculation
          </button>
        </div>
      )}
      <div aria-busy={loading}>
        {loading && (
          <div className="summary-grid skeletons" aria-hidden="true">
            {[1, 2, 3, 4].map((n) => (
              <div className="metric skeleton" key={n}>
                <span />
                <span />
                <span />
              </div>
            ))}
          </div>
        )}
        {demo && (
          <>
            <div className="summary-grid">
              <Metric
                demo={demo}
                name="requested_now_cents"
                label="Requested in this invoice"
                description="What the current document asks for."
              />
              <Metric
                demo={demo}
                name="remaining_commitment_cents"
                label="Remaining under recorded terms"
                description="Recorded commitments, less net payments."
                accent
              />
              <article
                className="metric"
                aria-label="Current payment conditions"
              >
                <p className="card-label">Current payment conditions</p>
                <div className="condition-value">
                  {demo.conditions.condition_text ?? "Unknown"}
                </div>
                <p className="card-description">
                  {demo.conditions.due_date
                    ? `Due date: ${demo.conditions.due_date}`
                    : "No due date supplied."}{" "}
                  Condition satisfaction:{" "}
                  {humanize(demo.conditions.satisfaction)}.
                </p>
                <details className="evidence">
                  <summary>
                    View supplied conditions<span aria-hidden="true">↗</span>
                  </summary>
                  <Sources demo={demo} ids={demo.conditions.evidence_refs} />
                </details>
              </article>
              <article
                className="metric clarification"
                aria-label="Needs clarification"
              >
                <p className="card-label">Needs clarification</p>
                <div className="amount">
                  {demo.normalization.questions.length
                    ? `${demo.normalization.questions.length} open`
                    : "All clear"}
                </div>
                <span
                  className={`status-pill ${demo.normalization.incomplete ? "warning" : ""}`}
                >
                  {demo.normalization.incomplete
                    ? "Provisional result"
                    : "For this sample"}
                </span>
                <p className="card-description">
                  {demo.normalization.incomplete
                    ? "An unresolved fact can change the affected totals."
                    : "No unresolved questions in the supplied history."}
                </p>
                <a href="#questions" className="text-link">
                  Review questions <span aria-hidden="true">↗</span>
                </a>
              </article>
            </div>
            <aside className="insight">
              <span className="insight-icon" aria-hidden="true">
                i
              </span>
              <div>
                <strong>What this example shows</strong>
                <p>{demo.explanation}</p>
              </div>
            </aside>
            <div className="detail-grid">
              <section
                className="panel history-panel"
                aria-labelledby="history-title"
              >
                <div className="panel-title">
                  <h3 id="history-title">The recorded story</h3>
                  <span>{demo.history.records.length} records</span>
                </div>
                <p className="panel-intro">
                  Open a record to see the synthetic source behind it.
                </p>
                <ol className="timeline">
                  {demo.history.records.map((record) => {
                    const disposition = [
                      ...demo.normalization.included,
                      ...demo.normalization.excluded,
                    ].find((d) => d.record.id === record.id);
                    const included = demo.normalization.included.some(
                      (d) => d.record.id === record.id,
                    );
                    return (
                      <li key={record.id}>
                        <details>
                          <summary>
                            <span
                              className={`timeline-dot ${included ? "" : "unresolved"}`}
                              aria-hidden="true"
                            />
                            <span className="record-title">
                              <small>
                                {record.effective_date} ·{" "}
                                {humanize(record.kind)}
                              </small>
                              <strong>
                                {demo.record_titles[record.id] ?? record.id}
                              </strong>
                            </span>
                            <span className="record-amount">
                              {money(record.amount_cents)}
                            </span>
                            <span className="expand" aria-hidden="true">
                              +
                            </span>
                          </summary>
                          <div className="record-detail">
                            <p className="record-status">
                              {humanize(disposition?.reason ?? "unknown")} ·
                              Meaning:{" "}
                              {humanize(
                                disposition?.effective_semantic_review ??
                                  "unknown",
                              )}
                            </p>
                            {record.basis && (
                              <p>Billing basis: {humanize(record.basis)}</p>
                            )}
                            <Sources
                              demo={demo}
                              ids={
                                disposition?.evidence_refs ??
                                record.evidence_refs
                              }
                            />
                          </div>
                        </details>
                      </li>
                    );
                  })}
                </ol>
              </section>
              <section
                className="panel calculation-panel"
                aria-labelledby="calculation-title"
              >
                <div className="panel-title">
                  <h3 id="calculation-title">Behind the numbers</h3>
                  <span>Calculated, not guessed</span>
                </div>
                <div className="formula-note">
                  Commitments − net payments = remaining
                </div>
                {[
                  "commitment_total_cents",
                  "net_paid_cents",
                  "remaining_commitment_cents",
                  ...(scenario === "FIN-11"
                    ? [
                        "charge:record:current",
                        "billed_total_cents",
                        "positive_outstanding_cents",
                        "credit_balance_cents",
                      ]
                    : []),
                  "unallocated_cents",
                ].map((key) => (
                  <div className="calculation-row" key={key}>
                    <div>
                      <span>{demo.traces[key].label}</span>
                      <strong>{money(demo.traces[key].amount_cents)}</strong>
                    </div>
                    {demo.normalization.incomplete_metrics.includes(key) && (
                      <span className="provisional-note">Provisional</span>
                    )}
                    <Evidence
                      demo={demo}
                      trace={demo.traces[key]}
                      title="Show records & sources"
                    />
                  </div>
                ))}
                {demo.calculation.charge_balances.length > 0 && (
                  <div className="invoice-balances">
                    <h4>Individual invoice balances</h4>
                    {demo.calculation.charge_balances.map((balance) => (
                      <div className="calculation-row" key={balance.charge_id}>
                        <div>
                          <span>
                            {
                              demo.record_titles[
                                balance.charge_id.replace("record:", "")
                              ]
                            }
                          </span>
                          <strong>{money(balance.remaining_cents)}</strong>
                        </div>
                        <Evidence
                          demo={demo}
                          trace={demo.traces[`balance:${balance.charge_id}`]}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
            <section
              className="panel questions-panel"
              id="questions"
              aria-labelledby="questions-title"
            >
              <div className="panel-title">
                <h3 id="questions-title">Needs clarification</h3>
                <span>Keep uncertainty visible</span>
              </div>
              {demo.normalization.questions.length === 0 ? (
                <p>
                  No open questions in this sample. This does not confirm that
                  work is complete or payment is due.
                </p>
              ) : (
                demo.normalization.questions.map((question) => (
                  <div className="question" key={question.id}>
                    <strong>
                      {question.code === "UNRESOLVED_RECIPIENT"
                        ? "The transfer recipient is unknown"
                        : humanize(question.code)}
                    </strong>
                    <p>
                      {question.message} Use the recipient choices above to
                      review it.
                    </p>
                    <p className="quiet">
                      Affected:{" "}
                      {question.affects
                        .map((key) => metricLabels[key] ?? humanize(key))
                        .join(", ")}
                    </p>
                    <Sources
                      demo={demo}
                      ids={demo.history.records
                        .filter((r) => question.record_ids.includes(r.id))
                        .flatMap((r) => r.evidence_refs)}
                    />
                  </div>
                ))
              )}
            </section>
            <p className="calculation-footnote">
              A calculation from supplied records, not permission to pay. No
              account, uploaded documents or saved decisions. Reset or reload to
              start over.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
