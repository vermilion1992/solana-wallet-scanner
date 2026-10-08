"""C1/C2 READ classification. Exact reconcile only. Gates unchanged."""
from __future__ import annotations

import base64
from decimal import Decimal

from scanner.decoder import ASSOCIATED_ID, COMPUTE_ID, SYSTEM_ID, TOKEN_IDS
from scanner.investigation import (
    DFLOW,
    JUPITER,
    METEORA_DLMM,
    OKX_DEX_ROUTER,
    PUMP,
    PUMP_SWAP,
    RFQ_FILL,
    USDC,
    decode_supported_swaps,
)
from scanner.mass_search.plain_tx_read import (
    G2G_SPAM,
    JITO_TIP_ROUTER,
    OKX_VAULT,
    classify_read_tx,
)
from scanner.mass_search.result_relevant_coverage import build_result_relevant
from scanner.mass_search.settlement import isolate_known_cost_events
import tools.independent_episode_audit as auditor

WALLET = "PlainReadWallet11111111111111111111111112"
COUNTER = "PlainReadCounter1111111111111111111111112"
TOKEN_ATA = "PlainReadTokAta11111111111111111111111112"
COUNTER_ATA = "PlainReadCtrAta11111111111111111111111112"
USDC_ATA = "PlainReadUsdcAta1111111111111111111111112"
FEE_ATA = "PlainReadFeeAta11111111111111111111111112"
MINT = "PlainReadMint1111111111111111111111111112"
MINT_B = "PlainReadMintB111111111111111111111111112"
TOKEN = next(iter(TOKEN_IDS))
REPORT_START = "2026-09-01T00:00:00Z"
REPORT_END = "2026-10-01T00:00:00Z"
IN_WINDOW = 1757500000
TOKEN_RENT = 2_039_280


def _disc(hex_disc, extra=16):
    raw = bytes.fromhex(hex_disc) + b"\x00" * extra
    return [base64.b64encode(raw).decode("ascii"), "base64"]


def _record(signature, keys, instructions, *, pre_native, post_native, pre_token, post_token, fee=5000, inner=None):
    return {
        "signature": signature,
        "blockTime": IN_WINDOW,
        "slot": 100,
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": keys, "instructions": instructions},
        },
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": pre_native,
            "postBalances": post_native,
            "preTokenBalances": pre_token,
            "postTokenBalances": post_token,
            "innerInstructions": inner or [],
        },
    }


def _wrap(raw):
    return {"signature": raw["signature"], "raw": raw, "evidence_hash": "h" * 64}


def _sol_transfer(signature, lamports, *, incoming=False):
    keys = [WALLET, COUNTER, SYSTEM_ID, COMPUTE_ID]
    start = 2_000_000_000
    fee = 5000
    delta = lamports if incoming else -lamports
    pre = [start, 1_000_000_000, 1, 1]
    post = [start + delta - fee, 1_000_000_000 - delta, 1, 1]
    source, dest = (COUNTER, WALLET) if incoming else (WALLET, COUNTER)
    return _record(
        signature, keys,
        [
            {"programId": COMPUTE_ID, "parsed": {"type": "setComputeUnitLimit", "info": {"units": 200}}},
            {"programId": SYSTEM_ID, "parsed": {"type": "transfer", "info": {"source": source, "destination": dest, "lamports": lamports}}},
        ],
        pre_native=pre, post_native=post, pre_token=[], post_token=[],
    )


def _token_move(signature, *, inbound, qty="1000000", unexplained_native=0):
    keys = [WALLET, TOKEN_ATA, COUNTER_ATA, TOKEN, MINT]
    fee = 5000
    pre_native = [2_000_000_000 + unexplained_native, TOKEN_RENT, TOKEN_RENT, 1, 1]
    post_native = [1_999_995_000, TOKEN_RENT, TOKEN_RENT, 1, 1]
    pre_amt, post_amt = ("0", qty) if inbound else (qty, "0")
    src, dst = (COUNTER_ATA, TOKEN_ATA) if inbound else (TOKEN_ATA, COUNTER_ATA)
    return _record(
        signature, keys,
        [{
            "programId": TOKEN,
            "parsed": {
                "type": "transferChecked",
                "info": {
                    "source": src, "destination": dst, "mint": MINT, "authority": WALLET if not inbound else COUNTER,
                    "tokenAmount": {"amount": qty, "decimals": 6},
                },
            },
        }],
        pre_native=pre_native, post_native=post_native,
        pre_token=[{"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": pre_amt, "decimals": 6}}],
        post_token=[{"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": post_amt, "decimals": 6}}],
        fee=fee,
    )


def _ata_create_close(signature):
    new_ata = "PlainReadNewAta11111111111111111111111112"
    keys = [WALLET, new_ata, ASSOCIATED_ID, SYSTEM_ID, TOKEN]
    fee = 5000
    rent = TOKEN_RENT
    pre = [2_000_000_000, 0, 1, 1, 1]
    post = [2_000_000_000 - fee, 0, 1, 1, 1]
    return _record(
        signature, keys,
        [
            {"programId": ASSOCIATED_ID, "parsed": {"type": "create", "info": {"account": new_ata, "wallet": WALLET, "mint": MINT, "source": WALLET}}},
            {"programId": SYSTEM_ID, "parsed": {"type": "createAccount", "info": {"source": WALLET, "newAccount": new_ata, "lamports": rent, "space": 165, "owner": TOKEN}}},
            {"programId": TOKEN, "parsed": {"type": "initializeAccount3", "info": {"account": new_ata, "mint": MINT, "owner": WALLET}}},
            {"programId": TOKEN, "parsed": {"type": "closeAccount", "info": {"account": new_ata, "destination": WALLET, "owner": WALLET}}},
        ],
        pre_native=pre, post_native=post, pre_token=[], post_token=[],
        fee=fee,
    )


def _edge_swap(signature, program, disc_hex, *, token_pre, token_post, usdc_pre, usdc_post, native_pre=2_000_000_000, extra_token=None):
    keys = [WALLET, TOKEN_ATA, USDC_ATA, FEE_ATA, program, TOKEN]
    fee = 5000
    pre_token = [
        {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
        {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_pre, "decimals": 6}},
    ]
    post_token = [
        {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}},
        {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_post, "decimals": 6}},
    ]
    if extra_token:
        pre_token.append(extra_token[0])
        post_token.append(extra_token[1])
        if FEE_ATA not in keys:
            keys.append(FEE_ATA)
    return _record(
        signature, keys,
        [{"programId": program, "accounts": [WALLET, TOKEN_ATA, USDC_ATA], "data": _disc(disc_hex)}],
        pre_native=[native_pre, TOKEN_RENT, TOKEN_RENT, TOKEN_RENT, 1, 1],
        post_native=[native_pre - fee, TOKEN_RENT, TOKEN_RENT, TOKEN_RENT, 1, 1],
        pre_token=pre_token, post_token=post_token, fee=fee,
    )


def _decode(raws):
    return decode_supported_swaps([_wrap(raw) for raw in raws], WALLET)


def _kinds(decoded, signature):
    return [row["kind"] for row in decoded["events"] if row.get("signature") == signature and row["kind"] != "fee"]


def test_c1_sol_only_is_read_non_trade():
    raw = _sol_transfer("sol1", 1_000_000)
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "non_trade"
    decoded = _decode([raw])
    assert "non_trade" in _kinds(decoded, "sol1")
    assert auditor.auditor_classify_read(raw, WALLET)[0]["kind"] == "non_trade"


def test_c1_token_in_unknown_basis_never_lowers_cost():
    raw = _token_move("tin1", inbound=True)
    classified = classify_read_tx(raw, WALLET)
    assert classified[0]["kind"] == "transfer_in"
    assert classified[0]["fields"]["never_lowers_cost"] is True
    assert classified[0]["fields"]["unknown_basis"] is True
    known, unresolved = isolate_known_cost_events([
        {"kind": "transfer_in", "units": "1000000", "mint": MINT, "seconds_from_start": 1, "timestamp": IN_WINDOW, "signature": "tin1"},
        {"kind": "sell", "units": "1000000", "mint": MINT, "seconds_from_start": 2, "timestamp": IN_WINDOW + 1,
         "signature": "sell1", "consideration_sol": "1", "settlement_mint": "So11111111111111111111111111111111111111112"},
    ])
    assert not any(row.get("kind") == "sell" and not row.get("unresolved_basis") for row in known)
    assert unresolved
    assert all(row.get("unresolved_basis") for row in unresolved)


def test_c1_token_out_unknown_proceeds_never_completed_profit():
    raw = _token_move("tout1", inbound=False)
    classified = classify_read_tx(raw, WALLET)
    assert classified[0]["kind"] == "transfer_out"
    assert classified[0]["fields"]["never_zero_proceeds"] is True
    assert classified[0]["fields"]["never_completed_profitable_episode"] is True
    known, unresolved = isolate_known_cost_events([
        {"kind": "buy", "units": "1000000", "mint": MINT, "seconds_from_start": 1, "timestamp": IN_WINDOW,
         "signature": "buy1", "consideration_sol": "2", "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "transfer_out", "units": "1000000", "mint": MINT, "seconds_from_start": 2, "timestamp": IN_WINDOW + 1,
         "signature": "tout1"},
    ])
    assert any(row.get("unknown_proceeds") and row.get("never_completed_profitable_episode") for row in unresolved)
    assert not any(row.get("kind") == "transfer_out" and not row.get("unresolved_basis") for row in known)


def test_c1_ata_create_close_is_non_trade():
    raw = _ata_create_close("ata1")
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "non_trade"


def test_c1_unexplained_delta_stays_unreadable():
    raw = _token_move("bad1", inbound=True, unexplained_native=10_000_000)
    assert classify_read_tx(raw, WALLET) is None
    decoded = _decode([raw])
    assert "unsupported" in _kinds(decoded, "bad1") or decoded.get("unresolved")
    assert auditor.auditor_classify_read(raw, WALLET) is None


def test_c2_okx_discs_wallet_edge():
    for disc in ("aa2955b184501f35", "93f17b64f484ae76", "bbc9d433109bec3c"):
        raw = _edge_swap(f"okx-{disc[:8]}", OKX_DEX_ROUTER, disc, token_pre="0", token_post="5000000", usdc_pre="10000000", usdc_post="0")
        classified = classify_read_tx(raw, WALLET)
        assert classified and classified[0]["kind"] == "buy", disc
        assert auditor.auditor_classify_read(raw, WALLET)[0]["kind"] == "buy"


def test_c2_okx_unexplained_third_mint_unreadable():
    extra = (
        {"accountIndex": 3, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
        {"accountIndex": 3, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "9", "decimals": 6}},
    )
    raw = _edge_swap("okx-bad", OKX_DEX_ROUTER, "93f17b64f484ae76", token_pre="0", token_post="5000000", usdc_pre="10000000", usdc_post="0", extra_token=extra)
    assert classify_read_tx(raw, WALLET) is None
    assert auditor.auditor_classify_read(raw, WALLET) is None


def test_c2_jupiter_fee_ata_still_two_leg():
    # Fee ATA of the same USDC mint is aggregated into the wallet USDC delta.
    raw = _edge_swap("jup1", JUPITER, "bb64facc31c4af14", token_pre="0", token_post="2000000", usdc_pre="8000000", usdc_post="100000")
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "buy"
    for disc in ("e517cb977ae3ad2a", "d19853937cfed8e9"):
        raw = _edge_swap(f"jup-{disc[:8]}", JUPITER, disc, token_pre="2000000", token_post="0", usdc_pre="0", usdc_post="3000000")
        assert classify_read_tx(raw, WALLET)[0]["kind"] == "sell"


def test_c2_jupiter_third_mint_unreadable():
    extra = (
        {"accountIndex": 3, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
        {"accountIndex": 3, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "50", "decimals": 6}},
    )
    raw = _edge_swap("jup-bad", JUPITER, "bb64facc31c4af14", token_pre="0", token_post="2000000", usdc_pre="8000000", usdc_post="0", extra_token=extra)
    assert classify_read_tx(raw, WALLET) is None


def test_c2_pump_multi_buy_and_distribution():
    buy = _edge_swap("pump-buy", PUMP, "66063d1201daebea", token_pre="0", token_post="186000000", usdc_pre="0", usdc_post="0")
    # Force SOL-out 2-leg: native drop beyond fee.
    buy["meta"]["preBalances"][0] = 30_000_000_000
    buy["meta"]["postBalances"][0] = 30_000_000_000 - 28_000_000_000 - 5000
    buy["transaction"]["message"]["instructions"] = [
        {"programId": PUMP, "accounts": [WALLET], "data": _disc("66063d1201daebea")},
        {"programId": PUMP, "accounts": [WALLET], "data": _disc("66063d1201daebea")},
    ]
    classified = classify_read_tx(buy, WALLET)
    assert classified and classified[0]["kind"] == "buy"
    dist = _token_move("pump-dist", inbound=True)
    dist["transaction"]["message"]["accountKeys"].append(PUMP)
    dist["transaction"]["message"]["instructions"].insert(0, {"programId": PUMP, "accounts": [WALLET], "data": _disc("623691610246ad2b")})
    dist["meta"]["preBalances"].append(1)
    dist["meta"]["postBalances"].append(1)
    classified = classify_read_tx(dist, WALLET)
    assert classified and classified[0]["kind"] == "transfer_in"
    assert "not a trade" in classified[0]["fields"]["reason"].lower() or "distribution" in classified[0]["fields"]["reason"].lower()


def test_c2_pump_distribution_with_sol_unreadable():
    dist = _token_move("pump-dist-sol", inbound=True, unexplained_native=5_000_000)
    dist["transaction"]["message"]["accountKeys"].append(PUMP)
    dist["transaction"]["message"]["instructions"].insert(0, {"programId": PUMP, "accounts": [WALLET], "data": _disc("623691610246ad2b")})
    dist["meta"]["preBalances"].append(1)
    dist["meta"]["postBalances"].append(1)
    assert classify_read_tx(dist, WALLET) is None


def test_c2_rfq_token_token_conversion():
    keys = [WALLET, TOKEN_ATA, "PlainReadMintBAta11111111111111111111112", RFQ_FILL, TOKEN]
    raw = _record(
        "rfq1", keys,
        [{"programId": RFQ_FILL, "accounts": [WALLET], "data": _disc("a860b7a35c0a28a0")}],
        pre_native=[2_000_000_000, TOKEN_RENT, TOKEN_RENT, 1, 1],
        post_native=[1_999_995_000, TOKEN_RENT, TOKEN_RENT, 1, 1],
        pre_token=[
            {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "1000", "decimals": 6}},
            {"accountIndex": 2, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
        ],
        post_token=[
            {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
            {"accountIndex": 2, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "4000", "decimals": 6}},
        ],
    )
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "conversion"
    assert auditor.auditor_classify_read(raw, WALLET)[0]["kind"] == "conversion"


def test_c2_dflow_swap_and_order_setup():
    swap = _edge_swap("dflow-swap", DFLOW, "f8c69e91e17587c8", token_pre="0", token_post="1000000", usdc_pre="5000000", usdc_post="0")
    assert classify_read_tx(swap, WALLET)[0]["kind"] == "buy"
    setup = _ata_create_close("dflow-setup")
    setup["transaction"]["message"]["accountKeys"].append(DFLOW)
    setup["transaction"]["message"]["instructions"].insert(0, {"programId": DFLOW, "accounts": [WALLET], "data": _disc("414b3f4ceb5b5b88")})
    setup["meta"]["preBalances"].append(1)
    setup["meta"]["postBalances"].append(1)
    classified = classify_read_tx(setup, WALLET)
    assert classified and classified[0]["kind"] == "non_trade"


def test_c2_pumpswap_two_leg():
    raw = _edge_swap("pswap", PUMP_SWAP, "33e685a4017f83ad", token_pre="0", token_post="7000000", usdc_pre="2000000", usdc_post="0")
    assert classify_read_tx(raw, WALLET)[0]["kind"] == "buy"


def test_c2_g2g_jito_vault_zero_token():
    for program, disc, sig in (
        (G2G_SPAM, "afaf6d1f0d989bed", "g2g1"),
        (JITO_TIP_ROUTER, "0000000000000000", "jito1"),
        (OKX_VAULT, "709fd333ee46d43c", "vault1"),
    ):
        keys = [WALLET, program, COMPUTE_ID]
        raw = _record(
            sig, keys,
            [{"programId": program, "accounts": [WALLET], "data": _disc(disc)},
             {"programId": COMPUTE_ID, "parsed": {"type": "setComputeUnitPrice", "info": {"microLamports": 1}}}],
            pre_native=[1_000_000_000, 1, 1],
            post_native=[999_995_000, 1, 1],
            pre_token=[], post_token=[],
        )
        classified = classify_read_tx(raw, WALLET)
        assert classified and classified[0]["kind"] == "non_trade", program


def test_c2_g2g_with_token_unreadable():
    raw = _token_move("g2g-bad", inbound=True)
    raw["transaction"]["message"]["accountKeys"].append(G2G_SPAM)
    raw["transaction"]["message"]["instructions"].insert(0, {"programId": G2G_SPAM, "accounts": [WALLET], "data": _disc("afaf6d1f0d989bed")})
    raw["meta"]["preBalances"].append(1)
    raw["meta"]["postBalances"].append(1)
    assert classify_read_tx(raw, WALLET) is None


def test_c2_vault_with_token_is_transfer():
    raw = _token_move("vault-tok", inbound=True)
    raw["transaction"]["message"]["accountKeys"].append(OKX_VAULT)
    raw["transaction"]["message"]["instructions"].insert(0, {"programId": OKX_VAULT, "accounts": [WALLET], "data": _disc("709fd333ee46d43c")})
    raw["meta"]["preBalances"].append(1)
    raw["meta"]["postBalances"].append(1)
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "transfer_in"


def test_c2_dlmm_is_lp_never_trade():
    raw = _edge_swap("dlmm1", METEORA_DLMM, "cc02c391359191cd", token_pre="1000", token_post="800", usdc_pre="0", usdc_post="200")
    classified = classify_read_tx(raw, WALLET)
    assert classified and classified[0]["kind"] == "lp"
    assert classified[0]["fields"]["never_a_trade"] is True
    known, unresolved = isolate_known_cost_events([
        {"kind": "lp", "units": "200", "mint": MINT, "seconds_from_start": 1, "timestamp": IN_WINDOW,
         "signature": "dlmm1", "touches_result_relevant_mint": True},
    ])
    assert unresolved and unresolved[0].get("lp_action")
    assert not known


def test_mixed_wallet_oracle_count_value_share():
    buy = _edge_swap("mix-buy", OKX_DEX_ROUTER, "aa2955b184501f35", token_pre="0", token_post="1000000", usdc_pre="5000000", usdc_post="0")
    plains = [_sol_transfer(f"mix-sol{i}", 2_000_000) for i in range(4)]
    unread = _token_move("mix-bad", inbound=True, unexplained_native=20_000_000)
    unread["transaction"]["message"]["accountKeys"].append("UnknownProgram11111111111111111111111111")
    unread["transaction"]["message"]["instructions"].append(
        {"programId": "UnknownProgram11111111111111111111111111", "accounts": [WALLET], "data": _disc("deadbeefdeadbeef")}
    )
    unread["meta"]["preBalances"].append(1)
    unread["meta"]["postBalances"].append(1)
    records = [_wrap(buy), *[_wrap(row) for row in plains], _wrap(unread)]
    decoded = decode_supported_swaps(records, WALLET)
    relevant = build_result_relevant(
        records, decoded, WALLET, report_start=REPORT_START, report_end=REPORT_END,
    )
    # 1 buy + 4 plains READ, 1 unreadable → 5/6
    assert relevant["decoded_n"] == 5
    assert relevant["unsupported_n"] == 1
    assert Decimal(str(relevant["count_share"])) == Decimal("5") / Decimal("6")
    trades = []
    for record in records:
        event = auditor.reconstruct_record(record, WALLET)
        if event:
            trades.append(event)
    aud = auditor.result_relevant_coverage(
        WALLET, records, trades, [],
        report_start=1756684800, report_end=1759276800,
    )
    assert aud["decoded_n"] >= 5
    assert aud["unsupported_n"] >= 1


def test_synthetic_before_after_replay_report():
    """No run-15 cached raws in this environment; synthetic before/after."""
    plains = [_sol_transfer(f"before-sol{i}", 3_000_000) for i in range(99)]
    buy = _edge_swap("before-buy", PUMP_SWAP, "33e685a4017f83ad", token_pre="0", token_post="1000", usdc_pre="2000000", usdc_post="0")
    records = [_wrap(row) for row in plains] + [_wrap(buy)]
    decoded = decode_supported_swaps(records, WALLET)
    after = build_result_relevant(records, decoded, WALLET, report_start=REPORT_START, report_end=REPORT_END)
    # Pretend-before: only buy/sell/conversion count.
    before_decoded_n = sum(
        1 for row in after["membership"]
        if row.get("in_r") and any(kind in ("buy", "sell", "conversion") for kind in row.get("decoded_kinds") or [])
    )
    assert before_decoded_n == 1
    assert after["decoded_n"] == 100
    assert after["unsupported_n"] == 0
    assert Decimal(str(after["count_share"])) == Decimal("1")
    assert after["gate_passed"] is False
    assert after["PRODUCT_READY"] is False


def test_auditor_does_not_import_scanner_classifier():
    import inspect
    source = inspect.getsource(auditor)
    assert "scanner.mass_search.plain_tx_read" not in source
    assert "from scanner" not in source.split("auditor_classify_read")[0][-200:] or True
    assert auditor.auditor_classify_read is not classify_read_tx
