"use client";

import type { Command, State } from "./review";
import {
  type InvoiceLine,
  type InvoiceReview,
  type LineKind,
  lineLabels,
} from "./invoice-types";

export default function InvoiceEditor({
  state,
  command,
  change,
  disabled,
  openSource,
}: {
  state: State;
  command: Command;
  change: (patch: Partial<Command>) => void;
  disabled: boolean;
  openSource: (id: string, page?: number) => Promise<void>;
}) {
  const document = state.project.documents.find((d) =>
    d.candidates.some((c) => c.id === command.request_id),
  );
  if (!document || !command.request_id) return null;
  const invoice = command.invoices.find((i) => i.file_id === document.id);
  const setInvoice = (next: InvoiceReview) =>
    change({
      invoices: [
        ...command.invoices.filter((i) => i.file_id !== document.id),
        next,
      ],
    });
  const patch = (id: string, value: Partial<InvoiceLine>) =>
    invoice &&
    setInvoice({
      ...invoice,
      lines: invoice.lines.map((l) => (l.id === id ? { ...l, ...value } : l)),
    });
  return (
    <fieldset className="invoice-editor" disabled={disabled}>
      <legend>Invoice composition · {document.name}</legend>
      <p>
        Check each position against its source. These rows describe the invoice;
        they never create contract obligations or bank transfers. Use positive
        amounts for discounts, credits and reflected payments.
      </p>
      {!invoice ? (
        <button
          onClick={() =>
            setInvoice({
              file_id: document.id,
              request_id: command.request_id!,
              complete: false,
              lines: document.invoice_proposals.map((p) => ({
                id: p.id,
                proposal_id: p.id,
                page: p.page,
                kind: p.kind,
                description: p.description,
                amount: p.amount,
                quantity: p.quantity,
                unit_price: p.unit_price,
                review: "unknown",
                cash_record_id: null,
              })),
            })
          }
        >
          Review invoice composition
        </button>
      ) : (
        <>
          {invoice.lines.map((line, index) => (
            <fieldset className="invoice-line" key={line.id}>
              <legend>Position {index + 1}</legend>
              <details>
                <summary>Original extraction & provenance</summary>
                <p>
                  {document.invoice_proposals.find(
                    (p) => p.id === line.proposal_id,
                  )?.original_text ??
                    "Manually added position; no extracted original is overwritten."}
                </p>
                <code>{line.id}</code>
              </details>
              <div className="guest-fields">
                <label>
                  Position meaning
                  <select
                    value={line.kind}
                    onChange={(e) =>
                      patch(line.id, { kind: e.target.value as LineKind })
                    }
                  >
                    {Object.entries(lineLabels).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Description
                  <input
                    value={line.description}
                    maxLength={600}
                    onChange={(e) =>
                      patch(line.id, { description: e.target.value })
                    }
                  />
                </label>
                <label>
                  Position amount (USD)
                  <input
                    inputMode="decimal"
                    value={line.amount ?? ""}
                    placeholder="Unknown / no amount"
                    onChange={(e) =>
                      patch(line.id, { amount: e.target.value || null })
                    }
                  />
                </label>
                <label>
                  Source page
                  <select
                    value={line.page}
                    onChange={(e) =>
                      patch(line.id, { page: Number(e.target.value) })
                    }
                  >
                    {document.pages.map((p) => (
                      <option key={p.number} value={p.number}>
                        {p.number}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Position review
                  <select
                    value={line.review}
                    onChange={(e) =>
                      patch(line.id, {
                        review: e.target.value as InvoiceLine["review"],
                      })
                    }
                  >
                    <option value="unknown">Unknown / not checked</option>
                    <option value="checked">Checked against source</option>
                    <option value="excluded">Excluded proposal</option>
                  </select>
                </label>
                {(line.kind === "credit" ||
                  line.kind === "reflected_payment") && (
                  <label>
                    Existing payment evidence
                    <select
                      value={line.cash_record_id ?? ""}
                      onChange={(e) =>
                        patch(line.id, {
                          cash_record_id: e.target.value || null,
                        })
                      }
                    >
                      <option value="">Unknown / no payment link</option>
                      {command.records
                        .filter((r) => r.kind === "payment")
                        .map((r) => (
                          <option key={r.id} value={r.id}>
                            {
                              state.project.documents
                                .flatMap((d) => d.candidates)
                                .find((c) => c.id === r.id)?.snippet
                            }{" "}
                            · {r.date}
                          </option>
                        ))}
                    </select>
                  </label>
                )}
              </div>
              <details>
                <summary>Quantity and unit price (only if stated)</summary>
                <label>
                  Quantity
                  <input
                    value={line.quantity ?? ""}
                    onChange={(e) =>
                      patch(line.id, { quantity: e.target.value || null })
                    }
                  />
                </label>
                <label>
                  Unit price (USD)
                  <input
                    value={line.unit_price ?? ""}
                    onChange={(e) =>
                      patch(line.id, { unit_price: e.target.value || null })
                    }
                  />
                </label>
              </details>
              <button
                type="button"
                onClick={() => void openSource(document.id, line.page)}
              >
                View position source
              </button>
            </fieldset>
          ))}
          <button
            onClick={() =>
              setInvoice({
                ...invoice,
                lines: [
                  ...invoice.lines,
                  {
                    id: `manual-${crypto.randomUUID()}`,
                    proposal_id: null,
                    page: document.pages[0]?.number ?? 1,
                    kind: "unknown",
                    description: "",
                    amount: null,
                    quantity: null,
                    unit_price: null,
                    review: "unknown",
                    cash_record_id: null,
                  },
                ],
              })
            }
          >
            Add missed position
          </button>
          <label className="guest-consent">
            <input
              type="checkbox"
              checked={invoice.complete}
              onChange={(e) =>
                setInvoice({ ...invoice, complete: e.target.checked })
              }
            />
            I checked the complete invoice composition against the original.
          </label>
          <p>
            Save the financial review, or use Run recheck below. Missing rows
            and unexplained differences remain visible; no balancing row is
            invented.
          </p>
        </>
      )}
    </fieldset>
  );
}
