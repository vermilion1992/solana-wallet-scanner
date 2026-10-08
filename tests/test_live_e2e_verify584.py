"""Verify-584233c residuals: both-down sells, v3 auditor, LP/NFT, D5 dates, lows."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import scanner.mass_search.qualification_gates as Q
from scanner.mass_search.live_e2e import known_trade_rate_from_state
from scanner.mass_search.qualification_gates import (
    GT25_ECONOMIC_TRADES_RULE,
    merge_trade_rates,
    raw_economic_keys_for_tx,
    raw_economic_trade_rate,
    with_gt25_blocker,
)
import tools.independent_episode_audit as auditor

A = "DtCiNAXm111111111111111111111111111111111"
X = "BonkMint111111111111111111111111111111111"
NFT = "PositionNft111111111111111111111111111111"
USDC = Q.USDC_MINT
DAY = int(datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp())


def tb(idx, mint, amt, owner=A):
    return {"accountIndex": idx, "mint": mint, "owner": owner, "uiTokenAmount": {"amount": str(amt)}}


def rec(sig, *, pre_tok, post_tok, native=0, fee=5000, logs=None, programs=None, bt=DAY + 10, n_acc=6):
    pre = [10_000_000_000] + [2_039_280] * (n_acc - 1)
    post = list(pre)
    post[0] += native - fee
    keys = [A] + [f"Acc{i}" for i in range(1, n_acc)]
    ixs = []
    for pid in programs or []:
        keys.append(pid)
        ixs.append({"programId": pid, "programIdIndex": len(keys) - 1})
    meta = {
        "err": None,
        "fee": fee,
        "preBalances": pre,
        "postBalances": post,
        "preTokenBalances": pre_tok,
        "postTokenBalances": post_tok,
        "logMessages": list(logs or []),
        "loadedAddresses": {"writable": [], "readonly": []},
    }
    return {
        "blockTime": bt,
        "transaction": {
            "signatures": [sig],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": keys,
                "instructions": ixs,
            },
        },
        "meta": meta,
    }


def test_both_down_sell_and_disperse_counts():
    tx = rec(
        "disperse",
        pre_tok=[tb(1, X, 1_000_000)],
        post_tok=[tb(1, X, 0)],
        native=-1_490_000,
        logs=["Program log: Instruction: SellAndDisperseBonk", "Program log: Instruction: SwapBaseInput"],
    )
    assert Q.raw_economic_keys_for_tx(tx, A) == 1
    assert auditor.raw_economic_keys_for_tx(tx, A) == 1
    rate = raw_economic_trade_rate([tx], A)
    assert rate["max"] == 1
    assert rate["max_on"] == "2026-10-02"


def test_both_down_pump_sell_counts():
    tx = rec(
        "pump-sell",
        pre_tok=[tb(1, X, 500)],
        post_tok=[tb(1, X, 0)],
        native=-770_000,
        logs=["Program log: Instruction: Sell"],
        programs=[auditor.PUMP],
    )
    assert Q.raw_economic_keys_for_tx(tx, A) == 1
    assert auditor.raw_economic_keys_for_tx(tx, A) == 1


def test_whirlpool_open_position_both_down_is_not_a_sell():
    """DQcmxgGC shape: token −, USDC −, SOL rent, +1 0-decimal NFT."""
    lp = rec(
        "wp-open",
        pre_tok=[tb(1, X, 1_000_000), tb(2, USDC, 5_000_000), tb(3, NFT, 0)],
        post_tok=[tb(1, X, 0), tb(2, USDC, 0), tb(3, NFT, 1)],
        native=-7_980_000,
        logs=["Program log: Instruction: OpenPosition"],
        programs=[auditor.WHIRLPOOL],
    )
    # decimals=0 on the NFT so dust filter drops +1 and the rest looks both-down.
    lp["meta"]["preTokenBalances"][2]["uiTokenAmount"]["decimals"] = 0
    lp["meta"]["postTokenBalances"][2]["uiTokenAmount"]["decimals"] = 0
    assert Q.raw_economic_keys_for_tx(lp, A) == 0
    assert auditor.raw_economic_keys_for_tx(lp, A) == 0


def test_rent_only_and_tip_transfer_and_300k_airdrop_are_not_trades():
    rent = rec(
        "rent-out",
        pre_tok=[tb(1, X, 1_000_000)],
        post_tok=[tb(1, X, 0)],
        native=-2_039_280,
        logs=[],
    )
    tip_out = rec(
        "tip-out",
        pre_tok=[tb(1, X, 1_000_000)],
        post_tok=[tb(1, X, 0)],
        native=-2_000_000,
        logs=[],
    )
    airdrop = rec(
        "tip-airdrop-300k",
        pre_tok=[tb(1, X, 0)],
        post_tok=[tb(1, X, 50)],
        native=-300_000,
        logs=[],
    )
    assert Q.raw_economic_keys_for_tx(rent, A) == 0
    assert Q.raw_economic_keys_for_tx(tip_out, A) == 0
    assert Q.raw_economic_keys_for_tx(airdrop, A) == 0


def test_auditor_excludes_meteora_dlmm_liquidity():
    add = rec(
        "dlmm-add",
        pre_tok=[tb(1, X, 1_000_000)],
        post_tok=[tb(1, X, 0)],
        native=-50_000,
        logs=["Program log: Instruction: addLiquidityByStrategy"],
        programs=[auditor.METEORA_DLMM],
    )
    remove = rec(
        "dlmm-remove",
        pre_tok=[tb(1, X, 0)],
        post_tok=[tb(1, X, 800_000)],
        native=40_000,
        logs=["Program log: Instruction: removeLiquidity"],
        programs=[auditor.METEORA_DLMM],
    )
    assert auditor.raw_economic_keys_for_tx(add, A) == 0
    assert auditor.raw_economic_keys_for_tx(remove, A) == 0


def test_lp_open_and_nft_mint_and_tip_airdrop_are_not_trades():
    lp = rec(
        "lp",
        pre_tok=[],
        post_tok=[tb(2, NFT, 1)],
        native=-7_980_000,
        logs=["Program log: Instruction: OpenPositionWithTokenExtensions"],
        programs=[auditor.WHIRLPOOL],
    )
    nft = rec(
        "nft",
        pre_tok=[],
        post_tok=[tb(2, NFT, 1)],
        native=-16_000_000,
        logs=["Program log: Instruction: MintV6"],
    )
    tip = rec(
        "tip",
        pre_tok=[],
        post_tok=[tb(1, X, 50)],
        native=-150_000,
        logs=[],
    )
    rent_other = rec(
        "rent",
        pre_tok=[],
        post_tok=[tb(2, NFT, 1)],
        native=-2_039_280,
        logs=[],
    )
    assert Q.raw_economic_keys_for_tx(lp, A) == 0
    assert Q.raw_economic_keys_for_tx(nft, A) == 0
    assert Q.raw_economic_keys_for_tx(tip, A) == 0
    assert Q.raw_economic_keys_for_tx(rent_other, A) == 0
    assert auditor.raw_economic_keys_for_tx(lp, A) == 0
    assert auditor.raw_economic_keys_for_tx(nft, A) == 0
    assert auditor.raw_economic_keys_for_tx(tip, A) == 0


def test_auditor_v3_not_balance_floor_clone():
    # Opposite legs, no swap signal: app may count a real buy; auditor does not.
    buy = rec(
        "buy-nosig",
        pre_tok=[tb(1, X, 0)],
        post_tok=[tb(1, X, 1000)],
        native=-1_000_000,
        logs=[],
    )
    assert Q.raw_economic_keys_for_tx(buy, A) == 1
    assert auditor.raw_economic_keys_for_tx(buy, A) == 0
    # Same buy with a swap log: auditor counts, independently of the SOL floor.
    buy_sig = rec(
        "buy-sig",
        pre_tok=[tb(1, X, 0)],
        post_tok=[tb(1, X, 1000)],
        native=-1_000_000,
        logs=["Program log: Instruction: Swap"],
    )
    assert auditor.raw_economic_keys_for_tx(buy_sig, A) == 1
    assert "INDEPENDENT_SOL_FLOOR_LAMPORTS" not in auditor.__dict__


def test_multi_hop_dust_is_one_key():
    hop = rec(
        "hop",
        pre_tok=[tb(1, X, 0), tb(2, "MidMint111111111111111111111111111111111", 0)],
        post_tok=[tb(1, X, 1000), tb(2, "MidMint111111111111111111111111111111111", 1)],
        native=-1_000_000,
        logs=["Program log: Instruction: Route"],
    )
    assert Q.raw_economic_keys_for_tx(hop, A) == 1
    assert auditor.raw_economic_keys_for_tx(hop, A) == 1


def test_blocktime_zero_counts():
    tx = rec(
        "epoch",
        pre_tok=[tb(1, X, 0)],
        post_tok=[tb(1, X, 1000)],
        native=-1_000_000,
        logs=["Program log: Instruction: Swap"],
        bt=0,
    )
    rate = raw_economic_trade_rate([tx], A)
    assert rate["incomplete"] is False
    assert rate["max"] == 1
    assert rate["max_on"] == "1970-01-01"
    aud, inc = auditor.raw_economic_trades_by_utc_day([tx], A)
    assert inc == 0
    assert aud["1970-01-01"] == 1


def test_d5_reads_date_from_saved_by_day():
    state = {
        "phase2": {
            "2M2vLX34saved111111111111111111111111": {
                "max_economic_trades_in_one_day": 44,
                "triage_decision": {
                    "max_economic_trades_in_one_day": 44,
                    "economic_trades_by_day": {"2025-03-02": 44, "2025-03-01": 10},
                },
            }
        },
        "phase3": {},
    }
    known = known_trade_rate_from_state(state, "2M2vLX34saved111111111111111111111111")
    assert known["max"] == 44
    assert known["max_on"] == "2025-03-02"
    text = with_gt25_blocker("no captured history in this run", known)
    assert "44 on 2025-03-02" in text
    assert "unknown" not in text


def test_dateless_stored_max_does_not_attach_to_unrelated_day():
    merged = merge_trade_rates({"by_day": {"2026-01-01": 5}}, {"max": 30})
    assert merged["max"] == 30
    assert merged["max_on"] is None


def test_stale_unknown_gt25_line_is_replaced():
    text = with_gt25_blocker(
        f"{GT25_ECONOMIC_TRADES_RULE}: 30 on unknown",
        {"max": 40, "max_on": "2026-09-01"},
    )
    assert text.count(GT25_ECONOMIC_TRADES_RULE) == 1
    assert "40 on 2026-09-01" in text
    assert "unknown" not in text


def test_same_tx_losing_round_trip_is_kept():
    def row(kind, sig, ts, qty, sol, post, pre="0"):
        return {
            "kind": kind,
            "mint": "M",
            "signature": sig,
            "timestamp": ts,
            "slot": ts,
            "quantity_raw": str(qty),
            "consideration_sol": str(sol),
            "fees_and_tips_sol": "0",
            "observed_pre_quantity_raw": pre,
            "observed_post_quantity_raw": str(post),
            "settlement_asset": "SOL",
        }

    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START, auditor.REPORT_END = 0, 2 ** 40
    try:
        eps, _u, _k, omitted = auditor._fifo([
            row("sell", "rt", 1, 100, 0.8, 0),
            row("buy", "rt", 1, 100, 1, 100),
        ])
        visible = any(Decimal(e["net_profit_sol"]) < 0 for e in eps) or bool(omitted)
        assert visible
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original
