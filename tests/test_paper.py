"""Worked forward-paper controls: no provider traffic or synthetic live claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scanner.paper import (SOL_MINT, apply_quote, begin_quote, create_run,
                           due_quotes, export_run, get_run, pause_run,
                           interrupt_requests, record_signal, request_marks, resume_run,
                           stop_run, validate_settings)
from scanner.storage import Store


WALLET = "11111111111111111111111111111111"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT_B = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
BASE = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def stamp(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "paper")
    yield value
    value.close()


def run(store, **settings):
    return create_run(store, WALLET, {"capital_sol": "2", "entry_sol": "1",
                                    "reaction_delay_seconds": 10,
                                    "adverse_bps": 0, "execution_fee_sol": "0.01",
                                    **settings}, at=stamp(0))


def signal(signature="buy-1", side="buy", seconds=1, mint=MINT, **extra):
    return {"signature": signature, "mint": mint, "side": side,
            "eligible": True, "detected_at": stamp(seconds),
            "decoded_at": stamp(seconds + 1), "decimals": 6,
            "raw_quantity": "999", "block_time": stamp(-100), **extra}


def emit(store, value, event, at=None):
    event = deepcopy(event)
    event.setdefault("evidence_hash", store.archive({"scope": "Synthetic signal mechanics", "signal": event}))
    return record_signal(store, value["id"], event, at=at or event["decoded_at"])


def settle(store, value, output, seconds, action="entry", **extra):
    requests = due_quotes(store, value["id"], at=stamp(seconds))
    request = next(request for request in requests if request["action"] == action)
    dispatched = begin_quote(store, value["id"], request["id"], at=stamp(seconds))
    quote = {"status": "available", "input_mint": dispatched["input_mint"],
             "output_mint": dispatched["output_mint"],
             "in_amount": dispatched["input_amount"], "out_amount": str(output),
             "price_impact_pct": "1", "received_at": stamp(seconds + 1),
             "provider": "synthetic-mechanics", **extra}
    quote["evidence_hash"] = store.archive({"scope": "Synthetic quote mechanics", "quote": quote})
    return apply_quote(store, value["id"], request["id"], quote, at=stamp(seconds + 1))


def test_delayed_quote_cannot_use_leader_time_or_price(store):
    value = run(store)
    value = emit(store, value, signal(leader_price_sol="0.000000001"))
    request = value["quote_requests"][0]
    assert request["due_at"] == stamp(12)  # decoded at 2 + selected delay 10
    assert due_quotes(store, value["id"], at=stamp(11)) == []
    with pytest.raises(ValueError, match="reaction delay"):
        begin_quote(store, value["id"], request["id"], at=stamp(11))
    value = settle(store, value, 100, 20)
    assert value["positions"][0]["raw_units"] == "100"
    assert value["positions"][0]["opened_at"] == stamp(21)
    assert value["cash_lamports"] == "990000000"
    assert value["summary"]["economic_pnl_sol"] is None
    assert "leader_price_sol" not in value["signals"][0]


def test_profitable_looking_leader_can_have_losing_follower_with_costs_once(store):
    value = run(store, adverse_bps=100)
    value = emit(store, value, signal(leader_profit_sol="50"))
    value = settle(store, value, 10000, 12)
    assert value["positions"][0]["raw_units"] == "9900"
    value = emit(store, value, signal("sell-1", "sell", 30))
    value = settle(store, value, 900000000, 41, "exit", observed_pool_fee_sol="0.02")
    # Provider output .9 SOL already includes its pool fees. Haircut .009,
    # additional exit cost .01, plus entry cost 1.01 gives -.129 SOL.
    assert value["summary"]["cash_sol"] == "1.871"
    assert value["summary"]["realised_pnl_sol"] == "-0.129"
    assert value["summary"]["economic_pnl_sol"] == "-0.129"
    assert value["summary"]["closed_positions"] == 1


def test_unavailable_first_sale_keeps_exposure_and_later_sale_cannot_replace_it(store):
    value = run(store)
    value = emit(store, value, signal())
    value = settle(store, value, 10000, 12)
    value = emit(store, value, signal("sell-1", "sell", 30))
    value = settle(store, value, 0, 41, "exit", status="unavailable", reason="no_sell_route")
    value = emit(store, value, signal("sell-2", "sell", 50))
    assert value["signals"][-1]["reason"] == "first_eligible_sale_already_selected"
    assert len([r for r in value["quote_requests"] if r["action"] == "exit"]) == 1
    assert value["positions"][0]["exit_unavailable"] is True
    assert value["summary"]["unavailable_exits"] == 1
    assert value["summary"]["open_positions"] == 1
    assert value["summary"]["economic_pnl_sol"] is None
    assert value["summary"]["complete_observation"] is False


def test_open_losses_are_in_equity_and_unavailable_latest_mark_revokes_old_value(store):
    value = run(store)
    value = emit(store, value, signal())
    value = settle(store, value, 10000, 12)
    value = request_marks(store, value["id"], at=stamp(30))
    value = settle(store, value, 500000000, 30, "mark")
    assert value["summary"]["realised_pnl_sol"] == "0"
    assert value["summary"]["open_pnl_sol"] == "-0.52"
    assert value["summary"]["economic_pnl_sol"] == "-0.52"
    value = request_marks(store, value["id"], at=stamp(40))
    value = settle(store, value, 0, 40, "mark", status="unavailable", reason="unavailable")
    assert value["summary"]["marked_open_value_sol"] is None
    assert value["summary"]["economic_pnl_sol"] is None
    assert value["summary"]["open_cost_sol"] == "1.01"


def test_duplicate_signals_quotes_and_additional_buys_are_idempotent(store):
    value = run(store)
    first = signal()
    value = emit(store, value, first)
    value = emit(store, value, first)
    assert len(value["signals"]) == 1
    assert value["budgets"]["events_used"] == 1
    value = emit(store, value, signal("buy-2", seconds=3))
    assert value["signals"][-1]["reason"] == "already_holding_or_entry_pending"
    value = settle(store, value, 10000, 12)
    request = value["quote_requests"][0]
    prior_cash = value["cash_lamports"]
    value = apply_quote(store, value["id"], request["id"], request["quote"], at=stamp(15))
    assert value["cash_lamports"] == prior_cash
    assert len(value["positions"]) == 1
    assert value["budgets"]["quotes_used"] == 1


def test_leader_exit_before_delayed_entry_cancels_hypothetical_buy(store):
    value = run(store)
    value = emit(store, value, signal())
    value = emit(store, value, signal("sell-1", "sell", 3))
    assert value["signals"][-1]["reason"] == "leader_exited_before_hypothetical_entry"
    assert due_quotes(store, value["id"], at=stamp(20)) == []
    assert value["summary"]["cash_sol"] == "2"


def test_resuming_after_restart_preserves_settings_units_gap_and_no_quote_replay(tmp_path):
    path = tmp_path / "restart"
    first_store = Store(path)
    value = run(first_store)
    settings = deepcopy(value["settings"])
    value = emit(first_store, value, signal())
    value = settle(first_store, value, 2**63 + 37, 12)
    value = emit(first_store, value, signal("sell-1", "sell", 30))
    pending = due_quotes(first_store, value["id"], at=stamp(41))[0]
    begin_quote(first_store, value["id"], pending["id"], at=stamp(41))
    pause_run(first_store, value["id"], at=stamp(42))
    first_store.close()
    second_store = Store(path)
    try:
        recovered = resume_run(second_store, value["id"], at=stamp(100))
        assert recovered["settings"] == settings
        assert recovered["positions"][0]["raw_units"] == str(2**63 + 37)
        assert recovered["positions"][0]["exit_unavailable"] is True
        assert recovered["gaps"][0]["start_at"] == stamp(42)
        assert recovered["gaps"][0]["end_at"] == stamp(100)
        assert recovered["gaps"][0]["backfilled"] is False
        assert due_quotes(second_store, value["id"], at=stamp(100)) == []
        assert recovered["budgets"]["quotes_used"] == 2
    finally:
        second_store.close()


def test_time_quote_and_event_budget_exhaustion_are_explicit(store):
    timed = run(store, max_duration_minutes=1)
    assert get_run(store, timed["id"], at=stamp(60))["stop_reason"] == "duration_budget_exhausted"
    with pytest.raises(ValueError, match="cannot be extended"):
        resume_run(store, timed["id"], at=stamp(61))
    quote_limited = run(store, max_quotes=1)
    quote_limited = emit(store, quote_limited, signal())
    quote_limited = settle(store, quote_limited, 10000, 12)
    quote_limited = request_marks(store, quote_limited["id"], at=stamp(30))
    assert due_quotes(store, quote_limited["id"], at=stamp(30)) == []
    assert get_run(store, quote_limited["id"], at=stamp(30))["stop_reason"] == "quote_budget_exhausted"
    assert get_run(store, quote_limited["id"], at=stamp(30))["summary"]["open_positions"] == 1
    event_limited = run(store, max_events=1)
    emit(store, event_limited, signal())
    event_limited = emit(store, event_limited, signal("extra", seconds=3))
    assert event_limited["stop_reason"] == "event_budget_exhausted"
    assert len(event_limited["signals"]) == 1


def test_pending_entries_reserve_cash_and_position_limit(store):
    value = run(store, max_open_positions=1)
    value = emit(store, value, signal())
    value = emit(store, value, signal("other", seconds=3, mint=MINT_B))
    assert value["signals"][-1]["reason"] == "maximum_open_positions"
    other = run(store, max_open_positions=5)
    other = emit(store, other, signal())
    other = emit(store, other, signal("other", seconds=3, mint=MINT_B))
    assert other["signals"][-1]["reason"] == "insufficient_simulated_cash"


@pytest.mark.parametrize("extra,reason", [
    ({"input_mint": SOL_MINT, "in_amount": "999"}, "quote_input_amount_mismatch"),
    ({"output_mint": SOL_MINT}, "quote_mint_mismatch"),
    ({"price_impact_pct": "6"}, "quote_price_impact_above_preset"),
    ({"out_amount": 1000}, "Raw units"),
    ({"request_started_at": stamp(11)}, "quote_was_not_requested_after_delay"),
])
def test_invalid_or_excessive_quote_cannot_create_position(store, extra, reason):
    value = emit(store, run(store), signal())
    value = settle(store, value, 1000, 12, **extra)
    assert reason in value["quote_requests"][0]["reason"]
    assert value["positions"] == []
    assert value["cash_lamports"] == "2000000000"


@pytest.mark.parametrize("settings", [
    {"entry_sol": 0.1}, {"capital_sol": "NaN"}, {"entry_sol": "0.0000000001"},
    {"max_quotes": True}, {"reaction_delay_seconds": -1}, {"adverse_bps": 5001},
    {"max_duration_minutes": 481}, {"entry_sol": "20", "capital_sol": "10"},
])
def test_settings_are_bounded_and_exact(settings):
    with pytest.raises(ValueError):
        validate_settings(settings)


def test_exports_preserve_immutable_original_settings_and_complete_evidence(store):
    value = run(store)
    value["settings"]["entry_sol"] = "500"
    saved = get_run(store, value["id"], at=stamp(1))
    assert saved["settings"]["entry_sol"] == "1"
    stopped = stop_run(store, value["id"], at=stamp(2))
    assert stopped["status"] == "stopped"
    exported = export_run(store, value["id"])
    assert exported["settings_evidence"]["settings"]["entry_sol"] == "1"
    assert exported["run"]["strategy"] == "fixed-entry-first-sale-v1"
    assert "no signed transaction" in exported["scope"]


def test_stopped_run_can_mark_open_loss_with_no_new_signals_and_deadline_invalidates_current_value(store):
    value = emit(store, run(store, max_duration_minutes=1), signal())
    value = settle(store, value, 10000, 12)
    value = stop_run(store, value["id"], at=stamp(20))
    value = emit(store, value, signal("stopped-buy", seconds=21))
    assert len(value["signals"]) == 1
    value = request_marks(store, value["id"], at=stamp(30))
    value = settle(store, value, 500000000, 30, "mark")
    assert value["status"] == "stopped"
    assert value["summary"]["economic_pnl_sol"] == "-0.52"
    value = get_run(store, value["id"], at=stamp(60))
    assert value["summary"]["economic_pnl_sol"] is None
    assert value["positions"][0]["prior_mark"]["net_value_lamports"] == "490000000"


def test_stopping_inflight_entry_retains_quote_but_does_not_open_position(store):
    value = emit(store, run(store), signal())
    request = begin_quote(store, value["id"], value["quote_requests"][0]["id"], at=stamp(12))
    stop_run(store, value["id"], at=stamp(13))
    quote = {"status": "available", "input_mint": request["input_mint"],
             "output_mint": request["output_mint"], "in_amount": request["input_amount"],
             "out_amount": "100", "price_impact_pct": "1", "received_at": stamp(14)}
    value = apply_quote(store, value["id"], request["id"], quote, at=stamp(14))
    assert value["positions"] == []
    assert value["summary"]["cash_sol"] == "2"
    assert value["quote_requests"][0]["quote_evidence_hash"]
    duplicate = apply_quote(store, value["id"], request["id"], quote, at=stamp(15))
    assert duplicate["quote_requests"][0]["quote_evidence_hash"] == value["quote_requests"][0]["quote_evidence_hash"]


@pytest.mark.parametrize("source", ["settings", "signal", "quote_interpretation", "quote_raw"])
def test_missing_original_sources_revoke_supported_conclusion_without_rewriting_recorded_money(store, source):
    value = emit(store, run(store, execution_fee_sol="0"), signal())
    value = settle(store, value, 10000, 12)
    value = emit(store, value, signal("sell-1", "sell", 30))
    value = settle(store, value, 1200000000, 41, "exit")
    assert value["summary"]["economic_pnl_sol"] == "0.2"
    assert value["summary"]["complete_observation"] is True
    digest = {"settings": value["settings_snapshot_hash"],
              "signal": value["signals"][0]["evidence_hash"],
              "quote_interpretation": value["quote_requests"][-1]["quote_evidence_hash"],
              "quote_raw": value["quote_requests"][-1]["quote"]["evidence_hash"]}[source]
    path = store.path / "evidence" / (digest + ".json.gz")
    original = path.read_bytes()
    path.unlink()
    missing = get_run(store, value["id"], at=stamp(43))
    assert missing["summary"]["economic_pnl_sol"] == "0.2"
    assert missing["summary"]["complete_observation"] is False
    assert missing["summary"]["source_availability"]["state"] == "UNKNOWN"
    assert missing["summary"]["supported_economic_pnl_sol"] is None
    assert missing["copyability"]["status"] == "insufficient_evidence"
    path.write_bytes(original)
    restored = get_run(store, value["id"], at=stamp(44))
    assert restored["summary"]["source_availability"]["state"] == "KNOWN"
    assert restored["summary"]["supported_economic_pnl_sol"] == "0.2"
    assert restored["summary"]["complete_observation"] is True


def test_repeated_pre_entry_exits_exclude_named_strategy_with_primary_timing_evidence(store):
    value = run(store)
    for index in range(2):
        offset = index * 20
        value = emit(store, value, signal(f"buy-{index}", seconds=offset + 1))
        value = emit(store, value, signal(f"sell-{index}", "sell", seconds=offset + 3))
    assert value["copyability"]["status"] == "excluded_by_copy_preset"
    observed = value["risk_observations"][0]
    assert observed["key"] == "leader_exit_before_entry"
    assert observed["state"] == "OBSERVED"
    assert observed["actual"]["count"] == 2
    assert len(observed["evidence"]) == 2
    assert value["copy_research_preset_snapshot"]["version"] == "forward-copy-preset-v1"


def test_multiple_losing_closed_outcomes_exclude_strategy_without_intent_inference(store):
    value = run(store, capital_sol="10", execution_fee_sol="0")
    for index in range(3):
        offset = index * 100
        value = emit(store, value, signal(f"buy-{index}", seconds=offset + 1))
        value = settle(store, value, 10000, offset + 12)
        value = emit(store, value, signal(f"sell-{index}", "sell", seconds=offset + 30))
        value = settle(store, value, 900000000, offset + 41, "exit")
    assert value["summary"]["realised_pnl_sol"] == "-0.3"
    assert value["copyability"]["status"] == "excluded_by_copy_preset"
    observed = next(r for r in value["risk_observations"] if r["key"] == "follower_disadvantage")
    assert observed["actual"]["closed_positions"] == 3
    assert observed["actual"]["losing_positions"] == 3
    assert len(observed["evidence"]) == 6
    assert "does not establish leader intent" in observed["reason"]


def test_no_strategy_activity_and_excluded_only_signals_cannot_be_worth_observing(store):
    value = run(store)
    assert value["copyability"]["status"] == "insufficient_evidence"
    assert value["summary"]["complete_observation"] is False
    assert value["summary"]["supported_performance_state"] == "INCOMPLETE"
    value = emit(store, value, signal(eligible=False, reason="unsupported_settlement"))
    assert value["signals"][0]["decision"] == "excluded"
    assert value["copyability"]["status"] == "insufficient_evidence"
    assert value["summary"]["supported_economic_pnl_sol"] is None


def test_notification_source_loss_revokes_delay_support_and_restore_preserves_numbers(store):
    value = run(store)
    digest = store.archive({"scope": "Synthetic notification mechanics", "detected_at": stamp(1)})
    value = emit(store, value, signal(notification_evidence_hash=digest))
    value = settle(store, value, 10000, 12)
    value = request_marks(store, value["id"], at=stamp(30))
    value = settle(store, value, 500000000, 30, "mark")
    path = store.path / "evidence" / (digest + ".json.gz")
    saved = path.read_bytes()
    path.unlink()
    value = get_run(store, value["id"], at=stamp(32))
    assert value["summary"]["economic_pnl_sol"] == "-0.52"
    assert value["summary"]["source_availability"]["state"] == "UNKNOWN"
    assert value["summary"]["supported_economic_pnl_sol"] is None
    path.write_bytes(saved)
    value = get_run(store, value["id"], at=stamp(33))
    assert value["summary"]["supported_economic_pnl_sol"] == "-0.52"


def test_monitoring_gap_abandons_signal_quotes_without_abandoning_current_marks(store):
    value = emit(store, run(store, capital_sol="10"), signal())
    value = settle(store, value, 10000, 12)
    value = request_marks(store, value["id"], at=stamp(30))
    value = emit(store, value, signal("second-buy", seconds=31, mint=MINT_B))
    value = interrupt_requests(store, value["id"], at=stamp(33))
    entry = next(r for r in value["quote_requests"] if r["mint"] == MINT_B)
    mark = next(r for r in value["quote_requests"] if r["action"] == "mark")
    assert entry["status"] == "interrupted"
    assert mark["status"] == "pending"
    assert due_quotes(store, value["id"], at=stamp(50)) == [mark]


def test_late_quote_response_after_deadline_is_retained_without_spending_simulated_cash(store):
    value = emit(store, run(store, max_duration_minutes=1, reaction_delay_seconds=0), signal(seconds=58))
    request = begin_quote(store, value["id"], value["quote_requests"][0]["id"], at=stamp(59))
    quote = {"status": "available", "input_mint": request["input_mint"],
             "output_mint": request["output_mint"], "in_amount": request["input_amount"],
             "out_amount": "100", "price_impact_pct": "1", "received_at": stamp(61)}
    quote["evidence_hash"] = store.archive({"scope": "Synthetic late quote mechanics", "quote": quote})
    value = apply_quote(store, value["id"], request["id"], quote, at=stamp(61))
    assert value["status"] == "budget_exhausted"
    assert value["quote_requests"][0]["status"] == "cancelled"
    assert value["quote_requests"][0]["quote_evidence_hash"]
    assert value["positions"] == []
    assert value["cash_lamports"] == "2000000000"


def test_missing_settings_source_still_exports_recorded_history_with_unavailable_evidence(store):
    value = run(store)
    digest = value["settings_snapshot_hash"]
    (store.path / "evidence" / (digest + ".json.gz")).unlink()
    exported = export_run(store, value["id"])
    assert exported["settings_evidence"] is None
    assert exported["settings_evidence_availability"]["state"] == "UNKNOWN"
    assert exported["run"]["settings"] == value["settings"]
    assert exported["run"]["cash_lamports"] == "2000000000"
    assert exported["run"]["summary"]["source_availability"]["state"] == "UNKNOWN"


def test_unfundable_modeled_mark_cannot_manufacture_negative_equity_beyond_initial_cash(store):
    value = emit(store, run(store, execution_fee_sol="0.9"), signal())
    value = settle(store, value, 10000, 12)
    assert value["summary"]["cash_sol"] == "0.1"
    value = request_marks(store, value["id"], at=stamp(30))
    value = settle(store, value, 200000000, 30, "mark")
    assert value["quote_requests"][-1]["status"] == "unavailable"
    assert value["quote_requests"][-1]["reason"] == "insufficient_simulated_cash_for_exit_cost"
    assert value["summary"]["economic_pnl_sol"] is None
    assert value["summary"]["cash_sol"] == "0.1"
    assert value["positions"][0]["raw_units"] == "10000"


def test_stop_and_pause_cannot_reopen_exhausted_immutable_quote_budget(store):
    value = emit(store, run(store, max_quotes=1), signal())
    value = settle(store, value, 10000, 12)
    value = request_marks(store, value["id"], at=stamp(30))
    assert value["status"] == "budget_exhausted"
    assert stop_run(store, value["id"], at=stamp(31))["status"] == "budget_exhausted"
    assert pause_run(store, value["id"], at=stamp(32))["status"] == "budget_exhausted"
    with pytest.raises(ValueError, match="cannot be extended"):
        resume_run(store, value["id"], at=stamp(33))


def test_decode_crossing_recorded_monitoring_gap_is_excluded_without_hindsight_entry(store):
    from scanner.paper import record_gap
    value = run(store)
    value = record_gap(store, value["id"], "Disconnected before decoding finished", stamp(2), stamp(20))
    value = emit(store, value, signal(decoded_at=stamp(21)), at=stamp(21))
    assert value["signals"][0]["decision"] == "excluded"
    assert value["signals"][0]["reason"] == "signal_crosses_unobserved_monitoring_gap"
    assert value["quote_requests"] == []
    assert value["cash_lamports"] == "2000000000"


def test_concurrent_quote_reservations_and_responses_charge_cash_and_budget_once(store):
    from concurrent.futures import ThreadPoolExecutor
    value = emit(store, run(store), signal())
    request_id = value["quote_requests"][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        dispatched = list(pool.map(lambda _: begin_quote(store, value["id"], request_id, at=stamp(12)), range(8)))
    assert sum(request is not None for request in dispatched) == 1
    request = next(request for request in dispatched if request is not None)
    quote = {"status": "available", "input_mint": request["input_mint"],
             "output_mint": request["output_mint"], "in_amount": request["input_amount"],
             "out_amount": "10000", "price_impact_pct": "1", "received_at": stamp(13)}
    quote["evidence_hash"] = store.archive({"scope": "Synthetic concurrent quote mechanics", "quote": quote})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: apply_quote(store, value["id"], request_id, quote, at=stamp(13)), range(8)))
    value = get_run(store, value["id"], at=stamp(14))
    assert value["budgets"]["quotes_used"] == 1
    assert value["cash_lamports"] == "990000000"
    assert len(value["positions"]) == 1


def test_quote_begin_at_deadline_persists_expiry_even_when_it_returns_no_dispatch(store):
    value = emit(store, run(store, max_duration_minutes=1), signal())
    request_id = due_quotes(store, value["id"], at=stamp(59))[0]["id"]
    assert begin_quote(store, value["id"], request_id, at=stamp(60)) is None
    saved = store.get("paper_runs", value["id"])
    assert saved["status"] == "budget_exhausted"
    assert saved["quote_requests"][0]["status"] == "cancelled"
    assert saved["budgets"]["quotes_used"] == 0


def test_portfolio_mark_costs_cannot_collectively_borrow_simulated_capital(store):
    value = run(store, capital_sol="3", entry_sol="0.1", execution_fee_sol="0.9")
    value = emit(store, value, signal())
    value = settle(store, value, 10000, 12)
    value = emit(store, value, signal("buy-other", seconds=20, mint=MINT_B))
    value = settle(store, value, 10000, 31)
    assert value["cash_lamports"] == "1000000000"
    value = request_marks(store, value["id"], at=stamp(40))
    value = settle(store, value, 200000000, 40, "mark")
    value = settle(store, value, 200000000, 42, "mark")
    assert value["summary"]["known_marked_open_value_sol"] == "-1.4"
    assert value["summary"]["economic_pnl_sol"] is None
    assert value["summary"]["complete_observation"] is False
    assert "unfunded" in value["summary"]["valuation_reason"]


@pytest.mark.parametrize("entry_already_dispatched", [False, True])
def test_exit_cost_cannot_turn_pending_entry_reservation_into_borrowed_cash(store, entry_already_dispatched):
    value = emit(store, run(store, capital_sol="4", execution_fee_sol="0.9"), signal())
    value = settle(store, value, 10000, 12)
    value = emit(store, value, signal("sell-first", "sell", 20))
    value = emit(store, value, signal("buy-second", seconds=22, mint=MINT_B))
    second = next(r for r in value["quote_requests"] if r["action"] == "entry" and r["mint"] == MINT_B)
    if entry_already_dispatched:
        request = begin_quote(store, value["id"], second["id"], at=stamp(33))
        value = settle(store, value, 100000000, 34, "exit")
        quote = {"status": "available", "input_mint": request["input_mint"],
                 "output_mint": request["output_mint"], "in_amount": request["input_amount"],
                 "out_amount": "10000", "price_impact_pct": "1", "received_at": stamp(36)}
        quote["evidence_hash"] = store.archive({"scope": "Synthetic concurrent cash mechanics", "quote": quote})
        value = apply_quote(store, value["id"], second["id"], quote, at=stamp(36))
    else:
        value = settle(store, value, 100000000, 31, "exit")
        assert begin_quote(store, value["id"], second["id"], at=stamp(33)) is None
        value = get_run(store, value["id"], at=stamp(34))
    assert value["cash_lamports"] == "1300000000"
    assert len(value["positions"]) == 1
    assert value["positions"][0]["status"] == "closed"
    second = next(r for r in value["quote_requests"] if r["id"] == second["id"])
    assert second["status"] == "unavailable"
    assert second["reason"] == "insufficient_simulated_cash_for_entry_cost"
