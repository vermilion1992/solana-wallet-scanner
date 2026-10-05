"""Additive mass-search tables. Legacy records/reservations stay unchanged."""
from __future__ import annotations

MASS_SEARCH_SCHEMA_VERSION = 1
MASS_UNIVERSE_CAPACITY = 10000
VALUE_SCALE = 10**9

SQL_V1 = """
CREATE TABLE IF NOT EXISTS mass_search_schema (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS search_runs (
  run_id TEXT PRIMARY KEY,
  parent_run_id TEXT,
  status TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  plan_sha256 TEXT NOT NULL,
  source_id TEXT NOT NULL,
  capability_json TEXT NOT NULL,
  corpus_kind TEXT NOT NULL,
  live_authorized INTEGER NOT NULL,
  authorization_sha256 TEXT,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  plan_frozen_at TEXT NOT NULL,
  universe_sealed_at TEXT,
  universe_sha256 TEXT,
  cohort_frozen_at TEXT,
  cohort_sha256 TEXT,
  strategy_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_universe (
  candidate_id TEXT PRIMARY KEY,
  chain TEXT NOT NULL,
  address TEXT NOT NULL,
  identity_state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS candidate_universe_chain_address
  ON candidate_universe(chain, address);
CREATE TABLE IF NOT EXISTS candidate_memberships (
  membership_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  page INTEGER,
  stratum TEXT,
  rank INTEGER,
  raw_evidence_sha256 TEXT,
  inclusion_reason TEXT,
  source_timestamp TEXT,
  fetch_timestamp TEXT,
  raw_row_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memberships_run_candidate
  ON candidate_memberships(run_id, candidate_id);
CREATE TABLE IF NOT EXISTS metric_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  value TEXT,
  unit TEXT NOT NULL,
  state TEXT NOT NULL,
  basis TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  population TEXT NOT NULL,
  population_count INTEGER NOT NULL,
  method_version TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  missing_json TEXT NOT NULL,
  source_provider TEXT,
  is_wallet_wide_verified INTEGER NOT NULL,
  notes_json TEXT NOT NULL,
  value_nanos INTEGER
);
CREATE INDEX IF NOT EXISTS metrics_run_key_sort
  ON metric_snapshots(run_id, metric_key, value_nanos, candidate_id);
CREATE TABLE IF NOT EXISTS stage_decisions (
  decision_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  stage_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  result TEXT NOT NULL,
  reason_codes TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  metric_versions TEXT NOT NULL,
  source_hashes TEXT NOT NULL,
  next_capability TEXT,
  decided_at TEXT NOT NULL,
  UNIQUE(run_id, stage_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS decisions_run_stage_result
  ON stage_decisions(run_id, stage_id, result, candidate_id);
CREATE TABLE IF NOT EXISTS work_items (
  work_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  candidate_id TEXT,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  lease_until TEXT,
  checkpoint TEXT,
  reservation_id TEXT,
  requested_units INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS work_items_run_state
  ON work_items(run_id, state, operation);
CREATE TABLE IF NOT EXISTS report_links (
  link_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  report_id TEXT NOT NULL,
  reconciliation_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS report_links_run
  ON report_links(run_id, candidate_id);
CREATE TABLE IF NOT EXISTS benchmark_receipts (
  receipt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def ensure_schema(db):
    db.executescript(SQL_V1)
    row = db.execute("SELECT version FROM mass_search_schema WHERE id=1").fetchone()
    if row is None:
        db.execute("INSERT INTO mass_search_schema(id, version) VALUES (1, ?)", (MASS_SEARCH_SCHEMA_VERSION,))
    elif int(row[0]) > MASS_SEARCH_SCHEMA_VERSION:
        raise ValueError("mass-search schema is newer than this application")
    db.commit()
