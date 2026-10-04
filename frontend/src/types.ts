export type Policy = "MATCH" | "MISS" | "UNRESOLVED";
export type Metric = {
  value: string | null;
  unit?: string;
  status: "known" | "unknown";
  population?: string | number;
  reason?: string;
  evidence?: string[];
};
export type Check = {
  key: string;
  label: string;
  state: "PASS" | "FAIL" | "UNKNOWN";
  actual: string | null;
  expected: unknown;
  reason?: string;
};
export type Qualification = {
  qualified: boolean;
  financial_policy: Policy | "NOT_AUDITED";
  preset_version: string | null;
  preset_snapshot?: Preset | null;
  methodology?: string | null;
  window: { start: string; end: string } | null;
  profit_sol: string | null;
  evidence_status: string;
  report_id?: string;
  failed_checks: Check[];
  unknown_checks: Check[];
  checks?: Check[];
  reason?: string;
  notes?: string[];
};
export type CopyReview = {
  scope: string;
  conditional?: boolean;
  checks: Record<
    string,
    {
      state: string;
      detail: string;
      actual?: unknown;
      evidence?: string[];
      conditional?: boolean;
      comparison?: string;
    }
  >;
  findings: {
    key?: string;
    severity: string;
    title: string;
    detail: string;
    evidence?: string[];
    conditional?: boolean;
  }[];
  unknown_checks: string[];
  notes: string[];
};
export type MetricCoverage = {
  start: string;
  end: string;
  status: string;
  source: string;
  evidence?: string[];
  reason?: string;
  available_start?: string | null;
  available_end?: string | null;
  interval?: string;
  metric_status?: string;
};
export type HistoryAssessment = {
  saved_methodology: string | null;
  current_methodology: string;
  state: "current" | "rebuild_required" | "missing";
  reason: string;
};
export type PositionAssessment = HistoryAssessment;
export type AccountPositionStage = {
  state: "PASS" | "UNKNOWN";
  reason: string;
  evidence: string[];
  dependencies: string[];
};
export type SourceConsistencyCheck = {
  state: "PASS" | "UNKNOWN";
  status: "consistent" | "conflict" | "missing";
  field: string;
  signature: string;
  account: string | null;
  reason: string;
  evidence: string[];
  facts: {
    hash: string;
    path: string;
    value: unknown;
    status: "known" | "missing" | "invalid" | "not_applicable";
  }[];
};
export type SourceConsistencyGroup = {
  state: "PASS" | "UNKNOWN";
  checks: Record<string, SourceConsistencyCheck>;
  reason: string;
};
export type SourceSet = {
  state: "PASS" | "UNKNOWN";
  complete: boolean;
  raw_reference_count: number;
  authenticated_reference_count: number;
  omitted_link_count: number;
  invalid_authenticated_link_count: number;
  unique_link_count: number;
  unique_hash_count: number;
  inspected_hash_count: number;
  omitted_hash_count: number;
  invalid_link_count?: number;
  unauthenticated_link_count?: number;
  budget?: { max_unique_hashes: number };
  omitted_scope?: unknown;
  evidence_scope?: string;
  reason: string;
  evidence: string[];
};
export type SourceConsistency = {
  version: string;
  state: "PASS" | "UNKNOWN";
  source_set?: SourceSet;
  archive_contents?: {
    state: "PASS" | "UNKNOWN";
    counts: { links: number; usable: number; unresolved: number };
    receipts: {
      kind: string;
      hash: string | null;
      state: "PASS" | "UNKNOWN";
      read_state: string;
      validation_state: string;
      reason: string;
      scope: { account: string | null; signatures: string[] | null; slot: number | null };
      recovery: { action: string; provider_requests: number } | null;
    }[];
  };
  transactions: Record<
    string,
    {
      state: "PASS" | "UNKNOWN";
      native_hashes: string[];
      evidence: string[];
      accounts: Record<
        string,
        SourceConsistencyGroup
      >;
      native: {
        wallet_network_fees_sol: SourceConsistencyGroup;
        native_wallet_delta_sol: SourceConsistencyGroup;
        checks: Record<string, SourceConsistencyCheck>;
      };
    }
  >;
};
export type AccountPositionEvidence = {
  version: string;
  scope: string;
  trust_boundary?: string;
  account_placement_sources?: Record<string, string[]>;
  account_scope?: {
    candidate_account_count: number;
    inspected_account_count: number;
    omitted_account_count: number;
    population: string;
  };
  counts: { known_closed: number; open: number; unresolved: number };
  known_account_hold_median_hours: Metric;
  positions: {
    id: string;
    account: string;
    mint: string;
    status: "known_closed" | "open" | "unresolved";
    start: string | null;
    end: string | null;
    opening_raw: string | null;
    closing_raw: string | null;
    acquired_raw: string;
    sold_raw: string;
    hold_hours: Metric;
    stages: Record<string, AccountPositionStage>;
    source_paths?: { signature: string; hash: string; paths: string[] }[];
    source_set?: SourceSet;
    placement_scope?: {
      max_uncertain_exclusions: number;
      inspected_uncertain_exclusions: number;
      omitted_uncertain_exclusions: number;
      complete: boolean;
    };
    dependency_exclusions?: {
      signature: string;
      state: "PASS";
      relation: "before" | "after";
      reason: string;
      evidence: string[];
      slot_bounds: {
        bounded: boolean;
        min: number | null;
        max: number | null;
      };
      index_bounds: Record<
        string,
        {
          bounded: boolean;
          min: number | null;
          max: number | null;
          possible_indices?: number[];
        }
      >;
    }[];
    sources: string[];
    signatures: string[];
  }[];
  recovery_actions: {
    kind: string;
    account: string;
    signature?: string;
    slot?: number;
    method?: string;
    reason: string;
    requires_network: boolean;
  }[];
  limitations: string[];
};
export type Report = {
  report_view?: {
    version: "report-view-v1";
    view: "summary" | "display";
    source_report_id: string;
    omitted_paths: string[];
    full_report_url: string;
    full_export_url: string;
    scope: string;
  };
  id: string;
  scan_id?: string;
  address: string;
  label?: string;
  source: "demo" | "live";
  created_at: string;
  window: { start: string; end: string };
  methodology: string;
  policy: Policy;
  evidence_status: string;
  preset?: Preset;
  archive_input_hash?: string;
  archive_assessment?: HistoryAssessment;
  archive_accounting?: {
    dataset: 'real' | 'synthetic';
    scope: string;
    population_state: 'PASS' | 'UNKNOWN';
    gaps: string[];
    metric_requirements: Record<string, {state: string; reason?: string; dependencies: string[]}>;
  };
  preview?: boolean;
  history_assessment?: HistoryAssessment;
  position_assessment?: PositionAssessment;
  research_assessment?: HistoryAssessment;
  wallet_assessment?: HistoryAssessment;
  qualification?: Qualification;
  copy_review?: CopyReview;
  metrics: Record<string, Metric>;
  metric_intervals?: Record<string, MetricCoverage>;
  metric_coverage?: Record<string, MetricCoverage>;
  checks: Check[];
  coverage: Record<string, unknown> & {
    position_evidence?: AccountPositionEvidence;
    history_evidence?: Record<string, unknown> & {
      source_consistency?: SourceConsistency;
    };
  };
  positions: Record<string, unknown>[];
  events: Record<string, unknown>[];
  findings: {
    severity: string;
    title: string;
    detail: string;
    evidence?: string[];
  }[];
  evidence: { hash: string; kind: string; signature?: string }[];
  counts: {
    closed: number;
    open: number;
    interrupted: number;
    unresolved: number;
  };
  counts_population?: string;
  notes: string[];
  market_observations?: Record<string, unknown>[];
  market_observation_scope?: string;
  market_observation_note?: string;
  research?: {
    scope: string;
    history_complete: boolean;
    observed_profit_sol?: string | null;
    known_matched_profit_sol?: string | null;
    conditional_observed_lot_profit_sol?: string | null;
    supported_swaps: number;
    observed_matched_sales: number;
    matched_sales: number;
    unresolved_basis_sales: number;
    closed_episodes: number;
    conditional_median_hold_hours?: string | null;
    conditional_first_sale_hours?: string | null;
    conditional_exit_50_hours?: string | null;
    conditional_exit_90_hours?: string | null;
    conditional_rapid_sale_pct?: string | null;
    limitations: string[];
    risk_findings?: (string | { title?: string; detail?: string })[];
    [key: string]: unknown;
  };
  token_risk?: {
    mint: string;
    status: string;
    scope: string;
    observed_at?: string;
    evidence: string[];
    gates: Record<
      string,
      {
        state: "PASS" | "FAIL" | "UNKNOWN";
        detail: string;
        actual?: unknown;
        evidence?: string[];
      }
    >;
    notes?: string[];
  }[];
};
export type Scan = {
  id: string;
  source: string;
  status: string;
  stage: string;
  created_at: string;
  window: { start: string; end: string };
  addresses: string[];
  progress: {
    wallets_completed: number;
    wallets_total: number;
    pages: number;
    transactions: number;
    credits: number;
    unresolved: number;
  };
  reason?: string;
  discovery_cohort_id?: string;
};
export type DiscoveryCandidate = {
  address: string;
  source?: string;
  status: "candidate" | "rejected" | "unresolved";
  reason: string;
  signatures: string[];
  pools: (string | Record<string, unknown>)[];
  validation?: {
    identity_verified?: boolean;
    economic_signers?: string[];
    account_type?: string;
    economic_signer?: boolean;
    program_owned?: boolean;
    [key: string]: unknown;
  };
  observed_profit_sol?: string | null;
  report_id?: string;
  qualification?: Qualification;
  copy_review?: CopyReview;
  research?: Report["research"];
  states?: CandidateStates;
  risk?: {
    findings?: (string | { title?: string; detail?: string })[];
    unresolved?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
};
export type CandidateStates = {
  observed: boolean;
  identity_checked: boolean;
  sample_audited: boolean;
  history_reconstructed: boolean;
};
export type SavedCandidate = {
  address: string;
  source: "saved-universe";
  status: string;
  stage: string;
  states: CandidateStates;
  first_seen: string | null;
  last_seen: string | null;
  origin_types: string[];
  cohort_ids: string[];
  pools: string[];
  signatures: string[];
  evidence: string[];
  report_ids: string[];
  report_id?: string;
  audit_eligible_cohort_ids: string[];
  reason: string;
};
export type CandidateUniverse = {
  version: string;
  candidates: SavedCandidate[];
  counts: Record<string, number>;
  limits: { candidate_cap: number };
  limitations: string[];
};
export type EvidenceAudit = {
  id: string;
  audit_id?: string;
  created_at: string;
  bundle_hash: string;
  source: string;
  address: string;
  scope: {
    kind: string;
    signatures: string[];
    accounts: string[];
    history_complete: boolean;
    description: string;
  };
  certificate: {
    version: string;
    status: string;
    scope_kind: string;
    content_hash: string;
    wallet_history_complete: boolean;
    financial_qualification: string;
    checks: Record<
      string,
      {
        state: string;
        detail: string;
        actual?: unknown;
        evidence: string[];
        paths?: string[];
      }
    >;
  };
  metrics: Record<
    string,
    {
      status: "known" | "unknown";
      value: string | Record<string, string> | null;
      unit?: string;
      reason?: string | null;
      population?: string;
      evidence?: string[];
      required_checks?: string[];
    }
  >;
  evidence: { hash: string; kind: string; signature?: string }[];
  notes: string[];
};
export type DiscoveryCohort = {
  id: string;
  created_at: string;
  status: string;
  stage: string;
  candidates: DiscoveryCandidate[];
  counts?: Record<string, number>;
  limits?: Record<string, number>;
  limitations?: string[];
  pools?: (string | Record<string, unknown>)[];
  universe?: Record<string, unknown>[];
  sample?: Record<string, unknown>;
  audit_scan_ids?: string[];
  audit_plan?: {
    selected_addresses: string[];
    deferred: { address: string; reason?: string }[];
    excluded: { address?: string; reason?: string }[];
  };
  reason?: string;
  [key: string]: unknown;
};
export type Preset = Record<string, string | number | boolean>;
export type HistoricalSourceDecision = {
  version: string;
  state: string;
  source_contract_id: string;
  scope: string;
  reason: string;
};
export type State = {
  methodology: string;
  evidence_audit_methodology: string;
  history_evidence_methodology?: string;
  position_evidence_methodology?: string;
  source_consistency_methodology?: string;
  wallet_evidence_methodology?: string;
  historical_source_decision?: HistoricalSourceDecision;
  settings: { limits: Record<string, number>; refresh_minutes: number };
  preset: Preset;
  scans: Scan[];
  discovery_cohorts?: DiscoveryCohort[];
  candidate_universe?: CandidateUniverse;
  evidence_audits?: EvidenceAudit[];
  reports: Report[];
  watchlist: { address: string; label: string; added_at?: string }[];
  usage: {
    used: number;
    reserved: number;
    cap: number;
    remaining: number;
    cycle_start?: string;
    cycle_end?: string;
    manifest_version?: string;
    mode?: string;
    billing_cycle_verified?: boolean;
    setup_pilot?: Record<string, unknown>;
  };
  provider: {
    configured: boolean;
    storage: string;
    free_plan_confirmed: boolean;
    capability_status: string;
    calibration_address?: string;
    last_test?: unknown;
    cycle_start?: string;
    cycle_end?: string;
  };
  storage: Record<string, unknown>;
};
