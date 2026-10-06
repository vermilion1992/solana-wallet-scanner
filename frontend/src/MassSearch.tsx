import { useEffect, useState } from "react";
import { Download, Play, RefreshCw, Search } from "lucide-react";
import type { Actions } from "./App";
import type { MassSearchCandidate, MassSearchMetric, MassSearchRun, RankedBatch, RankedWorkflowRow, RankedWorkflowView, ResearchCompare } from "./types";
import { Badge, Button, Empty, SectionHeading } from "./components";
import { api, reportDisplay } from "./api";
import { count, decimal, label, shorten } from "./format";
import { useNarrowViewport } from "./useNarrow";

const STAGES = ["triage", "behaviour", "reconstruct", "forward_select"] as const;

export function massSearchCorpusLabel(kind?: string) {
  if (kind === "GENUINE_LIVE") return "Genuine live collection";
  if (kind === "GENUINE_REPLAY") return "Genuine archived replay";
  return "Synthetic / development";
}

export function massSearchEmptyReason(run?: MassSearchRun | null, reports = 0) {
  if (!run) return { state: "not_scanned", action: "Create a Search run, then acquire a frozen universe." };
  const unique = run.universe?.unique_candidates ?? 0;
  if (unique === 0) return { state: "empty_universe", action: "No valid candidates were retained. Check the source page or import fixture." };
  const triage = run.stages?.triage;
  if (triage && triage.promoted === 0 && triage.deferred > 0) return { state: "budget_or_missing", action: "Survivors were deferred. Inspect reason codes; do not treat this as a completed market search." };
  if (reports === 0) return { state: "no_reconstruction", action: "The universe is frozen. Open a candidate after subset reconstruction, or run the offline slice." };
  if (run.corpus_kind === "SYNTHETIC") return { state: "synthetic", action: "This run is synthetic. It cannot prove a live 1,000-wallet search." };
  return { state: "ready", action: "Open a candidate to inspect subset P&L, median hold and exit timing." };
}

export function massSearchMetricText(metric?: MassSearchMetric | null, fallback?: string | null) {
  if (metric?.value) return `${decimal(metric.value, 4)} ${metric.unit || ""}`.trim();
  if (fallback) return fallback;
  return metric?.state || "unknown";
}

export function MassSearchView({ state, busy, run, navigate, refresh, open }: Actions) {
  const [detail, setDetail] = useState<MassSearchRun | null>(null);
  const [candidates, setCandidates] = useState<MassSearchCandidate[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [stage, setStage] = useState<(typeof STAGES)[number]>("triage");
  const [selectedId, setSelectedId] = useState<string>("");
  const [blocker, setBlocker] = useState<string>("Live collection is blocked until a named authorization exists.");
  const [ranked, setRanked] = useState<RankedWorkflowView | null>(null);
  const [compareLeft, setCompareLeft] = useState<string>("");
  const [compareRight, setCompareRight] = useState<string>("");
  const [compareResult, setCompareResult] = useState<string>("");
  const [minTrades, setMinTrades] = useState<string>("");
  const [onlyShortlist, setOnlyShortlist] = useState(false);
  const [onlyUser, setOnlyUser] = useState(false);
  const [onlyCaptured, setOnlyCaptured] = useState(false);
  const [minCompleted, setMinCompleted] = useState<string>("");
  const [minSample, setMinSample] = useState<string>("");
  const [minCoverage, setMinCoverage] = useState<string>("");
  const [visibleLimit, setVisibleLimit] = useState(20);
  const [batch, setBatch] = useState<RankedBatch | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [filterNote, setFilterNote] = useState("");
  const [acquireNote, setAcquireNote] = useState("");
  const narrow = useNarrowViewport();
  const summary = state.mass_search;
  const runs = summary?.runs || [];
  const newestId = runs[0]?.run_id;
  const activeId = selectedId && runs.some((item) => item.run_id === selectedId) ? selectedId : newestId;
  const savedReports = state.reports.filter((report) => report.source === "mass-search");
  const empty = massSearchEmptyReason(detail, candidates.filter((row) => row.report_id).length + savedReports.length);

  const loadRanked = () => {
    api("/mass-search/ranked-workflow")
      .then((value) => {
        const view = value as RankedWorkflowView;
        setRanked(view);
        const proxy = view.filters?.provider_proxy || {};
        setMinTrades(proxy.min_provider_trade_count || "");
        setOnlyShortlist(!!proxy.only_shortlist);
        setOnlyUser(!!proxy.only_user_shortlist);
        setOnlyCaptured(!!proxy.only_captured);
        setMinCompleted(view.filters?.thresholds?.min_completed_known_cost || "");
        setMinSample(view.filters?.thresholds?.min_sample_positions || "");
        setMinCoverage(view.filters?.thresholds?.min_coverage_share || "");
      })
      .catch(() => undefined);
  };

  const persistFilters = async (next: {
    min_provider_trade_count?: string;
    only_shortlist?: boolean;
    only_user_shortlist?: boolean;
    only_captured?: boolean;
    min_completed_known_cost?: string;
    min_sample_positions?: string;
    min_coverage_share?: string;
  }) => {
    const body = {
      provider_proxy: {
        min_provider_trade_count: next.min_provider_trade_count ?? minTrades,
        only_shortlist: next.only_shortlist ?? onlyShortlist,
        only_user_shortlist: next.only_user_shortlist ?? onlyUser,
        only_captured: next.only_captured ?? onlyCaptured,
      },
      thresholds: {
        ...(ranked?.filters?.thresholds || {}),
        min_completed_known_cost: next.min_completed_known_cost ?? minCompleted,
        min_sample_positions: next.min_sample_positions ?? minSample,
        min_coverage_share: next.min_coverage_share ?? minCoverage,
      },
    };
    const saved = await api("/mass-search/research-filters", "PUT", body);
    setFilterNote("Filters saved locally. Provider-proxy and reconstructed-evidence stay separate.");
    await loadRanked();
    return saved;
  };

  useEffect(() => {
    api("/mass-search/access-blocker")
      .then((value) => {
        const body = value as { birdeye?: { purpose?: string; provider?: string } };
        setBlocker(`${body.birdeye?.provider || "birdeye"}: ${body.birdeye?.purpose || "authorization required"}`);
      })
      .catch(() => undefined);
    loadRanked();
    const savedBatch = sessionStorage.getItem("mass-search-batch-id");
    if (savedBatch) {
      api(`/mass-search/ranked-workflow/batch/${savedBatch}`)
        .then((value) => setBatch(value as RankedBatch))
        .catch(() => undefined);
    }
    try {
      const nav = JSON.parse(sessionStorage.getItem("mass-search-nav") || "null");
      if (nav && typeof nav === "object") {
        if (nav.stage) setStage(nav.stage);
        if (nav.compareLeft) setCompareLeft(nav.compareLeft);
        if (nav.compareRight) setCompareRight(nav.compareRight);
        if (nav.visibleLimit) setVisibleLimit(nav.visibleLimit);
        if (nav.onlyShortlist != null) setOnlyShortlist(!!nav.onlyShortlist);
      }
    } catch {
      /* session-only navigation restore */
    }
  }, []);

  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      setCandidates([]);
      return;
    }
    api(`/mass-search/runs/${activeId}`)
      .then((value) => setDetail(value as MassSearchRun))
      .catch(() => undefined);
  }, [activeId, state.mass_search?.runs?.length, busy]);

  useEffect(() => {
    sessionStorage.setItem("mass-search-nav", JSON.stringify({
      stage,
      compareLeft,
      compareRight,
      visibleLimit,
      onlyShortlist,
    }));
  }, [stage, compareLeft, compareRight, visibleLimit, onlyShortlist]);

  useEffect(() => {
    if (!activeId) return;
    api(`/mass-search/runs/${activeId}/candidates?stage=${stage}&limit=50`)
      .then((value) => {
        const page = value as { items?: MassSearchCandidate[]; next_cursor?: string | null };
        setCandidates(page.items || []);
        setNextCursor(page.next_cursor || null);
      })
      .catch(() => {
        setCandidates([]);
        setNextCursor(null);
      });
  }, [activeId, stage, detail?.status, busy]);

  const inspect = async (reportId: string) => {
    await open(await reportDisplay(reportId));
  };

  const toggleShortlist = async (address: string, selected: boolean) => {
    await api("/mass-search/ranked-workflow/shortlist", "POST", { address, selected });
    loadRanked();
  };

  const startBatch = async (includeFixtures: boolean) => {
    if (batchBusy) return;
    const shortlist = ranked?.user_shortlist || [];
    const captured = (ranked?.rows || []).filter((row) => row.capture_available).map((row) => row.address);
    const noHistory = (ranked?.rows || []).filter((row) => !row.capture_available).slice(0, 2).map((row) => row.address);
    const addresses = includeFixtures
      ? Array.from(new Set([...captured, ...noHistory, ...((ranked?.engineering_fixtures || []).map((row) => row.address))]))
      : (shortlist.length ? shortlist : captured);
    setBatchBusy(true);
    try {
      let current = await api<RankedBatch>("/mass-search/ranked-workflow/batch", "POST", {
        addresses,
        include_fixtures: includeFixtures,
        run: false,
      });
      setBatch(current);
      sessionStorage.setItem("mass-search-batch-id", current.batch_id);
      while (current.status !== "completed" && current.status !== "cancelled" && current.completed < current.total) {
        current = await api<RankedBatch>(`/mass-search/ranked-workflow/batch/${current.batch_id}/step`, "POST", {});
        setBatch(current);
      }
      loadRanked();
      await refresh();
    } finally {
      setBatchBusy(false);
    }
  };

  const cancelActiveBatch = async () => {
    if (!batch?.batch_id) return;
    const current = await api<RankedBatch>(`/mass-search/ranked-workflow/batch/${batch.batch_id}/cancel`, "POST", {});
    setBatch(current);
  };

  const acquireHistory = async () => {
    const gate = await api<{ status?: { allowed?: boolean; reason?: string }; attempt?: { allowed?: boolean; reason?: string; would_contact_provider?: boolean } }>(
      "/mass-search/acquisition-gate",
    );
    const reason = gate.attempt?.reason || gate.status?.reason || "Acquisition is blocked.";
    setAcquireNote(
      gate.attempt?.allowed
        ? "Authorization would still not dispatch from this UI."
        : `Acquire history blocked: ${reason}`,
    );
  };

  const loadMore = async () => {
    if (!activeId || !nextCursor) return;
    const page = await api<{ items?: MassSearchCandidate[]; next_cursor?: string | null }>(
      `/mass-search/runs/${activeId}/candidates?stage=${stage}&limit=50&cursor=${encodeURIComponent(nextCursor)}`,
    );
    setCandidates((current) => [...current, ...(page.items || [])]);
    setNextCursor(page.next_cursor || null);
  };

  return (
    <div className="research-workflow mass-search">
      <p className="research-intro">
        Mass research keeps the named Strict preset unchanged. Preliminary ranking is a queue, not a
        financial MATCH. Offline mode is the default. Snapshot {ranked?.snapshot_id || "cached ranked-100"}
        {ranked?.snapshot_raw_sha256 ? ` · ${ranked.snapshot_raw_sha256.slice(0, 12)}` : ""}.
        The public sampler still caps at {count(summary?.legacy_candidate_cap ?? 20)}{" "}
        discovery leads; this funnel can store up to {count(summary?.bulk_capacity ?? 10000)} lightweight rows without raising credit caps.
      </p>
      <div className="research-action-row">
        <Button
          icon={Play}
          disabled={!!busy}
          onClick={() => run("mass-search-slice", "/mass-search/vertical-slice", { corpus_kind: "SYNTHETIC" }, "POST", "Offline source-to-report slice finished.").then(() => setSelectedId(""))}
        >
          Run offline slice
        </Button>
        <Button
          icon={RefreshCw}
          variant="secondary"
          disabled={!activeId || !!busy}
          onClick={() => activeId && run("mass-search-refilter", `/mass-search/runs/${activeId}/refilter`, {}, "POST", "Cached refilter issued no provider calls.").then((value) => {
            const child = value as MassSearchRun | undefined;
            if (child?.run_id) setSelectedId(child.run_id);
          })}
        >
          Refilter cached rows
        </Button>
        {activeId && (
          <a className="button secondary" href={`/api/mass-search/runs/${encodeURIComponent(activeId)}/export`} download>
            <Download size={15} /> Export run
          </a>
        )}
        <Button icon={Search} variant="secondary" onClick={() => navigate("research")}>
          Open research
        </Button>
      </div>
      <p className="research-note">{blocker} Additional spend stays $0. The example authorization file is not a grant.</p>
      <section className="research-subpanel mass-search-budget" data-budget-enabled="false">
        <SectionHeading title="Budget / live collection" subtitle="Disabled without live approval" />
        <p className="research-note">
          Budget view stays off. Consumed grants stay consumed. Cached ranked-100 browse and report reopen make zero provider calls.
        </p>
        <Button variant="secondary" disabled>Request live spend</Button>
      </section>
      <section className="research-subpanel" data-ranked-workflow="cached">
        <SectionHeading title="Ranked-100 cached shortlist" subtitle="Provider rank is not verification" />
        <p className="research-note">
          {count(ranked?.ranked_count ?? 0)} ranked wallets from the saved discovery page.
          Rank-1, positive subset P&amp;L, and “worth investigating” are not verified profitable or safe to copy.
        </p>
        <p className="research-note" data-phone-access="blocked">
          {ranked?.phone_access?.blocker || "Phone access uses the local authenticated launcher only. No public preview is configured."}
        </p>
        <div className="research-metrics mass-search-funnel" data-funnel-counts="true">
          <div>
            <span>Funnel A yes</span>
            <strong>{count(ranked?.funnel_counts?.A_YES ?? 0)}</strong>
            <small>worth investigating — unverified</small>
          </div>
          <div>
            <span>Awaiting evidence</span>
            <strong>{count(ranked?.funnel_counts?.awaiting_evidence ?? 0)}</strong>
            <small>history required — not analysed</small>
          </div>
          <div>
            <span>Analysed</span>
            <strong>{count(ranked?.funnel_counts?.analysed ?? 0)}</strong>
            <small>cached reconstruction only</small>
          </div>
          <div>
            <span>C evaluated</span>
            <strong>{count((ranked?.funnel_counts?.C_MET ?? 0) + (ranked?.funnel_counts?.C_NOT_MET ?? 0))}</strong>
            <small>not set · not applied</small>
          </div>
        </div>
        <form
          className="mass-search-filters"
          data-filter-group="provider-and-reconstructed"
          onSubmit={(event) => {
            event.preventDefault();
            void persistFilters({
              min_provider_trade_count: minTrades,
              only_shortlist: onlyShortlist,
              only_user_shortlist: onlyUser,
              only_captured: onlyCaptured,
              min_completed_known_cost: minCompleted,
              min_sample_positions: minSample,
              min_coverage_share: minCoverage,
            });
          }}
        >
          <fieldset data-filter-group="provider_proxy">
            <legend>Provider-proxy filters</legend>
            <label>
              Min provider trades
              <input
                aria-label="Minimum provider trade count"
                inputMode="numeric"
                value={minTrades}
                onChange={(event) => setMinTrades(event.target.value)}
                placeholder="unset"
              />
              <small>unit: provider_trades · missing does not hide rows</small>
            </label>
            <label>
              <input type="checkbox" checked={onlyShortlist} onChange={(event) => setOnlyShortlist(event.target.checked)} />
              Provider shortlist only
            </label>
            <label>
              <input type="checkbox" checked={onlyUser} onChange={(event) => setOnlyUser(event.target.checked)} />
              Your shortlist only
            </label>
            <label>
              <input type="checkbox" checked={onlyCaptured} onChange={(event) => setOnlyCaptured(event.target.checked)} />
              Cached history only
            </label>
          </fieldset>
          <fieldset data-filter-group="reconstructed_evidence">
            <legend>Reconstructed-evidence filters</legend>
            <label>
              Min completed known-cost
              <input
                aria-label="Minimum completed known-cost positions"
                inputMode="numeric"
                value={minCompleted}
                onChange={(event) => setMinCompleted(event.target.value)}
                placeholder="unset"
              />
              <small>unit: positions · unknown never passes · applies only after analysis</small>
            </label>
            <label>
              Min sample positions
              <input
                aria-label="Minimum sample positions"
                inputMode="numeric"
                value={minSample}
                onChange={(event) => setMinSample(event.target.value)}
                placeholder="3"
              />
              <small>unit: positions · default 3 · a single matched trade never qualifies the account</small>
            </label>
            <label>
              Min coverage share
              <input
                aria-label="Minimum coverage share"
                inputMode="decimal"
                value={minCoverage}
                onChange={(event) => setMinCoverage(event.target.value)}
                placeholder="unset"
              />
              <small>unit: share · not set is not applied</small>
            </label>
          </fieldset>
          <Button type="submit" variant="secondary" disabled={!!busy || batchBusy}>Save filters</Button>
        </form>
        {filterNote && <p className="research-note" data-filters-saved="true">{filterNote}</p>}
        <div className="research-action-row">
          <Button
            icon={Play}
            disabled={!!busy || batchBusy}
            onClick={() => void startBatch(false)}
          >
            Analyse shortlist
          </Button>
          <Button
            variant="secondary"
            disabled={!!busy || batchBusy}
            onClick={() => void startBatch(true)}
          >
            Analyse available + fixtures
          </Button>
          <Button variant="secondary" disabled={!!busy} onClick={() => loadRanked()}>Refresh cached list</Button>
          <Button
            variant="secondary"
            data-acquire-history="true"
            disabled={!!busy || batchBusy}
            onClick={() => void acquireHistory()}
          >
            Acquire history
          </Button>
          {batch && batch.status === "running" && (
            <Button variant="secondary" disabled={!batch.batch_id} onClick={() => void cancelActiveBatch()}>Cancel batch</Button>
          )}
        </div>
        {acquireNote && <p className="research-note" data-acquire-block="true">{acquireNote}</p>}
        {ranked?.research_screen && (
          <p className="research-note" data-research-screen="true">
            Research screen {ranked.research_screen.outcome}: inconclusive {count(ranked.research_screen.counts?.inconclusive ?? 0)}
            {` · zero-qualified ${count(ranked.research_screen.counts?.zero_qualified ?? 0)}`}
            {` · qualified ${count(ranked.research_screen.counts?.completed_qualified ?? 0)}`}
            . Thresholds were fixed before evaluation. Unknown never passes.
            {` Qualification (evidence quality, not screen pass/fail): not evaluated ${count(ranked.research_screen.counts?.qualification?.not_evaluated ?? 0)} · analysed-incomplete ${count(ranked.research_screen.counts?.qualification?.analysed_incomplete ?? 0)} · matched-position ${count(ranked.research_screen.counts?.qualification?.positive_matched_position_evidence ?? 0)} · net realised ${count(ranked.research_screen.counts?.qualification?.positive_net_realised_over_window ?? 0)} · account performance ${count(ranked.research_screen.counts?.qualification?.profitable_account_performance ?? 0)}.`}
          </p>
        )}
        {batch && (
          <div className="mass-search-batch" data-batch-progress={batch.status}>
            <p>
              Batch {batch.status}: {count(batch.completed)} / {count(batch.total)}
            </p>
            <progress max={batch.total || 1} value={batch.completed || 0} />
            <ul>
              {(batch.outcomes || []).map((item) => (
                <li key={item.address} data-batch-status={item.status}>
                  <span className="mono">{shorten(item.address)}</span>
                  <span>{item.status === "history_required" ? "History required — not analysed" : item.status}</span>
                  {item.detail && <small>{item.detail}</small>}
                  {item.report_id && <Button variant="secondary" onClick={() => void inspect(item.report_id!)}>Open report</Button>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!ranked?.rows?.length && (
          <>
            {!narrow && (
              <div className="mass-search-table-wrap">
                <table className="mass-search-table">
                  <thead>
                    <tr>
                      <th>Shortlist</th>
                      <th>Rank</th>
                      <th>Address</th>
                      <th>A / B / C</th>
                      <th>Provider trades</th>
                      <th>Scoped P&amp;L</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ranked.rows || []).slice(0, visibleLimit).map((row) => (
                      <RankedRow
                        key={row.address}
                        row={row}
                        busy={!!busy || batchBusy}
                        onOpen={(id) => void inspect(id)}
                        onToggle={(selected) => void toggleShortlist(row.address, selected)}
                        onReplay={() => run("ranked-replay", "/mass-search/ranked-workflow/replay", { address: row.address }, "POST", "Cached capture reconstructed.").then((value) => {
                          const body = value as { report_id?: string };
                          loadRanked();
                          if (body?.report_id) void inspect(body.report_id);
                        })}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <ul className="mass-search-cards" data-ranked-cards="true">
              {(ranked.rows || []).slice(0, visibleLimit).map((row) => (
                <li key={`ranked-${row.address}`} data-history-required={row.history_required ? "true" : "false"}>
                  <label className="mass-search-shortlist">
                    <input
                      type="checkbox"
                      aria-label={`Shortlist ${shorten(row.address)}`}
                      checked={!!row.user_shortlisted}
                      onChange={(event) => void toggleShortlist(row.address, event.target.checked)}
                    />
                    Shortlist
                  </label>
                  <strong className="mono">{shorten(row.address)}</strong>
                  <p>Provider rank {row.provider_rank ?? "—"} · A {row.funnel?.A?.state || "—"} · B {row.funnel?.B?.state || "—"} · C {row.funnel?.C?.state || "—"}</p>
                  <p>Provider trades {row.trade_count ?? "unknown"} · {row.capture_available ? "cached capture" : row.report_id ? "analysed" : "History required — not analysed"}</p>
                  <p data-qualification-category={row.qualification_category?.category || "not_evaluated"}>Qualification {String(row.qualification_category?.category || "not_evaluated").replaceAll("_", " ")} · screening separate</p>
                  <p>{row.funnel?.next_action?.detail || "Browse cached row only."}</p>
                  {row.report_id
                    ? <Button variant="secondary" disabled={!!busy || batchBusy} onClick={() => void inspect(row.report_id!)}>Open report</Button>
                    : row.capture_available
                      ? <Button variant="secondary" disabled={!!busy || batchBusy} onClick={() => run("ranked-replay", "/mass-search/ranked-workflow/replay", { address: row.address }, "POST", "Cached capture reconstructed.").then((value) => {
                          const body = value as { report_id?: string };
                          loadRanked();
                          if (body?.report_id) void inspect(body.report_id);
                        })}>Analyse</Button>
                      : <span data-history-required-label="true">History required — not analysed</span>}
                </li>
              ))}
            </ul>
            {(ranked.rows || []).length > visibleLimit && (
              <Button variant="secondary" onClick={() => setVisibleLimit((current) => current + 20)}>Show more wallets</Button>
            )}
          </>
        )}
        {!!ranked?.engineering_fixtures?.length && (
          <div data-engineering-fixtures="true">
            <SectionHeading title="Engineering fixtures" subtitle="SYNTHETIC — not proof" />
            <ul className="mass-search-cards">
              {ranked.engineering_fixtures.map((row) => (
                <li key={`fixture-${row.address}`}>
                  <label className="mass-search-shortlist">
                    <input
                      type="checkbox"
                      aria-label={`Shortlist ${shorten(row.address)}`}
                      checked={!!row.user_shortlisted}
                      onChange={(event) => void toggleShortlist(row.address, event.target.checked)}
                    />
                    Shortlist
                  </label>
                  <strong className="mono">{shorten(row.address)}</strong>
                  <p>{row.label || "SYNTHETIC — engineering fixture, not proof"}</p>
                  {row.report_id
                    ? <Button variant="secondary" onClick={() => void inspect(row.report_id!)}>Open report</Button>
                    : <Button variant="secondary" disabled={!!busy || batchBusy} onClick={() => run("ranked-replay", "/mass-search/ranked-workflow/replay", { address: row.address }, "POST", "Synthetic fixture reconstructed.").then(() => loadRanked())}>Analyse fixture</Button>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!savedReports.length && (
          <div className="research-action-row">
            <label>
              Compare left
              <select aria-label="Compare left report" value={compareLeft} onChange={(event) => setCompareLeft(event.target.value)}>
                <option value="">Select saved report</option>
                {savedReports.map((report) => (
                  <option key={`left-${report.id}`} value={report.id}>{shorten(report.address)} · {report.id.slice(0, 8)}</option>
                ))}
              </select>
            </label>
            <label>
              Compare right
              <select aria-label="Compare right report" value={compareRight} onChange={(event) => setCompareRight(event.target.value)}>
                <option value="">Select saved report</option>
                {savedReports.map((report) => (
                  <option key={`right-${report.id}`} value={report.id}>{shorten(report.address)} · {report.id.slice(0, 8)}</option>
                ))}
              </select>
            </label>
            <Button
              variant="secondary"
              disabled={!compareLeft || !compareRight || !!busy}
              onClick={() => api("/mass-search/research-compare", "POST", { left_id: compareLeft, right_id: compareRight }).then((value) => {
                const body = value as ResearchCompare;
                const policy = body.window_policy || {};
                const formatCompare = (value: unknown) => {
                  if (value == null || value === "") return "—";
                  if (typeof value === "object") {
                    const rec = value as Record<string, unknown>;
                    if ("quantity" in rec || "proceeds" in rec || "sales" in rec) {
                      return `sales ${rec.sales ?? "—"} · qty ${rec.quantity ?? "—"} · proceeds ${rec.proceeds ?? "—"}`;
                    }
                    try {
                      return JSON.stringify(value);
                    } catch {
                      return "—";
                    }
                  }
                  return String(value);
                };
                const fields = (body.fields || []).map((field) => `${field.key}: ${formatCompare(field.left)} vs ${formatCompare(field.right)}`).join(" · ");
                const mismatches = (body.mismatches || []).map((item) => `${item.kind}: ${item.detail}`).join(" · ");
                const policyText = [
                  policy.kind || "own_windows_shown_mismatch_blocks",
                  policy.detail,
                  `left window ${policy.left_window?.start || "—"} → ${policy.left_window?.end || "—"}`,
                  `right window ${policy.right_window?.start || "—"} → ${policy.right_window?.end || "—"}`,
                  `left tx ${policy.left_included_trades ?? (policy.left_included_tx || []).length}`,
                  `right tx ${policy.right_included_trades ?? (policy.right_included_tx || []).length}`,
                  `samples ${String(policy.left_sample_size ?? "—")} vs ${String(policy.right_sample_size ?? "—")}`,
                  `scoped_pnl ${String(policy.left_scoped_pnl ?? "—")} vs ${String(policy.right_scoped_pnl ?? "—")}`,
                  body.comparable ? "comparable" : "blocked",
                  policy.result_scope || "conditional_on_captured_inventory",
                ].filter(Boolean).join(" · ");
                setCompareResult(mismatches ? `${policyText} · ${fields} · Mismatches: ${mismatches}` : `${policyText} · ${fields}`);
              }).catch((error: Error) => setCompareResult(error.message))}
            >
              Compare saved reports
            </Button>
          </div>
        )}
        {compareResult && <p className="research-note" data-research-compare="true">{compareResult}</p>}
      </section>
      {!runs.length && <Empty title="Not scanned" detail={empty.action} />}
      {!!runs.length && (
        <label className="research-report-picker">
          Search run
          <select aria-label="Search run" value={activeId || ""} onChange={(event) => setSelectedId(event.target.value)}>
            {runs.map((item) => (
              <option key={item.run_id} value={item.run_id}>
                {massSearchCorpusLabel(item.corpus_kind)} · {label(item.status)} · {item.run_id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {detail && (
        <section className="research-subpanel">
          <SectionHeading title="Search run" subtitle={massSearchCorpusLabel(detail.corpus_kind)} />
          <div className="research-metrics mass-search-funnel">
            {STAGES.map((name) => {
              const counts = detail.stages?.[name];
              return (
                <div key={name}>
                  <span>{label(name)}</span>
                  <strong>{count(counts?.promoted ?? 0)}</strong>
                  <small>
                    in {count(counts?.input ?? 0)} · rejected {count(counts?.rejected ?? 0)} · deferred {count(counts?.deferred ?? 0)} · pending {count(counts?.pending ?? 0)}
                  </small>
                </div>
              );
            })}
          </div>
          <p>
            Universe {count(detail.universe?.unique_candidates ?? 0)} unique / {count(detail.universe?.raw_rows ?? 0)} raw ·
            duplicates {count(detail.universe?.duplicate_rows ?? 0)} · invalid {count(detail.universe?.invalid_rows ?? 0)} ·
            live authorized {detail.live_authorized ? "yes" : "no"} · {label(detail.status)}
          </p>
          <p className="research-note">{empty.action}</p>
        </section>
      )}
      <section className="research-subpanel">
        <SectionHeading title="Stage shortlist" subtitle="Cached rows only" />
        <div className="research-action-row">
          <label>
            Stage
            <select aria-label="Stage" value={stage} onChange={(event) => setStage(event.target.value as (typeof STAGES)[number])}>
              {STAGES.map((name) => (
                <option key={name} value={name}>{label(name)}</option>
              ))}
            </select>
          </label>
        </div>
        {!candidates.length && <Empty title="No rows on this page" detail="Change stage or run the offline slice. Filter changes here do not call providers." />}
        {!!candidates.length && (
          <>
            {!narrow && <div className="mass-search-table-wrap">
              <table className="mass-search-table">
                <thead>
                  <tr>
                    <th>Address</th>
                    <th>Decision</th>
                    <th>Reported P&amp;L</th>
                    <th>Subset P&amp;L</th>
                    <th>Median hold</th>
                    <th>t90</th>
                    <th>Reasons</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((row) => (
                    <tr key={row.candidate_id}>
                      <td className="mono">{shorten(row.address)}</td>
                      <td><Badge value={row.result || "pending"}>{label(row.result || "pending")}</Badge></td>
                      <td>{row.sort_value ? `${decimal(row.sort_value, 2)} ${row.unit || ""}` : row.metric_state || "unknown"}</td>
                      <td>{massSearchMetricText(row.subset_pnl)}</td>
                      <td>{massSearchMetricText(row.median_hold)}</td>
                      <td>{massSearchMetricText(row.material_exit_t90)}</td>
                      <td>{(row.reason_codes || []).join(", ") || "—"}</td>
                      <td>
                        {row.report_id
                          ? <Button variant="secondary" disabled={!!busy} onClick={() => void inspect(row.report_id!)}>Open report</Button>
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>}
            <ul className="mass-search-cards">
              {candidates.map((row) => (
                <li key={`card-${row.candidate_id}`}>
                  <strong className="mono">{shorten(row.address)}</strong>
                  <Badge value={row.result || "pending"}>{label(row.result || "pending")}</Badge>
                  <p>Reported {row.sort_value ? `${decimal(row.sort_value, 2)} ${row.unit || ""}` : row.metric_state || "unknown"}</p>
                  <p>Subset {massSearchMetricText(row.subset_pnl)} · hold {massSearchMetricText(row.median_hold)} · t90 {massSearchMetricText(row.material_exit_t90)}</p>
                  <p>{(row.reason_codes || []).join(", ") || "—"}</p>
                  {row.report_id && <Button variant="secondary" disabled={!!busy} onClick={() => void inspect(row.report_id!)}>Open report</Button>}
                </li>
              ))}
            </ul>
          </>
        )}
        {nextCursor && <Button variant="secondary" disabled={!!busy} onClick={() => void loadMore()}>Load next 50</Button>}
      </section>
      {!!savedReports.length && (
        <section className="research-subpanel">
          <SectionHeading title="Saved subset reports" subtitle="Reopen without provider calls" />
          <ul className="mass-search-saved">
            {savedReports.map((report) => (
              <li key={report.id}>
                <span className="mono">{shorten(report.address)}</span>
                <span>{massSearchCorpusLabel(String(report.corpus_kind || "SYNTHETIC"))}</span>
                <Button variant="secondary" disabled={!!busy} onClick={() => void inspect(report.id)}>Reopen report</Button>
                <a className="button secondary" href={`/api/export/reports/${encodeURIComponent(report.id)}.json`} download>Export JSON</a>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Button variant="secondary" onClick={() => refresh()}>Refresh workspace</Button>
    </div>
  );
}

function RankedRow({
  row,
  busy,
  onOpen,
  onReplay,
  onToggle,
}: {
  row: RankedWorkflowRow;
  busy: boolean;
  onOpen: (id: string) => void;
  onReplay: () => void;
  onToggle: (selected: boolean) => void;
}) {
  return (
    <tr data-history-required={row.history_required ? "true" : "false"}>
      <td>
        <input
          type="checkbox"
          aria-label={`Shortlist ${shorten(row.address)}`}
          checked={!!row.user_shortlisted}
          onChange={(event) => onToggle(event.target.checked)}
        />
      </td>
      <td>{row.provider_rank ?? "—"}</td>
      <td className="mono">{shorten(row.address)}</td>
      <td>{row.funnel?.A?.state || "—"} / {row.funnel?.B?.state || "—"} / {row.funnel?.C?.state || "—"}</td>
      <td>{row.trade_count ?? "unknown"}</td>
      <td>{row.funnel?.B?.scoped_pnl ? `${row.funnel.B.scoped_pnl} ${row.funnel.B.scoped_pnl_unit || ""}` : "unverified"}</td>
      <td>
        {row.report_id
          ? <Button variant="secondary" disabled={busy} onClick={() => onOpen(row.report_id!)}>Open report</Button>
          : row.capture_available
            ? <Button variant="secondary" disabled={busy} onClick={onReplay}>Analyse</Button>
            : <span data-history-required-label="true">History required — not analysed</span>}
      </td>
    </tr>
  );
}
