type ObservedCard = {
  observation: { active?: boolean; financial_revision?: number };
  evidence_state: string;
};

export function presenceLabel(card: ObservedCard) {
  if (card.observation.active === true)
    return "Active in this recorded calculation";
  if (card.observation.active === false)
    return "Historical — absent from this recorded calculation";
  return "Presence not recorded in this version";
}

export default function QuestionPresence({ card }: { card: ObservedCard }) {
  return (
    <div
      className="question-presence"
      data-question-presence={
        card.observation.active === true
          ? "active"
          : card.observation.active === false
            ? "historical"
            : "unknown"
      }
    >
      <strong>{presenceLabel(card)}</strong>
      {card.observation.financial_revision !== undefined && (
        <p>
          Recorded financial revision: {card.observation.financial_revision}.
        </p>
      )}
      {card.observation.active === false && (
        <p>
          This is retained history, not the current processing or eligibility
          status. Disappearance does not prove resolution or close a financial
          question.
        </p>
      )}
      {card.evidence_state === "needs_recheck" && (
        <p>
          Previous conclusion requires reassessment. This is separate from
          whether the question is active.
        </p>
      )}
    </div>
  );
}
