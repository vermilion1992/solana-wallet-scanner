"""C1/C2 READ classification. Exact reconcile only. Gates unchanged."""
from __future__ import annotations

import base64
import json
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
IN_WINDOW = 1789000000
TOKEN_RENT = 2_039_280


def _disc(hex_disc, extra=24):
    raw = bytes.fromhex(hex_disc) + b"\x00" * extra
    return [base64.b64encode(raw).decode("ascii"), "base64"]


def _record(signature, keys, instructions, *, pre_native, post_native, pre_token, post_token, fee=5000, inner=None):
    return {
        "signature": signature,
        "blockTime": IN_WINDOW,
        "slot": 100,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": key, "signer": index == 0, "writable": True} if isinstance(key, str) else key
                    for index, key in enumerate(keys)
                ] if keys and isinstance(keys[0], str) else keys,
                "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": max(0, len(keys) - 1)},
                "instructions": instructions,
            },
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
    keys = [WALLET, TOKEN_ATA, USDC_ATA, FEE_ATA, program, TOKEN, COUNTER_ATA]
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
    token_delta = int(token_post) - int(token_pre)
    usdc_delta = int(usdc_post) - int(usdc_pre)
    inners = []
    if token_delta:
        src, dst, qty = (COUNTER_ATA, TOKEN_ATA, token_delta) if token_delta > 0 else (TOKEN_ATA, COUNTER_ATA, -token_delta)
        inners.append({
            "programId": TOKEN,
            "parsed": {"type": "transferChecked", "info": {
                "source": src, "destination": dst, "mint": MINT, "authority": WALLET,
                "tokenAmount": {"amount": str(qty), "decimals": 6},
            }},
        })
    if usdc_delta:
        src, dst, qty = (COUNTER_ATA, USDC_ATA, usdc_delta) if usdc_delta > 0 else (USDC_ATA, COUNTER_ATA, -usdc_delta)
        inners.append({
            "programId": TOKEN,
            "parsed": {"type": "transferChecked", "info": {
                "source": src, "destination": dst, "mint": USDC, "authority": WALLET,
                "tokenAmount": {"amount": str(qty), "decimals": 6},
            }},
        })
    return _record(
        signature, keys,
        [{"programId": program, "accounts": [WALLET, TOKEN_ATA, USDC_ATA, COUNTER_ATA], "data": _disc(disc_hex)}],
        pre_native=[native_pre, TOKEN_RENT, TOKEN_RENT, TOKEN_RENT, 1, 1, TOKEN_RENT],
        post_native=[native_pre - fee, TOKEN_RENT, TOKEN_RENT, TOKEN_RENT, 1, 1, TOKEN_RENT],
        pre_token=pre_token, post_token=post_token, fee=fee,
        inner=[{"index": 0, "instructions": inners}] if inners else [{"index": 0, "instructions": [
            {"programId": TOKEN, "parsed": {"type": "getAccountDataSize", "info": {"mint": MINT}}},
        ]}],
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
    mint_b_ata = "PlainReadMintBAta11111111111111111111112"
    keys = [WALLET, TOKEN_ATA, mint_b_ata, RFQ_FILL, TOKEN, COUNTER_ATA]
    raw = _record(
        "rfq1", keys,
        [{"programId": RFQ_FILL, "accounts": [WALLET, TOKEN_ATA, mint_b_ata, COUNTER_ATA], "data": _disc("a860b7a35c0a28a0")}],
        pre_native=[2_000_000_000, TOKEN_RENT, TOKEN_RENT, 1, 1, TOKEN_RENT],
        post_native=[1_999_995_000, TOKEN_RENT, TOKEN_RENT, 1, 1, TOKEN_RENT],
        pre_token=[
            {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "1000", "decimals": 6}},
            {"accountIndex": 2, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
        ],
        post_token=[
            {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6}},
            {"accountIndex": 2, "mint": MINT_B, "owner": WALLET, "uiTokenAmount": {"amount": "4000", "decimals": 6}},
        ],
        inner=[{
            "index": 0,
            "instructions": [
                {"programId": TOKEN, "parsed": {"type": "transferChecked", "info": {
                    "source": TOKEN_ATA, "destination": COUNTER_ATA, "mint": MINT, "authority": WALLET,
                    "tokenAmount": {"amount": "1000", "decimals": 6},
                }}},
                {"programId": TOKEN, "parsed": {"type": "transferChecked", "info": {
                    "source": COUNTER_ATA, "destination": mint_b_ata, "mint": MINT_B, "authority": WALLET,
                    "tokenAmount": {"amount": "4000", "decimals": 6},
                }}},
            ],
        }],
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
    for offset, row in enumerate(records):
        row["raw"]["slot"] = 100 + offset
        row["slot"] = 100 + offset
    decoded = decode_supported_swaps(records, WALLET)
    relevant = build_result_relevant(
        records, decoded, WALLET, report_start=REPORT_START, report_end=REPORT_END,
    )
    # 1 buy + 4 plains READ, 1 unreadable → 5/6
    assert relevant["decoded_n"] == 5
    assert relevant["unsupported_n"] == 1
    assert (
        Decimal(relevant["decoded_n"])
        / Decimal(relevant["decoded_n"] + relevant["unsupported_n"])
        == Decimal("5") / Decimal("6")
    )
    trades = []
    for record in records:
        event = auditor.reconstruct_record(record, WALLET)
        if event:
            trades.append(event)
    aud = auditor.result_relevant_coverage(
        WALLET, records, trades, [],
        report_start=1788220800, report_end=1790812800,
    )
    assert aud["decoded_n"] >= 5
    assert aud["unsupported_n"] >= 1


def test_synthetic_before_after_replay_report():
    """No run-15 cached raws in this environment; synthetic before/after."""
    plains = [_sol_transfer(f"before-sol{i}", 3_000_000) for i in range(99)]
    buy = _edge_swap("before-buy", PUMP_SWAP, "33e685a4017f83ad", token_pre="0", token_post="1000", usdc_pre="2000000", usdc_post="0")
    records = [_wrap(row) for row in plains] + [_wrap(buy)]
    for offset, row in enumerate(records):
        row["raw"]["slot"] = 200 + offset
        row["slot"] = 200 + offset
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
    assert after["gate_passed"] is True
    assert after["PRODUCT_READY"] is False


def test_auditor_does_not_import_scanner_classifier():
    import inspect
    source = inspect.getsource(auditor)
    assert "scanner.mass_search.plain_tx_read" not in source
    assert not any(
        line.strip().startswith(("import scanner", "from scanner"))
        for line in source.splitlines()
    )
    assert auditor.auditor_classify_read is not classify_read_tx


def test_c2_allocate_assign_identity_mixed_sponsored_and_graft_stay_unreadable():
    """Material-1 negatives: first-path fail-closed proofs stay unread on app and auditor."""
    sale = _edge_swap("fc-sale", PUMP_SWAP, "33e685a4017f83ad", token_pre="1000", token_post="0", usdc_pre="0", usdc_post="2000000")
    cases = []

    allocate = json.loads(json.dumps(sale))
    allocate["transaction"]["message"]["instructions"].insert(0, {
        "programId": SYSTEM_ID, "parsed": {"type": "allocate", "info": {"account": WALLET, "space": 1}},
    })
    allocate["transaction"]["message"]["accountKeys"].append({"pubkey": SYSTEM_ID, "signer": False, "writable": False})
    allocate["meta"]["preBalances"].append(1)
    allocate["meta"]["postBalances"].append(1)
    cases.append(("allocate", allocate))

    assign = json.loads(json.dumps(sale))
    assign["transaction"]["message"]["instructions"].insert(0, {
        "programId": SYSTEM_ID, "parsed": {"type": "assign", "info": {"account": WALLET, "owner": SYSTEM_ID}},
    })
    cases.append(("assign", assign))

    nonce = json.loads(json.dumps(sale))
    nonce["transaction"]["message"]["instructions"].insert(0, {
        "programId": SYSTEM_ID, "parsed": {"type": "advanceNonce", "info": {
            "nonceAccount": COUNTER, "nonceAuthority": WALLET,
            "recentBlockhashesSysvar": "SysvarRecentB1ockHashes11111111111111111111",
        }},
    })
    cases.append(("nonce", nonce))

    unknown_outer = json.loads(json.dumps(sale))
    unknown_outer["transaction"]["message"]["instructions"].insert(0, {
        "programId": "UnknownOuter11111111111111111111111111111",
        "accounts": [WALLET], "data": _disc("deadbeefdeadbeef"),
    })
    unknown_outer["transaction"]["message"]["accountKeys"].append(
        {"pubkey": "UnknownOuter11111111111111111111111111111", "signer": False, "writable": False}
    )
    unknown_outer["meta"]["preBalances"].append(1)
    unknown_outer["meta"]["postBalances"].append(1)
    cases.append(("unknown-outer", unknown_outer))

    mixed = json.loads(json.dumps(sale))
    mixed["meta"]["innerInstructions"] = [{
        "index": 0,
        "instructions": [{
            "programId": TOKEN,
            "parsed": {"type": "transferChecked", "info": {
                "source": TOKEN_ATA, "destination": COUNTER_ATA, "mint": MINT,
                "tokenAmount": {"amount": "1000", "decimals": 6},
            }},
            "accounts": [],
        }],
    }]
    cases.append(("mixed-empty-accounts", mixed))

    identity = json.loads(json.dumps(sale))
    identity["meta"]["innerInstructions"] = [{
        "index": 0,
        "instructions": [{
            "programId": TOKEN,
            "parsed": {"type": "transferChecked", "info": {
                "source": TOKEN_ATA, "destination": COUNTER_ATA, "mint": MINT,
                "tokenAmount": {"amount": "1000", "decimals": 9},
            }},
        }],
    }]
    cases.append(("wrong-decimals", identity))

    sponsored = json.loads(json.dumps(sale))
    sponsored["meta"]["postBalances"][1] = TOKEN_RENT + 500_000_000
    cases.append(("sponsored-rent", sponsored))

    pump = _edge_swap("fc-pump", PUMP, "66063d1201daebea", token_pre="0", token_post="1000", usdc_pre="0", usdc_post="0")
    pump["meta"]["preBalances"][0] = 30_000_000_000
    pump["meta"]["postBalances"][0] = 30_000_000_000 - 1_000_000_000 - 5000
    pump["transaction"]["message"]["instructions"].insert(0, {
        "programId": SYSTEM_ID, "parsed": {"type": "advanceNonce", "info": {
            "nonceAccount": COUNTER, "nonceAuthority": WALLET,
            "recentBlockhashesSysvar": "SysvarRecentB1ockHashes11111111111111111111",
        }},
    })
    cases.append(("pump-nonce-graft", pump))

    okx = _edge_swap("fc-okx", OKX_DEX_ROUTER, "aa2955b184501f35", token_pre="0", token_post="1000", usdc_pre="5000000", usdc_post="0")
    okx["transaction"]["message"]["instructions"].insert(0, {
        "programId": "UnknownOuter11111111111111111111111111111",
        "accounts": [WALLET], "data": _disc("deadbeefdeadbeef"),
    })
    okx["transaction"]["message"]["accountKeys"].append(
        {"pubkey": "UnknownOuter11111111111111111111111111111", "signer": False, "writable": False}
    )
    okx["meta"]["preBalances"].append(1)
    okx["meta"]["postBalances"].append(1)
    cases.append(("okx-unknown-outer", okx))

    reconstruct_must_refuse = {
        "allocate", "assign", "nonce", "mixed-empty-accounts", "wrong-decimals", "pump-nonce-graft",
    }
    for label, raw in cases:
        assert classify_read_tx(raw, WALLET) is None or all(
            item.get("kind") not in ("buy", "sell", "conversion") for item in (classify_read_tx(raw, WALLET) or [])
        ), label
        decoded = _decode([raw])
        assert "buy" not in _kinds(decoded, raw["signature"])
        assert "sell" not in _kinds(decoded, raw["signature"])
        assert auditor.auditor_classify_read(raw, WALLET) is None or all(
            row.get("kind") not in ("buy", "sell", "conversion")
            for row in (auditor.auditor_classify_read(raw, WALLET) or [])
        ), label
        rebuilt = auditor.reconstruct_record(_wrap(raw), WALLET)
        if label in reconstruct_must_refuse:
            assert rebuilt is None or rebuilt.get("kind") not in ("buy", "sell", "conversion"), label


def test_c2_g2g_inner_large_sol_unreadable():
    raw = _sol_transfer("g2g-inner", 7_000_000_000)
    raw["transaction"]["message"]["accountKeys"].append({"pubkey": G2G_SPAM, "signer": False, "writable": False})
    raw["transaction"]["message"]["accountKeys"].append({"pubkey": "UnknownOuter11111111111111111111111111111", "signer": False, "writable": False})
    raw["meta"]["preBalances"].extend([1, 1])
    raw["meta"]["postBalances"].extend([1, 1])
    raw["transaction"]["message"]["instructions"].insert(0, {
        "programId": "UnknownOuter11111111111111111111111111111",
        "accounts": [WALLET], "data": _disc("afaf6d1f0d989bed"),
    })
    raw["transaction"]["message"]["instructions"].insert(1, {
        "programId": G2G_SPAM, "accounts": [WALLET], "data": _disc("afaf6d1f0d989bed"),
    })
    # Move G2G to inner so only unknown is outer.
    raw["meta"]["innerInstructions"] = [{"index": 0, "instructions": [raw["transaction"]["message"]["instructions"].pop(1)]}]
    assert classify_read_tx(raw, WALLET) is None
    assert auditor.auditor_classify_read(raw, WALLET) is None


def test_c2_pump_distribute_usdc_out_is_not_transfer_in():
    raw = _edge_swap("pump-usdc", PUMP, "623691610246ad2b", token_pre="0", token_post="1000", usdc_pre="5000000", usdc_post="0")
    classified = classify_read_tx(raw, WALLET)
    assert classified is None or classified[0]["kind"] != "transfer_in"
    aud = auditor.auditor_classify_read(raw, WALLET)
    assert aud is None or aud[0]["kind"] != "transfer_in"


def test_auditor_reads_compiled_system_transfer():
    lamports = 1_000_000
    payload = (2).to_bytes(4, "little") + lamports.to_bytes(8, "little")
    encoded = base64.b64encode(payload).decode("ascii")
    start = 2_000_000_000
    fee = 5000
    raw = _record(
        "compiled-sol",
        [WALLET, COUNTER, SYSTEM_ID, COMPUTE_ID],
        [
            {"programId": COMPUTE_ID, "accounts": [], "data": _disc("00")},
            {"programId": SYSTEM_ID, "accounts": [WALLET, COUNTER], "data": [encoded, "base64"]},
        ],
        pre_native=[start, 1_000_000_000, 1, 1],
        post_native=[start - lamports - fee, 1_000_000_000 + lamports, 1, 1],
        pre_token=[], post_token=[],
    )
    classified = auditor.auditor_classify_read(raw, WALLET)
    assert classified and classified[0]["kind"] == "non_trade"
    assert classify_read_tx(raw, WALLET)[0]["kind"] == "non_trade"


def test_c1_wrap_and_unwrap_reconcile_or_neither():
    wsol_ata = "PlainReadWsolAta1111111111111111111111112"
    keys = [WALLET, wsol_ata, SYSTEM_ID, TOKEN]
    wrap = _record(
        "wrap1", keys,
        [
            {"programId": SYSTEM_ID, "parsed": {"type": "transfer", "info": {"source": WALLET, "destination": wsol_ata, "lamports": 1_000_000_000}}},
            {"programId": TOKEN, "parsed": {"type": "syncNative", "info": {"account": wsol_ata}}},
        ],
        pre_native=[3_000_000_000, TOKEN_RENT, 1, 1],
        post_native=[1_999_995_000, TOKEN_RENT + 1_000_000_000, 1, 1],
        pre_token=[{"accountIndex": 1, "mint": "So11111111111111111111111111111111111111112", "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 9}}],
        post_token=[{"accountIndex": 1, "mint": "So11111111111111111111111111111111111111112", "owner": WALLET, "uiTokenAmount": {"amount": "1000000000", "decimals": 9}}],
    )
    unwrap = _record(
        "unwrap1", keys,
        [{"programId": TOKEN, "parsed": {"type": "closeAccount", "info": {"account": wsol_ata, "destination": WALLET, "owner": WALLET}}}],
        pre_native=[1_000_000_000, TOKEN_RENT + 1_000_000_000, 1, 1],
        post_native=[1_999_995_000 + TOKEN_RENT, 0, 1, 1],
        pre_token=[{"accountIndex": 1, "mint": "So11111111111111111111111111111111111111112", "owner": WALLET, "uiTokenAmount": {"amount": "1000000000", "decimals": 9}}],
        post_token=[],
    )
    wrap_app = classify_read_tx(wrap, WALLET)
    wrap_aud = auditor.auditor_classify_read(wrap, WALLET)
    unwrap_app = classify_read_tx(unwrap, WALLET)
    unwrap_aud = auditor.auditor_classify_read(unwrap, WALLET)
    # Either both wrap and unwrap read, or neither does.
    assert bool(wrap_app) == bool(unwrap_app)
    assert bool(wrap_aud) == bool(unwrap_aud)
    if wrap_app:
        assert wrap_app[0]["kind"] == "non_trade"
        assert unwrap_app[0]["kind"] == "non_trade"
    if wrap_aud:
        assert wrap_aud[0]["kind"] == "non_trade"
        assert unwrap_aud[0]["kind"] == "non_trade"


def _b58(data):
    from scanner.mass_search.fail_closed_preflight import _b58encode
    return _b58encode(data)


def _no_priced_trade(raw, address=WALLET):
    classified = classify_read_tx(raw, address)
    if classified and any(item.get("kind") in ("buy", "sell", "conversion") for item in classified):
        return False
    decoded = _decode([raw])
    if any(kind in ("buy", "sell", "conversion") for kind in _kinds(decoded, raw["signature"])):
        return False
    aud = auditor.auditor_classify_read(raw, address)
    if aud and any(row.get("kind") in ("buy", "sell", "conversion") for row in aud):
        return False
    rebuilt = auditor.reconstruct_record(_wrap(raw), address)
    if rebuilt and rebuilt.get("kind") in ("buy", "sell", "conversion"):
        return False
    return True


def _graft_feature(raw, feature, location, form):
    grafted = json.loads(json.dumps(raw))
    unknown = "UnknownInner11111111111111111111111111111"
    other = "CloseRecipient111111111111111111111111112"
    newacc = "NewAllocAccount1111111111111111111111112"
    if feature == "version_1":
        grafted["version"] = 1
        return grafted
    if feature == "jupiter_short":
        for instruction in grafted["transaction"]["message"]["instructions"]:
            if instruction.get("programId") == JUPITER or (isinstance(instruction.get("data"), list)):
                instruction["data"] = _disc("bb64facc31c4af14", extra=8)
                instruction["programId"] = JUPITER
        return grafted
    if feature == "sponsored_third_party":
        grafted["transaction"]["message"]["accountKeys"].extend([
            {"pubkey": newacc, "signer": False, "writable": True},
            {"pubkey": COUNTER, "signer": False, "writable": True},
        ])
        grafted["meta"]["preBalances"].extend([0, 6_000_000_000])
        grafted["meta"]["postBalances"].extend([5_000_000_000, 1_000_000_000])
        grafted["meta"]["postTokenBalances"].append({
            "accountIndex": len(grafted["transaction"]["message"]["accountKeys"]) - 2,
            "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6},
        })
        ix = (
            {"programId": SYSTEM_ID, "parsed": {"type": "createAccount", "info": {
                "source": COUNTER, "newAccount": newacc, "lamports": 5_000_000_000, "space": 165, "owner": TOKEN,
            }}}
            if form == "parsed" else
            {"programId": SYSTEM_ID, "accounts": [COUNTER, newacc], "data": [
                base64.b64encode((0).to_bytes(4, "little") + (5_000_000_000).to_bytes(8, "little") + (165).to_bytes(8, "little")).decode(),
                "base64",
            ]}
        )
        _place_ix(grafted, ix, location)
        return grafted
    if feature == "signer_missing":
        keys = grafted["transaction"]["message"]["accountKeys"]
        if keys and isinstance(keys[0], dict):
            keys[0]["signer"] = False
            keys[0]["pubkey"] = COUNTER
            keys.append({"pubkey": WALLET, "signer": False, "writable": True})
            grafted["meta"]["preBalances"].append(grafted["meta"]["preBalances"][0])
            grafted["meta"]["postBalances"].append(grafted["meta"]["postBalances"][0])
            grafted["transaction"]["message"]["header"]["numRequiredSignatures"] = 1
        return grafted

    payload = {
        "inner_assign_wallet": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "assign", "info": {"account": WALLET, "owner": unknown}}},
            "compiled": {"programId": SYSTEM_ID, "accounts": [WALLET], "data": [
                base64.b64encode(bytes([1, 0, 0, 0]) + bytes(range(1, 33))).decode(), "base64",
            ]},
        },
        "inner_allocate_2440": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "allocate", "info": {"account": newacc, "space": 2440}}},
            "compiled": {"programId": SYSTEM_ID, "accounts": [newacc], "data": [
                base64.b64encode(bytes([8, 0, 0, 0]) + (2440).to_bytes(8, "little")).decode(), "base64",
            ]},
        },
        "inner_allocate_2440_wallet": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "allocate", "info": {"account": WALLET, "space": 2440}}},
            "compiled": {"programId": SYSTEM_ID, "accounts": [WALLET], "data": [
                base64.b64encode(bytes([8, 0, 0, 0]) + (2440).to_bytes(8, "little")).decode(), "base64",
            ]},
        },
        "inner_unknown_program": {
            "parsed": {"programId": unknown, "accounts": [WALLET, TOKEN_ATA], "data": _disc("deadbeefdeadbeef")},
            "compiled": {"programId": unknown, "accounts": [WALLET, TOKEN_ATA], "data": _disc("deadbeefdeadbeef")},
        },
        "inner_advance_nonce": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "advanceNonce", "info": {
                "nonceAccount": COUNTER, "nonceAuthority": WALLET,
                "recentBlockhashesSysvar": "SysvarRecentB1ockHashes11111111111111111111",
            }}},
            "compiled": {"programId": SYSTEM_ID, "accounts": [COUNTER, "SysvarRecentB1ockHashes11111111111111111111", WALLET], "data": [
                base64.b64encode(bytes([4, 0, 0, 0])).decode(), "base64",
            ]},
        },
        "close_to_other": {
            "parsed": {"programId": TOKEN, "parsed": {"type": "closeAccount", "info": {
                "account": TOKEN_ATA, "destination": other, "owner": WALLET,
            }}},
            "compiled": {"programId": TOKEN, "accounts": [TOKEN_ATA, other, WALLET], "data": [
                base64.b64encode(bytes([9])).decode(), "base64",
            ]},
        },
        "mixed_data": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "transfer", "info": {
                "source": WALLET, "destination": WALLET, "lamports": 0,
            }}, "accounts": [WALLET], "data": [
                base64.b64encode(bytes([2, 0, 0, 0]) + (7).to_bytes(8, "little")).decode(), "base64",
            ]},
            "compiled": {"programId": SYSTEM_ID, "parsed": {"type": "transfer", "info": {
                "source": WALLET, "destination": WALLET, "lamports": 0,
            }}, "accounts": [WALLET], "data": [
                base64.b64encode(bytes([2, 0, 0, 0]) + (7).to_bytes(8, "little")).decode(), "base64",
            ]},
        },
        "compiled_wrong_decimals": {
            "parsed": {"programId": TOKEN, "parsed": {"type": "transferChecked", "info": {
                "source": TOKEN_ATA, "destination": COUNTER_ATA, "mint": MINT, "authority": WALLET,
                "tokenAmount": {"amount": "0", "decimals": 9},
            }}},
            "compiled": {"programId": TOKEN, "accounts": [TOKEN_ATA, MINT, COUNTER_ATA, WALLET], "data": [
                base64.b64encode(bytes([12]) + (0).to_bytes(8, "little") + bytes([9])).decode(), "base64",
            ]},
        },
        "nonce_admin": {
            "parsed": {"programId": SYSTEM_ID, "parsed": {"type": "withdrawNonceAccount", "info": {
                "nonceAccount": COUNTER, "destination": WALLET,
            }}},
            "compiled": {"programId": SYSTEM_ID, "accounts": [COUNTER, WALLET], "data": [
                base64.b64encode(bytes([5, 0, 0, 0])).decode(), "base64",
            ]},
        },
    }[feature][form]
    if feature in ("inner_unknown_program", "close_to_other", "inner_allocate_2440"):
        extra = other if feature == "close_to_other" else (unknown if feature == "inner_unknown_program" else newacc)
        grafted["transaction"]["message"]["accountKeys"].append({"pubkey": extra, "signer": False, "writable": True})
        grafted["meta"]["preBalances"].append(5_000_000_000 if feature == "close_to_other" else 1)
        grafted["meta"]["postBalances"].append(0 if feature == "close_to_other" else 1)
    if feature == "close_to_other":
        grafted["meta"]["preTokenBalances"].append({
            "accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": "0", "decimals": 6},
        })
    _place_ix(grafted, payload, location)
    return grafted


def _place_ix(raw, instruction, location):
    if location == "outer":
        raw["transaction"]["message"]["instructions"].insert(0, instruction)
        return
    groups = raw["meta"].setdefault("innerInstructions", [])
    if not isinstance(groups, list) or not groups:
        raw["meta"]["innerInstructions"] = [{"index": 0, "instructions": [instruction]}]
        return
    groups[0].setdefault("instructions", []).append(instruction)


def test_preflight_mutation_matrix_unreadable_on_app_and_auditor():
    """Every pricing path × unsafe feature × outer/inner × parsed/compiled is unreadable."""
    carriers = {
        "c2": _edge_swap("mtx-c2", OKX_DEX_ROUTER, "aa2955b184501f35", token_pre="0", token_post="1000", usdc_pre="5000000", usdc_post="0"),
        "c1": _token_move("mtx-c1", inbound=True),
        "first_path": _edge_swap("mtx-fp", PUMP_SWAP, "33e685a4017f83ad", token_pre="1000", token_post="0", usdc_pre="0", usdc_post="2000000"),
        "net_balance": _edge_swap("mtx-nb", OKX_DEX_ROUTER, "aa2955b184501f35", token_pre="0", token_post="1000", usdc_pre="5000000", usdc_post="0"),
    }
    features = (
        "inner_assign_wallet", "inner_allocate_2440", "inner_allocate_2440_wallet",
        "inner_unknown_program", "inner_advance_nonce", "close_to_other",
        "mixed_data", "compiled_wrong_decimals", "nonce_admin",
    )
    tx_features = ("version_1", "jupiter_short", "sponsored_third_party", "signer_missing")
    failures = []
    for path, carrier in carriers.items():
        for feature in features:
            for location in ("outer", "inner"):
                if feature == "inner_advance_nonce" and location == "outer" and path in ("first_path", "c1"):
                    # Outer durable nonce stays a first-path layout exception.
                    continue
                for form in ("parsed", "compiled"):
                    grafted = _graft_feature(carrier, feature, location, form)
                    if not _no_priced_trade(grafted):
                        failures.append(f"{path}/{feature}/{location}/{form}")
        for feature in tx_features:
            if feature == "signer_missing" and path == "c1":
                continue
            grafted = _graft_feature(carrier, feature, "inner", "parsed")
            if not _no_priced_trade(grafted):
                failures.append(f"{path}/{feature}")
    assert not failures, failures


def test_preflight_missing_inners_refuse_priced_trades():
    raw = _edge_swap("no-ix", OKX_DEX_ROUTER, "aa2955b184501f35", token_pre="0", token_post="1000", usdc_pre="5000000", usdc_post="0")
    for inner in (None, [], "absent"):
        grafted = json.loads(json.dumps(raw))
        if inner == "absent":
            grafted["meta"].pop("innerInstructions", None)
        else:
            grafted["meta"]["innerInstructions"] = inner
        assert _no_priced_trade(grafted), inner


def test_okx_vault_sol_cap_matches_jito():
    from scanner.mass_search.plain_tx_read import JITO_MAX_NATIVE_LAMPORTS
    keys = [WALLET, OKX_VAULT, COMPUTE_ID, COUNTER]
    over = _record(
        "vault-over", keys,
        [{"programId": OKX_VAULT, "accounts": [WALLET], "data": _disc("709fd333ee46d43c")},
         {"programId": SYSTEM_ID, "parsed": {"type": "transfer", "info": {
             "source": WALLET, "destination": COUNTER, "lamports": JITO_MAX_NATIVE_LAMPORTS + 1,
         }}}],
        pre_native=[2_000_000_000_000, 1, 1, 1],
        post_native=[2_000_000_000_000 - JITO_MAX_NATIVE_LAMPORTS - 1 - 5000, 1, 1, 1 + JITO_MAX_NATIVE_LAMPORTS + 1],
        pre_token=[], post_token=[],
    )
    assert classify_read_tx(over, WALLET) is None
    assert auditor.auditor_classify_read(over, WALLET) is None


def test_product_report_lp_and_conversion_are_blocking_unknown():
    from scanner.accounting import analyze
    buy = {
        "kind": "buy", "timestamp": IN_WINDOW, "order": 1, "mint": MINT,
        "quantity_raw": "1000000", "decimals": 6, "amount_sol": "1",
        "classification": "unknown", "signature": "buy-lp", "path": "ix.0",
        "evidence": ["a" * 64], "paid_by_wallet": True,
    }
    lp = {
        "kind": "lp", "timestamp": IN_WINDOW + 1, "order": 2, "mint": MINT,
        "quantity_raw": "1000000", "decimals": 6, "classification": "lp",
        "touches_result_relevant_mint": True, "signature": "lp1", "path": "ix.1",
        "evidence": ["b" * 64],
    }
    conversion = {
        "kind": "conversion", "timestamp": IN_WINDOW + 2, "order": 3, "mint": MINT,
        "quantity_raw": "1", "decimals": 6, "classification": "conversion",
        "signature": "conv1", "path": "ix.2", "evidence": ["c" * 64],
    }
    report = analyze(
        [buy, lp], REPORT_START, REPORT_END,
        opening_equity="0", closing_equity="0",
        external_deposits="0", external_withdrawals="0",
    )
    assert report["counts"]["unresolved"] >= 1 or any(row["status"] == "unresolved" for row in report["positions"])
    assert report["metrics"]["profit_sol"]["value"] is None or report["counts"]["unresolved"]
    converted = analyze(
        [buy, conversion], REPORT_START, REPORT_END,
        opening_equity="0", closing_equity="0",
        external_deposits="0", external_withdrawals="0",
    )
    assert converted["metrics"]["profit_sol"]["value"] is None or any(
        row["status"] == "unresolved" for row in converted["positions"]
    )


def test_jxt_okx_wrap_inner_assign_drops_out_of_proven(tmp_path):
    """E2E: OKX-wrapped first-path buy + inner wallet assign must leave proven."""
    from datetime import datetime, timezone
    from scanner.investigation import REVIEWED_OUTER_VENUES
    from scanner.mass_search.history_ingest import replay_cached_history_to_report
    from scanner.mass_search.research_profile import (
        attach_live_independent_audit,
        build_research_profile,
        default_filters,
    )
    from scanner.storage import Store
    from tests.test_live_e2e_d1_d9 import JXT, JXT_PAGES, _require_pages

    records = _require_pages(JXT_PAGES)
    end = datetime(2026, 9, 21, tzinfo=timezone.utc)
    start = end.timestamp() - 30 * 86400
    target = None
    for record in records:
        stamp = record.get("blockTime") or 0
        if not (start <= stamp < end.timestamp()):
            continue
        raw = record
        message = (raw.get("transaction") or {}).get("message") or {}
        meta = raw.get("meta") or {}
        if not meta.get("innerInstructions"):
            continue
        keys = [
            item["pubkey"] if isinstance(item, dict) else item
            for item in (message.get("accountKeys") or [])
        ]
        loaded = meta.get("loadedAddresses") or {}
        keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
        if not keys or keys[0] != JXT:
            continue
        decoded = decode_supported_swaps([_wrap(raw)], JXT)
        trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
        if not trades or any("wallet-edge" in (row.get("reason") or "") for row in trades):
            continue
        if trades[0].get("kind") != "buy":
            continue
        target = raw
        break
    assert target is not None, "need an in-window first-path JXT buy"
    grafted = json.loads(json.dumps(target))
    message = grafted["transaction"]["message"]
    keys = [item["pubkey"] if isinstance(item, dict) else item for item in message["accountKeys"]]
    loaded = grafted["meta"].setdefault("loadedAddresses", {})
    keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    outer = next(
        index for index, instruction in enumerate(message["instructions"])
        if keys[instruction.get("programIdIndex", -1)] in REVIEWED_OUTER_VENUES
        or instruction.get("programId") in REVIEWED_OUTER_VENUES
    )
    for extra in (OKX_DEX_ROUTER, SYSTEM_ID):
        if extra not in keys:
            message["accountKeys"].append(
                {"pubkey": extra, "signer": False, "writable": False}
                if isinstance(message["accountKeys"][0], dict) else extra
            )
            grafted["meta"]["preBalances"].append(1)
            grafted["meta"]["postBalances"].append(1)
            keys.append(extra)
    okx_index = keys.index(OKX_DEX_ROUTER)
    message["instructions"][outer]["programIdIndex"] = okx_index
    message["instructions"][outer].pop("programId", None)
    rest = b""
    data = message["instructions"][outer].get("data")
    if isinstance(data, str):
        from scanner.mass_search.plain_tx_read import _b58decode
        rest = _b58decode(data)[8:]
    message["instructions"][outer]["data"] = _b58(bytes.fromhex("aa2955b184501f35") + rest)
    group = next((item for item in grafted["meta"]["innerInstructions"] if item.get("index") == outer), None)
    if group is None:
        group = {"index": outer, "instructions": []}
        grafted["meta"]["innerInstructions"].append(group)
    group["instructions"].append({
        "programIdIndex": keys.index(SYSTEM_ID),
        "accounts": [keys.index(JXT)],
        "data": _b58(bytes([1, 0, 0, 0]) + bytes(range(1, 33))),
        "stackHeight": 2,
    })
    sig = (target.get("transaction") or {}).get("signatures") or [target.get("signature")]
    signature = sig[0]
    decoded = decode_supported_swaps([_wrap(grafted)], JXT)
    assert not any(row.get("kind") in ("buy", "sell", "conversion") and row.get("signature") == signature for row in decoded.get("events") or [])
    rebuilt = auditor.reconstruct_record(_wrap(grafted), JXT)
    assert rebuilt is None or rebuilt.get("kind") not in ("buy", "sell", "conversion")
    swapped = []
    for record in records:
        rec_sig = ((record.get("transaction") or {}).get("signatures") or [record.get("signature")])[0]
        swapped.append(grafted if rec_sig == signature else record)
    from scanner.mass_search.live_e2e import window_bounds
    bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    store = Store(tmp_path / "jxt-graft")
    report = replay_cached_history_to_report(
        store, address=JXT, records=swapped,
        window_start=bounds["report_start_inclusive"],
        window_end=bounds["report_end_exclusive"],
        acquisition_start=bounds["history_start_inclusive"],
    )["report"]
    profile = build_research_profile(report, filters=default_filters())
    audit = attach_live_independent_audit(report, profile, swapped, address=JXT)
    store.close()
    level = (profile.get("qualification_level") or {}).get("level")
    assert level != "stronger_research_shortlist"
    assert audit.get("independently_audited") is not True
    assert audit.get("status") != "independently_audited"
    assert classify_read_tx(grafted, JXT) is None or all(
        item.get("kind") not in ("buy", "sell", "conversion") for item in (classify_read_tx(grafted, JXT) or [])
    )
