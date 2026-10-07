"""Mass-search orchestrator: acquire, decide, reconstruct, refilter, recover."""
from __future__ import annotations

import json
import statistics
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

from scanner.accounting import analyze
from scanner.config import LIMITS
from scanner.research import summarize_research
from scanner.storage import now

from .adapters import FixtureTraderAdapter, SourceError
from .capability import (
    access_blocker,
    apply_probe_result,
    authorization_sha256,
    documented_birdeye_traders,
    documented_helius_history,
    documented_jupiter_quotes,
    documented_public_sampler_fallback,
    live_authorization_from_store,
    validate_capability,
)
from .metrics import (
    build_metric,
    combined_economics,
    earliest_quote_request_seconds,
    fifo_sale_results,
    format_decimal,
    MATERIAL_EXIT_VERSION,
    material_exit_v2,
    median_hold_hours,
    unavailable_exit,
)
from .plan import assert_strict_preset_unchanged, load_default_plan, sha256_json, validate_mass_plan
from .schema import MASS_UNIVERSE_CAPACITY, ensure_schema
from .triage import (
    STAGES,
    apply_stage_cap,
    audit_sample,
    conserve_counts,
    evaluate_behaviour,
    evaluate_forward_select,
    evaluate_reconstruct,
    evaluate_triage,
    priority_tuple,
)
from .universe import (
    detect_cursor_loop,
    ingest_page,
    page_summaries,
    seal_universe,
    synthetic_address,
    universe_counts,
)

SERVICE_VERSION = "mass-search-service-v1"


def _window(plan, frozen_at):
    end = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    start = end - timedelta(days=plan["selection"]["report_window_days"])
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _load_run(store, run_id):
    with store.lock:
        row = store.db.execute("SELECT * FROM search_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown mass-search run")
    return dict(row)


def _data_run_id(store, run_id):
    """Refilter children reuse the parent's frozen memberships and metrics."""
    run = _load_run(store, run_id)
    parent = run.get("parent_run_id")
    if not parent:
        return run_id
    with store.lock:
        own = store.db.execute(
            "SELECT 1 FROM candidate_memberships WHERE run_id=? LIMIT 1", (run_id,)
        ).fetchone()
    return run_id if own else parent


def _metric_record(row):
    return {
        "metric_key": row[1], "value": row[2], "unit": row[3], "state": row[4], "basis": row[5],
        "window": {"start_inclusive": row[6], "end_exclusive": row[7]}, "population": row[8],
        "population_count": row[9], "method_version": row[10], "observed_at": row[11],
        "evidence_sha256": json.loads(row[12]), "missing_dependencies": json.loads(row[13]),
        "source_provider": row[14], "is_wallet_wide_verified": bool(row[15]), "notes": json.loads(row[16]),
    }


def _metrics_map(store, run_id):
    with store.lock:
        rows = store.db.execute(
            "SELECT candidate_id, metric_key, value, unit, state, basis, window_start, window_end, population, "
            "population_count, method_version, observed_at, evidence_json, missing_json, source_provider, "
            "is_wallet_wide_verified, notes_json FROM metric_snapshots WHERE run_id=?",
            (run_id,),
        ).fetchall()
    metrics = {}
    for row in rows:
        metrics.setdefault(row[0], {})[row[1]] = _metric_record(row)
    return metrics


def _metrics_for(store, run_id, candidate_id):
    with store.lock:
        rows = store.db.execute(
            "SELECT candidate_id, metric_key, value, unit, state, basis, window_start, window_end, population, "
            "population_count, method_version, observed_at, evidence_json, missing_json, source_provider, "
            "is_wallet_wide_verified, notes_json FROM metric_snapshots WHERE run_id=? AND candidate_id=?",
            (run_id, candidate_id),
        ).fetchall()
    metrics = {}
    for row in rows:
        metrics[row[1]] = _metric_record(row)
    return metrics


def _insert_metric(store, run_id, metric):
    store.db.execute(
        "INSERT INTO metric_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, run_id, metric["candidate_id"], metric["metric_key"], metric["value"],
         metric["unit"], metric["state"], metric["basis"], metric["window"]["start_inclusive"],
         metric["window"]["end_exclusive"], metric["population"], metric["population_count"],
         metric["method_version"], metric["observed_at"], json.dumps(metric["evidence_sha256"]),
         json.dumps(metric["missing_dependencies"]), metric["source_provider"],
         int(metric["is_wallet_wide_verified"]), json.dumps(metric["notes"]), metric.get("value_nanos")),
    )


def _save_decisions(store, run_id, stage_id, decisions, source_hashes):
    timestamp = now()
    source = json.dumps(source_hashes)
    rows = [
        (uuid.uuid4().hex, run_id, stage_id, row["candidate_id"], row["result"],
         json.dumps(row["reason_codes"]), row["policy_version"], row["metric_versions"],
         source, row.get("next_capability"), timestamp)
        for row in decisions
    ]
    with store.lock, store.db:
        store.db.execute("DELETE FROM stage_decisions WHERE run_id=? AND stage_id=?", (run_id, stage_id))
        store.db.executemany("INSERT INTO stage_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        store.db.execute("UPDATE search_runs SET updated_at=? WHERE run_id=?", (timestamp, run_id))


def stage_summary(store, run_id, stage_id):
    with store.lock:
        rows = store.db.execute(
            "SELECT result, COUNT(*) FROM stage_decisions WHERE run_id=? AND stage_id=? GROUP BY result",
            (run_id, stage_id),
        ).fetchall()
    counts = {name: 0 for name in ("PROMOTED", "REJECTED", "DEFERRED", "PENDING")}
    for result, count in rows:
        counts[result] = count
    total = sum(counts.values())
    return conserve_counts(total, counts["PROMOTED"], counts["REJECTED"], counts["DEFERRED"], counts["PENDING"])


class MassSearchService:
    def __init__(self, store, *, clock=None):
        ensure_schema(store.db)
        self.store = store
        self.clock = clock or now
        self.external_requests = 0
        self._capability_cache = None
        self._plan_cache = {}
        self._member_cache = {}
        self._metrics_cache = {}

    def capability_bundle(self):
        if self._capability_cache is None:
            self._capability_cache = self._build_capability_bundle()
        result = deepcopy(self._capability_cache)
        result["setup_pilot"] = self.store.usage("helius", "setup-pilot", 200)
        return result

    def _build_capability_bundle(self):
        auth = live_authorization_from_store(self.store)
        birdeye = documented_birdeye_traders()
        if not auth or not auth.get("enabled"):
            birdeye = apply_probe_result(
                birdeye, state="UNAUTHORIZED", role="NO_GO",
                limitations=["No enabled live authorization. Offline implementation continues."],
            )
        bundle = {
            "strict_preset": assert_strict_preset_unchanged(),
            "legacy_limits": dict(LIMITS),
            "bulk_universe_capacity": MASS_UNIVERSE_CAPACITY,
            "live_authorization": None if not auth else {"enabled": auth.get("enabled"), "authorization_id": auth.get("authorization_id")},
            "sources": {
                "birdeye-traders": validate_capability(birdeye),
                "public-pool-sampler": documented_public_sampler_fallback(),
                "helius-history": documented_helius_history(),
                "jupiter-quote": documented_jupiter_quotes(),
            },
            "access_blocker": access_blocker("birdeye-traders"),
            "helius_blocker": access_blocker("helius-history"),
        }
        return bundle

    def _validated_plan(self, plan=None):
        key = "default" if plan is None else sha256_json(plan)
        if key not in self._plan_cache:
            self._plan_cache[key] = validate_mass_plan(plan)
        return deepcopy(self._plan_cache[key])

    def preview_plan(self, plan=None):
        validated = self._validated_plan(plan)
        return {"plan": validated, "plan_sha256": sha256_json(validated), "strict_preset": assert_strict_preset_unchanged()}

    def create_run(self, plan=None, *, source_id="fixture-traders", corpus_kind="SYNTHETIC",
                   parent_run_id=None, authorization=None):
        if corpus_kind not in ("SYNTHETIC", "GENUINE_REPLAY", "GENUINE_LIVE"):
            raise ValueError("Unsupported corpus kind")
        validated = self._validated_plan(plan)
        if validated["live_enabled"] and corpus_kind == "GENUINE_LIVE":
            auth = authorization or live_authorization_from_store(self.store)
            if not auth or not auth.get("enabled"):
                raise SourceError("UNAUTHORIZED", "Live collection requires an enabled authorization")
        elif corpus_kind == "GENUINE_LIVE":
            raise SourceError("UNAUTHORIZED", "Plan live_enabled is false; genuine live collection is blocked")
        frozen_at = self.clock()
        window_start, window_end = _window(validated, frozen_at)
        capability = self.capability_bundle()
        run_id = uuid.uuid4().hex
        auth_hash = authorization_sha256(authorization or live_authorization_from_store(self.store))
        live = corpus_kind == "GENUINE_LIVE"
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT INTO search_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, parent_run_id, "CREATED", json.dumps(validated), sha256_json(validated),
                 source_id, json.dumps(capability["sources"]), corpus_kind, int(live), auth_hash,
                 window_start, window_end, frozen_at, None, None, None, None,
                 validated["provisional_following_model"]["baseline_strategy"], frozen_at, frozen_at),
            )
        return self.run_view(run_id)

    def run_view(self, run_id):
        run = _load_run(self.store, run_id)
        counts = universe_counts(self.store, _data_run_id(self.store, run_id))
        stages = {stage: stage_summary(self.store, run_id, stage) for stage in STAGES}
        return {
            "run_id": run["run_id"],
            "parent_run_id": run["parent_run_id"],
            "status": run["status"],
            "source_id": run["source_id"],
            "corpus_kind": run["corpus_kind"],
            "live_authorized": bool(run["live_authorized"]),
            "plan": json.loads(run["plan_json"]),
            "plan_sha256": run["plan_sha256"],
            "plan_frozen_at": run["plan_frozen_at"],
            "window_start": run["window_start"],
            "window_end": run["window_end"],
            "universe": counts,
            "universe_sealed_at": run["universe_sealed_at"],
            "universe_sha256": run["universe_sha256"],
            "cohort_frozen_at": run["cohort_frozen_at"],
            "cohort_sha256": run["cohort_sha256"],
            "strategy_id": run["strategy_id"],
            "stages": stages,
            "legacy_limits": dict(LIMITS),
            "bulk_capacity": MASS_UNIVERSE_CAPACITY,
        }

    def list_runs(self):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT run_id, status, source_id, corpus_kind, created_at FROM search_runs ORDER BY created_at DESC, run_id",
            ).fetchall()
        return [{"run_id": row[0], "status": row[1], "source_id": row[2], "corpus_kind": row[3], "created_at": row[4]} for row in rows]

    def acquire_from_adapter(self, run_id, adapter, *, window="30d", target_unique=None):
        run = _load_run(self.store, run_id)
        if run["status"] in ("CANCELLED",):
            raise ValueError("Cancelled run cannot acquire")
        plan = json.loads(run["plan_json"])
        target = target_unique or plan["selection"]["universe_target_unique"]
        offset = 0
        seen = set()
        totals = {"raw_rows": 0, "unique_added": 0, "duplicate_rows": 0, "invalid_rows": 0}
        pages = 0
        while totals["unique_added"] < target:
            detect_cursor_loop(seen, offset)
            page = adapter.fetch_page(offset=offset, limit=100, window=window, store=self.store)
            self.external_requests += int(page.get("external_requests") or 0)
            page["window_start"] = run["window_start"]
            page["window_end"] = run["window_end"]
            ingested = ingest_page(self.store, run_id, page)
            totals["raw_rows"] += ingested["raw_rows"]
            totals["unique_added"] += ingested["unique_added"]
            totals["duplicate_rows"] += ingested["duplicate_rows"]
            totals["invalid_rows"] += ingested["invalid_rows"]
            pages += 1
            if page.get("next_offset") is None or ingested["raw_rows"] == 0:
                break
            offset = page["next_offset"]
        sealed = seal_universe(self.store, run_id, extra=totals)
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE search_runs SET status=?, updated_at=? WHERE run_id=?", ("UNIVERSE_SEALED", now(), run_id))
        return {**sealed, "pages": pages, "external_requests": self.external_requests}

    def evaluate_stage(self, run_id, stage_id, *, persist=True):
        run = _load_run(self.store, run_id)
        plan = json.loads(run["plan_json"])
        if stage_id not in STAGES:
            raise ValueError("Unsupported stage")
        data_run = _data_run_id(self.store, run_id)
        if stage_id == "triage":
            if data_run not in self._member_cache:
                with self.store.lock:
                    self._member_cache[data_run] = [row[0] for row in self.store.db.execute(
                        "SELECT DISTINCT candidate_id FROM candidate_memberships WHERE run_id=?", (data_run,)).fetchall()]
            ids = self._member_cache[data_run]
            cap = plan["stage_workload_maxima_not_permissions"]["summary_enrichment"]
            evaluator = evaluate_triage
        else:
            previous = STAGES[STAGES.index(stage_id) - 1]
            with self.store.lock:
                ids = [row[0] for row in self.store.db.execute(
                    "SELECT candidate_id FROM stage_decisions WHERE run_id=? AND stage_id=? AND result='PROMOTED' ORDER BY candidate_id",
                    (run_id, previous),
                ).fetchall()]
            cap_key = {"behaviour": "behaviour_history", "reconstruct": "detailed_reconstruction",
                       "forward_select": "forward_watch_candidates"}[stage_id]
            cap = plan["stage_workload_maxima_not_permissions"][cap_key]
            evaluator = {"behaviour": evaluate_behaviour, "reconstruct": evaluate_reconstruct,
                         "forward_select": evaluate_forward_select}[stage_id]
        if data_run not in self._metrics_cache:
            self._metrics_cache[data_run] = _metrics_map(self.store, data_run)
        metric_index = self._metrics_cache[data_run]
        decisions = []
        for ident in ids:
            address = ident.split(":", 1)[1]
            metrics = metric_index.get(ident, {})
            candidate = {"candidate_id": ident, "address": address,
                         "_priority": priority_tuple({"candidate_id": ident}, metrics)}
            extra = {}
            if stage_id == "reconstruct":
                extra["report"] = self._report_link(run_id, ident)
            decisions.append(evaluator(candidate, metrics, plan, **extra))
        decisions = apply_stage_cap(decisions, cap)
        if persist:
            _save_decisions(self.store, run_id, stage_id, decisions, [run["plan_sha256"]])
        summary = conserve_counts(
            len(decisions),
            sum(row["result"] == "PROMOTED" for row in decisions),
            sum(row["result"] == "REJECTED" for row in decisions),
            sum(row["result"] == "DEFERRED" for row in decisions),
            sum(row["result"] == "PENDING" for row in decisions),
        )
        return {"stage_id": stage_id, "summary": summary, "decisions": decisions}

    def refilter(self, run_id, plan=None):
        """New decision snapshot against the frozen universe. Zero provider calls."""
        before = self.external_requests
        parent = _load_run(self.store, run_id)
        child = self.create_run(plan or json.loads(parent["plan_json"]),
                                source_id=parent["source_id"], corpus_kind=parent["corpus_kind"],
                                parent_run_id=run_id)
        sealed_at = parent["universe_sealed_at"] or now()
        sealed_hash = parent["universe_sha256"] or sha256_json({"parent_run_id": run_id})
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "UPDATE search_runs SET universe_sealed_at=?, universe_sha256=?, status=?, updated_at=? WHERE run_id=?",
                (sealed_at, sealed_hash, "UNIVERSE_SEALED", now(), child["run_id"]),
            )
        if self.external_requests != before:
            raise RuntimeError("Refilter issued external requests")
        self.evaluate_stage(child["run_id"], "triage")
        if self.external_requests != before:
            raise RuntimeError("Refilter issued external requests")
        return self.run_view(child["run_id"])

    def reconstruct_candidate(self, run_id, candidate_id, events, *, corpus_kind=None, mint="Mint1111111111111111111111111111111111111"):
        run = _load_run(self.store, run_id)
        kind = corpus_kind or run["corpus_kind"]
        start, end = run["window_start"], run["window_end"]
        accounting_events = events_to_accounting(events, mint=mint, start=start)
        evidence = self.store.archive({
            "kind": "mass-search-reconstruction-v1",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "corpus_kind": kind,
            "events": events,
        })
        try:
            analysis = analyze(accounting_events, start, end, history_complete=False)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"Accounting integration failed: {error}") from error
        try:
            research = summarize_research(accounting_events, start, end, history_complete=False)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"Research integration failed: {error}") from error
        from .settlement import USDC, settlement_aware_worksheet, settlement_of

        trade_events = [event for event in events if event.get("kind") in ("buy", "sell")]
        try:
            worksheet = settlement_aware_worksheet(trade_events) if trade_events else None
        except ValueError:
            worksheet = None
        from .g3_history import completed_episodes
        by_mint = {}
        for event in trade_events:
            mint_id = event.get("mint") or mint
            row = dict(event)
            if row.get("role") is None and row.get("window_qualified") is None:
                row["role"] = "in_report"
                row["window_qualified"] = True
            by_mint.setdefault(mint_id, []).append(row)
        episodes = completed_episodes(by_mint) if by_mint else {
            "wallet_completed_episodes": 0,
            "wallet_sale_count": 0,
            "per_mint": {},
            "per_mint_detail": {},
        }
        exit_diag = material_exit_v2([
            {
                "kind": event["kind"],
                "units": event.get("units"),
                "seconds_from_start": event.get("seconds_from_start"),
                "mint": event.get("mint") or mint,
                "signature": event.get("signature"),
                "unresolved_order": event.get("unresolved_order"),
                "timestamp_missing": event.get("timestamp_missing"),
            }
            for event in events
            if event.get("kind") in ("buy", "sell")
        ], transfers_unknown=any(event.get("origin") == "transfer" for event in events))
        holds = []
        for position in analysis.get("positions") or []:
            hours = (position.get("metrics") or {}).get("hold_hours") if isinstance(position, dict) else None
            if isinstance(position, dict) and position.get("hold_hours") is not None:
                holds.append(position["hold_hours"])
            elif isinstance(hours, dict) and hours.get("value") is not None:
                holds.append(hours["value"])
        if not holds:
            closed = [event for event in events if event.get("kind") == "sell" and event.get("hold_hours") is not None]
            holds = [event["hold_hours"] for event in closed]
        if not holds and exit_diag.get("final_hold_seconds") is not None:
            holds = [format_decimal(Decimal(exit_diag["final_hold_seconds"]) / Decimal("3600"))]
        hold_metric = median_hold_hours(holds)
        profit = None
        profit_unit = "SOL"
        profit_metric = (analysis.get("metrics") or {}).get("profit_sol")
        mixed = bool((worksheet or {}).get("settlement_asset") == "mixed" or len((worksheet or {}).get("by_quote_asset") or {}) > 1)
        if isinstance(profit_metric, dict) and profit_metric.get("value") is not None and profit_metric.get("status") == "known":
            profit = profit_metric["value"]
            profit_unit = "SOL"
        elif mixed:
            profit = None
            profit_unit = "mixed"
        elif worksheet and worksheet.get("total_profit_usdc") not in (None, "") and worksheet.get("settlement_asset") == "USDC":
            profit = worksheet["total_profit_usdc"]
            profit_unit = "USDC"
        elif worksheet and worksheet.get("total_profit_sol") not in (None, ""):
            profit = worksheet["total_profit_sol"]
            profit_unit = "SOL"
        window = {"start_inclusive": start, "end_exclusive": end}
        observed = self.clock()
        with self.store.lock, self.store.db:
            if profit_unit == "mixed":
                by_asset = (worksheet or {}).get("by_quote_asset") or {}
                usdc_ws = by_asset.get("USDC") or {}
                sol_ws = by_asset.get("SOL") or {}
                if usdc_ws.get("total_profit_usdc") not in (None, ""):
                    pnl = build_metric(
                        metric_key="subset_realised_pnl_usdc", candidate_id=candidate_id,
                        value=usdc_ws["total_profit_usdc"], unit="USDC",
                        state="KNOWN", basis="INDEPENDENTLY_RECONCILED_SUBSET", window=window,
                        population="supported_closed_subset", population_count=len(holds) or len(events),
                        observed_at=observed, evidence_sha256=[evidence], missing_dependencies=[],
                        source_provider="local-reconstruction",
                        notes=["USDC-settled subset of a mixed wallet; no FX into SOL."],
                    )
                    _insert_metric(self.store, run_id, pnl)
                if sol_ws.get("total_profit_sol") not in (None, ""):
                    pnl = build_metric(
                        metric_key="subset_realised_pnl_sol", candidate_id=candidate_id,
                        value=sol_ws["total_profit_sol"], unit="SOL",
                        state="KNOWN", basis="INDEPENDENTLY_RECONCILED_SUBSET", window=window,
                        population="supported_closed_subset", population_count=len(holds) or len(events),
                        observed_at=observed, evidence_sha256=[evidence], missing_dependencies=[],
                        source_provider="local-reconstruction",
                        notes=["SOL-settled subset of a mixed wallet; no FX into USDC."],
                    )
                else:
                    pnl = build_metric(
                        metric_key="subset_realised_pnl_sol", candidate_id=candidate_id, value=None, unit="SOL",
                        state="UNKNOWN", basis="RAW_DERIVED_SUBSET", window=window,
                        population="supported_closed_subset", population_count=0,
                        observed_at=observed, evidence_sha256=[evidence],
                        missing_dependencies=["mixed_quote_assets_no_fx"],
                        source_provider="local-reconstruction",
                        notes=["Mixed SOL+USDC subset; totals stay per quote asset with no FX."],
                    )
            elif profit is None:
                pnl = build_metric(
                    metric_key="subset_realised_pnl_sol", candidate_id=candidate_id, value=None, unit="SOL",
                    state="UNKNOWN", basis="RAW_DERIVED_SUBSET", window=window, population="supported_closed_subset",
                    population_count=0, observed_at=observed, evidence_sha256=[evidence],
                    missing_dependencies=["supported_fifo_basis"], source_provider="local-reconstruction",
                    notes=["Subset P&L unknown; independent fees remain visible where supported."],
                )
            elif profit_unit == "USDC":
                pnl = build_metric(
                    metric_key="subset_realised_pnl_usdc", candidate_id=candidate_id, value=profit, unit="USDC",
                    state="KNOWN", basis="INDEPENDENTLY_RECONCILED_SUBSET", window=window,
                    population="supported_closed_subset", population_count=len(holds) or len(events),
                    observed_at=observed, evidence_sha256=[evidence], missing_dependencies=[],
                    source_provider="local-reconstruction",
                    notes=["USDC-settled subset; SOL P&L is not converted. Not a wallet-wide MATCH."],
                )
                _insert_metric(self.store, run_id, pnl)
                pnl = build_metric(
                    metric_key="subset_realised_pnl_sol", candidate_id=candidate_id, value=None, unit="SOL",
                    state="UNKNOWN", basis="RAW_DERIVED_SUBSET", window=window,
                    population="supported_closed_subset", population_count=0,
                    observed_at=observed, evidence_sha256=[evidence],
                    missing_dependencies=["usdc_settlement_not_converted"],
                    source_provider="local-reconstruction",
                    notes=["USDC-settled subset; no fake FX into SOL."],
                )
            else:
                pnl = build_metric(
                    metric_key="subset_realised_pnl_sol", candidate_id=candidate_id, value=profit, unit="SOL",
                    state="KNOWN", basis="INDEPENDENTLY_RECONCILED_SUBSET", window=window,
                    population="supported_closed_subset", population_count=len(holds) or len(events),
                    observed_at=observed, evidence_sha256=[evidence], missing_dependencies=[],
                    source_provider="local-reconstruction",
                    notes=["Independently reconciled subset; not a strict whole-wallet result."],
                )
            _insert_metric(self.store, run_id, pnl)
            if hold_metric["state"] == "KNOWN":
                hold = build_metric(
                    metric_key="median_observed_hold_hours", candidate_id=candidate_id, value=hold_metric["value"],
                    unit="hours", state="KNOWN", basis="RAW_DERIVED_SUBSET", window=window,
                    population="eligible_closed_observed_episodes", population_count=hold_metric["population_count"],
                    observed_at=observed, evidence_sha256=[evidence], missing_dependencies=[],
                    source_provider="local-reconstruction",
                )
            else:
                hold = build_metric(
                    metric_key="median_observed_hold_hours", candidate_id=candidate_id, value=None, unit="hours",
                    state="UNKNOWN", basis="RAW_DERIVED_SUBSET", window=window,
                    population="eligible_closed_observed_episodes", population_count=0,
                    observed_at=observed, evidence_sha256=[evidence],
                    missing_dependencies=hold_metric["missing_dependencies"], source_provider="local-reconstruction",
                )
            _insert_metric(self.store, run_id, hold)
            if exit_diag.get("exit_90_seconds") is not None:
                t90 = build_metric(
                    metric_key="material_exit_t90_seconds", candidate_id=candidate_id,
                    value=str(exit_diag["exit_90_seconds"]), unit="seconds", state="KNOWN",
                    basis="RAW_DERIVED_SUBSET", window=window,
                    population="per_position_opening_relative",
                    population_count=int(exit_diag.get("sample_count") or 1),
                    method_version=MATERIAL_EXIT_VERSION, observed_at=observed,
                    evidence_sha256=[evidence], missing_dependencies=[],
                    source_provider="local-reconstruction",
                    notes=[
                        note for note in (
                            "material-exit-v2; t90 is opening-relative per completed position.",
                            "Long final hold does not hide a fast t90.",
                            exit_diag.get("quantity_weighted_exit_note"),
                        ) if note
                    ],
                )
                _insert_metric(self.store, run_id, t90)
            elif (exit_diag.get("state") == "UNKNOWN") or exit_diag.get("missing_dependencies"):
                t90 = build_metric(
                    metric_key="material_exit_t90_seconds", candidate_id=candidate_id,
                    value=None, unit="seconds", state="UNKNOWN",
                    basis="RAW_DERIVED_SUBSET", window=window,
                    population="per_position_opening_relative",
                    population_count=0, method_version=MATERIAL_EXIT_VERSION,
                    observed_at=observed, evidence_sha256=[evidence],
                    missing_dependencies=list(exit_diag.get("missing_dependencies") or ["material_exit_unavailable"]),
                    source_provider="local-reconstruction",
                    notes=["material-exit-v2; opening-relative t90 unavailable; no window-offset substitution."],
                )
                _insert_metric(self.store, run_id, t90)
            if exit_diag.get("final_hold_seconds") is not None:
                final = build_metric(
                    metric_key="final_hold_seconds", candidate_id=candidate_id,
                    value=str(exit_diag["final_hold_seconds"]), unit="seconds", state="KNOWN",
                    basis="RAW_DERIVED_SUBSET", window=window,
                    population="per_position_opening_relative",
                    population_count=int(exit_diag.get("sample_count") or 1),
                    method_version=MATERIAL_EXIT_VERSION, observed_at=observed,
                    evidence_sha256=[evidence], missing_dependencies=[],
                    source_provider="local-reconstruction",
                )
                _insert_metric(self.store, run_id, final)
        report = {
            "id": uuid.uuid4().hex,
            "address": candidate_id.split(":", 1)[1],
            "label": f"Mass-search subset · {kind}",
            "source": "mass-search",
            "corpus_kind": kind,
            "created_at": observed,
            "window": {"start": start, "end": end},
            "methodology": analysis.get("methodology"),
            "policy": analysis.get("policy") or "UNRESOLVED",
            "evidence_status": "partial",
            "metrics": analysis.get("metrics") or {},
            "checks": analysis.get("checks") or [],
            "counts": analysis.get("counts") or {},
            "positions": analysis.get("positions") or [],
            "events": [row for row in accounting_events if row.get("kind") in ("buy", "sell")],
            "findings": [],
            "coverage": analysis.get("coverage") or {},
            "research": research,
            "worksheet": worksheet,
            "by_quote_asset": (worksheet or {}).get("by_quote_asset"),
            "wallet_completed_episodes": episodes["wallet_completed_episodes"],
            "wallet_sale_count": episodes.get("wallet_sale_count") or 0,
            "completed_episode_detail": episodes,
            "material_exit": exit_diag,
            "evidence": [{"hash": evidence, "kind": "mass-search-reconstruction"}],
            "strict_preset": assert_strict_preset_unchanged(),
            "notes": [
                "Subset reconstruction through the existing accounting/research functions.",
                "Does not establish complete historical ownership or PRODUCT_READY.",
            ],
        }
        self.store.put("reports", report["id"], report)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT INTO report_links VALUES (?,?,?,?,?,?)",
                (uuid.uuid4().hex, run_id, candidate_id, report["id"],
                 json.dumps({"worksheet": worksheet, "material_exit": exit_diag, "evidence": evidence}),
                 observed),
            )
        return {"report": report, "evidence_sha256": evidence, "worksheet": worksheet, "material_exit": exit_diag}

    def _report_link(self, run_id, candidate_id):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT report_id FROM report_links WHERE run_id=? AND candidate_id=?",
                (run_id, candidate_id),
            ).fetchone()
        return None if row is None else self.store.get("reports", row[0])

    def page_candidates(self, run_id, **kwargs):
        data_run = _data_run_id(self.store, run_id)
        query_run = run_id if kwargs.get("stage") else data_run
        page = page_summaries(self.store, query_run, data_run_id=data_run, **kwargs)
        return self._attach_candidate_details(run_id, page)

    def _attach_candidate_details(self, run_id, page):
        items = page.get("items") or []
        if not items:
            return page
        data_run = _data_run_id(self.store, run_id)
        ids = [item["candidate_id"] for item in items]
        placeholders = ",".join("?" * len(ids))
        with self.store.lock:
            links = self.store.db.execute(
                f"SELECT candidate_id, report_id FROM report_links WHERE run_id IN (?, ?) AND candidate_id IN ({placeholders})",
                (run_id, data_run, *ids),
            ).fetchall()
            extras = self.store.db.execute(
                f"SELECT candidate_id, metric_key, value, unit, state FROM metric_snapshots "
                f"WHERE run_id=? AND candidate_id IN ({placeholders}) AND metric_key IN (?,?,?)",
                (data_run, *ids, "subset_realised_pnl_sol", "median_observed_hold_hours",
                 "material_exit_t90_seconds"),
            ).fetchall()
        link_map = {row[0]: row[1] for row in links}
        extra_map = {}
        for ident, key, value, unit, state in extras:
            extra_map.setdefault(ident, {})[key] = {"value": value, "unit": unit, "state": state}
        for item in items:
            ident = item["candidate_id"]
            item["report_id"] = link_map.get(ident)
            metrics = extra_map.get(ident, {})
            item["subset_pnl"] = metrics.get("subset_realised_pnl_sol")
            item["median_hold"] = metrics.get("median_observed_hold_hours")
            item["material_exit_t90"] = metrics.get("material_exit_t90_seconds")
        return page

    def linked_reports(self, run_id):
        data_run = _data_run_id(self.store, run_id)
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT candidate_id, report_id FROM report_links WHERE run_id IN (?, ?) ORDER BY created_at, report_id",
                (run_id, data_run),
            ).fetchall()
        reports = []
        seen = set()
        for ident, report_id in rows:
            if report_id in seen:
                continue
            seen.add(report_id)
            report = self.store.get("reports", report_id)
            if report:
                reports.append({**report, "candidate_id": ident})
        return reports

    def pause(self, run_id):
        return self._set_status(run_id, "PAUSED", allowed=("CREATED", "UNIVERSE_SEALED", "RUNNING"))

    def resume(self, run_id):
        return self._set_status(run_id, "RUNNING", allowed=("PAUSED", "CREATED", "UNIVERSE_SEALED"))

    def cancel(self, run_id):
        return self._set_status(run_id, "CANCELLED", allowed=("CREATED", "UNIVERSE_SEALED", "RUNNING", "PAUSED"))

    def _set_status(self, run_id, status, allowed):
        run = _load_run(self.store, run_id)
        if run["status"] not in allowed:
            raise ValueError(f"Cannot move run from {run['status']} to {status}")
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE search_runs SET status=?, updated_at=? WHERE run_id=?", (status, now(), run_id))
        return self.run_view(run_id)

    def freeze_cohort(self, run_id, candidate_ids, *, strategy_id="fixed-entry-first-sale-v1"):
        run = _load_run(self.store, run_id)
        if run["cohort_frozen_at"]:
            raise ValueError("Cohort already frozen; create a new experiment to change selection")
        payload = {"run_id": run_id, "candidate_ids": list(candidate_ids), "strategy_id": strategy_id}
        digest = sha256_json(payload)
        timestamp = self.clock()
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "UPDATE search_runs SET cohort_frozen_at=?, cohort_sha256=?, strategy_id=?, updated_at=? WHERE run_id=?",
                (timestamp, digest, strategy_id, timestamp, run_id),
            )
        return {"cohort_frozen_at": timestamp, "cohort_sha256": digest, "strategy_id": strategy_id}

    def record_work(self, run_id, operation, *, candidate_id=None, units=1, reservation_id=None, state="reserved"):
        work_id = uuid.uuid4().hex
        key = f"{run_id}:{operation}:{candidate_id or '*'}"
        timestamp = now()
        with self.store.lock, self.store.db:
            existing = self.store.db.execute("SELECT work_id FROM work_items WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return {"work_id": existing[0], "idempotent": True}
            self.store.db.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (work_id, run_id, candidate_id, operation, key, state, None, None, reservation_id, units, timestamp, timestamp),
            )
        return {"work_id": work_id, "idempotent": False}

    def recover_reservation(self, reservation_id, *, dispatched=False, archived=False):
        if not dispatched:
            self.store.release(reservation_id)
            return {"released": True, "charged": False}
        self.store.settle(reservation_id, charge=True)
        return {"released": False, "charged": True, "archived": archived}

    def vertical_slice(self, *, events, pages=None, corpus_kind="SYNTHETIC"):
        """Smallest complete source -> universe -> triage -> history -> report path."""
        plan = load_default_plan()
        run = self.create_run(plan, source_id="fixture-traders", corpus_kind=corpus_kind)
        address = events[0].get("address") or synthetic_address(1)
        fixture_row = {
            "address": address,
            "realized_pnl": "12.5",
            "trade_count": 24,
            "last_active": 1,
            "rank": 1,
        }
        adapter = FixtureTraderAdapter(pages or [[fixture_row]], corpus_kind=corpus_kind)
        acquired = self.acquire_from_adapter(run["run_id"], adapter, target_unique=1)
        ident = f"solana:{address}"
        reconstructed = self.reconstruct_candidate(run["run_id"], ident, events, corpus_kind=corpus_kind)
        for stage in STAGES:
            self.evaluate_stage(run["run_id"], stage)
        view = self.run_view(run["run_id"])
        exported = self.export_run(run["run_id"])
        return {
            "run": view,
            "acquisition": acquired,
            "reconstruction": reconstructed,
            "export": exported,
            "setup_pilot": self.store.usage("helius", "setup-pilot", 200),
            "external_requests": self.external_requests,
        }

    def export_run(self, run_id):
        view = self.run_view(run_id)
        with self.store.lock:
            decisions = [dict(row) for row in self.store.db.execute("SELECT * FROM stage_decisions WHERE run_id=?", (run_id,)).fetchall()]
            links = [dict(row) for row in self.store.db.execute("SELECT * FROM report_links WHERE run_id=?", (run_id,)).fetchall()]
        reports = []
        from scanner.mass_search.workflow import visible_mass_search_report
        for report in self.linked_reports(run_id):
            visible = visible_mass_search_report(report)
            reports.append({
                "id": visible.get("id"),
                "candidate_id": visible.get("candidate_id"),
                "address": visible.get("address"),
                "source": visible.get("source"),
                "corpus_kind": visible.get("corpus_kind"),
                "policy": visible.get("policy"),
                "label": visible.get("label"),
                "worksheet": visible.get("worksheet"),
                "material_exit": visible.get("material_exit"),
                "notes": visible.get("notes"),
                "observations": visible.get("observations") or [],
                "g3_status": visible.get("g3_status"),
                "source_integrity": visible.get("source_integrity"),
                "declared_mints": visible.get("declared_mints") or [],
                "wallet_completed_episodes": visible.get("wallet_completed_episodes"),
                "events": visible.get("events") or [],
                "research_profile": visible.get("research_profile"),
                "funnel": visible.get("funnel"),
                "analytics": visible.get("analytics"),
                "capture_sha256": visible.get("capture_sha256"),
                "analysis_cache_key": visible.get("analysis_cache_key"),
                "mass_search_interpretation": visible.get("mass_search_interpretation"),
            })
        payload = {"run": view, "decisions": decisions, "report_links": links, "reports": reports, "exported_at": self.clock()}
        digest = self.store.archive(payload)
        dest = self.store.path / "exports" / f"mass-search-{run_id[:12]}.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"path": str(dest), "evidence_sha256": digest, "payload": payload}

    def local_scale_benchmark(self, *, rows=10000, warmups=5, measured=20, page_size=50):
        if rows > MASS_UNIVERSE_CAPACITY:
            raise ValueError("Local scale benchmark cannot exceed bulk-universe capacity")
        plan = load_default_plan()
        page = []
        for index in range(rows):
            page.append({
                "address": synthetic_address(index),
                "realized_pnl": str((index % 97) - 10),
                "trade_count": 10 + (index % 40),
                "rank": index,
            })
        run = self.create_run(plan, source_id="fixture-traders", corpus_kind="SYNTHETIC")
        adapter = FixtureTraderAdapter([page[i:i + 100] for i in range(0, rows, 100)])
        before = self.external_requests
        acquired = self.acquire_from_adapter(run["run_id"], adapter, target_unique=rows)
        self.evaluate_stage(run["run_id"], "triage")
        timings = []
        for _ in range(warmups):
            self.refilter(run["run_id"], plan)
            self.page_candidates(run["run_id"], stage="triage", limit=page_size)
        for _ in range(measured):
            started = time.perf_counter()
            child = self.refilter(run["run_id"], plan)
            self.page_candidates(child["run_id"], stage="triage", limit=page_size)
            timings.append((time.perf_counter() - started) * 1000)
        if self.external_requests != before:
            raise RuntimeError("Local scale benchmark issued external requests")
        timings.sort()
        p95_index = max(0, int(round(0.95 * (len(timings) - 1))))
        return {
            "run_id": run["run_id"],
            "rows": acquired["unique_candidates"] if "unique_candidates" in acquired else rows,
            "unique_candidates": universe_counts(self.store, run["run_id"])["unique_candidates"],
            "external_requests": 0,
            "warmups": warmups,
            "measured": measured,
            "median_ms": statistics.median(timings),
            "p95_ms": timings[p95_index],
            "max_ms": max(timings),
            "timings_ms": timings,
            "legacy_candidate_cap": LIMITS["candidate_cap"],
        }

    def next_work(self, run_id):
        """Deterministic planner: cached -> decisive cheap criterion -> priority -> id."""
        view = self.run_view(run_id)
        promoted = []
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT candidate_id FROM stage_decisions WHERE run_id=? AND stage_id='triage' AND result='PROMOTED'",
                (run_id,),
            ).fetchall()
        data_run = _data_run_id(self.store, run_id)
        metric_index = _metrics_map(self.store, data_run)
        for (ident,) in rows:
            metrics = metric_index.get(ident, {})
            cached = self._report_link(run_id, ident) is not None
            promoted.append((priority_tuple({"candidate_id": ident}, metrics, cached=cached), ident))
        promoted.sort()
        return [{"candidate_id": ident, "priority": list(priority)} for priority, ident in promoted]

    def exploration_sample(self, run_id):
        plan = json.loads(_load_run(self.store, run_id)["plan_json"])
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT candidate_id, reason_codes FROM stage_decisions WHERE run_id=? AND stage_id='triage' AND result IN ('REJECTED','DEFERRED')",
                (run_id,),
            ).fetchall()
        items = [{"candidate_id": row[0], "reason_codes": json.loads(row[1])} for row in rows]
        slots = plan["stage_workload_maxima_not_permissions"]["detailed_reconstruction"]
        return audit_sample(items, share_pct=plan["exploration_audit"]["share_of_authorised_deep_work_pct"],
                            seed=plan["exploration_audit"]["selection_seed"], authorised_slots=slots)


def evidenced_paid_by_wallet(event):
    """Carry explicit payer evidence. Do not invent paid_by_wallet=True on every trade."""
    if "paid_by_wallet" in event:
        paid = event["paid_by_wallet"]
        if not isinstance(paid, bool):
            raise ValueError("paid_by_wallet must be boolean")
        return paid
    return None


def events_to_accounting(events, *, mint, start):
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    rows = []
    for index, event in enumerate(events):
        if event.get("timestamp_missing"):
            continue
        if event.get("kind") == "transfer":
            when = start_dt + timedelta(seconds=int(event.get("seconds_from_start") or 0))
            transfer_order = event.get("order")
            rows.append({
                "kind": "transfer",
                "timestamp": when.isoformat().replace("+00:00", "Z"),
                "order": transfer_order if isinstance(transfer_order, int) and not isinstance(transfer_order, bool) else index,
                "mint": event.get("mint") or mint,
                "quantity_raw": str(event["units"]),
                "decimals": 0,
                "classification": "meme",
                "signature": event.get("signature") or f"synthetic-transfer-{index}",
                "path": event.get("path") or "fixture",
                "evidence": event.get("evidence") or ["fixture-hash"],
                "origin": "transfer",
            })
            continue
        if event.get("kind") not in ("buy", "sell", "fee"):
            continue
        when = start_dt + timedelta(seconds=int(event.get("seconds_from_start") or 0))
        paid = evidenced_paid_by_wallet(event)
        fee_amount = event.get("wallet_fee_sol") if event.get("wallet_fee_sol") not in (None, "") else event.get("fee_sol")
        event_order = event.get("order")
        row = {
            "kind": event["kind"],
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            "order": event_order if isinstance(event_order, int) and not isinstance(event_order, bool) else index,
            "mint": event.get("mint") or mint,
            "quantity_raw": str(event.get("units") or "0"),
            "decimals": 0,
            "classification": "meme",
            "signature": event.get("signature") or f"synthetic-{index}",
            "path": event.get("path") or "fixture",
            "evidence": event.get("evidence") or ["fixture-hash"],
            "seconds_from_start": event.get("seconds_from_start"),
            "units": str(event.get("units") or "0"),
        }
        from .settlement import USDC, settlement_of
        if settlement_of(event) == USDC:
            row["amount_usdc"] = str(event.get("consideration_usdc") or event.get("amount_usdc") or "0")
            row["settlement_mint"] = USDC
            row["settlement_asset"] = "USDC"
            row["market_classification"] = event.get("classification") or "market"
        elif "consideration_sol" in event:
            row["amount_sol"] = event["consideration_sol"]
        elif event.get("amount_sol") is not None:
            row["amount_sol"] = event["amount_sol"]
        if fee_amount not in (None, ""):
            row["fee_sol"] = str(fee_amount)
        if paid is True:
            row["paid_by_wallet"] = True
        elif paid is False:
            row["paid_by_wallet"] = False
        elif fee_amount not in (None, "", "0"):
            # wallet_fee_sol / fee_sol on a mass-search trade is evidenced wallet spend.
            row["paid_by_wallet"] = True
            paid = True
        rows.append(row)
        if (
            event["kind"] in ("buy", "sell")
            and fee_amount not in (None, "", "0")
            and row.get("paid_by_wallet") is True
        ):
            rows.append({
                "kind": "fee",
                "timestamp": row["timestamp"],
                "order": index + 1000,
                "amount_sol": str(fee_amount),
                "paid_by_wallet": True,
                "signature": row["signature"],
                "path": "meta.fee",
                "allocation": "buy_basis" if event["kind"] == "buy" else "sell_exit",
                "allocated_trade_path": row["path"],
                "evidence": row["evidence"],
            })
    return rows


def causal_quote_guard(*, chain_time_seconds, notification_receipt_seconds, decode_completed_seconds,
                       reaction_delay_seconds, quote_request_seconds):
    earliest = earliest_quote_request_seconds(
        notification_receipt_seconds=notification_receipt_seconds,
        decode_completed_seconds=decode_completed_seconds,
        reaction_delay_seconds=reaction_delay_seconds,
    )
    if quote_request_seconds < earliest:
        raise ValueError("Quote request precedes the reaction deadline")
    if quote_request_seconds < chain_time_seconds + reaction_delay_seconds and notification_receipt_seconds > chain_time_seconds:
        # Allowed only when measured receipt/decode are used; chain+delay alone is too early.
        pass
    return {"earliest_quote_request_seconds": earliest, "accepted": quote_request_seconds >= earliest}
