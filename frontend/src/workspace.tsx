import { useMemo, useRef, useState } from "react";
import { useNarrowViewport } from "./useNarrow";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  CircleHelp,
  Clock3,
  Compass,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  Pause,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Star,
  Trash2,
  Upload,
  Wallet,
} from "lucide-react";
import type { Actions } from "./App";
import type { Report, Scan } from "./types";
import { reportDisplay, uploadArchive } from "./api";
import {
  Badge,
  Button,
  Empty,
  EvidenceHint,
  ListRealisedProfitCell,
  MetricValue,
  ReportTable,
  SectionHeading,
  WindowLabel,
  metricDefinitions,
} from "./components";
import {
  compareDecimal,
  count,
  date,
  label,
  listRealisedProfit,
  parseAddresses,
  shorten,
  validAddress,
} from "./format";

export function ScanCard({
  scan,
  busy,
  run,
}: {
  scan: Scan;
  busy: Actions["busy"];
  run: Actions["run"];
}) {
  return (
    <div className="scan-card">
      <div className="scan-icon">
        <Activity size={20} />
      </div>
      <div className="scan-main">
        <div className="scan-title">
          <strong>{scan.source === "live" && scan.status === "completed" ? "Bounded sample collection finished" : label(scan.stage || scan.status)}</strong>
          <Badge value={scan.status}>
            {scan.source === "live" && scan.status === "completed" ? "Sample collected" : label(scan.status)}
          </Badge>
        </div>
        <p>
          {count(scan.progress.wallets_completed)} /{" "}
          {count(scan.progress.wallets_total)} {scan.source === "live" ? "wallet samples collected" : "wallets reviewed"} ·{" "}
          {count(scan.progress.pages)} pages ·{" "}
          {count(scan.progress.transactions)} transactions
        </p>
        {scan.source === "live" && scan.status === "completed" && (
          <div className="scan-reason">The bounded job finished. Complete history and financial qualification are assessed separately.</div>
        )}
        {scan.reason && <div className="scan-reason">{scan.reason}</div>}
        <div className="scan-meta">
          <span>{date(scan.created_at)}</span>
          <span>{count(scan.progress.credits)} credits</span>
          <span>{count(scan.progress.unresolved)} unresolved items</span>
        </div>
      </div>
      {["running", "queued"].includes(scan.status) ? (
        <Button
          variant="secondary"
          icon={Pause}
          busy={busy === `pause-${scan.id}`}
          onClick={() =>
            run(
              `pause-${scan.id}`,
              `/scans/${scan.id}/pause`,
              {},
              "POST",
              "Pause requested. The current page will finish safely.",
            )
          }
        >
          Pause
        </Button>
      ) : scan.status === "paused" ? (
        <Button
          variant="secondary"
          icon={Play}
          busy={busy === `resume-${scan.id}`}
          onClick={() =>
            run(
              `resume-${scan.id}`,
              `/scans/${scan.id}/resume`,
              {},
              "POST",
              "Scan resumed from its saved checkpoint.",
            )
          }
        >
          Resume
        </Button>
      ) : null}
    </div>
  );
}
export function Overview(actions: Actions) {
  const { state, navigate, open, busy, run } = actions;
  const counts = {
    matches: state.reports.filter((r) => r.policy === "MATCH").length,
    unresolved: state.reports.filter((r) => r.policy === "UNRESOLVED").length,
  };
  const incomplete = state.scans.filter((s) =>
    ["running", "queued", "paused"].includes(s.status),
  );
  const stale = state.reports.filter(
    (r) => r.evidence_status === "stale",
  ).length;
  return (
    <>
      <section className="overview-hero">
        <div className="hero-copy">
          <div className="hero-pill">
            <span className="status-dot" /> EVIDENCE FIRST, ALWAYS
          </div>
          <h2>
            Find the signal.
            <br />
            <span>Keep the evidence.</span>
          </h2>
          <p>
            Understand public Solana wallets through exact accounting, clear
            screening rules, and records you can inspect.
          </p>
          <div className="hero-actions">
            <Button icon={Search} onClick={() => navigate("discover")}>
              Discover wallets
            </Button>
            <button
              className="hero-demo"
              onClick={() =>
                run(
                  "demo",
                  "/demo",
                  {},
                  "POST",
                  "Offline synthetic reports are ready to explore.",
                )
              }
              disabled={busy === "demo"}
            >
              <FlaskConical size={16} />
              {busy === "demo" ? "Preparing demo…" : "Load offline demo"}
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="orbit orbit-three" />
          <div className="orbit-core">
            <Compass size={48} strokeWidth={1.25} />
          </div>
          <div className="orbit-node node-one">
            <Wallet size={20} />
          </div>
          <div className="orbit-node node-two">
            <ShieldCheck size={19} />
          </div>
          <div className="orbit-node node-three">
            <Layers3 size={19} />
          </div>
          <span className="art-label">RECORD → RECONSTRUCT → VERIFY</span>
        </div>
      </section>
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-icon">
            <Wallet size={19} />
          </span>
          <span className="stat-label">Wallet reports</span>
          <strong>{count(state.reports.length)}</strong>
          <small>
            {state.reports.length
              ? "Saved locally and ready to inspect"
              : "Your first investigation starts here"}
          </small>
        </div>
        <div className="stat-card">
          <span className="stat-icon green">
            <CheckCircle2 size={19} />
          </span>
          <span className="stat-label">Policy matches</span>
          <strong>{count(counts.matches)}</strong>
          <small>All required checks passed</small>
        </div>
        <div className="stat-card">
          <span className="stat-icon amber">
            <CircleHelp size={19} />
          </span>
          <span className="stat-label">Unresolved reports</span>
          <strong>{count(counts.unresolved)}</strong>
          <small>Evidence needed before a conclusion</small>
        </div>
        <div className="stat-card">
          <span className="stat-icon blue">
            <Clock3 size={19} />
          </span>
          <span className="stat-label">Unfinished scans</span>
          <strong>{count(incomplete.length)}</strong>
          <small>
            {stale
              ? `${stale} stale reports also need review`
              : "Saved checkpoints keep your place"}
          </small>
        </div>
      </div>
      {incomplete.length > 0 && (
        <section className="panel">
          <SectionHeading
            title="Continue your investigation"
            subtitle="Progress reflects retrieved records; the full history length may be unknown."
          />
          {incomplete.map((scan) => (
            <ScanCard key={scan.id} scan={scan} busy={busy} run={run} />
          ))}
        </section>
      )}
      <div className="overview-bottom">
        <section className="panel recent-panel">
          <SectionHeading
            title="Recent research"
            subtitle="A conclusion is only as strong as its records."
            action={
              state.reports.length ? (
                <button
                  className="text-button"
                  onClick={() => navigate("results")}
                >
                  View all <ArrowRight size={15} />
                </button>
              ) : undefined
            }
          />
          {state.reports.length ? (
            <div className="recent-list">
              {state.reports.slice(0, 4).map((report) => (
                <button
                  className="recent-item"
                  key={report.id}
                  onClick={() => open(report)}
                >
                  <span
                    className={`wallet-avatar ${report.source === "demo" ? "demo-avatar" : ""}`}
                  >
                    {(report.label || report.address).slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <strong>{report.label || shorten(report.address)}</strong>
                    <small>
                      {date(report.created_at)}
                      {report.source === "demo" ? " · Synthetic demo" : ""}
                    </small>
                  </div>
                  <Badge value={report.policy} />
                  <ArrowRight size={16} />
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="Your research starts here"
              detail="Find candidates from public trading pools, or explore the clearly labelled offline demonstration."
              icon={Search}
              action={
                <Button
                  variant="secondary"
                  onClick={() => navigate("discover")}
                  icon={Plus}
                >
                  Find candidates
                </Button>
              }
            />
          )}
        </section>
        <section className="workflow-card">
          <span className="eyebrow">A SMALL SCOPE. A CLEARER PICTURE.</span>
          <h2>
            Three steps to
            <br />a better question.
          </h2>
          <div className="workflow-step">
            <span>01</span>
            <div>
              <strong>Discover trading wallets</strong>
              <p>Public pool leads, checked against transaction signers.</p>
            </div>
          </div>
          <div className="workflow-step">
            <span>02</span>
            <div>
              <strong>Inspect the reconstruction</strong>
              <p>Positions, costs, flows, and missing evidence.</p>
            </div>
          </div>
          <div className="workflow-step">
            <span>03</span>
            <div>
              <strong>Keep what matters</strong>
              <p>Compare reports and build your watchlist.</p>
            </div>
          </div>
          <div className="workflow-foot">
            <ShieldCheck size={16} /> Public addresses. Read-only research.
          </div>
        </section>
      </div>
      {state.scans.filter(
        (s) => !["running", "queued", "paused"].includes(s.status),
      ).length > 0 && (
        <section className="panel">
          <SectionHeading
            title="Completed scan history"
            subtitle="A completed job can still have incomplete evidence."
          />
          {state.scans
            .filter((s) => !["running", "queued", "paused"].includes(s.status))
            .slice(0, 5)
            .map((scan) => (
              <ScanCard key={scan.id} scan={scan} busy={busy} run={run} />
            ))}
        </section>
      )}
    </>
  );
}
export function ScanView({ state, busy, run, navigate, manualAddresses, refresh, open }: Actions) {
  const [input, setInput] = useState((manualAddresses ?? []).join("\n"));
  const [days, setDays] = useState(String(state.preset.window_days || 30));
  const [importError, setImportError] = useState("");
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const parsed = useMemo(() => parseAddresses(input), [input]);
  const cap = state.settings.limits.candidate_cap;
  const ready =
    state.provider.configured &&
    state.provider.free_plan_confirmed &&
    state.provider.capability_status === "passed" &&
    !!state.provider.calibration_address;
  const end = new Date(),
    start = new Date(end.getTime() - Number(days) * 86400000);
  const begin = async () => {
    const result = await run(
      "scan",
      "/scans",
      {
        addresses: parsed.addresses,
        window_days: Number(days),
        source: "manual",
      },
      "POST",
      "Scan queued. Progress and saved checkpoints are shown below.",
    );
    if (result) setInput("");
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    if (file.size > 1024 * 1024) {
      setImportError("Import files must be smaller than 1 MB.");
      return;
    }
    setImportError("");
    setInput(await file.text());
  };
  return (
    <>
      <div className="report-navigation">
        <button className="text-button" onClick={() => navigate("discover")}>
          <ArrowRight size={15} /> Back to wallet discovery
        </button>
        <Button variant="secondary" icon={Search} onClick={() => navigate("evidence")}>
          Review saved transaction records
        </Button>
      </div>
      <section className="panel" style={{ marginBottom: 20 }}>
        <SectionHeading title="Account from saved records" subtitle="Import a scanner evidence ZIP to create a report locally. No provider credits are used." />
        <p>Incomplete history keeps wallet profit and qualification unresolved. The offline example uses synthetic records to demonstrate accounting.</p>
        <label htmlFor="wallet-archive">Wallet evidence ZIP (up to 20 MiB)</label>
        <input id="wallet-archive" type="file" accept=".zip,application/zip" disabled={!!busy || archiveBusy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            event.target.value = '';
            if (file.size > 20 * 1024 * 1024) {setArchiveError('Evidence ZIP must be at most 20 MiB.'); return;}
            setArchiveBusy(true); setArchiveError('');
            try {
              const result = await uploadArchive(file);
              const report = await reportDisplay(result.report_id);
              await refresh();
              await open(report);
            } catch (error) {setArchiveError(error instanceof Error ? error.message : 'Archive import failed.');}
            finally {setArchiveBusy(false);}
          }} />
        {archiveBusy && <p role="status">Accounting from saved records…</p>}
        {archiveError && <p role="alert">{archiveError}</p>}
        <p><a href="/api/archives/example.zip" download>Download offline accounting example</a></p>
      </section>
      <div className="scan-layout">
      <div>
        <section className="panel scan-input-panel">
          <SectionHeading
            title="Choose the wallets"
            subtitle="Paste one address per line, or import a CSV / JSON file."
          />
          <div className="input-label-row">
            <label htmlFor="addresses">Public Solana addresses</label>
            <button
              className="text-button"
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={15} /> Import file
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.json,.txt,text/plain,application/json,text/csv"
              className="visually-hidden"
              onChange={(event) => importFile(event.target.files?.[0])}
            />
          </div>
          <textarea
            id="addresses"
            className="address-input mono"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={
              'Paste public wallet addresses here…\n\nCSV: address,label\nJSON: ["address", "address"]'
            }
            spellCheck={false}
          />
          <div className="input-summary">
            <span className={parsed.addresses.length > cap ? "red-text" : ""}>
              <CheckCircle2 size={15} />
              {parsed.addresses.length} valid, unique addresses
            </span>
            <span>Up to {cap} per batch</span>
          </div>
          {(parsed.invalid.length > 0 || importError) && (
            <div className="inline-alert">
              <CircleHelp size={17} />
              <div>
                {importError ||
                  `${parsed.invalid.length} invalid entries. Correct these before scanning.`}
                {parsed.invalid.length > 0 && (
                  <span className="mono invalid-list">
                    {parsed.invalid.slice(0, 3).join(" · ")}
                  </span>
                )}
              </div>
            </div>
          )}
          <div className="form-grid two">
            <div className="form-field">
              <label htmlFor="window">Reporting window</label>
              <select
                id="window"
                value={days}
                onChange={(event) => setDays(event.target.value)}
              >
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>
            </div>
            <div className="form-field">
              <label>Active preset</label>
              <div className="readonly-field">
                <ListPreset />
                {String(state.preset.name)}
                <button onClick={() => navigate("settings")}>Edit</button>
              </div>
            </div>
          </div>
          <div className="window-info">
            <Clock3 size={15} />
            {date(start.toISOString())} → {date(end.toISOString())} · UTC ·
            exact timestamps frozen when queued
          </div>
          <EvidenceHint />
          <div className="scan-form-footer">
            <span>
              Manual research · {state.settings.limits.deep_audit_cap}{" "}
              deep-audit cap
            </span>
            <Button
              busy={busy === "scan"}
              icon={Search}
              disabled={
                !ready ||
                !parsed.addresses.length ||
                !!parsed.invalid.length ||
                parsed.addresses.length > cap
              }
              onClick={begin}
            >
              Start scan
            </Button>
          </div>
        </section>
        {state.scans.length > 0 && (
          <section className="panel">
            <SectionHeading
              title="Scan queue"
              subtitle="One local worker. Pause and resume without losing the collected evidence."
            />
            {state.scans.slice(0, 10).map((scan) => (
              <ScanCard key={scan.id} scan={scan} busy={busy} run={run} />
            ))}
          </section>
        )}
      </div>
      <div className="scan-aside">
        <section className="panel scope-card">
          <span className="small-icon">
            <ShieldCheck size={21} />
          </span>
          <h3>Bounded by design</h3>
          <p>Your free allowance is a hard guardrail for every read.</p>
          <dl className="scope-list">
            <div>
              <dt>Candidate limit</dt>
              <dd>{count(cap)} wallets</dd>
            </div>
            <div>
              <dt>Deep audits</dt>
              <dd>{count(state.settings.limits.deep_audit_cap)} wallets</dd>
            </div>
            <div>
              <dt>Transactions per wallet</dt>
              <dd>{count(state.settings.limits.transaction_limit)}</dd>
            </div>
            <div>
              <dt>Wallet credit ceiling</dt>
              <dd>{count(state.settings.limits.wallet_credit_limit)}</dd>
            </div>
            <div>
              <dt>Credits available</dt>
              <dd>
                {state.provider.configured
                  ? count(state.usage.remaining)
                  : "Configure provider"}
              </dd>
            </div>
          </dl>
          <p className="small-note">
            History length is unknown until collected. A safe estimate is
            bounded by your wallet credit ceiling; actual use appears as the
            scan progresses.
          </p>
        </section>
        {!ready && (
          <section className="connection-card">
            <h3>Connect your free data source</h3>
            <p>
              Configure a manually obtained Helius Free key, confirm your
              billing cycle, and run the read-only capability test.
            </p>
            <Button
              variant="secondary"
              onClick={() => navigate("settings")}
              icon={ArrowRight}
            >
              Open Settings
            </Button>
          </section>
        )}
        <div className="demo-option">
          <FlaskConical size={20} />
          <strong>Just exploring?</strong>
          <p>
            The offline demo uses synthetic records and no provider credits.
          </p>
          <button
            className="text-button"
            disabled={busy === "demo"}
            onClick={() =>
              run(
                "demo",
                "/demo",
                {},
                "POST",
                "Synthetic offline reports are ready. Explore them in Results.",
              ).then((result) => {
                if (result) navigate("results");
              })
            }
          >
            {busy === "demo" ? "Preparing…" : "Load offline demo"}
            <ArrowRight size={15} />
          </button>
        </div>
      </div>
      </div>
    </>
  );
}
function ListPreset() {
  return <Layers3 size={15} />;
}
export function Results({
  state,
  open,
  selected,
  onSelect,
}: Actions & { selected: string[]; onSelect: (id: string) => void }) {
  const [policy, setPolicy] = useState("ALL");
  const [source, setSource] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"recent" | "profit_desc" | "profit_asc">(
    "recent",
  );
  const reports = useMemo(() => {
    const result = state.reports.filter(
      (r) =>
        (policy === "ALL" || r.policy === policy) &&
        (source === "all" || r.source === source) &&
        `${r.address} ${r.label || ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
    if (sort !== "recent")
      result.sort((a, b) => {
        const x = listRealisedProfit(a).value,
          y = listRealisedProfit(b).value;
        if (x === null || x === undefined)
          return y === null || y === undefined ? 0 : 1;
        if (y === null || y === undefined) return -1;
        return compareDecimal(x, y) * (sort === "profit_desc" ? -1 : 1);
      });
    return result;
  }, [state.reports, policy, source, query, sort]);
  return (
    <section className="panel results-panel">
      <div className="result-toolbar">
        <div className="segmented">
          {["ALL", "MATCH", "MISS", "UNRESOLVED"].map((item) => (
            <button
              key={item}
              className={item === policy ? "active" : ""}
              onClick={() => setPolicy(item)}
            >
              {item === "ALL" ? "All reports" : label(item.toLowerCase())}
              <span>
                {
                  state.reports.filter(
                    (r) => item === "ALL" || r.policy === item,
                  ).length
                }
              </span>
            </button>
          ))}
        </div>
        <div className="results-filters">
          <div className="search-input">
            <Search size={15} />
            <input
              aria-label="Search wallets"
              placeholder="Search wallets…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select
            aria-label="Data source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="all">All sources</option>
            <option value="live">Live records</option>
            <option value="demo">Synthetic demo</option>
            <option value="mass-search">Mass-search subset</option>
          </select>
          <select
            aria-label="Sort results"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="recent">Most recent</option>
            <option value="profit_desc">Profit: high to low</option>
            <option value="profit_asc">Profit: low to high</option>
          </select>
        </div>
      </div>
      {reports.length ? (
        <ReportTable
          reports={reports}
          onOpen={open}
          selected={selected}
          onSelect={onSelect}
        />
      ) : (
        <Empty
          title={
            state.reports.length
              ? "No reports for these filters"
              : "No reports yet"
          }
          detail={
            state.reports.length
              ? "Adjust the filters to inspect your saved reports. Policy thresholds remain unchanged."
              : "Run a small scan or load the offline demonstration to inspect how reports are evaluated."
          }
        />
      )}
      <div className="result-footer">
        <span>
          {reports.length} report{reports.length !== 1 ? "s" : ""}
          {selected.length
            ? ` · ${selected.length} selected for comparison`
            : ""}
        </span>
        <span>
          <ShieldCheck size={14} /> Policy fit ≠ evidence completeness
        </span>
      </div>
    </section>
  );
}
export function CompareView({
  state,
  open,
  selected,
  onSelect,
}: Actions & { selected: string[]; onSelect: (id: string) => void }) {
  const reports = state.reports.filter((report) =>
    selected.includes(report.id),
  );
  const narrow = useNarrowViewport();
  const sameWindows =
    reports.length < 2 ||
    reports.every(
      (r) =>
        r.window.start === reports[0].window.start &&
        r.window.end === reports[0].window.end &&
        r.methodology === reports[0].methodology &&
        r.source === reports[0].source,
    );
  return (
    <>
      <section className="panel">
        <SectionHeading
          title="Choose up to four reports"
          subtitle="Comparisons require identical windows, methodology, and data source."
        />
        <div className="compare-picker">
          {state.reports.slice(0, 100).map((report) => (
            <button
              className={`compare-choice ${selected.includes(report.id) ? "selected" : ""}`}
              key={report.id}
              onClick={() => onSelect(report.id)}
            >
              <span className="choice-check">
                {selected.includes(report.id) ? (
                  <CheckCircle2 size={18} />
                ) : (
                  <Plus size={18} />
                )}
              </span>
              <span>
                <strong>{report.label || shorten(report.address)}</strong>
                <small>
                  {report.source === "demo" ? "Synthetic demo" : report.source === "mass-search" ? "Mass-search subset" : "Live records"}{" "}
                  · {date(report.window.end)}
                </small>
              </span>
            </button>
          ))}
        </div>
        {!state.reports.length && (
          <Empty
            title="Choose reports to compare"
            detail="Complete an investigation first, then select two to four wallet reports."
            icon={GitCompareArrows}
          />
        )}
      </section>
      {reports.length > 0 && (
        <section className="panel compare-panel">
          <SectionHeading
            title="A shared view of the details"
            subtitle={
              sameWindows
                ? reports.some((report) => report.source === "mass-search")
                  ? "Mass-search realised P&L is reconstructed subset, not a wallet-wide MATCH."
                  : "The selected reports use the same window, source, and methodology."
                : "These reports have different windows, data sources, or methodology. Their metrics cannot be compared like for like."
            }
          />
          {reports.some((report) => report.source === "mass-search") && (
            <p className="subset-compare-note">
              Supported closed trades only. Reconstructed subset P&amp;L is not wallet-wide MATCH.
            </p>
          )}
          {!sameWindows && (
            <div className="inline-alert">
              <CircleHelp size={18} />
              <span>
                Select reports with identical reporting windows and methodology
                to enable the metric comparison.
              </span>
            </div>
          )}
          {!narrow && (
            <div className="table-scroll">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>Research measure</th>
                    {reports.map((report) => (
                      <th key={report.id}>
                        <button
                          className="text-button"
                          onClick={() => open(report)}
                        >
                          {report.label || shorten(report.address)}
                          <ArrowRight size={14} />
                        </button>
                        <WindowLabel report={report} />
                        {report.source === "demo" && (
                          <small className="demo-inline">SYNTHETIC DEMO</small>
                        )}
                        {report.source === "mass-search" && (
                          <small className="demo-inline">RECONSTRUCTED SUBSET</small>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Policy fit</td>
                    {reports.map((r) => (
                      <td key={r.id}>
                        <Badge value={r.policy} />
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Evidence status</td>
                    {reports.map((r) => (
                      <td key={r.id}>
                        <Badge value={r.evidence_status} />
                      </td>
                    ))}
                  </tr>
                  {sameWindows &&
                    metricDefinitions.map((metric) => (
                      <tr key={metric.key}>
                        <td title={metric.hint}>{metric.name}</td>
                        {reports.map((r) => (
                          <td key={r.id} className="numeric">
                            {metric.key === "profit_sol" ? (
                              <ListRealisedProfitCell report={r} />
                            ) : (
                              <MetricValue
                                metric={r.metrics[metric.key]}
                                suffix={metric.suffix}
                              />
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          <ul className="compare-cards">
            {reports.map((report) => (
              <li key={`compare-card-${report.id}`}>
                <strong>{report.label || shorten(report.address)}</strong>
                {report.source === "demo" && (
                  <small className="demo-inline">SYNTHETIC DEMO</small>
                )}
                {report.source === "mass-search" && (
                  <small className="demo-inline">RECONSTRUCTED SUBSET</small>
                )}
                <div className="report-card-profit">
                  <span>Realised profit</span>
                  <ListRealisedProfitCell report={report} />
                </div>
                <p>
                  Hold{" "}
                  <MetricValue
                    metric={report.metrics.median_hold_hours}
                    suffix="h"
                  />
                  {" · "}
                  Positions{" "}
                  <MetricValue metric={report.metrics.completed_positions} />
                </p>
                <p>
                  <Badge value={report.policy} />{" "}
                  <Badge value={report.evidence_status} />
                </p>
                <Button variant="secondary" onClick={() => open(report)}>
                  Open report
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
export function WatchlistView({ state, busy, run, open }: Actions) {
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [invalid, setInvalid] = useState(false);
  const save = async () => {
    if (!validAddress(address.trim())) {
      setInvalid(true);
      return;
    }
    const result = await run(
      "watch-add",
      "/watchlist",
      { address: address.trim(), label: name.trim() },
      "POST",
      "Wallet saved to your local watchlist.",
    );
    if (result) {
      setAddress("");
      setName("");
      setInvalid(false);
    }
  };
  return (
    <>
      <section className="panel watch-add">
        <SectionHeading
          title="Save a public wallet"
          subtitle="Watchlist entries are saved locally. Refresh is controlled in Settings."
        />
        <div className="watch-form">
          <div className="form-field">
            <label htmlFor="watch-address">Wallet address</label>
            <input
              id="watch-address"
              className="mono"
              placeholder="Public Solana address"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                setInvalid(false);
              }}
            />
          </div>
          <div className="form-field">
            <label htmlFor="watch-label">
              Label <span className="muted">(optional)</span>
            </label>
            <input
              id="watch-label"
              placeholder="A name for your research"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button
            icon={Plus}
            busy={busy === "watch-add"}
            disabled={!address.trim()}
            onClick={save}
          >
            Add wallet
          </Button>
        </div>
        {invalid && (
          <p className="red-text">
            Enter a valid 32-byte public Solana address.
          </p>
        )}
      </section>
      <section className="panel">
        <SectionHeading
          title="Saved wallets"
          subtitle={`${state.watchlist.length} wallet${state.watchlist.length !== 1 ? "s" : ""} · ${state.settings.refresh_minutes ? `refresh every ${state.settings.refresh_minutes} minutes while app runs` : "manual refresh"}`}
        />
        {state.watchlist.some((item) => item.source === "mass-search" || state.reports.some((report) => report.address === item.address && report.source === "mass-search")) && (
          <p className="research-note">Mass-search shortlist entries are a reconstructed subset, not a wallet-wide MATCH. Quote-only observation is not started from this list.</p>
        )}
        {state.watchlist.length ? (
          <div className="watchlist-list">
            {state.watchlist.map((item) => {
              const report = state.reports.find(
                (r) => r.address === item.address,
              );
              const subset = item.source === "mass-search" || report?.source === "mass-search";
              return (
                <div className="watch-row" key={item.address} data-watch-source={item.source ?? report?.source ?? "unknown"}>
                  <span className="wallet-avatar">
                    <Star size={20} />
                  </span>
                  <div className="watch-wallet">
                    <strong>{item.label || shorten(item.address)}</strong>
                    <small className="mono">{item.address}</small>
                  </div>
                  {report ? (
                    <>
                      <div className="watch-report-meta">
                        <Badge value={report.policy} />
                        {subset && (
                          <>
                            <small className="subset-list-label">Reconstructed subset</small>
                            <small>not a wallet-wide MATCH</small>
                            <ListRealisedProfitCell report={report} />
                          </>
                        )}
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => open(report)}
                        icon={ArrowRight}
                      >
                        Latest report
                      </Button>
                    </>
                  ) : (
                    <span className="muted">{subset ? "Reconstructed subset · no live MATCH" : "No report yet"}</span>
                  )}
                  <button
                    className="icon-button"
                    disabled={busy === `watch-remove-${item.address}`}
                    aria-label={`Remove ${item.label || item.address} from watchlist`}
                    onClick={() =>
                      run(
                        `watch-remove-${item.address}`,
                        `/watchlist/${item.address}`,
                        undefined,
                        "DELETE",
                        "Wallet removed from the watchlist.",
                      )
                    }
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty
            title="A place for wallets worth revisiting"
            detail="Save a public address above or use the star button on a wallet report."
            icon={Star}
          />
        )}
      </section>
    </>
  );
}
