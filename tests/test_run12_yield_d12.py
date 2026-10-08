"""Run-12 yield + parked D12 items. Offline. Gates stay fail-closed."""
from __future__ import annotations

import base64
from decimal import Decimal
from hashlib import sha256

import pytest

from scanner.investigation import JUPITER, WSOL, _anchor, _route
from scanner.mass_search.capability import _forbidden_signing_or_swap_op, validate_live_authorization
from scanner.mass_search.live_e2e import parse_run_caps, plan_request_counts, validate_config
from scanner.mass_search.readable_first import (
    DEFER_UNREADABLE,
    KEEP,
    SAMPLE_PAGES_DEFAULT,
    estimate_sample_round_trips,
    merge_funnel_reports,
    rank_by_nansen_pnl,
    readable_first_plan,
    sample_readable_shares,
    walk_ranked,
    write_funnel_report,
)
from scanner.mass_search.seed_sources import (
    DISCOVERY_LIQUID_MINTS,
    HELIUS_SIGNATURES_HISTORY_CAP,
    helius_signatures_prescreen,
    select_discovery_tokens,
    select_tgm_wallets,
    tgm_pre_rank_key,
    tgm_row_address,
    tgm_row_metrics,
)
from scanner.mass_search.live_e2e import DRAFT_PATH, TRIAGE_SAMPLES as LIVE_TRIAGE


WALLET = "YieldWallet11111111111111111111111111112"
MINT = "YieldMint1111111111111111111111111111112"
TOKEN_ATA = "YieldTokAta11111111111111111111111111112"
USDC_ATA = "YieldUsdcAta1111111111111111111111111112"
SOL_ATA = "YieldWsolAta1111111111111111111111111112"
POOL_TOK = "YieldPoolTok1111111111111111111111111112"
POOL_USDC = "YieldPoolUsdc111111111111111111111111112"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
UNKNOWN = "UnkYieldProgram1111111111111111111111111"


def test_d12_1_getsignatures_is_allowlisted():
    assert _forbidden_signing_or_swap_op("getSignaturesForAddress") is False
    assert _forbidden_signing_or_swap_op("getsignaturesforaddress") is False
    assert _forbidden_signing_or_swap_op("signTransaction") is True
    assert _forbidden_signing_or_swap_op("signAndSend") is True
    assert _forbidden_signing_or_swap_op("swap") is True
    grant = {
        "schema_version": "live-research-authorization-v1",
        "enabled": True,
        "authorization_id": "d12-1",
        "authorized_by_user_at": "2026-10-08T00:00:00Z",
        "expires_at": "2026-12-01T00:00:00Z",
        "max_additional_spend_usd": "0",
        "overages_enabled": False,
        "allow_paid_upgrade": False,
        "allow_signing_or_submission": False,
        "providers": [{
            "provider_id": "helius",
            "allowed_operations": ["getTransactionsForAddress", "getSignaturesForAddress"],
            "billing_unit": "helius_credit",
            "existing_plan_confirmed": True,
            "remaining_quota_confirmed_at": "2026-10-08T00:00:00Z",
            "cycle_start": "2026-10-07T00:00:00Z",
            "cycle_end_exclusive": "2026-12-01T00:00:00Z",
            "max_requests": 10,
            "max_units": 100,
            "max_concurrency": 1,
            "max_duration_seconds": 60,
        }],
    }
    checked = validate_live_authorization(grant)
    assert checked["enabled"] is True


def test_d12_4_trader_address_and_pre_rank():
    row = {
        "trader_address": "DtqQuuSca14Avfr1FopSaBmxPBQagRrWLMh5BqSi3vqc",
        "pnl_usd_realised": "3273.84",
        "nof_trades": 6,
    }
    assert tgm_row_address(row).startswith("DtqQuu")
    metrics = tgm_row_metrics(row)
    assert Decimal(str(metrics["realized_pnl_usd"])) == Decimal("3273.84")
    assert tgm_pre_rank_key({"realized_pnl_usd": "10", "n_trades": 1}) < tgm_pre_rank_key(
        {"realized_pnl_usd": "1", "n_trades": 99}
    )
    tokens = select_discovery_tokens(limit=5)
    assert tokens[0] == DISCOVERY_LIQUID_MINTS[0]
    assert len(tokens) == 5
    seen = {}
    first = select_tgm_wallets([row], token=tokens[0], seen=seen, billing={"X-Nansen-Credits-Cost": "5"})
    again = select_tgm_wallets([row], token=tokens[1], seen=seen, billing={"X-Nansen-Credits-Cost": "5"})
    assert len(first) == 1
    assert again == []
    assert first[0]["billing"]["X-Nansen-Credits-Cost"] == "5"
    assert seen[first[0]["address"]]["source_tokens"] == [tokens[0], tokens[1]]


def test_d12_3_parse_run_caps():
    assert parse_run_caps("") is None
    assert parse_run_caps("helius_units=4000,nansen_requests=80") == {
        "helius_units": 4000,
        "nansen_requests": 80,
    }
    with pytest.raises(Exception):
        parse_run_caps("not-a-pair")


def test_d12_5_plan_uses_triage_pages_and_skips_dex_when_off():
    assert LIVE_TRIAGE == 3
    plan = readable_first_plan(
        discovered_wallets=10,
        dex_pages=0,
        sample_pages=3,
        token_count=12,
        token_pnl_calls=12,
        deep_n=4,
    )
    sample = next(stage for stage in plan["stages"] if stage["stage"] == "decodability_sample")
    bot = next(stage for stage in plan["stages"] if stage["stage"] == "bot_prescreen")
    assert sample["helius_requests"] == 10 * 3
    assert bot["nansen_requests"] == 0
    assert SAMPLE_PAGES_DEFAULT == 2


def test_d12_7_history_exactly_at_cap_is_deferred():
    rows = [{"signature": f"sig{i}", "blockTime": 1_780_000_000 + i} for i in range(HELIUS_SIGNATURES_HISTORY_CAP)]
    screen = helius_signatures_prescreen(rows, history_cap=HELIUS_SIGNATURES_HISTORY_CAP)
    assert screen["deferred"] is True
    assert screen["passed"] is False


def test_d12_8_funnel_report_accumulates(tmp_path):
    first = walk_ranked([
        {"address": "keep1", "funnel_decision": KEEP, "realized_pnl_usd": "10"},
        {"address": "defer1", "funnel_decision": DEFER_UNREADABLE, "realized_pnl_usd": "9"},
    ], n=2)
    write_funnel_report(tmp_path, first)
    second = walk_ranked([
        {"address": "keep2", "funnel_decision": KEEP, "realized_pnl_usd": "8"},
        {"address": "keep1", "funnel_decision": KEEP, "realized_pnl_usd": "10"},
    ], n=2)
    merged = write_funnel_report(tmp_path, second)
    assert merged["accumulated"] is True
    assert "keep1" in merged["kept"]
    assert "keep2" in merged["kept"]
    prior = {"kind": "readable-first-funnel-v1", "kept": ["a"], "deferred_unreadable": [], "dropped": [], "unscreened": [], "examined": 1, "dominant_unreadable_programs": []}
    incoming = {"kind": "readable-first-funnel-v1", "kept": ["b"], "deferred_unreadable": [], "dropped": [], "unscreened": [], "examined": 2, "dominant_unreadable_programs": []}
    out = merge_funnel_reports(prior, incoming)
    assert out["kept"] == ["a", "b"]
    assert out["examined"] == 3


def _swap(*, signature, token_pre, token_post, quote_mint=USDC, quote_ata=USDC_ATA, quote_pre, quote_post, program=JUPITER):
    return {
        "signature": signature,
        "blockTime": 1_780_000_000,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [WALLET, TOKEN_ATA, quote_ata, POOL_TOK, POOL_USDC, program, TOKEN],
                "instructions": [{"programId": program, "accounts": [WALLET, TOKEN_ATA, quote_ata], "data": "route"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "postBalances": [1_999_995_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
                {"accountIndex": 2, "mint": quote_mint, "owner": WALLET, "uiTokenAmount": {"amount": quote_pre, "decimals": 9 if quote_mint == WSOL else 6}},
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}},
                {"accountIndex": 2, "mint": quote_mint, "owner": WALLET, "uiTokenAmount": {"amount": quote_post, "decimals": 9 if quote_mint == WSOL else 6}},
            ],
        },
    }


def test_value_denom_prices_quote_legs_and_skips_only_when_none():
    priced = _swap(signature="sol", token_pre="0", token_post="1000000", quote_mint=WSOL, quote_ata=SOL_ATA, quote_pre="1000000000", quote_post="0")
    unpriced = _swap(signature="tok", token_pre="0", token_post="1", quote_mint=MINT, quote_ata=TOKEN_ATA, quote_pre="1", quote_post="1")
    shares = sample_readable_shares([priced, unpriced], WALLET, decoded={"events": []})
    assert shares["value_share"] is not None
    none = sample_readable_shares([unpriced], WALLET, decoded={"events": []})
    # A token-only row with no quote mint movement has no value denominator.
    assert none["value_share"] is None or none["value_denom"] in (None, "0")


def test_episode_prefilter_skips_transfer_in_sells():
    transfer_in = _swap(signature="tin", token_pre="0", token_post="1000000", quote_pre="0", quote_post="0")
    sell = _swap(signature="sell", token_pre="1000000", token_post="0", quote_pre="0", quote_post="100000000")
    trips = estimate_sample_round_trips([transfer_in, sell], WALLET, decoded={"events": []})
    assert trips["skip_deep_pull"] is True
    assert trips["expected_completed_episodes"] == 0
    buy = _swap(signature="buy", token_pre="0", token_post="1000000", quote_pre="100000000", quote_post="0")
    round_trip = estimate_sample_round_trips([buy, sell], WALLET, decoded={"events": []})
    assert round_trip["expected_completed_episodes"] == 1
    assert round_trip["skip_deep_pull"] is False
    ranked = rank_by_nansen_pnl([
        {"address": "few", "realized_pnl_usd": "999", "expected_completed_episodes": 0},
        {"address": "many", "realized_pnl_usd": "1", "expected_completed_episodes": 4},
    ])
    assert [row["address"] for row in ranked] == ["many", "few"]
    walked = walk_ranked([
        {"address": "skip", "funnel_decision": KEEP, "skip_deep_pull": True, "skip_deep_pull_reason": "sample_no_round_trips", "realized_pnl_usd": "9"},
        {"address": "keep", "funnel_decision": KEEP, "realized_pnl_usd": "1", "expected_completed_episodes": 2},
    ], n=2)
    assert walked["kept"][0]["address"] == "keep"
    assert walked["dropped"][0]["address"] == "skip"
    assert walked["dropped"][0]["funnel_reason"] == "sample_no_round_trips"


def test_jup6_exact_out_v2_layouts_are_fail_closed():
    accounts = [WALLET] + [f"acct{i}" for i in range(11)]
    payload = _anchor("exact_out_route_v2") + b"\0" * 28
    instruction = {
        "programId": JUPITER,
        "accounts": accounts,
        "data": [base64.b64encode(payload).decode(), "base64"],
    }
    route = _route(instruction, accounts)
    assert route["instruction"] == "exact_out_route_v2"
    shared_accounts = [f"acct{i}" for i in range(12)]
    shared = {
        "programId": JUPITER,
        "accounts": shared_accounts,
        "data": [base64.b64encode(_anchor("shared_accounts_exact_out_route_v2") + b"\0" * 28).decode(), "base64"],
    }
    assert _route(shared, shared_accounts)["instruction"] == "shared_accounts_exact_out_route_v2"
    truncated = {
        "programId": JUPITER,
        "accounts": accounts[:3],
        "data": [base64.b64encode(_anchor("exact_out_route_v2") + b"\0" * 4).decode(), "base64"],
    }
    with pytest.raises(ValueError, match="truncated"):
        _route(truncated, accounts[:3])


def test_readable_first_defaults_token_pnl_calls(tmp_path):
    cfg = validate_config({
        "mode": "dry-run",
        "grant_path": DRAFT_PATH,
        "output_dir": tmp_path,
        "wallets": [WALLET],
        "phases": "2",
        "readable_first": True,
        "window_days": 30,
        "earlier_history_days": 60,
    })
    assert cfg["nansen_token_pnl_max_calls"] == len(select_discovery_tokens(limit=200))
    plan = plan_request_counts(cfg)
    sample = next(
        stage for stage in plan["readable_first_plan"]["stages"]
        if stage["stage"] == "decodability_sample"
    )
    assert sample["helius_requests"] >= 3
