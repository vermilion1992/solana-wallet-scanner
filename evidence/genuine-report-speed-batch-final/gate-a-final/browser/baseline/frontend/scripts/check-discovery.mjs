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
    qualifiedCandidates,
    strictFilterSummary,
  } = require(join(output, "Discovery.js"));
  const {
    ReportView,
    HistoryAssessmentBanner,
    PositionAssessmentBanner,
    AccountPositionEvidenceSection,
    SourceConsistencySection,
    sourceSetComplete,
  } = require(join(output, "report.js"));
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
    position_evidence_methodology: "account-position-evidence-v9",
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
    listedHtml.includes("Imported public list · no chain observation supplied"),
  );
  assert.ok(listedHtml.includes("No wallet qualifies yet"));
  assert.ok(listedHtml.includes("Saved candidate universe"));
  assert.ok(
    listedHtml.includes("1 unique addresses across 2 saved lists and samples"),
  );
  assert.ok(listedHtml.includes("History reconstructed"));
  assert.ok(listedHtml.includes("Not established"));
  assert.ok(!listedHtml.includes("Signer verified"));
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
  console.log(
    "299 discovery, interval coverage, independent history/position freshness, source-set completeness, source consistency, unresolved source recovery, scoped account-episode, and rebuild assertions passed.",
  );
} finally {
  rmSync(output, { recursive: true, force: true });
}
