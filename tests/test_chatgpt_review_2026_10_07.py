"""Named regressions for the 2026-10-07 ChatGPT review of PR #6 at 6295021.

Every constructed wallet is SYNTHETIC and must never count as a genuine
research wallet. Zero live provider calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from scanner.investigation import _message_signers
from scanner.mass_search.qualification_gates import (
    ACCOUNTING_POLICY_VERSION,
    CROSS_CURRENCY_SENSITIVITY,
    allocate_verified_costs,
    amounts_agree,
    compute_audit_fingerprint,
    even_sample_median,
    is_synthetic_case,
    mandatory_coverage_gate,
    mark_synthetic,
    tolerance_text,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
    qualification_level,
    sensitivity_sign_flips,
)
from scanner.mass_search.verified_costs import classify_cost_role, classify_native_withdrawal
from scanner.mass_search.workflow import coverage_eligibility


def _synthetic(payload, reason):
    return mark_synthetic(payload, reason=reason)


def _clean_coverage():
    return {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}}


def test_stale_audit_does_not_attach():
    report = {
        "address": "SynthStaleAudit11111111111111111111111111",
        "events": [],
        "wallet_completed_episodes": 3,
        "completed_episode_net": "10",
        "completed_episode_net_unit": "SOL",
        "completed_episode_ledger": [
            {"mint": "M1", "close_signature": "sig-a", "net": "4", "unit": "SOL"},
            {"mint": "M2", "close_signature": "sig-b", "net": "3", "unit": "SOL"},
            {"mint": "M3", "close_signature": "sig-c", "net": "3", "unit": "SOL"},
        ],
        "window": {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
        "record_breakdown": _clean_coverage(),
        "worksheet": {"total_profit_sol": "10", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "capture_sha256": "aaa111",
        "corpus_kind": "GENUINE_REPLAY",
        "synthetic": True,
        "label": "SYNTHETIC — stale-audit fingerprint mismatch, not a genuine research wallet",
        "not_a_genuine_research_wallet": True,
    }
    current = compute_audit_fingerprint(report)
    stale = {
        "status": "independently_audited",
        "independently_audited": True,
        "independently_audited_episode_net": "999",
        "independently_audited_episode_net_unit": "SOL",
        "app_completed_episode_net": "999",
        "app_completed_episode_net_unit": "SOL",
        "content_fingerprint": {
            **current,
            "fingerprint": "0" * 64,
            "raw_capture_hashes": ["bbbbbb-old-capture"],
            "accounting_policy_version": "old-policy",
        },
    }
    report["independent_audit"] = stale
    profile = build_research_profile(report, filters=default_filters())
    assert profile["audit_fingerprint"]["fingerprint"] != "0" * 64
    assert profile["audit_fingerprint"]["accounting_policy_version"] == ACCOUNTING_POLICY_VERSION
    assert independently_audited(report, profile) is False
    assert profile["completed_episode_net"] != "999"
    assert Decimal(str(profile["completed_episode_net"])) == Decimal("10")
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert is_synthetic_case(report, profile) is True
    assert profile["not_a_genuine_research_wallet"] is True


def test_99_5_count_80_value_does_not_qualify():
    report = _synthetic({
        "address": "SynthCoverage995080111111111111111111111",
        "events": [],
        "wallet_completed_episodes": 5,
        "completed_episode_net": "20",
        "completed_episode_net_unit": "SOL",
        "completed_episode_ledger": [{"net": "4", "mint": f"M{i}", "unit": "SOL"} for i in range(5)],
        "record_breakdown": {
            "unsupported_swap_share_in_window": {
                "by_count": "0.005",
                "by_consideration": {"SOL": "0.20"},
            }
        },
        "worksheet": {"total_profit_sol": "20", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
        "corpus_kind": "SYNTHETIC",
    }, "99.5% count / 80% value must not qualify")
    profile = build_research_profile(report, filters=default_filters())
    gate = mandatory_coverage_gate(report, profile)
    assert Decimal(str(gate["coverage_count_share"])) == Decimal("0.995")
    assert Decimal(str(gate["coverage_value_share"])) == Decimal("0.80")
    assert gate["passed"] is False
    judged = coverage_eligibility(report, profile)
    assert judged["status"] != "provisional_eligible"
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert profile["qualification_level"]["level"] != "stronger_research_shortlist"
    assert profile["not_a_genuine_research_wallet"] is True


def test_20_episode_3_mint_one_day_burst_fails_stronger_shortlist():
    day = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    ledger = []
    events = []
    for index in range(20):
        mint = f"BurstMint{index % 3}11111111111111111111111111"
        opened = int(day.timestamp()) + index * 60
        closed = opened + 30
        ledger.append({
            "net": "1",
            "mint": mint,
            "unit": "SOL",
            "day": "2026-09-20",
            "opened_at": opened,
            "closed_at": closed,
            "close_signature": f"burst-close-{index}",
        })
        events.append({
            "kind": "buy", "mint": mint, "units": "1", "signature": f"burst-buy-{index}",
            "timestamp": opened, "consideration_sol": "1",
        })
        events.append({
            "kind": "sell", "mint": mint, "units": "1", "signature": f"burst-close-{index}",
            "timestamp": closed, "consideration_sol": "2",
        })
    report = _synthetic({
        "address": "SynthOneDayBurst1111111111111111111111111",
        "events": events,
        "wallet_completed_episodes": 20,
        "completed_episode_ledger": ledger,
        "completed_episode_net": "20",
        "completed_episode_net_unit": "SOL",
        "record_breakdown": _clean_coverage(),
        "worksheet": {"total_profit_sol": "20", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
        "corpus_kind": "SYNTHETIC",
    }, "20-episode 3-mint one-day burst")
    profile = build_research_profile(report, filters=default_filters())
    assert profile["trading_activity"]["active_trading_days"] == 1
    assert profile["trading_activity"]["span_days"] == 0
    assert profile["candidate_assessment"]["active_trading_days_state"] != "NOT_EVALUATED"
    assert profile["candidate_assessment"]["active_trading_days"] == 1
    assert profile["concentration_detail"]["distinct_tokens"] == 3
    assert profile["qualification_level"]["level"] != "stronger_research_shortlist"
    assert profile["not_a_genuine_research_wallet"] is True


def test_positive_worksheet_negative_episodes_does_not_qualify():
    report = _synthetic({
        "address": "SynthWorksheetVsEpisode111111111111111111",
        "events": [],
        "wallet_completed_episodes": 4,
        "completed_episode_net": "-12.5",
        "completed_episode_net_unit": "SOL",
        "completed_episode_ledger": [{"net": "-3.125", "mint": f"M{i}", "unit": "SOL"} for i in range(4)],
        "record_breakdown": _clean_coverage(),
        "worksheet": {"total_profit_sol": "88.25", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
        "corpus_kind": "SYNTHETIC",
    }, "positive worksheet with negative completed episodes")
    profile = build_research_profile(report, filters=default_filters())
    assert Decimal(str(profile["scoped_pnl"])) == Decimal("88.25")
    assert Decimal(str(profile["completed_episode_net"])) == Decimal("-12.5")
    assert profile["worksheet_episode_bridge"]["worksheet_is_not_qualifying"] is True
    judged = qualification_level(report, profile)
    assert judged["level"] != "provisional_research_lead"
    assert judged["positive_completed_episode_net"] is False
    assert judged["worksheet_is_not_qualifying"] is True
    assert profile["not_a_genuine_research_wallet"] is True


def test_cross_currency_sensitivity_blocks_lead():
    report = _synthetic({
        "address": "SynthUsdcSensitivity111111111111111111111",
        "events": [],
        "wallet_completed_episodes": 4,
        "completed_episode_net": "54.96",
        "completed_episode_net_unit": "USDC",
        "completed_episode_net_vector": {"USDC": "54.96", "SOL": "-0.02"},
        "completed_episode_ledger": [{"net": "13.74", "mint": f"M{i}", "unit": "USDC"} for i in range(4)],
        "sensitivity_unverified_debits_sol": "0.5",
        "record_breakdown": {
            "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"USDC": "0"}},
        },
        "worksheet": {"total_profit_usdc": "54.96", "settlement_asset": "USDC", "unresolved_basis_sales": 0},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
        "corpus_kind": "SYNTHETIC",
    }, "USDC settlement cannot establish SOL-cost sensitivity")
    profile = build_research_profile(report, filters=default_filters())
    result = sensitivity_sign_flips(report, profile)
    assert result == CROSS_CURRENCY_SENSITIVITY
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert profile["qualification_level"]["sensitivity_sign_flip"] == CROSS_CURRENCY_SENSITIVITY
    assert "USDC" in (profile.get("completed_episode_net_vector") or {})
    judged = coverage_eligibility(report, profile)
    assert judged["dependency_unresolved_costs"] is True
    assert profile["not_a_genuine_research_wallet"] is True


def test_even_sample_median_uses_mean_of_two_central_values():
    assert even_sample_median([1, 2, 3, 4]) == Decimal("2.5")
    assert even_sample_median([10, 1, 3]) == Decimal("3")


def test_asset_specific_atomic_tolerances():
    assert amounts_agree("1.000000001", "1.000000003", "SOL") is True
    assert amounts_agree("1.000000001", "1.000000004", "SOL") is False
    assert amounts_agree("1.000001", "1.000003", "USDC") is True
    assert amounts_agree("1.000001", "1.000004", "USDC") is False
    assert amounts_agree("1.000001", "1.000003", "SOL") is False
    assert tolerance_text("SOL") == "2 lamports"
    assert tolerance_text("USDC") == "2 USDC base units"


def test_message_signers_header_cross_check_rejects_conflicting_flags():
    keys = ["Signer111111111111111111111111111111111111", "Other1111111111111111111111111111111111111"]
    header = {
        "numRequiredSignatures": 1,
        "numReadonlySignedAccounts": 0,
        "numReadonlyUnsignedAccounts": 1,
    }
    matching = [
        {"pubkey": keys[0], "signer": True, "writable": True},
        {"pubkey": keys[1], "signer": False, "writable": False},
    ]
    assert _message_signers({"accountKeys": matching, "header": header}, keys) == {keys[0]}
    conflicting = [
        {"pubkey": keys[0], "signer": False, "writable": True},
        {"pubkey": keys[1], "signer": True, "writable": False},
    ]
    assert _message_signers({"accountKeys": conflicting, "header": header}, keys) == set()
    compiled = _message_signers({"accountKeys": keys, "header": header}, keys)
    assert compiled == {keys[0]}


def test_proven_platform_fee_is_a_cost_unexplained_transfer_is_not():
    assert classify_cost_role("RandomDest11111111111111111111111111111111", transfer=True) == "unexplained_transfer"
    assert classify_native_withdrawal("RandomDest11111111111111111111111111111111") == "unresolved_debit"
    assert classify_cost_role(
        "JupFee111111111111111111111111111111111111",
        proven_from_layout=True,
        transfer=True,
    ) == "proven_router_or_platform_fee"
    assert classify_cost_role(
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        transfer=True,
    ) == "verified_tip"
    assert classify_cost_role(None, wallet_paid_network=True, transfer=False) == "network_plus_priority_fee"
    assert classify_cost_role("Anyone", transaction_failed=True, transfer=True) == "failed_tx_transfer_excluded"
    allocation = allocate_verified_costs([
        {"signature": "closed", "economic_role": "proven_router_or_platform_fee", "sol": "0.01", "episode_closed": True},
        {"signature": "closed", "economic_role": "proven_router_or_platform_fee", "sol": "0.01", "episode_closed": True},
        {"signature": "fail", "economic_role": "network_plus_priority_fee", "sol": "0.000005", "transaction_failed": True},
        {"signature": "mystery", "economic_role": "unexplained_transfer", "sol": "0.5"},
        {"signature": "tip-other", "economic_role": "verified_tip", "sol": "0.002", "allocate_to": "other_activity"},
    ])
    assert allocation["no_double_subtraction"] is True
    assert allocation["unexplained_transfers_are_not_fees"] is True
    assert Decimal(str(allocation["closed_episodes_sol"])) == Decimal("0.01")
    assert Decimal(str(allocation["failed_attempts_sol"])) == Decimal("0.000005")
    assert Decimal(str(allocation["sensitivity_unexplained_transfers_sol"])) == Decimal("0.5")
    assert Decimal(str(allocation["other_activity_sol"])) == Decimal("0.002")


def test_synthetic_cases_never_count_as_genuine_research_wallets():
    report = _synthetic({
        "address": "SynthOnly111111111111111111111111111111111",
        "events": [],
        "wallet_completed_episodes": 0,
    }, "empty synthetic marker")
    profile = build_research_profile(report, filters=default_filters())
    assert profile["corpus_kind"] == "SYNTHETIC"
    assert profile["not_a_genuine_research_wallet"] is True
    assert profile["synthetic"] is True
