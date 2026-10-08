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
    assert DECODER_VERSION == "spot-v31-plain-read-v1"


def test_app_and_auditor_are_independent_modules():
    assert decode_supported_swaps.__module__ == "scanner.investigation"
    assert auditor.reconstruct_record.__module__ == "tools.independent_episode_audit"
    assert auditor.PINNED is not None
    assert DGMG in {key[0] for key in auditor.PINNED}
    assert DFLOW in {key[0] for key in auditor.PINNED}


def test_jxt_dgmg_buy_hand_deltas():
    """jXt unresolved-basis sale was mint 44y8…pump: PumpSwap sell decoded, DGMg buy did not.

    Hand: wallet −104_998_679 = fee 105_000 + pool 99_909_999 + router
    1_844_400 + ATA rent 2_039_280 + tips 1_100_000. App and auditor both
    include the 1_844_400-lamport DGMg router fee in basis (0.101754399).
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
    assert Decimal(str(trade.get("amount_sol") or trade.get("consideration_sol"))) == Decimal("0.101754399")
    assert Decimal(aud["consideration_sol"]) == Decimal("0.101754399")
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


def _conversions(decoded):
    return [row for row in decoded.get("events") or [] if row.get("kind") == "conversion"]


def test_dflow_swap2_usdc_sol_is_conversion_not_blocked():
    """Run-7 9TxdAeLT 4rZp4CN3 is DFlow Swap2 (414b3f4ceb5b5b88), wallet at 3.

    Hand: native −125_000_005_704 + fee 5_704 = 125 SOL out; +14_512_696_704
    raw USDC. App policy: USDC↔SOL is a quote conversion, not a spot buy.
    Auditor has no non-USDC mint, so it stays silent (not a zero-basis guess).
    """
    from scanner.mass_search.live_e2e import classify_programs

    payload = _load("dflow-swap2-buy.json")
    assert payload["address"].startswith("9TxdAeLT")
    assert payload["signature"].startswith("4rZp4CN3")
    decoded, trades = _app_trades(payload)
    assert trades == []
    conversions = _conversions(decoded)
    assert len(conversions) == 1
    row = conversions[0]
    assert row.get("instruction") == "swap2"
    assert row["quantity_raw"] == "14512696704"
    assert Decimal(str(row["amount_sol"])) == Decimal("125")
    assert Decimal(str(row["amount_usdc"])) == Decimal("14512.696704")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    if aud:
        assert aud.get("kind") == "conversion"
    ranked = classify_programs([payload["record"]], payload["address"])
    assert not any(item.get("program_id") == DFLOW for item in ranked.get("blockers") or [])


def test_dflow_swap_plus_unwrap_usdc_sol_is_conversion():
    """CSC8 5pSfmWV2 is DFlow Swap + UnwrapSol sibling (63280e692d6bacc9).

    Unwrap is not a second swap. Hand: −37_908_000_000 raw USDC, native
    +421_036_689_583 + fee 1_426_619 = 421.038116202 SOL. Quote conversion.
    """
    from scanner.mass_search.live_e2e import classify_programs

    payload = _load("dflow-swap-unwrap-sell.json")
    assert payload["address"].startswith("CSC8xFPM")
    decoded, trades = _app_trades(payload)
    assert trades == []
    conversions = _conversions(decoded)
    assert len(conversions) == 1
    row = conversions[0]
    assert row.get("instruction") == "swap"
    assert row["quantity_raw"] == "37908000000"
    assert Decimal(str(row["amount_sol"])) == Decimal("421.038116202")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    if aud:
        assert aud.get("kind") == "conversion"
    ranked = classify_programs([payload["record"]], payload["address"])
    assert not any(item.get("program_id") == DFLOW for item in ranked.get("blockers") or [])


def test_dflow_transfer_to_sponsor_is_not_a_swap():
    """9bb38297 TransferToSponsor (and companion cd4d7f6c) stay unresolved."""
    payload = _load("dflow-sponsor-not-swap.json")
    decoded, trades = _app_trades(payload)
    assert trades == []
    assert decoded.get("unresolved")
    assert auditor.reconstruct_record(payload["record"], payload["address"]) is None


def test_dflow_swap2_token_sol_hand_deltas():
    """HAv8 3G9EDeWV is Swap2 token↔SOL. Hand: +29_860_798_819 raw 74SBV4zD
    against 2.080341597 SOL.
    """
    payload = _load("dflow-swap2-token-sol.json")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["kind"] == "buy"
    assert trade["mint"].startswith("74SBV4zD")
    assert trade["quantity_raw"] == "29860798819"
    assert Decimal(str(trade.get("amount_sol") or trade.get("consideration_sol"))) == Decimal("2.080341597")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    assert aud["kind"] == "buy"
    assert aud["quantity_raw"] == "29860798819"
    assert Decimal(aud["consideration_sol"]) == Decimal("2.080341597")
    assert aud["instruction"] == "swap2"


def test_dflow_swap2_token_usdc_hand_deltas():
    """23Yu 2KFyZ9yq is Swap2 token↔USDC. Hand: −402_160_000_000 raw 3iQL8BFS
    for 317.208149 USDC. Auditor isolates the USDC-settled fill.
    """
    payload = _load("dflow-swap2-token-usdc.json")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["kind"] == "sell"
    assert trade["mint"].startswith("3iQL8BFS")
    assert trade["quantity_raw"] == "402160000000"
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    assert aud["kind"] == "sell"
    assert aud["quantity_raw"] == "402160000000"
    assert Decimal(str(aud.get("consideration_usdc") or 0)) == Decimal("317.208149")


def test_dflow_swap2_unwrap_token_hand_deltas():
    """2gPk 4WeDYptj (run-7 venue example) is Swap2 + unwrap, token↔SOL.

    Hand: −308_290_000 raw CASHx9KJ against 2.505635336 SOL. Unwrap is not a
    second swap.
    """
    payload = _load("dflow-swap-unwrap-token.json")
    decoded, trades = _app_trades(payload)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["kind"] == "sell"
    assert trade["mint"].startswith("CASHx9KJ")
    assert trade["quantity_raw"] == "308290000"
    assert Decimal(str(trade.get("amount_sol") or trade.get("consideration_sol"))) == Decimal("2.505635336")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    assert aud
    assert aud["kind"] == "sell"
    assert aud["quantity_raw"] == "308290000"
    assert Decimal(aud["consideration_sol"]) == Decimal("2.505635336")


def test_dflow_transfer_fee_is_not_a_swap():
    payload = _load("dflow-transfer-fee-not-swap.json")
    decoded, trades = _app_trades(payload)
    assert trades == []
    assert decoded.get("unresolved")
    assert auditor.reconstruct_record(payload["record"], payload["address"]) is None


def test_dflow_fixture_without_reconciliation_stays_unresolved():
    """25865JdB multi-hop: app may now isolate H4KUxs if wrap/settlement
    reconciles; otherwise it stays unresolved. Never a silent zero-basis.
    """
    payload = _load("dflow-swap.json")
    decoded, trades = _app_trades(payload)
    if trades:
        trade = trades[0]
        assert trade["mint"].startswith("H4KUxs")
        assert Decimal(str(trade.get("amount_sol") or trade.get("consideration_sol") or 0)) > 0 or Decimal(
            str(trade.get("amount_usdc") or trade.get("consideration_usdc") or 0)
        ) > 0
    else:
        assert decoded.get("unresolved")
    aud = auditor.reconstruct_record(payload["record"], payload["address"])
    if aud is not None:
        usdc = Decimal(str(aud.get("consideration_usdc") or 0))
        sol = Decimal(str(aud.get("consideration_sol") or 0))
        assert usdc > 0 or sol > 0
