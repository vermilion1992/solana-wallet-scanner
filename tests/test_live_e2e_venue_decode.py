"""Undecoded-venue fixtures from attached live pages. Offline only; no shared app/auditor path."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    DECODER_VERSION,
    DFLOW,
    DGMG,
    decode_supported_swaps,
)
from scanner.mass_search.canonical_records import canonical_decode_records
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/live-e2e-phase3"
B311 = "B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
DKX = "DKxKrP4yCSGt27AECQvaaxrr5KwZ3FxLYdNhnD3LcMTv"
JXT_MINT = "44y8UUEtJq6Cw4g3jnUz3Zoyd1M6P45o39sJ5L4vpump"
GE87 = "Ge87EtsjwRQbHaqQmKRno69RFTwh9bfSsm99XNxTpump"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _app_trades(payload):
    decoded = decode_supported_swaps(
        canonical_decode_records([payload["record"]]), payload["address"]
    )
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    return decoded, trades


def test_decoder_version_bumped_for_dgmg_dflow():
    assert DECODER_VERSION == "spot-v21-dgmg-dflow-auditor-v1"


def test_app_and_auditor_are_independent_modules():
    assert decode_supported_swaps.__module__ == "scanner.investigation"
    assert auditor.reconstruct_record.__module__ == "tools.independent_episode_audit"
    assert auditor.PINNED is not None
    assert DGMG in {key[0] for key in auditor.PINNED}
    assert DFLOW in {key[0] for key in auditor.PINNED}


def test_jxt_dgmg_buy_hand_deltas():
    """jXt unresolved-basis sale was mint 44y8…pump: PumpSwap sell decoded, DGMg buy did not.

    Hand: wallet wraps 99_910_001 lamports, receives 4_450_544_168_706 raw of 44y8
    (6 decimals). Auditor isolates wrap-minus-dust 0.099909999 SOL. App emits the
    same quantity; fee 105_000 lamports.
    """
    payload = _load("jxt-dgmg-buy.json")
    assert payload["address"] == JXT
    assert payload["signature"].startswith("2EtPn1a61imQ")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["kind"] == "buy"
    assert trade["mint"] == JXT_MINT
    assert trade["quantity_raw"] == "4450544168706"
    assert trade.get("instruction") == "buy"
    assert trade.get("source") == DGMG or trade.get("program") == DGMG
    aud = auditor.reconstruct_record(payload["record"], JXT)
    assert aud
    assert aud["kind"] == "buy"
    assert aud["mint"] == JXT_MINT
    assert aud["quantity_raw"] == "4450544168706"
    assert Decimal(aud["consideration_sol"]) == Decimal("0.099909999")
    assert Decimal(aud["network_fee_sol"]) == Decimal("0.000105")
    assert aud["program"] == DGMG
    assert aud["instruction"] == "buy"


def test_dkx_dflow_opening_buy_hand_deltas():
    """DKx Ge87 opening buy vYeWFHJd. Wrap sibling 2f3e9bac83cd25c9 is not a swap.

    Hand: +32_679_409_659 raw Ge87 against 2.997013452 SOL (native −2_997_020_510
    plus fee 7_058). App and auditor must agree on quantity and SOL consideration.
    """
    payload = _load("dkx-dflow-buy.json")
    assert payload["address"] == DKX
    assert payload["signature"].startswith("vYeWFHJd")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["kind"] == "buy"
    assert trade["mint"] == GE87
    assert trade["quantity_raw"] == "32679409659"
    assert Decimal(str(trade.get("amount_sol") or trade.get("consideration_sol"))) == Decimal("2.997013452")
    aud = auditor.reconstruct_record(payload["record"], DKX)
    assert aud
    assert aud["kind"] == "buy"
    assert aud["mint"] == GE87
    assert aud["quantity_raw"] == "32679409659"
    assert Decimal(aud["consideration_sol"]) == Decimal("2.997013452")
    assert aud["program"] == DFLOW
    assert aud["instruction"] == "swap"
    assert aud["discriminator"] == "f8c69e91e17587c8"


def test_b311_stays_unresolved_never_silent_guess():
    payload = _load("b311-unreviewed.json")
    decoded, trades = _app_trades(payload)
    assert trades == []
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    assert "No reviewed outer spot swap" in reasons or "unresolved" in reasons.lower() or decoded.get("unresolved")
    assert auditor.reconstruct_record(payload["record"], payload["address"]) is None


def test_unknown_program_stays_unresolved():
    """A made-up outer program must not become a zero-basis swap."""
    fake = {
        "transaction": {
            "signatures": ["FakeUnknownVenue111111111111111111111111111111111111111111111111"],
            "message": {
                "accountKeys": [
                    {"pubkey": JXT, "signer": True, "writable": True},
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
            "postBalances": [900_000_000, 0],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "innerInstructions": [],
        },
        "blockTime": 1_780_000_000,
        "slot": 1,
    }
    decoded = decode_supported_swaps(canonical_decode_records([fake]), JXT)
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    assert trades == []
    assert decoded.get("unresolved")
    assert auditor.reconstruct_record(fake, JXT) is None


def test_dflow_fixture_without_reconciliation_stays_unresolved():
    """App rejects the multi-hop 25865JdB fixture (no opposing SOL reconcilation).

    Auditor may isolate a USDC-settled single-mint fill from balances; that is
    not a silent zero-basis guess — consideration must be nonzero.
    """
    payload = _load("dflow-swap.json")
    decoded, trades = _app_trades(payload)
    assert trades == []
    assert decoded.get("unresolved")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    if aud is not None:
        usdc = Decimal(str(aud.get("consideration_usdc") or 0))
        sol = Decimal(str(aud.get("consideration_sol") or 0))
        assert usdc > 0 or sol > 0
