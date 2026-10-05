"""Sampled research mechanics; these development inputs do not prove live profit."""
from copy import deepcopy

import pytest

from scanner.accounting import METHODOLOGY, analyze, evaluate_policy
from scanner.config import STRICT
from scanner.native_cash_observations import VERSION as CASH_VERSION
from scanner.research import summarize_research
from scanner.screening import build_screening, validate_screening_preset
from scanner.wallet_identity import VERSION as IDENTITY_VERSION

HASH = "a" * 64
OTHER = "b" * 64
START, END = "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"


def sample(*, rapid=False, open_position=False, unmatched=False):
    shared = {"mint": "observed-mint", "quantity_raw": "1000", "decimals": 6,
              "classification": "unknown", "paid_by_wallet": True, "fee_sol": "0.01", "evidence": [HASH]}
    events = [{**shared, "kind": "buy", "timestamp": "2026-09-05T00:00:00+00:00",
               "order": 0, "amount_sol": "1", "signature": "development-buy", "path": "instruction.0"},
              {**shared, "kind": "sell", "timestamp": "2026-09-05T00:01:00+00:00" if rapid else "2026-09-05T02:00:00+00:00",
               "order": 1, "amount_sol": "1.2", "signature": "development-sell", "path": "instruction.0"}]
    if open_position:
        events.append({**shared, "mint": "open-mint", "kind": "buy", "timestamp": "2026-09-06T00:00:00+00:00",
                       "order": 2, "amount_sol": "2", "signature": "development-open", "path": "instruction.0"})
    if unmatched:
        events.append({**shared, "mint": "unmatched-mint", "kind": "sell", "timestamp": "2026-09-07T00:00:00+00:00",
                       "order": 3, "amount_sol": "50", "signature": "development-unmatched", "path": "instruction.0"})
    result = analyze(events, START, END, history_complete=False)
    return {"id": "sample-report", "address": "sample-wallet", "source": "live", "methodology": METHODOLOGY,
            "preset": deepcopy(STRICT), "window": {"start": START, "end": END},
            "evidence_status": "partial", **result, **evaluate_policy(result["metrics"], STRICT, evidence_verified=False),
            "events": events, "research": summarize_research(events, START, END),
            "evidence": [{"hash": HASH, "kind": "development-transaction"}], "token_risk": [],
            "coverage": {"transactions": len(events), "pages": 1, "credits": 3,
                         "collection_stop_reason": "Transaction limit reached (20)",
                         "wallet_evidence": {"wallet_identity": {"version": IDENTITY_VERSION, "state": "PASS", "evidence": [HASH],
                            "reason": "Development native signer and current account fixture"}}}}


def test_sample_is_worth_observing_without_relaxing_strict_qualification_and_is_immutable():
    report = sample(unmatched=True, open_position=True)
    before = deepcopy(report)
    value = build_screening(report)
    assert value["result"] == "worth_observing"
    assert not value["strict_qualification"]["qualified"]
    assert value["trading_evidence"]["conditional_matched_lot_profit_sol"] == "0.18"
    assert value["trading_evidence"]["unmatched_sales"] == 1
    assert value["trading_evidence"]["wallet_profit_verified"] is False
    assert value["collection"]["stop_reason"] == "Transaction limit reached (20)"
    exposure = value["trading_evidence"]["open_exposure"][0]
    assert exposure["mint"] == "open-mint" and exposure["quantity_raw"] == "1000"
    assert exposure["remaining_basis_sol"] == "2.01"
    assert exposure["market_value_sol"] is None and exposure["valuation_state"] == "UNKNOWN"
    assert report == before
    report["events"][0]["amount_sol"] = "999"
    assert value["trading_evidence"]["conditional_matched_lot_profit_sol"] == "0.18"


def test_small_sample_has_explicit_continuation_budget_and_no_wallet_profit_badge():
    report = sample()
    value = build_screening(report, {"min_supported_swaps": 5, "continuation_max_transactions": 30,
                                     "continuation_max_credits": 200, "continuation_max_accounts": 8})
    assert value["result"] == "insufficient_evidence"
    assert value["continuation"]["recommended"] is True
    assert value["continuation"]["budget"] == {"max_transactions": 30, "max_credits": 200, "max_accounts": 8}
    assert value["continuation"]["checkpoint_required"] is True
    assert value["preset_snapshot"]["min_supported_swaps"] == 5


def test_import_provenance_does_not_supply_identity_but_server_checked_identity_can():
    report = sample()
    report["coverage"]["wallet_evidence"] = {}
    assert build_screening(report)["result"] == "insufficient_evidence"
    identity = {"state": "PASS", "reason": "Rechecked imported native and current-account sources", "evidence": [OTHER], "address": "sample-wallet"}
    value = build_screening(report, identity=identity)
    assert value["result"] == "worth_observing"
    assert value["identity"]["evidence"] == [OTHER]
    identity["address"] = "different-wallet"
    assert build_screening(report, identity=identity)["result"] == "insufficient_evidence"
    identity.update(address="sample-wallet", evidence=[])
    assert build_screening(report, identity=identity)["identity"]["state"] == "UNKNOWN"


def test_stale_research_or_unlinked_trade_evidence_never_supplies_supported_count_or_profit():
    report = sample()
    report["research"]["version"] = "obsolete"
    value = build_screening(report)
    assert value["result"] == "insufficient_evidence"
    assert value["trading_evidence"]["conditional_matched_lot_profit_sol"] is None
    report = sample()
    report["events"][0]["evidence"] = [OTHER]
    assert build_screening(report)["trading_evidence"]["supported_swaps"] == 1
    report = sample()
    report["events"].append(deepcopy(report["events"][0]))
    assert build_screening(report)["trading_evidence"]["supported_swaps"] == 2


def test_early_exit_exclusion_uses_observed_timing_and_its_own_frozen_preset():
    report = sample(rapid=True)
    before = deepcopy(report["preset"])
    excluded = build_screening(report)
    assert excluded["result"] == "excluded_by_preset"
    reason = next(row for row in excluded["reasons"] if row["key"] == "rapid_first_sales")
    assert reason["state"] == "FAIL" and reason["actual"] == "100" and reason["evidence"] == [HASH]
    assert build_screening(report, {"max_rapid_sale_pct": "100"})["result"] == "worth_observing"
    assert report["preset"] == before
    assert excluded["preset_snapshot"]["max_rapid_sale_pct"] == "50"


def test_risk_exclusion_requires_linked_primary_control_evidence_and_explains_capability():
    report = sample()
    gate = {"state": "FAIL", "detail": "Active authority can freeze token accounts", "actual": "authority", "evidence": [OTHER]}
    report["token_risk"] = [{"mint": "observed-mint", "gates": {"freeze_authority": gate}, "findings": []}]
    value = build_screening(report)
    assert value["result"] == "worth_observing"
    observation = next(row for row in value["risk_observations"] if row["key"] == "freeze_authority")
    assert observation["state"] == "UNKNOWN" and observation["actual"] is None
    gate["evidence"] = [HASH]
    value = build_screening(report)
    assert value["result"] == "excluded_by_preset"
    assert "freeze token accounts" in value["reason"]
    assert build_screening(report, {"exclude_active_freeze_authority": False})["result"] == "worth_observing"
    assert all(row["state"] == "UNKNOWN" for row in value["risk_observations"] if row["key"] in ("creator_links", "follower_exploitation", "forward_copy_outcomes"))
    assert "score" not in value and "safe" not in value


def test_missing_episode_evidence_stays_in_timing_population_and_open_exposure():
    report = sample(rapid=True, open_position=True)
    unknown = deepcopy(report["research"]["episodes"][0])
    unknown.update(id="unsupported-slow", mint="unsupported-slow", first_sale_hours="2", evidence=[OTHER])
    report["research"]["episodes"].append(unknown)
    report["research"]["episodes"][1]["evidence"] = [OTHER]
    value = build_screening(report)
    assert value["trading_evidence"]["early_exits"]["rapid_first_sales"]["state"] == "UNKNOWN"
    assert not any(row["key"] == "rapid_first_sales" and row["state"] == "FAIL" for row in value["reasons"])
    exposure = value["trading_evidence"]["open_exposure"][0]
    assert exposure["mint"] == "open-mint" and exposure["quantity_raw"] is None
    assert exposure["quantity_state"] == "UNKNOWN"


def test_direct_native_relationship_is_observed_without_asserting_capital_or_common_control():
    report = sample()
    report["coverage"]["wallet_evidence"]["native_cash_observations"] = {
        "version": CASH_VERSION, "transactions": {"development-transfer": {"failed": False, "movements": [
            {"source": "funding-wallet", "destination": "sample-wallet", "lamports": "1513840", "direction": "in",
             "raw_paths": ["transaction.message.instructions.1"], "check": {"state": "PASS", "evidence": [HASH]}}]}}}
    value = build_screening(report)
    observation = next(row for row in value["risk_observations"] if row["key"] == "direct_native_transfer")
    assert observation["actual"]["lamports"] == "1513840"
    assert observation["relationship"] == "direct_transfer_only"
    assert "common control are not established" in observation["reason"]
    report["coverage"]["wallet_evidence"]["native_cash_observations"]["transactions"]["development-transfer"]["movements"][0]["check"]["evidence"] = [OTHER]
    assert not any(row["key"] == "direct_native_transfer" for row in build_screening(report)["risk_observations"])


def test_missing_collection_reason_is_visible_and_negative_conditional_results_can_fail_optional_preset():
    report = sample()
    del report["coverage"]["collection_stop_reason"]
    report["research"]["conditional_observed_lot_profit_sol"] = "-0.5"
    value = build_screening(report, {"require_positive_conditional_profit": True})
    assert value["result"] == "excluded_by_preset"
    assert "not retained" in value["collection"]["stop_reason"]
    assert value["trading_evidence"]["conditional_matched_lot_profit_sol"] == "-0.5"
    report["source"] = "demo"
    assert build_screening(report)["result"] == "insufficient_evidence"


def test_mass_search_subset_cannot_become_worth_observing_or_match():
    report = sample()
    report["source"] = "mass-search"
    report["policy"] = "UNRESOLVED"
    identity = {"state": "PASS", "reason": "Rechecked imported native and current-account sources",
                "evidence": [HASH], "address": "sample-wallet"}
    value = build_screening(report, identity=identity)
    assert value["result"] == "insufficient_evidence"
    assert value["label"] == "Insufficient evidence"
    assert value["source"] == "mass-search"
    live = next(row for row in value["reasons"] if row["key"] == "live_source")
    assert live["state"] == "UNKNOWN"
    assert live["actual"] == "mass-search"
    assert "reconstructed-subset" in live["reason"]
    assert "MATCH" in live["reason"]
    assert value["strict_qualification"]["qualified"] is False
    assert value["strict_qualification"]["financial_policy"] == "UNRESOLVED"
    assert value["result"] != "worth_observing"


@pytest.mark.parametrize("preset", [{"unknown": True}, {"min_supported_swaps": True}, {"max_rapid_sale_pct": "101"},
                                    {"exclude_active_mint_authority": 1}, {"continuation_max_credits": 0}])
def test_invalid_screening_or_unbounded_budget_settings_are_rejected(preset):
    with pytest.raises(ValueError):
        validate_screening_preset(preset)
