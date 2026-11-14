export type LineKind =
  | "work"
  | "charge"
  | "discount"
  | "credit"
  | "reflected_payment"
  | "condition"
  | "unknown";
export type InvoiceLine = {
  id: string;
  proposal_id: string | null;
  page: number;
  kind: LineKind;
  description: string;
  amount: string | null;
  quantity: string | null;
  unit_price: string | null;
  review: "checked" | "unknown" | "excluded";
  cash_record_id: string | null;
};
export type Proposal = Omit<
  InvoiceLine,
  "proposal_id" | "review" | "cash_record_id"
> & {
  original_text: string;
  origin: string;
  source_key: string | null;
};
export type InvoiceReview = {
  file_id: string;
  request_id: string;
  complete: boolean;
  lines: InvoiceLine[];
};
export type CheckedLine = {
  value: InvoiceLine;
  amount_cents: number | null;
  signed_cents: number | null;
  source_ref: string;
  review_source_ref: string;
  origin: string;
  original_text: string | null;
  cash_event_id: string | null;
  cash_evidence_refs: string[];
};
export type Composition = {
  file_id: string;
  request_id: string;
  requested_cents: number | null;
  accounted_cents: number;
  unexplained_cents: number | null;
  complete: boolean;
  lines: CheckedLine[];
  issues: string[];
};
export const lineLabels: Record<LineKind, string> = {
  work: "Work",
  charge: "Charge",
  discount: "Discount",
  credit: "Credit / allowance",
  reflected_payment: "Payment reflected in invoice",
  condition: "Payment condition",
  unknown: "Unknown meaning",
};
export const money = (value: number | null) =>
  value === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(value / 100);
