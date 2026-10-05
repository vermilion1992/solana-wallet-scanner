import { useEffect, useState } from "react";
import { Download, Play, RefreshCw, Search } from "lucide-react";
import type { Actions } from "./App";
import type { MassSearchCandidate, MassSearchMetric, MassSearchRun, Report } from "./types";
import { Badge, Button, Empty, SectionHeading } from "./components";
import { api, reportDisplay } from "./api";
import { count, decimal, label, shorten } from "./format";

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
  const summary = state.mass_search;
  const runs = summary?.runs || [];
  const newestId = runs[0]?.run_id;
  const activeId = selectedId && runs.some((item) => item.run_id === selectedId) ? selectedId : newestId;
  const savedReports = state.reports.filter((report) => report.source === "mass-search");
  const empty = massSearchEmptyReason(detail, candidates.filter((row) => row.report_id).length + savedReports.length);

  useEffect(() => {
    api("/mass-search/access-blocker")
      .then((value) => {
        const body = value as { birdeye?: { purpose?: string; provider?: string } };
        setBlocker(`${body.birdeye?.provider || "birdeye"}: ${body.birdeye?.purpose || "authorization required"}`);
      })
      .catch(() => undefined);
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
    const listed = savedReports.find((report) => report.id === reportId);
    await open((listed || await reportDisplay(reportId)) as Report);
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
        financial MATCH. Offline mode is the default. The public sampler still caps at {count(summary?.legacy_candidate_cap ?? 20)}{" "}
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
            <div className="mass-search-table-wrap">
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
            </div>
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
