"""C6 JUP6 hop predicate and FIFO window-scoped drop rows. Offline only."""
from __future__ import annotations

from decimal import Decimal

from scanner.investigation import (
    JUPITER,
    RAYDIUM_AMM,
    USDC,
    WELL_KNOWN_INNER_AMMS,
    _jupiter_hop_inner_ok,
    _keys,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.research_profile import attach_live_independent_audit
import tools.independent_episode_audit as auditor

HUMIDIFI = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"
GOONFI = "goonERTdGsjnkZqWuVjs73BZ3Pb9qoCUdBUL17BnS5j"
UNKNOWN_PROP_AMM = "UnkPropAmmC6Example11111111111111111111111"
SCORCH = "SCoRcH8c2dpjvcJD6FiPbCSQyQgu3PcUAWj2Xxx3mqn"
SRC5QY = "src5qyOrderEscrow11111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM = "11111111111111111111111111111111"
COMPUTE = "ComputeBudget111111111111111111111111111111"

ENAAT = "EnaatNfHKJHifA6VsiZBm1dKKwY8z2aaqW8BhDYwvYJm"
ENAAT_SIG = "4Berw8vBNXqu69GQwHFnrkM1vqQrM2jxQTrPXeY8YSZhDXh6TEGwhW6oah3cf4jCcNDRCqEUx2tEdLszhGuRxgn9"
UYDX = "4uyDXbsK11111111111111111111111111111111111"
UYDX_SIG = "43f4FnEdqhx3N47J111111111111111111111111111111111111111111111111111111111111111111111"
HXP = "HXpJhVrbdGvnaPh2zpex7boUGX1qiRTL5ZNhmV76pBpC"
HXP_SIG = "4gevPEMQ37tXXKj6uEXV4SbqwRkRE1wD5pGUzDSnkZ5x9XUGzaBWzg8Db9swKezNCZ4wnUSfmJCJmFTFz7vL8SYW"

USDC_ATA = "UsdcAtaC6Example11111111111111111111111111"
POOL_USDC = "PoolUsdcC6Example1111111111111111111111111"
POOL_AUTH = "PoolAuthC6Example1111111111111111111111111"


def _trades(decoded):
    return [
        event for event in decoded.get("events") or []
        if event.get("kind") in {"buy", "sell", "conversion"}
    ]


def _jup6_hop_tx(
    wallet,
    signature,
    *,
    extra_outer=None,
    approve=False,
    outer_program=JUPITER,
    hop_amm=HUMIDIFI,
    stack3_child=False,
    usdc_amount="77140299024",
    sol_out=1_000_000_000_000,
):
    keys = [
        wallet, USDC_ATA, POOL_USDC, POOL_AUTH, outer_program,
        hop_amm, TOKEN, SYSTEM, COMPUTE, SCORCH, SRC5QY,
    ]
    outers = [
        {"programId": COMPUTE, "accounts": [], "data": "3"},
        {
            "programId": outer_program,
            "accounts": [wallet, USDC_ATA, POOL_USDC],
            "data": "11111111",
        },
    ]
    if extra_outer:
        outers.append({"programId": extra_outer, "accounts": [wallet, USDC_ATA], "data": "11111111"})
    hop_children = [
        {
            "programId": TOKEN,
            "stackHeight": 3,
            "parsed": {
                "type": "transfer",
                "info": {
                    "source": POOL_USDC,
                    "destination": USDC_ATA,
                    "authority": POOL_AUTH,
                    "amount": usdc_amount,
                },
            },
        }
    ]
    if approve:
        hop_children.append({
            "programId": TOKEN,
            "stackHeight": 3,
            "parsed": {
                "type": "approve",
                "info": {
                    "source": USDC_ATA,
                    "delegate": POOL_AUTH,
                    "owner": wallet,
                    "amount": "1",
                },
            },
        })
    inners = [
        {
            "programId": hop_amm,
            "stackHeight": 2,
            "accounts": [wallet, USDC_ATA, POOL_USDC],
            "data": "11111111",
        },
        *hop_children,
    ]
    if stack3_child:
        inners.extend([
            {
                "programId": SCORCH,
                "stackHeight": 2,
                "accounts": [wallet, USDC_ATA],
                "data": "11111111",
            },
            {
                "programId": TOKEN,
                "stackHeight": 3,
                "parsed": {
                    "type": "transferChecked",
                    "info": {
                        "source": POOL_USDC,
                        "destination": USDC_ATA,
                        "authority": POOL_AUTH,
                        "mint": USDC,
                        "tokenAmount": {"amount": "0", "decimals": 6},
                    },
                },
            },
        ])
    fee = 5000
    pre_balances = [sol_out + fee, 2_039_280, 2_039_280] + [0] * (len(keys) - 3)
    post_balances = [fee, 2_039_280, 2_039_280] + [0] * (len(keys) - 3)
    # Document the hop SOL take on the hop program account so a lamport-only
    # wallet credit cannot understate cost (DC-9 H5).
    hop_idx = keys.index(hop_amm)
    post_balances[hop_idx] = sol_out
    raw = {
        "transaction": {
            "signatures": [signature],
            "message": {
                "header": {
                    "numRequiredSignatures": 1,
                    "numReadonlySignedAccounts": 0,
                    "numReadonlyUnsignedAccounts": 7,
                },
                "accountKeys": keys,
                "instructions": outers,
            },
        },
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": pre_balances,
            "postBalances": post_balances,
            "preTokenBalances": [{
                "accountIndex": 1,
                "mint": USDC,
                "owner": wallet,
                "uiTokenAmount": {"amount": "0", "decimals": 6},
            }],
            "postTokenBalances": [{
                "accountIndex": 1,
                "mint": USDC,
                "owner": wallet,
                "uiTokenAmount": {"amount": usdc_amount, "decimals": 6},
            }],
            "innerInstructions": [{"index": 1, "instructions": inners}],
        },
        "blockTime": 1_784_704_003,
        "slot": 1,
    }
    return raw


def _app_keys(raw):
    message = raw["transaction"]["message"]
    return _keys(message, raw["meta"])


def test_prop_amms_stay_off_well_known_inner_allowlist():
    # Published HumidiFi (9H6tua7) is the live pin; unpublished stand-ins stay off.
    assert HUMIDIFI in WELL_KNOWN_INNER_AMMS
    assert GOONFI not in WELL_KNOWN_INNER_AMMS
    assert UNKNOWN_PROP_AMM not in WELL_KNOWN_INNER_AMMS
    assert HUMIDIFI in auditor.WELL_KNOWN_INNER_AMMS
    assert GOONFI not in auditor.WELL_KNOWN_INNER_AMMS
    assert UNKNOWN_PROP_AMM not in auditor.WELL_KNOWN_INNER_AMMS
    src = auditor.__file__
    text = open(src, encoding="utf-8").read()
    assert not any(
        line.lstrip().startswith(("from scanner", "import scanner"))
        for line in text.splitlines()
    )


def test_c6_example1_humidifi_hop_decodes():
    raw = _jup6_hop_tx(ENAAT, ENAAT_SIG)
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, ENAAT, keys) is True
    assert auditor._jupiter_hop_inner_ok(raw, ENAAT, auditor._keys(raw)) is True
    app = net_balance_reviewed_swap(raw, ENAAT)
    assert app and app["kind"] == "conversion"
    decoded = decode_supported_swaps(canonical_decode_records([raw]), ENAAT)
    trades = _trades(decoded)
    assert len(trades) == 1
    assert trades[0]["kind"] == "conversion"
    aud = auditor.reconstruct_record(raw, ENAAT)
    assert aud and aud["kind"] == "conversion"


def test_c6_example2_stack3_child_decodes():
    raw = _jup6_hop_tx(
        UYDX, UYDX_SIG, stack3_child=True, usdc_amount="13894720000", sol_out=170_800_000_000,
    )
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, UYDX, keys) is True
    assert auditor._jupiter_hop_inner_ok(raw, UYDX, auditor._keys(raw)) is True
    decoded = decode_supported_swaps(canonical_decode_records([raw]), UYDX)
    assert _trades(decoded)
    assert auditor.reconstruct_record(raw, UYDX)


def test_c6_example3_src5qy_outer_stays_blocked():
    raw = _jup6_hop_tx(HXP, HXP_SIG, extra_outer=SRC5QY, usdc_amount="14414839", sol_out=22_020_157_360)
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, HXP, keys) is False
    assert auditor._jupiter_hop_inner_ok(raw, HXP, auditor._keys(raw)) is False
    assert net_balance_reviewed_swap(raw, HXP) is None
    decoded = decode_supported_swaps(canonical_decode_records([raw]), HXP)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(raw, HXP) is None


def test_c6_synthetic_approve_hop_stays_blocked():
    raw = _jup6_hop_tx(ENAAT, ENAAT_SIG, approve=True, hop_amm=UNKNOWN_PROP_AMM)
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, ENAAT, keys) is False
    assert auditor._jupiter_hop_inner_ok(raw, ENAAT, auditor._keys(raw)) is False
    assert net_balance_reviewed_swap(raw, ENAAT) is None
    decoded = decode_supported_swaps(canonical_decode_records([raw]), ENAAT)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(raw, ENAAT) is None


def test_c6_unknown_inner_under_unreviewed_outer_stays_blocked():
    raw = _jup6_hop_tx(
        ENAAT, ENAAT_SIG, outer_program="B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A"
    )
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, ENAAT, keys) is False
    assert auditor._jupiter_hop_inner_ok(raw, ENAAT, auditor._keys(raw)) is False
    assert net_balance_reviewed_swap(raw, ENAAT) is None
    decoded = decode_supported_swaps(canonical_decode_records([raw]), ENAAT)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(raw, ENAAT) is None


def _usdc_round_trip(mint, close_ts, *, flatten_reset=False, unflat=False):
    sell_qty = "40" if unflat else ("150" if flatten_reset else "100")
    buy = {
        "mint": mint,
        "kind": "buy",
        "quantity_raw": "100",
        "consideration_usdc": "1000",
        "consideration_sol": "0",
        "fees_and_tips_sol": "0",
        "settlement_asset": "USDC",
        "signature": f"buy-{mint[:6]}",
        "slot": 1,
        "transaction_index": 0,
        "timestamp": close_ts - 1000,
        "observed_pre_quantity_raw": "0",
        "observed_post_quantity_raw": "100",
        "program": JUPITER,
        "instruction": "net_balance",
    }
    sell = {
        "mint": mint,
        "kind": "sell",
        "quantity_raw": sell_qty,
        "consideration_usdc": "50",
        "consideration_sol": "0",
        "fees_and_tips_sol": "0",
        "settlement_asset": "USDC",
        "signature": f"sell-{mint[:6]}",
        "slot": 2,
        "transaction_index": 0,
        "timestamp": close_ts,
        "observed_pre_quantity_raw": "100",
        "observed_post_quantity_raw": "60" if unflat else "0",
        "program": JUPITER,
        "instruction": "net_balance",
    }
    return [buy, sell]


def test_fifo_out_of_window_usdc_flatten_does_not_block():
    pengu = "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"
    trades = _usdc_round_trip(pengu, 1_734_000_000, flatten_reset=True)
    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START = 1_783_600_000
    auditor.REPORT_END = 1_791_400_000
    try:
        episodes, _unresolved, _known, omitted = auditor._fifo(trades)
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original
    assert episodes == []
    assert omitted
    drop = omitted[0]
    assert drop["reason"] == "not_in_window_or_unresolved"
    assert drop["timestamp"] == 1_734_000_000
    assert drop["settlement_asset"] == "USDC"
    assert "net_profit_sol" not in drop
    assert Decimal(drop["net_profit_usdc"]) < 0
    assert Decimal(drop["net_profit"]) == Decimal(drop["net_profit_usdc"])


def test_fifo_in_window_oversold_flatten_still_blocks():
    mint = "InWindowFlattenMint11111111111111111111111"
    trades = _usdc_round_trip(mint, 1_786_000_000, flatten_reset=True)
    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START = 1_783_600_000
    auditor.REPORT_END = 1_791_400_000
    try:
        episodes, _unresolved, _known, omitted = auditor._fifo(trades)
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original
    assert episodes == []
    assert omitted[0]["reason"] == "oversold_flatten_reset"
    assert omitted[0]["timestamp"] == 1_786_000_000
    assert omitted[0]["settlement_asset"] == "USDC"
    assert "net_profit_sol" not in omitted[0]


def test_fifo_out_of_window_unflattened_does_not_block():
    mint = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
    trades = _usdc_round_trip(mint, 1_720_000_000, unflat=True)
    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START = 1_783_600_000
    auditor.REPORT_END = 1_791_400_000
    try:
        episodes, _unresolved, _known, omitted = auditor._fifo(trades)
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original
    assert episodes == []
    assert omitted[0]["reason"] == "not_in_window_or_unresolved"
    assert omitted[0]["timestamp"] == 1_720_000_000
    assert "net_profit_sol" not in omitted[0]


def test_fifo_in_window_unflattened_still_blocks():
    mint = "InWindowUnflatMint111111111111111111111111"
    trades = _usdc_round_trip(mint, 1_786_000_000, unflat=True)
    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START = 1_783_600_000
    auditor.REPORT_END = 1_791_400_000
    try:
        episodes, _unresolved, _known, omitted = auditor._fifo(trades)
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original
    assert omitted[0]["reason"] == "unflattened_losing_inventory"
    assert omitted[0]["settlement_asset"] == "USDC"
    assert "net_profit_sol" not in omitted[0]


def test_attach_ignores_out_of_window_oversold_usdc_drop():
    pengu = "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"
    win_mint = "WinMint11111111111111111111111111111111111"
    report_window = {
        "start": "2026-07-09T14:57:15Z",
        "end": "2026-10-07T14:57:15Z",
    }
    window_start = int(auditor.datetime.fromisoformat("2026-07-09T14:57:15+00:00").timestamp())
    old = _usdc_round_trip(pengu, 1_734_000_000, flatten_reset=True)
    clean = [
        {
            "mint": win_mint,
            "kind": "buy",
            "quantity_raw": "10",
            "consideration_usdc": "100",
            "consideration_sol": "0",
            "fees_and_tips_sol": "0",
            "settlement_asset": "USDC",
            "signature": "buy-win",
            "slot": 10,
            "transaction_index": 0,
            "timestamp": window_start + 10,
            "observed_pre_quantity_raw": "0",
            "observed_post_quantity_raw": "10",
            "program": JUPITER,
            "instruction": "net_balance",
        },
        {
            "mint": win_mint,
            "kind": "sell",
            "quantity_raw": "10",
            "consideration_usdc": "712.568446",
            "consideration_sol": "0",
            "fees_and_tips_sol": "0",
            "settlement_asset": "USDC",
            "signature": "sell-win",
            "slot": 11,
            "transaction_index": 0,
            "timestamp": window_start + 20,
            "observed_pre_quantity_raw": "10",
            "observed_post_quantity_raw": "0",
            "program": JUPITER,
            "instruction": "net_balance",
        },
    ]
    original_fn = auditor.reconstruct_record
    original_window = auditor.REPORT_START, auditor.REPORT_END
    auditor.reconstruct_record = lambda record, _address: record
    try:
        report = {
            "address": "9hciHnHzEyLHtjbeUzpp6ZRt4Y4HQbZg4Vx9sFAGGiup",
            "window": report_window,
            "events": [],
            "worksheet": {},
            "classification": {"counts": {}, "transactions": 0},
            "coverage": {},
            "completed_episode_ledger": [{
                "mint": win_mint,
                "close_signature": "sell-win",
                "net": "612.568446",
                "unit": "USDC",
                "basis": "100",
                "proceeds": "712.568446",
                "costs": "0",
            }],
        }
        profile = {
            "completed_episode_ledger": report["completed_episode_ledger"],
            "completed_episode_net": "612.568446",
            "completed_episode_net_unit": "USDC",
            "audit_fingerprint": {"fingerprint": "x" * 64, "accounting_policy_version": "v"},
        }
        audit = attach_live_independent_audit(report, profile, old + clean, "W")
    finally:
        auditor.reconstruct_record = original_fn
        auditor.REPORT_START, auditor.REPORT_END = original_window
    assert audit.get("reason") != "auditor_dropped_losing_episodes"
    assert audit["dropped_losers"] is False
    assert all(row.get("reason") != "oversold_flatten_reset" for row in (audit.get("dropped_losing_episodes") or []))
    assert audit["status"] == "independently_audited"


def test_episode_net_totals_reads_usdc_field():
    net, unit, by_unit = auditor.episode_net_totals([
        {"settlement_asset": "USDC", "net_profit": "612.568446", "net_profit_usdc": "612.568446"},
    ])
    assert unit == "USDC"
    assert Decimal(net) == Decimal("612.568446")
    assert Decimal(by_unit["USDC"]) == Decimal("612.568446")
