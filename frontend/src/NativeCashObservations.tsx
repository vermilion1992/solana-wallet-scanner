import { ArrowUpRight } from "lucide-react";
import { Badge, SectionHeading } from "./components";
import { dateTime, shorten } from "./format";
import type { Report } from "./types";

type Facts = Record<string, unknown>;
const facts = (value: unknown): Facts | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Facts : undefined;
const sources = (value: unknown): string[] => Array.isArray(value)
  ? [...new Set(value.filter((hash): hash is string =>
    typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash)))] : [];
const hasSourceReferences = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length > 0 &&
  value.every((hash) => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash));
const instant = (value: unknown) => {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))
    return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

// Aggregate gross movements can exceed a single account's u64 balance. Keep
// integer text exact and bounded rather than converting lamports to a float.
export function nativeCashAmount(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 512 || !/^\d+$/.test(value)) return undefined;
  const digits = BigInt(value).toString().padStart(10, "0");
  const fraction = digits.slice(-9).replace(/0+$/, "");
  return `${digits.slice(0, -9)}${fraction ? `.${fraction}` : ""}`;
}

export function NativeCashObservations({ report, currentWalletMethod, historyCurrent, showEvidence }: {
  report: Report;
  currentWalletMethod?: string;
  historyCurrent: boolean;
  showEvidence: (hash: string) => void;
}) {
  if (report.source !== "live" || report.preview) return null;
  const wallet = facts(report.coverage.wallet_evidence);
  const observation = facts(wallet?.native_cash_observations);
  if (!observation) return null;
  const assessment = report.wallet_assessment;
  const current = Boolean(currentWalletMethod && historyCurrent && wallet?.version === currentWalletMethod &&
    assessment?.state === "current" && assessment.saved_methodology === currentWalletMethod &&
    assessment.current_methodology === currentWalletMethod && observation.version === "native-cash-observations-v1");
  const intervals = facts(observation.intervals);
  const end = instant(report.window.end);
  return <section className="panel" data-native-cash-observations={current ? "current" : "rebuild_required"}>
    <SectionHeading title="Observed SOL transfers"
      subtitle="Gross incoming and outgoing System transfers at the wallet address, in selected archived records."
      action={<Badge value="partial">Selected records</Badge>} />
    <p className="small-note">The economic role of these movements remains unknown. They do not establish capital deposits, withdrawals, profit or complete wallet history.</p>
    <p className="small-note">These transfer totals do not measure account creation or rent costs, SOL wrapping, or token-account balances. Those need separate evidence and accounting.</p>
    {!current && <p className="report-note" role="status">Rebuild from saved records to use the current interpretation. Original values and sources remain in the saved report and JSON export.</p>}
    <details className="selected-cohort-details">
      <summary>Inspect SOL movements by interval</summary>
      <div className="selected-cohort-windows">
        {[["report_period", "Reporting period"], ["four_weeks", "Independent 28 days"], ["verification_90d", "Independent 90 days"]].map(([key, name]) => {
          const interval = facts(intervals?.[key]);
          const check = facts(interval?.check);
          const start = key === "report_period" ? instant(report.window.start)
            : end === undefined ? undefined : end - (key === "four_weeks" ? 28 : 90) * 86400000;
          const matched = start !== undefined && end !== undefined && start < end &&
            instant(interval?.start) === start && instant(interval?.end) === end;
          const known = current && matched && check?.state === "PASS" && hasSourceReferences(check.evidence);
          return <div className="selected-cohort-window" key={key} data-native-cash-window={name}>
            <h3>{name}</h3>
            <p className="small-note">{instant(interval?.start) !== undefined && instant(interval?.end) !== undefined
              ? `${dateTime(interval?.start as string)} → ${dateTime(interval?.end as string)} UTC`
              : "Interval boundaries are unavailable."}</p>
            {current && !matched && <p className="small-note">The saved boundaries do not match this interval. Its supported values remain unknown.</p>}
            <div className="selected-cohort-values">
              {[["Gross incoming SOL", "gross_in_lamports"], ["Gross outgoing SOL", "gross_out_lamports"]].map(([title, field]) => {
                const amount = known ? nativeCashAmount(interval?.[field]) : undefined;
                return <div key={field}><span>{title}</span>
                  <strong style={{ overflowWrap: "anywhere" }} title={amount}>
                    {amount === undefined ? "Unknown" : <>{amount}<small> SOL</small></>}
                  </strong>
                </div>;
              })}
            </div>
            <div className="selected-cohort-sources">{sources(check?.evidence).slice(0, 6).map((hash) => <button
              type="button" className="text-button mono" key={hash} onClick={() => showEvidence(hash)}
            >Source {shorten(hash, 5)} <ArrowUpRight size={12} /></button>)}</div>
            {typeof check?.reason === "string" && <p className="small-note">{check.reason}</p>}
            {sources(check?.evidence).length > 6 && <p className="small-note">All source references remain in the JSON export.</p>}
          </div>;
        })}
      </div>
    </details>
  </section>;
}
