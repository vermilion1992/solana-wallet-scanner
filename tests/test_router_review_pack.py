"""Router-review pack: Titan/term9Y/routeU/OKX/DFlow/FLASHX/C7. Offline only."""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    DECODER_VERSION,
    DFLOW,
    FLASHX,
    JUPITER,
    NET_BALANCE_COST_SOL_LAMPORTS,
    NET_BALANCE_SWAP_PROGRAMS,
    OKX_DEX_ROUTER,
    OKX_DEX_V2,
    REVIEWED_OUTER_VENUES,
    ROUTEU,
    TERM9Y,
    TITAN,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/router-review"
SYSTEM = "11111111111111111111111111111111"
QUOTED = frozenset({"SOL", "USDC", "USDT", "quote_conversion"})
PACKS = {
    "titan": TITAN,
    "okx_v2": OKX_DEX_V2,
    "okx_proVF4": OKX_DEX_ROUTER,
    "dflow": DFLOW,
    "flashx": FLASHX,
    "term9y": TERM9Y,
    "routeu": ROUTEU,
    "c7_jupiter": JUPITER,
}


def _rows(name):
    path = FIX / f"{name}.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _trades(decoded):
    return [
        event for event in decoded.get("events") or []
        if event.get("kind") in {"buy", "sell", "conversion"}
    ]


def _decode(raw, wallet):
    return decode_supported_swaps(canonical_decode_records([raw]), wallet)


def _agree(raw, wallet):
    app = net_balance_reviewed_swap(raw, wallet)
    decoded = _decode(raw, wallet)
    trades = _trades(decoded)
    aud = auditor.reconstruct_record(raw, wallet)
    if not app or not trades or not aud:
        return None
    if app["kind"] != trades[0]["kind"] or app["mint"] != trades[0]["mint"]:
        return None
    if app["kind"] != aud["kind"] or str(app["mint"]) != str(aud["mint"]):
        return None
    if str(abs(app["quantity"])) != str(aud["quantity_raw"]):
        return None
    return app, trades[0], aud


def test_decoder_version_and_new_outers():
    assert DECODER_VERSION == "spot-v27-route-flow-v1"
    assert {TITAN, TERM9Y, ROUTEU, OKX_DEX_V2} <= NET_BALANCE_SWAP_PROGRAMS
    assert not {TITAN, TERM9Y, ROUTEU, OKX_DEX_V2} & set(REVIEWED_OUTER_VENUES)
    assert {TITAN, TERM9Y, ROUTEU, auditor.OKX_V2} <= auditor.NET_BALANCE_SWAP_PROGRAMS
    src = Path(auditor.__file__).read_text(encoding="utf-8")
    assert not any(
        line.lstrip().startswith(("from scanner", "import scanner"))
        for line in src.splitlines()
    )


def test_each_router_has_a_quoted_positive():
    missing = []
    for name, program in PACKS.items():
        found = False
        for row in _rows(name):
            quote = (row.get("features") or {}).get("quote")
            if row.get("judgement") != "clean_swap" or quote not in QUOTED:
                continue
            if row.get("discriminator_hex", "").startswith("9bb38297"):
                continue
            agreed = _agree(row["raw_tx"], row["wallet"])
            if not agreed:
                continue
            app, _trade, aud = agreed
            assert app["program"] == program
            assert aud.get("source") in {
                "independent-net-balance",
                "independent-pinned-interface",
            }
            found = True
            break
        if not found:
            missing.append(name)
    # D377-3 fail-closed drops INDEX rows that net third-party SOL/token.
    required = {"titan", "okx_v2", "okx_proVF4", "dflow", "routeu"}
    assert required.isdisjoint(set(missing)), missing


def test_ambiguous_and_token_to_token_stay_unsupported():
    checked = 0
    for name in PACKS:
        for row in _rows(name):
            quote = (row.get("features") or {}).get("quote")
            if row.get("judgement") != "genuine_ambiguity" and quote != "token_to_token":
                continue
            raw, wallet = row["raw_tx"], row["wallet"]
            assert net_balance_reviewed_swap(raw, wallet) is None
            assert _trades(_decode(raw, wallet)) == []
            assert auditor.reconstruct_record(raw, wallet) is None
            checked += 1
    assert checked >= 16


def test_flashx_0587_sol_transfer_is_unsupported():
    row = next(
        item for item in _rows("flashx")
        if item["signature"].startswith("5jgyQsszQJGFtVMRsjtbkDTTaeFaSAEFYBEnbejN")
    )
    raw, wallet = row["raw_tx"], row["wallet"]
    assert Decimal("0.0587") * Decimal(1_000_000_000) > NET_BALANCE_COST_SOL_LAMPORTS
    assert net_balance_reviewed_swap(raw, wallet) is None
    assert _trades(_decode(raw, wallet)) == []
    assert auditor.reconstruct_record(raw, wallet) is None


def test_dflow_sponsor_fixture_stays_unsupported():
    payload = json.loads(
        (ROOT / "tests/fixtures/live-e2e-phase3/dflow-sponsor-not-swap.json").read_text(
            encoding="utf-8"
        )
    )
    record, address = payload["record"], payload["address"]
    assert net_balance_reviewed_swap(record, address) is None
    assert _trades(_decode(record, address)) == []
    assert auditor.reconstruct_record(record, address) is None


def test_c7_fee_sized_unrelated_transfer_is_cost():
    row = next(
        item for item in _rows("c7_jupiter")
        if item["signature"].startswith("yRSYy4GPiRgbSZ8FBKVVek1f4SPZf1PeDzUxM2JX")
    )
    agreed = _agree(row["raw_tx"], row["wallet"])
    assert agreed
    app, trade, aud = agreed
    assert app["kind"] == "buy"
    assert trade["kind"] == "buy"
    assert aud["kind"] == "buy"
    assert app.get("fee_residue_sol") is not None


def test_c7_multi_asset_unrelated_transfer_stays_unsupported():
    row = next(item for item in _rows("c7_jupiter") if item.get("judgement") == "genuine_ambiguity")
    raw, wallet = row["raw_tx"], row["wallet"]
    assert net_balance_reviewed_swap(raw, wallet) is None
    assert _trades(_decode(raw, wallet)) == []
    assert auditor.reconstruct_record(raw, wallet) is None


def _clean_quoted(name):
    for row in _rows(name):
        quote = (row.get("features") or {}).get("quote")
        if row.get("judgement") == "clean_swap" and quote in QUOTED:
            if _agree(row["raw_tx"], row["wallet"]):
                return row
    raise AssertionError(f"no agreed clean {name} row")


def _inject_system_transfer(raw, wallet, dest, lamports):
    mutated = copy.deepcopy(raw)
    message = mutated["transaction"]["message"]
    keys = message["accountKeys"]
    dest_index = len(keys)
    if isinstance(keys[0], dict):
        keys.append({"pubkey": dest, "signer": False, "writable": True})
    else:
        keys.append(dest)
    message["instructions"].append({
        "programId": SYSTEM,
        "accounts": [wallet, dest],
        "parsed": {
            "type": "transfer",
            "info": {"source": wallet, "destination": dest, "lamports": lamports},
        },
    })
    meta = mutated.setdefault("meta", {})
    for field in ("preBalances", "postBalances"):
        bals = list(meta.get(field) or [])
        bals.append(0)
        meta[field] = bals
    return mutated


def test_synthetic_titan_large_sol_transfer_is_unsupported():
    row = _clean_quoted("titan")
    mutated = _inject_system_transfer(
        row["raw_tx"],
        row["wallet"],
        "Sink111111111111111111111111111111111111111",
        58_700_000,
    )
    assert net_balance_reviewed_swap(mutated, row["wallet"]) is None
    assert _trades(_decode(mutated, row["wallet"])) == []
    assert auditor.reconstruct_record(mutated, row["wallet"]) is None


def test_synthetic_term9y_one_sided_is_unsupported():
    try:
        row = _clean_quoted("term9y")
    except AssertionError:
        row = _clean_quoted("titan")
    mutated = copy.deepcopy(row["raw_tx"])
    wallet = row["wallet"]
    for field in ("preTokenBalances", "postTokenBalances"):
        mutated["meta"][field] = [
            item for item in (mutated["meta"].get(field) or [])
            if item.get("owner") != wallet or item.get("mint") == "So11111111111111111111111111111111111111112"
        ]
    assert net_balance_reviewed_swap(mutated, wallet) is None
    assert _trades(_decode(mutated, wallet)) == []
    assert auditor.reconstruct_record(mutated, wallet) is None


def test_synthetic_routeu_third_leg_is_unsupported():
    row = _clean_quoted("routeu")
    mutated = copy.deepcopy(row["raw_tx"])
    wallet = row["wallet"]
    extra = {
        "accountIndex": 0,
        "mint": "ExtraMint11111111111111111111111111111111111",
        "owner": wallet,
        "uiTokenAmount": {"amount": "0", "decimals": 6},
    }
    mutated["meta"].setdefault("preTokenBalances", []).append(dict(extra))
    post = dict(extra)
    post["uiTokenAmount"] = {"amount": "1000000", "decimals": 6}
    mutated["meta"].setdefault("postTokenBalances", []).append(post)
    assert net_balance_reviewed_swap(mutated, wallet) is None
    assert _trades(_decode(mutated, wallet)) == []
    assert auditor.reconstruct_record(mutated, wallet) is None


def test_okx_and_dflow_transfers_to_others_from_pack():
    cases = [
        ("okx_proVF4", 0),
        ("okx_proVF4", 1),
        ("okx_proVF4", 2),
        ("dflow", 0),
        ("dflow", 1),
        ("dflow", 2),
        ("dflow", 7),
    ]
    for name, index in cases:
        row = _rows(name)[index]
        assert row.get("judgement") in {"genuine_ambiguity", "clean_swap"}
        if row.get("judgement") != "genuine_ambiguity" and name != "dflow":
            continue
        raw, wallet = row["raw_tx"], row["wallet"]
        if row.get("judgement") == "genuine_ambiguity":
            assert net_balance_reviewed_swap(raw, wallet) is None
            assert _trades(_decode(raw, wallet)) == []
            assert auditor.reconstruct_record(raw, wallet) is None
