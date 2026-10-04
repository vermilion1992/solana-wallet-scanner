import type { HistoricalSourceDecision } from "./types";

export function HistoricalSourceNotice({ decision }: {
  decision?: HistoricalSourceDecision;
}) {
  if (decision?.version !== "historical-source-capability-v1" ||
    decision.state !== "UNSUPPORTED_CURRENT_SOURCE") return null;
  return <aside className="report-note" data-historical-source-decision={decision.state} role="note">
    <strong>Full wallet qualification is unavailable with the current sources.</strong>
    <p>These sources do not establish complete historical ownership and account lifecycle coverage. Independently supported fees and selected trades can still be reported.</p>
    <p>A paid plan alone does not prove complete coverage. Partial observations remain separate from wallet-wide profit and copy-trading qualification.</p>
    {typeof decision.reason === "string" && decision.reason && <details>
      <summary>Why complete coverage remains unavailable</summary>
      <p>{decision.reason}</p>
    </details>}
  </aside>;
}
