"""Named regressions for the 2026-10-07 ChatGPT review of PR #6 at 6295021.

Every constructed wallet is SYNTHETIC and must never count as a genuine
research wallet. Zero live provider calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

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
        "completed_episode_ledger": [{"net": "4", "mint": f"M{i}", "unit": "SOL", "close_signature": f"cov-close-{i}"} for i in range(5)],
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
        "completed_episode_ledger": [{"net": "-3.125", "mint": f"M{i}", "unit": "SOL", "close_signature": f"neg-close-{i}"} for i in range(4)],
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
        "completed_episode_ledger": [{"net": "13.74", "mint": f"M{i}", "unit": "USDC", "close_signature": f"usdc-close-{i}"} for i in range(4)],
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


BVZT = "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9"
DQ7N = "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys"
TOKEN_2022_BUYS = {
    BVZT: (
        "4YAVTERNvutrxh2YMCriQgNaS5NwkFewLNTTVKf8htmdvyG2gk1s4kEFdEW17qjbDgVzXrGHVVGK6Fnqb6cscr7H",
        "46LTwehRd9gqRxEQvQCrvHqRPtAAYFmmXucozRpYWnhFkfnV2eZcs7GR5XZQ4brYVmEJkkdMFZVKBdaE5BP1c8L9",
        "5gsBEZxKDdo35atprX2LEqZeeF8dk1ZKVE5hkUAjH9RMeFgZZh3MgAPk6GsWiN99Q2J1Fx2diyxzMs3cWr8MTZEg",
    ),
    DQ7N: (
        "1Y1QbF3ECkgRd91MVVEV4TZW7fmS86e5sgiMDecHKyyap31FxPRt8DMMgbrQiXtjyxZZdW5UKLCVeGS1YpyqKLR",
        "3m8Mv7ubyP6Pw1SPwf2YTchbfU677txE7zzC2iBr4LTi76t6VFHxEgoh7RHNWMD7eyab4zq8yo9kq3vhrfFuFmak",
        "4iEHb4sFwBkibDreePFFNa6Uh2xw4qJ7Jp6dsQGF1sP3bfRPxTm8xYLLkAP92CUwfj23fcpVH3GbCQscWzPsT8iL",
    ),
}
RFQ_SALES = (
    "3otd93M7i4qzYUaXTWWaBnmmhBHisZhW533B9Hiqg1JcmqFrMD5KowYZYDYLFFe37KsJ6RC2ExKjMn1r7c3oCJqd",
    "3kkiuPNLnfD8nMSgaJrHYQPgpB5vwkjpoxbgUcuteEyUwtrJj5GUhw5afAkrQ3Nn1eSkyPB2Rfytv1hQhLsNBEFc",
    "2cdzEPn6uaQr7kzifKhS2RWaJxu84FbvsJxCr4Gi6E1HptX9yuHpQ7W1krBj7rkZpVrQ8EehBW1TJAFHd6Tc9asf",
)
RFQ_FEE_ACCOUNT = "9PnYDCTJ5B4mJJMPvjCZ97L6ZBcti48CYgxv5QU1mV5G"
SWAPTOB = "3uXPRZpMS7LAkhw3q4LXuwXKuxgS7aLfoYw3WGSXALHR5MUFh5ufaSwGi9gueNPHqwk99pTyAXMf56SEnfRakA9e"


def _decode_signature(address, signature):
    from scanner.investigation import decode_supported_swaps
    from scanner.mass_search.canonical_records import canonical_decode_records
    from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
    from tools.independent_episode_audit import _unwrap

    records, _ = load_capture_records(catalog_by_address()[address])
    for record in records:
        raw = _unwrap(record)
        found = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
        if found == signature:
            return decode_supported_swaps(canonical_decode_records([record]), address)
    raise AssertionError(f"missing {signature} for {address}")


def test_token_2022_transfer_fee_bvzt_dq7n_jupiter_buys():
    from scanner.investigation import infer_token_2022_fee_bps, token_2022_ceiling_fee

    assert token_2022_ceiling_fee(109308768417, 100) == 1093087685
    assert infer_token_2022_fee_bps([109308768417, 212654447298], 3219632158) == 100
    for address, signatures in TOKEN_2022_BUYS.items():
        for signature in signatures:
            decoded = _decode_signature(address, signature)
            buys = [row for row in decoded["events"] if row.get("kind") == "buy"]
            assert buys, (address, signature, [row.get("reason") for row in decoded.get("unresolved") or []][:3])
            fee = buys[0].get("token_2022_transfer_fee")
            assert fee, (address, signature, buys[0])
            assert fee["gross"] > fee["net_received"]
            assert fee["withheld"] == fee["gross"] - fee["net_received"]
            assert fee.get("observed") is True
            assert fee.get("transfer_fee_config_established") is False
            assert fee.get("execution_time_mint_config_established") is False
            assert infer_token_2022_fee_bps(fee["inbound_gross_amounts"], fee["withheld"]) == fee["transfer_fee_basis_points"]
            assert str(buys[0].get("quantity_raw")) == str(fee["net_received"])


def test_rfq_fee_fill_bvzt_three_sales():
    from scanner.investigation import RFQ_FEE_FILL_ACCOUNT

    assert RFQ_FEE_FILL_ACCOUNT == RFQ_FEE_ACCOUNT
    for signature in RFQ_SALES:
        decoded = _decode_signature(BVZT, signature)
        sells = [row for row in decoded["events"] if row.get("kind") == "sell"]
        assert sells, (signature, [row.get("reason") for row in decoded.get("unresolved") or []][:3])
        fee = sells[0].get("rfq_platform_fee")
        assert fee, sells[0]
        assert fee["recipient"] == RFQ_FEE_ACCOUNT
        assert fee["pattern"] == "rfq_fill_separate_top_level_transfer_checked"
        assert fee["not_subtracted_again"] is True
        assert sells[0].get("platform_fee_usdc") not in (None, "", "0")


def _load_record(address, signature):
    from scanner.mass_search.canonical_records import canonical_decode_records
    from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
    from tools.independent_episode_audit import _unwrap

    records, _ = load_capture_records(catalog_by_address()[address])
    for record in records:
        raw = _unwrap(record)
        found = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
        if found == signature:
            return record, raw, canonical_decode_records([record])
    raise AssertionError(f"missing {signature} for {address}")


def _rfq_fee_compiled(decoded_records):
    from copy import deepcopy
    from scanner.compiled_instructions import _base58_decode, _base58_encode
    from scanner.investigation import RFQ_FEE_FILL_ACCOUNT

    clone = deepcopy(decoded_records)
    raw = clone[0].get("raw") or clone[0]
    message = ((raw.get("transaction") or {}).get("message") or {})
    keys = list(message.get("accountKeys") or [])
    fee_index = keys.index(RFQ_FEE_FILL_ACCOUNT)
    for ix in message.get("instructions") or []:
        accounts = list(ix.get("accounts") or [])
        if fee_index not in accounts:
            continue
        data = _base58_decode(ix.get("data") or "", "rfq.fee.data", 16)
        if data and data[0] == 12:
            return clone, raw, message, keys, ix, accounts, fee_index, data
    raise AssertionError("compiled RFQ transferChecked not found")


def _assert_rfq_exception_rejected(decoded):
    from scanner.investigation import decode_supported_swaps

    mutated = decode_supported_swaps(decoded, BVZT)
    sells = [row for row in mutated["events"] if row.get("kind") == "sell"]
    reasons = [row.get("reason") or "" for row in mutated.get("unresolved") or []]
    attributed = bool(sells and sells[0].get("rfq_platform_fee"))
    assert attributed is False
    assert (not sells) or any("Unrelated token transfer" in reason for reason in reasons)


def test_unrelated_transfer_guard_still_rejects_non_rfq_outer_owned_transfer():
    from copy import deepcopy
    from scanner.compiled_instructions import _base58_encode
    from scanner.investigation import decode_supported_swaps

    _, _, decoded = _load_record(BVZT, RFQ_SALES[0])
    baseline = decode_supported_swaps(decoded, BVZT)
    assert [row for row in baseline["events"] if row.get("kind") == "sell"][0].get("rfq_platform_fee")

    clone, _raw, _message, keys, ix, accounts, fee_index, data = _rfq_fee_compiled(decoded)
    ix["data"] = _base58_encode(bytes([3]) + data[1:9])
    ix["accounts"] = [accounts[0], fee_index, accounts[3] if len(accounts) > 3 else accounts[-1]]
    _assert_rfq_exception_rejected(clone)

    clone, _raw, _message, keys, ix, accounts, fee_index, _data = _rfq_fee_compiled(decoded)
    keys[fee_index] = "UnrelatedFeeSink11111111111111111111111111"
    _message = ((clone[0].get("raw") or clone[0]).get("transaction") or {}).get("message") or {}
    _message["accountKeys"] = keys
    _assert_rfq_exception_rejected(clone)

    clone, _raw, _message, keys, ix, accounts, fee_index, _data = _rfq_fee_compiled(decoded)
    ix["accounts"] = [fee_index if slot == accounts[0] else slot for slot in accounts]
    _assert_rfq_exception_rejected(clone)

    clone, _raw, message, keys, ix, accounts, fee_index, data = _rfq_fee_compiled(decoded)
    keys.append("UnrelatedOuterDest11111111111111111111111")
    message["accountKeys"] = keys
    message["instructions"].append({
        "programIdIndex": ix.get("programIdIndex"),
        "accounts": [accounts[0], len(keys) - 1, accounts[1], accounts[3] if len(accounts) > 3 else accounts[-1]],
        "data": ix.get("data"),
        "stackHeight": ix.get("stackHeight"),
    })
    _assert_rfq_exception_rejected(clone)


def test_swaptob_decodes_from_official_layout_on_live_fixture():
    from scanner.investigation import OKX_SWAPTOB, decode_supported_swaps
    from scanner.mass_search.canonical_records import canonical_decode_records

    assert OKX_SWAPTOB.hex() == "aa2955b184501f35"
    payload = json.loads(Path("tests/fixtures/live-e2e-phase3/okx-swaptob.json").read_text())
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell")]
    assert trades
    assert trades[0]["venue"] == "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u"
    assert trades[0]["instruction"] == "SwapTob"
    assert trades[0]["quantity_raw"]
    assert trades[0].get("amount_usdc") or trades[0].get("amount_sol")


def test_next_capture_box_driver_emits_supported_gta_request():
    from scanner.mass_search.adapters import SourceError
    from scanner.mass_search.history_ingest import (
        HELIUS_METHOD,
        PROVIDER_SIDE_CUTOFF_UNIX,
        UNSUPPORTED_UNTIL,
        assert_gta_options_not_widened,
        build_historical_gta_options,
        documented_gta_contract,
        load_next_capture_draft,
        provider_side_cutoff_unix,
        serialize_box_driver_next_capture_first_request,
    )

    assert provider_side_cutoff_unix() == PROVIDER_SIDE_CUTOFF_UNIX == 1791206967
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False
    assert "until" not in draft["exact_query"]["params"]
    assert draft["exact_query"]["top_level_until_forbidden"] is True
    assert draft["exact_query"]["params"]["filters"]["blockTime"]["lt"] == 1791206967
    assert draft["request_ceiling_is_not_a_target"] is True
    assert draft["max_dispatched_requests"] == 20
    assert draft["zero_usd_claim"] == "conditional_on_verified_quota_with_overages_disabled"
    assert draft["overages_enabled"] is False
    assert "stop_when_page_unproductive" in draft["stop_conditions"]
    assert "never_stop_because_a_wallet_turned_positive" in draft["stop_conditions"]
    a6ps = next(row for row in draft["allowed_wallets"] if row["address"].startswith("A6PS"))
    assert a6ps["separately_justified"] is True
    assert a6ps["investigation"] == "repeatability_of_concentrated_return"
    assert a6ps["tests"]
    bsn5 = next(row for row in draft["allowed_wallets"] if row["address"].startswith("BSN5"))
    aw6p = next(row for row in draft["allowed_wallets"] if row["address"].startswith("AW6P"))
    cccs = next(row for row in draft["allowed_wallets"] if row["address"].startswith("CccS"))
    pw58 = next(row for row in draft["allowed_wallets"] if row["address"].startswith("58PW"))
    assert "Unsupported unknown/L2" in bsn5["tests"]
    assert "unreviewed System opcode" in aw6p["tests"]
    assert "Not profit backfill" in cccs["tests"]
    assert pw58["initial_pages"] == 0
    assert pw58["decoder_first"] is True
    request = serialize_box_driver_next_capture_first_request()
    assert request["not_a_dispatched_request"] is True
    assert request["draft_enabled"] is False
    assert request["method"] == HELIUS_METHOD
    assert request["params"][0].startswith("gtfo")
    options = request["params"][1]
    assert "until" not in options
    assert options["paginationToken"] == "453163900:357"
    assert options["filters"]["blockTime"] == {"lt": 1791206967}
    assert_gta_options_not_widened(options)
    contract = documented_gta_contract(options)
    assert contract["until_present"] is False
    assert contract["block_time_lt"] == 1791206967
    assert contract["continuation_token"] == "453163900:357"
    built = build_historical_gta_options(
        page_index=1,
        pagination_token="453163900:357",
        block_time_lt=1791206967,
        historical_target=True,
    )
    assert built == options
    with pytest.raises(SourceError) as error:
        build_historical_gta_options(until="2026-10-05T13:29:27Z")
    assert error.value.state == UNSUPPORTED_UNTIL
    armed = json.loads((Path(__file__).resolve().parents[1] / "config/live_authorization.ranked100-depth-biased-next-capture-draft.json").read_text(encoding="utf-8"))
    assert armed["enabled"] is False
