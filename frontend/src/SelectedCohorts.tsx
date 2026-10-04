import { ArrowUpRight } from "lucide-react";
import { Badge, SectionHeading } from "./components";
import { dateTime, decimal, shorten } from "./format";
import type { Report } from "./types";

type Facts = Record<string, unknown>;
const facts = (value: unknown): Facts | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Facts
    : undefined;
const candidateCount = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined;
const amount = (value: unknown) =>
  typeof value === "string" && value.length <= 512 && /^-?\d+(?:\.\d+)?$/.test(value)
    ? value
    : undefined;
const instant = (value: unknown) => {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))
    return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

export function selectedCohortFreshness(
  report: Report,
  currentWalletMethod?: string,
  currentAccountingMethod?: string,
  historyCurrent = false,
) {
  if (!currentWalletMethod || !currentAccountingMethod) return "method_unavailable";
  if (report.source !== "live" || report.preview) return "rebuild_required";
  const wallet = facts(report.coverage.wallet_evidence);
  const saved = report.wallet_assessment;
  if (!wallet || !saved || !saved.saved_methodology || saved.state === "missing")
    return "missing";
  const research = facts(report.research);
  const researchAssessment = report.research_assessment;
  if (!research || !researchAssessment || !researchAssessment.saved_methodology || researchAssessment.state === "missing")
    return "missing";
  return historyCurrent && report.methodology === currentAccountingMethod &&
    saved.state === "current" && saved.saved_methodology === currentWalletMethod &&
    saved.current_methodology === currentWalletMethod && wallet.version === currentWalletMethod &&
    researchAssessment.state === "current" && typeof researchAssessment.current_methodology === "string" &&
    researchAssessment.saved_methodology === researchAssessment.current_methodology &&
    research.version === researchAssessment.current_methodology
    ? "current"
    : "rebuild_required";
}

function SourceLinks({ value, showEvidence }: {
  value: unknown;
  showEvidence: (hash: string) => void;
}) {
  const hashes = Array.isArray(value)
    ? [...new Set(value.filter((hash): hash is string =>
      typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash)))]
    : [];
  if (!hashes.length) return null;
  return <div className="selected-cohort-sources">
    {hashes.slice(0, 6).map((hash) => <button
      type="button"
      className="text-button mono"
      key={hash}
      onClick={() => showEvidence(hash)}
    >Source {shorten(hash, 5)} <ArrowUpRight size={12} /></button>)}
    {hashes.length > 6 && <small>All source references remain in the JSON export.</small>}
  </div>;
}

function ObservationValue({ value, known, unit }: {
  value: unknown;
  known: boolean;
  unit?: string;
}) {
  const parsed = known ? amount(value) : undefined;
  return <strong title={parsed}>
    {parsed === undefined ? "Unknown" : <>{decimal(parsed, unit === "SOL" ? 9 : 2)}{unit && <small> {unit}</small>}</>}
  </strong>;
}

function State({ value, current, title }: {
  value: unknown;
  current: boolean;
  title: string;
}) {
  const known = current && value === "PASS";
  return <span className="selected-cohort-state">
    {title}: <Badge value={known ? "pass" : "unknown"}>{known ? "Supported" : "Unknown"}</Badge>
  </span>;
}

function SelectedInterval({ value, name, current, start, end, showEvidence }: {
  value: unknown;
  name: string;
  current: boolean;
  start?: number;
  end?: number;
  showEvidence: (hash: string) => void;
}) {
  const interval = facts(value);
  const intervalCurrent = current && start !== undefined && end !== undefined && start < end &&
    instant(interval?.start) === start && instant(interval?.end) === end;
  const closed = facts(interval?.closed_cohort);
  const disposed = facts(interval?.disposed_units);
  const closedCount = candidateCount(closed?.candidate_count);
  const saleCount = candidateCount(disposed?.candidate_sale_count);
  const populationKnown = intervalCurrent && closed?.population_state === "PASS" && closedCount !== undefined;
  const moneyKnown = populationKnown && closedCount! > 0 && closed?.monetary_state === "PASS";
  const timingKnown = populationKnown && closedCount! > 0 && closed?.timing_state === "PASS";
  const disposalKnown = intervalCurrent && saleCount !== undefined && saleCount > 0 &&
    disposed?.quantity_state === "PASS" && disposed?.monetary_state === "PASS";
  const disposalBasisKnown = intervalCurrent && saleCount !== undefined && saleCount > 0 &&
    disposed?.quantity_state === "PASS" && disposed?.cost_basis_state === "PASS";
  return <details className="selected-cohort-window" data-selected-cohort-window={name}>
    <summary>{name}</summary>
    <p className="small-note">
      {instant(interval?.start) !== undefined && instant(interval?.end) !== undefined
        ? `${dateTime(interval?.start as string)} → ${dateTime(interval?.end as string)} UTC`
        : "Interval boundaries are unavailable."}
    </p>
    {current && !intervalCurrent && <p className="small-note">The saved boundaries do not match this interval. Its supported values remain unknown.</p>}
    <h3>Completed holdings in selected records</h3>
    <p className="small-note">
      {closedCount === undefined ? "Candidate count unknown" : `${closedCount.toLocaleString()} observed candidates`}
      {closedCount === 0 && " · No completed holding values are defined for an empty cohort."}
    </p>
    <div className="selected-cohort-states">
      <State title="Selected cohort" value={closed?.population_state} current={populationKnown} />
      <State title="Costs" value={closed?.monetary_state} current={moneyKnown} />
      <State title="Holding clocks" value={closed?.timing_state} current={timingKnown} />
    </div>
    <div className="selected-cohort-values">
      {[
        ["Conditional closed-holding P&L", "conditional_profit_sol", moneyKnown, "SOL"],
        ["Conditional win rate", "conditional_win_rate_pct", moneyKnown, "%"],
        ["Conditional median ROI", "conditional_median_roi_pct", moneyKnown, "%"],
        ["Median completed hold", "conditional_median_hold_hours", timingKnown, "hours"],
        ["Median first sale", "conditional_first_sale_hours", timingKnown, "hours"],
        ["Median 50% exit", "conditional_exit_50_hours", timingKnown, "hours"],
        ["Median 90% exit", "conditional_exit_90_hours", timingKnown, "hours"],
      ].map(([title, key, known, unit]) => <div key={String(key)}>
        <span>{String(title)}</span>
        <ObservationValue value={closed?.[String(key)]} known={known === true} unit={String(unit)} />
      </div>)}
    </div>
    <SourceLinks value={closed?.evidence} showEvidence={showEvidence} />
    <h3>Disposed units in selected records</h3>
    <p className="small-note">
      {saleCount === undefined ? "Sale count unknown" : `${saleCount.toLocaleString()} observed sales`}
      . This view includes partial exits. It excludes unallocated overhead and does not establish wallet-wide profit.
    </p>
    <div className="selected-cohort-states">
      <State title="Quantities" value={disposed?.quantity_state} current={intervalCurrent && saleCount !== undefined} />
      <State title="Costs" value={disposed?.monetary_state} current={disposalKnown} />
    </div>
    <div className="selected-cohort-values">
      <div><span>Conditional disposal P&L</span><ObservationValue value={disposed?.conditional_profit_sol} known={disposalKnown} unit="SOL" /></div>
      <div><span>Matched acquisition basis</span><ObservationValue value={disposed?.conditional_matched_basis_sol} known={disposalBasisKnown} unit="SOL" /></div>
    </div>
    <SourceLinks value={disposed?.evidence} showEvidence={showEvidence} />
  </details>;
}

export function SelectedCohortSection({ report, currentWalletMethod, currentAccountingMethod,
  historyCurrent = false, showEvidence }: {
  report: Report;
  currentWalletMethod?: string;
  currentAccountingMethod?: string;
  historyCurrent?: boolean;
  showEvidence: (hash: string) => void;
}) {
  if (report.source !== "live" || report.preview) return null;
  const wallet = facts(report.coverage.wallet_evidence);
  const accounting = facts(wallet?.query_accounting);
  const observation = facts(accounting?.selected_cohort_observations);
  if (!observation) return null;
  const freshness = selectedCohortFreshness(report, currentWalletMethod, currentAccountingMethod, historyCurrent);
  const current = freshness === "current" && observation.version === "selected-cohort-observations-v2";
  const intervals = facts(observation.intervals);
  const end = instant(report.window.end);
  const stock = facts(observation.open_stock);
  const openCount = candidateCount(stock?.candidate_count);
  const lots = Array.isArray(stock?.lots) ? stock.lots.flatMap((lot) => {
    const row = facts(lot);
    return row ? [row] : [];
  }) : [];
  const stockCurrent = current && end !== undefined && instant(stock?.at) === end &&
    openCount !== undefined && openCount === lots.length;
  const stockKnown = stockCurrent && openCount! > 0 &&
    stock?.quantity_state === "PASS" && stock?.cost_basis_state === "PASS";
  return <section className="panel selected-cohorts" data-selected-cohort-freshness={current ? "current" : freshness === "current" ? "rebuild_required" : freshness}>
    <SectionHeading title="Selected holding observations" subtitle="Completed holdings, disposed units and remaining stock have separate evidence requirements." action={<Badge value="partial">Selected records</Badge>} />
    <p className="observed-research-note">
      These conditional observations describe selected records only. They do not establish complete wallet history, eligible assets, wallet-wide profit or a copy-trading recommendation.
    </p>
    {!current && <p className="report-note" role="status">
      Saved observations require a rebuild before current supported values can be shown. Original values and sources remain in the saved report and JSON export.
    </p>}
    <details className="selected-cohort-details">
      <summary>Inspect selected holdings by interval</summary>
      <div className="selected-cohort-windows">
        {[["report_period", "Reporting period"], ["four_weeks", "Independent 28 days"], ["verification_90d", "Independent 90 days"]].map(([key, name]) =>
          <SelectedInterval key={key} name={name} value={intervals?.[key]} current={current}
            start={key === "report_period" ? instant(report.window.start) : end === undefined ? undefined : end - (key === "four_weeks" ? 28 : 90) * 86400000}
            end={end} showEvidence={showEvidence} />)}
      </div>
      <details className="selected-cohort-window" data-selected-open-stock>
        <summary>Remaining selected holdings</summary>
        <p className="small-note">
          {openCount === undefined ? "Open-holding count unknown" : `${openCount.toLocaleString()} observed open holdings`}
          {instant(stock?.at) !== undefined && ` at ${dateTime(stock?.at as string)} UTC`}.
          Acquisition cost and market value are separate. A missing valuation does not erase supported cost basis.
        </p>
        <div className="selected-cohort-states">
          <State title="Quantities" value={stock?.quantity_state} current={stockCurrent && openCount !== undefined} />
          <State title="Cost basis" value={stock?.cost_basis_state} current={stockKnown} />
          <State title="Market value" value={stock?.valuation_state} current={stockCurrent} />
        </div>
        <div className="selected-cohort-values">
          <div><span>Conditional remaining basis</span><ObservationValue value={stock?.conditional_remaining_basis_sol} known={stockKnown} unit="SOL" /></div>
          <div><span>Closing market value</span><ObservationValue value={stock?.closing_value_sol} known={stockCurrent && stock?.valuation_state === "PASS" && openCount !== undefined} unit="SOL" /></div>
        </div>
        <SourceLinks value={stock?.evidence} showEvidence={showEvidence} />
        {lots.slice(0, 10).map((lot, index) => <div className="selected-open-lot" key={`${typeof lot.id === "string" ? lot.id : index}`}>
          <span className="mono">{typeof lot.mint === "string" ? shorten(lot.mint) : "Mint unavailable"}</span>
          <span>Remaining raw units: <strong>{stockCurrent && lot.quantity_state === "PASS" && typeof lot.remaining_raw === "string" && lot.remaining_raw.length <= 512 && /^\d+$/.test(lot.remaining_raw) ? lot.remaining_raw : "Unknown"}</strong></span>
          <span>Remaining basis: <ObservationValue value={lot.conditional_remaining_basis_sol} known={stockCurrent && lot.quantity_state === "PASS" && lot.cost_basis_state === "PASS"} unit="SOL" /></span>
          <SourceLinks value={lot.evidence} showEvidence={showEvidence} />
        </div>)}
        {lots.length > 10 && <p className="small-note">Showing 10 selected holdings. Every holding remains in the JSON export.</p>}
      </details>
    </details>
  </section>;
}
