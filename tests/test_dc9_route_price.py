"""NEW-1..5 and DC-11: route-leg price, own-ATA rent, fail-closed. Offline only."""
from __future__ import annotations

from decimal import Decimal

from scanner.investigation import (
    JUPITER,
    OKX_DEX_V2,
    RAYDIUM_CLMM,
    TITAN,
    _jupiter_hop_inner_ok,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.qualification_gates import mandatory_coverage_gate
from scanner.mass_search.readable_first import merge_funnel_reports
from scanner.mass_search.result_relevant_coverage import wallet_touched_mints
import tools.independent_episode_audit as auditor
from tests.test_d377_verify_fixes import (
    THIRD,
    THIRD_ATA,
    TOKEN,
    WALLET as CLMM_WALLET,
    WSOL_ATA,
    _clmm_buy,
)
from tests.test_dc_c85388e_verify import _base_clean, _rr_gate
from tests.test_jup6_hop_and_fifo_window import (
    ENAAT,
    ENAAT_SIG,
    SYSTEM,
    UNKNOWN_PROP_AMM,
    USDC_ATA,
    _app_keys,
    _jup6_hop_tx,
)
from tests.test_result_relevant_coverage import (
    IN_WINDOW,
    MINT,
    OLD_2024,
    OTHER,
    OTHER_ATA,
    USDC,
    WALLET,
    _swap,
)

TOKEN_RENT = 2_039_280
OWN_ATA = "Nb3OwnCloseAta111111111111111111111111112"


def _trades(decoded):
    return [
        event for event in decoded.get("events") or []
        if event.get("kind") in {"buy", "sell", "conversion"}
    ]


def _programize(raw, program):
    raw["transaction"]["message"]["instructions"][0]["programId"] = program
    raw["transaction"]["message"]["accountKeys"][7] = program
    return raw


def _cosign(raw):
    msg = raw["transaction"]["message"]
    keys = msg["accountKeys"]
    keys[1], keys[5] = keys[5], keys[1]
    for lst in (raw["meta"]["preBalances"], raw["meta"]["postBalances"]):
        lst[1], lst[5] = lst[5], lst[1]
    for lst in (raw["meta"]["preTokenBalances"], raw["meta"]["postTokenBalances"]):
        for row in lst:
            if row["accountIndex"] == 1:
                row["accountIndex"] = 5
            elif row["accountIndex"] == 5:
                row["accountIndex"] = 1
    msg["header"]["numRequiredSignatures"] = 2


def _credit(raw, shape, amt):
    inner = raw["meta"]["innerInstructions"][0]["instructions"]
    third_ata_idx = 6
    if shape == "lamport_only":
        return raw
    if shape == "close_third_ata_to_wallet_inner":
        _cosign(raw)
        inner.append({
            "programId": TOKEN,
            "parsed": {
                "type": "closeAccount",
                "info": {"account": THIRD_ATA, "destination": CLMM_WALLET, "owner": THIRD},
            },
        })
        raw["meta"]["preBalances"][third_ata_idx] = amt
        raw["meta"]["postBalances"][third_ata_idx] = 0
        return raw
    if shape == "close_third_ata_to_wallet_outer":
        _cosign(raw)
        raw["transaction"]["message"]["instructions"].append({
            "programId": TOKEN,
            "parsed": {
                "type": "closeAccount",
                "info": {"account": THIRD_ATA, "destination": CLMM_WALLET, "owner": THIRD},
            },
        })
        raw["meta"]["preBalances"][third_ata_idx] = amt
        raw["meta"]["postBalances"][third_ata_idx] = 0
        return raw
    if shape == "unwrap_wsol_extra":
        inner.append({
            "programId": TOKEN,
            "parsed": {
                "type": "closeAccount",
                "info": {"account": WSOL_ATA, "destination": CLMM_WALLET, "owner": CLMM_WALLET},
            },
        })
        return raw
    raise AssertionError(shape)


def _own_ata_close(raw, rent=TOKEN_RENT):
    keys = raw["transaction"]["message"]["accountKeys"]
    keys.append(OWN_ATA)
    raw["meta"]["preBalances"].append(rent)
    raw["meta"]["postBalances"].append(0)
    raw["meta"]["preTokenBalances"].append({
        "accountIndex": len(keys) - 1,
        "mint": MINT,
        "owner": CLMM_WALLET,
        "uiTokenAmount": {"amount": "0", "decimals": 6},
    })
    raw["meta"]["postTokenBalances"].append({
        "accountIndex": len(keys) - 1,
        "mint": MINT,
        "owner": CLMM_WALLET,
        "uiTokenAmount": {"amount": "0", "decimals": 6},
    })
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": TOKEN,
        "parsed": {
            "type": "closeAccount",
            "info": {"account": OWN_ATA, "destination": CLMM_WALLET, "owner": CLMM_WALLET},
        },
    })
    raw["meta"]["postBalances"][0] = raw["meta"]["postBalances"][0] + rent
    return raw


def _consideration(raw, wallet=CLMM_WALLET):
    app = net_balance_reviewed_swap(raw, wallet)
    aud = auditor.reconstruct_record(raw, wallet)
    return app, aud


def test_new1_control_still_prices_one_sol():
    raw = _clmm_buy()
    app, aud = _consideration(raw)
    assert app and aud
    assert abs(Decimal(app["settlement"])) == Decimal(1_000_000_000)
    assert Decimal(str(aud["consideration_sol"])) == Decimal("1")


def test_new1_third_party_credits_refused_on_quoted_routes():
    shapes = (
        "lamport_only",
        "close_third_ata_to_wallet_inner",
        "close_third_ata_to_wallet_outer",
        "unwrap_wsol_extra",
    )
    for program in (RAYDIUM_CLMM, TITAN, OKX_DEX_V2, JUPITER):
        for shape in shapes:
            for amt in (19_000_000, TOKEN_RENT, 25_000_000):
                raw = _programize(_clmm_buy(native_post=1_999_995_000 + amt), program)
                raw = _credit(raw, shape, amt)
                app, aud = _consideration(raw)
                assert app is None, (program, shape, amt, app)
                assert aud is None, (program, shape, amt, aud)


def test_new1_own_ata_rent_does_not_lower_cost():
    raw = _own_ata_close(_clmm_buy())
    app, aud = _consideration(raw)
    assert app and aud
    assert abs(Decimal(app["settlement"])) == Decimal(1_000_000_000)
    assert Decimal(str(aud["consideration_sol"])) == Decimal("1")


def test_new1_own_ata_close_above_rent_refused():
    raw = _own_ata_close(_clmm_buy(native_post=1_999_995_000 + 19_000_000), rent=TOKEN_RENT)
    app, aud = _consideration(raw)
    assert app is None
    assert aud is None


def test_new2_auditor_refuses_025_at_least_as_strict():
    raw = _programize(_clmm_buy(native_post=1_999_995_000 + 25_000_000), RAYDIUM_CLMM)
    raw = _credit(raw, "close_third_ata_to_wallet_inner", 25_000_000)
    assert net_balance_reviewed_swap(raw, CLMM_WALLET) is None
    assert auditor.reconstruct_record(raw, CLMM_WALLET) is None
    raw2 = _programize(_clmm_buy(native_post=1_999_995_000 + 25_000_000), RAYDIUM_CLMM)
    raw2 = _credit(raw2, "unwrap_wsol_extra", 25_000_000)
    assert net_balance_reviewed_swap(raw2, CLMM_WALLET) is None
    assert auditor.reconstruct_record(raw2, CLMM_WALLET) is None


def test_new3_missing_owner_is_unreadable_in_keys():
    recs, evs = _base_clean()
    extra = _swap(
        signature="k1-no-owner", mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="5000000",
        usdc_pre="50000000000", usdc_post="0",
        block_time=IN_WINDOW + 800,
    )
    for side in ("preTokenBalances", "postTokenBalances"):
        for row in extra["meta"][side]:
            row.pop("owner", None)
    assert wallet_touched_mints(extra, WALLET) is None
    assert auditor._auditor_touched_mints(extra, WALLET) is None
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert gate["passed"] is False


def test_new3_missing_owner_wallet_not_in_keys_blocks():
    recs, evs = _base_clean()
    extra = _swap(
        signature="n2-no-owner", mint=MINT, token_ata=OTHER_ATA,
        token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="0",
        block_time=IN_WINDOW + 701,
    )
    keys = extra["transaction"]["message"]["accountKeys"]
    extra["transaction"]["message"]["accountKeys"] = [
        "KeeperXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" if k == WALLET else k for k in keys
    ]
    for side in ("preTokenBalances", "postTokenBalances"):
        for row in extra["meta"][side]:
            row.pop("owner", None)
    assert wallet_touched_mints(extra, WALLET) is None
    assert auditor._auditor_touched_mints(extra, WALLET) is None
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert gate["passed"] is False


def test_new4_jup6_hop_wallet_usdc_to_third_refused():
    third = "Thirdparty1111111111111111111111111111111112"
    third_ata = "ThirdAta11111111111111111111111111111111112"
    raw = _jup6_hop_tx(ENAAT, ENAAT_SIG, hop_amm=UNKNOWN_PROP_AMM)
    raw["transaction"]["message"]["accountKeys"].extend([third, third_ata])
    raw["meta"]["preBalances"].extend([0, 0])
    raw["meta"]["postBalances"].extend([0, 0])
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": TOKEN,
        "stackHeight": 3,
        "parsed": {
            "type": "transfer",
            "info": {
                "source": USDC_ATA,
                "destination": third_ata,
                "authority": ENAAT,
                "amount": "1000000",
            },
        },
    })
    keys = _app_keys(raw)
    assert _jupiter_hop_inner_ok(raw, ENAAT, keys) is False
    assert auditor._jupiter_hop_inner_ok(raw, ENAAT, auditor._keys(raw)) is False
    assert net_balance_reviewed_swap(raw, ENAAT) is None
    assert auditor.reconstruct_record(raw, ENAAT) is None
    assert _trades(decode_supported_swaps(canonical_decode_records([raw]), ENAAT)) == []


def test_new5_merged_funnel_one_status_latest_wins():
    prior = {
        "kind": "readable-first-funnel-v1",
        "kept": ["keep1", "later_drop"],
        "deferred_unreadable": [],
        "dropped": [{"address": "already_dropped", "reason": "bot"}],
        "unscreened": [],
        "examined": 3,
        "dominant_unreadable_programs": [],
    }
    incoming = {
        "kind": "readable-first-funnel-v1",
        "kept": ["keep2"],
        "deferred_unreadable": [],
        "dropped": [{"address": "later_drop", "reason": "unsupported_program_heavy"}],
        "unscreened": [],
        "examined": 2,
        "dominant_unreadable_programs": [],
    }
    out = merge_funnel_reports(prior, incoming)
    assert out["kept"] == ["keep1", "keep2"]
    assert "later_drop" not in out["kept"]
    dropped = {row["address"]: row["reason"] for row in out["dropped"]}
    assert dropped["later_drop"] == "unsupported_program_heavy"
    assert dropped["already_dropped"] == "bot"
    addresses = [row["address"] for row in out["history"]]
    assert addresses.count("later_drop") >= 2
    statuses = [row["status"] for row in out["history"] if row["address"] == "later_drop"]
    assert statuses[-1] == "dropped"


def test_dc11_in_window_usdc_wallet_not_in_keys_blocks_both():
    recs, evs = _base_clean()
    extra = _swap(
        signature="n4-usdc-notinkeys", mint=USDC, token_ata=OTHER_ATA,
        token_pre="0", token_post="50000000000",
        usdc_pre="0", usdc_post="0",
        block_time=IN_WINDOW + 703,
    )
    extra["meta"]["preTokenBalances"] = [{
        "accountIndex": 1, "mint": USDC, "owner": WALLET,
        "uiTokenAmount": {"amount": "0", "decimals": 6},
    }]
    extra["meta"]["postTokenBalances"] = [{
        "accountIndex": 1, "mint": USDC, "owner": WALLET,
        "uiTokenAmount": {"amount": "50000000000", "decimals": 6},
    }]
    keys = extra["transaction"]["message"]["accountKeys"]
    extra["transaction"]["message"]["accountKeys"] = [
        "KeeperXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" if k == WALLET else k for k in keys
    ]
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert extra["signature"] in rr["signatures"]
    assert gate["passed"] is False


def test_dc11_out_of_window_spam_stays_out():
    recs, evs = _base_clean()
    extra = _swap(
        signature="n5-spam", mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="5000000",
        usdc_pre="0", usdc_post="0",
        block_time=OLD_2024,
    )
    keys = extra["transaction"]["message"]["accountKeys"]
    extra["transaction"]["message"]["accountKeys"] = [
        "KeeperXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" if k == WALLET else k for k in keys
    ]
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] not in rr["signatures"]
    assert extra["signature"] not in aud["signatures"]
    assert gate["passed"] is True
