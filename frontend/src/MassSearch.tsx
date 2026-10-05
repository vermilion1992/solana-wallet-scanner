import { useEffect, useState } from "react";
import { Download, Play, RefreshCw, Search } from "lucide-react";
import type { Actions } from "./App";
import type { MassSearchCandidate, MassSearchRun } from "./types";
import { Badge, Button, Empty, SectionHeading } from "./components";
import { api } from "./api";
import { count, decimal, label, shorten } from "./format";

const STAGES = ["triage", "behaviour", "reconstruct", "forward_select"] as const;

export function massSearchCorpusLabel(kind?: string) {
  if (kind === "GENUINE_LIVE") return "Genuine live collection";
  if (kind === "GENUINE_REPLAY") return "Genuine archived replay";
  return "Synthetic / development";
}

export function massSearchEmptyReason(run?: MassSearchRun | null) {
  if (!run) return { state: "not_scanned", action: "Create a Search run, then acquire a frozen universe." };
  const unique = run.universe?.unique_candidates ?? 0;
  if (unique === 0) return { state: "empty_universe", action: "No valid candidates were retained. Check the source page or import fixture." };
  const triage = run.stages?.triage;
  if (triage && triage.promoted === 0 && triage.deferred > 0) return { state: "budget_or_missing", action: "Survivors were deferred. Inspect reason codes; do not treat this as a completed market search." };
  if (run.corpus_kind === "SYNTHETIC") return { state: "synthetic", action: "This run is synthetic. It cannot prove a live 1,000-wallet search." };
  return { state: "ready", action: "Open a candidate to inspect subset P&L, median hold and exit timing." };
}

export function MassSearchView({ state, busy, run, navigate, refresh }: Actions) {
  const [detail, setDetail] = useState<MassSearchRun | null>(null);
  const [candidates, setCandidates] = useState<MassSearchCandidate[]>([]);
  const [stage, setStage] = useState<(typeof STAGES)[number]>("triage");
  const [blocker, setBlocker] = useState<string>("Live collection is blocked until a named authorization exists.");
  const summary = state.mass_search;
  const activeId = detail?.run_id || summary?.runs?.[0]?.run_id;

  useEffect(() => {
    api("/mass-search/access-blocker")
      .then((value) => {
        const body = value as { birdeye?: { purpose?: string; provider?: string } };
        setBlocker(`${body.birdeye?.provider || "birdeye"}: ${body.birdeye?.purpose || "authorization required"}`);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!activeId) return;
    api(`/mass-search/runs/${activeId}`)
      .then((value) => setDetail(value as MassSearchRun))
      .catch(() => undefined);
  }, [activeId, state.mass_search?.runs?.length]);

  useEffect(() => {
    if (!activeId) return;
    api(`/mass-search/runs/${activeId}/candidates?stage=${stage}&limit=50`)
      .then((value) => setCandidates(((value as { items?: MassSearchCandidate[] }).items || [])))
      .catch(() => setCandidates([]));
  }, [activeId, stage, detail?.status]);

  const empty = massSearchEmptyReason(detail);

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
          onClick={() => run("mass-search-slice", "/mass-search/vertical-slice", { corpus_kind: "SYNTHETIC" }, "POST", "Offline source-to-report slice finished.")}
        >
          Run offline slice
        </Button>
        <Button
          icon={RefreshCw}
          variant="secondary"
          disabled={!activeId || !!busy}
          onClick={() => activeId && run("mass-search-refilter", `/mass-search/runs/${activeId}/refilter`, {}, "POST", "Cached refilter issued no provider calls.")}
        >
          Refilter cached rows
        </Button>
        <Button
          icon={Download}
          variant="secondary"
          disabled={!activeId}
          onClick={() => activeId && api(`/mass-search/runs/${activeId}/export`)}
        >
          Export run
        </Button>
        <Button icon={Search} variant="secondary" onClick={() => navigate("research")}>
          Open research
        </Button>
      </div>
      <p className="research-note">{blocker} Additional spend stays $0. The example authorization file is not a grant.</p>
      {!summary?.runs?.length && <Empty title="Not scanned" detail={empty.action} />}
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
            <select value={stage} onChange={(event) => setStage(event.target.value as (typeof STAGES)[number])}>
              {STAGES.map((name) => (
                <option key={name} value={name}>{label(name)}</option>
              ))}
            </select>
          </label>
        </div>
        {!candidates.length && <Empty title="No rows on this page" detail="Change stage or run the offline slice. Filter changes here do not call providers." />}
        {!!candidates.length && (
          <div className="mass-search-table-wrap">
            <table className="mass-search-table">
              <thead>
                <tr>
                  <th>Address</th>
                  <th>Decision</th>
                  <th>Reported P&amp;L</th>
                  <th>Reasons</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((row) => (
                  <tr key={row.candidate_id}>
                    <td className="mono">{shorten(row.address)}</td>
                    <td><Badge value={row.result || "pending"}>{label(row.result || "pending")}</Badge></td>
                    <td>{row.sort_value ? `${decimal(row.sort_value, 2)} ${row.unit || ""}` : row.metric_state || "unknown"}</td>
                    <td>{(row.reason_codes || []).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Button variant="secondary" onClick={() => refresh()}>Refresh workspace</Button>
    </div>
  );
}
