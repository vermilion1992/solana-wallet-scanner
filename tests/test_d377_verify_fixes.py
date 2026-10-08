"""Independent-verify 377a5cf defects D377-1..9. Offline only."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import (
    LAMPORTS,
    RAYDIUM_CLMM,
    USDC,
    USDT,
    WSOL,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.g3_history import load_cached_page, persist_page
from scanner.mass_search.live_e2e import Phase4Timeout
from scanner.mass_search.qualification_gates import (
    coverage_shares,
    mandatory_coverage_gate,
    raw_economic_keys_for_tx,
    raw_economic_trades_by_utc_day,
)
from scanner.mass_search.record_breakdown import partition_records
from scanner.mass_search.result_relevant_coverage import build_result_relevant
from scanner.mass_search.seed_sources import (
    _dex_trade_timestamp,
    dex_trades_per_utc_day,
    estimate_nansen_dex_trades_count,
)
from scanner.storage import Store
import tools.independent_episode_audit as auditor

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM = "11111111111111111111111111111111"
JUP6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
WALLET = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
MINT = "Nb3Mint11111111111111111111111111111111112"
WSOL_ATA = "Nb3WsolAta1111111111111111111111111111112"
TOKEN_ATA = "Nb3TokAta11111111111111111111111111111112"
POOL_WSOL = "Nb3PoolWsol111111111111111111111111111112"
POOL_TOK = "Nb3PoolTok1111111111111111111111111111112"
THIRD = "Nb3ThirdParty1111111111111111111111111112"
THIRD_ATA = "Nb3ThirdAta111111111111111111111111111112"
FAKE_OUTER = "FakeOuter11111111111111111111111111111112"
FWG = "FWgfv6jS111111111111111111111111111111112"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = B58[rem] + out
    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break
    return ("1" * pad) + (out or "1")


def _clmm_buy(
    *,
    native_post=1_999_995_000,
    extra_outers=None,
    extra_token_balances=None,
    token_pre="0",
    token_post="1000000000",
    wsol_pre="1000000000",
    wsol_post="0",
    signature="Nb3SigBuy111111111111111111111111111111111111111111111111111",
):
    outers = [
        {
            "programId": RAYDIUM_CLMM,
            "accounts": [WALLET, WSOL_ATA, TOKEN_ATA, POOL_WSOL, POOL_TOK],
            "data": "11111111",
        },
    ]
    outers.extend(extra_outers or [])
    pre_token = [
        {"accountIndex": 1, "mint": WSOL, "owner": WALLET, "uiTokenAmount": {"amount": wsol_pre, "decimals": 9}},
        {"accountIndex": 2, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
        {"accountIndex": 3, "mint": WSOL, "owner": "pool", "uiTokenAmount": {"amount": "0", "decimals": 9}},
        {"accountIndex": 4, "mint": MINT, "owner": "pool", "uiTokenAmount": {"amount": token_post, "decimals": 6}},
    ]
    post_token = [
        {"accountIndex": 1, "mint": WSOL, "owner": WALLET, "uiTokenAmount": {"amount": wsol_post, "decimals": 9}},
        {"accountIndex": 2, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}},
        {"accountIndex": 3, "mint": WSOL, "owner": "pool", "uiTokenAmount": {"amount": wsol_pre, "decimals": 9}},
        {"accountIndex": 4, "mint": MINT, "owner": "pool", "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
    ]
    if extra_token_balances:
        pre_token.extend(extra_token_balances.get("pre") or [])
        post_token.extend(extra_token_balances.get("post") or [])
    return {
        "transaction": {
            "signatures": [signature],
            "message": {
                "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 1},
                "accountKeys": [
                    WALLET, WSOL_ATA, TOKEN_ATA, POOL_WSOL, POOL_TOK,
                    THIRD, THIRD_ATA, RAYDIUM_CLMM, TOKEN, SYSTEM, FAKE_OUTER,
                ],
                "instructions": outers,
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 1_002_039_280, 2_039_280, 0, 0, 2_000_000_000, 2_039_280, 1, 1, 1, 1],
            "postBalances": [native_post, 2_039_280, 2_039_280, 0, 0, 1_500_000_000, 2_039_280, 1, 1, 1, 1],
            "preTokenBalances": pre_token,
            "postTokenBalances": post_token,
            "innerInstructions": [{
                "index": 0,
                "instructions": [
                    {
                        "programId": TOKEN,
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": WSOL_ATA,
                                "destination": POOL_WSOL,
                                "authority": WALLET,
                                "amount": "1000000000",
                                "mint": WSOL,
                            },
                        },
                    },
                    {
                        "programId": TOKEN,
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": POOL_TOK,
                                "destination": TOKEN_ATA,
                                "authority": "pool",
                                "amount": "1000000000",
                                "mint": MINT,
                            },
                        },
                    },
                ],
            }],
        },
        "blockTime": 1_780_000_000,
        "slot": 1,
    }


def _trades(decoded):
    return [
        event for event in decoded.get("events") or []
        if event.get("kind") in {"buy", "sell", "conversion"}
    ]


def test_d377_3_n0_control_still_decodes():
    raw = _clmm_buy()
    app = net_balance_reviewed_swap(raw, WALLET)
    aud = auditor.reconstruct_record(raw, WALLET)
    assert app and aud
    assert app["kind"] == "buy"
    assert abs(Decimal(app["settlement"])) == Decimal(1_000_000_000)
    assert Decimal(str(aud["consideration_sol"])) == Decimal("1")


def test_d377_3_n1_third_party_sol_inflow_fails_closed():
    raw = _clmm_buy(
        native_post=2_499_995_000,
        extra_outers=[{
            "programId": SYSTEM,
            "parsed": {"type": "transfer", "info": {"source": THIRD, "destination": WALLET, "lamports": 500_000_000}},
        }],
    )
    assert net_balance_reviewed_swap(raw, WALLET) is None
    assert auditor.reconstruct_record(raw, WALLET) is None
    assert _trades(decode_supported_swaps(canonical_decode_records([raw]), WALLET)) == []


def test_d377_3_n12_almost_full_inflow_fails_closed():
    raw = _clmm_buy(
        native_post=2_949_995_000,
        extra_outers=[{
            "programId": SYSTEM,
            "parsed": {"type": "transfer", "info": {"source": THIRD, "destination": WALLET, "lamports": 950_000_000}},
        }],
    )
    assert net_balance_reviewed_swap(raw, WALLET) is None
    assert auditor.reconstruct_record(raw, WALLET) is None


def test_d377_3_n3_token_inflow_fails_closed():
    raw = _clmm_buy(
        token_pre="1000000000",
        token_post="500000000",
        wsol_pre="0",
        wsol_post="1000000000",
        extra_outers=[{
            "programId": TOKEN,
            "parsed": {
                "type": "transfer",
                "info": {
                    "source": THIRD_ATA,
                    "destination": TOKEN_ATA,
                    "authority": THIRD,
                    "amount": "500000000",
                    "mint": MINT,
                },
            },
        }],
        extra_token_balances={
            "pre": [{"accountIndex": 6, "mint": MINT, "owner": THIRD, "uiTokenAmount": {"amount": "500000000", "decimals": 6}}],
            "post": [{"accountIndex": 6, "mint": MINT, "owner": THIRD, "uiTokenAmount": {"amount": "0", "decimals": 6}}],
        },
    )
    # Flip the inner token direction to a sell of 1000M.
    raw["meta"]["innerInstructions"][0]["instructions"] = [
        {
            "programId": TOKEN,
            "parsed": {
                "type": "transfer",
                "info": {
                    "source": TOKEN_ATA,
                    "destination": POOL_TOK,
                    "authority": WALLET,
                    "amount": "1000000000",
                    "mint": MINT,
                },
            },
        },
        {
            "programId": TOKEN,
            "parsed": {
                "type": "transfer",
                "info": {
                    "source": POOL_WSOL,
                    "destination": WSOL_ATA,
                    "authority": "pool",
                    "amount": "1000000000",
                    "mint": WSOL,
                },
            },
        },
    ]
    assert net_balance_reviewed_swap(raw, WALLET) is None
    assert auditor.reconstruct_record(raw, WALLET) is None


def test_d377_3_s5_unknown_outer_credit_fails_closed():
    raw = _clmm_buy(native_post=2_499_995_000, extra_outers=[{
        "programId": FAKE_OUTER,
        "accounts": [WALLET],
        "data": "11111111",
    }])
    assert net_balance_reviewed_swap(raw, WALLET) is None
    assert auditor.reconstruct_record(raw, WALLET) is None


def test_d377_3_auditor_method_is_not_the_app_net():
    src = Path(auditor.__file__).read_text(encoding="utf-8")
    assert "independent-net-balance" in src
    assert "_route_cpi_disagrees_with_wallet" in src
    assert "from scanner" not in src
    assert auditor._route_cpi_disagrees_with_wallet is not None


def _swap_record(wallet, sig, *, sol_down=400_000, token_up=1000, logs=(), program=JUP6, extra_ix=None):
    instructions = [{"programId": program, "accounts": [0], "data": "11111111"}]
    if extra_ix:
        instructions.extend(extra_ix)
    return {
        "transaction": {
            "signatures": [sig],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [
                    {"pubkey": wallet, "signer": True, "writable": True},
                    {"pubkey": program, "signer": False, "writable": False},
                ],
                "instructions": instructions,
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10_000_000_000, 1],
            "postBalances": [10_000_000_000 - sol_down - 5000, 1],
            "preTokenBalances": [{"accountIndex": 0, "owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "0", "decimals": 6}}],
            "postTokenBalances": [{"accountIndex": 0, "owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": str(token_up), "decimals": 6}}],
            "logMessages": list(logs),
        },
        "blockTime": int(datetime(2026, 10, 3, tzinfo=timezone.utc).timestamp()),
    }


def test_d377_2_lp_log_with_jupiter_swap_still_counts():
    record = _swap_record(
        FWG, "lp-hop", sol_down=400_000, token_up=1000,
        logs=("Program log: Instruction: SharedAccountsRoute", "Program log: Instruction: AddLiquidity2"),
    )
    assert raw_economic_keys_for_tx(record, FWG) >= 1


def test_d377_2_tip_airdrop_with_swap_ix_counts():
    record = _swap_record(
        FWG, "tip-air", sol_down=233_522, token_up=50,
        logs=("Program log: Instruction: SharedAccountsRoute",),
    )
    assert raw_economic_keys_for_tx(record, FWG) >= 1


def test_d377_2_tip_airdrop_without_swap_ix_excluded():
    record = _swap_record(
        FWG, "tip-only", sol_down=233_522, token_up=50, program=SYSTEM,
        logs=("Program log: Transfer",),
    )
    record["transaction"]["message"]["instructions"] = [{
        "programId": SYSTEM,
        "parsed": {"type": "transfer", "info": {"source": FWG, "destination": THIRD, "lamports": 233_522}},
    }]
    assert raw_economic_keys_for_tx(record, FWG) == 0


def test_d377_2_zero_net_jupiter_arb_counts():
    record = {
        "transaction": {
            "signatures": ["arb"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [{"pubkey": FWG, "signer": True}, {"pubkey": JUP6}],
                "instructions": [{"programId": JUP6, "accounts": [0], "data": "11111111"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10_000_000_000, 1],
            "postBalances": [10_000_000_000 - 5000, 1],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "logMessages": ["Program log: Instruction: Route", "Program log: Instruction: SharedAccountsRoute"],
        },
        "blockTime": int(datetime(2026, 8, 26, tzinfo=timezone.utc).timestamp()),
    }
    assert raw_economic_keys_for_tx(record, FWG) == 1


def test_d377_2_fwgfv6js_shape_reaches_26():
    records = []
    day = int(datetime(2026, 10, 3, tzinfo=timezone.utc).timestamp())
    for i in range(21):
        rec = _swap_record(FWG, f"real-{i}", sol_down=1_000_000, token_up=2000,
                           logs=("Program log: Instruction: SharedAccountsRoute",))
        rec["blockTime"] = day + i
        records.append(rec)
    for i, spent in enumerate((110_690, 150_000, 180_000, 200_000, 233_522)):
        rec = _swap_record(FWG, f"tip-{i}", sol_down=spent, token_up=40,
                           logs=("Program log: Instruction: SharedAccountsRoute",))
        rec["blockTime"] = day + 40 + i
        records.append(rec)
    by_day, _ = raw_economic_trades_by_utc_day(records, FWG)
    assert max(by_day.values() or [0]) >= 26


def test_d377_1_usdt_dust_cannot_raise_coverage():
    wallet = "UsdtDust111111111111111111111111111111111"
    stamp = int(datetime(2026, 5, 28, tzinfo=timezone.utc).timestamp())
    decoded = []
    records = []
    for i in range(500):
        sig = f"sol-buy-{i}"
        decoded.append({"signature": sig, "kind": "buy", "amount_sol": "0.1", "mint": MINT})
        records.append({
            "blockTime": stamp + i,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [wallet, JUP6], "instructions": [{"programId": JUP6}]}},
            "meta": {
                "err": None, "fee": 5000,
                "preBalances": [10**10, 1], "postBalances": [10**10 - 100_000_000, 1],
                "preTokenBalances": [{"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "0"}}],
                "postTokenBalances": [{"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "10"}}],
            },
        })
    for i in range(500):
        sig = f"usdt-buy-{i}"
        decoded.append({"signature": sig, "kind": "buy", "amount_usdt": "100", "mint": MINT})
        records.append({
            "blockTime": stamp + 600 + i,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [wallet, JUP6], "instructions": [{"programId": JUP6}]}},
            "meta": {
                "err": None, "fee": 5000,
                "preBalances": [10**10, 1], "postBalances": [10**10 - 5000, 1],
                "preTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "100000000"}},
                    {"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "0"}},
                ],
                "postTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "0"}},
                    {"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "10"}},
                ],
            },
        })
    for i in range(10):
        sig = f"hidden-sol-{i}"
        records.append({
            "blockTime": stamp + 1300 + i,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [wallet, JUP6], "instructions": [{"programId": JUP6}]}},
            "meta": {
                "err": None, "fee": 5000,
                "preBalances": [10**10, 1], "postBalances": [10**10 - 5_000_000_000, 1],
                "preTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "1"}},
                    {"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "0"}},
                ],
                "postTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "0"}},
                    {"owner": wallet, "mint": MINT, "uiTokenAmount": {"amount": "10"}},
                ],
            },
        })
    start = datetime.fromtimestamp(stamp - 3600, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(stamp + 4000, tz=timezone.utc).isoformat()
    decoded_blob = {"events": decoded, "unresolved": []}
    breakdown = partition_records(records, decoded_blob, wallet, window_start=start, window_end=end)
    breakdown["result_relevant"] = build_result_relevant(
        records, decoded_blob, wallet, report_start=start, report_end=end,
        ledger=[{"mint": MINT}],
    )
    shares = breakdown["unsupported_swap_share_in_window"]["by_consideration"]
    assert "SOL" in shares
    assert Decimal(str(shares["SOL"])) > Decimal("0")
    gate = mandatory_coverage_gate({"record_breakdown": breakdown}, min_share=Decimal("0.95"))
    assert gate.get("passed") is not True
    cov = coverage_shares({"record_breakdown": breakdown})
    assert cov["value_share"] is not None
    assert cov["value_share"] < Decimal("0.99")


def test_d377_1_adding_bucket_never_raises_coverage():
    """Property: booking an extra quote bucket cannot raise any resolved share."""
    decoded = {"SOL": Decimal("50"), "USDC": Decimal("0"), "USDT": Decimal("0")}
    unsupported = {"SOL": Decimal("50"), "USDC": Decimal("0"), "USDT": Decimal("0")}
    sol_share = unsupported["SOL"] / (decoded["SOL"] + unsupported["SOL"])
    # Adding a USDT dust bucket for the same unsupported txs.
    decoded2 = dict(decoded)
    unsupported2 = dict(unsupported)
    unsupported2["USDT"] = Decimal("0.00001")
    shares = {}
    for asset in ("SOL", "USDC", "USDT"):
        total = decoded2[asset] + unsupported2[asset]
        if total:
            shares[asset] = unsupported2[asset] / total
    # SOL share is unchanged; a new bucket can only add a constraint.
    assert shares["SOL"] == sol_share
    resolved_before = 1 - sol_share
    resolved_after = min(1 - share for share in shares.values())
    assert resolved_after <= resolved_before


def test_d377_5_phase4_timeout_is_base_exception():
    assert issubclass(Phase4Timeout, BaseException)
    assert not issubclass(Phase4Timeout, Exception)
    try:
        raise Phase4Timeout("budget")
    except Exception:
        pytest.fail("Phase4Timeout must not be caught by except Exception")
    except Phase4Timeout:
        pass


def test_d377_6_interrupted_chunked_persist_keeps_old_generation(tmp_path):
    store = Store(tmp_path)
    store.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 6_000)
    old = [{"i": i, "pad": "y" * 200} for i in range(30)]
    persist_page(store, "auth", "W", 0, {"kind": "g3-history-page-v2", "records": old})
    assert len((load_cached_page(store, "auth", "W", 0) or {}).get("records") or []) == 30
    real_put = store.put

    def flaky(kind, key, value):
        if ":chunk:" not in str(key) and value.get("chunked"):
            raise RuntimeError("interrupt before new manifest")
        return real_put(kind, key, value)

    store.put = flaky
    new = [{"i": i, "pad": "z" * 200} for i in range(25)]
    with pytest.raises(RuntimeError):
        persist_page(store, "auth", "W", 0, {"kind": "g3-history-page-v2", "records": new})
    store.put = real_put
    loaded = load_cached_page(store, "auth", "W", 0)
    assert loaded is not None
    assert len(loaded.get("records") or []) == 30
    store.close()


def test_d377_7_auditor_excludes_meteora_claim_fee_by_disc():
    disc = hashlib.sha256(b"global:ClaimFee2").digest()[:8]
    record = {
        "transaction": {
            "signatures": ["claim"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [{"pubkey": WALLET, "signer": True}, {"pubkey": auditor.METEORA_DLMM}],
                "instructions": [{"programId": auditor.METEORA_DLMM, "data": _b58(disc + b"\x00\x00"), "accounts": [0]}],
            },
        },
        "meta": {
            "err": None,
            "preTokenBalances": [{"owner": WALLET, "mint": MINT, "uiTokenAmount": {"amount": "1000"}}],
            "postTokenBalances": [{"owner": WALLET, "mint": MINT, "uiTokenAmount": {"amount": "900"}}],
            "logMessages": ["Program log: Instruction: ClaimFee2"],
        },
    }
    assert auditor.raw_economic_keys_for_tx(record, WALLET) == 0
    src = Path(auditor.__file__).read_text(encoding="utf-8")
    assert "AUDITOR_LP_DISCS" in src
    assert "Instruction: \\w*(?:AddLiquidity" not in src


def test_d377_8_dex_trades_max_pages_rejects_below_one():
    with pytest.raises(ValueError, match=">= 1"):
        estimate_nansen_dex_trades_count(wallet_cap=2, max_pages=0)
    with pytest.raises(ValueError, match=">= 1"):
        estimate_nansen_dex_trades_count(wallet_cap=2, max_pages=-5)
    assert estimate_nansen_dex_trades_count(wallet_cap=2, max_pages=3) == 6


def test_d377_9_naive_dex_trade_timestamps_are_utc():
    rows = []
    for i in range(20):
        rows.append({"transaction_hash": f"a{i}", "block_timestamp": "2026-08-26T22:00:00"})
    for i in range(8):
        rows.append({"transaction_hash": f"b{i}", "block_timestamp": "2026-08-27T01:00:00"})
    stats = dex_trades_per_utc_day(rows)
    assert stats["per_day"].get("2026-08-26") == 20
    assert stats["per_day"].get("2026-08-27") == 8
    assert _dex_trade_timestamp({"block_timestamp": "2026-08-26T22:00:00"}) == int(
        datetime(2026, 8, 26, 22, tzinfo=timezone.utc).timestamp()
    )


def test_d377_4_token_list_page_is_not_a_token_source():
    from scanner.mass_search.live_e2e import _tokens_from_imported_page_bodies
    listing = {
        "success": True,
        "data": {"items": [
            {"address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "liquidity": 1, "mc": 1},
            {"address": "So11111111111111111111111111111111111111112", "liquidity": 1, "mc": 1},
        ]},
    }
    assert _tokens_from_imported_page_bodies([listing]) == []
    request_page = {"request": {"address": "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}}
    assert _tokens_from_imported_page_bodies([request_page]) == ["USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"]
    import scanner.mass_search.live_e2e as live_e2e
    assert not hasattr(live_e2e, "_tokens_from_import_filenames")
