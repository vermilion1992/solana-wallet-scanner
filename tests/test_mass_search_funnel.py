"""Mass-search funnel: decisions, metrics, universe, reconstruction and safety."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scanner.config import LIMITS, STRICT
from scanner.mass_search.adapters import BirdeyeTraderAdapter, FixtureTraderAdapter, SourceError, parse_trader_row
from scanner.mass_search.capability import (
    access_blocker,
    documented_birdeye_traders,
    redact_secrets,
    validate_live_authorization,
)
from scanner.mass_search.forward import overlap_note, proportional_exit, simulate_fixed_entry_first_sale
from scanner.mass_search.metrics import (
    build_metric,
    combined_economics,
    compare_to_threshold,
    concentration,
    earliest_quote_request_seconds,
    fifo_sale_results,
    four_week_consistency,
    material_exit_v1,
    median_hold_hours,
    transfer_sale_outcome,
    unavailable_exit,
)
from scanner.mass_search.plan import STRICT_PRESET_SNAPSHOT, assert_strict_preset_unchanged, load_default_plan, validate_mass_plan
from scanner.mass_search.schema import MASS_UNIVERSE_CAPACITY
from scanner.mass_search.service import MassSearchService, causal_quote_guard
from scanner.mass_search.triage import conserve_counts, evaluate_forward_select, evaluate_triage
from scanner.mass_search.universe import ingest_page, page_summaries, synthetic_address
from scanner.storage import QuotaExceeded, Store

CASES = json.loads((Path(__file__).resolve().parents[1] / "work_packages/mass_wallet_search_v1/fixtures/acceptance_cases.json").read_text())
WINDOW = {"start_inclusive": "2026-01-01T00:00:00Z", "end_exclusive": "2026-01-31T00:00:00Z"}


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def case(identifier):
    return next(item for item in CASES["cases"] if item["id"] == identifier)


def known_pnl(candidate, value, unit="USD"):
    return {
        "provider_realized_pnl": build_metric(
            metric_key="provider_realized_pnl", candidate_id=candidate, value=value, unit=unit,
            state="KNOWN", basis="PROVIDER_REPORTED", window=WINDOW, population="provider_summary",
            population_count=1, observed_at="2026-10-05T00:00:00Z", evidence_sha256=["a" * 64],
            missing_dependencies=[], source_provider="fixture",
        )
    }


def test_strict_preset_snapshot_matches_repository_constant():
    assert STRICT == STRICT_PRESET_SNAPSHOT
    assert assert_strict_preset_unchanged()["min_profit_sol"] == "5"
    with pytest.raises(ValueError, match="auto-relax"):
        validate_mass_plan({"selection": {"auto_relax_filters": True}})


def test_missing_zero_and_negative_profit_are_distinct(store):
    plan = load_default_plan()
    candidate = {"candidate_id": "solana:missing"}
    missing = evaluate_triage(candidate, {}, plan)
    assert missing["result"] == "DEFERRED"
    zero = evaluate_triage(candidate, known_pnl("solana:missing", "0"), plan)
    assert zero["result"] == "PROMOTED"
    assert "known_zero_reported_pnl" in zero["reason_codes"]
    negative = evaluate_triage(candidate, known_pnl("solana:missing", "-2"), plan)
    assert negative["result"] == "PROMOTED"
    assert "known_negative_reported_pnl_ranked" in negative["reason_codes"]


def test_usd_metric_is_not_converted_to_sol_strict():
    expected = case("currency_mismatch")["expected"]
    metric = known_pnl("solana:x", "1000", "USD")["provider_realized_pnl"]
    result = compare_to_threshold(metric, "5", "SOL")
    assert result["state"] == expected["strict_comparison_state"]
    assert result.get("convert_at_current_price") is False


def test_provider_trade_count_is_only_a_proxy():
    expected = case("provider_count_proxy")["expected"]
    plan = load_default_plan()
    metrics = known_pnl("solana:x", "10")
    metrics["provider_trade_count"] = build_metric(
        metric_key="provider_trade_count", candidate_id="solana:x", value="20", unit="count",
        state="KNOWN", basis="PROVIDER_REPORTED", window=WINDOW, population="provider_summary",
        population_count=1, observed_at="2026-10-05T00:00:00Z", evidence_sha256=["a" * 64],
        missing_dependencies=[], source_provider="fixture",
    )
    decision = evaluate_triage({"candidate_id": "solana:x"}, metrics, plan)
    assert "provider_trade_count_queue_priority_only" in decision["reason_codes"]
    assert expected["can_use_as_preliminary_queue_priority"] is True
    assert expected["strict_position_count_state"] == "UNKNOWN"


def test_high_profit_cannot_override_unknown_exit():
    plan = load_default_plan()
    metrics = known_pnl("solana:x", "9999")
    decision = evaluate_forward_select({"candidate_id": "solana:x"}, metrics, plan)
    assert decision["result"] == "DEFERRED"
    assert "high_reported_pnl_cannot_override_unknown_exit" in decision["reason_codes"]


def test_stage_conservation_and_budget_deferral():
    expected = case("stage_conservation")["expected"]
    summary = conserve_counts(1000, 200, 650, 100, 50)
    assert summary["next_stage_input"] == expected["next_stage_input"]
    assert summary["run_complete"] is expected["run_complete"]
    service_plan = load_default_plan()
    from scanner.mass_search.triage import apply_stage_cap
    decisions = [{"candidate_id": f"solana:{i}", "result": "PROMOTED", "reason_codes": [],
                  "policy_version": "Mass research v1", "metric_versions": "v",
                  "_priority": (0, 0, -i, 0, f"solana:{i}")} for i in range(8)]
    capped = apply_stage_cap(decisions, service_plan["stage_workload_maxima_not_permissions"]["forward_watch_candidates"])
    assert sum(row["result"] == "PROMOTED" for row in capped) == 5
    assert sum(row["result"] == "DEFERRED" and "budget_stage_cap" in row["reason_codes"] for row in capped) == 3
    assert sum(row["result"] == "REJECTED" for row in capped) == 0


def test_dust_tail_fifo_and_material_exit_independent_of_production_helpers():
    from decimal import Decimal

    fixture = case("fees_and_dust_tail")
    unit_cost = (Decimal("1") + Decimal("0.01")) / Decimal("100")
    hand_basis = [
        format(Decimal("50") * unit_cost, "f").rstrip("0").rstrip("."),
        format(Decimal("45") * unit_cost, "f").rstrip("0").rstrip("."),
        format(Decimal("5") * unit_cost, "f").rstrip("0").rstrip("."),
    ]
    hand_nets = [
        format(Decimal("0.8") - Decimal(hand_basis[0]) - Decimal("0.005"), "f").rstrip("0").rstrip("."),
        format(Decimal("0.72") - Decimal(hand_basis[1]) - Decimal("0.005"), "f").rstrip("0").rstrip("."),
        format(Decimal("0.08") - Decimal(hand_basis[2]) - Decimal("0.005"), "f").rstrip("0").rstrip("."),
    ]
    hand_total = format(sum((Decimal(item) for item in hand_nets), Decimal("0")), "f").rstrip("0").rstrip(".")
    assert hand_basis == ["0.505", "0.4545", "0.0505"]
    assert hand_nets == ["0.29", "0.2605", "0.0245"]
    assert hand_total == "0.575"
    worksheet = fifo_sale_results(fixture["inputs"]["events"])
    timing = material_exit_v1(fixture["inputs"]["events"])
    assert worksheet["sale_fifo_basis_sol"] == hand_basis == fixture["expected"]["sale_fifo_basis_sol"]
    assert worksheet["sale_net_profit_sol"] == hand_nets == fixture["expected"]["sale_net_profit_sol"]
    assert worksheet["total_profit_sol"] == hand_total == fixture["expected"]["total_profit_sol"]
    assert timing["first_sale_seconds"] == 20 == fixture["expected"]["first_sale_seconds"]
    assert timing["exit_50_seconds"] == 20 == fixture["expected"]["exit_50_seconds"]
    assert timing["exit_90_seconds"] == 30 == fixture["expected"]["exit_90_seconds"]
    assert timing["final_hold_seconds"] == 172800 == fixture["expected"]["final_hold_seconds"]
    assert timing["quantity_weighted_exit_seconds"] == fixture["expected"]["quantity_weighted_exit_seconds"]
    assert timing["exit_90_seconds"] < timing["final_hold_seconds"]


def test_later_buy_moves_material_exit_and_unknown_transfer_revokes_it():
    first_leg = [
        {"kind": "buy", "seconds_from_start": 0, "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0"},
        {"kind": "sell", "seconds_from_start": 10, "units": "90", "consideration_sol": "1", "wallet_fee_sol": "0"},
    ]
    scaled = first_leg + [
        {"kind": "buy", "seconds_from_start": 20, "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0"},
    ]
    without_scale = material_exit_v1(first_leg)
    with_scale = material_exit_v1(scaled)
    assert without_scale["exit_90_seconds"] == 10
    assert with_scale["exit_90_seconds"] is None
    assert with_scale["acquired_units"] == "200"
    unknown = material_exit_v1(first_leg, transfers_unknown=True)
    assert unknown["state"] == "UNKNOWN"
    assert unknown["exit_90_seconds"] is None
    assert "transfer_or_unknown_quantity" in unknown["missing_dependencies"]


def test_unknown_transfer_basis_keeps_sale_and_fee():
    fixture = case("unknown_transfer_basis")
    result = transfer_sale_outcome(
        sale_proceeds_sol=fixture["inputs"]["sale_proceeds_sol"],
        fee_sol=fixture["inputs"]["fee_sol"],
        basis_sol=fixture["inputs"]["basis_sol"],
    )
    assert result == fixture["expected"]


def test_closed_winners_do_not_erase_open_losses():
    fixture = case("closed_winners_open_losses")
    combined = combined_economics(closed_net=fixture["inputs"]["closed_net_profit_sol"],
                                  known_open=fixture["inputs"]["known_open_pnl_sol"])
    assert combined == fixture["expected"]["combined_pnl_sol"]


def test_median_hold_is_not_the_mean():
    fixture = case("median_not_average")
    result = median_hold_hours(fixture["inputs"]["eligible_closed_hold_hours"])
    assert result["value"] == fixture["expected"]["median_hold_hours"]
    assert result["population_count"] == fixture["expected"]["population_count"]


def test_four_week_consistency_uses_independent_weeks():
    fixture = case("weekly_consistency")
    result = four_week_consistency(fixture["inputs"]["complete_independent_week_net_sol"])
    assert result["positive_weeks"] == fixture["expected"]["positive_weeks"]
    assert result["four_week_net"] == fixture["expected"]["four_week_net_sol"]
    assert result["overlapping_windows_used"] is False
    assert four_week_consistency(["1", None, "2", "3"])["state"] == "UNKNOWN"


def test_largest_winner_stress_uses_two_denominators():
    fixture = case("largest_winner_stress")
    result = concentration(fixture["inputs"]["per_mint_net_profit_sol"])
    assert result["net_profit"] == fixture["expected"]["net_profit_sol"]
    assert result["net_without_largest_winner"] == fixture["expected"]["net_without_largest_winner_sol"]
    assert result["denominators_interchangeable"] is False


def test_causal_delay_and_unavailable_exit():
    delay = case("causal_delay")
    earliest = earliest_quote_request_seconds(
        notification_receipt_seconds=delay["inputs"]["notification_receipt_seconds"],
        decode_completed_seconds=delay["inputs"]["decode_completed_seconds"],
        reaction_delay_seconds=delay["inputs"]["reaction_delay_seconds"],
    )
    assert earliest == delay["expected"]["earliest_quote_request_seconds"]
    with pytest.raises(ValueError, match="reaction deadline"):
        causal_quote_guard(chain_time_seconds=0, notification_receipt_seconds=3, decode_completed_seconds=4,
                           reaction_delay_seconds=60, quote_request_seconds=60)
    missing = case("unavailable_exit")
    result = unavailable_exit(open_units=missing["inputs"]["open_units"], exit_quote_available=False,
                              last_mark_sol=missing["inputs"]["last_mark_sol"])
    assert result["closed_units"] == missing["expected"]["closed_units"]
    assert result["supported_liquidation_value_sol"] is None
    assert result["use_last_mark_as_realized_exit"] is False


def test_forward_cash_duplicate_and_overlap_controls():
    first = simulate_fixed_entry_first_sale(
        capital_sol="10", entry_sol="0.1", open_positions=0, max_open=5,
        notification_receipt_seconds=3, decode_completed_seconds=4, reaction_delay_seconds=60,
        quote_request_seconds=64, quote_available=True, exit_quote_available=False, remaining_units="10",
    )
    assert first["accepted"] is True
    assert first["exit"]["supported_liquidation_value_sol"] is None
    unfunded = simulate_fixed_entry_first_sale(
        capital_sol="0.05", entry_sol="0.1", open_positions=0, max_open=5,
        notification_receipt_seconds=3, decode_completed_seconds=4, reaction_delay_seconds=60,
        quote_request_seconds=64, quote_available=True, exit_quote_available=True,
    )
    assert unfunded["reason"] == "unfunded_entry"
    early = simulate_fixed_entry_first_sale(
        capital_sol="10", entry_sol="0.1", open_positions=0, max_open=5,
        notification_receipt_seconds=3, decode_completed_seconds=4, reaction_delay_seconds=60,
        quote_request_seconds=10, quote_available=True, exit_quote_available=True,
    )
    assert early["reason"] == "quote_before_deadline"
    unknown = proportional_exit(sold_units="50", pre_sale_inventory=None, follower_units="10")
    assert unknown["state"] == "UNKNOWN"
    overlap = overlap_note({"mintA": ["w1", "w2"], "mintB": ["w3"]})
    assert overlap["independent_validations"] is False


def test_memberships_survive_duplicate_addresses(store):
    service = MassSearchService(store)
    run = service.create_run()
    address = synthetic_address(7)
    page = {
        "source_id": "fixture-traders", "state": "AUTHORIZED_AVAILABLE", "evidence_sha256": "b" * 64,
        "raw_count": 3, "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-31T00:00:00Z",
        "rows": [
            parse_trader_row({"address": address, "realized_pnl": "4", "trade_count": 21, "rank": 1},
                             field_map=documented_birdeye_traders()["field_map"], source_id="token-a",
                             page=0, offset=0, fetch_timestamp="t0"),
            parse_trader_row({"address": address, "realized_pnl": "4", "trade_count": 21, "rank": 8},
                             field_map=documented_birdeye_traders()["field_map"], source_id="token-b",
                             page=1, offset=100, fetch_timestamp="t1"),
            {"valid": False, "reason": "invalid_address"},
        ],
    }
    ingested = ingest_page(store, run["run_id"], page)
    assert ingested["unique_added"] == 1
    assert ingested["duplicate_rows"] == 1
    assert ingested["invalid_rows"] == 1
    with store.lock:
        memberships = store.db.execute("SELECT source_id FROM candidate_memberships WHERE run_id=?", (run["run_id"],)).fetchall()
    assert {row[0] for row in memberships} == {"token-a", "token-b"}


def test_bulk_capacity_does_not_raise_legacy_caps(store):
    service = MassSearchService(store)
    run = service.create_run()
    page = {
        "source_id": "fixture-traders", "state": "AUTHORIZED_AVAILABLE", "evidence_sha256": "c" * 64,
        "raw_count": 25, "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-31T00:00:00Z",
        "rows": [parse_trader_row({"address": synthetic_address(i), "realized_pnl": "1", "trade_count": 20},
                                  field_map=documented_birdeye_traders()["field_map"], source_id="fixture-traders",
                                  page=0, offset=0, fetch_timestamp="t") for i in range(25)],
    }
    ingested = ingest_page(store, run["run_id"], page)
    assert ingested["unique_added"] == 25
    assert ingested["legacy_candidate_cap"] == 20
    assert LIMITS["candidate_cap"] == 20
    assert LIMITS["deep_audit_cap"] == 5
    assert MASS_UNIVERSE_CAPACITY == 10000


def test_decimal_sort_is_numeric_not_lexicographic(store):
    service = MassSearchService(store)
    run = service.create_run()
    values = ["-2", "-10", "0.01", "0.1", "9", "10"]
    rows = []
    for index, value in enumerate(values):
        rows.append(parse_trader_row({"address": synthetic_address(index + 100), "realized_pnl": value, "trade_count": 20},
                                    field_map=documented_birdeye_traders()["field_map"], source_id="fixture-traders",
                                    page=0, offset=0, fetch_timestamp="t"))
    ingest_page(store, run["run_id"], {
        "source_id": "fixture-traders", "state": "AUTHORIZED_AVAILABLE", "evidence_sha256": "d" * 64,
        "raw_count": len(rows), "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-31T00:00:00Z",
        "rows": rows,
    })
    page = page_summaries(store, run["run_id"], sort_metric="provider_realized_pnl", limit=10)
    ordered = [item["sort_value"] for item in page["items"]]
    assert ordered == ["10", "9", "0.1", "0.01", "-2", "-10"]


def test_entitlement_failure_is_not_an_empty_success(store):
    adapter = BirdeyeTraderAdapter()
    with pytest.raises(SourceError) as error:
        adapter._authorized_entry({"schema_version": "live-research-authorization-v1", "enabled": False}, store)
    assert error.value.state == "UNAUTHORIZED"
    with pytest.raises(ValueError, match="empty-success"):
        ingest_page(store, "missing", {"state": "ENTITLEMENT_BLOCKED", "rows": []})


def test_authorization_example_is_not_a_grant():
    example = json.loads((Path(__file__).resolve().parents[1] / "work_packages/mass_wallet_search_v1/config/live_authorization.example.json").read_text())
    checked = validate_live_authorization(example)
    assert checked["enabled"] is False
    assert access_blocker()["max_additional_spend_usd"] == "0"


def test_redaction_and_schema_drift_keep_raw_unknown():
    raw = parse_trader_row({"address": synthetic_address(3), "mystery_score": 99, "api_key": "secret-value"},
                           field_map=documented_birdeye_traders()["field_map"], source_id="birdeye-traders",
                           page=0, offset=0, fetch_timestamp="t")
    assert "mystery_score" in raw["unreviewed_fields"]
    assert redact_secrets({"X-API-KEY": "abcd1234", "items": [1]})["X-API-KEY"] == "[REDACTED]"


def test_vertical_slice_and_refilter_zero_network(store):
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    events = case("fees_and_dust_tail")["inputs"]["events"]
    events = [{**event, "address": synthetic_address(1)} for event in events]
    service = MassSearchService(store)
    result = service.vertical_slice(events=events, corpus_kind="SYNTHETIC")
    assert result["external_requests"] == 0
    assert result["setup_pilot"]["remaining"] == 0
    assert result["run"]["universe"]["unique_candidates"] == 1
    report = result["reconstruction"]["report"]
    assert report["worksheet"]["total_profit_sol"] == "0.575"
    assert report["material_exit"]["exit_90_seconds"] == 30
    child = service.refilter(result["run"]["run_id"])
    assert child["parent_run_id"] == result["run"]["run_id"]
    assert child["stages"]["triage"]["input"] == 1
    assert child["universe"]["unique_candidates"] == 1
    child_page = service.page_candidates(child["run_id"], stage="triage", limit=10)
    assert child_page["total"] == 1
    assert child_page["items"][0]["sort_value"] is not None
    assert store.usage("helius", "setup-pilot", 200)["used"] == 200
    assert STRICT["min_profit_sol"] == "5"


def test_synthetic_cannot_claim_live_benchmark():
    expected = case("synthetic_cannot_be_live")["expected"]
    assert expected["real_search_benchmark_state"] == "INCOMPLETE"
    assert expected["profitable_wallets_established"] == 0


def test_resume_keeps_decisions_and_work_is_idempotent(store):
    service = MassSearchService(store)
    run = service.create_run()
    adapter = FixtureTraderAdapter([[{"address": synthetic_address(2), "realized_pnl": "3", "trade_count": 22}]])
    service.acquire_from_adapter(run["run_id"], adapter, target_unique=1)
    first = service.evaluate_stage(run["run_id"], "triage")
    service.pause(run["run_id"])
    service.resume(run["run_id"])
    second = service.evaluate_stage(run["run_id"], "triage")
    assert first["summary"] == second["summary"]
    work = service.record_work(run["run_id"], "triage")
    again = service.record_work(run["run_id"], "triage")
    assert again["idempotent"] is True
    assert again["work_id"] == work["work_id"]


def test_quota_crash_paths_do_not_reset_setup_pilot(store):
    reserved = store.reserve("helius", "getTransaction", 30, "setup-pilot", 200)
    service = MassSearchService(store)
    released = service.recover_reservation(reserved, dispatched=False)
    assert released["released"] is True
    dispatched = store.reserve("helius", "getTransaction", 30, "setup-pilot", 200)
    store.dispatch(dispatched)
    charged = service.recover_reservation(dispatched, dispatched=True, archived=True)
    assert charged["charged"] is True
    with pytest.raises(QuotaExceeded):
        store.reserve("birdeye", "trader_gainers_losers", 6, "cycle", 5)
    assert store.usage("helius", "setup-pilot", 200)["used"] == 30


def test_local_refilter_scale_keeps_legacy_caps(store):
    service = MassSearchService(store)
    result = service.local_scale_benchmark(rows=200, warmups=1, measured=2, page_size=50)
    assert result["unique_candidates"] == 200
    assert result["external_requests"] == 0
    assert result["legacy_candidate_cap"] == 20
    assert result["median_ms"] >= 0
