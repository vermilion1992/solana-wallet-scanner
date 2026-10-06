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
  source: "demo" | "live" | "mass-search";
  corpus_kind?: string;
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
  worksheet?: {
    total_profit_sol?: string | null;
    total_profit_usdc?: string | null;
    sale_fifo_basis_sol?: string[];
    sale_fifo_basis_usdc?: string[];
    sale_net_profit_sol?: string[];
    sale_net_profit_usdc?: string[];
    settlement_asset?: string | null;
    unresolved_basis_sales?: number;
    oracle?: string | null;
  } | null;
  independent_worksheet?: {
    total_profit_sol?: string | null;
    total_profit_usdc?: string | null;
    sale_fifo_basis_sol?: string[];
    sale_fifo_basis_usdc?: string[];
    sale_net_profit_sol?: string[];
    sale_net_profit_usdc?: string[];
    settlement_asset?: string | null;
    unresolved_basis_sales?: number;
    oracle?: string | null;
  } | null;
  worksheet_reconciliation?: {
    status?: string | null;
    production_total_profit_sol?: string | null;
    independent_total_profit_sol?: string | null;
    production_total_profit_usdc?: string | null;
    independent_total_profit_usdc?: string | null;
    difference_sol?: string | null;
    difference_usdc?: string | null;
    settlement_asset?: string | null;
    note?: string | null;
  } | null;
  research_profile?: Record<string, unknown> | null;
  visible_report?: boolean | null;
  result_scope?: string;
  capture_sha256?: string;
  analysis_cache_key?: string;
  funnel?: Record<string, unknown> | null;
  analytics?: Record<string, unknown> | null;
  next_candidates?: Record<string, unknown>[] | null;
  observations?: { kind?: string; detail?: string; reason?: string; signature?: string; count?: number }[];
  g3_status?: string | null;
  source_integrity?: { status?: string; damaged?: number; intact?: number } | null;
  declared_mints?: string[];
  wallet_completed_episodes?: number;
  wallet_sale_count?: number;
  unsupported_tx_count?: number;
  unsupported_swaps_in_window?: number;
  in_window_swaps?: number;
  unsupported_swap_share_in_window?: {
    by_count?: string | null;
    by_consideration?: Record<string, string>;
  };
  in_window_span?: { seconds?: number; hours?: string; start?: string; end?: string } | null;
  record_breakdown?: Record<string, unknown>;
  residual_sol?: string;
  residual_sol_note?: string;
  independent_audit?: {
    status?: string;
    independently_audited?: boolean;
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
    worksheet_total?: string | null;
    worksheet_total_unit?: string | null;
    worksheet_total_independently_audited?: boolean;
    worksheet_episode_bridge?: {
      worksheet_total?: string | null;
      completed_episode_net?: string | null;
      bridge?: string | null;
      unit?: string | null;
    } | null;
    content_fingerprint?: Record<string, unknown> | null;
    note?: string;
  } | null;
  verified_tips_sol?: string;
  sensitivity_unverified_debits_sol?: string;
  sensitivity_unverified_debits_note?: string;
  coverage_status?: string;
  blocking_reason?: string;
  worksheet_error?: string | null;
  unsupported_transactions?: Record<string, unknown>[];
  conversions?: Record<string, unknown>[];
  by_quote_asset?: Record<string, unknown>;
  material_exit?: {
    state?: string | null;
    first_sale_seconds?: number | null;
    exit_50_seconds?: number | null;
    exit_90_seconds?: number | null;
    final_hold_seconds?: number | null;
    quantity_weighted_exit_seconds?: string | null;
    method_version?: string | null;
    aggregation_method?: string | null;
    sample_count?: number | null;
    quantity_weighted_exit_note?: string | null;
    first_sale_window_offset_seconds?: number | null;
    exit_90_window_offset_seconds?: number | null;
  } | null;
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
  screenings?: Screening[];
  observations?: PaperObservation[];
  mass_search?: MassSearchState;
  reports: Report[];
  watchlist: { address: string; label: string; added_at?: string; source?: "demo" | "live" | "mass-search" }[];
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

export type Screening = {
  id: string;
  version: string;
  created_at: string;
  report_id: string;
  address: string;
  source?: "demo" | "live" | "mass-search" | string;
  preset_snapshot?: Preset;
  identity?: { state: string; reason: string; evidence: string[] };
  current_source_availability?: { state: string; missing: (string | null)[] };
  current_result?: string;
  current_label?: string;
  current_reason?: string;
  current_identity?: { state: string; reason: string; evidence: string[] };
  current_eligibility?: { can_start_observation: boolean; reason: string };
  result: string;
  label: string;
  reason: string;
  reasons?: (string | { key: string; state: string; reason: string; actual?: unknown; evidence?: string[] })[];
  strict_qualification?: Qualification;
  trading_evidence: {
    supported_swaps?: number;
    buy_signals?: number;
    sell_signals?: number;
    matched_sales?: number;
    unmatched_sales?: number;
    unresolved_basis_sales?: number;
    conditional_matched_lot_profit_sol?: string | null;
    open_exposure?: unknown;
    early_exits?: unknown;
    scope?: unknown;
    window?: { start: string; end: string };
  };
  risk_observations: {
    key: string;
    state: string;
    reason: string;
    actual?: unknown;
    evidence?: string[];
    mint?: string;
    relationship?: unknown;
  }[];
  collection: {
    stop_reason?: string;
    scope?: unknown;
    transactions?: number;
    pages?: number;
    credits?: number;
    gaps?: unknown[];
    terminal_evidence?: unknown;
  };
  continuation?: {
    recommended?: boolean;
    action?: string;
    reason?: string;
    budget?: { max_transactions?: number; max_credits?: number; max_accounts?: number };
    checkpoint_required?: boolean;
  };
};

export type PaperSettings = {
  capital_sol: string;
  entry_sol: string;
  max_open_positions: number;
  reaction_delay_seconds: number;
  adverse_bps: number;
  execution_fee_sol: string;
  max_price_impact_pct: string;
  max_events: number;
  max_quotes: number;
  max_duration_minutes: number;
};
export type PaperObservation = {
  id: string;
  address: string;
  screening_id?: string;
  strategy: string;
  status: string;
  settings: PaperSettings;
  started_at: string;
  updated_at: string;
  stop_reason?: string;
  signals: Record<string, unknown>[];
  quote_requests: Record<string, unknown>[];
  positions: Record<string, unknown>[];
  gaps: Record<string, unknown>[];
  observer?: {
    status?: string;
    stop_reason?: string;
    connected_at?: string;
    updated_at?: string;
    connection_attempts?: number;
    notifications?: number;
    transactions?: number;
    limits?: { max_notifications?: number; max_transactions?: number; max_minutes?: number };
    last_error?: { code: string; message: string; http_status?: number; at: string };
    monitoring_gap_started_at?: string | null;
    scope?: string;
  };
  notifications?: Record<string, unknown>[];
  risk_observations?: Screening["risk_observations"];
  copyability?: { status: string; reasons: string[]; preset_snapshot?: unknown };
  summary: {
    initial_capital_sol: string;
    cash_sol: string;
    realised_pnl_sol: string;
    open_positions: number;
    closed_positions: number;
    open_cost_sol: string;
    marked_open_value_sol: string | null;
    economic_pnl_sol: string | null;
    valuation_status: string;
    signal_count: number;
    quote_count: number;
    unavailable_quotes: number;
    complete_observation: boolean;
    [key: string]: unknown;
  };
  [key: string]: unknown;
};
export type MassSearchRunSummary = {
  run_id: string;
  status: string;
  source_id: string;
  corpus_kind: string;
  created_at?: string;
};
export type MassSearchState = {
  runs?: MassSearchRunSummary[];
  bulk_capacity?: number;
  legacy_candidate_cap?: number;
  legacy_deep_audit_cap?: number;
  live_default?: boolean;
  budget_enabled?: boolean;
  ranked_workflow?: boolean;
  note?: string;
};
export type RankedWorkflowRow = {
  address: string;
  provider_rank?: number | null;
  trade_count?: number | null;
  shortlisted?: boolean;
  capture_available?: boolean;
  report_id?: string | null;
  can_open_report?: boolean;
  user_shortlisted?: boolean;
  history_required?: boolean;
  history_required_label?: string | null;
  in_window_span?: { seconds?: number; hours?: string; start?: string; end?: string } | null;
  row_kind?: string;
  not_proof?: boolean;
  label?: string;
  corpus_kind?: string;
  funnel?: {
    A?: { state?: string };
    B?: { state?: string; scoped_pnl?: string | null; scoped_pnl_unit?: string | null; completed_known_cost_positions?: number };
    C?: { state?: string };
    next_action?: { code?: string; detail?: string };
    holder_fee_heavy?: boolean;
  } | null;
  qualification_category?: {
    category?: string;
    evidence_class?: number;
    screening_separate?: boolean;
  } | null;
  qualification_level?: {
    level?: string;
    label?: string;
  } | null;
  coverage_status?: string | null;
  blocking_reason?: string | null;
  research_profile?: {
    scoped_pnl?: string | null;
    scoped_pnl_unit?: string | null;
    completed_episode_net?: string | null;
    completed_episode_net_unit?: string | null;
    completed_known_cost_positions?: number;
    matched_fragment_pnl?: string | null;
    matched_fragment_unit?: string | null;
    qualification_level?: { level?: string; label?: string };
    coverage_status?: string | null;
    blocking_reason?: string | null;
    qualification_category?: {
      category?: string;
      evidence_class?: number;
      screening_separate?: boolean;
    };
  } | null;
  analytics?: {
    scoped_pnl?: string | null;
    scoped_pnl_unit?: string | null;
    median_hold?: { seconds?: number | null; sample_count?: number | null; n_equals_one_disclosed?: boolean };
  } | null;
};
export type RankedWorkflowView = {
  rows?: RankedWorkflowRow[];
  engineering_fixtures?: RankedWorkflowRow[];
  control_archives?: RankedWorkflowRow[];
  ranked_count?: number;
  visible_count?: number;
  budget_enabled?: boolean;
  live_enabled?: boolean;
  user_shortlist?: string[];
  funnel_counts?: Record<string, number>;
  filter_effects?: { key: string; group: string; label: string; unit?: string; value?: unknown; missing?: boolean }[];
  filters?: {
    thresholds?: Record<string, string | null>;
    provider_proxy?: {
      min_provider_trade_count?: string | null;
      min_provider_score?: string | null;
      only_shortlist?: boolean;
      only_user_shortlist?: boolean;
      only_captured?: boolean;
    };
    units?: Record<string, string>;
  };
  phone_access?: { preview_available?: boolean; blocker?: string };
  note?: string;
  snapshot_id?: string;
  snapshot_raw_sha256?: string;
  analysis_version?: string;
  capture_sha256?: string;
  research_screen?: {
    outcome?: string;
    thresholds_fixed_before_evaluation?: {
      min_completed_known_cost?: string | null;
      min_sample_positions?: string | null;
      min_coverage_share?: string | null;
    };
    counts?: {
      inconclusive?: number;
      zero_qualified?: number;
      completed_qualified?: number;
      not_executed?: number;
      qualification?: {
        not_evaluated?: number;
        analysed_incomplete?: number;
        positive_matched_position_evidence?: number;
        positive_net_realised_over_window?: number;
        profitable_account_performance?: number;
      };
      qualification_level?: {
        insufficient_evidence?: number;
        conditional_captured_lot_result?: number;
        provisional_research_lead?: number;
        stronger_research_shortlist?: number;
      };
      coverage_status?: {
        provisional_eligible?: number;
        coverage_eligibility_pending_reassessment?: number;
        watchlist_incomplete_evidence?: number;
        coverage_blocked?: number;
        blocked_unknown_denominator?: number;
      };
    };
  };
};
export type RankedBatch = {
  batch_id: string;
  status: string;
  total: number;
  completed: number;
  cancel_requested?: boolean;
  outcomes?: {
    address: string;
    status: string;
    report_id?: string | null;
    detail?: string | null;
    capture_available?: boolean;
    not_proof?: boolean;
    scoped_pnl?: string | null;
    scoped_pnl_unit?: string | null;
  }[];
};
export type ResearchCompare = {
  fields?: { key: string; left: unknown; right: unknown }[];
  mismatches?: { kind: string; detail: string }[];
  comparable?: boolean;
  window_policy?: {
    kind?: string;
    detail?: string;
    left_window?: { start?: string; end?: string };
    right_window?: { start?: string; end?: string };
    left_included_tx?: string[];
    right_included_tx?: string[];
    left_included_trades?: number;
    right_included_trades?: number;
    left_sample_size?: number;
    right_sample_size?: number;
    left_scoped_pnl?: string | null;
    right_scoped_pnl?: string | null;
    left_scoped_pnl_unit?: string | null;
    right_scoped_pnl_unit?: string | null;
    left_completed_episode_net?: string | null;
    right_completed_episode_net?: string | null;
    left_completed_episode_net_unit?: string | null;
    right_completed_episode_net_unit?: string | null;
    left_independently_audited?: boolean;
    right_independently_audited?: boolean;
    left_independently_audited_episode_net?: string | null;
    right_independently_audited_episode_net?: string | null;
    left_independently_audited_episode_net_unit?: string | null;
    right_independently_audited_episode_net_unit?: string | null;
    result_scope?: string;
  };
};
export type MassSearchStageCounts = {
  input: number;
  promoted: number;
  rejected: number;
  deferred: number;
  pending: number;
};
export type MassSearchRun = {
  run_id: string;
  status: string;
  source_id: string;
  corpus_kind: string;
  live_authorized: boolean;
  plan_frozen_at?: string;
  universe?: { raw_rows?: number; unique_candidates?: number; duplicate_rows?: number; invalid_rows?: number };
  stages?: Record<string, MassSearchStageCounts>;
  legacy_limits?: Record<string, number>;
  bulk_capacity?: number;
};
export type MassSearchMetric = {
  value?: string | null;
  unit?: string | null;
  state?: string | null;
};
export type MassSearchCandidate = {
  candidate_id: string;
  address: string;
  result?: string | null;
  reason_codes?: string[];
  sort_value?: string | null;
  unit?: string | null;
  metric_state?: string | null;
  report_id?: string | null;
  subset_pnl?: MassSearchMetric | null;
  median_hold?: MassSearchMetric | null;
  material_exit_t90?: MassSearchMetric | null;
};
