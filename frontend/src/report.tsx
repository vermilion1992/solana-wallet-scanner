import { useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Copy,
  Download,
  FileJson,
  FlaskConical,
  GitCompareArrows,
  RotateCcw,
  Search,
  ShieldCheck,
  Star,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import type { Actions } from "./App";
import type {
  AccountPositionEvidence,
  PositionAssessment,
  Report,
  SourceConsistency,
  SourceConsistencyCheck,
  SourceConsistencyGroup,
  SourceSet,
} from "./types";
import {
  Badge,
  Button,
  Empty,
  MetricValue,
  SectionHeading,
  WindowLabel,
  metricDefinitions,
} from "./components";
import { count, date, dateTime, decimal, label, shorten } from "./format";
import { samePresetSnapshot } from "./Discovery";
import { reportDisplay } from "./api";
import { SelectedCohortSection } from "./SelectedCohorts";
import { InventoryObservations } from "./InventoryObservations";
import { NativeCashObservations } from "./NativeCashObservations";
import { HistoricalSourceNotice } from "./HistoricalSourceNotice";

export function subsetHoldText(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return "unknown";
  const hours = seconds / 3600;
  if (Number.isInteger(hours) && hours > 0) return `${hours} hours (${seconds} seconds)`;
  return `${seconds} seconds`;
}

export function subsetWorksheetVisible(report: Pick<Report, "worksheet" | "material_exit" | "observations" | "g3_status">) {
  return Boolean(report.worksheet || report.material_exit || report.observations?.length || report.g3_status);
}

export function SubsetWorksheetPanel({ report }: { report: Report }) {
  if (!subsetWorksheetVisible(report)) return null;
  const worksheet = report.worksheet;
  const independent = report.independent_worksheet;
  const reconciliation = report.worksheet_reconciliation;
  const exit = report.material_exit;
  const settlement = worksheet?.settlement_asset || (worksheet?.total_profit_usdc ? "USDC" : "SOL");
  const sales = settlement === "USDC" ? (worksheet?.sale_net_profit_usdc || []) : (worksheet?.sale_net_profit_sol || []);
  const observations = report.observations || [];
  const trades = (report.events || []).filter((row) => row.kind === "buy" || row.kind === "sell");
  const closedPositions = (report.positions || []).filter((row) => row.status === "closed" || row.end);
  const productionPnl = settlement === "USDC" ? worksheet?.total_profit_usdc : worksheet?.total_profit_sol;
  const independentPnl = settlement === "USDC"
    ? (independent?.total_profit_usdc || worksheet?.total_profit_usdc)
    : (independent?.total_profit_sol || worksheet?.total_profit_sol);
  return (
    <section className="panel subset-worksheet" data-subset-worksheet="independent">
      <SectionHeading
        title="Reconstructed subset / independent worksheet"
        subtitle="Supported closed trades and unresolved observations. Not a wallet-wide MATCH. Below-G3 reports stay visible."
      />
      <p className="subset-worksheet-note">
        Independently reconciled subset from reconstructed buy/sell events.
        Standard report cards stay on full-wallet evidence and may remain unknown.
        Policy remains {report.policy || "UNRESOLVED"}.
        {report.g3_status ? ` G3 status: ${report.g3_status}.` : ""}
        {report.source_integrity?.status ? ` Source integrity: ${report.source_integrity.status}.` : ""}
        {report.research?.supported_swaps != null ? ` Supported swaps: ${report.research.supported_swaps}.` : ""}
      </p>
      <div className="subset-worksheet-metrics">
        <div>
          <span>Production subset P&amp;L</span>
          <strong>{productionPnl ? `${decimal(productionPnl, 4)} ${settlement}` : "unknown"}</strong>
        </div>
        <div>
          <span>Independent subset P&amp;L</span>
          <strong>{independentPnl ? `${decimal(independentPnl, 4)} ${settlement}` : "unknown"}</strong>
        </div>
        <div>
          <span>Material-exit t90 (from open)</span>
          <strong>{exit?.exit_90_seconds != null ? `${exit.exit_90_seconds} seconds` : "unknown"}</strong>
        </div>
        <div>
          <span>Position hold</span>
          <strong>{subsetHoldText(exit?.final_hold_seconds)}</strong>
        </div>
      </div>
      {exit?.method_version && (
        <p className="subset-worksheet-note" data-material-exit-version={exit.method_version}>
          Exit timings are opening-relative ({exit.method_version}
          {exit.aggregation_method ? ` · ${exit.aggregation_method}` : ""}
          {exit.sample_count != null ? ` n=${exit.sample_count}` : ""}).
          {exit.first_sale_seconds != null ? ` First sale ${exit.first_sale_seconds}s.` : ""}
          {exit.quantity_weighted_exit_seconds != null ? ` Quantity-weighted exit time ${exit.quantity_weighted_exit_seconds}s (not lot holding time).` : ""}
        </p>
      )}
      {reconciliation?.status && (
        <p className="subset-worksheet-note" data-worksheet-reconciliation={reconciliation.status}>
          Worksheet reconciliation: {reconciliation.status}
          {reconciliation.difference_usdc != null ? ` · difference ${reconciliation.difference_usdc} USDC` : ""}
          {reconciliation.difference_sol != null ? ` · difference ${reconciliation.difference_sol} SOL` : ""}
          {reconciliation.note ? ` — ${reconciliation.note}` : ""}
        </p>
      )}
      {!!(report.analytics as { trades?: unknown[] } | undefined)?.trades?.length && (
        <table className="subset-worksheet-trades" data-subset-trades={String(((report.analytics as { trades?: unknown[] }).trades || []).length)} data-analytics-trades="true">
          <caption>Supported subset trades ({((report.analytics as { trades?: unknown[] }).trades || []).length})</caption>
          <thead>
            <tr>
              <th>Side</th>
              <th>Token</th>
              <th>Qty</th>
              <th>Settlement</th>
              <th>Proceeds / cost</th>
              <th>Allocated basis</th>
              <th>Known P&amp;L</th>
              <th>Unmatched qty</th>
              <th>Reason</th>
              <th>Tx</th>
            </tr>
          </thead>
          <tbody>
            {((report.analytics as { trades?: Record<string, unknown>[] }).trades || []).map((row, index) => (
              <tr key={`${String(row.tx_ref || index)}-${index}`} data-trade-scope={String(row.result_scope || report.result_scope || "conditional_on_captured_inventory")}>
                <td>{String(row.side || "")}</td>
                <td>{shorten(String(row.token || ""), 6)}</td>
                <td>{row.quantity != null ? String(row.quantity) : "unknown"}</td>
                <td>{String(row.settlement_asset || "")}</td>
                <td>{row.proceeds_or_cost != null ? `${decimal(String(row.proceeds_or_cost), 4)} ${String(row.settlement_asset || "")}` : "unknown"}</td>
                <td>{row.allocated_basis != null ? `${decimal(String(row.allocated_basis), 4)} ${String(row.settlement_asset || "")}` : row.reconciliation_or_exclusion === "unresolved_basis" ? "unknown basis" : "—"}</td>
                <td>{row.known_cost_pnl != null ? `${decimal(String(row.known_cost_pnl), 4)} ${String(row.settlement_asset || "")}` : row.reconciliation_or_exclusion === "unresolved_basis" ? "unresolved" : "—"}</td>
                <td>{row.unmatched_quantity != null && String(row.unmatched_quantity) !== "" ? String(row.unmatched_quantity) : "—"}</td>
                <td>{String(row.reconciliation_or_exclusion || "—")}{row.whole_sale_pnl_resolved === false && row.side === "sell" ? " · whole-sale unresolved" : ""}</td>
                <td>{row.tx_ref ? shorten(String(row.tx_ref), 6) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!!trades.length && !(report.analytics as { trades?: unknown[] } | undefined)?.trades?.length && (
        <table className="subset-worksheet-trades" data-subset-trades={String(trades.length)}>
          <caption>Supported subset trades ({trades.length})</caption>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Mint</th>
              <th>Amount</th>
              <th>Fee</th>
              <th>Signature</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((row, index) => (
              <tr key={`${String(row.signature || index)}-${index}`}>
                <td>{String(row.kind)}</td>
                <td>{shorten(String(row.mint || ""), 6)}</td>
                <td>{row.amount_usdc != null ? `${decimal(String(row.amount_usdc), 4)} USDC` : row.amount_sol != null ? `${decimal(String(row.amount_sol), 4)} SOL` : "unknown"}</td>
                <td>{row.fee_sol != null ? `${decimal(String(row.fee_sol), 9)} SOL` : "unknown"}</td>
                <td>{row.signature ? shorten(String(row.signature), 6) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!!closedPositions.length && (
        <p className="subset-worksheet-sales" data-subset-positions={String(closedPositions.length)}>
          Declared completed positions {closedPositions.length}
          {closedPositions[0]?.hold_hours != null ? ` · hold ${closedPositions[0].hold_hours} hours` : ""}
          {closedPositions[0]?.pnl_sol != null ? ` · position P&L ${decimal(String(closedPositions[0].pnl_sol), 4)} SOL` : ""}
        </p>
      )}
      {!!sales.length && (
        <p className="subset-worksheet-sales">
          Sale nets {sales.map((value) => `${decimal(value, 4)} ${settlement}`).join(" · ")}
          {settlement === "USDC" && worksheet?.sale_fifo_basis_usdc?.length
            ? ` · FIFO basis ${worksheet.sale_fifo_basis_usdc.map((value) => `${decimal(value, 4)} USDC`).join(" · ")}`
            : ""}
          {settlement !== "USDC" && worksheet?.sale_fifo_basis_sol?.length
            ? ` · FIFO basis ${worksheet.sale_fifo_basis_sol.map((value) => `${decimal(value, 4)} SOL`).join(" · ")}`
            : ""}
        </p>
      )}
      {!!observations.length && (
        <ul className="subset-worksheet-observations" data-g3-observations="unresolved">
          {observations.slice(0, 12).map((item, index) => (
            <li key={`${item.kind || "obs"}-${index}`}>
              {item.kind || "observation"}
              {item.reason ? `: ${item.reason}` : ""}
              {item.detail ? ` — ${item.detail}` : ""}
              {item.signature ? ` (${item.signature.slice(0, 8)}…)` : ""}
            </li>
          ))}
        </ul>
      )}
      <ResearchProfilePanel report={report} />
    </section>
  );
}

function funnelState(funnel: Record<string, unknown> | null | undefined, key: string) {
  const stage = funnel?.[key];
  if (!stage || typeof stage !== "object") return "unknown";
  return String((stage as { state?: string }).state || "unknown");
}

export function ResearchProfilePanel({ report }: { report: Report }) {
  const profile = report.research_profile || {};
  const funnel = report.funnel || {};
  if (!report.research_profile && !report.funnel) return null;
  const market = (profile.market_vs_rewards || {}) as Record<string, unknown>;
  return (
    <div className="research-profile" data-research-profile="local">
      <SectionHeading title="Research profile" subtitle="Local scoped metrics. Unset thresholds do not pass. Not safe to copy." />
      <div className="research-metrics mass-search-funnel">
        <div>
          <span>Funnel A</span>
          <strong>{funnelState(funnel, "A")}</strong>
          <small>worth investigating</small>
        </div>
        <div>
          <span>Funnel B</span>
          <strong>{funnelState(funnel, "B")}</strong>
          <small>evidence establishes results</small>
        </div>
        <div>
          <span>Funnel C</span>
          <strong>{funnelState(funnel, "C")}</strong>
          <small>meets research criteria</small>
        </div>
        <div>
          <span>Scoped P&amp;L</span>
          <strong>{profile.scoped_pnl ? `${decimal(String(profile.scoped_pnl), 4)} ${String(profile.scoped_pnl_unit || "")}` : "unknown"}</strong>
        </div>
      </div>
      <p className="subset-worksheet-note">
        Completed known-cost {String(profile.completed_known_cost_positions ?? 0)}
        {profile.hold_t90_seconds != null ? ` · t90 ${String(profile.hold_t90_seconds)}s` : ""}
        {profile.final_hold_seconds != null ? ` · hold ${String(profile.final_hold_seconds)}s` : ""}
        {profile.unresolved_basis_sales != null ? ` · unresolved basis ${String(profile.unresolved_basis_sales)}` : ""}
        {` · market ${String(market.market_swaps ?? 0)} / holder-fee ${String(market.holder_fee_distributions ?? 0)}`}
        . Rewards and fees are not profitability. PRODUCT_READY remains false.
      </p>
      <p className="subset-worksheet-note" data-report-provenance="true">
        Provenance {report.corpus_kind || "unknown corpus"}
        {report.capture_sha256 ? ` · capture ${String(report.capture_sha256).slice(0, 12)}` : ""}
        {report.analysis_cache_key ? ` · analysis ${String(report.analysis_cache_key).slice(0, 12)}` : ""}
        {report.window?.start ? ` · window ${String(report.window.start)} → ${String(report.window.end || "")}` : ""}
        {` · visible_report ${report.visible_report === true ? "true" : report.visible_report === false ? "false" : "unknown"}`}
        . Reopened reports keep this capture and window; they are not a later live refresh.
      </p>
      <p className="subset-worksheet-note" data-result-scope="true">
        Results are conditional on captured inventory. A positive matched trade never qualifies the account.
        {(() => {
          const evidence = (profile.evidence_class || {}) as { position?: { label?: string }; account?: { label?: string } };
          return `${evidence.position?.label ? ` Position class: ${evidence.position.label}.` : ""}${evidence.account?.label ? ` Account class: ${evidence.account.label}.` : ""}`;
        })()}
      </p>
      {!!report.analytics && (
        <div className="research-profile-analytics" data-wallet-analytics="true">
          {(() => {
            const analytics = report.analytics as Record<string, unknown>;
            const win = (analytics.win_rate || {}) as Record<string, unknown>;
            const hold = (analytics.median_hold || {}) as Record<string, unknown>;
            const period = (analytics.captured_period || {}) as Record<string, unknown>;
            const scope = (analytics.scope || {}) as Record<string, unknown>;
            const pnl = (analytics.known_cost_realised_pnl || {}) as Record<string, unknown>;
            return (
              <>
                <p data-win-rate="true">
                  Win rate {win.rate != null ? String(win.rate) : "not evaluated"}
                  {` (${String(win.wins ?? 0)} / ${String(win.denominator ?? 0)} completed known-cost positions)`}
                </p>
                <p data-median-hold="true">
                  Median hold {hold.seconds != null ? `${String(hold.seconds)}s` : "unknown"}
                  {` · n=${String(hold.sample_count ?? 0)}`}
                  {hold.n_equals_one_disclosed ? " · n=1 is one completed position, not a wallet-wide median" : ""}
                  {` · ${String(hold.method_version || "material-exit-v2")}`}
                </p>
                <p data-captured-period="true">
                  Captured period {String(period.start || "unknown")} → {String(period.end || "unknown")}.
                  {` Scope: ${String(scope.population || "supported_closed_subset")}.`}
                  {" Coverage of captured transactions is not completeness of wallet history."}
                </p>
                {pnl.usdc_excludes_sol_fees ? (
                  <p data-usdc-excludes-sol-fees="true">USDC results exclude SOL fees. No FX conversion.</p>
                ) : null}
                <p>
                  Open positions {String(analytics.open_positions ?? 0)} stay out of hold statistics.
                  Unresolved-basis sales {String(analytics.unresolved_basis_sales ?? 0)} are missing basis, not zero.
                </p>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}

export function currentHistoryState(
  report: Report,
  currentMethodology?: string,
) {
  if (!currentMethodology) return "method_unavailable";
  const saved = report.history_assessment;
  if (!saved || saved.state === "missing" || !saved.saved_methodology)
    return "missing";
  return saved.state === "current" &&
    saved.saved_methodology === currentMethodology &&
    saved.current_methodology === currentMethodology
    ? "current"
    : "rebuild_required";
}

export function HistoryAssessmentBanner({
  report,
  currentMethodology,
}: {
  report: Report;
  currentMethodology?: string;
}) {
  if (report.source !== "live" || report.preview) return null;
  const assessment = currentHistoryState(report, currentMethodology);
  const current = assessment === "current";
  const title = current
    ? "Current history method"
    : assessment === "rebuild_required"
      ? "Saved history assessment requires rebuild"
      : assessment === "method_unavailable"
        ? "Current history method unavailable"
        : "No current history assessment";
  const explanation = current
    ? "This saved assessment uses the current history method. Its individual gates still determine which evidence remains unknown."
    : assessment === "method_unavailable"
      ? "The service has not supplied a current history method. Saved native period receipts remain historical until their method can be checked."
      : "Saved native period receipts are historical assessments. Use Rebuild from saved records to assess this report under the current history method. Missing history may remain unresolved.";
  return (
    <div
      className={current ? "inline-info" : "inline-alert"}
      data-history-assessment={assessment}
      role="status"
    >
      {current ? <ShieldCheck size={18} /> : <TriangleAlert size={18} />}
      <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
        <strong>{title}</strong>
        <p>{explanation}</p>
        {report.history_assessment?.reason && (
          <p>{report.history_assessment.reason}</p>
        )}
        <small>
          Saved method:{" "}
          <span className="mono">
            {report.history_assessment?.saved_methodology || "not recorded"}
          </span>{" "}
          · Current method:{" "}
          <span className="mono">{currentMethodology || "not supplied"}</span>.
          Saved figures and source records remain unchanged.
        </small>
      </div>
    </div>
  );
}

function positionFreshness(
  evidence: AccountPositionEvidence | undefined,
  saved: PositionAssessment | undefined,
  currentMethodology?: string,
) {
  if (!currentMethodology) return "method_unavailable";
  if (
    !evidence ||
    !saved ||
    saved.state === "missing" ||
    !saved.saved_methodology
  )
    return "missing";
  return saved.state === "current" &&
    saved.saved_methodology === currentMethodology &&
    saved.current_methodology === currentMethodology &&
    evidence.version === currentMethodology
    ? "current"
    : "rebuild_required";
}

export function currentPositionState(
  report: Report,
  currentMethodology?: string,
) {
  return positionFreshness(
    report.coverage.position_evidence,
    report.position_assessment,
    currentMethodology,
  );
}

export function PositionAssessmentBanner({
  report,
  currentMethodology,
}: {
  report: Report;
  currentMethodology?: string;
}) {
  if (report.source !== "live" || report.preview) return null;
  const assessment = currentPositionState(report, currentMethodology);
  const current = assessment === "current";
  const title = current
    ? "Current account-position method"
    : assessment === "rebuild_required"
      ? "Saved account-position assessment requires rebuild"
      : assessment === "method_unavailable"
        ? "Current account-position method unavailable"
        : "No current account-position assessment";
  const explanation = current
    ? "This account-position assessment uses the current method. A current known scoped hold also requires a matching current history assessment; unknown stages remain unknown."
    : "Saved account holds and stage results remain historical. Use Rebuild from saved records to assess the archived sources under the current account-position method without provider calls.";
  return (
    <div
      className={current ? "inline-info" : "inline-alert"}
      data-position-assessment={assessment}
      role="status"
    >
      {current ? <ShieldCheck size={18} /> : <TriangleAlert size={18} />}
      <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
        <strong>{title}</strong>
        <p>{explanation}</p>
        {report.position_assessment?.reason && (
          <p>{report.position_assessment.reason}</p>
        )}
        <small>
          Saved method:{" "}
          <span className="mono">
            {report.position_assessment?.saved_methodology ||
              report.coverage.position_evidence?.version ||
              "not recorded"}
          </span>{" "}
          · Current method:{" "}
          <span className="mono">{currentMethodology || "not supplied"}</span>.
          Saved quantities, figures and source records remain unchanged.
        </small>
      </div>
    </div>
  );
}

export function SourceConsistencySection({
  evidence,
  currentMethodology,
  historyCurrent,
  showEvidence,
  projection,
}: {
  evidence?: SourceConsistency;
  currentMethodology?: string;
  historyCurrent: boolean;
  showEvidence: (hash: string) => void;
  projection?: Report["report_view"];
}) {
  const [page, setPage] = useState(0);
  const transactions = Object.entries(evidence?.transactions ?? {});
  const transactionsProjected = projection?.omitted_paths.some((path) =>
    path === "coverage.history_evidence.source_consistency.transactions" ||
    path.startsWith("coverage.history_evidence.source_consistency.transactions."),
  );
  const freshness = !currentMethodology
    ? "method_unavailable"
    : !evidence
      ? "missing"
      : historyCurrent && evidence.version === currentMethodology
        ? "current"
        : "rebuild_required";
  const fresh = freshness === "current";
  const complete = sourceSetComplete(evidence?.source_set);
  const currentPass = fresh && complete;
  const groupStatus = (group: SourceConsistencyGroup) => group.state === "PASS"
    ? "consistent"
    : Object.values(group.checks).some((check) => check.status === "conflict")
      ? "conflict"
      : "missing";
  const renderCheck = (name: string, check: SourceConsistencyCheck) => (
    <div className="check-row" key={`${check.account}:${name}`}>
      <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
        <strong>{label(name)}</strong>
        <small>{check.reason}</small>
        <details style={{ marginTop: 7 }}>
          <summary>Inspect archive facts · {count(check.facts.length)}</summary>
          <div style={{ maxHeight: 240, overflow: "auto", marginTop: 10 }}>
            {check.facts.slice(0, 20).map((fact, index) => (
              <div key={`${fact.hash}:${fact.path}:${index}`} style={{ marginBottom: 12 }}>
                <button className="text-button mono" onClick={() => showEvidence(fact.hash)}>
                  Source {shorten(fact.hash, 5)} <ArrowUpRight size={12} />
                </button>
                <small className="mono">{fact.path}</small>
                <small>{label(fact.status)}: <span className="mono">{typeof fact.value === "string" ? fact.value : JSON.stringify(fact.value) ?? "not recorded"}</span></small>
              </div>
            ))}
            {check.facts.length > 20 && <p className="small-note">Showing 20 archive facts. Complete facts and paths remain in the JSON export.</p>}
          </div>
        </details>
      </div>
      <Badge value={!fresh ? "stale" : check.status === "conflict" ? "FAIL" : currentPass ? check.state : "UNKNOWN"}>
        {!fresh ? `Saved ${label(check.status)}` : !complete && check.state === "PASS" ? "Incomplete proof" : label(check.status)}
      </Badge>
    </div>
  );
  return (
    <section className="panel" data-source-consistency={evidence?.version ?? "missing"} data-source-consistency-freshness={freshness} data-source-set-complete={String(complete)}>
      <SectionHeading title="Linked archive consistency" subtitle="Metric-specific facts across collector-linked native receipts." action={<Badge value="partial">Source scope</Badge>} />
      <p className="observed-research-note">
        Different archive hashes can agree on the required facts. Contradictions
        and missing facts invalidate their dependent checks. Native fee checks
        govern their own observed totals; token conflicts do not erase agreeing
        fees. This assessment does not establish complete wallet history, profit,
        or financial qualification. Native totals also require their collection
        and inspection budgets to be complete.
      </p>
      {evidence && <div className="report-note" data-source-set-state={!evidence.source_set ? "missing" : !fresh ? "saved" : complete ? "PASS" : "UNKNOWN"}>
        <strong>{fresh ? "Linked source index: " : "Saved source index: "}</strong>
        <span>{complete ? "Complete" : "Unknown · incomplete or unavailable proof"}</span>
        {evidence.source_set ? <>
          <p>{count(evidence.source_set.raw_reference_count)} references · {count(evidence.source_set.authenticated_reference_count)} authenticated references · {count(evidence.source_set.unique_link_count)} unique links · {count(evidence.source_set.unique_hash_count)} unique archives · {count(evidence.source_set.inspected_hash_count)} inspected · {count(evidence.source_set.omitted_hash_count)} omitted</p>
          <p>{evidence.source_set.reason}</p>
          <small>A complete index records enumeration and attempted reads. Usable contents and each metric's dependencies are assessed separately.</small>
          <small>Omitted authenticated links: {count(evidence.source_set.omitted_link_count)} · Invalid authenticated links: {count(evidence.source_set.invalid_authenticated_link_count)} · Invalid links: {count(evidence.source_set.invalid_link_count)} · Unauthenticated links: {count(evidence.source_set.unauthenticated_link_count)}{evidence.source_set.budget && ` · Unique-archive budget: ${count(evidence.source_set.budget.max_unique_hashes)}`}</small>
          {(Array.isArray(evidence.source_set.evidence) ? evidence.source_set.evidence : []).slice(0, 3).map((hash) => <button key={hash} className="text-button mono" style={{ marginRight: 10 }} onClick={() => showEvidence(hash)}>Source {shorten(hash, 5)} <ArrowUpRight size={12} /></button>)}
          {!complete && Boolean(evidence.source_set.omitted_scope) && <details><summary>Inspect omitted source scope</summary><pre style={{ maxHeight: 180, overflow: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(evidence.source_set.omitted_scope, null, 2)}</pre></details>}
        </> : <p>No complete authenticated link index is recorded. Inspected agreements cannot replace missing source-set proof.</p>}
      </div>}
      {evidence?.archive_contents && <div className="report-note" data-archive-contents-state={fresh ? evidence.archive_contents.state : "saved"}>
        <strong>{fresh ? "Archive contents: " : "Saved archive contents: "}</strong>
        <span>{count(evidence.archive_contents.counts.usable)} usable roles · {count(evidence.archive_contents.counts.unresolved)} unresolved roles</span>
        <p>Missing or invalid sources remain linked. Dependent results stay unknown until recovery or a supported exclusion; independent fee observations keep their own evidence.</p>
        {evidence.archive_contents.counts.unresolved > 0 && <details>
          <summary>Inspect unresolved sources and recovery</summary>
          <div style={{ maxHeight: 240, overflow: "auto", overflowWrap: "anywhere" }}>
            {evidence.archive_contents.receipts.filter((row) => row.state !== "PASS").slice(0, 20).map((row, index) => <div key={`${row.kind}:${row.hash}:${index}`} style={{ marginTop: 12 }}>
              <strong>{label(row.kind)} · {label(row.read_state)} · {label(row.validation_state)}</strong>
              {row.hash && <button className="text-button mono" style={{ marginLeft: 8 }} onClick={() => showEvidence(row.hash!)}>Source {shorten(row.hash, 5)} <ArrowUpRight size={12} /></button>}
              <small>{row.reason}</small>
              <small>{row.recovery?.action ?? "Source recovery remains unresolved."}</small>
            </div>)}
            {evidence.archive_contents.counts.unresolved > 20 && <p className="small-note">Showing 20 unresolved sources. Every source receipt remains in the JSON export.</p>}
          </div>
        </details>}
      </div>}
      <p className="report-note">
        Saved method: <span className="mono">{evidence?.version ?? "not recorded"}</span> · Current method: <span className="mono">{currentMethodology ?? "not supplied"}</span>.
        {!fresh && " Saved consistency checks are historical or unavailable. Rebuild from saved records to assess them under the current method."}
      </p>
      {!evidence ? <p className="report-note">No shared source-consistency assessment is saved. Missing facts remain unknown.</p> : transactionsProjected ? (
        <p className="report-note" data-source-receipts-view="export">
          Detailed linked receipt checks remain in the full saved report JSON
          export. The source index and recorded assessment above are unchanged;
          individual archives remain available in Source records.
        </p>
      ) : (
        <details>
          <summary>Inspect linked receipt checks · {count(transactions.length)} signatures</summary>
          {transactions.length ? <>
            <div className="table-scroll" style={{ marginTop: 16 }}>
              <table className="records-table">
                <thead><tr><th>Signature</th><th>Linked native archives</th><th>Native fee facts</th><th>Native movement facts</th><th>Account and source checks</th></tr></thead>
                <tbody>{transactions.slice(page * 10, page * 10 + 10).map(([signature, receipt]) => (
                  <tr key={signature}>
                    <td className="mono" title={signature}>{shorten(signature)}</td>
                    <td>{count(receipt.native_hashes.length)}</td>
                    <td><Badge value={!fresh ? "stale" : currentPass ? receipt.native.wallet_network_fees_sol.state : "UNKNOWN"}>{!fresh ? `Saved ${label(groupStatus(receipt.native.wallet_network_fees_sol))}` : !complete && receipt.native.wallet_network_fees_sol.state === "PASS" ? "Incomplete proof" : label(groupStatus(receipt.native.wallet_network_fees_sol))}</Badge></td>
                    <td><Badge value={!fresh ? "stale" : currentPass ? receipt.native.native_wallet_delta_sol.state : "UNKNOWN"}>{!fresh ? `Saved ${label(groupStatus(receipt.native.native_wallet_delta_sol))}` : !complete && receipt.native.native_wallet_delta_sol.state === "PASS" ? "Incomplete proof" : label(groupStatus(receipt.native.native_wallet_delta_sol))}</Badge></td>
                    <td style={{ minWidth: 310, maxWidth: 440, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                      <details><summary>Inspect receipt facts</summary>
                        <div className="checks-list" style={{ padding: 0 }}>
                          <div><strong>Native fee dependencies</strong>{Object.entries(receipt.native.wallet_network_fees_sol.checks).map(([name, check]) => renderCheck(name, check))}</div>
                          <div><strong>Native movement dependencies</strong>{Object.entries(receipt.native.native_wallet_delta_sol.checks).map(([name, check]) => renderCheck(name, check))}</div>
                          {Object.entries(receipt.accounts).slice(0, 10).map(([account, checks]) => (
                            <div key={account}>
                              <strong className="mono" title={account}>Account {shorten(account)}</strong>
                              {Object.entries(checks.checks).slice(0, 16).map(([name, check]) => renderCheck(name, check))}
                            </div>
                          ))}
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div className="pagination"><span>{page * 10 + 1}–{Math.min(page * 10 + 10, transactions.length)} of {count(transactions.length)} signatures</span><div>
              <Button variant="secondary" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous receipts</Button>
              <Button variant="secondary" disabled={page * 10 + 10 >= transactions.length} onClick={() => setPage((value) => value + 1)}>Next receipts</Button>
            </div></div>
          </> : <p className="report-note">No linked native receipts are available for shared fact reconciliation.</p>}
        </details>
      )}
    </section>
  );
}

export function sourceSetComplete(source?: SourceSet) {
  return Boolean(source && source.state === "PASS" && source.complete === true && Array.isArray(source.evidence) &&
    [source.raw_reference_count, source.authenticated_reference_count, source.omitted_link_count, source.invalid_authenticated_link_count, source.unique_link_count, source.unique_hash_count, source.inspected_hash_count, source.omitted_hash_count].every((value) => Number.isSafeInteger(value) && value >= 0) &&
    (source.budget && Number.isSafeInteger(source.budget.max_unique_hashes) && source.budget.max_unique_hashes >= 1 && source.budget.max_unique_hashes <= 40000 && source.unique_hash_count <= source.budget.max_unique_hashes) &&
    source.unique_link_count >= source.unique_hash_count && source.raw_reference_count >= source.unique_link_count && source.authenticated_reference_count >= source.unique_link_count &&
    source.omitted_link_count === 0 && source.invalid_authenticated_link_count === 0 && source.omitted_hash_count === 0 && source.inspected_hash_count === source.unique_hash_count &&
    source.invalid_link_count === 0 && source.unauthenticated_link_count === 0);
}

export function AccountPositionEvidenceSection({
  evidence,
  assessment,
  currentMethodology,
  historyCurrent = false,
  showEvidence,
}: {
  evidence?: AccountPositionEvidence;
  assessment?: PositionAssessment;
  currentMethodology?: string;
  historyCurrent?: boolean;
  showEvidence: (hash: string) => void;
}) {
  const [page, setPage] = useState(0);
  const knownMedian = evidence?.known_account_hold_median_hours;
  const fresh =
    historyCurrent &&
    positionFreshness(evidence, assessment, currentMethodology) === "current";
  const closed = evidence?.positions.filter(
    (position) => position.status === "known_closed",
  ) ?? [];
  const sourceGateKnown = Boolean(
    evidence &&
      closed.length === evidence.counts.known_closed &&
      closed.every((position) => position.stages.source_consistency?.state === "PASS" && sourceSetComplete(position.source_set)),
  );
  const medianKnown =
    fresh &&
    sourceGateKnown &&
    evidence &&
    evidence.counts.known_closed > 0 &&
    knownMedian?.status === "known" &&
    knownMedian.value !== null;
  return (
    <section
      className="panel"
      data-account-position-evidence={evidence?.version ?? "missing"}
      data-position-evidence={evidence?.version ?? "missing"}
      data-position-freshness={
        fresh
          ? "current"
          : historyCurrent
            ? positionFreshness(evidence, assessment, currentMethodology)
            : "history_not_current"
      }
    >
      <SectionHeading
        title="Source-backed account episodes"
        subtitle="Strict-zero stages for enumerated token-account episodes only."
        action={<Badge value="partial">Account scope</Badge>}
      />
      <p className="observed-research-note">
        These stages describe individual enumerated account episodes. They do
        not establish whole-wallet median hold, profit, strict-filter
        qualification, or trading safety.
        A current known account hold also requires its source-consistency gate
        to pass.
      </p>
      {!evidence ? (
        <p className="report-note">
          No account-episode assessment is saved in this report. Rebuild from
          saved records to assess the available sources; missing records remain
          unknown.
        </p>
      ) : (
        <>
          {!fresh && (
            <p className="report-note">
              <strong>Saved account assessment · rebuild needed.</strong> These
              saved holds and stage outcomes do not represent a current known
              account-episode assessment. Both history and position methods must
              match before current scoped timing can be shown.
            </p>
          )}
          {evidence.trust_boundary && (
            <p className="report-note">
              Source boundary: {evidence.trust_boundary}
            </p>
          )}
          {evidence.account_scope && <p className="report-note" data-account-scope>
            Evaluated account subset: {count(evidence.account_scope.inspected_account_count)} of {count(evidence.account_scope.candidate_account_count)} candidate accounts · {count(evidence.account_scope.omitted_account_count)} omitted.
            <small style={{ display: "block" }}>{evidence.account_scope.population}</small>
          </p>}
          <div
            className="position-counts"
            style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))" }}
          >
            <div>
              <strong>{count(evidence.counts.known_closed)}</strong>
              <span>{fresh && sourceGateKnown ? "Known closed" : fresh ? "Recorded closed · gate needed" : "Saved known closed"}</span>
            </div>
            <div>
              <strong>{count(evidence.counts.open)}</strong>
              <span>{fresh ? "Open" : "Saved open"}</span>
            </div>
            <div>
              <strong>{count(evidence.counts.unresolved)}</strong>
              <span>{fresh ? "Unresolved" : "Saved unresolved"}</span>
            </div>
          </div>
          <div className="report-note">
            <strong>
              {fresh
                ? "Known account-episode hold median: "
                : "Saved account-episode hold median: "}
            </strong>
            <span title={knownMedian?.value ?? knownMedian?.reason}>
              {medianKnown
                ? `${decimal(knownMedian?.value)} hours`
                : !fresh && typeof knownMedian?.value === "string"
                  ? `${decimal(knownMedian.value)} hours · rebuild needed`
                  : "Unknown"}
            </span>
            <p>{knownMedian?.population || evidence.scope}</p>
            {!medianKnown && (
              <p>
                {!fresh
                  ? "Current scoped timing is unavailable until both history and position assessments are current."
                  : !sourceGateKnown
                    ? "A required account source-consistency gate is unknown or not recorded, or its linked source-set proof is incomplete. Saved values remain in the report and export."
                  : knownMedian?.reason ||
                    "No fully evidenced strict-zero closed account population is available."}
              </p>
            )}
          </div>
          {evidence.positions.length ? (
            <>
              <div className="table-scroll">
                <table className="records-table">
                  <thead>
                    <tr>
                      <th>Token account</th>
                      <th>Mint</th>
                      <th>{fresh ? "Episode state" : "Saved episode state"}</th>
                      <th>
                        {fresh ? "Account hold" : "Saved hold · rebuild needed"}
                      </th>
                      <th>
                        {fresh
                          ? "Source-backed stages"
                          : "Saved stage assessments"}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {evidence.positions
                      .slice(page * 10, page * 10 + 10)
                      .map((position) => (
                        <tr key={position.id} data-position-source-consistency={!fresh ? "saved" : !sourceSetComplete(position.source_set) ? "UNKNOWN" : position.stages.source_consistency?.state ?? "missing"}>
                          <td className="mono" title={position.account}>
                            {shorten(position.account)}
                          </td>
                          <td className="mono" title={position.mint}>
                            {shorten(position.mint)}
                          </td>
                          <td>
                            <Badge value={fresh ? position.status : "stale"}>
                              {fresh
                                ? label(position.status)
                                : `Saved ${label(position.status)}`}
                            </Badge>
                          </td>
                          <td
                            title={
                              position.hold_hours.value ??
                              position.hold_hours.reason
                            }
                          >
                            {fresh &&
                            position.stages.source_consistency?.state === "PASS" &&
                            sourceSetComplete(position.source_set) &&
                            position.status === "known_closed" &&
                            position.hold_hours.status === "known" &&
                            position.hold_hours.value !== null
                              ? `${decimal(position.hold_hours.value)} h`
                              : !fresh &&
                                  typeof position.hold_hours.value === "string"
                                ? `${decimal(position.hold_hours.value)} h · saved / rebuild needed`
                                : "Unknown"}
                          </td>
                          <td style={{ whiteSpace: "normal", minWidth: 290 }}>
                            <details>
                              <summary>
                                {fresh
                                  ? "Inspect episode stages"
                                  : "Inspect saved episode stages"}
                              </summary>
                              <div
                                className="checks-list"
                                style={{ padding: 0 }}
                              >
                                {Object.entries(position.stages).map(
                                  ([key, stage]) => (
                                    <div className="check-row" key={key}>
                                      <div style={{ minWidth: 0 }}>
                                        <strong>{label(key)}</strong>
                                        <small>{stage.reason}</small>
                                        {fresh && !sourceSetComplete(position.source_set) && stage.state === "PASS" && <small>Recorded assertion requires a complete linked source set before a current PASS can be shown.</small>}
                                        {key === "source_consistency" && stage.dependencies.length > 0 && (
                                          <small>Required facts: {stage.dependencies.map(label).join(" · ")}</small>
                                        )}
                                        {!fresh && (
                                          <small>
                                            Historical saved result · rebuild
                                            required for a current assessment
                                          </small>
                                        )}
                                        {stage.evidence
                                          .slice(0, 3)
                                          .map((hash) => (
                                            <button
                                              className="text-button mono"
                                              style={{
                                                fontSize: 8,
                                                marginTop: 5,
                                                marginRight: 7,
                                              }}
                                              key={hash}
                                              onClick={() => showEvidence(hash)}
                                            >
                                              Source {shorten(hash, 5)}{" "}
                                              <ArrowUpRight size={12} />
                                            </button>
                                          ))}
                                      </div>
                                      <Badge
                                        value={!fresh ? "stale" : sourceSetComplete(position.source_set) ? stage.state : "UNKNOWN"}
                                      >
                                        {!fresh ? `Saved ${label(stage.state.toLowerCase())}` : !sourceSetComplete(position.source_set) && stage.state === "PASS" ? "Incomplete proof" : label(stage.state.toLowerCase())}
                                      </Badge>
                                    </div>
                                  ),
                                )}
                              </div>
                              <dl
                                className="coverage-list"
                                style={{ padding: 0 }}
                              >
                                <div>
                                  <dt>First acquisition</dt>
                                  <dd>
                                    {position.start
                                      ? dateTime(position.start)
                                      : "Unknown"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Strict-zero close</dt>
                                  <dd>
                                    {position.end
                                      ? dateTime(position.end)
                                      : "Unknown"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Opening / closing raw</dt>
                                  <dd className="mono">
                                    {position.opening_raw ?? "Unknown"} /{" "}
                                    {position.closing_raw ?? "Unknown"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Acquired / sold raw</dt>
                                  <dd className="mono">
                                    {position.acquired_raw} /{" "}
                                    {position.sold_raw}
                                  </dd>
                                </div>
                              </dl>
                              <p className="small-note" data-position-source-set={sourceSetComplete(position.source_set) ? "complete" : "incomplete"}>
                                {fresh ? "Source-set proof: " : "Saved source-set proof: "}{sourceSetComplete(position.source_set) ? "Complete" : "Unknown"}.
                                {position.source_set ? ` ${count(position.source_set.raw_reference_count)} references; ${count(position.source_set.inspected_hash_count)} archives inspected; ${count(position.source_set.omitted_hash_count)} omitted. ${position.source_set.reason}` : " No complete authenticated link index is recorded."}
                              </p>
                              {position.source_paths && position.source_paths.length > 0 && (
                                <details style={{ marginTop: 12 }}>
                                  <summary>{fresh ? "Inspect quantity source paths" : "Inspect saved quantity source paths"} · {count(position.source_paths.length)} archive records</summary>
                                  <div style={{ maxHeight: 240, overflow: "auto", overflowWrap: "anywhere", marginTop: 10 }}>
                                    {position.source_paths.slice(0, 20).map((source) => (
                                      <div key={`${source.signature}:${source.hash}`} style={{ marginBottom: 14 }}>
                                        <button className="text-button mono" onClick={() => showEvidence(source.hash)}>Source {shorten(source.hash, 5)} <ArrowUpRight size={12} /></button>
                                        <small className="mono" style={{ display: "block", whiteSpace: "normal" }}>{source.paths.slice(0, 20).join(" · ")}</small>
                                      </div>
                                    ))}
                                    {position.source_paths.length > 20 && <p className="small-note">Showing 20 archive records. All source paths remain in the JSON export.</p>}
                                  </div>
                                </details>
                              )}
                            </details>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <span>
                  {page * 10 + 1}–
                  {Math.min(page * 10 + 10, evidence.positions.length)} of{" "}
                  {count(evidence.positions.length)} account episodes
                </span>
                <div>
                  <Button
                    variant="secondary"
                    disabled={page === 0}
                    onClick={() => setPage((value) => value - 1)}
                  >
                    Previous episodes
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={page * 10 + 10 >= evidence.positions.length}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Next episodes
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <p className="report-note">
              No enumerated account episodes could be reconstructed from the
              available sources. Account hold remains Unknown.
            </p>
          )}
          {evidence.recovery_actions.length > 0 && (
            <details className="observed-research-limitations">
              <summary>
                Needed source records ·{" "}
                {count(evidence.recovery_actions.length)} recovery actions
              </summary>
              {evidence.recovery_actions.slice(0, 20).map((action, index) => (
                <p key={index}>
                  <span className="mono" title={action.account}>
                    {shorten(action.account)}
                  </span>{" "}
                  · {action.reason} ·{" "}
                  {action.requires_network
                    ? "Requires additional source reads"
                    : "Uses saved records"}
                </p>
              ))}
            </details>
          )}
          <details className="observed-research-limitations">
            <summary>Account scope and limitations</summary>
            <p>{evidence.scope}</p>
            <p>Assessment method: {evidence.version}</p>
            {evidence.limitations.map((limitation, index) => (
              <p key={index}>{limitation}</p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}

function RecordTable({
  records,
  kind,
}: {
  records: Record<string, unknown>[];
  kind: "positions" | "events";
}) {
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const preferred =
    kind === "positions"
      ? [
          "mint",
          "status",
          "start",
          "end",
          "basis_sol",
          "pnl_sol",
          "hold_hours",
          "in_window",
        ]
      : [
          "timestamp",
          "kind",
          "mint",
          "quantity_raw",
          "amount_sol",
          "fee_sol",
          "classification",
          "signature",
        ];
  const available = new Set(records.flatMap((record) => Object.keys(record)));
  const columns = preferred.filter((key) => available.has(key)).slice(0, 8);
  const displayed = columns.length
    ? columns
    : [...available]
        .filter((key) => !["id", "evidence", "events", "lots"].includes(key))
        .slice(0, 8);
  if (!records.length)
    return (
      <Empty
        title={`No ${kind} in this report`}
        detail="Records appear here only when the underlying reconstruction supplies them."
        icon={Search}
      />
    );
  const start = page * 25;
  const display = (key: string, value: unknown) => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "object")
      return Array.isArray(value) ? `${value.length} records` : "Details";
    if (["mint", "signature"].includes(key)) return shorten(String(value), 6);
    if (
      key === "timestamp" &&
      typeof value === "number" &&
      Number.isFinite(value)
    )
      return dateTime(new Date(value * 1000).toISOString());
    if (
      /(?:timestamp|_at|^start$|^end$)$/.test(key) &&
      typeof value === "string"
    )
      return dateTime(value);
    if (typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value))
      return key.endsWith("_raw")
        ? value
        : decimal(value, key.endsWith("_sol") ? 9 : 5);
    return String(value);
  };
  return (
    <>
      <div className="table-scroll">
        <table className="records-table">
          <thead>
            <tr>
              {displayed.map((key) => (
                <th key={key}>{label(key)}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {records.slice(start, start + 25).map((record, index) => (
              <tr
                key={start + index}
                onClick={() =>
                  setExpanded(expanded === start + index ? null : start + index)
                }
                className="clickable-row"
              >
                {displayed.map((key) => (
                  <td
                    key={key}
                    title={
                      typeof record[key] === "string"
                        ? String(record[key])
                        : undefined
                    }
                    className={
                      ["mint", "signature", "quantity_raw"].includes(key)
                        ? "mono"
                        : ""
                    }
                  >
                    {display(key, record[key])}
                  </td>
                ))}
                <td>
                  <button
                    className="icon-button"
                    aria-label={`Inspect ${kind === "positions" ? "position" : "event"} ${start + index + 1}`}
                  >
                    <ChevronDown size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {expanded !== null && (
        <div className="record-detail">
          <strong>
            Complete {kind === "positions" ? "position" : "event"} record
          </strong>
          <button className="text-button" onClick={() => setExpanded(null)}>
            Close
          </button>
          <pre>{JSON.stringify(records[expanded], null, 2)}</pre>
        </div>
      )}
      <div className="pagination">
        <span>
          {start + 1}–{Math.min(start + 25, records.length)} of{" "}
          {count(records.length)} records
        </span>
        <div>
          <Button
            variant="secondary"
            disabled={page === 0}
            onClick={() => {
              setPage((p) => p - 1);
              setExpanded(null);
            }}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            disabled={start + 25 >= records.length}
            onClick={() => {
              setPage((p) => p + 1);
              setExpanded(null);
            }}
          >
            Next
          </Button>
        </div>
      </div>
    </>
  );
}

export function CoverageDetails({
  value,
  projected = false,
}: {
  value: unknown;
  projected?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary style={{ cursor: "pointer" }}>
        {projected ? "Inspect coverage summary" : "Inspect saved coverage"}
      </summary>
      {projected && <p className="small-note" data-coverage-view="summary">Repeated derivation details remain in the full saved report JSON export. Saved decisions and metrics are unchanged.</p>}
      {expanded && (
        <pre
          style={{
            maxHeight: 240,
            overflow: "auto",
            textAlign: "left",
            fontSize: 9,
          }}
        >
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </details>
  );
}

export function ReportView({
  state,
  report,
  busy,
  run,
  navigate,
  open,
  updateReport,
  showEvidence,
  selected,
  onSelect,
}: Actions & {
  report: Report;
  showEvidence: (hash: string) => void;
  selected: string[];
  onSelect: (id: string) => void;
}) {
  const [tab, setTab] = useState("overview");
  const [evidencePage, setEvidencePage] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildError, setRebuildError] = useState("");
  const watched = state.watchlist.some(
    (item) => item.address === report.address,
  );
  const qualification = report.qualification;
  const historyCurrent =
    currentHistoryState(report, state.history_evidence_methodology) ===
    "current";
  const missingSnapshot = !!qualification && !qualification.preset_snapshot;
  const pastPreset =
    !!qualification?.preset_snapshot &&
    !samePresetSnapshot(qualification.preset_snapshot, state.preset);
  const qualified =
    report.source === "live" &&
    !report.preview &&
    historyCurrent &&
    qualification?.qualified === true &&
    qualification.financial_policy === "MATCH" &&
    qualification.evidence_status === "verified" &&
    typeof qualification.profit_sol === "string" &&
    report.policy === "MATCH" &&
    report.evidence_status === "verified" &&
    report.metrics.profit_sol?.status === "known" &&
    report.metrics.profit_sol.value !== null &&
    typeof state.methodology === "string" &&
    !!state.methodology &&
    qualification.methodology === state.methodology &&
    report.methodology === state.methodology &&
    samePresetSnapshot(qualification.preset_snapshot, state.preset) &&
    !pastPreset;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report.address);
      setCopied(true);
      setCopyError("");
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopyError(
        "Copy is unavailable in this browser. Select the full address below.",
      );
    }
  };
  const rebuild = async () => {
    setRebuilding(true);
    setRebuildError("");
    try {
      const result = (await run(
        "report-rebuild",
        `/reports/${encodeURIComponent(report.id)}/rebuild`,
        {},
        "POST",
        "Report rebuilt from saved records. Missing history remains unresolved.",
      )) as { report_id?: string } | undefined;
      if (result?.report_id)
        await open(await reportDisplay(result.report_id));
    } catch (issue) {
      setRebuildError(
        issue instanceof Error
          ? issue.message
          : "The rebuilt report could not be opened.",
      );
    } finally {
      setRebuilding(false);
    }
  };
  const mainMetrics = metricDefinitions.filter((metric) =>
    [
      "profit_sol",
      "realised_roi_pct",
      "median_hold_hours",
      "completed_positions",
      "win_rate_pct",
      "economic_pnl_sol",
    ].includes(metric.key),
  );
  return (
    <>
      <div className="report-navigation">
        <button className="text-button" onClick={() => navigate("results")}>
          <ArrowLeft size={15} /> Back to results
        </button>
        <div>
          {!report.preview && (
            <Button
              variant="secondary"
              icon={Search}
              disabled={!!busy}
              busy={busy === "report-screen"}
              onClick={async () => {
                const assessment = await run("report-screen", "/screenings", { report_id: report.id }, "POST", "Screening assessment saved. Inspect its reasons in Research.");
                if (assessment) navigate("research");
              }}
            >
              Screen and save assessment
            </Button>
          )}
          {(report.source === "live" || report.archive_input_hash) && !report.preview && (
            <Button
              variant="secondary"
              icon={RotateCcw}
              disabled={!!busy || rebuilding}
              busy={busy === "report-rebuild" || rebuilding}
              onClick={rebuild}
              title="Recompute the saved window and filters from archived records without provider reads. Missing history remains unresolved."
            >
              Rebuild from saved records
            </Button>
          )}
          <Button
            variant="secondary"
            icon={GitCompareArrows}
            onClick={() => onSelect(report.id)}
          >
            {selected.includes(report.id)
              ? "Selected for comparison"
              : "Select to compare"}
          </Button>
          <Button
            variant="secondary"
            busy={busy === "report-watch"}
            icon={watched ? Check : Star}
            disabled={watched}
            onClick={() =>
              run(
                "report-watch",
                "/watchlist",
                { address: report.address, label: report.label || "" },
                "POST",
                "Wallet saved to the watchlist.",
              )
            }
          >
            {watched ? "On watchlist" : "Watch wallet"}
          </Button>
          <a
            className="button secondary"
            href={`/api/export/reports/${encodeURIComponent(report.id)}.csv`}
            download
          >
            <Download size={15} /> Export CSV
          </a>
        </div>
      </div>
      {rebuildError && (
        <div className="inline-alert" role="alert">
          {rebuildError}
        </div>
      )}
      {report.source === "live" && <HistoricalSourceNotice decision={state.historical_source_decision} />}
      <section className="panel report-summary">
        <div className="report-identity">
          <span
            className={`wallet-avatar large ${report.source === "demo" ? "demo-avatar" : ""}`}
          >
            {(report.label || report.address).slice(0, 2).toUpperCase()}
          </span>
          <div>
            <div className="report-name">
              <h2>{report.label || shorten(report.address, 8)}</h2>
              <Badge value={report.policy} />
              {report.source === "demo" && (
                <span className="synthetic-chip">
                  <FlaskConical size={13} /> Synthetic demo
                </span>
              )}
            </div>
            <div className="full-address">
              <span className="mono">{report.address}</span>
              <button
                className="icon-button"
                aria-label="Copy wallet address"
                onClick={copy}
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
            </div>
            {copyError && <p className="small-note">{copyError}</p>}
            <WindowLabel report={report} />
          </div>
        </div>
        <div className="report-data-state">
          <span className="muted">Evidence completeness</span>
          <Badge value={report.evidence_status} />
          <small>
            {report.methodology} · saved {date(report.created_at)}
          </small>
        </div>
      </section>
      <HistoryAssessmentBanner
        report={report}
        currentMethodology={state.history_evidence_methodology}
      />
      <PositionAssessmentBanner
        report={report}
        currentMethodology={state.position_evidence_methodology}
      />
      {report.source === "live" && qualification && (
        <section
          className={`report-qualification ${qualified ? "qualified" : ""}`}
        >
          <div>
            <span className="eyebrow">
              {historyCurrent
                ? "STRICT FILTER QUALIFICATION"
                : "SAVED FILTER ASSESSMENT"}
            </span>
            <h2>
              {!historyCurrent
                ? "Current history evidence needed"
                : missingSnapshot
                  ? "Saved filter snapshot unavailable"
                  : pastPreset
                    ? "Past preset result"
                    : qualified
                      ? "Meets your saved financial filters"
                      : qualification.financial_policy === "MISS"
                        ? "A required filter fails"
                        : "Evidence needed before qualification"}
            </h2>
            <p>
              {!historyCurrent ? "Saved assessment: " : ""}
              {qualification.reason ||
                "Complete accounting and every required financial and evidence gate must pass."}
            </p>
            <small>
              Saved preset {qualification.preset_version ?? "unknown"} ·{" "}
              {count(qualification.failed_checks?.length)} failed checks ·{" "}
              {count(qualification.unknown_checks?.length)} unknown checks
            </small>
            {pastPreset && (
              <p>
                Saved thresholds differ from the active filters, even if the
                version names match. This result does not qualify under the
                current settings.
              </p>
            )}
            {missingSnapshot && (
              <p>
                The frozen thresholds must be available before this report can
                qualify under the active filters.
              </p>
            )}
          </div>
          <Badge value={qualified ? "qualified" : "unresolved"}>
            {pastPreset
              ? "Past preset"
              : qualified
                ? "Filters pass"
                : "Not qualified"}
          </Badge>
        </section>
      )}
      {report.source === "demo" && (
        <div className="inline-info">
          <FlaskConical size={18} />
          <span>
            This entire report uses synthetic offline records. Addresses,
            events, and conclusions are demonstration controls.
          </span>
        </div>
      )}
      {report.archive_accounting && (
        <section className="panel" data-archive-accounting={report.archive_accounting.dataset} data-archive-report-id={report.id}>
          <SectionHeading title={report.archive_accounting.dataset === 'synthetic' ? 'Synthetic accounting · development' : 'Archived records · partial wallet coverage'}
            subtitle={report.archive_accounting.scope} />
          {report.archive_assessment && report.archive_assessment.state !== 'current' &&
            <p role="status">{report.archive_assessment.reason}</p>}
          <p>Selected network fees: {decimal(report.metrics.observed_network_fees_sol?.value, 9)} SOL. This observation does not establish all trading costs.</p>
          {report.archive_accounting.gaps.map((gap, i) => <p key={i}>{gap}</p>)}
          <details><summary>Inspect metric evidence requirements</summary>
            {Object.entries(report.archive_accounting.metric_requirements).map(([name, requirement]) => (
              <div key={name} style={{ overflowWrap: 'anywhere', marginTop: 12 }} data-archive-metric={name}>
                <strong>{label(name)} · {requirement.state}</strong>
                <p>{requirement.dependencies.map(label).join(', ')}</p>
                {requirement.reason && <p>{requirement.reason}</p>}
              </div>
            ))}
          </details>
        </section>
      )}
      <div className="report-tabs" role="tablist" aria-label="Report sections">
        {[
          { id: "overview", name: "Summary" },
          { id: "positions", name: `Positions (${report.positions.length})` },
          { id: "events", name: `Ledger & flows (${report.events.length})` },
          {
            id: "evidence",
            name: `Source evidence (${report.evidence.length})`,
          },
          ...(report.source === "live"
            ? [{ id: "market", name: "Current observations" }]
            : []),
        ].map((item) => (
          <button
            role="tab"
            aria-selected={tab === item.id}
            key={item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
          >
            {item.name}
          </button>
        ))}
      </div>
      <p className="display-precision-note">
        Display values are rounded; full values remain in records and exports.
        SOL ledger amounts retain nine decimal places.
      </p>
      {tab === "overview" && (
        <>
          <SubsetWorksheetPanel report={report} />
          {report.source === "live" && report.copy_review && (
            <section className="panel copy-review-panel">
              <SectionHeading
                title="Copy-trading behavior and open questions"
                subtitle={report.copy_review.scope}
                action={
                  <Badge value="unresolved">
                    {count(report.copy_review.unknown_checks.length)} unresolved{" "}
                    {report.copy_review.unknown_checks.length === 1
                      ? "check"
                      : "checks"}
                  </Badge>
                }
              />
              <div className="copy-review-scope">
                Timing patterns can flag a strategy that exits before a follower
                can react. A long final hold can include a small leftover
                position after most tokens were sold. These records do not
                establish the trader’s intent or exploitation of followers.
              </div>
              {report.copy_review.findings.map((finding, index) => (
                <div className="finding" key={`copy-${index}`}>
                  <TriangleAlert size={17} />
                  <div>
                    <strong>{finding.title}</strong>
                    <p>{finding.detail}</p>
                    {finding.conditional && (
                      <small>Conditional fetched-subset observation</small>
                    )}
                    {finding.evidence?.slice(0, 3).map((hash) => (
                      <button
                        className="text-button mono"
                        onClick={() => showEvidence(hash)}
                        key={hash}
                      >
                        Source {shorten(hash, 5)} <ArrowUpRight size={12} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div className="checks-list">
                {Object.entries(report.copy_review.checks).map(
                  ([key, check]) => (
                    <div className="check-row" key={key}>
                      <span className="check-icon">
                        {check.state === "UNKNOWN" ? (
                          <CircleHelp size={16} />
                        ) : (
                          <Search size={16} />
                        )}
                      </span>
                      <div>
                        <strong>{label(key)}</strong>
                        <small>
                          {check.detail}
                          {check.conditional
                            ? " · conditional fetched subset"
                            : ""}
                          {check.comparison
                            ? ` · ${label(check.comparison.toLowerCase())}`
                            : ""}
                        </small>
                      </div>
                      <Badge value={check.state} />
                    </div>
                  ),
                )}
              </div>
              {report.copy_review.notes.map((note, index) => (
                <p className="report-note" key={`copy-note-${index}`}>
                  {note}
                </p>
              ))}
            </section>
          )}
          {report.source === "live" && report.research && (
            <section className="panel observed-research">
              <SectionHeading
                title="Observed trading research"
                subtitle={`${report.research.scope} · ${count(report.research.supported_swaps)} supported swaps · ${count(report.research.closed_episodes)} observed closed episodes`}
                action={<Badge value="partial">Fetched subset</Badge>}
              />
              {report.research_assessment &&
                report.research_assessment.state !== "current" && (
                  <p role="status">{report.research_assessment.reason}</p>
                )}
              <div className="observed-research-note">
                These conditional calculations assume no earlier undiscovered
                holdings. Sales without fetched cost basis are excluded. They do
                not verify 30-day profit or establish that these trades can be
                copied.
              </div>
              <div className="observed-research-metrics">
                {[
                  {
                    name: "Conditional observed P&L",
                    value: report.research.conditional_observed_lot_profit_sol,
                    suffix: "SOL",
                    note: "FIFO over supported observed buys and sells",
                  },
                  {
                    name: "Conditional median hold",
                    value: report.research.conditional_median_hold_hours,
                    suffix: "hours",
                    note: "Observed closed episodes only",
                  },
                  {
                    name: "Conditional median first sale",
                    value: report.research.conditional_first_sale_hours,
                    suffix: "hours",
                    note: "Observed entry to first economic sale",
                  },
                  {
                    name: "Conditional median 50% exit",
                    value: report.research.conditional_exit_50_hours,
                    suffix: "hours",
                    note: "Observed entry to half the acquired quantity sold",
                  },
                  {
                    name: "Conditional median 90% exit",
                    value: report.research.conditional_exit_90_hours,
                    suffix: "hours",
                    note: "Observed entry to 90% of acquired quantity sold",
                  },
                ].map((metric) => (
                  <div key={metric.name}>
                    <span>{metric.name}</span>
                    <strong>
                      {metric.value !== null && metric.value !== undefined
                        ? decimal(metric.value, metric.suffix === "SOL" ? 9 : 2)
                        : "—"}
                      {metric.value !== null && metric.value !== undefined && (
                        <small> {metric.suffix}</small>
                      )}
                    </strong>
                    <p>{metric.note}</p>
                  </div>
                ))}
              </div>
              <details className="observed-research-limitations">
                <summary>
                  Missing basis and research limits ·{" "}
                  {count(report.research.unresolved_basis_sales)} sales with
                  unresolved basis
                </summary>
                {report.research.limitations.map((note, index) => (
                  <p key={index}>{note}</p>
                ))}
                {report.research.risk_findings?.map((finding, index) => (
                  <p key={`risk-${index}`}>
                    {typeof finding === "string"
                      ? finding
                      : [finding.title, finding.detail]
                          .filter(Boolean)
                          .join(" · ")}
                  </p>
                ))}
              </details>
            </section>
          )}
          {report.source === "live" && !report.preview && (
            <>
            <SelectedCohortSection
              report={report}
              currentWalletMethod={state.wallet_evidence_methodology}
              currentAccountingMethod={state.methodology}
              historyCurrent={historyCurrent}
              showEvidence={showEvidence}
            />
            <InventoryObservations
              report={report}
              currentWalletMethod={state.wallet_evidence_methodology}
              historyCurrent={historyCurrent}
              showEvidence={showEvidence}
            />
            <NativeCashObservations
              report={report}
              currentWalletMethod={state.wallet_evidence_methodology}
              historyCurrent={historyCurrent}
              showEvidence={showEvidence}
            />
            <SourceConsistencySection
              evidence={report.coverage.history_evidence?.source_consistency}
              currentMethodology={state.source_consistency_methodology}
              historyCurrent={historyCurrent}
              showEvidence={showEvidence}
              projection={report.report_view}
            />
            <AccountPositionEvidenceSection
              evidence={report.coverage.position_evidence}
              assessment={report.position_assessment}
              currentMethodology={state.position_evidence_methodology}
              historyCurrent={historyCurrent}
              showEvidence={showEvidence}
            />
            </>
          )}
          <div className="report-metrics">
            {mainMetrics.map((metric) => (
              <div className="report-metric" key={metric.key}>
                <span>
                  {metric.name}
                  <CircleHelp size={13} aria-label={metric.hint}>
                    <title>{metric.hint}</title>
                  </CircleHelp>
                </span>
                <strong>
                  <MetricValue
                    metric={report.metrics[metric.key]}
                    suffix={metric.suffix}
                  />
                </strong>
                <small>
                  {report.metrics[metric.key]?.status === "known"
                    ? "From eligible evidenced records"
                    : report.metrics[metric.key]?.reason ||
                      "Insufficient evidence"}
                </small>
              </div>
            ))}
          </div>
          <div className="report-columns">
            <section className="panel policy-panel">
              <SectionHeading
                title="Why this result?"
                subtitle="The report's saved thresholds, evaluated check by check."
              />
              <div className="policy-summary">
                <div
                  className={`policy-summary-icon ${report.policy.toLowerCase()}`}
                >
                  {report.policy === "MATCH" ? (
                    <CheckCircle2 size={23} />
                  ) : report.policy === "MISS" ? (
                    <XCircle size={23} />
                  ) : (
                    <CircleHelp size={23} />
                  )}
                </div>
                <div>
                  <strong>
                    {report.policy === "MATCH"
                      ? "All required checks pass"
                      : report.policy === "MISS"
                        ? "At least one known check fails"
                        : "A conclusion needs more evidence"}
                  </strong>
                  <p>
                    {report.policy === "MATCH"
                      ? "The report satisfies every policy and evidence gate."
                      : report.policy === "MISS"
                        ? "Known failures remain failures even when other checks are unknown."
                        : "Unknown records or metrics prevent a fully evidenced match."}
                  </p>
                </div>
              </div>
              <div className="checks-list">
                {report.checks.map((check) => (
                  <div className="check-row" key={check.key}>
                    <span className={`check-icon ${check.state.toLowerCase()}`}>
                      {check.state === "PASS" ? (
                        <CheckCircle2 size={16} />
                      ) : check.state === "FAIL" ? (
                        <XCircle size={16} />
                      ) : (
                        <CircleHelp size={16} />
                      )}
                    </span>
                    <div>
                      <strong>{check.label}</strong>
                      <small>
                        {`Expected ${typeof check.expected === "string" ? check.expected : JSON.stringify(check.expected)}`}
                        {check.reason ? ` · ${check.reason}` : ""}
                      </small>
                    </div>
                    <span className="check-actual">
                      {check.actual !== null
                        ? decimal(check.actual)
                        : check.key.startsWith("evidence_") &&
                            check.state === "PASS"
                          ? "Verified"
                          : "Unknown"}
                    </span>
                    <Badge value={check.state} />
                  </div>
                ))}
              </div>
            </section>
            <div>
              <section className="panel findings-panel">
                <SectionHeading
                  title="Investigation notes"
                  subtitle="What the records support, and where they fall short."
                />
                {report.findings.length ? (
                  report.findings.map((finding, index) => (
                    <div
                      className={`finding ${finding.severity.toLowerCase()}`}
                      key={index}
                    >
                      <TriangleAlert size={17} />
                      <div>
                        <strong>{finding.title}</strong>
                        <p>{finding.detail}</p>
                        {finding.evidence?.slice(0, 3).map((hash) => (
                          <button
                            className="text-button mono"
                            onClick={() => showEvidence(hash)}
                            key={hash}
                          >
                            Source {shorten(hash, 5)}
                            <ArrowUpRight size={12} />
                          </button>
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="quiet-message">
                    No additional findings recorded.
                  </div>
                )}
                {report.notes.map((note, index) => (
                  <p key={index} className="report-note">
                    {note}
                  </p>
                ))}
              </section>
              <section className="panel coverage-panel">
                <SectionHeading
                  title="Reconstruction coverage"
                  subtitle={report.counts_population}
                />
                <div className="position-counts">
                  {Object.entries(report.counts).map(([key, value]) => (
                    <div key={key}>
                      <strong>{count(value)}</strong>
                      <span>{label(key)}</span>
                    </div>
                  ))}
                </div>
                <dl className="coverage-list">
                  {Object.entries(report.coverage)
                    .filter(([key]) => key !== "position_evidence")
                    .slice(0, 16)
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>{label(key)}</dt>
                        <dd>
                          {typeof value === "boolean" ? (
                            value ? (
                              "Yes"
                            ) : (
                              "No"
                            )
                          ) : value !== null && typeof value === "object" ? (
                            <CoverageDetails value={value} projected={report.report_view?.omitted_paths.some((path) =>
                              path === `coverage.${key}` || path.startsWith(`coverage.${key}.`),
                            )} />
                          ) : (
                            String(value ?? "Unknown")
                          )}
                        </dd>
                      </div>
                    ))}
                </dl>
              </section>
            </div>
          </div>
          {report.source === "live" && !!report.token_risk?.length && (
            <section className="panel token-risk-panel">
              <SectionHeading
                title="Current token controls and risk questions"
                subtitle="Current mint observations cannot establish historical sellability, legitimacy, or future returns."
              />
              {report.token_risk.map((token) => (
                <div className="token-risk-record" key={token.mint}>
                  <div className="token-risk-heading">
                    <div>
                      <strong className="mono" title={token.mint}>
                        {shorten(token.mint, 7)}
                      </strong>
                      <p>
                        {token.scope}
                        {token.observed_at
                          ? ` · observed ${dateTime(token.observed_at)}`
                          : " · evidence unavailable"}
                      </p>
                    </div>
                    <Badge value={token.status} />
                  </div>
                  <div className="checks-list">
                    {Object.entries(token.gates).map(([key, gate]) => (
                      <div className="check-row" key={key}>
                        <span
                          className={`check-icon ${gate.state.toLowerCase()}`}
                        >
                          {gate.state === "PASS" ? (
                            <CheckCircle2 size={16} />
                          ) : gate.state === "FAIL" ? (
                            <XCircle size={16} />
                          ) : (
                            <CircleHelp size={16} />
                          )}
                        </span>
                        <div>
                          <strong>{label(key)}</strong>
                          <small>{gate.detail}</small>
                        </div>
                        <Badge value={gate.state} />
                      </div>
                    ))}
                  </div>
                  <div className="token-risk-sources">
                    {token.evidence.map((hash) => (
                      <button
                        className="text-button mono"
                        onClick={() => showEvidence(hash)}
                        key={hash}
                      >
                        Mint source {shorten(hash, 6)}{" "}
                        <ArrowUpRight size={12} />
                      </button>
                    ))}
                    {token.notes?.map((note, index) => (
                      <p key={index}>{note}</p>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}
          <section className="panel">
            <SectionHeading
              title="All screening measures"
              subtitle="Values stay exact decimal strings; unavailable measures include the reason."
            />
            <div className="all-metrics-grid">
              {metricDefinitions.map((metric) => (
                <div key={metric.key}>
                  <span title={metric.hint}>{metric.name}</span>
                  <strong>
                    <MetricValue
                      metric={report.metrics[metric.key]}
                      suffix={metric.suffix}
                    />
                  </strong>
                  <small>
                    {report.metrics[metric.key]?.status === "known"
                      ? `Population: ${report.metrics[metric.key]?.population ?? "see methodology"}`
                      : report.metrics[metric.key]?.reason || "Not available"}
                  </small>
                  {metric.key === "positive_weeks" && (
                    <div className="metric-interval-detail">
                      <span>Independent four-week interval</span>
                      {(report.metric_coverage?.positive_weeks ??
                      report.metric_intervals?.four_weeks) ? (
                        <>
                          <p>
                            {dateTime(
                              (
                                report.metric_coverage?.positive_weeks ??
                                report.metric_intervals?.four_weeks
                              )?.start,
                            )}
                            {" → "}
                            {dateTime(
                              (
                                report.metric_coverage?.positive_weeks ??
                                report.metric_intervals?.four_weeks
                              )?.end,
                            )}{" "}
                            · UTC
                          </p>
                          <p>
                            Coverage:{" "}
                            {label(
                              (
                                report.metric_coverage?.positive_weeks ??
                                report.metric_intervals?.four_weeks
                              )?.status ?? "unknown",
                            )}
                          </p>
                          {(
                            report.metric_coverage?.positive_weeks ??
                            report.metric_intervals?.four_weeks
                          )?.reason && (
                            <p>
                              {
                                (
                                  report.metric_coverage?.positive_weeks ??
                                  report.metric_intervals?.four_weeks
                                )?.reason
                              }
                            </p>
                          )}
                        </>
                      ) : (
                        <p>
                          Coverage of the independent 28-day interval is not
                          established in this saved report.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
      {tab === "positions" && (
        <section className="panel records-panel">
          <SectionHeading
            title="Position reconstruction"
            subtitle="FIFO lots, closed and open positions, interrupted sequences, and unknown cost bases."
          />
          <RecordTable records={report.positions} kind="positions" />
        </section>
      )}
      {tab === "events" && (
        <section className="panel records-panel">
          <SectionHeading
            title="Normalized ledger & flows"
            subtitle="Buys, sells, fees, transfers, and unsupported records remain visible."
          />
          <RecordTable records={report.events} kind="events" />
        </section>
      )}
      {tab === "market" && (
        <section className="panel observations-panel">
          <SectionHeading
            title="Current token observations"
            subtitle="Up to five token mints, with current indicative GeckoTerminal observations."
            action={
              <Button
                variant="secondary"
                icon={Search}
                busy={busy === "enrich"}
                onClick={async () => {
                  const result = await run(
                    "enrich",
                    `/reports/${encodeURIComponent(report.id)}/enrich?view=display`,
                    {},
                    "POST",
                    "Current observations saved. Historical metrics remain unchanged.",
                  ) as Report | undefined;
                  if (result?.id === report.id) updateReport(result);
                }}
              >
                Get current token observations
              </Button>
            }
          />
          <div className="inline-info">
            <CircleHelp size={17} />
            <span>
              {report.market_observation_scope ||
                "Current observations are indicative. They never substitute for missing historical prices or change the reconstructed ledger."}
            </span>
          </div>
          {report.market_observation_note && (
            <div className="inline-alert">{report.market_observation_note}</div>
          )}
          {report.market_observations?.length ? (
            <div className="market-records">
              {report.market_observations.map((observation, index) => (
                <pre key={index}>{JSON.stringify(observation, null, 2)}</pre>
              ))}
            </div>
          ) : (
            <Empty
              title="No current observations saved"
              detail="Fetch a small set of current indicative token observations for this live report. This uses the public GeckoTerminal read path."
            />
          )}
        </section>
      )}
      {tab === "evidence" && (
        <section className="panel evidence-panel">
          <SectionHeading
            title="Inspect the source records"
            subtitle="Archived JSON records are addressed and verified by their SHA-256 checksum."
            action={
              <a
                className="button secondary"
                href={`/api/export/reports/${encodeURIComponent(report.id)}.json`}
                download
              >
                <FileJson size={15} /> Export report JSON
              </a>
            }
          />
          {report.source === "demo" && (
            <div className="inline-info">
              <FlaskConical size={16} />
              <span>
                These archives contain synthetic normalized records for the
                offline demonstration.
              </span>
            </div>
          )}
          {report.evidence.length ? (
            <>
              <div className="evidence-list">
                {report.evidence
                  .slice(evidencePage * 25, evidencePage * 25 + 25)
                  .map((record, index) => (
                    <div key={`${record.hash}-${index}`}>
                      <span className="evidence-icon">
                        <ShieldCheck size={20} />
                      </span>
                      <div>
                        <strong>{label(record.kind)}</strong>
                        <span className="mono">{record.hash}</span>
                        {record.signature && (
                          <small className="mono">
                            Transaction: {shorten(record.signature, 12)}
                          </small>
                        )}
                      </div>
                      <Button
                        variant="secondary"
                        busy={busy === "evidence"}
                        onClick={() => showEvidence(record.hash)}
                        icon={Search}
                      >
                        Inspect record
                      </Button>
                    </div>
                  ))}
              </div>
              <div className="pagination">
                <span>
                  {evidencePage * 25 + 1}–
                  {Math.min(evidencePage * 25 + 25, report.evidence.length)} of{" "}
                  {count(report.evidence.length)} archives
                </span>
                <div>
                  <Button
                    variant="secondary"
                    disabled={evidencePage === 0}
                    onClick={() => setEvidencePage((page) => page - 1)}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={evidencePage * 25 + 25 >= report.evidence.length}
                    onClick={() => setEvidencePage((page) => page + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <Empty
              title="No verified source archives"
              detail="This report has no archived source records to inspect. Its evidence status remains separate from policy fit."
              icon={ShieldCheck}
            />
          )}
        </section>
      )}
    </>
  );
}
