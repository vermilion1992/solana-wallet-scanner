import { useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CircleHelp,
  Compass,
  FlaskConical,
  Layers3,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  Wallet,
} from "lucide-react";
import type { Actions } from "./App";
import type { DiscoveryCandidate, DiscoveryCohort, Preset, Report } from "./types";
import {
  Badge,
  Button,
  Empty,
  ReportTable,
  SectionHeading,
} from "./components";
import { count, dateTime, decimal, label, parseAddresses, shorten, validAddress } from "./format";
import { ScanCard } from "./workspace";

export function auditableCandidates(cohort?: DiscoveryCohort) {
  const sourceEligible = cohort?.audit_plan
    ? new Set([...cohort.audit_plan.selected_addresses, ...cohort.audit_plan.deferred.map((item) => item.address)])
    : null;
  return (cohort?.candidates ?? []).filter(
    (candidate) =>
      validAddress(candidate.address) &&
      (!sourceEligible || sourceEligible.has(candidate.address)) &&
      candidate.status === "candidate" &&
      candidate.validation?.identity_verified === true &&
      candidate.validation?.account_type === "system-owned signer" &&
      candidate.validation?.economic_signers?.includes(candidate.address),
  );
}

export function plannedAuditAddresses(cohort: DiscoveryCohort | undefined, auditCap: number, manual?: string[]) {
  const eligible = new Set(auditableCandidates(cohort).map((candidate) => candidate.address));
  const proposed = manual ?? cohort?.audit_plan?.selected_addresses ?? [...eligible];
  return [...new Set(proposed)].filter((address) => eligible.has(address)).slice(0, auditCap);
}

export function qualifiedCandidates(
  cohort: DiscoveryCohort | undefined,
  reports: Report[],
  activePreset: Preset,
  currentMethodology?: string,
) {
  return (cohort?.candidates ?? []).filter((candidate) => {
    const qualification = candidate.qualification;
    const report = reports.find(
      (item) => item.id === (qualification?.report_id ?? candidate.report_id),
    );
    return (
      candidate.status === "candidate" &&
      candidate.validation?.identity_verified === true &&
      candidate.validation?.account_type === "system-owned signer" &&
      candidate.validation?.economic_signers?.includes(candidate.address) &&
      typeof currentMethodology === "string" && !!currentMethodology &&
      qualification?.qualified === true &&
      qualification.financial_policy === "MATCH" &&
      qualification.evidence_status === "verified" &&
      samePresetSnapshot(qualification.preset_snapshot, activePreset) &&
      qualification.methodology === currentMethodology &&
      typeof qualification.profit_sol === "string" &&
      report?.source === "live" &&
      !report.preview &&
      report.address === candidate.address &&
      report.policy === "MATCH" &&
      report.evidence_status === "verified" &&
      report.methodology === currentMethodology &&
      report.metrics.profit_sol?.status === "known" &&
      report.metrics.profit_sol.value !== null
    );
  });
}

export function samePresetSnapshot(snapshot: Preset | null | undefined, active: Preset) {
  if (!snapshot || !Object.keys(active).length) return false;
  const keys = Object.keys(snapshot);
  return keys.length === Object.keys(active).length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(active, key) && snapshot[key] === active[key]);
}

export function strictFilterSummary(preset: Preset) {
  const value = (key: string) => String(preset[key] ?? "—");
  return [
    {
      name: "History windows",
      detail: `${value("window_days")}-day report · ${value("verification_days")}-day verification`,
    },
    {
      name: "Profit and returns",
      detail: `≥ ${value("min_profit_sol")} SOL after costs · realised ROI ≥ ${value("min_realised_roi_pct")}% · median ROI ≥ ${value("min_median_roi_pct")}%`,
    },
    {
      name: "Win rate and median hold",
      detail: `${value("min_win_rate_pct")}–${value("max_win_rate_pct")}% wins · ${value("min_hold_hours")}–${value("max_hold_hours")} hours`,
    },
    {
      name: "Completed positions",
      detail: `≥ ${value("min_positions")} in ${value("window_days")} days · ≥ ${value("min_positions_90d")} in ${value("verification_days")} days`,
    },
    {
      name: "Mint breadth and rapid sales",
      detail: `${value("min_mints")}–${value("max_mints")} distinct mints · first sale within 5 minutes ≤ ${value("max_rapid_sale_pct")}%`,
    },
    {
      name: "Entries and exits",
      detail: `Average buys ${value("min_avg_buys")}–${value("max_avg_buys")} · average sells ${value("min_avg_sells")}–${value("max_avg_sells")}`,
    },
    {
      name: "Consistency and concentration",
      detail: `≥ ${value("min_positive_weeks")} positive weeks · largest profit contribution ≤ ${value("max_contribution_pct")}%`,
    },
    {
      name: "Economic accounting",
      detail: preset.require_positive_economic_pnl === true
        ? "Positive economic P&L required · external flows and fees accounted for"
        : preset.require_positive_economic_pnl === false
          ? "Positive economic P&L gate disabled in this preset"
          : "Economic P&L setting unavailable",
    },
  ];
}

function riskText(finding: string | { title?: string; detail?: string }) {
  return typeof finding === "string"
    ? finding
    : [finding.title, finding.detail].filter(Boolean).join(" · ");
}

function CandidateCard({
  candidate,
  eligible,
  selected,
  disabled,
  toggle,
  openReport,
  qualified,
  activePreset,
  auditManually,
  checkIdentity,
}: {
  candidate: DiscoveryCandidate;
  eligible: boolean;
  selected: boolean;
  disabled: boolean;
  toggle: () => void;
  openReport?: () => void;
  qualified: boolean;
  activePreset: Preset;
  auditManually?: () => void;
  checkIdentity?: () => void;
}) {
  const findings = candidate.risk?.findings ?? [];
  const unresolved = candidate.risk?.unresolved ?? [];
  const profit = qualified
    ? candidate.qualification?.profit_sol
    : candidate.observed_profit_sol;
  const research = candidate.research;
  const conditionalProfit = research?.conditional_observed_lot_profit_sol;
  const qualification = candidate.qualification;
  const imported = candidate.source === "user-list";
  const audited = !!qualification && qualification.financial_policy !== "NOT_AUDITED";
  const missingSnapshot = audited && !qualification?.preset_snapshot;
  const pastPreset =
    audited && !!qualification?.preset_snapshot &&
    !samePresetSnapshot(qualification.preset_snapshot, activePreset);
  const qualificationLabel = missingSnapshot
    ? "Saved filters unavailable"
    : pastPreset
    ? "Past preset result"
    : qualified
      ? "Meets your filters"
      : qualification?.financial_policy === "MISS"
        ? "Filter mismatch"
        : !qualification || qualification.financial_policy === "NOT_AUDITED"
          ? "Not audited"
          : "Evidence incomplete";
  return (
    <article className={`candidate-card ${selected ? "selected" : ""}`}>
      <div className="candidate-identity">
        <span className="wallet-avatar">
          <Wallet size={18} />
        </span>
        <div>
          <a
            className="candidate-address mono"
            href={`https://solscan.io/account/${encodeURIComponent(candidate.address)}`}
            target="_blank"
            rel="noreferrer"
            title={candidate.address}
          >
            {shorten(candidate.address, 6)} <ArrowUpRight size={13} />
          </a>
          <span>
            {imported ? eligible ? "Imported public list · native identity checked" : "Imported public list · identity unresolved" : <>
              {count(candidate.pools?.length ?? 0)} sampled pools ·{" "}
              {count(candidate.signatures?.length ?? 0)} source transactions
            </>}
          </span>
        </div>
        <input
          type="checkbox"
          checked={selected}
          disabled={!eligible || disabled}
          onChange={toggle}
          aria-label={`Select ${candidate.address} for audit`}
          title={
            eligible
              ? "Select for a bounded wallet audit"
              : "A verified economic signer is required before audit"
          }
        />
      </div>
      <div className="candidate-status">
        <Badge value={candidate.status}>
          {eligible ? "Signer verified" : imported ? "Listed" : label(candidate.status)}
        </Badge>
        <span>{eligible ? "Ready for audit" : "Identity review"}</span>
      </div>
      <p className="candidate-reason">{candidate.reason}</p>
      <div className={`candidate-qualification ${qualified ? "qualified" : ""}`}>
        <span className="eyebrow">PDF FILTER QUALIFICATION</span>
        <Badge value={qualified ? "qualified" : "unresolved"}>
          {qualificationLabel}
        </Badge>
        <p>
          {missingSnapshot
            ? "The frozen filter settings are missing. This result cannot qualify under the active filters."
            : pastPreset
            ? "Saved thresholds differ from the active filters. The version name can stay the same when thresholds change."
            : qualification?.reason ||
              "Verified identity is a discovery lead. Complete accounting and every required filter still need evidence."}
        </p>
        {!!qualification && !pastPreset && qualification.financial_policy !== "NOT_AUDITED" && (
          <small>
            {count(qualification.failed_checks?.length)} failed checks ·{" "}
            {count(qualification.unknown_checks?.length)} unknown checks
          </small>
        )}
      </div>
      <dl className="candidate-measures">
        <div>
          <dt>Profit</dt>
          <dd>
            {profit !== null && profit !== undefined
              ? `${decimal(profit, 9)} SOL`
              : "Unverified"}
            <small>
              {profit !== null && profit !== undefined
                ? qualified
                  ? "Verified reporting-period accounting · saved filter version"
                  : "Observed subset only · not 30-day profit"
                : conditionalProfit !== null && conditionalProfit !== undefined
                  ? `Conditional observed P&L: ${decimal(conditionalProfit, 9)} SOL · assumes no earlier holdings`
                  : "Complete cost basis and exits needed"}
            </small>
          </dd>
        </div>
        <div>
          <dt>Strategy fit</dt>
          <dd>
            {research?.supported_swaps ? "Conditional observed timings" : "Unassessed"}
            <small>
              {research?.supported_swaps
                ? "Fetched episodes only · inspect first sale and 50% / 90% exits in the report"
                : "Entry, first sale, and 50% / 90% exits needed"}
            </small>
          </dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>
            {eligible ? "Native signer check" : "Discovery lead"}
            <small>
              {eligible
                ? "Economic activity checked in sampled transactions"
                : "A third-party address requires native verification"}
            </small>
          </dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>
            {findings.length
              ? `${count(findings.length)} recorded findings`
              : "Unresolved"}
            <small>
              {unresolved.length
                ? `${count(unresolved.length)} checks still need evidence`
                : "Identity verification does not establish trading safety"}
            </small>
          </dd>
        </div>
      </dl>
      <details className="candidate-details">
        <summary>Inspect sources and open questions</summary>
        <div>
          <p className="mono candidate-full-address">{candidate.address}</p>
          {findings.map((finding, index) => (
            <p key={`finding-${index}`}>{riskText(finding)}</p>
          ))}
          {unresolved.map((question, index) => (
            <p key={`unresolved-${index}`}>{question}</p>
          ))}
          {!findings.length && !unresolved.length && (
            <p>
              Token controls, liquidity, insider links, transfers, and
              execution costs require further review.
            </p>
          )}
          {candidate.signatures?.slice(0, 8).map((signature) => (
            <a
              className="text-button mono"
              href={`https://solscan.io/tx/${encodeURIComponent(signature)}`}
              target="_blank"
              rel="noreferrer"
              key={signature}
            >
              Transaction {shorten(signature, 7)} <ArrowUpRight size={12} />
            </a>
          ))}
          {candidate.validation && (
            <pre>{JSON.stringify(candidate.validation, null, 2)}</pre>
          )}
        </div>
      </details>
      {openReport && (
        <button className="candidate-open-report text-button" onClick={openReport}>
          Open audit report <ArrowRight size={13} />
        </button>
      )}
      {!eligible && checkIdentity && (
        <button className="candidate-open-report text-button" disabled={disabled} onClick={checkIdentity}>
          Check native identity <ShieldCheck size={13} />
        </button>
      )}
      {imported && auditManually && (
        <button className="candidate-open-report text-button" onClick={auditManually}>
          Open advanced manual audit <ArrowRight size={13} />
        </button>
      )}
    </article>
  );
}

export function DiscoveryView({
  state,
  busy,
  run,
  navigate,
  open,
  auditManually,
}: Actions) {
  const [cohortId, setCohortId] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [importInput, setImportInput] = useState("");
  const [importError, setImportError] = useState("");
  const importFileRef = useRef<HTMLInputElement>(null);
  const importedAddresses = useMemo(() => parseAddresses(importInput), [importInput]);
  const [selection, setSelection] = useState<{
    cohortId: string;
    addresses: string[];
  } | null>(null);
  const cohorts = state.discovery_cohorts ?? [];
  const cohort = cohorts.find((item) => item.id === cohortId) ?? cohorts[0];
  const candidates = cohort?.candidates ?? [];
  const eligible = auditableCandidates(cohort);
  const universe = state.candidate_universe;
  const importCap = Math.min(20, state.settings.limits.candidate_cap || 20);
  const presetVersion = String(state.preset.version ?? "");
  const qualified = qualifiedCandidates(cohort, state.reports, state.preset, state.methodology);
  const auditCap = Math.min(5, state.settings.limits.deep_audit_cap || 5);
  const selected = plannedAuditAddresses(cohort, auditCap,
    selection && cohort && selection.cohortId === cohort.id ? selection.addresses : undefined);
  const isDiscovering =
    busy === "discovery" ||
    cohorts.some((item) => ["queued", "running"].includes(item.status));
  const candidateAddresses = new Set(candidates.map((item) => item.address));
  const auditScans = state.scans.filter(
    (scan) =>
      scan.source !== "demo" &&
      ((cohort && scan.discovery_cohort_id === cohort.id) ||
        cohort?.audit_scan_ids?.includes(scan.id)),
  );
  const scanIds = new Set(auditScans.map((scan) => scan.id));
  const auditReports = state.reports.filter(
    (report) =>
      report.source === "live" &&
      candidateAddresses.has(report.address) &&
      (!auditScans.length || (report.scan_id && scanIds.has(report.scan_id))),
  );
  const toggle = (address: string) => {
    if (!cohort) return;
    setSelection({
      cohortId: cohort.id,
      addresses: selected.includes(address)
        ? selected.filter((item) => item !== address)
        : selected.length < auditCap
          ? [...selected, address]
          : selected,
    });
  };
  const discover = async () => {
    const result = (await run(
      "discovery",
      "/discovery",
      { pool_cap: 3, candidate_cap: 20, validate_cap: 8 },
      "POST",
      "Discovery started. The sample is saved locally as identity checks progress.",
    )) as { cohort_id?: string; id?: string } | undefined;
    if (result?.cohort_id || result?.id)
      setCohortId(result.cohort_id ?? result.id ?? "");
  };
  const audit = async () => {
    if (!cohort || !selected.length) return;
    await run(
      `audit-${cohort.id}`,
      `/discovery/${encodeURIComponent(cohort.id)}/audit`,
      { addresses: selected },
      "POST",
      "Candidate audit queued. Reports will show missing evidence explicitly.",
    );
  };
  const checkIdentity = async (addresses: string[]) => {
    if (!cohort) return;
    await run(
      `identity-${cohort.id}`,
      `/discovery/${encodeURIComponent(cohort.id)}/identity`,
      { addresses: addresses.slice(0, auditCap) },
      "POST",
      "Native identity results saved. Missing evidence stays unresolved.",
    );
  };
  const connectKey = async () => {
    if (!providerKey.trim()) return;
    const result = await run(
      "discovery-key",
      "/provider/key",
      { api_key: providerKey.trim() },
      "POST",
      "Helius connected. Run discovery again to verify candidate identities.",
    );
    if (result) setProviderKey("");
  };
  const importCandidates = async () => {
    const result = await run(
      "candidate-import", "/discovery/import",
      { addresses: importedAddresses.addresses }, "POST",
      "Public addresses saved as listed candidates. Chain activity and identity remain unverified.",
    ) as { cohort_id?: string; id?: string } | undefined;
    if (result) {
      setImportInput("");
      setImportError("");
      if (result.cohort_id || result.id) setCohortId(result.cohort_id ?? result.id ?? "");
    }
  };
  const poolCount =
    cohort?.counts?.pools_sampled ??
    cohort?.pools?.length ??
    new Set(
      candidates.flatMap((candidate) =>
        (candidate.pools ?? []).map((pool) => JSON.stringify(pool)),
      ),
    ).size;
  return (
    <>
      <section className="discovery-hero">
        <div className="discovery-hero-copy">
          <div className="hero-pill">
            <span className="status-dot" /> START WITH PUBLIC TRADES
          </div>
          <h2>
            Find credible trading evidence.
            <br />
            <span>Observe whether you could follow.</span>
          </h2>
          <p>
            Find trading addresses from a small sample of active Solana pools.
            Or paste public addresses below. Check native identity, investigate
            a small sample, and save a screening assessment. Shortlist wallets
            for forward quote-based paper observation in Research.
          </p>
          <div className="discovery-actions">
            <Button
              icon={Search}
              busy={isDiscovering}
              disabled={!!busy && busy !== "discovery"}
              onClick={discover}
            >
              {isDiscovering ? "Finding candidates…" : "Find wallet candidates"}
            </Button>
            <button
              className="discovery-manual"
              onClick={() => navigate("scan")}
            >
              <SlidersHorizontal size={15} /> Advanced manual scan
            </button>
          </div>
          <div className="discovery-source-note">
            <Layers3 size={14} /> Public GeckoTerminal pool sample · up to 3
            pools / 20 leads / 8 native identity checks
          </div>
        </div>
        <div className="discovery-path">
          <span className="eyebrow">FROM LEAD TO EVIDENCE</span>
          <div>
            <span>01</span>
            <p>
              <strong>Discover</strong>
              <small>Public trades reveal candidate addresses.</small>
            </p>
            <Compass size={18} />
          </div>
          <div>
            <span>02</span>
            <p>
              <strong>Verify</strong>
              <small>Check the signer, account owner, and economic flow.</small>
            </p>
            <ShieldCheck size={18} />
          </div>
          <div>
            <span>03</span>
            <p>
              <strong>Audit</strong>
              <small>Separate profit, strategy fit, evidence, and risk.</small>
            </p>
            <Activity size={18} />
          </div>
        </div>
      </section>
      <div className="discovery-context">
        <CircleHelp size={18} />
        <p>
          <strong>Discovery leads are not recommendations.</strong> A
          third-party sample is not 30-day accounting. Verified identity does
          not establish profit, copyability, or protection from a scam.
        </p>
      </div>
      <div className="discovery-access">
        <span>
          <span className="status-dot" /> Public discovery needs no API key
        </span>
        {state.provider.configured ? (
          <span>
            <ShieldCheck size={15} /> Helius connected for native checks
          </span>
        ) : (
          <button className="text-button" onClick={() => navigate("settings")}>
            Configure historical collection <ArrowRight size={14} />
          </button>
        )}
      </div>
      {!state.provider.configured && (
        <section className="discovery-key-card">
          <div>
            <strong>Connect historical collection with your Helius key</strong>
            <p>
              Native identity checks can use public RPC. Historical audits use
              the saved provider allowance; confirm your billing cycle in Settings
              for extended audits.
            </p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void connectKey();
            }}
          >
            <label className="visually-hidden" htmlFor="discovery-helius-key">
              Helius API key
            </label>
            <input
              id="discovery-helius-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Helius API key"
              value={providerKey}
              onChange={(event) => setProviderKey(event.target.value)}
            />
            <Button
              type="submit"
              variant="secondary"
              icon={ShieldCheck}
              busy={busy === "discovery-key"}
              disabled={!providerKey.trim() || !!busy}
            >
              Connect historical collection
            </Button>
          </form>
        </section>
      )}
      <div className="discovery-stats">
        {[
          {
            value: qualified.length,
            label: "Qualified by your filters",
            note: "Live MATCH · verified evidence · active preset",
          },
          {
            value: cohort?.source === "user-list" ? candidates.length : cohort?.counts?.leads_observed ?? candidates.length,
            label: cohort?.source === "user-list" ? "Listed public addresses" : "Provider leads",
            note: cohort?.source === "user-list" ? "Imported list · chain activity unverified" : "Addresses observed in sampled trades",
          },
          {
            value: eligible.length,
            label: "Verified economic addresses",
            note: "Sampled native signer and flow checks",
          },
          {
            value: auditReports.length,
            label: "Wallet audit reports",
            note: "Evidence completeness assessed separately",
          },
        ].map((stat) => (
          <div key={stat.label}>
            <span>{stat.label}</span>
            <strong>{count(stat.value)}</strong>
            <small>{stat.note}</small>
          </div>
        ))}
      </div>
      <section className="panel strict-filter-panel">
        <SectionHeading
          title="Your PDF filters, applied to the evidence"
          subtitle={`Blueprint page 9 · ${String(state.preset.name ?? "Saved preset")} · ${presetVersion || "Version unavailable"}`}
          action={
            <button className="text-button" onClick={() => navigate("settings")}>
              Review filters <ArrowRight size={14} />
            </button>
          }
        />
        <div className={`qualification-overview ${qualified.length ? "qualified" : ""}`}>
          <CircleHelp size={18} />
          <p>
            <strong>
              {qualified.length
                ? `${count(qualified.length)} wallet${qualified.length === 1 ? "" : "s"} meet the saved filters.`
                : "No wallet qualifies yet."}
            </strong>{" "}
            Native signer checks and conditional observed profit do not count
            as qualification. Every required financial and evidence gate must
            pass; follower exploitation and token risks are assessed separately.
          </p>
        </div>
        <div className="strict-filter-grid">
          {strictFilterSummary(state.preset).map((filter) => (
            <div key={filter.name}>
              <strong>{filter.name}</strong>
              <p>{filter.detail}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="panel public-list-panel">
        <details>
          <summary><Upload size={16} /> Import a public candidate list</summary>
          <div className="public-list-content">
            <p>
              Save addresses from a list you already have. Imported addresses
              start as listed; the import does not observe trades, verify
              identity, or qualify a wallet.
            </p>
            <div className="input-label-row">
              <label htmlFor="candidate-import-addresses">Public Solana addresses</label>
              <button className="text-button" onClick={() => importFileRef.current?.click()}>
                <Upload size={14} /> Choose file
              </button>
              <input
                ref={importFileRef}
                type="file"
                accept=".csv,.json,.txt,text/plain,application/json,text/csv"
                className="visually-hidden"
                aria-label="Import public address file"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  if (file.size > 1024 * 1024) {
                    setImportError("Address list files must be smaller than 1 MB.");
                    return;
                  }
                  setImportError("");
                  setImportInput(await file.text());
                }}
              />
            </div>
            <textarea
              id="candidate-import-addresses"
              className="mono public-list-input"
              placeholder="Paste public addresses, one per line…"
              value={importInput}
              onChange={(event) => setImportInput(event.target.value)}
              spellCheck={false}
            />
            <div className="input-summary">
              <span>{count(importedAddresses.addresses.length)} valid, unique addresses</span>
              <span>Up to {importCap} per imported list</span>
            </div>
            {(importError || importedAddresses.invalid.length > 0 || importedAddresses.addresses.length > importCap) && (
              <div className="inline-alert">
                <CircleHelp size={16} />
                {importError || (importedAddresses.addresses.length > importCap
                  ? `Keep this list to ${importCap} addresses or fewer.`
                  : `${count(importedAddresses.invalid.length)} invalid entries. Correct them before importing.`)}
              </div>
            )}
            <div className="public-list-actions">
              <span>Saved locally · uses no provider credits</span>
              <Button
                icon={Upload}
                busy={busy === "candidate-import"}
                disabled={!!busy || !importedAddresses.addresses.length || !!importedAddresses.invalid.length || importedAddresses.addresses.length > importCap}
                onClick={importCandidates}
              >
                Save public list
              </Button>
            </div>
          </div>
        </details>
      </section>
      {universe && (
        <section className="panel saved-universe-panel">
          <SectionHeading
            title="Saved candidate universe"
            subtitle={`${count(universe.counts.unique_candidates)} unique addresses across ${count(universe.counts.cohorts)} saved lists and samples. Repeated addresses are grouped together.`}
          />
          <div className="universe-stage-key">
            <span>Listed: a public address was saved</span>
            <span>Observed: source trades were recorded</span>
            <span>Identity checked: native signer evidence</span>
            <span>Sample audited: fetched raw records reviewed</span>
            <span>History reconstructed: coverage demonstrated</span>
          </div>
          {universe.candidates.length ? (
            <div className="table-scroll">
              <table className="saved-universe-table">
                <thead><tr>
                  <th>Public wallet</th><th>Sources</th><th>Observed</th>
                  <th>Identity checked</th><th>Sample audited</th><th>History reconstructed</th><th />
                </tr></thead>
                <tbody>{universe.candidates.map((candidate) => (
                  <tr key={candidate.address}>
                    <td><span className="mono" title={candidate.address}>{shorten(candidate.address, 6)}</span><small>{count(candidate.cohort_ids.length)} saved origins</small></td>
                    <td>{candidate.origin_types.map((origin) => origin === "user-list" ? "Imported list" : "Pool trades").join(" · ")}</td>
                    {(["observed", "identity_checked", "sample_audited", "history_reconstructed"] as const).map((stage) => (
                      <td key={stage} title={candidate.reason}>
                        <Badge value={candidate.states[stage] ? "known" : "unknown"}>
                          {candidate.states[stage] ? "Evidenced" : "Not established"}
                        </Badge>
                      </td>
                    ))}
                    <td>
                      <button className="text-button" onClick={() => {
                        const id = candidate.audit_eligible_cohort_ids[0] ?? candidate.cohort_ids[0];
                        if (id) setCohortId(id);
                      }}>Review source <ArrowRight size={13} /></button>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <Empty title="Your saved universe starts here" detail="Public pool samples and imported lists are grouped here as you save them." />}
          {!!universe.counts.omitted_candidates && <p className="universe-limit-note">Showing {count(universe.counts.returned_candidates)} of {count(universe.counts.unique_candidates)} saved addresses in this bounded view.</p>}
          {universe.limitations.length > 0 && <details className="universe-limitations"><summary>Saved universe limits</summary>{universe.limitations.map((note, index) => <p key={index}>{note}</p>)}</details>}
        </section>
      )}
      <section className="panel discovery-results">
        <SectionHeading
          title="Your discovery sample"
          subtitle={
            cohort
              ? `Saved ${dateTime(cohort.created_at)} · ${count(poolCount)} pools sampled · ${cohort.stage || label(cohort.status)}`
              : "No address needed. Start with a bounded sample of public pool trades."
          }
          action={
            cohorts.length > 1 ? (
              <select
                className="discovery-cohort-select"
                aria-label="Saved discovery sample"
                value={cohort?.id ?? ""}
                onChange={(event) => setCohortId(event.target.value)}
              >
                {cohorts.map((item) => (
                  <option value={item.id} key={item.id}>
                    {dateTime(item.created_at)} · {label(item.status)}
                  </option>
                ))}
              </select>
            ) : cohort ? (
              <Badge value={cohort.status} />
            ) : undefined
          }
        />
        {cohort?.limitations?.length ? (
          <details className="discovery-limitations" open={!candidates.length}>
            <summary>
              Sample limits and missing evidence ({cohort.limitations.length})
            </summary>
            {cohort.limitations.map((limitation, index) => (
              <p key={index}>{limitation}</p>
            ))}
          </details>
        ) : null}
        {!!cohort?.audit_plan?.deferred.length && (
          <details className="discovery-limitations">
            <summary>Deferred research ({cohort.audit_plan.deferred.length})</summary>
            {cohort.audit_plan.deferred.map((item) => (
              <p key={item.address}>{shorten(item.address)} · {item.reason || "Review saved evidence before collecting again."}</p>
            ))}
          </details>
        )}
        {candidates.length ? (
          <>
            <div className="discovery-audit-bar">
              <div>
                <strong>{count(selected.length)} selected for audit</strong>
                <p>
                  Select up to {auditCap} verified economic addresses. Start
                  with a small sample, then use an explicit continuation budget
                  from its saved screening assessment.
                </p>
              </div>
              {candidates.some((candidate) => candidate.validation?.identity_verified !== true) && (
                <Button
                  variant="secondary"
                  icon={ShieldCheck}
                  busy={busy === `identity-${cohort?.id}`}
                  disabled={!!busy}
                  onClick={() => checkIdentity(candidates.filter((candidate) => candidate.validation?.identity_verified !== true).map((candidate) => candidate.address))}
                >
                  Check native identities (up to {auditCap})
                </Button>
              )}
              <Button
                icon={Search}
                busy={busy === `audit-${cohort?.id}`}
                disabled={
                  !selected.length || !!busy
                }
                onClick={audit}
              >
                Audit candidates{selected.length ? ` (${selected.length})` : ""}
              </Button>
            </div>
            {!eligible.length && (
              <div className="discovery-no-verified">
                <CircleHelp size={16} /> No economic signer passed the sampled native checks. Use Check native identity to collect bounded evidence. An imported address alone establishes no trust.
              </div>
            )}
            <div className="candidate-grid">
              {candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.address}
                  candidate={candidate}
                  qualified={qualified.some((item) => item.address === candidate.address)}
                  activePreset={state.preset}
                  auditManually={auditManually ? () => auditManually([candidate.address]) : undefined}
                  checkIdentity={() => checkIdentity([candidate.address])}
                  eligible={eligible.some(
                    (item) => item.address === candidate.address,
                  )}
                  selected={selected.includes(candidate.address)}
                  disabled={
                    !!busy ||
                    (!selected.includes(candidate.address) &&
                      selected.length >= auditCap)
                  }
                  toggle={() => toggle(candidate.address)}
                  openReport={
                    state.reports.some((report) => report.id === candidate.report_id)
                      ? () => {
                          const report = state.reports.find(
                            (item) => item.id === candidate.report_id,
                          );
                          if (report) open(report);
                        }
                      : undefined
                  }
                />
              ))}
            </div>
          </>
        ) : (
          <Empty
            title={
              isDiscovering
                ? "Reading the public pool sample"
                : cohort
                  ? "No candidates in this sample"
                  : "Let the scanner find the starting point"
            }
            detail={
              cohort?.reason ||
              "Pool activity and public API availability vary. Each discovery sample is saved locally for review."
            }
            icon={isDiscovering ? Activity : Compass}
            action={
              !isDiscovering ? (
                <Button
                  variant="secondary"
                  icon={Search}
                  disabled={!!busy}
                  onClick={discover}
                >
                  Find wallet candidates
                </Button>
              ) : undefined
            }
          />
        )}
      </section>
      {auditScans.length > 0 && (
        <section className="panel">
          <SectionHeading
            title="Candidate audit progress"
            subtitle="Collected history can remain partial. Profit and risk conclusions require their own evidence."
          />
          {auditScans.map((scan) => (
            <ScanCard key={scan.id} scan={scan} busy={busy} run={run} />
          ))}
        </section>
      )}
      {auditReports.length > 0 && (
        <section className="panel">
          <SectionHeading
            title="Audit reports for this sample"
            subtitle="Open a report to inspect accounting, policy fit, and unresolved records."
          />
          <ReportTable reports={auditReports} onOpen={open} />
        </section>
      )}
      <div className="discovery-bottom">
        <section className="panel copy-research">
          <SectionHeading
            title="What makes a wallet copyable?"
            subtitle="Profit alone does not tell you whether you can follow its trades."
          />
          <div className="copy-research-grid">
            <div>
              <strong>Timing and exits</strong>
              <p>
                Check time to first sale, 50% and 90% exits, partial sales,
                and whether the edge survives your execution delay.
              </p>
            </div>
            <div>
              <strong>Profit quality</strong>
              <p>
                Reconstruct transfer-adjusted cost basis and fees. Check if
                one token, one week, or an insider allocation drives returns.
              </p>
            </div>
            <div>
              <strong>Token and execution risk</strong>
              <p>
                Review liquidity, token controls, linked-wallet concentration,
                transfer costs, and slippage for your intended trade size.
              </p>
            </div>
          </div>
        </section>
        <section className="discovery-demo">
          <FlaskConical size={22} />
          <h3>Explore the audit workflow</h3>
          <p>
            Load synthetic offline reports to inspect profit calculations,
            missing evidence, and policy checks without using credits.
          </p>
          <button
            className="text-button"
            disabled={!!busy}
            onClick={() =>
              run("demo", "/demo", {}, "POST").then((result) => {
                if (result) navigate("results");
              })
            }
          >
            {busy === "demo" ? "Preparing demo…" : "Load offline demo"}
            <ArrowRight size={15} />
          </button>
          <button
            className="text-button"
            onClick={() => navigate("settings")}
          >
            Configure extended audit allowance <ArrowRight size={15} />
          </button>
        </section>
      </div>
    </>
  );
}
