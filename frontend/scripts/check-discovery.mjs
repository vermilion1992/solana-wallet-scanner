import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const project = dirname(dirname(fileURLToPath(import.meta.url)));
const output = mkdtempSync(join(tmpdir(), "wallet-atlas-discovery-"));
const require = createRequire(import.meta.url);
try {
  execFileSync(
    process.execPath,
    [
      join(project, "node_modules/typescript/bin/tsc"),
      "src/Discovery.tsx",
      "src/report.tsx",
      "src/EvidenceAudit.tsx",
      "--target",
      "ES2022",
      "--module",
      "commonjs",
      "--jsx",
      "react-jsx",
      "--skipLibCheck",
      "--esModuleInterop",
      "--outDir",
      output,
    ],
    { cwd: project, stdio: "inherit" },
  );
  symlinkSync(join(project, "node_modules"), join(output, "node_modules"));
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const {
    DiscoveryView,
    auditableCandidates,
    plannedAuditAddresses,
    qualifiedCandidates,
    strictFilterSummary,
  } = require(join(output, "Discovery.js"));
  const {
    ReportView,
    HistoryAssessmentBanner,
    PositionAssessmentBanner,
    AccountPositionEvidenceSection,
    SourceConsistencySection,
    CoverageDetails,
    sourceSetComplete,
  } = require(join(output, "report.js"));
  const { SelectedCohortSection, selectedCohortFreshness } = require(join(output, "SelectedCohorts.js"));
  const { NativeCashObservations, nativeCashAmount } = require(join(output, "NativeCashObservations.js"));
  const { InventoryObservations } = require(join(output, "InventoryObservations.js"));
  const { HistoricalSourceNotice } = require(join(output, "HistoricalSourceNotice.js"));
  const { PaperDetail, ScreeningDetail, defaultPaperSettings, paperSolFromLamports } = require(join(output, "Research.js"));
  const { workspaceSummary, reportDisplay, loadReportDisplay } = require(join(output, "api.js"));
  const { replaceActiveReport } = require(join(output, "App.js"));
  const {
    parseRawEvidenceBundle,
    EvidenceAuditResult,
    EvidenceAuditView,
  } = require(join(output, "EvidenceAudit.js"));
  const address = "11111111111111111111111111111111";
  const lead = {
    address,
    status: "unresolved",
    reason: "Provider lead awaiting native evidence",
    signatures: [],
    pools: [],
  };
  const verified = {
    ...lead,
    status: "candidate",
    reason: "Native identity confirmed in sampled transaction",
    validation: {
      identity_verified: true,
      account_type: "system-owned signer",
      economic_signers: [address],
    },
  };
  const cohort = {
    id: "sample",
    created_at: "2026-10-02T00:00:00+00:00",
    status: "completed",
    stage: "Sample saved",
    candidates: [lead],
    counts: { pools_sampled: 1, leads_observed: 2 },
    limitations: ["Fetched subset does not establish 30-day profit"],
  };
  const state = {
    methodology: "fifo-v3",
    evidence_audit_methodology: "scoped-evidence-audit-v2",
    history_evidence_methodology: "history-evidence-v8",
    position_evidence_methodology: "account-position-evidence-v10",
    source_consistency_methodology: "source-consistency-v4",
    settings: { limits: { deep_audit_cap: 5 }, refresh_minutes: 0 },
    preset: {},
    scans: [],
    reports: [],
    watchlist: [],
    discovery_cohorts: [],
    provider: { configured: false },
    usage: { used: 0, reserved: 0, cap: 200, remaining: 200 },
    storage: {},
  };
  const actions = {
    state,
    busy: null,
    run: async () => undefined,
    refresh: async () => {},
    navigate: () => {},
    open: () => {},
  };
  const render = (nextState) =>
    renderToStaticMarkup(
      React.createElement(DiscoveryView, { ...actions, state: nextState }),
    );
  const button = (html, text) =>
    (html.match(/<button\b[\s\S]*?<\/button>/g) ?? []).find((item) =>
      item.includes(text),
    );
  const initial = render(state);
  assert.ok(button(initial, "Find wallet candidates"));
  assert.ok(!button(initial, "Find wallet candidates").includes("disabled="));
  assert.ok(initial.includes('type="password"'));
  assert.ok(initial.includes("Discovery leads are not recommendations"));
  assert.ok(initial.includes("third-party sample is not 30-day accounting"));

  assert.deepEqual(auditableCandidates(cohort), []);
  const plannedCohort = { ...cohort, candidates: [verified], audit_plan: { selected_addresses: [], deferred: [], excluded: [] } };
  assert.deepEqual(plannedAuditAddresses(plannedCohort, 5), []);
  assert.deepEqual(plannedAuditAddresses(plannedCohort, 5, [address]), []);
  assert.deepEqual(plannedAuditAddresses({ ...plannedCohort, audit_plan: { ...plannedCohort.audit_plan, deferred: [{ address }] } }, 5, [address]), [address]);
  assert.deepEqual(plannedAuditAddresses({ ...plannedCohort, audit_plan: { ...plannedCohort.audit_plan, selected_addresses: [address, address, "invalid"] } }, 5), [address]);
  assert.deepEqual(plannedAuditAddresses({ ...cohort, candidates: [verified] }, 5), [address]);
  assert.deepEqual(auditableCandidates({ ...cohort, candidates: [verified] }), [
    verified,
  ]);
  for (const invalid of [
    { ...verified, status: "rejected" },
    { ...verified, address: "bad address" },
    {
      ...verified,
      validation: { ...verified.validation, identity_verified: false },
    },
    {
      ...verified,
      validation: { ...verified.validation, account_type: "program-owned" },
    },
    {
      ...verified,
      validation: { ...verified.validation, economic_signers: [] },
    },
  ])
    assert.deepEqual(
      auditableCandidates({ ...cohort, candidates: [invalid] }),
      [],
    );

  const unresolved = render({ ...state, discovery_cohorts: [cohort] });
  assert.ok(button(unresolved, "Audit candidates").includes("disabled="));
  assert.ok(unresolved.includes("No economic signer passed"));
  assert.ok(!unresolved.includes("Signer verified"));
  assert.ok(unresolved.includes("Unverified"));

  const native = render({
    ...state,
    provider: { configured: true },
    discovery_cohorts: [{ ...cohort, candidates: [verified] }],
  });
  assert.ok(button(native, "Audit candidates (1)"));
  assert.ok(!button(native, "Audit candidates (1)").includes("disabled="));
  assert.ok(native.includes("Signer verified"));
  assert.ok(
    native.includes("Identity verification does not establish trading safety"),
  );
  assert.ok(!native.includes('type="password"'));

  const observation = render({
    ...state,
    discovery_cohorts: [
      {
        ...cohort,
        candidates: [{ ...lead, observed_profit_sol: "0.123456789" }],
      },
    ],
  });
  assert.ok(observation.includes("0.123456789 SOL"));
  assert.ok(observation.includes("Observed subset only · not 30-day profit"));

  const report = {
    id: "report",
    address,
    source: "live",
    policy: "UNRESOLVED",
    evidence_status: "partial",
    created_at: cohort.created_at,
    methodology: "fifo-v1",
    window: { start: cohort.created_at, end: cohort.created_at },
    metrics: {},
    checks: [],
    coverage: {},
    positions: [],
    events: [],
    evidence: [],
    findings: [],
    notes: [],
    counts: { closed: 0, open: 0, interrupted: 0, unresolved: 1 },
    research: {
      scope: "supported spot swaps in fetched subset",
      history_complete: false,
      supported_swaps: 4,
      closed_episodes: 1,
      unresolved_basis_sales: 1,
      conditional_observed_lot_profit_sol: "0.123456789",
      conditional_first_sale_hours: "1.25",
      conditional_exit_50_hours: "2.5",
      conditional_exit_90_hours: "3.75",
      limitations: ["Opening inventory remains unverified"],
    },
  };
  const research = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(research.includes("Conditional observed P&amp;L"));
  assert.ok(research.includes("Conditional median 50% exit"));
  assert.ok(research.includes("Conditional median 90% exit"));
  assert.ok(research.includes("0.123456789"));
  assert.ok(research.includes("assume no earlier undiscovered"));
  assert.ok(research.includes("Opening inventory remains unverified"));

  const strictPreset = {
    name: "Strict research",
    version: "strict-v0.3",
    window_days: 30,
    verification_days: 90,
    min_profit_sol: "5",
    min_realised_roi_pct: "10",
    min_median_roi_pct: "5",
    min_win_rate_pct: "50",
    max_win_rate_pct: "85",
    min_hold_hours: "1",
    max_hold_hours: "72",
    min_positions: 50,
    min_positions_90d: 100,
    min_mints: 20,
    max_mints: 100,
    max_rapid_sale_pct: "10",
    min_avg_buys: "1",
    max_avg_buys: "2",
    min_avg_sells: "1",
    max_avg_sells: "3",
    min_positive_weeks: 3,
    max_contribution_pct: "25",
    require_positive_economic_pnl: true,
  };
  const filterText = strictFilterSummary(strictPreset)
    .map((item) => item.detail)
    .join(" | ");
  assert.ok(filterText.includes("30-day report · 90-day verification"));
  assert.ok(
    filterText.includes(
      "≥ 5 SOL after costs · realised ROI ≥ 10% · median ROI ≥ 5%",
    ),
  );
  assert.ok(filterText.includes("50–85% wins · 1–72 hours"));
  assert.ok(filterText.includes("≥ 50 in 30 days · ≥ 100 in 90 days"));
  assert.ok(
    filterText.includes(
      "20–100 distinct mints · first sale within 5 minutes ≤ 10%",
    ),
  );
  assert.ok(filterText.includes("Average buys 1–2 · average sells 1–3"));
  assert.ok(
    filterText.includes(
      "≥ 3 positive weeks · largest profit contribution ≤ 25%",
    ),
  );
  assert.ok(filterText.includes("Positive economic P&L required"));
  assert.ok(
    strictFilterSummary({
      ...strictPreset,
      min_profit_sol: "9",
    })[1].detail.includes("≥ 9 SOL"),
  );
  const qualification = {
    qualified: true,
    financial_policy: "MATCH",
    preset_version: "strict-v0.3",
    preset_snapshot: strictPreset,
    methodology: state.methodology,
    window: report.window,
    profit_sol: "5.25",
    evidence_status: "verified",
    report_id: "qualified-report",
    failed_checks: [],
    unknown_checks: [],
    reason: "Every required financial and evidence gate passes",
  };
  const qualifiedReport = {
    ...report,
    id: "qualified-report",
    policy: "MATCH",
    evidence_status: "verified",
    methodology: state.methodology,
    history_assessment: {
      saved_methodology: state.history_evidence_methodology,
      current_methodology: state.history_evidence_methodology,
      state: "current",
      reason: "Current saved history assessment",
    },
    metrics: { profit_sol: { status: "known", value: "5.25" } },
    qualification,
  };
  const qualifiedLead = {
    ...verified,
    report_id: qualifiedReport.id,
    qualification,
  };
  const qualifiedCohort = { ...cohort, candidates: [qualifiedLead] };
  const getQualified = (
    nextCohort = qualifiedCohort,
    nextReports = [qualifiedReport],
    activePreset = strictPreset,
  ) =>
    qualifiedCandidates(
      nextCohort,
      nextReports,
      activePreset,
      state.methodology,
    );
  assert.deepEqual(getQualified(), [qualifiedLead]);
  assert.deepEqual(getQualified(cohort, [report]), []);
  assert.deepEqual(
    getQualified(qualifiedCohort, [{ ...qualifiedReport, source: "demo" }]),
    [],
  );
  assert.deepEqual(
    getQualified(qualifiedCohort, [{ ...qualifiedReport, preview: true }]),
    [],
  );
  assert.deepEqual(
    getQualified(qualifiedCohort, [
      { ...qualifiedReport, evidence_status: "partial" },
    ]),
    [],
  );
  assert.deepEqual(
    getQualified(qualifiedCohort, [qualifiedReport], {
      ...strictPreset,
      version: "strict-v0.4",
    }),
    [],
  );
  assert.deepEqual(
    getQualified({
      ...qualifiedCohort,
      candidates: [
        {
          ...qualifiedLead,
          qualification: { ...qualification, financial_policy: "MISS" },
        },
      ],
    }),
    [],
  );
  assert.deepEqual(
    getQualified({
      ...qualifiedCohort,
      candidates: [
        {
          ...qualifiedLead,
          qualification: { ...qualification, profit_sol: null },
        },
      ],
    }),
    [],
  );
  const filtered = render({
    ...state,
    preset: strictPreset,
    reports: [qualifiedReport],
    discovery_cohorts: [qualifiedCohort],
  });
  assert.ok(filtered.includes("Qualified by your filters"));
  assert.ok(filtered.includes("Meets your filters"));
  assert.ok(filtered.includes("5.25 SOL"));
  assert.ok(filtered.includes("Blueprint page 9"));
  const pastPreset = render({
    ...state,
    preset: { ...strictPreset, version: "strict-v0.4" },
    reports: [qualifiedReport],
    discovery_cohorts: [qualifiedCohort],
  });
  assert.ok(pastPreset.includes("Past preset result"));
  assert.ok(pastPreset.includes("No wallet qualifies yet"));
  const changedFilters = { ...strictPreset, min_profit_sol: "9" };
  assert.deepEqual(
    getQualified(qualifiedCohort, [qualifiedReport], changedFilters),
    [],
  );
  assert.deepEqual(
    getQualified({
      ...qualifiedCohort,
      candidates: [
        {
          ...qualifiedLead,
          qualification: { ...qualification, preset_snapshot: null },
        },
      ],
    }),
    [],
  );
  assert.deepEqual(
    getQualified(qualifiedCohort, [
      { ...qualifiedReport, methodology: "fifo-v1" },
    ]),
    [],
  );
  const sameVersionChange = render({
    ...state,
    preset: changedFilters,
    reports: [qualifiedReport],
    discovery_cohorts: [qualifiedCohort],
  });
  assert.ok(sameVersionChange.includes("Past preset result"));
  assert.ok(sameVersionChange.includes("No wallet qualifies yet"));
  const legacySnapshot = render({
    ...state,
    preset: strictPreset,
    reports: [qualifiedReport],
    discovery_cohorts: [
      {
        ...qualifiedCohort,
        candidates: [
          {
            ...qualifiedLead,
            qualification: { ...qualification, preset_snapshot: null },
          },
        ],
      },
    ],
  });
  assert.ok(legacySnapshot.includes("Saved filters unavailable"));
  const qualifiedReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      state: { ...state, preset: strictPreset },
      report: qualifiedReport,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(qualifiedReportHtml.includes("Meets your saved financial filters"));
  const inconsistentReport = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      state: { ...state, preset: strictPreset },
      report: { ...report, qualification },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(!inconsistentReport.includes("Meets your saved financial filters"));
  const copyReview = {
    scope: "Conditional behavior in fetched transactions",
    conditional: true,
    checks: {
      long_tail_holds: {
        state: "OBSERVED",
        detail:
          "90% sold within five minutes; final remainder held for 48 hours",
        conditional: true,
      },
      follower_exploitation: {
        state: "UNKNOWN",
        detail: "Follower exploitation has not been established",
      },
    },
    findings: [
      {
        severity: "warning",
        title: "Remainder extends final holding time",
        detail: "Most observed quantity was sold before the final hold ended",
        conditional: true,
      },
    ],
    unknown_checks: ["follower_exploitation"],
    notes: ["These records do not establish the trader's intent"],
  };
  const copy = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      state: { ...state, preset: strictPreset },
      report: { ...report, copy_review: copyReview },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(copy.includes("Copy-trading behavior and open questions"));
  assert.ok(copy.includes("Remainder extends final holding time"));
  assert.ok(copy.includes("Follower exploitation has not been established"));
  assert.ok(copy.includes("Conditional fetched-subset observation"));
  assert.ok(copy.includes("1 unresolved check"));
  assert.deepEqual(
    qualifiedCandidates(qualifiedCohort, [qualifiedReport], strictPreset),
    [],
  );
  assert.deepEqual(
    qualifiedCandidates(
      qualifiedCohort,
      [qualifiedReport],
      strictPreset,
      "fifo-v4",
    ),
    [],
  );
  const nextQualification = { ...qualification, methodology: "fifo-v4" };
  const nextReport = {
    ...qualifiedReport,
    methodology: "fifo-v4",
    qualification: nextQualification,
  };
  const nextLead = { ...qualifiedLead, qualification: nextQualification };
  assert.deepEqual(
    qualifiedCandidates(
      { ...cohort, candidates: [nextLead] },
      [nextReport],
      strictPreset,
      "fifo-v4",
    ),
    [nextLead],
  );
  const listed = {
    ...qualifiedLead,
    source: "user-list",
    status: "unresolved",
    signatures: [],
    pools: [],
    reason: "Imported public address; chain activity unverified",
    states: {
      observed: false,
      identity_checked: false,
      sample_audited: false,
      history_reconstructed: false,
    },
  };
  assert.deepEqual(
    auditableCandidates({ ...cohort, candidates: [listed] }),
    [],
  );
  assert.deepEqual(
    qualifiedCandidates(
      { ...cohort, candidates: [listed] },
      [qualifiedReport],
      strictPreset,
      state.methodology,
    ),
    [],
  );
  const universe = {
    version: "saved-candidate-universe-v1",
    candidates: [
      {
        address,
        source: "saved-universe",
        status: "unresolved",
        stage: "listed",
        states: listed.states,
        first_seen: cohort.created_at,
        last_seen: cohort.created_at,
        origin_types: ["user-list"],
        cohort_ids: ["imported"],
        pools: [],
        signatures: [],
        evidence: [],
        report_ids: [],
        audit_eligible_cohort_ids: [],
        reason: listed.reason,
      },
    ],
    counts: { unique_candidates: 1, cohorts: 2, duplicate_records: 1 },
    limits: { candidate_cap: 20 },
    limitations: [],
  };
  const listedHtml = render({
    ...state,
    preset: strictPreset,
    reports: [qualifiedReport],
    candidate_universe: universe,
    discovery_cohorts: [
      { ...cohort, id: "imported", source: "user-list", candidates: [listed] },
    ],
  });
  assert.ok(listedHtml.includes("Listed public addresses"));
  assert.ok(
    listedHtml.includes("Imported public list · identity unresolved"),
  );
  assert.ok(listedHtml.includes("No wallet qualifies yet"));
  assert.ok(listedHtml.includes("Saved candidate universe"));
  assert.ok(
    listedHtml.includes("1 unique addresses across 2 saved lists and samples"),
  );
  assert.ok(listedHtml.includes("History reconstructed"));
  assert.ok(listedHtml.includes("Not established"));
  assert.ok(!listedHtml.includes("Signer verified"));
  assert.ok(listedHtml.includes("Check native identity"));
  const checkedImport = { ...qualifiedLead, source: "user-list" };
  assert.deepEqual(auditableCandidates({ ...cohort, candidates: [checkedImport] }), [checkedImport],
    "An imported address needs the same native identity proof as a discovered candidate");
  assert.deepEqual(qualifiedCandidates({ ...cohort, candidates: [checkedImport] }, [qualifiedReport], strictPreset, state.methodology), [checkedImport],
    "Import provenance alone cannot permanently exclude a fully evidenced native wallet");
  assert.deepEqual(auditableCandidates({ ...cohort, candidates: [{ ...checkedImport, validation: { ...checkedImport.validation, identity_verified: false } }] }), [],
    "Import alone never supplies native identity");
  const paper = {
    id: "paper-synthetic", address, strategy: "fixed-entry-first-sale-v1", status: "stopped",
    settings: { ...defaultPaperSettings }, started_at: cohort.created_at, updated_at: cohort.created_at,
    stop_reason: "Stopped by owner", signals: [], quote_requests: [],
    positions: [{ id: "open-loss", mint: address, status: "open", cost_lamports: "100010000", opened_at: cohort.created_at,
      mark: { net_value_lamports: "40000000" }, exit_unavailable: true }],
    gaps: [{ reason: "subscription disconnected" }],
    summary: { initial_capital_sol: "10", cash_sol: "9.89999", realised_pnl_sol: "0.02", open_positions: 1,
      closed_positions: 1, open_cost_sol: "0.10001", marked_open_value_sol: "0.04", economic_pnl_sol: "-0.04001",
      valuation_status: "known", signal_count: 4, quote_count: 3, unavailable_quotes: 1, complete_observation: false },
  };
  const paperHtml = renderToStaticMarkup(React.createElement(PaperDetail, { observation: paper }));
  assert.ok(paperHtml.includes("-0.04001"), "Open losses remain in overall paper outcomes");
  assert.ok(paperHtml.includes("sell quote unavailable"));
  assert.ok(paperHtml.includes("subscription disconnected"));
  assert.ok(paperHtml.includes("Frozen at run creation"));
  assert.ok(paperHtml.includes("Quotes do not guarantee execution"));
  assert.ok(paperHtml.includes("counted once"), "Pool/provider fees are not modeled a second time");
  const unknownPaperHtml = renderToStaticMarkup(React.createElement(PaperDetail, { observation: {
    ...paper, summary: { ...paper.summary, economic_pnl_sol: null, marked_open_value_sol: null, valuation_status: "unknown" },
  } }));
  assert.ok(unknownPaperHtml.includes("Incomplete valuation"));
  assert.ok(unknownPaperHtml.includes("Open value unavailable"));
  const missingPaperSourceHtml = renderToStaticMarkup(React.createElement(PaperDetail, { observation: {
    ...paper, summary: { ...paper.summary, source_availability: { state: "UNKNOWN", reason: "Quote source archive unavailable" }, supported_economic_pnl_sol: null },
    copyability: { status: "insufficient_evidence", reasons: ["Quote source archive unavailable"], preset_snapshot: { name: "Forward quote research" } },
  } }));
  assert.ok(missingPaperSourceHtml.includes("Unsupported source evidence"));
  assert.ok(missingPaperSourceHtml.includes("cannot support a complete positive copying conclusion"));
  assert.ok(missingPaperSourceHtml.includes("Quote source archive unavailable"));
  assert.equal(paperSolFromLamports("-100000001"), "-0.100000001");
  assert.equal(paperSolFromLamports("9007199254740993000001"), "9007199254740.993000001");
  assert.equal(paperSolFromLamports(100), undefined);
  const screenHtml = renderToStaticMarkup(React.createElement(ScreeningDetail, { screening: {
    id: "synthetic-screen", version: "wallet-screening-v1", report_id: "report", address,
    result: "insufficient_evidence", label: "Insufficient evidence", reason: "Budget stopped collection",
    reasons: [{ key: "identity", state: "UNKNOWN", reason: "Native evidence missing", evidence: [] }],
    trading_evidence: { supported_swaps: 2, matched_sales: 1, unmatched_sales: 3, conditional_matched_lot_profit_sol: "0.5", open_exposure: [], early_exits: {} },
    risk_observations: [{ key: "creator_relationship", state: "UNKNOWN", reason: "No reviewed relationship proof", evidence: [] }],
    collection: { stop_reason: "Transaction budget exhausted", transactions: 20 },
  }, showEvidence: () => undefined }));
  assert.ok(screenHtml.includes("Transaction budget exhausted"));
  assert.ok(screenHtml.includes("Native evidence missing"));
  assert.ok(screenHtml.includes("3 unmatched or basis-unresolved sales"));
  assert.ok(screenHtml.includes("No reviewed relationship proof"));
  assert.ok(screenHtml.includes("Strict financial qualification"));
  const intervals = {
    four_weeks: {
      start: "2026-09-04T00:00:00+00:00",
      end: cohort.created_at,
      status: "complete",
      source: "reviewed history",
      reason: "All four independent weeks are evidenced",
    },
  };
  const shortWindow = {
    ...report,
    window: { start: "2026-09-25T00:00:00+00:00", end: cohort.created_at },
    metric_intervals: intervals,
    metrics: {
      positive_weeks: {
        status: "known",
        value: "4",
        population: "Four independent weeks",
      },
    },
  };
  const weeklyHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: shortWindow,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(weeklyHtml.includes("Independent four-week interval"));
  assert.ok(weeklyHtml.includes("Sep 4, 2026"));
  assert.ok(weeklyHtml.includes("Coverage: Complete"));
  assert.ok(weeklyHtml.includes("All four independent weeks are evidenced"));
  const missingWeeks = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: {
        ...shortWindow,
        metric_intervals: {
          four_weeks: {
            ...intervals.four_weeks,
            status: "partial",
            reason: "The first independent week has missing fees",
          },
        },
      },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(missingWeeks.includes("Coverage: Partial"));
  assert.ok(
    missingWeeks.includes("The first independent week has missing fees"),
  );
  const bundle = {
    version: "raw-evidence-v1",
    address,
    transactions: [{ signature: "sample", raw: {} }],
    scope: { kind: "transaction_set", signatures: ["sample"] },
  };
  assert.deepEqual(parseRawEvidenceBundle(JSON.stringify(bundle)), bundle);
  assert.throws(
    () => parseRawEvidenceBundle(JSON.stringify({ addresses: [address] })),
    /raw-evidence-v1/,
  );
  assert.throws(
    () =>
      parseRawEvidenceBundle(JSON.stringify({ ...bundle, transactions: [] })),
    /1–20/,
  );
  assert.throws(
    () =>
      parseRawEvidenceBundle(
        JSON.stringify({ ...bundle, transactions: Array(21).fill({}) }),
      ),
    /1–20/,
  );
  assert.throws(
    () => parseRawEvidenceBundle(" ".repeat(4 * 1024 * 1024 + 1)),
    /4 MiB/,
  );
  const recordAudit = {
    id: "record-audit",
    created_at: cohort.created_at,
    bundle_hash: "a".repeat(64),
    source: "unverified-import",
    address,
    scope: {
      kind: "transaction_set",
      signatures: ["sample"],
      accounts: [address],
      history_complete: false,
      description:
        "Explicit transaction set; complete wallet history is not established",
    },
    certificate: {
      version: state.evidence_audit_methodology,
      status: "SCOPED_RECONSTRUCTION",
      scope_kind: "transaction_set",
      content_hash: "b".repeat(64),
      wallet_history_complete: false,
      financial_qualification: "UNRESOLVED",
      checks: {
        fee_allocation: {
          state: "PASS",
          detail: "Wallet-paid fees reconcile within the supplied records",
          evidence: [],
        },
        chain_provenance: {
          state: "UNKNOWN",
          detail:
            "Imported content has not been authenticated as a chain observation",
          evidence: [],
        },
        wallet_profit: {
          state: "UNKNOWN",
          detail:
            "Complete history and opening costs have not been established",
          evidence: [],
        },
      },
    },
    metrics: {
      gross_buy_consideration_sol: {
        status: "known",
        value: "0.123456789",
        unit: "SOL",
      },
      wallet_profit_sol: { status: "unknown", value: null, unit: "SOL" },
    },
    evidence: [],
    notes: [],
  };
  const renderRecord = (
    audit,
    currentMethodology = state.evidence_audit_methodology,
  ) =>
    renderToStaticMarkup(
      React.createElement(EvidenceAuditResult, { audit, currentMethodology }),
    );
  const recordHtml = renderRecord(recordAudit);
  assert.ok(recordHtml.includes("Unverified import"));
  assert.ok(
    recordHtml.includes(
      "does not establish that an arbitrary import came from the Solana chain",
    ),
  );
  assert.ok(recordHtml.includes("Supplied records reconcile"));
  assert.ok(recordHtml.includes("0.123456789"));
  assert.ok(recordHtml.includes("Wallet profit</span><strong>Unknown"));
  assert.ok(
    recordHtml.includes(
      "Complete history and opening costs have not been established",
    ),
  );
  assert.ok(recordHtml.includes("/api/evidence/audits/record-audit/export"));
  const reviewedHtml = renderRecord({
    ...recordAudit,
    source: "raw-mainnet-records",
  });
  assert.ok(reviewedHtml.includes("Reviewed mainnet record"));
  assert.ok(reviewedHtml.includes("Wallet profit</span><strong>Unknown"));
  const feeRow = (html) =>
    html.match(
      /<div class="check-row" data-record-check="fee_allocation">[\s\S]*?<\/span><\/div>/,
    )?.[0] ?? "";
  assert.ok(feeRow(recordHtml).includes('class="badge pass"'));
  assert.ok(!recordHtml.includes("Rebuild needed"));
  const oldAudit = structuredClone(recordAudit);
  oldAudit.certificate.version = "scoped-evidence-audit-v1";
  const oldSnapshot = structuredClone(oldAudit);
  const oldHtml = renderRecord(oldAudit);
  assert.ok(oldHtml.includes("Saved audit uses a previous method"));
  assert.ok(oldHtml.includes("Older saved assessment"));
  assert.ok(oldHtml.includes("Archived amounts within the supplied records"));
  assert.ok(oldHtml.includes("0.123456789"));
  assert.ok(oldHtml.includes("/api/evidence/audits/record-audit/export"));
  assert.ok(oldHtml.includes(oldAudit.certificate.content_hash));
  assert.ok(feeRow(oldHtml).includes("Saved assessment: Pass"));
  assert.ok(
    feeRow(oldHtml).includes("Rebuild required for the current fee assessment"),
  );
  assert.ok(feeRow(oldHtml).includes("Rebuild needed"));
  assert.ok(!feeRow(oldHtml).includes('class="badge pass"'));
  assert.ok(!oldHtml.includes("Supplied records reconcile"));
  assert.ok(oldHtml.includes("Wallet profit</span><strong>Unknown"));
  assert.ok(
    oldHtml.includes("Financial qualification</span><strong>Unresolved"),
  );
  assert.deepEqual(oldAudit, oldSnapshot);
  const incompleteFeeAudit = structuredClone(recordAudit);
  incompleteFeeAudit.certificate.status = "INCOMPLETE";
  incompleteFeeAudit.certificate.checks.fee_allocation.state = "UNKNOWN";
  const incompleteFeeHtml = renderRecord(incompleteFeeAudit);
  assert.ok(incompleteFeeHtml.includes("Supplied records need more evidence"));
  assert.ok(feeRow(incompleteFeeHtml).includes('class="badge unknown"'));
  assert.ok(!feeRow(incompleteFeeHtml).includes('class="badge pass"'));
  const noMethodHtml = renderRecord(recordAudit, "");
  assert.ok(noMethodHtml.includes("Current record-audit method unavailable"));
  assert.ok(!feeRow(noMethodHtml).includes('class="badge pass"'));
  const futureAudit = structuredClone(recordAudit);
  futureAudit.certificate.version = "scoped-evidence-audit-v3";
  assert.ok(
    renderRecord(futureAudit, futureAudit.certificate.version).includes(
      "Supplied records reconcile",
    ),
  );
  const savedViewHtml = renderToStaticMarkup(
    React.createElement(EvidenceAuditView, {
      ...actions,
      state: { ...state, evidence_audits: [oldAudit] },
      showEvidence: () => {},
    }),
  );
  assert.ok(savedViewHtml.includes("Current method: scoped-evidence-audit-v2"));
  assert.ok(button(savedViewHtml, "Audit reviewed example"));
  const liveReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(button(liveReportHtml, "Rebuild from saved records"));
  assert.ok(liveReportHtml.includes("Missing history remains unresolved"));
  const busyReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      busy: "another-action",
      report,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(
    button(busyReportHtml, "Rebuild from saved records").includes("disabled="),
  );
  const demoReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: { ...report, source: "demo" },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(!button(demoReportHtml, "Rebuild from saved records"));
  const previewReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: { ...report, preview: true },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(!button(previewReportHtml, "Rebuild from saved records"));
  const currentHistory = {
    saved_methodology: state.history_evidence_methodology,
    current_methodology: state.history_evidence_methodology,
    state: "current",
    reason: "Current assessment still has unknown ownership coverage",
  };
  const renderHistory = (
    nextReport = report,
    currentMethodology = state.history_evidence_methodology,
  ) =>
    renderToStaticMarkup(
      React.createElement(HistoryAssessmentBanner, {
        report: nextReport,
        currentMethodology,
      }),
    );
  const currentHistoryHtml = renderHistory({
    ...report,
    history_assessment: currentHistory,
  });
  assert.ok(currentHistoryHtml.includes('data-history-assessment="current"'));
  assert.ok(currentHistoryHtml.includes("Current history method"));
  assert.ok(
    currentHistoryHtml.includes(
      "individual gates still determine which evidence remains unknown",
    ),
  );
  assert.ok(currentHistoryHtml.includes(currentHistory.reason));
  const historicalReport = {
    ...report,
    metrics: { profit_sol: { status: "known", value: "123456789.123456789" } },
    history_assessment: {
      ...currentHistory,
      saved_methodology: "history-evidence-v1",
      state: "rebuild_required",
      reason: "Ownership continuity must be reassessed",
    },
  };
  const historicalSnapshot = structuredClone(historicalReport);
  const historicalHistoryHtml = renderHistory(historicalReport);
  assert.ok(
    historicalHistoryHtml.includes(
      'data-history-assessment="rebuild_required"',
    ),
  );
  assert.ok(
    historicalHistoryHtml.includes("Saved history assessment requires rebuild"),
  );
  assert.ok(
    historicalHistoryHtml.includes(
      "Saved native period receipts are historical assessments",
    ),
  );
  assert.ok(historicalHistoryHtml.includes("history-evidence-v1"));
  assert.ok(historicalHistoryHtml.includes(state.history_evidence_methodology));
  assert.ok(
    historicalHistoryHtml.includes(
      "Saved figures and source records remain unchanged",
    ),
  );
  assert.deepEqual(historicalReport, historicalSnapshot);
  assert.ok(renderHistory().includes('data-history-assessment="missing"'));
  assert.ok(
    renderHistory({
      ...report,
      history_assessment: {
        ...currentHistory,
        saved_methodology: null,
        state: "missing",
      },
    }).includes("No current history assessment"),
  );
  assert.ok(
    renderHistory(
      { ...report, history_assessment: currentHistory },
      "",
    ).includes("Current history method unavailable"),
  );
  assert.ok(
    renderHistory({
      ...report,
      history_assessment: {
        ...currentHistory,
        saved_methodology: "history-evidence-v1",
      },
    }).includes('data-history-assessment="rebuild_required"'),
  );
  assert.equal(
    renderHistory({
      ...report,
      source: "demo",
      history_assessment: currentHistory,
    }),
    "",
  );
  assert.equal(
    renderHistory({
      ...report,
      preview: true,
      history_assessment: currentHistory,
    }),
    "",
  );
  const staleQualificationHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      state: { ...state, preset: strictPreset },
      report: {
        ...qualifiedReport,
        history_assessment: historicalReport.history_assessment,
      },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(
    !staleQualificationHtml.includes("Meets your saved financial filters"),
  );
  assert.ok(staleQualificationHtml.includes("Current history evidence needed"));
  assert.ok(
    staleQualificationHtml.includes("/api/export/reports/qualified-report.csv"),
  );
  const unknownAccountMetric = {
    status: "unknown",
    value: null,
    unit: "hours",
    population: "Enumerated account episodes",
    reason: "Opening account inventory is not independently known",
  };
  const unknownStage = {
    state: "UNKNOWN",
    reason: "Earlier acquisition records are needed",
    evidence: [],
    dependencies: ["opening_zero"],
  };
  const knownStage = {
    state: "PASS",
    reason: "Source-backed account episode interval",
    evidence: ["c".repeat(64)],
    dependencies: [],
  };
  const completeSourceSet = { state: "PASS", complete: true, raw_reference_count: 40001, authenticated_reference_count: 40001, omitted_link_count: 0, invalid_authenticated_link_count: 0, unique_link_count: 9, unique_hash_count: 9, inspected_hash_count: 9, omitted_hash_count: 0, invalid_link_count: 0, unauthenticated_link_count: 0, budget: { max_unique_hashes: 40000 }, reason: "All authenticated links were normalized and every distinct archive inspected.", evidence: ["c".repeat(64)] };
  const accountEpisode = {
    id: "episode-one",
    account: address,
    mint: address,
    status: "unresolved",
    start: null,
    end: null,
    opening_raw: "10",
    closing_raw: null,
    acquired_raw: "10",
    sold_raw: "5",
    hold_hours: unknownAccountMetric,
    stages: {
      source_consistency: unknownStage,
      placement: unknownStage,
      opening_zero: unknownStage,
      strict_zero: unknownStage,
      hold: unknownStage,
      basis: unknownStage,
    },
    sources: [],
    signatures: [],
  };
  const accountEvidence = {
    version: state.position_evidence_methodology,
    trust_boundary:
      "Checksum-verified archived native collector/provider receipts; not independent mainnet authentication",
    scope: "Enumerated account episodes only",
    counts: { known_closed: 0, open: 0, unresolved: 1 },
    known_account_hold_median_hours: unknownAccountMetric,
    positions: [accountEpisode],
    recovery_actions: [
      {
        kind: "acquisition_backfill",
        account: address,
        reason: "Find earlier acquisitions before declaring an opening zero",
        requires_network: true,
      },
    ],
    limitations: [
      "Closed or previously owned accounts can remain undiscovered",
    ],
  };
  const currentPosition = {
    saved_methodology: state.position_evidence_methodology,
    current_methodology: state.position_evidence_methodology,
    state: "current",
    reason:
      "Current account-scoped assessment; wallet-wide financial gates remain independent",
  };
  const renderAccount = (evidence, overrides = {}) =>
    renderToStaticMarkup(
      React.createElement(AccountPositionEvidenceSection, {
        evidence,
        assessment: currentPosition,
        currentMethodology: state.position_evidence_methodology,
        historyCurrent: true,
        ...overrides,
        showEvidence: () => {},
      }),
    );
  const accountSnapshot = structuredClone(accountEvidence);
  const accountHtml = renderAccount(accountEvidence);
  assert.ok(accountHtml.includes("Source-backed account episodes"));
  assert.ok(accountHtml.includes("not independent mainnet authentication"));
  assert.ok(
    accountHtml.includes(
      "They do not establish whole-wallet median hold, profit, strict-filter qualification, or trading safety",
    ),
  );
  assert.ok(
    accountHtml.includes("Known account-episode hold median: </strong><span"),
  );
  assert.ok(accountHtml.includes(">Unknown</span>"));
  assert.ok(accountHtml.includes("Earlier acquisition records are needed"));
  assert.ok(accountHtml.includes("Placement"));
  assert.ok(
    accountHtml.includes(
      "Find earlier acquisitions before declaring an opening zero",
    ),
  );
  assert.ok(accountHtml.includes("Requires additional source reads"));
  assert.deepEqual(accountEvidence, accountSnapshot);
  assert.ok(renderAccount().includes("No account-episode assessment is saved"));
  const emptyAccountHtml = renderAccount({
    ...accountEvidence,
    counts: { known_closed: 0, open: 0, unresolved: 0 },
    positions: [],
    recovery_actions: [],
  });
  assert.ok(
    emptyAccountHtml.includes(
      "No enumerated account episodes could be reconstructed",
    ),
  );
  assert.ok(emptyAccountHtml.includes("Account hold remains Unknown"));
  const knownAccountEvidence = {
    ...accountEvidence,
    counts: { known_closed: 1, open: 0, unresolved: 0 },
    known_account_hold_median_hours: {
      status: "known",
      value: "3.25",
      unit: "hours",
      population: "One enumerated token-account episode",
    },
    positions: [
      {
        ...accountEpisode,
        status: "known_closed",
        opening_raw: "0",
        closing_raw: "0",
        hold_hours: { status: "known", value: "3.25", unit: "hours" },
        stages: {
          source_consistency: knownStage,
          placement: knownStage,
          opening_zero: knownStage,
          strict_zero: knownStage,
          hold: knownStage,
          basis: unknownStage,
          fees: unknownStage,
          classification: unknownStage,
          valuation: unknownStage,
        },
        source_paths: [{ signature: "synthetic-signature", hash: "c".repeat(64), paths: ["meta.preTokenBalances[accountIndex=1].uiTokenAmount.amount", "meta.postTokenBalances[accountIndex=1].uiTokenAmount.amount"] }],
        source_set: completeSourceSet,
      },
    ],
  };
  const knownAccountHtml = renderAccount(knownAccountEvidence);
  assert.ok(knownAccountHtml.includes("3.25 hours"));
  assert.ok(knownAccountHtml.includes("Placement"));
  assert.ok(knownAccountHtml.includes("3.25 h"));
  assert.ok(knownAccountHtml.includes("One enumerated token-account episode"));
  assert.ok(knownAccountHtml.includes("Source ccccc…ccccc"));
  assert.ok(knownAccountHtml.includes('class="badge unknown"'));
  assert.ok(!knownAccountHtml.includes("Filters pass"));
  const renderPositionBanner = (
    nextReport,
    currentMethodology = state.position_evidence_methodology,
  ) =>
    renderToStaticMarkup(
      React.createElement(PositionAssessmentBanner, {
        report: nextReport,
        currentMethodology,
      }),
    );
  const legacyPositionEvidence = structuredClone(knownAccountEvidence);
  legacyPositionEvidence.version = "account-position-evidence-v1";
  legacyPositionEvidence.known_account_hold_median_hours.value = "6";
  legacyPositionEvidence.positions[0].hold_hours.value = "6";
  legacyPositionEvidence.positions[0].acquired_raw =
    "9007199254740993123456789";
  legacyPositionEvidence.positions[0].stages.chronology = knownStage;
  const legacyPositionAssessment = {
    ...currentPosition,
    saved_methodology: legacyPositionEvidence.version,
    state: "rebuild_required",
    reason:
      "Same-slot order must be reassessed under the current account method",
  };
  const legacyPositionSnapshot = structuredClone(legacyPositionEvidence);
  const legacyPositionHtml = renderAccount(legacyPositionEvidence, {
    assessment: legacyPositionAssessment,
  });
  assert.ok(
    legacyPositionHtml.includes('data-position-freshness="rebuild_required"'),
  );
  assert.ok(legacyPositionHtml.includes("Saved account-episode hold median:"));
  assert.ok(legacyPositionHtml.includes("6 hours · rebuild needed"));
  assert.ok(legacyPositionHtml.includes("6 h · saved / rebuild needed"));
  assert.ok(legacyPositionHtml.includes("Saved Pass"));
  assert.ok(
    legacyPositionHtml.includes("Historical saved result · rebuild required"),
  );
  assert.ok(legacyPositionHtml.includes("9007199254740993123456789"));
  assert.ok(!legacyPositionHtml.includes('class="badge pass"'));
  assert.ok(!legacyPositionHtml.includes("Known account-episode hold median:"));
  assert.deepEqual(legacyPositionEvidence, legacyPositionSnapshot);
  const historyCurrentPositionOldReport = {
    ...report,
    history_assessment: currentHistory,
    position_assessment: legacyPositionAssessment,
    coverage: { position_evidence: legacyPositionEvidence },
  };
  const independentFreshnessHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: historyCurrentPositionOldReport,
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(
    independentFreshnessHtml.includes('data-history-assessment="current"'),
  );
  assert.ok(
    independentFreshnessHtml.includes(
      'data-position-assessment="rebuild_required"',
    ),
  );
  assert.ok(
    independentFreshnessHtml.includes(
      "Saved account-position assessment requires rebuild",
    ),
  );
  assert.ok(
    independentFreshnessHtml.includes("Same-slot order must be reassessed"),
  );
  assert.ok(button(independentFreshnessHtml, "Rebuild from saved records"));
  assert.ok(independentFreshnessHtml.includes("without provider calls"));
  assert.ok(
    independentFreshnessHtml.includes("/api/export/reports/report.csv"),
  );
  const missingPositionMethodHtml = renderAccount(knownAccountEvidence, {
    currentMethodology: "",
  });
  assert.ok(
    missingPositionMethodHtml.includes(
      'data-position-freshness="method_unavailable"',
    ),
  );
  assert.ok(!missingPositionMethodHtml.includes('class="badge pass"'));
  assert.ok(
    renderPositionBanner(historyCurrentPositionOldReport, "").includes(
      "Current account-position method unavailable",
    ),
  );
  assert.ok(
    renderPositionBanner(report).includes('data-position-assessment="missing"'),
  );
  assert.ok(
    renderAccount(knownAccountEvidence, { assessment: undefined }).includes(
      'data-position-freshness="missing"',
    ),
  );
  assert.ok(
    renderAccount(knownAccountEvidence, { historyCurrent: false }).includes(
      'data-position-freshness="history_not_current"',
    ),
  );
  assert.ok(
    !renderAccount(knownAccountEvidence, { historyCurrent: false }).includes(
      'class="badge pass"',
    ),
  );
  assert.ok(
    renderAccount(legacyPositionEvidence, {
      assessment: currentPosition,
    }).includes('data-position-freshness="rebuild_required"'),
  );
  const currentPositionReport = {
    ...report,
    history_assessment: currentHistory,
    position_assessment: currentPosition,
    coverage: { position_evidence: knownAccountEvidence },
  };
  const currentPositionBannerHtml = renderPositionBanner(currentPositionReport);
  assert.ok(
    currentPositionBannerHtml.includes('data-position-assessment="current"'),
  );
  assert.ok(
    currentPositionBannerHtml.includes("matching current history assessment"),
  );
  assert.ok(knownAccountHtml.includes('data-position-freshness="current"'));
  assert.ok(knownAccountHtml.includes('class="badge pass"'));
  assert.ok(!knownAccountHtml.includes("Saved Pass"));
  assert.ok(accountHtml.includes('data-position-freshness="current"'));
  assert.ok(accountHtml.includes('class="badge unknown"'));
  assert.equal(
    renderPositionBanner({ ...currentPositionReport, source: "demo" }),
    "",
  );
  assert.equal(
    renderPositionBanner({ ...currentPositionReport, preview: true }),
    "",
  );
  const previewPositionReportHtml = renderToStaticMarkup(
    React.createElement(ReportView, {
      ...actions,
      report: { ...currentPositionReport, preview: true },
      showEvidence: () => {},
      selected: [],
      onSelect: () => {},
    }),
  );
  assert.ok(
    !previewPositionReportHtml.includes("Source-backed account episodes"),
  );
  assert.ok(!previewPositionReportHtml.includes("data-position-assessment"));
  const previousPositionEvidence = structuredClone(knownAccountEvidence);
  previousPositionEvidence.version = "account-position-evidence-v4";
  const previousPositionAssessment = {
    ...currentPosition,
    saved_methodology: previousPositionEvidence.version,
    current_methodology: previousPositionEvidence.version,
  };
  const previousMethodsReport = {
    ...currentPositionReport,
    history_assessment: {
      ...currentHistory,
      saved_methodology: "history-evidence-v5",
      current_methodology: "history-evidence-v5",
    },
    position_assessment: previousPositionAssessment,
    coverage: { position_evidence: previousPositionEvidence },
  };
  const previousMethodsSnapshot = structuredClone(previousMethodsReport);
  const renderFreshnessReport = (nextReport) =>
    renderToStaticMarkup(
      React.createElement(ReportView, {
        ...actions,
        report: nextReport,
        showEvidence: () => {},
        selected: [],
        onSelect: () => {},
      }),
    );
  const previousMethodsHtml = renderFreshnessReport(previousMethodsReport);
  assert.ok(previousMethodsHtml.includes('data-history-assessment="rebuild_required"'));
  assert.ok(previousMethodsHtml.includes('data-position-assessment="rebuild_required"'));
  assert.ok(previousMethodsHtml.includes('data-position-freshness="history_not_current"'));
  assert.ok(previousMethodsHtml.includes("3.25 hours · rebuild needed"));
  assert.ok(previousMethodsHtml.includes("Saved Pass"));
  assert.ok(!previousMethodsHtml.includes("Known account-episode hold median:"));
  assert.ok(!previousMethodsHtml.includes('class="badge pass"'));
  assert.deepEqual(previousMethodsReport, previousMethodsSnapshot);
  const currentHistoryPreviousPositionHtml = renderFreshnessReport({
    ...previousMethodsReport,
    history_assessment: currentHistory,
  });
  assert.ok(currentHistoryPreviousPositionHtml.includes('data-history-assessment="current"'));
  assert.ok(currentHistoryPreviousPositionHtml.includes('data-position-assessment="rebuild_required"'));
  assert.ok(currentHistoryPreviousPositionHtml.includes('data-position-freshness="rebuild_required"'));
  assert.ok(!currentHistoryPreviousPositionHtml.includes("Known account-episode hold median:"));
  assert.ok(currentHistoryPreviousPositionHtml.includes(state.position_evidence_methodology));
  assert.ok(knownAccountHtml.includes("Inspect quantity source paths"));
  assert.ok(knownAccountHtml.includes("meta.preTokenBalances[accountIndex=1].uiTokenAmount.amount"));
  assert.ok(knownAccountHtml.includes('data-position-source-consistency="PASS"'));
  const disputedKnownAccount = structuredClone(knownAccountEvidence);
  disputedKnownAccount.positions[0].stages.source_consistency = unknownStage;
  const disputedKnownSnapshot = structuredClone(disputedKnownAccount);
  const disputedKnownHtml = renderAccount(disputedKnownAccount);
  assert.ok(disputedKnownHtml.includes('data-position-source-consistency="UNKNOWN"'));
  assert.ok(!disputedKnownHtml.includes("3.25 hours"));
  assert.ok(!disputedKnownHtml.includes("3.25 h"));
  assert.ok(disputedKnownHtml.includes("source-consistency gate is unknown or not recorded"));
  assert.deepEqual(disputedKnownAccount, disputedKnownSnapshot);
  delete disputedKnownAccount.positions[0].stages.source_consistency;
  assert.ok(!renderAccount(disputedKnownAccount).includes("3.25 hours"));
  const nativeFact = { hash: "d".repeat(64), path: "meta.fee", value: 5000, status: "known" };
  const consistentFactCheck = { state: "PASS", status: "consistent", field: "fee", signature: "synthetic-signature", account: address, reason: "All linked native fee facts agree.", evidence: [nativeFact.hash], facts: [nativeFact] };
  const boundaryCheck = { ...consistentFactCheck, state: "UNKNOWN", status: "conflict", field: "pre_quantity", reason: "Linked sources disagree on pre_quantity.", evidence: ["c".repeat(64), "e".repeat(64)], facts: [{ hash: "c".repeat(64), path: "meta.preTokenBalances[accountIndex=1].uiTokenAmount.amount", value: "0", status: "known" }, { hash: "e".repeat(64), path: "meta.preTokenBalances[accountIndex=1].uiTokenAmount.amount", value: "200", status: "known" }] };
  const feeGroup = { state: "PASS", reason: "Native fee dependencies agree", checks: { fee: consistentFactCheck } };
  const sourceEvidence = { version: state.source_consistency_methodology, state: "UNKNOWN", source_set: completeSourceSet, transactions: { "synthetic-signature": { state: "UNKNOWN", native_hashes: ["c".repeat(64), "e".repeat(64)], evidence: boundaryCheck.evidence, accounts: { [address]: { state: "UNKNOWN", reason: boundaryCheck.reason, checks: { pre_quantity: boundaryCheck } } }, native: { wallet_network_fees_sol: feeGroup, native_wallet_delta_sol: feeGroup, checks: { fee: consistentFactCheck } } } } };
  const sourceSnapshot = structuredClone(sourceEvidence);
  const renderConsistency = (evidence = sourceEvidence, overrides = {}) => renderToStaticMarkup(React.createElement(SourceConsistencySection, { evidence, currentMethodology: state.source_consistency_methodology, historyCurrent: true, showEvidence: () => {}, ...overrides }));
  const sourceHtml = renderConsistency();
  assert.ok(sourceHtml.includes('data-source-consistency="source-consistency-v4"'));
  assert.ok(sourceHtml.includes('data-source-consistency-freshness="current"'));
  assert.ok(sourceHtml.includes("Linked archive consistency"));
  assert.ok(sourceHtml.includes("token conflicts do not erase agreeing fees"));
  assert.ok(sourceHtml.includes("Conflict"));
  assert.ok(sourceHtml.includes("Consistent"));
  assert.ok(sourceHtml.includes("Native fee dependencies"));
  assert.ok(sourceHtml.includes("meta.preTokenBalances[accountIndex=1].uiTokenAmount.amount"));
  assert.ok(sourceHtml.includes("200"));
  assert.ok(sourceHtml.includes("Inspect archive facts"));
  assert.deepEqual(sourceEvidence, sourceSnapshot);
  const historicalSourceHtml = renderConsistency(sourceEvidence, { historyCurrent: false });
  assert.ok(historicalSourceHtml.includes('data-source-consistency-freshness="rebuild_required"'));
  assert.ok(historicalSourceHtml.includes("Saved Conflict"));
  assert.ok(!historicalSourceHtml.includes('class="badge pass"'));
  assert.ok(renderConsistency(sourceEvidence, { currentMethodology: "" }).includes('data-source-consistency-freshness="method_unavailable"'));
  assert.ok(renderConsistency({ ...sourceEvidence, version: "source-consistency-v1" }).includes('data-source-consistency-freshness="rebuild_required"'));
  assert.ok(renderConsistency(undefined, { evidence: undefined }).includes("No shared source-consistency assessment is saved"));
  assert.ok(renderConsistency({ ...sourceEvidence, transactions: {} }).includes("No linked native receipts are available"));
  const missingCheck = { ...boundaryCheck, status: "missing", reason: "A linked archive is unavailable", facts: [{ ...nativeFact, value: null, status: "missing" }] };
  const missingSource = structuredClone(sourceEvidence);
  missingSource.transactions["synthetic-signature"].accounts[address].checks.pre_quantity = missingCheck;
  assert.ok(renderConsistency(missingSource).includes("Missing"));
  assert.ok(renderConsistency(missingSource).includes("A linked archive is unavailable"));
  const boundedSource = structuredClone(sourceEvidence);
  boundedSource.transactions = Object.fromEntries(Array.from({ length: 11 }, (_, index) => [`record-${index}`, sourceEvidence.transactions["synthetic-signature"]]));
  assert.ok(renderConsistency(boundedSource).includes("Next receipts"));
  assert.ok(!renderConsistency(boundedSource).includes('title="record-10"'));
  assert.equal(sourceSetComplete(completeSourceSet), true);
  assert.ok(sourceHtml.includes('data-source-set-complete="true"'));
  assert.ok(sourceHtml.includes("40,001 references"));
  assert.ok(sourceHtml.includes("9 unique archives"));
  assert.ok(sourceHtml.includes("Unique-archive budget: 40,000"));
  const incompleteSet = { ...completeSourceSet, state: "UNKNOWN", complete: false, inspected_hash_count: 8, omitted_hash_count: 1, omitted_scope: { unresolved: ["synthetic-signature"] }, reason: "A required linked archive exceeded the supported inspection budget." };
  const incompleteSource = { ...sourceEvidence, source_set: incompleteSet };
  const incompleteSnapshot = structuredClone(incompleteSource);
  const incompleteHtml = renderConsistency(incompleteSource);
  assert.ok(incompleteHtml.includes('data-source-set-complete="false"'));
  assert.ok(incompleteHtml.includes('data-source-set-state="UNKNOWN"'));
  assert.ok(incompleteHtml.includes("Incomplete proof"));
  assert.ok(incompleteHtml.includes("1 omitted"));
  assert.ok(incompleteHtml.includes("Inspect omitted source scope"));
  assert.ok(!incompleteHtml.includes('class="badge pass"'));
  assert.deepEqual(incompleteSource, incompleteSnapshot);
  const incompletePosition = structuredClone(knownAccountEvidence);
  incompletePosition.positions[0].source_set = incompleteSet;
  const incompletePositionSnapshot = structuredClone(incompletePosition);
  const incompletePositionHtml = renderAccount(incompletePosition);
  assert.ok(!incompletePositionHtml.includes("3.25 hours"));
  assert.ok(!incompletePositionHtml.includes("3.25 h"));
  assert.ok(!incompletePositionHtml.includes('class="badge pass"'));
  assert.ok(incompletePositionHtml.includes('data-position-source-consistency="UNKNOWN"'));
  assert.ok(incompletePositionHtml.includes('data-position-source-set="incomplete"'));
  assert.deepEqual(incompletePosition, incompletePositionSnapshot);
  delete incompletePosition.positions[0].source_set;
  assert.ok(!renderAccount(incompletePosition).includes("3.25 hours"));
  assert.equal(sourceSetComplete({ ...completeSourceSet, complete: "true" }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, raw_reference_count: "40001" }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, inspected_hash_count: 8 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, unique_hash_count: 40001, inspected_hash_count: 40001 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, invalid_link_count: 1 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, unauthenticated_link_count: 1 }), false);
  assert.ok(renderConsistency({ ...sourceEvidence, source_set: { ...completeSourceSet, evidence: undefined } }).includes('data-source-set-complete="false"'));
  assert.equal(sourceSetComplete({ ...completeSourceSet, omitted_link_count: 1 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, invalid_authenticated_link_count: 1 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, authenticated_reference_count: undefined }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, omitted_link_count: undefined }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, budget: undefined }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, budget: { max_unique_hashes: 40001 } }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, budget: { max_unique_hashes: 0 } }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, budget: { max_unique_hashes: "40000" } }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, unique_link_count: 8 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, raw_reference_count: 8 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, authenticated_reference_count: 8 }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, invalid_link_count: undefined }), false);
  assert.equal(sourceSetComplete({ ...completeSourceSet, unauthenticated_link_count: undefined }), false);
  const unavailableArchives = { state: "UNKNOWN", counts: { links: 9, usable: 8, unresolved: 1 }, receipts: [{ kind: "signature-page", hash: "f".repeat(64), state: "UNKNOWN", read_state: "unavailable", validation_state: "unavailable", scope: { account: null, signatures: null, slot: null }, reason: "The linked page cannot be read; its relevance remains unresolved.", recovery: { action: "Restore the checksum-matching archived source, then rebuild.", provider_requests: 0 } }] };
  const archiveSnapshot = structuredClone(unavailableArchives);
  const unresolvedHtml = renderConsistency({ ...sourceEvidence, archive_contents: unavailableArchives });
  assert.ok(unresolvedHtml.includes('data-source-set-state="PASS"'));
  assert.ok(unresolvedHtml.includes('data-archive-contents-state="UNKNOWN"'));
  assert.ok(unresolvedHtml.includes("8 usable roles"));
  assert.ok(unresolvedHtml.includes("1 unresolved roles"));
  assert.ok(unresolvedHtml.includes("attempted reads"));
  assert.ok(unresolvedHtml.includes("Inspect unresolved sources and recovery"));
  assert.ok(unresolvedHtml.includes("Restore the checksum-matching archived source, then rebuild."));
  assert.ok(unresolvedHtml.includes("independent fee observations"));
  assert.deepEqual(unavailableArchives, archiveSnapshot);
  assert.ok(renderConsistency({ ...sourceEvidence, archive_contents: unavailableArchives }, { historyCurrent: false }).includes('data-archive-contents-state="saved"'));
  const boundedArchives = { ...unavailableArchives, counts: { links: 25, usable: 0, unresolved: 25 }, receipts: Array.from({ length: 25 }, (_, index) => ({ ...unavailableArchives.receipts[0], reason: `Unresolved source ${index}` })) };
  assert.ok(renderConsistency({ ...sourceEvidence, archive_contents: boundedArchives }).includes("Every source receipt remains in the JSON export"));
  assert.ok(!renderConsistency({ ...sourceEvidence, archive_contents: boundedArchives }).includes("Unresolved source 24"));
  const unassignableArchive = { ...unavailableArchives, receipts: [{ ...unavailableArchives.receipts[0], hash: null, validation_state: "unsupported", reason: "The source identifier cannot be assigned to an archive." }] };
  assert.ok(renderConsistency({ ...incompleteSource, archive_contents: unassignableArchive }).includes("The source identifier cannot be assigned to an archive."));
  assert.ok(renderConsistency({ ...incompleteSource, archive_contents: unassignableArchive }).includes('data-source-set-complete="false"'));
  const boundedAccountScope = renderAccount({ ...knownAccountEvidence, account_scope: { candidate_account_count: 1001, inspected_account_count: 1000, omitted_account_count: 1, population: "Median over the evaluated known account-episode subset only" } });
  assert.ok(boundedAccountScope.includes("1,000 of 1,001 candidate accounts"));
  assert.ok(boundedAccountScope.includes("1 omitted"));
  assert.ok(boundedAccountScope.includes("evaluated known account-episode subset only"));
  const viewMetadata = {
    version: "report-view-v1", view: "display", source_report_id: report.id,
    omitted_paths: ["coverage.wallet_evidence.transactions", "archive_accounting.source_consistency"],
    full_report_url: `/api/reports/${report.id}`, full_export_url: `/api/export/reports/${report.id}.json`,
    scope: "Transient presentation projection; saved report and evidence unchanged",
  };
  const displayReport = { ...report, report_view: viewMetadata, coverage: { wallet_evidence: { state: "UNKNOWN", gaps: ["Missing historical population"] } }, metrics: { profit_sol: { status: "unknown", value: null, reason: "Missing acquisition basis" }, wallet_network_fees_sol: { status: "known", value: "0.008904733" } } };
  const displaySnapshot = structuredClone(displayReport);
  const enrichedDisplay = { ...displayReport, market_observations: [{ mint: address, scope: "Current indicative only" }] };
  assert.equal(replaceActiveReport(displayReport, enrichedDisplay), enrichedDisplay);
  assert.equal(replaceActiveReport({ ...displayReport, id: "different-selection" }, enrichedDisplay).id, "different-selection");
  assert.equal(replaceActiveReport(null, enrichedDisplay), null);
  assert.equal(replaceActiveReport(displayReport, { ...enrichedDisplay, report_view: { ...viewMetadata, view: "summary" } }), displayReport);
  const projectedHtml = renderFreshnessReport(displayReport);
  assert.ok(projectedHtml.includes("Inspect coverage summary"));
  assert.ok(projectedHtml.includes("Saved decisions and metrics are unchanged"));
  assert.ok(projectedHtml.includes("Missing acquisition basis"));
  assert.ok(projectedHtml.includes(`/api/export/reports/${report.id}.csv`));
  assert.deepEqual(displayReport, displaySnapshot);
  const closedCoverage = Object.defineProperty({}, "large_nested_payload", { enumerable: true, get() { throw new Error("Collapsed coverage must not serialize its payload"); } });
  const closedHtml = renderToStaticMarkup(React.createElement(CoverageDetails, { value: closedCoverage }));
  assert.ok(closedHtml.includes("Inspect saved coverage"));
  assert.ok(!closedHtml.includes("<pre"));
  const projectedSource = { ...sourceEvidence, transactions: {} };
  const projectedSourceHtml = renderConsistency(projectedSource, { projection: { ...viewMetadata, omitted_paths: ["coverage.history_evidence.source_consistency.transactions"] } });
  assert.ok(projectedSourceHtml.includes('data-source-receipts-view="export"'));
  assert.ok(projectedSourceHtml.includes('data-source-set-state="PASS"'));
  assert.ok(!projectedSourceHtml.includes("No linked native receipts are available"));
  const originalFetch = globalThis.fetch;
  const summaryReport = { ...report, report_view: { ...viewMetadata, view: "summary" } };
  const summarySnapshot = structuredClone(summaryReport);
  const requested = [];
  try {
    globalThis.fetch = async (url, options) => {
      requested.push({ url, options });
      return { ok: true, status: 200, json: async () => url.includes("/state?") ? { ...state, reports: [summaryReport] } : displayReport };
    };
    const summaryState = await workspaceSummary();
    assert.equal(requested[0].url, "/api/state?report_view=summary");
    assert.equal(requested[0].options.credentials, "same-origin");
    assert.equal(summaryState.reports[0].report_view.view, "summary");
    const pendingDisplay = loadReportDisplay(summaryReport);
    const samePendingDisplay = loadReportDisplay(summaryReport);
    assert.equal(pendingDisplay, samePendingDisplay);
    assert.equal(await pendingDisplay, displayReport);
    assert.equal(requested.length, 2);
    assert.equal(requested[1].url, `/api/reports/${report.id}?view=display`);
    assert.equal(requested[1].options.method, "GET");
    assert.equal(await loadReportDisplay(displayReport), displayReport);
    assert.equal(requested.length, 2);
    await reportDisplay("report /+");
    assert.equal(requested[2].url, "/api/reports/report%20%2F%2B?view=display");
    await loadReportDisplay(summaryReport);
    assert.equal(requested.length, 4, "Later explicit openings refresh display rather than retaining a stale projection");
    globalThis.fetch = async (url) => {
      requested.push({ url });
      return { ok: false, status: 404, json: async () => ({ detail: "Frozen report is unavailable" }) };
    };
    await assert.rejects(loadReportDisplay(summaryReport), /Frozen report is unavailable/);
    assert.equal(requested.length, 5);
    assert.ok(requested.every(({ url }) => url.includes("report_view=summary") || url.endsWith("?view=display")));
    assert.deepEqual(summaryReport, summarySnapshot);
    assert.deepEqual(displayReport, displaySnapshot);
  } finally {
    globalThis.fetch = originalFetch;
  }
  // Synthetic UI contract controls only; these do not authenticate a wallet.
  const cohortEnd = "2026-01-31T00:00:00Z";
  const cohortStart = "2026-01-25T00:00:00Z";
  const observedClosed = {
    candidate_count: 2, population_state: "PASS", monetary_state: "PASS", timing_state: "PASS",
    conditional_profit_sol: "-0.2", conditional_win_rate_pct: "0", conditional_median_roi_pct: "-10",
    conditional_median_hold_hours: "2.5", conditional_first_sale_hours: "0.25",
    conditional_exit_50_hours: "1", conditional_exit_90_hours: "2", evidence: ["a".repeat(64)],
  };
  const observedDisposed = {
    candidate_sale_count: 3, quantity_state: "PASS", cost_basis_state: "PASS", monetary_state: "PASS",
    conditional_profit_sol: "0", conditional_matched_basis_sol: "1.25", evidence: ["b".repeat(64)],
  };
  const intervalFact = (start) => ({ start, end: cohortEnd, closed_cohort: structuredClone(observedClosed), disposed_units: structuredClone(observedDisposed) });
  const cohortObservation = {
    version: "selected-cohort-observations-v2",
    intervals: {
      report_period: intervalFact(cohortStart),
      four_weeks: intervalFact(new Date(Date.parse(cohortEnd) - 28 * 86400000).toISOString()),
      verification_90d: intervalFact(new Date(Date.parse(cohortEnd) - 90 * 86400000).toISOString()),
    },
    open_stock: { at: cohortEnd, candidate_count: 1, quantity_state: "PASS", cost_basis_state: "PASS",
      valuation_state: "UNKNOWN", conditional_remaining_basis_sol: "0.5000025", closing_value_sol: null,
      evidence: ["c".repeat(64)], lots: [{ id: "selected-lot", mint: address, remaining_raw: "9007199254740993000000",
        quantity_state: "PASS", cost_basis_state: "PASS", conditional_remaining_basis_sol: "0.5000025", evidence: ["c".repeat(64)] }] },
  };
  const cohortReport = { ...report, source: "live", methodology: "fifo-v4", window: { start: cohortStart, end: cohortEnd },
    research: { ...(report.research ?? {}), version: "supported-subset-research-v5-origin-scopes" },
    research_assessment: { state: "current", saved_methodology: "supported-subset-research-v5-origin-scopes", current_methodology: "supported-subset-research-v5-origin-scopes" },
    wallet_assessment: { state: "current", saved_methodology: "wallet-raw-evidence-v8", current_methodology: "wallet-raw-evidence-v8" },
    coverage: { wallet_evidence: { version: "wallet-raw-evidence-v8", query_accounting: { selected_cohort_observations: cohortObservation } } } };
  const renderCohorts = (next = cohortReport, options = {}) => renderToStaticMarkup(React.createElement(SelectedCohortSection, {
    report: next, currentWalletMethod: "wallet-raw-evidence-v8", currentAccountingMethod: "fifo-v4", historyCurrent: true,
    showEvidence: () => undefined, ...options,
  }));
  const cohortSnapshot = structuredClone(cohortReport);
  const cohortHtml = renderCohorts();
  assert.ok(cohortHtml.includes('data-selected-cohort-freshness="current"'));
  assert.ok(cohortHtml.includes("selected records only"));
  assert.ok(cohortHtml.includes("wallet-wide profit or a copy-trading recommendation"));
  for (const name of ["Reporting period", "Independent 28 days", "Independent 90 days"])
    assert.ok(cohortHtml.includes(`data-selected-cohort-window="${name}"`));
  assert.ok(cohortHtml.includes("-0.2<small> SOL"), "A losing observed cohort remains included");
  assert.ok(cohortHtml.includes("0<small> SOL"), "Known zero disposal profit remains known");
  assert.ok(cohortHtml.includes("0<small> %"), "Known zero win rate is not empty");
  assert.ok(cohortHtml.includes("0.5000025<small> SOL"));
  assert.ok(cohortHtml.includes("9007199254740993000000"), "Raw quantities retain exact integer text");
  assert.ok(cohortHtml.includes("Closing market value</span><strong>Unknown"));
  assert.ok(cohortHtml.includes("Source aaaaa"));
  assert.deepEqual(cohortReport, cohortSnapshot, "Rendering never changes saved evidence");
  for (const next of [
    { ...cohortReport, methodology: "fifo-v3" },
    { ...cohortReport, wallet_assessment: { ...cohortReport.wallet_assessment, saved_methodology: "wallet-raw-evidence-v6" } },
    { ...cohortReport, wallet_assessment: undefined },
    { ...cohortReport, research_assessment: { ...cohortReport.research_assessment, state: "rebuild_required" } },
    { ...cohortReport, research_assessment: undefined },
    { ...cohortReport, research: { ...cohortReport.research, version: "supported-subset-research-v3" } },
  ]) {
    const savedHtml = renderCohorts(next);
    assert.ok(savedHtml.includes("Saved observations require a rebuild"));
    assert.ok(!savedHtml.includes("-0.2<small> SOL"));
    assert.ok(!savedHtml.includes("0.5000025<small> SOL"));
    assert.ok(!savedHtml.includes('class="badge pass"'));
  }
  assert.equal(selectedCohortFreshness(cohortReport, undefined, "fifo-v4", true), "method_unavailable");
  assert.ok(!renderCohorts(cohortReport, { historyCurrent: false }).includes("-0.2<small> SOL"));
  const changedCohort = (mutate) => {
    const next = structuredClone(cohortReport);
    mutate(next.coverage.wallet_evidence.query_accounting.selected_cohort_observations);
    return renderCohorts(next);
  };
  const missingBasisHtml = changedCohort((value) => {
    value.intervals.report_period.closed_cohort.monetary_state = "UNKNOWN";
    value.intervals.report_period.disposed_units.monetary_state = "UNKNOWN";
    value.intervals.report_period.disposed_units.cost_basis_state = "UNKNOWN";
    value.open_stock.cost_basis_state = "UNKNOWN";
    value.open_stock.lots[0].cost_basis_state = "UNKNOWN";
  });
  assert.equal((missingBasisHtml.match(/-0\.2<small> SOL/g) ?? []).length, 2, "28/90-day values survive a report-period basis gap");
  assert.ok(missingBasisHtml.includes("2.5<small> hours"), "Missing money does not erase supported timing");
  assert.ok(missingBasisHtml.includes("9007199254740993000000"), "Missing money does not erase supported quantities");
  assert.ok(!missingBasisHtml.includes("0.5000025<small> SOL"));
  assert.equal((missingBasisHtml.match(/Matched acquisition basis<\/span><strong title="1\.25">1\.25<small> SOL/g) ?? []).length, 2,
    "Missing report-period basis cannot borrow known 28/90-day acquisition basis");
  const missingSaleFeeHtml = changedCohort((value) => {
    value.intervals.report_period.disposed_units.monetary_state = "UNKNOWN";
    value.intervals.report_period.disposed_units.conditional_profit_sol = null;
  });
  assert.equal((missingSaleFeeHtml.match(/Matched acquisition basis<\/span><strong title="1\.25">1\.25<small> SOL/g) ?? []).length, 3,
    "Supported acquisition basis remains visible when a missing sale fee blocks profit");
  assert.equal((missingSaleFeeHtml.match(/Conditional disposal P&amp;L<\/span><strong title="0">0<small> SOL/g) ?? []).length, 2,
    "Missing sale fees still revoke only the dependent disposal profit");
  const malformedHtml = changedCohort((value) => {
    value.intervals.report_period.closed_cohort.candidate_count = "2";
    value.intervals.four_weeks.closed_cohort.monetary_state = true;
    value.intervals.verification_90d.closed_cohort.conditional_profit_sol = "NaN";
    value.open_stock.candidate_count = null;
    value.open_stock.lots = [null, 42, { quantity_state: "PASS", cost_basis_state: "PASS", remaining_raw: "bad", conditional_remaining_basis_sol: [] }];
  });
  assert.ok(malformedHtml.includes("Candidate count unknown"));
  assert.ok(malformedHtml.includes("Open-holding count unknown"));
  assert.ok(!malformedHtml.includes("-0.2<small> SOL"));
  assert.ok(!malformedHtml.includes("NaN"));
  assert.ok(!malformedHtml.includes("0.5000025<small> SOL"));
  const wrongBoundaryHtml = changedCohort((value) => {
    value.intervals.report_period.start = value.intervals.four_weeks.start;
    value.open_stock.at = cohortStart;
  });
  assert.equal((wrongBoundaryHtml.match(/-0\.2<small> SOL/g) ?? []).length, 2);
  assert.ok(wrongBoundaryHtml.includes("saved boundaries do not match"));
  assert.ok(!wrongBoundaryHtml.includes("0.5000025<small> SOL"));
  assert.ok(!changedCohort((value) => { value.version = "unknown-method"; }).includes('class="badge pass"'));
  const invalidSourcesHtml = changedCohort((value) => {
    for (const interval of Object.values(value.intervals)) {
      interval.closed_cohort.evidence = [null, "javascript:bad", "../private", "a".repeat(64), "a".repeat(64)];
    }
  });
  assert.ok(!invalidSourcesHtml.includes("javascript:bad"));
  assert.ok(!invalidSourcesHtml.includes("../private"));
  assert.equal((invalidSourcesHtml.match(/Source aaaaa/g) ?? []).length, 3);
  const emptyHtml = changedCohort((value) => {
    for (const interval of Object.values(value.intervals)) {
      interval.closed_cohort.candidate_count = 0;
      interval.disposed_units.candidate_sale_count = 0;
    }
    value.open_stock.candidate_count = 0;
  });
  assert.ok(emptyHtml.includes("empty cohort"));
  assert.ok(!emptyHtml.includes("-0.2<small> SOL"));
  assert.ok(!emptyHtml.includes("0<small> SOL"));
  assert.ok(!emptyHtml.includes("0<small> %"));
  const selectedState = { ...state, methodology: "fifo-v4", wallet_evidence_methodology: "wallet-raw-evidence-v8" };
  const visibleCohortReport = { ...cohortReport, history_assessment: { state: "current", saved_methodology: state.history_evidence_methodology, current_methodology: state.history_evidence_methodology } };
  const integratedCohortHtml = renderToStaticMarkup(React.createElement(ReportView, { ...actions, state: selectedState, report: visibleCohortReport, showEvidence: () => undefined, selected: [], onSelect: () => undefined }));
  assert.ok(integratedCohortHtml.includes('data-selected-cohort-freshness="current"'));
  assert.ok(!renderCohorts({ ...cohortReport, coverage: {} }).includes("Selected holding observations"));
  assert.ok(!renderCohorts({ ...cohortReport, preview: true }).includes("Selected holding observations"));
  assert.ok(!renderCohorts({ ...cohortReport, source: "demo" }).includes("Selected holding observations"));
  // Native cash UI controls are synthetic rendering inputs, not wallet proof.
  assert.equal(nativeCashAmount("1"), "0.000000001");
  assert.equal(nativeCashAmount("0"), "0");
  assert.equal(nativeCashAmount("9007199254740993000001"), "9007199254740.993000001");
  assert.equal(nativeCashAmount("18446744073709551616000"), "18446744073709.551616");
  for (const value of [null, 1, "-1", "1.5", "1e9", "9".repeat(513)])
    assert.equal(nativeCashAmount(value), undefined);
  const cashInterval = (start) => ({ start, end: cohortEnd,
    gross_in_lamports: "1000000001", gross_out_lamports: "1000000001",
    economic_roles_state: "UNKNOWN", wallet_population_state: "UNKNOWN",
    check: { state: "PASS", evidence: ["a".repeat(64)] } });
  const cashReport = structuredClone(cohortReport);
  cashReport.coverage.wallet_evidence.native_cash_observations = {
    version: "native-cash-observations-v1", intervals: {
      report_period: cashInterval(cohortStart),
      four_weeks: cashInterval(new Date(Date.parse(cohortEnd) - 28 * 86400000).toISOString()),
      verification_90d: cashInterval(new Date(Date.parse(cohortEnd) - 90 * 86400000).toISOString()),
    },
  };
  const renderCash = (next = cashReport, options = {}) => renderToStaticMarkup(React.createElement(NativeCashObservations, {
    report: next, currentWalletMethod: "wallet-raw-evidence-v8", historyCurrent: true,
    showEvidence: () => undefined, ...options,
  }));
  const cashSnapshot = structuredClone(cashReport);
  const cashHtml = renderCash();
  assert.ok(cashHtml.includes('data-native-cash-observations="current"'));
  assert.equal((cashHtml.match(/1\.000000001<small> SOL/g) ?? []).length, 6, "Cancelling gross amounts remain separately visible");
  assert.ok(cashHtml.includes("economic role of these movements remains unknown"));
  assert.ok(cashHtml.includes("capital deposits, withdrawals, profit or complete wallet history"));
  assert.ok(cashHtml.includes("Source aaaaa"));
  assert.deepEqual(cashReport, cashSnapshot, "Rendering preserves saved cash evidence");
  for (const next of [
    { ...cashReport, wallet_assessment: undefined },
    { ...cashReport, wallet_assessment: { ...cashReport.wallet_assessment, state: "rebuild_required" } },
    { ...cashReport, wallet_assessment: { ...cashReport.wallet_assessment, current_methodology: "different-method" } },
  ]) assert.ok(!renderCash(next).includes("1.000000001<small> SOL"));
  assert.ok(!renderCash(cashReport, { historyCurrent: false }).includes("1.000000001<small> SOL"));
  assert.ok(!renderCash(cashReport, { currentWalletMethod: undefined }).includes("1.000000001<small> SOL"));
  const changedCash = (mutate) => {
    const next = structuredClone(cashReport);
    mutate(next.coverage.wallet_evidence.native_cash_observations);
    return renderCash(next);
  };
  const inventoryReport = structuredClone(cashReport);
  inventoryReport.coverage.wallet_evidence.inventory_observations = {
    version: "current-inventory-evidence-v1", source_dependencies: ["a".repeat(64)], components: {
      native_lamports: { state: "PASS", evidence: ["a".repeat(64)],
        observations: [{ slot: 42, lamports: "1000000001", evidence: ["a".repeat(64)] }] },
    },
  };
  const renderInventory = (next = inventoryReport, options = {}) => renderToStaticMarkup(React.createElement(InventoryObservations, {
    report: next, currentWalletMethod: "wallet-raw-evidence-v8", historyCurrent: true, showEvidence: () => undefined, ...options,
  }));
  assert.ok(renderInventory().includes("1.000000001 SOL"), "Source-bound native inventory remains visible");
  const inventoryWithoutMethod = structuredClone(inventoryReport);
  delete inventoryWithoutMethod.coverage.wallet_evidence.version;
  for (const [next, options] of [
    [inventoryWithoutMethod, { currentWalletMethod: undefined }],
    [{ ...inventoryReport, wallet_assessment: { ...inventoryReport.wallet_assessment, saved_methodology: undefined } }, {}],
    [{ ...inventoryReport, wallet_assessment: { ...inventoryReport.wallet_assessment, state: "rebuild_required" } }, {}],
  ]) {
    const original = structuredClone(next);
    const savedInventoryHtml = renderInventory(next, options);
    assert.ok(!savedInventoryHtml.includes("1.000000001 SOL"), "Inventory values need an explicit matching current wallet assessment");
    assert.ok(savedInventoryHtml.includes("Rebuild from saved records"));
    assert.ok(savedInventoryHtml.includes("Source aaaaa"));
    assert.deepEqual(next, original, "Freshness rendering preserves saved inventory and source references");
  }
  for (const evidence of [undefined, [], ["invalid-hash"], ["a".repeat(64), null]]) {
    const cashWithoutSources = changedCash((value) => { value.intervals.report_period.check.evidence = evidence; });
    const inventoryWithoutSources = structuredClone(inventoryReport);
    inventoryWithoutSources.coverage.wallet_evidence.inventory_observations.components.native_lamports.evidence = evidence;
    assert.deepEqual([
      (cashWithoutSources.match(/1\.000000001<small> SOL/g) ?? []).length,
      (renderInventory(inventoryWithoutSources).match(/1\.000000001 SOL/g) ?? []).length,
    ], [4, 0], "Missing, empty, invalid or partly malformed references cannot support native observations");
  }
  const pointWithoutSources = structuredClone(inventoryReport);
  delete pointWithoutSources.coverage.wallet_evidence.inventory_observations.components.native_lamports.observations[0].evidence;
  assert.ok(!renderInventory(pointWithoutSources).includes("1.000000001 SOL"), "Each inventory point needs its own source references");
  assert.ok(renderInventory().includes("1.000000001 SOL"), "Restored inventory references recover the observation");
  assert.equal((changedCash((value) => { value.intervals.report_period.check.state = "UNKNOWN"; })
    .match(/1\.000000001<small> SOL/g) ?? []).length, 4, "A reporting-period dependency gap preserves 28/90-day observations");
  assert.equal((changedCash((value) => { value.intervals.four_weeks.start = cohortStart; })
    .match(/1\.000000001<small> SOL/g) ?? []).length, 4, "Each interval must match its own boundaries");
  const malformedCashHtml = changedCash((value) => {
    value.intervals.report_period.gross_in_lamports = "NaN";
    value.intervals.report_period.gross_out_lamports = 1000000001;
    value.intervals.report_period.check.evidence = [null, "../private", "a".repeat(64), "a".repeat(64)];
    value.intervals.four_weeks = null;
  });
  assert.ok(!malformedCashHtml.includes("NaN"));
  assert.ok(!malformedCashHtml.includes("../private"));
  assert.equal((malformedCashHtml.match(/Source aaaaa/g) ?? []).length, 2);
  assert.ok(!changedCash((value) => { value.version = "older-method"; }).includes("1.000000001<small> SOL"));
  assert.equal(renderCash({ ...cashReport, preview: true }), "");
  assert.equal(renderCash({ ...cashReport, source: "demo" }), "");
  const integratedCashHtml = renderToStaticMarkup(React.createElement(ReportView, { ...actions, state: selectedState,
    report: { ...cashReport, history_assessment: visibleCohortReport.history_assessment },
    showEvidence: () => undefined, selected: [], onSelect: () => undefined }));
  assert.ok(integratedCashHtml.includes('data-native-cash-observations="current"'));
  const sourceDecision = { version: "historical-source-capability-v1", state: "UNSUPPORTED_CURRENT_SOURCE",
    source_contract_id: "helius-indexed-address-query-2026-10-03",
    scope: "Exhaustive event-time historical wallet ownership and token-account lifecycle population",
    reason: "Pinned wording does not explicitly guarantee closed, reassigned or both-program event-time historical membership." };
  const sourceNoticeHtml = renderToStaticMarkup(React.createElement(ReportView, { ...actions,
    state: { ...selectedState, historical_source_decision: sourceDecision },
    report: { ...cashReport, history_assessment: visibleCohortReport.history_assessment },
    showEvidence: () => undefined, selected: [], onSelect: () => undefined }));
  assert.ok(sourceNoticeHtml.includes('data-historical-source-decision="UNSUPPORTED_CURRENT_SOURCE"') &&
    sourceNoticeHtml.includes("Independently supported fees and selected trades can still be reported") &&
    sourceNoticeHtml.includes("A paid plan alone does not prove complete coverage"),
    "Current source limits stay visible in a real report without erasing independent observations");
  assert.equal(renderToStaticMarkup(React.createElement(HistoricalSourceNotice, { decision: undefined })), "",
    "Older state responses remain compatible when the source-decision field is absent");
  console.log(
    "Discovery, interval coverage, independent freshness, source consistency, scoped account-episode, selected holding/cohort and gross native cash isolation, rebuild, report projection routing, display reuse, and lazy coverage assertions passed (one frontend runner).",
  );
} finally {
  rmSync(output, { recursive: true, force: true });
}
