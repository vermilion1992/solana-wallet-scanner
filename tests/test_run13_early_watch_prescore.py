"""Run-13 blockers, early_watch, cheap pre-score, auth-16. Offline. Gates stay fail-closed."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.mass_search.adapters import SourceError
from scanner.mass_search.labels import QUALIFICATION_LEVELS, research_label_tables, wallet_status_fields
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_16,
    DRAFT_REL_16,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    ROOT,
    _account_spend,
    _empty_state,
    bind_run_spend,
    hard_stop_if_needed,
    parse_run_caps,
    remaining_caps,
)
from scanner.mass_search.qualification_gates import (
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
    raw_economic_keys_for_tx as app_raw_keys,
)
from scanner.mass_search.readable_first import (
    DROP,
    KEEP,
    estimate_full_gate_prescore,
    estimate_sample_round_trips,
    funnel_report,
    merge_funnel_walks,
    rank_by_nansen_pnl,
    walk_ranked,
)
from scanner.mass_search.workflow import apply_local_filters
from scanner.mass_search.research_profile import (
    _headline_including_dropped_losers,
    apply_headline_losing_pnl,
    app_omitted_losing_episodes,
    build_research_profile,
    default_filters,
    early_watch_label,
    independently_audited,
    qualification_level,
)
from scanner.mass_search.seed_sources import (
    DISCOVERY_LIQUID_MINTS,
    MEW_MINT,
    PINNED_MINT_SOURCES,
    RULE_A_MAX_AVG_TRADES_PER_DAY,
    RULE_A_MAX_TOKENS,
    RULE_A_MIN_TOKENS,
    nansen_infra_label_drop,
)
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report
import tools.independent_episode_audit as auditor


def _replay_eligible(completed):
    report = _eligible_report()
    report["completed_episode_ledger"] = list(report["completed_episode_ledger"][:completed])
    report["wallet_completed_episodes"] = completed
    report["completed_episode_net"] = str(3 * completed)
    report["events"] = [
        row for row in report["events"]
        if any(row.get("mint") == item["mint"] for item in report["completed_episode_ledger"])
    ]
    from scanner.mass_search.qualification_gates import compute_audit_fingerprint, component_bridge, ACCOUNTING_POLICY_VERSION
    ledger = report["completed_episode_ledger"]
    fingerprint = compute_audit_fingerprint(report, episodes=ledger)
    episodes = []
    for row in ledger:
        auditor_row = {
            "mint": row["mint"],
            "close_signature": row["close_signature"],
            "acquisition": row["acquisition"],
            "proceeds": row["proceeds"],
            "costs": row["costs"],
            "net": row["net"],
        }
        episodes.append({
            "mint": row["mint"],
            "close_signature": row["close_signature"],
            "component_bridge": component_bridge(row, auditor_row, row.get("unit") or "SOL"),
        })
    net = str(3 * completed) if completed else "0"
    report["independent_audit"] = {
        "status": "independently_audited",
        "independently_audited": True,
        "independently_audited_episode_net": net,
        "independently_audited_episode_net_unit": "SOL",
        "app_completed_episode_net": net,
        "app_completed_episode_net_unit": "SOL",
        "content_fingerprint": fingerprint,
        "accounting_policy_version": ACCOUNTING_POLICY_VERSION,
        "one_to_one_membership": True,
        "episodes": episodes,
        "component_bridges": [item["component_bridge"] for item in episodes],
    }
    profile = build_research_profile(report, filters=default_filters())
    return report, profile


def test_9dk_shape_includes_omitted_losing_episode():
    clean = "4003.43"
    dropped = [{"net_profit": "-251.13", "settlement_asset": "USDC", "mint": "Loser9Dk", "reason": "app_omitted_losing_flatten"}]
    headline, unit, included = _headline_including_dropped_losers(clean, "USDC", dropped)
    assert unit == "USDC"
    assert included
    assert abs(Decimal(headline) - Decimal("3752.30")) <= Decimal("0.01")
    profile = {"completed_episode_net": clean, "completed_episode_net_unit": "USDC", "completed_episode_net_vector": {"USDC": clean}}
    apply_headline_losing_pnl(profile, {}, headline, unit)
    assert abs(Decimal(profile["completed_episode_net"]) - Decimal("3752.30")) <= Decimal("0.01")
    assert profile["scoped_pnl_unit"] == "USDC"


def test_9bfcmf_shape_includes_unclosed_losing_inventory():
    mapped = [
        {"kind": "buy", "mint": "OpenLoser", "units": "100", "signature": "b1", "timestamp": 1_780_000_000,
         "consideration_usdc": "211422", "settlement_asset": "USDC", "settlement_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
        {"kind": "sell", "mint": "ClosedWin", "units": "1", "signature": "s1", "timestamp": 1_780_000_100,
         "consideration_usdc": "5421", "settlement_asset": "USDC"},
        {"kind": "buy", "mint": "ClosedWin", "units": "1", "signature": "b2", "timestamp": 1_779_000_000,
         "consideration_usdc": "1", "settlement_asset": "USDC"},
    ]
    report = {"window": {"start": "2026-01-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"}}
    omitted = app_omitted_losing_episodes(mapped, report, ledger=[{"mint": "ClosedWin", "close_signature": "s1"}])
    assert omitted
    assert omitted[0]["reason"] == "unflattened_losing_inventory"
    headline, unit, included = _headline_including_dropped_losers("5421", "USDC", omitted)
    assert included
    assert Decimal(headline) < 0
    assert abs(Decimal(headline) - (Decimal("5421") - Decimal("211422"))) <= Decimal("1")


def test_d13_1_run_caps_bind_at_the_lifetime_choke_point():
    config = {
        "caps": {
            "birdeye_requests": 40, "birdeye_units": 1400,
            "helius_requests": 4000, "helius_units": 40000,
            "nansen_requests": 300, "nansen_units": 600,
        },
        "run_caps": parse_run_caps("helius_requests=6,helius_units=600"),
    }
    state = _empty_state(config)
    bind_run_spend(config, state)
    for _ in range(6):
        hard_stop_if_needed(config, state["spend"], provider="helius", units=10, phase=2, phase_spend=state["phase_spend"])
        _account_spend(state, provider="helius", units=10, phase=2)
    assert state["run_spend"]["helius_requests"] == 6
    with pytest.raises(SourceError) as raised:
        hard_stop_if_needed(config, state["spend"], provider="helius", units=10, phase=2, phase_spend=state["phase_spend"])
    assert raised.value.state == "CAP_EXCEEDED"
    left = remaining_caps(config, state["spend"], run_spend=state["run_spend"])
    assert left["helius_requests"] == 0


def _token_to_token_tx(wallet, sold, bought):
    return {
        "transaction": {
            "signatures": ["tok2toksig111111111111111111111111111111111111"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"],
                "instructions": [{
                    "programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                    "accounts": [0, 1],
                    "data": "route",
                }],
            },
        },
        "meta": {
            "err": None,
            "logMessages": ["Program JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4 invoke [1]", "Instruction: Route"],
            "preTokenBalances": [
                {"owner": wallet, "mint": sold, "uiTokenAmount": {"amount": "100", "decimals": 6}},
                {"owner": wallet, "mint": bought, "uiTokenAmount": {"amount": "0", "decimals": 6}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": sold, "uiTokenAmount": {"amount": "0", "decimals": 6}},
                {"owner": wallet, "mint": bought, "uiTokenAmount": {"amount": "80", "decimals": 6}},
            ],
            "preBalances": [1_000_000_000, 1, 1],
            "postBalances": [999_000_000, 1, 1],
        },
        "blockTime": 1735689600,
    }


def test_7jrzax_token_to_token_app_and_auditor_agree():
    wallet = "7jrZAxBotCountWallet111111111111111111111"
    sold = "SoldMint11111111111111111111111111111111"
    bought = "BoughtMint111111111111111111111111111111"
    raw = _token_to_token_tx(wallet, sold, bought)
    app_n = app_raw_keys(raw, wallet)
    aud_n = auditor.raw_economic_keys_for_tx(raw, wallet)
    assert app_n == aud_n
    assert app_n == 2
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 15


@pytest.mark.parametrize("n", [1, 2])
def test_early_watch_one_or_two_episodes_passing_everything_else(n):
    report, profile = _replay_eligible(n)
    level = profile["qualification_level"]
    assert independently_audited(report, profile) is True
    assert level["level"] == "early_watch"
    assert level["label"] == early_watch_label(n)
    assert level["lead_eligible"] is False
    assert level["proven"] is False
    assert level["PRODUCT_READY"] is False
    fields = wallet_status_fields(report, profile)
    assert fields["qualification_level"] == "early_watch"
    assert "Early watch – not proven" in (fields["blocking_reason"] or "")
    tables = research_label_tables([{
        "address": profile.get("address"),
        "qualification_level": "early_watch",
        "coverage_status": "provisional_eligible",
    }])
    assert "early_watch" in QUALIFICATION_LEVELS
    assert tables["qualification_level_counts"]["early_watch"] == 1


def test_early_watch_other_gates_block():
    report, profile = _replay_eligible(2)
    blocked = dict(profile)
    blocked["unresolved_basis_sales"] = 1
    judged = qualification_level(report, blocked)
    assert judged["level"] != "early_watch"
    unprofitable = dict(profile)
    unprofitable["completed_episode_net"] = "-1"
    unprofitable["completed_episode_ledger"] = [
        {**row, "net": "-1"} for row in (profile.get("completed_episode_ledger") or [])
    ]
    unprofitable["headline_includes_losing_episodes"] = True
    judged = qualification_level(report, unprofitable)
    assert judged["level"] != "early_watch"
    unaudited = dict(profile)
    unaudited_report = dict(report)
    unaudited_report["independent_audit"] = {"status": "not_independently_audited", "independently_audited": False}
    judged = qualification_level(unaudited_report, unaudited)
    assert judged["level"] != "early_watch"
    bot = dict(profile)
    bot["max_economic_trades_in_one_day"] = 16
    bot["max_economic_trades_on"] = "2024-12-31"
    judged = qualification_level(report, bot)
    assert judged["level"] != "early_watch"
    thin = dict(report)
    relevant = dict((thin.get("result_relevant") or thin.get("record_breakdown") or {}).get("result_relevant") or thin.get("result_relevant") or {})
    if not relevant:
        relevant = {"version": "result-relevant-v1", "size": 10, "denominator": 10, "empty": False}
    relevant = dict(relevant)
    relevant["count_share"] = "0.50"
    relevant["value_share"] = "0.50"
    thin["result_relevant"] = relevant
    breakdown = dict(thin.get("record_breakdown") or {})
    breakdown["result_relevant"] = relevant
    thin["record_breakdown"] = breakdown
    judged = qualification_level(thin, profile)
    assert judged["level"] != "early_watch"


def test_three_episodes_take_the_normal_path():
    _report, profile = _replay_eligible(3)
    assert profile["qualification_level"]["level"] == "provisional_research_lead"
    assert profile["qualification_level"]["level"] != "early_watch"


def test_zero_episodes_never_early_watch():
    _report, profile = _replay_eligible(0)
    assert profile["qualification_level"]["level"] == "insufficient_evidence"
    assert profile["qualification_level"]["level"] != "early_watch"


def test_only_early_watch_filter_keeps_that_tier():
    kept = apply_local_filters(
        [
            {"address": "ew", "qualification_level": {"level": "early_watch"}, "shortlisted": True, "capture_available": True, "trade_count": 3},
            {"address": "lead", "qualification_level": {"level": "provisional_research_lead"}, "shortlisted": True, "capture_available": True, "trade_count": 3},
            {"address": "none", "qualification_level": {"level": "insufficient_evidence"}, "shortlisted": True, "capture_available": True, "trade_count": 3},
        ],
        {"provider_proxy": {"only_early_watch": True}},
    )
    assert [row["address"] for row in kept] == ["ew"]


def test_funnel_report_has_its_own_early_watch_section():
    report = funnel_report(
        {"kept": [{"address": "ew", "qualification_level": {"level": "early_watch", "label": early_watch_label(2)}}], "dropped": [], "deferred_unreadable": [], "unscreened": []},
        extra={"early_watch": [{"address": "ew", "label": early_watch_label(2)}]},
    )
    assert report["early_watch"]
    assert report["early_watch"][0]["address"] == "ew"
    from scanner.mass_search.readable_first import format_funnel_markdown
    text = format_funnel_markdown(report)
    assert "Early watch – not proven" in text


def test_prescore_never_passes_and_skips_zero_round_trips():
    wallet = "PreScoreWallet11111111111111111111111112"
    score = estimate_full_gate_prescore([], wallet)
    assert score["never_passes"] is True
    assert score["skip_deep_pull"] is True
    assert score["PRODUCT_READY"] is False
    assert int(score["expected_completed_episodes"] or 0) == 0


def test_prescore_ranks_by_pass_probability_then_pnl():
    rows = [
        {"address": "low", "estimated_pass_probability": "0.2", "realized_pnl_usd": "999"},
        {"address": "high", "estimated_pass_probability": "0.8", "realized_pnl_usd": "1"},
        {"address": "mid", "estimated_pass_probability": "0.8", "realized_pnl_usd": "50"},
    ]
    ranked = rank_by_nansen_pnl(rows)
    assert [row["address"] for row in ranked] == ["mid", "high", "low"]


def test_skip_deep_pull_is_not_kept():
    walked = walk_ranked([
        {"address": "skip", "funnel_decision": KEEP, "skip_deep_pull": True, "skip_deep_pull_reason": "sample_no_round_trips"},
        {"address": "keep", "funnel_decision": KEEP, "estimated_pass_probability": "0.9"},
    ], n=2)
    kept = [row["address"] for row in walked["kept"]]
    dropped = [row["address"] for row in walked["dropped"]]
    assert "skip" not in kept
    assert "skip" in dropped
    assert "keep" in kept


def test_resumed_walk_accumulates():
    first = walk_ranked([{"address": "a", "funnel_decision": KEEP}], n=1)
    second = walk_ranked([{"address": "b", "funnel_decision": KEEP}], n=1)
    merged = merge_funnel_walks(first, second)
    assert {row["address"] for row in merged["kept"]} == {"a", "b"}
    assert merged["accumulated"] is True


def test_mew_and_built_in_mints_have_sources():
    assert MEW_MINT == "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScDhz"
    assert MEW_MINT in DISCOVERY_LIQUID_MINTS
    assert set(DISCOVERY_LIQUID_MINTS) == set(PINNED_MINT_SOURCES)
    for mint, (ticker, source) in PINNED_MINT_SOURCES.items():
        assert mint
        assert ticker
        assert source.startswith("https://")


def test_rule_a_defaults_are_discovery_filters():
    assert RULE_A_MAX_AVG_TRADES_PER_DAY == Decimal("5")
    assert RULE_A_MIN_TOKENS == 2
    assert RULE_A_MAX_TOKENS == 30
    hit = nansen_infra_label_drop({"labels": ["Market Maker", "lp"]})
    assert hit and hit["dropped"] is True


def test_auth16_draft_hash_and_ceilings():
    path = ROOT / DRAFT_REL_16
    draft = path.read_text(encoding="utf-8")
    import json
    payload = json.loads(draft)
    assert payload["enabled"] is False
    assert payload["authorization_id"] == AUTHORIZATION_ID_16
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_16] == digest
    nansen = next(row for row in payload["providers"] if row["provider_id"] == "nansen")
    helius = next(row for row in payload["providers"] if row["provider_id"] == "helius")
    birdeye = next(row for row in payload["providers"] if row["provider_id"] == "birdeye")
    assert nansen["max_requests"] == 300
    assert nansen["max_units"] == 600
    assert helius["max_requests"] == 10000
    assert helius["max_units"] == 80000
    assert birdeye["max_requests"] == 0
    assert HARD_CEILINGS["helius_requests"] == 10000
    assert HARD_CEILINGS["helius_units"] == 80000
    assert HARD_CEILINGS["nansen_requests"] == 300
    assert HARD_CEILINGS["nansen_units"] == 600


def test_offline_replay_command_is_wired():
    from scanner.mass_search.offline_replay import discover_cached_wallets, replay_cached_pages
    assert callable(discover_cached_wallets)
    assert callable(replay_cached_pages)
    script = ROOT / "scripts/offline_replay_cached.py"
    assert script.is_file()
