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
    assert DECODER_VERSION == "spot-v27-route-flow-v1"


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
    group["instructions"].append({
        "programId": TOKEN_PROGRAM,
        "parsed": {
            "type": "initializeAccount3",
            "info": {
                "account": new_ata,
                "mint": USDC,
                "owner": wallet,
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
    for group in meta.get("innerInstructions") or []:
        for instruction in group.get("instructions") or []:
            if instruction.get("stackHeight") == 2:
                instruction["stackHeight"] = 3
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
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    if aud:
        assert aud.get("kind") == "conversion"
        assert aud.get("settlement_asset") in {"USDT", "SOL"}


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


OBSIDIAN = "HBVw6bZtcCaezhcBrmfyXBSBRWCdv72271xQ4GPvms2z"
GATORSWAP = "gatorLx9aC1e5ZWAXscv5QRKiLXnLPLXjftVc81h1Hr"
AQUIFER = "AQU1FRd7papthgdrwPTTq5JacJh8YtwEXaBfKU3bTz45"
JXT_PAGES = ROOT / "tests/fixtures/live-raw/f635a45" / JXT
OTHER_OWNER = "FY8B5zGjOtherOwner1111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"


def _require_pages(folder):
    folder = Path(folder)
    pages = sorted(folder.glob("page*.bin")) if folder.is_dir() else []
    if not pages:
        raise AssertionError(f"committed fixture pages missing: {folder}")
    records = []
    for path in pages:
        payload = json.loads(path.read_bytes())
        records.extend((payload.get("result") or {}).get("data") or [])
    if not records:
        raise AssertionError(f"committed fixture pages are empty: {folder}")
    return records


def test_d3p_obsidian_gator_aquifer_are_reviewed_inner_venues():
    from scanner.investigation import REVIEWED_INNER_PROGRAMS, WELL_KNOWN_INNER_AMMS
    assert OBSIDIAN in WELL_KNOWN_INNER_AMMS
    assert GATORSWAP in WELL_KNOWN_INNER_AMMS
    assert AQUIFER in WELL_KNOWN_INNER_AMMS
    assert OBSIDIAN in REVIEWED_INNER_PROGRAMS
    assert OBSIDIAN in auditor.REVIEWED_INNER_PROGRAMS
    assert GATORSWAP in auditor.REVIEWED_INNER_PROGRAMS
    assert AQUIFER in auditor.REVIEWED_INNER_PROGRAMS


def test_d1p_pumpswap_idl_user_volume_is_isolated_in_app_and_auditor():
    """Direct PumpSwap buy: IDL user-volume is isolated from the quote in both."""
    import gzip
    import hashlib

    page = ROOT / "evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz"
    wallet = "2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY"
    body = gzip.decompress(page.read_bytes())
    assert hashlib.sha256(body).hexdigest() == (
        "7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a"
    )
    raw = json.loads(body)["result"]["data"][83]
    record = {
        "signature": raw["transaction"]["signatures"][0],
        "evidence_hash": hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "raw": raw,
    }
    decoded, trades = _app_trades({"record": record, "address": wallet})
    assert len(trades) == 1
    assert Decimal(str(trades[0]["amount_sol"])) == Decimal("0.5651351")
    funding = trades[0].get("retained_account_funding") or []
    assert funding and funding[0]["lamports"] == 1_346_200
    aud = auditor.reconstruct_record(record, wallet)
    assert aud
    assert Decimal(aud["consideration_sol"]) == Decimal(str(trades[0]["amount_sol"]))


def test_d1p_jxt_2gDSxX4BGx_pump_pda_stays_in_consideration():
    payload = _load("jxt-2gDSxX4BGx-pump-pda.json")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    aud = auditor.reconstruct_record(payload["record"], JXT)
    assert aud
    assert Decimal(str(trades[0]["amount_sol"])) == Decimal(aud["consideration_sol"])
    # PDA 1,346,200 lamports is not-owned still-open: both keep it as cost.
    assert Decimal(str(trades[0]["amount_sol"])) >= Decimal("0.0013462")


def test_d2p_other_owner_wsol_create_stays_in_consideration():
    """EhJH7bmr 3Haiw9Tf pattern: wallet-paid wSOL ATA owned by another pubkey.

    Not wallet-owned still-open rent stays in consideration, so a USDC
    hop plus leftover native is cross-settlement (unresolved), not a
    cheapened USDC trade.
    """
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
    other_ata = "DC3wSwFsOtherOwnerWsol11111111111111111111"
    loaded = meta.setdefault("loadedAddresses", {})
    readonly = list(loaded.get("readonly") or [])
    readonly.append(other_ata)
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
                "newAccount": other_ata,
                "owner": TOKEN_PROGRAM,
                "lamports": 2_039_280,
                "space": 165,
            },
        },
    })
    group["instructions"].append({
        "programId": TOKEN_PROGRAM,
        "parsed": {
            "type": "initializeAccount3",
            "info": {
                "account": other_ata,
                "mint": WSOL,
                "owner": "FY8B5zGjOtherOwnerPumpPda111111111111111111",
            },
        },
    })
    decoded, trades = _app_trades(payload)
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    aud = auditor.reconstruct_record(payload["record"], wallet)
    # App must not exclude the other-owner rent and then emit a USDC sale.
    if trades:
        assert trades[0].get("settlement_asset") != "USDC" or Decimal(str(trades[0].get("amount_sol") or 0)) != 0
    else:
        assert "cross-settlement" in reasons or aud is None
    if aud and aud.get("settlement_asset") == "USDC":
        raise AssertionError("auditor treated other-owner wSOL rent as recoverable USDC rent")


def test_d2_auditor_sees_wallet_owned_ata_rent_only_usdc_buy():
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
    group["instructions"].append({
        "programId": TOKEN_PROGRAM,
        "parsed": {
            "type": "initializeAccount3",
            "info": {"account": new_ata, "mint": USDC, "owner": wallet},
        },
    })
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    assert trades[0]["settlement_asset"] == "USDC"
    aud = auditor.reconstruct_record(payload["record"], wallet)
    assert aud is not None
    assert aud["settlement_asset"] == "USDC"
    assert aud["kind"] == trades[0]["kind"]


def test_d4p_token_to_usdt_sell_records_usdt_proceeds_not_zero():
    payload = copy.deepcopy(_load("dflow-swap2-token-usdc.json"))
    raw = payload["record"]
    meta = raw["meta"]
    replaced = 0
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if row.get("mint") == USDC:
                row["mint"] = USDT
                replaced += 1
    assert replaced >= 1
    decoded, trades = _app_trades(payload)
    assert trades
    sell = next((row for row in trades if row.get("kind") == "sell"), trades[0])
    assert sell.get("settlement_asset") == "USDT"
    assert sell.get("amount_usdt") not in (None, "", "0")
    assert sell.get("amount_sol") in (None, "")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    assert aud["settlement_asset"] == "USDT"
    assert Decimal(aud["consideration_usdt"]) > 0
    from scanner.mass_search.settlement import map_decoder_trade
    mapped = map_decoder_trade(
        sell, address=payload["address"], seconds=0, timestamp_missing=False,
        role="exit", window_qualified=True, unresolved_order=False,
    )
    assert mapped.get("unknown_quote") is not True
    assert Decimal(mapped["consideration_usdt"]) == Decimal(str(sell["amount_usdt"]))


def test_d4p_unknown_quote_is_unresolved_never_zero():
    from scanner.mass_search.settlement import isolate_known_cost_events
    known, unresolved = isolate_known_cost_events([
        {
            "kind": "buy", "units": "10", "mint": "TokenMint",
            "consideration_sol": "1", "settlement_asset": "SOL",
            "seconds_from_start": 1, "signature": "b1",
        },
        {
            "kind": "sell", "units": "10", "mint": "TokenMint",
            "amount_sol": None, "settlement_asset": None,
            "seconds_from_start": 2, "signature": "s1",
        },
    ])
    assert any(row.get("unknown_quote") or row.get("unresolved_basis") for row in unresolved)
    assert not any(
        row.get("kind") == "sell" and row.get("signature") == "s1" and not row.get("unresolved_basis")
        for row in known
    )


def test_d7_jxt_is_audited_with_exact_net_30d_and_90d(tmp_path):
    from scanner.mass_search.history_ingest import replay_cached_history_to_report
    from scanner.mass_search.research_profile import (
        attach_live_independent_audit,
        build_research_profile,
        default_filters,
    )
    from scanner.storage import Store

    records = _require_pages(JXT_PAGES)
    end = datetime(2026, 10, 4, 17, 22, 3, tzinfo=timezone.utc)
    expected = {
        30: Decimal("310.781644564"),
        90: Decimal("321.515629495"),
    }
    for days, net in expected.items():
        bounds = window_bounds(days, 60, end=end, history_to_first=True, report_window_days=days)
        store = Store(tmp_path / f"jxt-{days}")
        report = replay_cached_history_to_report(
            store,
            address=JXT,
            records=records,
            window_start=bounds["report_start_inclusive"],
            window_end=bounds["report_end_exclusive"],
            acquisition_start=bounds["history_start_inclusive"],
        )["report"]
        profile = build_research_profile(report, filters=default_filters())
        audit = attach_live_independent_audit(report, profile, records, address=JXT)
        store.close()
        assert audit.get("independently_audited") or audit.get("status") == "independently_audited", (
            days, audit.get("status"), audit.get("reason"), audit.get("app_completed_episode_net"),
            audit.get("independently_audited_episode_net"),
        )
        assert "component_mismatch" not in str(audit.get("reason") or "")
        got = Decimal(str(
            audit.get("app_completed_episode_net")
            or profile.get("completed_episode_net")
            or report.get("completed_episode_net")
            or "0"
        ))
        assert got == net, (days, got, net, audit.get("reason"))


def test_d2_unparsed_system_create_wallet_owned_rent_is_not_cross_settlement():
    """AE4C 2jUxgRQv1z pattern: raw System opcode 0 + wallet-owned ATA still open."""
    from scanner.compiled_instructions import _base58_decode, _base58_encode

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
    new_ata = "NewAtaRaw111111111111111111111111111111111"
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
    owner = _base58_decode(TOKEN_PROGRAM, "token-program", 32)
    data = (
        (0).to_bytes(4, "little")
        + (2_039_280).to_bytes(8, "little")
        + (165).to_bytes(8, "little")
        + owner
    )
    groups = meta.setdefault("innerInstructions", [])
    group = next((g for g in groups if g.get("index") == route_index), None)
    if group is None:
        group = {"index": route_index, "instructions": []}
        groups.append(group)
    group["instructions"].append({
        "programId": "11111111111111111111111111111111",
        "accounts": [wallet, new_ata],
        "data": _base58_encode(data),
    })
    group["instructions"].append({
        "programId": TOKEN_PROGRAM,
        "parsed": {
            "type": "initializeAccount3",
            "info": {"account": new_ata, "mint": USDC, "owner": wallet},
        },
    })
    decoded, trades = _app_trades(payload)
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    assert "cross-settlement" not in reasons, reasons
    assert len(trades) == 1
    assert trades[0]["settlement_asset"] == "USDC"


def test_d4pp_usdt_events_keep_usdt_through_accounting_and_episodes():
    from scanner.mass_search.service import events_to_accounting
    from scanner.mass_search.research_profile import _episode_ledger_from_report

    payload = copy.deepcopy(_load("dflow-swap2-token-usdc.json"))
    raw = payload["record"]
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in raw["meta"].get(field) or []:
            if row.get("mint") == USDC:
                row["mint"] = USDT
    decoded, trades = _app_trades(payload)
    sell = next(row for row in trades if row.get("kind") == "sell")
    buy = next((row for row in trades if row.get("kind") == "buy"), None)
    mapped = []
    for row in trades:
        mapped.append({
            **row,
            "units": str(row.get("quantity_raw") or row.get("units") or "0"),
            "consideration_usdt": row.get("amount_usdt"),
            "seconds_from_start": 0 if row is (buy or sell) else 1,
            "timestamp_missing": False,
        })
    rows = events_to_accounting(mapped, mint=sell["mint"], start="2026-10-01T00:00:00Z")
    trades_out = [row for row in rows if row.get("kind") in ("buy", "sell")]
    assert trades_out
    assert all(row.get("settlement_asset") == "USDT" for row in trades_out)
    assert all(row.get("amount_usdt") not in (None, "") for row in trades_out)
    assert all(row.get("amount_sol") in (None, "") for row in trades_out)
    report = {
        "events": trades_out,
        "worksheet": {
            "sale_rows": [{
                "signature": sell.get("signature"),
                "mint": sell.get("mint"),
                "net_profit": "12.5",
                "basis": "10",
                "proceeds": "22.5",
                "fees_and_tips": "0",
                "settlement_asset": "USDT",
            }],
        },
        "window": {"start": "2026-09-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"},
    }
    if buy:
        report["events"] = trades_out
    ledger = _episode_ledger_from_report(report)
    if ledger:
        assert all(item.get("unit") == "USDT" for item in ledger)
        assert all(item.get("unit") != "SOL" for item in ledger)


def test_reviewed_stablecoin_rule_is_usdc_usdt_only():
    from scanner.investigation import (
        PYUSD,
        QUOTE_MINTS,
        REVIEWED_STABLECOIN_RULE,
        USD1,
        USDS,
    )
    from scanner.mass_search.settlement import REVIEWED_STABLECOIN_RULE as SETTLEMENT_RULE

    assert USDC in QUOTE_MINTS
    assert USDT in QUOTE_MINTS
    assert PYUSD not in QUOTE_MINTS
    assert PYUSD == "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo"
    assert USD1 not in QUOTE_MINTS
    assert USDS not in QUOTE_MINTS
    assert "USDC and USDT only" in REVIEWED_STABLECOIN_RULE
    assert "PYUSD" in REVIEWED_STABLECOIN_RULE
    assert SETTLEMENT_RULE == REVIEWED_STABLECOIN_RULE or "USDC and USDT only" in SETTLEMENT_RULE


def test_ax5_4k3dyjzv_auditor_closes_on_observed_flatten_not_mint_wide_sum():
    """AX5FaYB3 4k3Dyjzv: auditor was wrong; app flat-to-flat 319/321 is right.

    Buy qty sums miss 58590 raw dust versus observed balances. The first
    flatten (observed post=0) therefore leaves unmatched sell qty. The
    auditor used to keep that episode open and glue the next 319.07/321.37
    flat onto a mint-wide 583.20/640.44. Observed flatten must close.
    """
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    rows = [
        ("buy", "3DqoTA8", "6138875934", "100", "0", "6138875934", 1),
        ("buy", "4TCxff7", "1534488658", "25", "6138875934", "7673364592", 2),
        ("buy", "4aLQVD5", "1534646909", "25", "7673364592", "9208011501", 3),
        ("buy", "63Zrb5f", "3809763079", "61.52680626", "9208011501", "13017774580", 4),
        ("buy", "2mWTne9", "2844482406", "52.595918312", "13017833170", "15862315576", 5),
        ("sell", "2PVuv31", "3862000000", "74.146321876", "15862315576", "12000315576", 6),
        ("sell", "fJur4ca", "2000000000", "37.794267709", "12000315576", "10000315576", 7),
        ("sell", "3F2Zzh2", "10000315576", "207.137489233", "10000315576", "0", 8),
        ("buy", "3amUVtM", "15312443191", "319.072780188", "0", "15312443191", 9),
        ("sell", "2TRb1r1", "15312443191", "321.368106664", "15312443191", "0", 10),
    ]
    trades = []
    for kind, sig, qty, sol, pre, post, stamp in rows:
        trades.append({
            "mint": mint,
            "kind": kind,
            "signature": sig,
            "slot": stamp,
            "transaction_index": 0,
            "timestamp": 1_775_000_000 + stamp,
            "quantity_raw": qty,
            "observed_pre_quantity_raw": pre,
            "observed_post_quantity_raw": post,
            "settlement_asset": "SOL",
            "consideration_sol": sol,
            "fees_and_tips_sol": "0",
            "program": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "instruction": "route_v2",
        })
    original_start, original_end = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START = 0
    auditor.REPORT_END = 2_000_000_000
    try:
        episodes, unresolved, _known, omitted = auditor._fifo(trades)
    finally:
        auditor.REPORT_START = original_start
        auditor.REPORT_END = original_end
    assert omitted == []
    assert unresolved >= 1
    assert len(episodes) == 1
    last = episodes[0]
    assert last["close_signature"] == "2TRb1r1"
    assert Decimal(last["basis_sol"]) == Decimal("319.072780188")
    assert Decimal(last["proceeds_sol"]) == Decimal("321.368106664")
    mint_wide_basis = sum(Decimal(sol) for kind, _s, _q, sol, _pre, _post, _t in rows if kind == "buy")
    mint_wide_proceeds = sum(Decimal(sol) for kind, _s, _q, sol, _pre, _post, _t in rows if kind == "sell")
    assert mint_wide_basis == Decimal("583.19550476")
    assert mint_wide_proceeds == Decimal("640.446185482")
    assert Decimal(last["basis_sol"]) != mint_wide_basis
    assert Decimal(last["proceeds_sol"]) != mint_wide_proceeds
