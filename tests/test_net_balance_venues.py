"""Net-balance decoder fixtures from real corpus txs. Offline only."""
from __future__ import annotations

import json
from pathlib import Path

from scanner.investigation import (
    DECODER_VERSION,
    JUPITER,
    NET_BALANCE_INSTRUCTION,
    NET_BALANCE_SWAP_PROGRAMS,
    RAYDIUM_AMM,
    RAYDIUM_CLMM,
    REVIEWED_OUTER_VENUES,
    WHIRLPOOL,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/net-balance-venues"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _trades(decoded):
    return [
        event for event in decoded.get("events") or []
        if event.get("kind") in {"buy", "sell", "conversion"}
    ]


def test_decoder_version_bumped_for_net_balance():
    assert DECODER_VERSION == "spot-v25-net-balance-v1"
    assert RAYDIUM_CLMM in NET_BALANCE_SWAP_PROGRAMS
    assert RAYDIUM_CLMM not in REVIEWED_OUTER_VENUES
    assert auditor.NET_BALANCE_SWAP_PROGRAMS is not NET_BALANCE_SWAP_PROGRAMS
    assert RAYDIUM_CLMM in auditor.NET_BALANCE_SWAP_PROGRAMS


def test_b311_wrapper_is_not_a_jupiter_net_balance():
    payload = json.loads(
        (ROOT / "tests/fixtures/live-e2e-phase3/b311-unreviewed.json").read_text(encoding="utf-8")
    )
    record = payload["record"]
    address = payload["address"]
    assert net_balance_reviewed_swap(record, address) is None
    decoded = decode_supported_swaps(canonical_decode_records([record]), address)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(record, address) is None


def test_dflow_sponsor_is_not_a_net_balance_swap():
    payload = json.loads(
        (ROOT / "tests/fixtures/live-e2e-phase3/dflow-sponsor-not-swap.json").read_text(encoding="utf-8")
    )
    record = payload["record"]
    address = payload["address"]
    assert net_balance_reviewed_swap(record, address) is None
    decoded = decode_supported_swaps(canonical_decode_records([record]), address)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(record, address) is None


def test_unknown_program_still_fails_closed():
    fake = {
        "transaction": {
            "signatures": ["FakeNetBalance111111111111111111111111111111111111111111111111"],
            "message": {
                "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 1},
                "accountKeys": [
                    {"pubkey": "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ", "signer": True, "writable": True},
                    {"pubkey": "FakeVenue11111111111111111111111111111111111", "signer": False, "writable": False},
                ],
                "instructions": [{
                    "programId": "FakeVenue11111111111111111111111111111111111",
                    "accounts": [0],
                    "data": "11111111",
                }],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [1_000_000_000, 0],
            "postBalances": [500_000_000, 0],
            "preTokenBalances": [],
            "postTokenBalances": [{
                "accountIndex": 0,
                "mint": "FakeMint11111111111111111111111111111111111",
                "owner": "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ",
                "uiTokenAmount": {"amount": "100", "decimals": 6},
            }],
            "innerInstructions": [],
        },
        "blockTime": 1_780_000_000,
        "slot": 1,
    }
    wallet = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
    assert net_balance_reviewed_swap(fake, wallet) is None
    decoded = decode_supported_swaps(canonical_decode_records([fake]), wallet)
    assert _trades(decoded) == []
    assert auditor.reconstruct_record(fake, wallet) is None


def _assert_fixture(name, program, expect_layout_fail=True):
    payload = _load(name)
    record = payload["record"]
    address = payload["address"]
    assert payload["program"] == program
    before = decode_supported_swaps(
        canonical_decode_records([record]), address, allow_net_balance=False
    )
    after = decode_supported_swaps(
        canonical_decode_records([record]), address, allow_net_balance=True
    )
    aud = auditor.reconstruct_record(record, address)
    after_trades = _trades(after)
    assert after_trades, name
    trade = after_trades[0]
    assert aud
    assert trade["kind"] == aud["kind"]
    assert trade["mint"] == aud["mint"]
    assert str(trade["quantity_raw"]) == str(aud["quantity_raw"])
    if expect_layout_fail:
        assert _trades(before) == []
        assert trade.get("instruction") == NET_BALANCE_INSTRUCTION
        assert aud.get("source") == "independent-net-balance"
        assert aud.get("instruction") == NET_BALANCE_INSTRUCTION
    else:
        assert trade["kind"] == aud["kind"]
        assert {trade.get("source"), aud.get("program"), program} & {program, trade.get("source")}


def test_jupiter_v6_net_balance_fixture():
    _assert_fixture("jupiter_v6.json", JUPITER, expect_layout_fail=True)


def test_whirlpool_net_balance_fixture():
    _assert_fixture("orca_whirlpool.json", WHIRLPOOL, expect_layout_fail=True)


def test_raydium_amm_v4_net_balance_fixture():
    _assert_fixture("raydium_amm_v4.json", RAYDIUM_AMM, expect_layout_fail=True)


def test_raydium_clmm_net_balance_fixture():
    _assert_fixture("raydium_clmm.json", RAYDIUM_CLMM, expect_layout_fail=True)


def test_app_and_auditor_net_balance_are_independent():
    assert decode_supported_swaps.__module__ == "scanner.investigation"
    assert auditor.reconstruct_record.__module__ == "tools.independent_episode_audit"
    src = Path(auditor.__file__).read_text(encoding="utf-8")
    assert not any(
        line.lstrip().startswith(("from scanner", "import scanner"))
        for line in src.splitlines()
    )
    assert "independent-net-balance" in src
    assert auditor.NET_BALANCE_SWAP_PROGRAMS is not NET_BALANCE_SWAP_PROGRAMS
