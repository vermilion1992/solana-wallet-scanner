"""D1–D9 hermetic fixes for PR #7. Offline only; no live calls."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    DECODER_VERSION,
    DFLOW,
    DGMG,
    USDC,
    USDT,
    decode_supported_swaps,
)
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import align_wallet_bounds, window_bounds
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/live-e2e-phase3"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
UNKNOWN_INNER = "UnkInner11111111111111111111111111111111111"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _app_trades(payload):
    decoded = decode_supported_swaps(
        canonical_decode_records([payload["record"]]), payload["address"]
    )
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    return decoded, trades


def test_decoder_version_is_v23():
    assert DECODER_VERSION == "spot-v23-quote-rent-inner-v1"


def test_d1_auditor_includes_dgmg_router_fee():
    payload = _load("jxt-dgmg-buy.json")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    assert Decimal(str(trades[0]["amount_sol"])) == Decimal("0.101754399")
    aud = auditor.reconstruct_record(payload["record"], JXT)
    assert aud["program"] == DGMG
    assert Decimal(aud["consideration_sol"]) == Decimal("0.101754399")
    assert Decimal(aud["consideration_sol"]) == Decimal(str(trades[0]["amount_sol"]))


def test_d2_usdc_dflow_rent_only_native_is_not_cross_settlement():
    payload = copy.deepcopy(_load("dflow-swap2-token-usdc.json"))
    raw = payload["record"]
    message = raw["transaction"]["message"]
    meta = raw["meta"]
    keys = [
        item["pubkey"] if isinstance(item, dict) else item
        for item in message["accountKeys"]
    ]
    wallet = payload["address"]
    wallet_idx = keys.index(wallet)
    new_ata = "NewAtaRent11111111111111111111111111111111"
    loaded = meta.setdefault("loadedAddresses", {})
    readonly = list(loaded.get("readonly") or [])
    readonly.append(new_ata)
    loaded["readonly"] = readonly
    meta["preBalances"].append(0)
    meta["postBalances"].append(2_039_280)
    meta["postBalances"][wallet_idx] -= 2_039_280
    route_index = next(
        i
        for i, ins in enumerate(message["instructions"])
        if isinstance(ins.get("programIdIndex"), int) and keys[ins["programIdIndex"]] == DFLOW
        or ins.get("programId") == DFLOW
    )
    groups = meta.setdefault("innerInstructions", [])
    group = next((g for g in groups if g.get("index") == route_index), None)
    if group is None:
        group = {"index": route_index, "instructions": []}
        groups.append(group)
    group["instructions"].append({
        "programId": "11111111111111111111111111111111",
        "parsed": {
            "type": "createAccount",
            "info": {
                "source": wallet,
                "newAccount": new_ata,
                "owner": TOKEN_PROGRAM,
                "lamports": 2_039_280,
                "space": 165,
            },
        },
    })
    decoded, trades = _app_trades(payload)
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    assert "cross-settlement" not in reasons, reasons
    assert len(trades) == 1
    assert trades[0]["settlement_asset"] == "USDC"


def test_d3_unknown_inner_touching_wallet_blocks():
    payload = copy.deepcopy(_load("dflow-swap2-token-usdc.json"))
    raw = payload["record"]
    if "raw" in raw:
        raw = raw["raw"]
        if isinstance(raw, dict) and "result" in raw:
            raw = raw["result"]
    phoenix = "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY"
    message = raw["transaction"]["message"]
    meta = raw["meta"]
    keys = [
        item["pubkey"] if isinstance(item, dict) else item
        for item in message["accountKeys"]
    ]
    loaded = meta.get("loadedAddresses") or {}
    keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    replaced = 0
    for idx, key in enumerate(keys):
        if key != phoenix:
            continue
        static = message["accountKeys"]
        if idx < len(static):
            if isinstance(static[idx], dict):
                static[idx]["pubkey"] = UNKNOWN_INNER
            else:
                static[idx] = UNKNOWN_INNER
            replaced += 1
            continue
        writable = list(loaded.get("writable") or [])
        rest = idx - len(static)
        if rest < len(writable):
            writable[rest] = UNKNOWN_INNER
            loaded["writable"] = writable
        else:
            readonly = list(loaded.get("readonly") or [])
            readonly[rest - len(writable)] = UNKNOWN_INNER
            loaded["readonly"] = readonly
        replaced += 1
    assert replaced >= 1
    decoded, trades = _app_trades(payload)
    assert trades == []
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    assert "Unknown inner program" in reasons
    assert auditor.reconstruct_record(payload["record"], payload["address"]) is None


def test_d3_reviewed_inner_is_recorded():
    payload = _load("dflow-swap2-token-usdc.json")
    decoded, trades = _app_trades(payload)
    assert trades
    venues = trades[0].get("inner_venues") or []
    programs = {item.get("program") for item in venues}
    assert "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY" in programs
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    aud_programs = {item.get("program") for item in (aud.get("inner_venues") or [])}
    assert "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY" in aud_programs


def test_d4_usdt_sol_is_conversion_not_an_fx_episode():
    payload = copy.deepcopy(_load("dflow-swap2-buy.json"))
    raw = payload["record"]
    if "raw" in raw:
        raw = raw["raw"]
        if isinstance(raw, dict) and "result" in raw:
            raw = raw["result"]
    meta = raw["meta"]
    replaced = 0
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if row.get("mint") == USDC:
                row["mint"] = USDT
                replaced += 1
    assert replaced >= 1
    decoded, trades = _app_trades(payload)
    conversions = [row for row in decoded.get("events") or [] if row.get("kind") == "conversion"]
    assert trades == []
    assert conversions
    assert conversions[0].get("settlement_asset") == "USDT"
    assert conversions[0].get("from_asset") in {"USDT", "SOL"}
    assert auditor.reconstruct_record(payload["record"], payload["address"]) is None


def test_d5_auditor_keeps_sol_fees_on_usdc_settled_trade():
    payload = _load("dflow-swap2-token-usdc.json")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    assert aud["settlement_asset"] == "USDC"
    assert Decimal(aud["fees_and_tips_sol"]) > 0
    assert Decimal(aud["network_fee_sol"]) > 0
    assert Decimal(aud["fees_and_tips_sol"]) == Decimal(aud["network_fee_sol"]) + Decimal(aud.get("tips_sol") or 0)


def test_d6_ledger_docstring_states_same_uid_has_no_defense():
    import scanner.mass_search.live_e2e_ledger as ledger

    text = ledger.__doc__ or ""
    assert "same-uid" in text
    assert "grant file holds no spend state" in text
    assert "no defense against a same-uid writer" in text.lower() or "There is no defense against a same-uid writer" in text


def test_d8_dew9_comment_names_swap_not_swap2():
    text = (ROOT / "tests/test_research_search_b_defects.py").read_text(encoding="utf-8")
    assert "5125oxVi8HPY" in text
    assert "f8c69e91" in text
    assert "DFlow Swap (f8c69e91) reconstructs the DEW9 close 5125oxVi8HPY" in text


def test_d9_align_wallet_bounds_documents_configured_vs_aligned():
    last = int(datetime(2026, 10, 4, 17, 22, 3, tzinfo=timezone.utc).timestamp())
    records = [{"blockTime": last}]
    configured = window_bounds(
        30, 60,
        end=datetime(2026, 10, 7, 16, 52, 48, tzinfo=timezone.utc),
        report_window_days=30,
    )
    aligned = align_wallet_bounds(records, configured)
    assert aligned["configured_report_end_exclusive"] == configured["report_end_exclusive"]
    assert aligned["aligned_report_end_exclusive"] == aligned["report_end_exclusive"]
    assert aligned["report_end_anchored_to_last_tx"] is True
    assert aligned["report_end_exclusive"] < configured["report_end_exclusive"]
    assert aligned["report_end_exclusive"] == aligned["aligned_report_end_exclusive"]
