import { useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, Download, Play, RefreshCw, Search, Square, Star, TriangleAlert } from "lucide-react";
import type { Actions } from "./App";
import type { PaperObservation, PaperSettings, Preset, Screening } from "./types";
import { Badge, Button, Empty, SectionHeading } from "./components";
import { api } from "./api";
import { count, dateTime, decimal, label, shorten } from "./format";

export const defaultPaperSettings: PaperSettings = {
  capital_sol: "10", entry_sol: "0.1", max_open_positions: 5,
  reaction_delay_seconds: 5, adverse_bps: 100, execution_fee_sol: "0.00001",
  max_price_impact_pct: "5", max_events: 1000, max_quotes: 500,
  max_duration_minutes: 60,
};
const defaultScreeningPreset: Preset = {
  name: "Sampled wallet screening", min_supported_swaps: 2, min_matched_sales: 1,
  max_rapid_sale_pct: "50", require_positive_conditional_profit: false,
  exclude_active_mint_authority: true, exclude_active_freeze_authority: true,
  exclude_restrictive_extensions: true, continuation_max_transactions: 20,
  continuation_max_credits: 100, continuation_max_accounts: 10,
};

const settingFields: { key: keyof PaperSettings; name: string; min: number; max?: number; step?: string; hint: string }[] = [
  { key: "capital_sol", name: "Simulated capital (SOL)", min: 0.000000001, max: 1000000, step: "any", hint: "Known starting cash; no initial token holdings." },
  { key: "entry_sol", name: "Fixed entry (SOL)", min: 0.000000001, max: 1000000, step: "any", hint: "Amount for each eligible first buy." },
  { key: "max_open_positions", name: "Maximum open positions", min: 1, max: 25, hint: "Additional entries are excluded at this limit." },
  { key: "reaction_delay_seconds", name: "Reaction delay (seconds)", min: 0, max: 3600, hint: "Whole seconds after detection and decoding, not the leader's trade." },
  { key: "adverse_bps", name: "Adverse execution (basis points)", min: 0, max: 5000, hint: "Modeled reduction to quoted proceeds; 100 bps = 1%." },
  { key: "execution_fee_sol", name: "Modeled execution cost (SOL)", min: 0, max: 10, step: "any", hint: "Separate cost per hypothetical entry or exit." },
  { key: "max_price_impact_pct", name: "Maximum quote price impact (%)", min: 0, max: 100, step: "any", hint: "Quotes exceeding this limit cannot supply a paper fill." },
  { key: "max_events", name: "Signal budget", min: 1, max: 10000, hint: "Maximum events retained in this run." },
  { key: "max_quotes", name: "Quote budget", min: 1, max: 10000, hint: "Includes entry, exit and open-position mark requests." },
  { key: "max_duration_minutes", name: "Observation duration (minutes)", min: 1, max: 480, hint: "Stops collection when the time budget is exhausted (at most 8 hours)." },
];

function solInputUnits(value: string): bigint | undefined {
  if (value.length > 40 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,9})?$/.test(value)) return undefined;
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 1_000_000_000n + BigInt(fraction.padEnd(9, "0"));
}

function detail(value: unknown): string {
  if (value === undefined || value === null) return "Unknown / not supplied";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}

function Amount({ value, unknown = "Unknown" }: { value?: unknown; unknown?: string }) {
  const supported = typeof value === "string" && /^[+-]?\d+(?:\.\d+)?$/.test(value);
  return <span title={supported ? value : unknown}>{supported ? <>{decimal(value, 9)}<small> SOL</small></> : unknown}</span>;
}

export function paperSolFromLamports(value: unknown): string | undefined {
  if (typeof value !== "string" || !/^-?\d{1,512}$/.test(value)) return undefined;
  const units = BigInt(value);
  const absolute = units < 0n ? -units : units;
  const fraction = (absolute % 1_000_000_000n).toString().padStart(9, "0").replace(/0+$/, "");
  return `${units < 0n ? "-" : ""}${absolute / 1_000_000_000n}${fraction ? `.${fraction}` : ""}`;
}

function Exposure({ value }: { value: unknown }) {
  if (!Array.isArray(value)) return <p>Open exposure not established.</p>;
  if (!value.length) return <p>No open exposure identified in the supported sample. Complete wallet inventory remains unknown.</p>;
  return <div className="research-exposure-list">{value.map((item, index) => {
    if (!item || typeof item !== "object") return <p key={index}>Unresolved open holding</p>;
    const position = item as Record<string, unknown>;
    return <div key={index}><strong className="mono">{shorten(String(position.mint ?? "Unknown mint"))}</strong><p>{label(String(position.status ?? "unresolved"))} · {String(position.quantity_raw ?? "unknown")} raw units</p><small>Remaining basis <Amount value={position.remaining_basis_sol} /> · Market value <Amount value={position.market_value_sol} /></small></div>;
  })}</div>;
}

function EvidenceLinks({ evidence, showEvidence }: { evidence?: string[]; showEvidence: (hash: string) => void }) {
  return <div className="research-evidence">{[...new Set(evidence ?? [])].filter((hash) => /^[a-f0-9]{64}$/.test(hash)).slice(0, 8).map((hash) => (
    <button key={hash} className="text-button mono" onClick={() => showEvidence(hash)}>Source {shorten(hash, 5)}</button>
  ))}</div>;
}

export function screeningReviewKey(screening: Screening): string {
  return JSON.stringify([screening.current_source_availability, screening.current_result,
    screening.current_label, screening.current_reason, screening.current_identity, screening.current_eligibility]);
}

export function canObserveScreening(screening: Screening | undefined): boolean {
  if (!screening) return false;
  if (screening.current_eligibility) return screening.current_eligibility.can_start_observation === true;
  return screening.identity?.state === "PASS" && screening.result !== "excluded_by_preset";
}

export function newerObservationState(listed: PaperObservation, opened: PaperObservation): boolean {
  return listed.id === opened.id && Date.parse(listed.updated_at) > Date.parse(opened.updated_at);
}

export function ScreeningDetail({ screening, showEvidence }: { screening: Screening; showEvidence: (hash: string) => void }) {
  const trading = screening.trading_evidence;
  const qualification = screening.strict_qualification;
  const sourcesMissing = screening.current_source_availability?.state === "UNKNOWN";
  const identityMissing = screening.current_identity && screening.current_identity.state !== "PASS";
  const { current_source_availability, current_result, current_label, current_reason, current_identity, current_eligibility, ...savedSnapshot } = screening;
  return <>
    <div className="research-conclusion" role="status">
      <Badge value={screening.current_result ?? screening.result}>{screening.current_label ?? screening.label}</Badge>
      <p>{screening.current_reason ?? screening.reason}</p>
      <small>Saved assessment: {screening.label} · {dateTime(screening.created_at)} UTC</small>
      <small>Worth observing describes research eligibility. Conditional observations do not establish verified wallet profit.</small>
    </div>
    {sourcesMissing && <div className="inline-alert" role="status"><TriangleAlert size={18} /><div><strong>Current screening evidence unavailable</strong><p>Required cited archives are missing or unreadable. The saved assessment is retained, but its original positive result cannot support a current observation decision.</p><EvidenceLinks evidence={screening.current_source_availability?.missing.filter((hash): hash is string => typeof hash === "string")} showEvidence={showEvidence} /></div></div>}
    {screening.current_identity && <div className={identityMissing ? "inline-alert" : "inline-info"} role="status"><Badge value={screening.current_identity.state}>Current native identity: {label(screening.current_identity.state)}</Badge><div><p>{screening.current_identity.reason}</p><EvidenceLinks evidence={screening.current_identity.evidence} showEvidence={showEvidence} /></div></div>}
    <details className="research-subpanel"><summary>Original saved assessment and settings</summary><pre>{detail(savedSnapshot)}</pre></details>
    {!!screening.reasons?.length && <><h3>Saved assessment reasons</h3><ul className="research-reasons">{screening.reasons.map((reason, index) => <li key={index}>{typeof reason === "string" ? reason : <><strong>{label(reason.key)}</strong> · {label(reason.state)} · {reason.reason}<EvidenceLinks evidence={reason.evidence} showEvidence={showEvidence} /></>}</li>)}</ul></>}
    <div className="research-metrics">
      <div><span>Saved supported swaps</span><strong>{trading.supported_swaps ?? "Unknown"}</strong><small>{trading.buy_signals ?? "?"} buys · {trading.sell_signals ?? "?"} sells{sourcesMissing ? " · original record; source evidence unavailable" : ""}</small></div>
      <div><span>Conditional matched-lot P&L</span><strong><Amount value={sourcesMissing ? null : trading.conditional_matched_lot_profit_sol} unknown={sourcesMissing ? "Current source evidence unavailable" : "Unknown"} /></strong><small>Assumes no undiscovered earlier inventory or intervening flows.</small></div>
      <div><span>Saved matched sales</span><strong>{trading.matched_sales ?? "Unknown"}</strong><small>{trading.unmatched_sales ?? trading.unresolved_basis_sales ?? "Unknown"} unmatched or basis-unresolved sales{sourcesMissing ? " · original record" : ""}</small></div>
    </div>
    <div className="research-grid">
      <section className="research-subpanel"><h3>Observed open exposure</h3><Exposure value={trading.open_exposure} /></section>
      <section className="research-subpanel"><h3>Early exits</h3><p>Inspect the 90% exit alongside the final holding time. A small remainder can make the final hold look longer than most of the exposure.</p><details><summary>Observed exit timing and checks</summary><pre>{detail(trading.early_exits)}</pre></details></section>
    </div>
    <section className="research-subpanel">
      <SectionHeading title="Strict financial qualification" subtitle="The original historical evidence and preset requirements remain separate." action={<Badge value={sourcesMissing || identityMissing ? "unknown" : qualification?.qualified ? "qualified" : qualification?.financial_policy ?? "unknown"} />} />
      {(sourcesMissing || identityMissing) && <p>Current evidence does not support the saved qualification. The original qualification record remains inspectable above.</p>}
      <p>{qualification?.reason ?? "Strict qualification unavailable in this assessment."}</p>
      {qualification && <small>{qualification.failed_checks?.length ?? 0} failed · {qualification.unknown_checks?.length ?? 0} unknown checks · Saved preset {qualification.preset_version ?? "unknown"}</small>}
      <details><summary>Frozen sampled screening preset</summary><pre>{detail(screening.preset_snapshot)}</pre></details>
    </section>
    <section className="research-subpanel">
      <SectionHeading title="Collection scope and stop reason" />
      <dl className="research-facts">
        <div><dt>Collection stopped because</dt><dd>{screening.collection.stop_reason ?? "Not recorded"}</dd></div>
        <div><dt>Records examined</dt><dd>{screening.collection.transactions ?? "Unknown"} transactions · {screening.collection.pages ?? "Unknown"} pages · {screening.collection.credits ?? "Unknown"} credits</dd></div>
        <div><dt>Scope</dt><dd><pre>{detail(trading.scope ?? screening.collection.scope)}</pre></dd></div>
        {trading.window && <div><dt>Saved window (UTC)</dt><dd>{dateTime(trading.window.start)} → {dateTime(trading.window.end)}</dd></div>}
      </dl>
      {!!screening.collection.gaps?.length && <details open><summary>Missing collection evidence ({screening.collection.gaps.length})</summary><pre>{detail(screening.collection.gaps)}</pre></details>}
      <p>{screening.continuation?.reason ?? "Review this sample before extending collection."}</p>
    </section>
    <section className="research-subpanel">
      <SectionHeading title="Evidence-backed risk observations" subtitle="Capabilities and observed behavior; missing evidence stays unknown. These observations do not infer intent." />
      {screening.risk_observations.length ? screening.risk_observations.map((risk, index) => <article className="research-risk" key={`${risk.key}-${index}`}>
        <div><strong>{label(risk.key)}</strong><Badge value={sourcesMissing ? "unknown" : risk.state} /></div>
        {sourcesMissing && <small>Saved finding state: {label(risk.state)} · current source support unavailable</small>}
        {risk.mint && <small className="mono">Mint {risk.mint}</small>}
        <p>{risk.reason}</p>
        {risk.actual !== undefined && <pre>{detail(risk.actual)}</pre>}
        {risk.relationship !== undefined && <pre>{detail(risk.relationship)}</pre>}
        <EvidenceLinks evidence={risk.evidence} showEvidence={showEvidence} />
      </article>) : <p>No reviewed observations supplied. Risk remains unresolved.</p>}
    </section>
  </>;
}

export function PaperDetail({ observation, showEvidence = () => undefined }: { observation: PaperObservation; showEvidence?: (hash: string) => void }) {
  const summary = observation.summary;
  const observer = observation.observer;
  const connected = observer?.status === "listening";
  const unavailableQuotes = observation.quote_requests.filter((quote) => ["unavailable", "interrupted", "cancelled"].includes(String(quote.status)));
  const sourceAvailability = summary.source_availability && typeof summary.source_availability === "object"
    ? summary.source_availability as Record<string, unknown> : undefined;
  const sourcesMissing = sourceAvailability?.state === "UNKNOWN";
  const performanceValue = sourcesMissing ? null : "supported_economic_pnl_sol" in summary
    ? summary.supported_economic_pnl_sol : summary.economic_pnl_sol;
  return <>
    <div className="research-conclusion">
      <Badge value={observation.status} />
      <p>{observation.stop_reason ? label(observation.stop_reason) : connected ? "Listening for future address notifications and decoding eligible signals within the saved budgets." : "Paper run started; check the monitoring connection below before relying on signal capture."}</p>
      <small>Started {dateTime(observation.started_at)} · Updated {dateTime(observation.updated_at)} UTC</small>
    </div>
    <section className="research-subpanel research-monitoring" aria-label="Live monitoring connection">
      <SectionHeading title="Monitoring connection" subtitle="Notifications mention this address; they do not prove complete wallet activity." action={<Badge value={connected ? "known" : observer?.status ?? "unknown"}>{connected ? "Listening for address mentions" : label(observer?.status ?? "connection status unavailable")}</Badge>} />
      {observation.status === "running" && !connected && <p className="research-connection-warning">Monitoring is not connected. New signals cannot supply paper entries while the connection is unavailable. Unobserved intervals remain gaps.</p>}
      {observer?.last_error && <div className={connected ? "inline-info" : "inline-alert"} role="status"><TriangleAlert size={18} /><div><strong>{connected ? "Prior connection failure · now reconnected" : "Connection issue"}</strong><p>{observer.last_error.message}</p><small>{label(observer.last_error.code)}{observer.last_error.http_status !== undefined ? ` · HTTP ${observer.last_error.http_status}` : ""} · {dateTime(observer.last_error.at)} UTC</small></div></div>}
      {observer?.stop_reason && <p>Monitor stop reason: {label(observer.stop_reason)}. {observer.status === "budget_exhausted" ? "Create a new run for a new budget; the original settings remain fixed." : observer.status === "paused" ? "Resume retries within the original run budgets. Missed periods are not replayed." : ""}</p>}
      <dl className="research-settings-snapshot"><div><dt>Notification allowance</dt><dd>{observer?.notifications ?? "Unknown"} / {observer?.limits?.max_notifications ?? "Unknown"}</dd></div><div><dt>Transaction retrieval allowance</dt><dd>{observer?.transactions ?? "Unknown"} / {observer?.limits?.max_transactions ?? "Unknown"}</dd></div><div><dt>Connection attempts</dt><dd>{observer?.connection_attempts ?? "Not recorded"}</dd></div></dl>
      {observer?.monitoring_gap_started_at && <small>Current unobserved interval began {dateTime(observer.monitoring_gap_started_at)} UTC.</small>}
      {!!observation.notifications?.length && <details><summary>Detected notifications, including exclusions and retrieval failures ({observation.notifications.length})</summary><div className="research-signal-list">{observation.notifications.slice(-100).reverse().map((notification, index) => <details key={String(notification.id ?? index)}><summary>{label(String(notification.status ?? "recorded"))} · {shorten(String(notification.signature ?? "Unknown transaction"))}{typeof notification.reason === "string" ? ` · ${notification.reason}` : ""}</summary><pre>{detail(notification)}</pre></details>)}</div></details>}
    </section>
    <div className="research-metrics">
      <div><span>Simulated cash</span><strong><Amount value={summary.cash_sol} /></strong><small>Started with <Amount value={summary.initial_capital_sol} /></small></div>
      <div><span>Recorded realised paper P&L</span><strong><Amount value={summary.realised_pnl_sol} /></strong><small>{count(summary.closed_positions)} closed paper positions{sourcesMissing ? " · original retained values; source evidence unavailable" : ""}</small></div>
      <div><span>Paper P&L including open exposure</span><strong><Amount value={performanceValue} unknown={sourcesMissing ? "Unsupported source evidence" : "Incomplete valuation"} /></strong><small>Valuation {label(summary.valuation_status)}</small></div>
      <div><span>Open position cost</span><strong><Amount value={summary.open_cost_sol} /></strong><small>{count(summary.open_positions)} open paper positions</small></div>
      <div><span>Open liquidation quote value</span><strong><Amount value={summary.marked_open_value_sol} unknown="Open value unavailable" /></strong><small>Current quote after modeled execution costs.</small></div>
      <div><span>Captured signals / quotes</span><strong>{count(summary.signal_count)} / {count(summary.quote_count)}</strong><small>{count(summary.unavailable_quotes)} unavailable quotes · {observation.gaps?.length ?? 0} recorded monitoring gaps</small></div>
    </div>
    {!summary.complete_observation && <div className="inline-alert" role="status"><TriangleAlert size={18} /><p>This observation is incomplete. Unavailable quotes, unvalued exposure and monitoring gaps remain part of the result.</p></div>}
    {sourcesMissing && <div className="inline-alert" role="status"><TriangleAlert size={18} /><p>Required saved signal or quote evidence is unavailable. Original recorded values remain retained, but cannot support a complete positive copying conclusion.</p></div>}
    {sourceAvailability && <details className="research-subpanel"><summary>Signal and quote source availability · {label(String(sourceAvailability.state ?? "unknown"))}</summary><pre>{detail(sourceAvailability)}</pre></details>}
    {observation.copyability && <section className="research-subpanel"><SectionHeading title="Copy-research preset result" subtitle="Defined observed follower behavior; this result does not imply trader intent." action={<Badge value={observation.copyability.status} />} /><ul className="research-reasons">{observation.copyability.reasons.map((reason, index) => <li key={index}>{detail(reason)}</li>)}</ul><details><summary>Frozen copy-research preset</summary><pre>{detail(observation.copyability.preset_snapshot)}</pre></details></section>}
    {!!observation.risk_observations?.length && <section className="research-subpanel"><SectionHeading title="Observed follower disadvantages" subtitle="Evidence and timing for this strategy and run." />{observation.risk_observations.map((risk, index) => <article className="research-risk" key={`${risk.key}-${index}`}><div><strong>{label(risk.key)}</strong><Badge value={risk.state} /></div><p>{risk.reason}</p>{risk.actual !== undefined && <pre>{detail(risk.actual)}</pre>}<EvidenceLinks evidence={risk.evidence} showEvidence={showEvidence} /></article>)}</section>}
    <section className="research-subpanel"><SectionHeading title="Original run settings" subtitle="Frozen at run creation. New settings require a new run." /><dl className="research-settings-snapshot">{settingFields.map((field) => <div key={field.key}><dt>{field.name}</dt><dd>{String(observation.settings[field.key])}</dd></div>)}</dl></section>
    <section className="research-subpanel"><SectionHeading title="Paper positions" subtitle="Open losses and unavailable exits remain visible. Quote-based results are hypothetical, not actual fills." />
      {observation.positions.length ? <div className="table-scroll"><table className="report-table"><thead><tr><th>Mint / state</th><th>Entry cost</th><th>Quoted exit / mark</th><th>Result and timing</th></tr></thead><tbody>{observation.positions.map((position, index) => <tr key={String(position.id ?? index)}>
        <td><span className="mono" title={String(position.mint ?? "")}>{shorten(String(position.mint ?? "Unknown"))}</span><small>{detail(position.status ?? position.state)}</small></td>
        <td><Amount value={position.entry_cost_sol ?? position.cost_sol ?? paperSolFromLamports(position.cost_lamports)} /><small>{dateTime(typeof position.opened_at === "string" ? position.opened_at : undefined)}</small></td>
        <td><Amount value={position.exit_proceeds_sol ?? paperSolFromLamports(position.net_exit_lamports) ?? (position.mark && typeof position.mark === "object" ? paperSolFromLamports((position.mark as Record<string, unknown>).net_value_lamports) : undefined)} unknown="Quote / value unavailable" />{position.exit_unavailable === true && <small>Leader exit observed · sell quote unavailable</small>}</td>
        <td><details><summary>Inspect retained position</summary><pre>{detail(position)}</pre></details></td>
      </tr>)}</tbody></table></div> : <p>No paper entries yet. Excluded and additional leader signals are retained below.</p>}
    </section>
    <section className="research-subpanel"><SectionHeading title="Detected signals and exclusions" subtitle="Detection, decode time and the selected delay determine the earliest eligible quote time." />
      {observation.signals.length ? <div className="research-signal-list">{observation.signals.slice(-100).reverse().map((signal, index) => <details key={String(signal.id ?? index)}><summary>{label(String(signal.side ?? signal.kind ?? "Signal"))} · {shorten(String(signal.mint ?? signal.signature ?? "Unknown"))} · {label(String(signal.status ?? signal.decision ?? "Recorded"))}</summary><pre>{detail(signal)}</pre></details>)}</div> : <p>No signals detected during this run.</p>}
      {observation.signals.length > 100 && <small>Showing the latest 100 signals. Export retains the full saved run.</small>}
    </section>
    <section className="research-subpanel"><SectionHeading title="Captured quotes and modeled costs" subtitle="Observed quote responses are retained separately from adverse-execution and network-cost assumptions. Quotes do not guarantee execution." />
      <p>Provider and pool fees already included in quote output are counted once. The adverse output haircut and one additional SOL execution cost per paper entry or exit are modeled.</p>
      {!!unavailableQuotes.length && <div className="research-quote-failures"><h3>Unavailable or interrupted quote requests</h3>{unavailableQuotes.map((quote, index) => <article className="research-risk" key={String(quote.id ?? index)}><div><strong>{label(String(quote.action ?? "quote"))} · {shorten(String(quote.mint ?? "Unknown mint"))}</strong><Badge value="unknown">{label(String(quote.status))}</Badge></div><p>{quote.reason === "access_denied" ? "The quote provider denied read-only access. This request produced no hypothetical fill; retrying with hindsight will not replace it." : label(String(quote.reason ?? "Quote unavailable; no hypothetical fill assigned"))}</p><small>Eligible from {dateTime(typeof quote.due_at === "string" ? quote.due_at : undefined)} UTC</small><EvidenceLinks evidence={typeof quote.quote_evidence_hash === "string" ? [quote.quote_evidence_hash] : []} showEvidence={showEvidence} /></article>)}</div>}
      <details><summary>{observation.quote_requests.length} quote records, including unavailable requests</summary><pre>{detail(observation.quote_requests)}</pre></details>
    </section>
    {!!observation.gaps?.length && <section className="research-subpanel"><SectionHeading title="Monitoring gaps" subtitle="Missed periods are not replayed as if followed live." /><pre>{detail(observation.gaps)}</pre></section>}
    <details className="research-subpanel"><summary>Complete saved observation</summary><pre>{detail(observation)}</pre></details>
  </>;
}

export function ResearchView({ state, busy, run, open, navigate, refresh, showEvidence }: Actions & { showEvidence: (hash: string) => void }) {
  const screenings = state.screenings ?? [];
  const observations = state.observations ?? [];
  const [screeningId, setScreeningId] = useState("");
  const [observationId, setObservationId] = useState("");
  const [screeningDetail, setScreeningDetail] = useState<Screening | null>(null);
  const [observationDetail, setObservationDetail] = useState<PaperObservation | null>(null);
  const [detailError, setDetailError] = useState("");
  const [reportId, setReportId] = useState("");
  const [settings, setSettings] = useState<PaperSettings>({ ...defaultPaperSettings });
  const [screeningPreset, setScreeningPreset] = useState<Preset>({ ...defaultScreeningPreset });
  const [transactionLimit, setTransactionLimit] = useState(20);
  const [formError, setFormError] = useState("");
  const screeningPanelRef = useRef<HTMLElement>(null);
  const paperSetupRef = useRef<HTMLElement>(null);
  const paperResultsRef = useRef<HTMLElement>(null);
  const screening = screeningDetail?.id === screeningId ? screeningDetail : screenings.find((item) => item.id === screeningId) ?? screenings[0];
  const observation = observationDetail?.id === observationId ? observationDetail : observations.find((item) => item.id === observationId) ?? observations[0];
  const reports = state.reports.filter((report) => !report.preview);
  const report = reports.find((item) => item.id === reportId) ?? reports[0];
  const watched = screening && state.watchlist.some((wallet) => wallet.address === screening.address);
  const canStart = canObserveScreening(screening);
  const reopen = async (kind: "screenings" | "observations", id: string) => {
    setDetailError("");
    try {
      if (kind === "screenings") { setScreeningId(id); const detail = await api<Screening>(`/screenings/${encodeURIComponent(id)}`); await refresh(); setScreeningDetail(detail); }
      else { setObservationId(id); setObservationDetail(await api<PaperObservation>(`/observations/${encodeURIComponent(id)}`)); }
    } catch (error) { setDetailError(error instanceof Error ? error.message : "Saved research could not be reopened."); }
  };
  useEffect(() => {
    if (observationDetail && observations.some((item) => newerObservationState(item, observationDetail))) setObservationDetail(null);
  }, [observations, observationDetail]);
  useEffect(() => {
    if (screeningDetail && screenings.some((item) => item.id === screeningDetail.id && screeningReviewKey(item) !== screeningReviewKey(screeningDetail))) setScreeningDetail(null);
  }, [screenings, screeningDetail]);
  const screen = async () => {
    if (!report) return;
    const result = await run("screen-wallet", "/screenings", { report_id: report.id, preset: screeningPreset }, "POST", "Screening assessment saved. Strict qualification remains separate.") as Screening | { screening_id?: string; id?: string } | undefined;
    if (result) { setScreeningId("screening_id" in result ? result.screening_id ?? result.id ?? "" : result.id ?? ""); setScreeningDetail(null); screeningPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  };
  const start = async () => {
    if (!screening) return;
    setFormError("");
    const capital = solInputUnits(settings.capital_sol), entry = solInputUnits(settings.entry_sol), fee = solInputUnits(settings.execution_fee_sol);
    if (capital === undefined || entry === undefined || fee === undefined) {
      setFormError("Use plain decimal SOL amounts with at most nine fractional digits; scientific notation is not supported."); return;
    }
    if (capital <= 0n || entry <= 0n || entry + fee > capital) {
      setFormError("Capital must cover the positive fixed entry and modeled execution cost."); return;
    }
    const result = await run("paper-start", "/observations", { screening_id: screening.id, settings }, "POST", "Forward quote-based paper observation started with frozen settings.") as PaperObservation | { observation_id?: string; id?: string } | undefined;
    if (result) { setObservationId(typeof result.observation_id === "string" ? result.observation_id : result.id ?? ""); setObservationDetail(null); paperResultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  };
  const changeRun = async (action: "stop" | "resume" | "mark") => {
    if (!observation) return;
    const result = await run(`paper-${action}`, `/observations/${encodeURIComponent(observation.id)}/${action}`, {}, "POST", action === "mark" ? "Current open-position quote request saved." : `Observation ${action === "stop" ? "stopped" : "resumed"}.`) as PaperObservation | undefined;
    if (result?.id) setObservationDetail(result); else setObservationDetail(null);
  };
  return <>
    <div className="research-workflow"><span>Discover / paste</span><ArrowRight size={14} /><span>Native identity</span><ArrowRight size={14} /><span>Screen & inspect</span><ArrowRight size={14} /><span>Shortlist</span><ArrowRight size={14} /><span>Observe & compare</span></div>
    {detailError && <div className="inline-alert" role="alert">{detailError}</div>}
    <section className="panel">
      <SectionHeading title="Save a screening assessment" subtitle="A bounded sample can be useful while full historical qualification remains unresolved." action={<Button icon={Search} variant="secondary" onClick={() => navigate("discover")}>Discover or paste wallets</Button>} />
      {reports.length ? <div className="research-action-row"><label className="research-report-picker">Saved report<select aria-label="Report to screen" value={report?.id ?? ""} onChange={(event) => setReportId(event.target.value)}>{reports.map((item) => <option value={item.id} key={item.id}>{item.source === "demo" ? "SYNTHETIC · " : ""}{item.label || shorten(item.address)} · {dateTime(item.created_at)}</option>)}</select></label><Button icon={Search} busy={busy === "screen-wallet"} disabled={!!busy} onClick={screen}>Screen and save assessment</Button><Button variant="secondary" disabled={!report || !!busy} onClick={() => report && open(report)}>Inspect original report</Button></div> : <Empty title="Start with a wallet sample" detail="Discover or import public addresses, check native identity and investigate selected wallets. Their saved reports can be screened here." action={<Button onClick={() => navigate("discover")}>Find or paste wallets</Button>} />}
      <details className="research-subpanel"><summary>Adjust sampled screening preset</summary><p>These settings affect a new sampled assessment. The original strict financial preset stays separate; saved assessments keep their settings.</p><div className="research-setting-grid">
        {(["min_supported_swaps", "min_matched_sales", "max_rapid_sale_pct", "continuation_max_transactions", "continuation_max_credits", "continuation_max_accounts"] as const).map((key) => <label key={key}>{label(key)}<input type="number" aria-label={label(key)} min={key === "min_matched_sales" || key === "max_rapid_sale_pct" ? 0 : 1} max={key === "max_rapid_sale_pct" ? 100 : undefined} step="1" value={String(screeningPreset[key])} onChange={(event) => setScreeningPreset((current) => ({ ...current, [key]: key === "max_rapid_sale_pct" ? event.target.value : Number(event.target.value) }))} /></label>)}
      </div><div className="research-checkboxes">{(["require_positive_conditional_profit", "exclude_active_mint_authority", "exclude_active_freeze_authority", "exclude_restrictive_extensions"] as const).map((key) => <label key={key}><input type="checkbox" checked={screeningPreset[key] === true} onChange={(event) => setScreeningPreset((current) => ({ ...current, [key]: event.target.checked }))} />{label(key)}</label>)}</div></details>
    </section>
    <section className="panel" ref={screeningPanelRef}>
      <SectionHeading title="Saved screenings" subtitle={`${count(screenings.length)} immutable assessments · Every result retains its reasons and collection limits.`} />
      {screening ? <>
        <div className="research-action-row"><label className="research-report-picker">Assessment<select aria-label="Saved screening assessment" value={screening.id} onChange={(event) => void reopen("screenings", event.target.value)}>{screenings.map((item) => <option key={item.id} value={item.id}>{shorten(item.address)} · {item.current_label ?? item.label} · {dateTime(item.created_at)}</option>)}</select></label><Button variant="secondary" disabled={!!busy} onClick={() => reopen("screenings", screening.id)}>Reopen saved assessment</Button><a className="button secondary" href={`/api/screenings/${encodeURIComponent(screening.id)}/export`} download><Download size={15} /> Export screening</a></div>
        <p className="mono research-address">{screening.address}</p>
        <ScreeningDetail screening={screening} showEvidence={showEvidence} />
        <div className="research-action-row"><label>Additional transaction budget<input type="number" aria-label="Continue investigation transaction budget" min={1} max={screening.continuation?.budget?.max_transactions ?? 20} value={transactionLimit} onChange={(event) => setTransactionLimit(Number(event.target.value))} /></label><Button icon={RefreshCw} variant="secondary" disabled={!!busy || !screening.continuation?.recommended || !Number.isInteger(transactionLimit) || transactionLimit < 1} busy={busy === "screen-continue"} onClick={() => run("screen-continue", `/screenings/${encodeURIComponent(screening.id)}/continue`, { transaction_limit: transactionLimit }, "POST", "Budgeted continuation queued. The saved assessment stays unchanged.")}>Continue investigation</Button><Button icon={Star} variant="secondary" disabled={!!busy || !!watched} busy={busy === "research-shortlist"} onClick={() => run("research-shortlist", "/watchlist", { address: screening.address, label: "Research shortlist" }, "POST", "Wallet shortlisted. This is not a profit or safety endorsement.")}>{watched ? "Shortlisted" : "Save to shortlist"}</Button></div>
        {canStart && <Button icon={ArrowRight} variant="secondary" onClick={() => paperSetupRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}>Set up paper observation</Button>}
        <small>Each continuation retains the prior report and spends only its explicit collection budget. Inspect and screen the new report when it completes.</small>
      </> : <p>No saved screening assessments yet. Save an assessment from a report above.</p>}
    </section>
    <section className="panel" ref={paperSetupRef}>
      <SectionHeading title="Start forward quote-based paper observation" subtitle="Fixed entry, first leader sale · Strategy fixed-entry-first-sale-v1" />
      <p className="research-intro">Enter a fixed hypothetical SOL amount on an eligible observed buy while not holding that mint. Exit the full paper position on the first subsequent eligible leader sale. Additional buys and excluded signals are retained. Quotes are requested after detection, decoding and your reaction delay.</p>
      <form onSubmit={(event) => { event.preventDefault(); void start(); }}>
        <div className="research-setting-grid">{settingFields.map((field) => <label key={field.key}>{field.name}<input type="number" required min={field.min} max={field.max} step={field.step ?? "1"} value={settings[field.key]} onChange={(event) => setSettings((current) => ({ ...current, [field.key]: typeof defaultPaperSettings[field.key] === "number" ? Number(event.target.value) : event.target.value }))} /><small>{field.hint}</small></label>)}</div>
        {formError && <p className="inline-alert" role="alert">{formError}</p>}
        <div className="research-action-row"><Button type="submit" icon={Play} busy={busy === "paper-start"} disabled={!!busy || !canStart}>Start quote-only observation</Button><p>{!screening ? "Save and select a screening assessment first." : !canStart ? screening.current_eligibility?.reason ?? (screening.result === "excluded_by_preset" ? "This assessment is excluded by its screening preset. Inspect its evidence and reasons." : "Check and save native identity evidence before starting observation.") : `For ${shorten(screening.address)} · settings are saved with this run.`}</p></div>
      </form>
      <p className="research-note">Read-only research: no transaction is built, signed or submitted. Monitoring notifications do not prove complete wallet activity; gaps remain recorded and are not reconstructed with hindsight.</p>
    </section>
    <section className="panel" ref={paperResultsRef}>
      <SectionHeading title="Saved paper observations" subtitle="Reopen a run to inspect its frozen settings, retained signals, quotes and unresolved exposure." />
      {observations.length > 1 && <div className="table-scroll"><table className="report-table"><thead><tr><th>Wallet / started</th><th>Delay / entry</th><th>Paper P&L including open exposure</th><th>Gaps / open positions</th><th /></tr></thead><tbody>{observations.slice(0, 30).map((item) => <tr key={item.id}><td><span className="mono">{shorten(item.address)}</span><small>{dateTime(item.started_at)}</small></td><td>{item.settings.reaction_delay_seconds} seconds<small><Amount value={item.settings.entry_sol} /> fixed entry</small></td><td><Amount value={"supported_economic_pnl_sol" in item.summary ? item.summary.supported_economic_pnl_sol : item.summary.economic_pnl_sol} unknown="Incomplete / unsupported valuation" /><small>{label(item.status)} · {item.summary.complete_observation ? "No recorded gaps or unvalued exposure" : "Incomplete observation"}</small></td><td>{item.gaps.length} gaps · {item.summary.open_positions} open</td><td><button className="text-button" onClick={() => reopen("observations", item.id)}>Inspect run <ArrowRight size={13} /></button></td></tr>)}</tbody></table></div>}
      {observation ? <>
        <div className="research-action-row"><label className="research-report-picker">Observation<select aria-label="Saved paper observation" value={observation.id} onChange={(event) => void reopen("observations", event.target.value)}>{observations.map((item) => <option key={item.id} value={item.id}>{shorten(item.address)} · {label(item.status)} · {dateTime(item.started_at)}</option>)}</select></label><Button variant="secondary" disabled={!!busy} onClick={() => reopen("observations", observation.id)}>Reopen saved observation</Button><a className="button secondary" href={`/api/observations/${encodeURIComponent(observation.id)}/export`} download><Download size={15} /> Export paper observation</a></div>
        <div className="research-action-row"><Button icon={Square} variant="secondary" busy={busy === "paper-stop"} disabled={!!busy || observation.status !== "running"} onClick={() => changeRun("stop")}>Stop observation</Button><Button icon={Play} variant="secondary" busy={busy === "paper-resume"} disabled={!!busy || !["stopped", "paused"].includes(observation.status)} onClick={() => changeRun("resume")}>Resume observation</Button><Button icon={RefreshCw} variant="secondary" busy={busy === "paper-mark"} disabled={!!busy || !observation.summary.open_positions} onClick={() => changeRun("mark")}>Request current open-position quotes</Button></div>
        <PaperDetail observation={observation} showEvidence={showEvidence} />
      </> : <Empty icon={Activity} title="Your next signals start here" detail="Start an observation from a saved screening. Its paper portfolio begins with known cash and no holdings; only future detected signals can create paper entries." />}
    </section>
  </>;
}
