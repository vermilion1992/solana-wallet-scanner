import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Compass,
  Database,
  FlaskConical,
  GitCompareArrows,
  LayoutDashboard,
  ListFilter,
  Menu,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Star,
  X,
} from "lucide-react";
import { api, bootstrap, loadReportDisplay, workspaceSummary } from "./api";
import { Badge, Button } from "./components";
import { count } from "./format";
import type { Report, State } from "./types";
import {
  Overview,
  ScanView,
  Results,
  CompareView,
  WatchlistView,
} from "./workspace";
import { ReportView } from "./report";
import { SettingsView } from "./settings";
import { DiscoveryView } from "./Discovery";
import { EvidenceAuditView } from "./EvidenceAudit";
import { HistoricalSourceNotice } from "./HistoricalSourceNotice";
import { ResearchView } from "./Research";

export type View =
  | "overview"
  | "discover"
  | "scan"
  | "results"
  | "report"
  | "compare"
  | "watchlist"
  | "settings"
  | "evidence"
  | "research";
export type Actions = {
  state: State;
  busy: string | null;
  run: (
    name: string,
    path: string,
    body?: unknown,
    method?: string,
    message?: string,
  ) => Promise<unknown>;
  refresh: () => Promise<void>;
  navigate: (view: View) => void;
  open: (report: Report) => Promise<void>;
  updateReport: (report: Report) => void;
  manualAddresses?: string[];
  auditManually?: (addresses: string[]) => void;
};
const nav: { view: View; label: string; icon: typeof Compass }[] = [
  { view: "discover", label: "Discover", icon: Search },
  { view: "research", label: "Research", icon: Activity },
  { view: "overview", label: "Overview", icon: LayoutDashboard },
  { view: "results", label: "Results", icon: ListFilter },
  { view: "compare", label: "Compare", icon: GitCompareArrows },
  { view: "watchlist", label: "Watchlist", icon: Star },
  { view: "settings", label: "Settings", icon: Settings2 },
];
const pages: Record<
  View,
  { title: string; eyebrow: string; description: string }
> = {
  discover: {
    title: "Find wallets worth investigating",
    eyebrow: "WALLET DISCOVERY",
    description:
      "Discover or paste public wallets, check identity, then screen a bounded sample.",
  },
  research: {
    title: "Would following the signals have worked?",
    eyebrow: "SCREENING & FORWARD RESEARCH",
    description: "Saved trading evidence, risk observations, and quote-based paper portfolios with realistic delays and costs.",
  },
  overview: {
    title: "Your research workspace",
    eyebrow: "THE BIG PICTURE",
    description:
      "A clear view of your wallets, your evidence, and what comes next.",
  },
  scan: {
    title: "Audit a wallet you already know",
    eyebrow: "ADVANCED MANUAL SCAN",
    description:
      "Start with public wallet addresses. Keep the scope small and the standards high.",
  },
  results: {
    title: "Every result, with a reason",
    eyebrow: "RESEARCH RESULTS",
    description:
      "Screen your reports without losing sight of the evidence behind them.",
  },
  report: {
    title: "Wallet report",
    eyebrow: "UNDER THE SURFACE",
    description:
      "Trace every conclusion back to its positions and source records.",
  },
  compare: {
    title: "Put the details side by side",
    eyebrow: "WALLET COMPARISON",
    description:
      "Compare wallets with the same reporting window and metric definitions.",
  },
  watchlist: {
    title: "Keep an eye on the signal",
    eyebrow: "YOUR WATCHLIST",
    description: "A local collection of public wallets you want to revisit.",
  },
  settings: {
    title: "Make the research yours",
    eyebrow: "WORKSPACE SETTINGS",
    description:
      "Your thresholds, your free-data allowance, your local workspace.",
  },
  evidence: {
    title: "Review saved transaction records",
    eyebrow: "SCOPED EVIDENCE AUDIT",
    description:
      "Inspect supplied records and their fees. Wallet-wide history and profit need separate evidence.",
  },
};
let bootPromise: Promise<unknown> | undefined;

export function replaceActiveReport(current: Report | null, next: Report) {
  return current?.id === next.id && next.report_view?.view === "display"
    ? next
    : current;
}

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [view, setView] = useState<View>("discover");
  const [activeReport, setActiveReport] = useState<Report | null>(null);
  const reportRequest = useRef(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [manualAddresses, setManualAddresses] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [bootError, setBootError] = useState("");
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
    null,
  );
  const [menu, setMenu] = useState(false);
  const [evidence, setEvidence] = useState<{
    hash: string;
    data: unknown;
  } | null>(null);
  const refresh = useCallback(async () => {
    setState(await workspaceSummary());
  }, []);
  useEffect(() => {
    let canceled = false;
    bootPromise ??= bootstrap();
    bootPromise
      .then(() => workspaceSummary())
      .then((data) => {
        if (!canceled) setState(data);
      })
      .catch((error) => {
        if (!canceled) setBootError(error.message);
      });
    return () => {
      canceled = true;
    };
  }, []);
  const active =
    state?.observations?.some((observation) => observation.status === "running") ||
    state?.scans.some((scan) => ["queued", "running"].includes(scan.status)) ||
    state?.discovery_cohorts?.some((cohort) =>
      ["queued", "running"].includes(cohort.status),
    );
  useEffect(() => {
    if (!active && !state?.settings.refresh_minutes) return;
    const timer = window.setInterval(
      () =>
        refresh().catch((error) =>
          setToast({ text: error.message, error: true }),
        ),
      active ? 4000 : 10000,
    );
    return () => window.clearInterval(timer);
  }, [active, state?.settings.refresh_minutes, refresh]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(timer);
  }, [toast]);
  const navigate = (next: View) => {
    if (next !== "report") {
      reportRequest.current += 1;
      setBusy((current) => current === "report-open" ? null : current);
    }
    setView(next);
    setMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const open: Actions["open"] = async (report) => {
    const request = ++reportRequest.current;
    setBusy("report-open");
    try {
      const detail = await loadReportDisplay(report);
      if (request !== reportRequest.current) return;
      setActiveReport(detail);
      navigate("report");
    } catch (error) {
      if (request === reportRequest.current)
        setToast({
          text:
            error instanceof Error
              ? error.message
              : "The report could not be opened.",
          error: true,
        });
    } finally {
      if (request === reportRequest.current)
        setBusy((current) => current === "report-open" ? null : current);
    }
  };
  const run: Actions["run"] = async (
    name,
    path,
    body,
    method = "POST",
    message,
  ) => {
    setBusy(name);
    try {
      const result = await api(path, method, body);
      await refresh();
      if (message) setToast({ text: message });
      return result;
    } catch (error) {
      setToast({
        text:
          error instanceof Error
            ? error.message
            : "The request could not be completed.",
        error: true,
      });
      throw error;
    } finally {
      setBusy(null);
    }
  };
  const safeRun: Actions["run"] = async (...args) => {
    try {
      return await run(...args);
    } catch {
      return undefined;
    }
  };
  const showEvidence = async (hash: string) => {
    setBusy("evidence");
    try {
      setEvidence({ hash, data: await api(`/evidence/${hash}`) });
    } catch (error) {
      setToast({
        text:
          error instanceof Error
            ? error.message
            : "Evidence could not be loaded.",
        error: true,
      });
    } finally {
      setBusy(null);
    }
  };
  const toggleSelect = (id: string) =>
    setSelected((items) =>
      items.includes(id)
        ? items.filter((item) => item !== id)
        : items.length >= 4
          ? (setToast({ text: "Compare up to four reports at a time." }), items)
          : [...items, id],
    );
  if (!state)
    return (
      <main className="startup">
        <div className="brand-symbol">
          <Compass size={29} />
        </div>
        <span className="eyebrow">WALLET ATLAS</span>
        <h1>
          {bootError ? "Open your local session" : "Opening your workspace"}
        </h1>
        <p>{bootError || "Connecting to the local research service…"}</p>
        {!bootError && <Activity className="spin" size={22} />}
        <div className="startup-footer">
          <ShieldCheck size={15} /> Local. Read-only. Evidence first.
        </div>
      </main>
    );
  const actions: Actions = {
    state,
    busy,
    run: safeRun,
    refresh,
    navigate,
    open,
    updateReport: (report) => setActiveReport((current) => replaceActiveReport(current, report)),
    manualAddresses,
    auditManually: (addresses) => {
      setManualAddresses(addresses);
      navigate("scan");
    },
  };
  const hasDemo = state.reports.some((report) => report.source === "demo");
  const hasLive = state.reports.some((report) => report.source === "live");
  const page = pages[view];
  const currentReport = activeReport;
  const showDemoBanner =
    hasDemo &&
    (["overview", "results", "compare"].includes(view) ||
      (view === "report" && currentReport?.source === "demo"));
  const mixedDemoContext = hasLive && view !== "report";
  return (
    <div className="app-shell">
      {menu && (
        <button
          aria-label="Close navigation"
          className="nav-scrim"
          onClick={() => setMenu(false)}
        />
      )}
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <button className="brand" onClick={() => navigate("discover")}>
          <span className="brand-symbol">
            <Compass size={27} />
          </span>
          <span>
            <strong>
              Wallet Atlas<span className="brand-period">.</span>
            </strong>
            <small>SOLANA RESEARCH</small>
          </span>
        </button>
        <div className="workspace-label">
          <span className="status-dot" /> LOCAL WORKSPACE
        </div>
        <nav aria-label="Main navigation">
          {nav.map((item) => (
            <button
              key={item.view}
              className={`nav-item ${view === item.view || (view === "report" && item.view === "results") || (["scan", "evidence"].includes(view) && item.view === "discover") ? "active" : ""}`}
              onClick={() => navigate(item.view)}
            >
              <item.icon size={19} />
              <span>{item.label}</span>
              {item.view === "results" && state.reports.length > 0 && (
                <span className="nav-count">{state.reports.length}</span>
              )}
              {item.view === "watchlist" && state.watchlist.length > 0 && (
                <span className="nav-count">{state.watchlist.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="allowance-label">
            <span>
              {state.usage.mode === "setup-pilot"
                ? "Setup pilot allowance"
                : "Provider collection allowance"}
            </span>
            <ShieldCheck size={15} />
          </div>
          <div className="allowance-number">
            {state.provider.configured
              ? count(state.usage.remaining)
              : "Public samples available"}
            <small>
              {state.provider.configured
                ? state.usage.mode === "setup-pilot"
                  ? "pilot credits remaining"
                  : "credits remaining"
                : "Keyless bounded research"}
            </small>
          </div>
          <div className="usage-track">
            <span
              style={{
                width: `${state.usage.cap ? Math.min(100, Math.max(0, ((state.usage.used + state.usage.reserved) / state.usage.cap) * 100)) : 0}%`,
              }}
            />
          </div>
          <button className="sidebar-link" onClick={() => navigate("settings")}>
            Manage data access <ArrowRight size={14} />
          </button>
          <div className="local-footnote">
            <Database size={14} /> Saved on this computer
          </div>
          <span className="version">FREE LOCAL EDITION · V0.3.11</span>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMenu(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {view === "report"
                ? "Wallet report"
                : view === "scan"
                  ? "Advanced manual scan"
                  : view === "evidence"
                    ? "Saved record audit"
                    : nav.find((item) => item.view === view)?.label}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="local-chip">
              <span className="status-dot" /> Local & private
            </span>
            <span className="read-only-chip">
              <ShieldCheck size={14} /> Read-only
            </span>
            <span className="profile">WA</span>
          </div>
        </header>
        <div className="page-content">
          {showDemoBanner && (
            <div className="demo-banner">
              <FlaskConical size={17} />
              <span>
                <strong>
                  {mixedDemoContext
                    ? "Synthetic examples available"
                    : "Offline demonstration"}
                </strong>{" "}
                · Synthetic reports are labelled throughout. They are not wallet
                performance evidence.
              </span>
              <button onClick={() => navigate("results")}>
                View reports <ArrowRight size={14} />
              </button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <span className="eyebrow">{page.eyebrow}</span>
              <h1>
                {view === "report" && currentReport
                  ? currentReport.label || "Wallet report"
                  : page.title}
              </h1>
              <p>{page.description}</p>
            </div>
            {view === "overview" && (
              <Button icon={Search} onClick={() => navigate("discover")}>
                Discover wallets
              </Button>
            )}
            {view === "results" && (
              <Button
                icon={GitCompareArrows}
                variant="secondary"
                disabled={selected.length < 2}
                onClick={() => navigate("compare")}
              >
                Compare{selected.length ? ` (${selected.length})` : ""}
              </Button>
            )}
          </div>
          {["overview", "discover", "scan", "results"].includes(view) && (
            <HistoricalSourceNotice decision={state.historical_source_decision} />
          )}
          {view === "overview" && <Overview {...actions} />}
          {view === "discover" && <DiscoveryView {...actions} />}
          {view === "research" && <ResearchView {...actions} showEvidence={showEvidence} />}
          {view === "scan" && <ScanView {...actions} />}
          {view === "results" && (
            <Results {...actions} selected={selected} onSelect={toggleSelect} />
          )}
          {view === "report" &&
            (currentReport ? (
              <ReportView
                key={currentReport.id}
                {...actions}
                report={currentReport}
                showEvidence={showEvidence}
                selected={selected}
                onSelect={toggleSelect}
              />
            ) : (
              <p>Select a report from Results to inspect it.</p>
            ))}
          {view === "compare" && (
            <CompareView
              {...actions}
              selected={selected}
              onSelect={toggleSelect}
            />
          )}
          {view === "watchlist" && <WatchlistView {...actions} />}
          {view === "settings" && <SettingsView {...actions} />}
          {view === "evidence" && (
            <EvidenceAuditView {...actions} showEvidence={showEvidence} />
          )}
          <footer className="page-footer">
            <span>
              <BookOpen size={14} /> Built for investigation. Every conclusion
              needs a source.
            </span>
            <span>Wallet Atlas · V0.3.11</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <X size={19} /> : <Check size={19} />}
          <span>{toast.text}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {evidence && (
        <div className="modal-backdrop" onClick={() => setEvidence(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="evidence-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="section-heading">
              <div>
                <span className="eyebrow">ARCHIVED SOURCE</span>
                <h2 id="evidence-title">Evidence record</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close evidence"
                onClick={() => setEvidence(null)}
              >
                <X size={20} />
              </button>
            </div>
            <p className="mono evidence-hash">SHA-256 · {evidence.hash}</p>
            <div className="evidence-hint">
              <ShieldCheck size={17} />
              <span>
                The backend verifies the archived record against this checksum
                before returning it.
              </span>
            </div>
            <pre>{JSON.stringify(evidence.data, null, 2)}</pre>
          </section>
        </div>
      )}
    </div>
  );
}
