export type Answer = "contractor" | "other" | "unknown";
export type Action = {
  kind: "assign_recipient";
  record_id: string;
  answer: Answer;
};
export type Scenario = { id: string; title: string; description: string };
export type Trace = {
  label: string;
  amount_cents: number | null;
  formula: string;
  record_ids: string[];
  source_ids: string[];
};
export type RecordRow = {
  id: string;
  kind: string;
  amount_cents: number | null;
  effective_date: string;
  evidence_refs: string[];
  origin: string;
  basis?: string;
};
export type Disposition = {
  record: RecordRow;
  reason: string;
  evidence_refs: string[];
  canonical_record_id: string | null;
  effective_contractor_id: string | null;
  effective_semantic_review: string;
  decision_ids: string[];
};
export type Demo = {
  synthetic: true;
  persistence: "none";
  scenario: Scenario;
  history: {
    records: RecordRow[];
    sources: { id: string; origin: string }[];
    cutoff_date: string;
  };
  source_contents: { source_id: string; title: string; excerpt: string }[];
  record_titles: Record<string, string>;
  conditions: {
    due_date: string | null;
    condition_text: string | null;
    satisfaction: "unknown" | "user_reported";
    evidence_refs: string[];
  };
  allowed_actions: {
    kind: "assign_recipient";
    record_id: string;
    label: string;
    answers: Answer[];
  }[];
  actions: Action[];
  explanation: string;
  normalization: {
    included: Disposition[];
    excluded: Disposition[];
    incomplete: boolean;
    incomplete_metrics: string[];
    questions: {
      id: string;
      code: string;
      message: string;
      record_ids: string[];
      affects: string[];
    }[];
  };
  calculation: {
    requested_now_cents: number | null;
    remaining_commitment_cents: number | null;
    input_fingerprint: string;
    charge_balances: { charge_id: string; remaining_cents: number }[];
  };
  traces: Record<string, Trace>;
};
