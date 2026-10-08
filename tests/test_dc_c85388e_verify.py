"""Reproduce and lock the c85388e verify defects. Offline. PRODUCT_READY false."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal

from scanner.investigation import OKX_DEX_V2, TITAN, net_balance_reviewed_swap
from scanner.mass_search.live_e2e import _phase2_finish
from scanner.mass_search.qualification_gates import (
    mandatory_coverage_gate,
    raw_economic_keys_for_tx,
)
from scanner.mass_search.readable_first import DEFER_UNREADABLE, KEEP, walk_ranked
from scanner.mass_search.research_profile import _episode_ledger_from_report
from scanner.mass_search.result_relevant_coverage import (
    COVERAGE_GATE_VERSION,
    build_result_relevant,
)
import tools.independent_episode_audit as auditor
from tests.test_d377_verify_fixes import THIRD, TOKEN, WALLET as CLMM_WALLET, _clmm_buy
from tests.test_jup6_hop_and_fifo_window import ENAAT, ENAAT_SIG, SYSTEM, _jup6_hop_tx
from tests.test_result_relevant_coverage import (
    END_UNIX,
    IN_WINDOW,
    MINT,
    OLD_2024,
    OTHER,
    OTHER_ATA,
    REPORT_END,
    REPORT_START,
    START_UNIX,
    TOKEN_ATA,
    USDC,
    WALLET,
    _decoded_sell,
    _swap,
)

WSOL = "So11111111111111111111111111111111111111112"


def _base_clean(n=60):
    recs, evs = [], []
    for i in range(n):
        sig = f"clean-{i}"
        recs.append(_swap(
            signature=sig, mint=MINT, token_ata=TOKEN_ATA,
            token_pre="1000000", token_post="0",
            usdc_pre="0", usdc_post="100000000",
            block_time=IN_WINDOW + i,
        ))
        evs.append(_decoded_sell(sig))
    return recs, evs


def _unreadable_no_lists(sig, t, sol_delta_lamports=-10_000_000_000):
    row = _swap(
        signature=sig, mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="5000000",
        usdc_pre="0", usdc_post="0", block_time=t,
    )
    row["meta"]["preTokenBalances"] = None
    row["meta"]["postTokenBalances"] = None
    row["meta"]["preBalances"][0] = 20_000_000_000
    row["meta"]["postBalances"][0] = 20_000_000_000 + sol_delta_lamports
    return row


def _rr_gate(recs, evs):
    rr = build_result_relevant(
        recs, {"events": evs}, WALLET,
        report_start=REPORT_START, report_end=REPORT_END,
        ledger=[{"mint": MINT}],
    )
    trades = [{
        "kind": "sell", "signature": e["signature"], "mint": e["mint"],
        "timestamp": e["timestamp"], "consideration_usdc": e["consideration_usdc"],
        "settlement_asset": "USDC",
    } for e in evs]
    aud = auditor.result_relevant_coverage(
        WALLET, recs, trades, [{"mint": MINT}],
        report_start=START_UNIX, report_end=END_UNIX,
    )
    gate = mandatory_coverage_gate({
        "record_breakdown": {"result_relevant": rr},
        "independent_audit": {"result_relevant": aud},
    })
    return rr, aud, gate


def test_dc1_inwindow_unreadable_unknown_mints_blocks():
    recs, evs = _base_clean()
    extra = _unreadable_no_lists("a-unread", IN_WINDOW + 500)
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert gate["passed"] is False


def test_dc1_inwindow_mintless_row_blocks():
    recs, evs = _base_clean()
    extra = _swap(
        signature="a2-mintless", mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="5000000",
        usdc_pre="900000000", usdc_post="0",
        block_time=IN_WINDOW + 600, drop_mint=True,
    )
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert gate["passed"] is False


def test_dc1_five_inwindow_unreadables_drop_count_share():
    recs, evs = _base_clean()
    extras = [_unreadable_no_lists(f"a3-{i}", IN_WINDOW + 700 + i) for i in range(5)]
    rr, aud, gate = _rr_gate(recs + extras, evs)
    assert rr["unsupported_n"] >= 5
    assert Decimal(str(rr["count_share"])) < Decimal("0.99")
    assert gate["passed"] is False


def test_dc2_lineage_otc_buy_is_counted():
    recs, evs = _base_clean()
    extra = _swap(
        signature="b2-otc", mint=MINT, token_ata=TOKEN_ATA,
        token_pre="0", token_post="1000000",
        usdc_pre="0", usdc_post="0", block_time=OLD_2024,
    )
    extra["transaction"]["message"]["instructions"] = [
        {"programId": "11111111111111111111111111111111", "accounts": [WALLET], "data": "x"},
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "accounts": [WALLET], "data": "y"},
    ]
    extra["meta"]["preBalances"][0] = 20_000_000_000
    extra["meta"]["postBalances"][0] = 10_000_000_000
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] in rr["signatures"]
    assert extra["signature"] in aud["signatures"]
    assert rr["denominator"] == rr["decoded_n"] + rr["unsupported_n"]
    assert rr["decoded_n"] + rr["unsupported_n"] >= 61
    assert gate["passed"] is False


def test_dc4_missing_r_blocks_and_does_not_fall_back():
    gate = mandatory_coverage_gate({
        "record_breakdown": {
            "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"USDC": "0"}},
        }
    })
    assert gate["passed"] is False
    assert gate["count_share"] is None
    assert "missing" in (gate.get("reason") or "")


def test_dc4_wrong_version_blocks():
    relevant = {
        "version": "whole-span-v0",
        "signatures": ["x"],
        "size": 1,
        "empty": False,
        "denominator": 1,
        "unsupported_swap_share": {"by_count": "0", "by_consideration": {"USDC": "0"}},
        "count_share": "1",
        "value_share": "1",
        "gate_passed": True,
    }
    gate = mandatory_coverage_gate({"record_breakdown": {"result_relevant": relevant}})
    assert gate["passed"] is False
    assert "version" in (gate.get("reason") or "")


def test_dc5_recovery_refuses_taint():
    t0 = int(datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp())

    def ev(kind, sig, units, sol, ts, **extra):
        row = {
            "kind": kind, "signature": sig, "mint": MINT, "units": str(units),
            "timestamp": ts, "order": ts, "settlement_asset": "SOL",
            "quote_mint": WSOL, "amount_sol": str(sol), "consideration_sol": str(sol),
        }
        row.update(extra)
        return row

    for extra in (
        {"partial_known_cost": True},
        {"whole_sale_pnl_resolved": False},
        {"quarantined": True},
        {"transfer_in_zero_basis": True},
        {"undecoded_buy": True},
    ):
        report = {
            "window": {"start": REPORT_START, "end": REPORT_END},
            "events": [ev("buy", "b1", 1000, "1", t0), ev("sell", "s1", 1000, "3", t0 + 60, **extra)],
            "worksheet": {"sale_rows": []},
        }
        assert _episode_ledger_from_report(report) == []


def test_dc8_phase2_drop_wins_over_keep_stamp(tmp_path):
    rows = [
        {"address": "A_dropped_unsupported_heavy", "dropped": True,
         "drop_reason": "unsupported_program_heavy", "funnel_decision": KEEP,
         "nansen_realized_pnl_usd": "900000", "coverability_rank_key": 0},
        {"address": "B_dropped_bundle", "dropped": True,
         "drop_reason": "bundle_or_distribution", "funnel_decision": KEEP,
         "nansen_realized_pnl_usd": "800000", "coverability_rank_key": 0},
        {"address": "C_dropped_min_in_window", "dropped": True,
         "drop_reason": "below_min_in_window_tx", "funnel_decision": KEEP,
         "nansen_realized_pnl_usd": "700000", "coverability_rank_key": 0},
        {"address": "E_deferred", "dropped": False, "deferred": True,
         "funnel_decision": DEFER_UNREADABLE, "nansen_realized_pnl_usd": "500000",
         "coverability_rank_key": 0},
        {"address": "F_clean_keep", "dropped": False, "funnel_decision": KEEP,
         "nansen_realized_pnl_usd": "100", "coverability_rank_key": 0},
    ]
    walked = walk_ranked(rows, n=3)
    assert [row["address"] for row in walked["kept"]] == ["F_clean_keep"]
    assert {row["address"] for row in walked["dropped"]} >= {
        "A_dropped_unsupported_heavy", "B_dropped_bundle", "C_dropped_min_in_window",
    }
    cfg = {"readable_first": True, "readable_first_n": 3, "output_dir": tmp_path}
    out = _phase2_finish(cfg, {}, [dict(row) for row in rows])
    assert out["kept"] == ["F_clean_keep"]


def test_dc9_inner_third_party_sol_inflow_refused():
    raw = _clmm_buy(native_post=1_999_995_000 + 500_000_000)
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": "11111111111111111111111111111111",
        "parsed": {"type": "transfer", "info": {
            "source": THIRD,
            "destination": CLMM_WALLET, "lamports": 500_000_000,
        }},
    })
    assert net_balance_reviewed_swap(raw, CLMM_WALLET) is None
    assert auditor.reconstruct_record(raw, CLMM_WALLET) is None


def test_dc9_fee_sized_inflow_is_not_a_fee():
    raw = _clmm_buy(native_post=1_999_995_000 + 19_000_000)
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": "11111111111111111111111111111111",
        "parsed": {"type": "transfer", "info": {
            "source": THIRD,
            "destination": CLMM_WALLET, "lamports": 19_000_000,
        }},
    })
    assert net_balance_reviewed_swap(raw, CLMM_WALLET) is None
    assert auditor.reconstruct_record(raw, CLMM_WALLET) is None


def test_dc9_titan_and_okx_inner_inflow_refused():
    for prog in (TITAN, OKX_DEX_V2):
        raw = _clmm_buy(native_post=1_999_995_000 + 500_000_000)
        raw["transaction"]["message"]["instructions"][0]["programId"] = prog
        raw["transaction"]["message"]["accountKeys"][7] = prog
        raw["meta"]["innerInstructions"][0]["instructions"].append({
            "programId": "11111111111111111111111111111111",
            "parsed": {"type": "transfer", "info": {
                "source": THIRD, "destination": CLMM_WALLET, "lamports": 500_000_000,
            }},
        })
        assert net_balance_reviewed_swap(raw, CLMM_WALLET) is None
        assert auditor.reconstruct_record(raw, CLMM_WALLET) is None


def test_dc9_jup6_hop_sol_credit_refused():
    from tests.test_jup6_hop_and_fifo_window import POOL_AUTH
    raw = _jup6_hop_tx(ENAAT, ENAAT_SIG)
    raw["meta"]["postBalances"][0] += 400_000_000_000
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": SYSTEM, "stackHeight": 3,
        "parsed": {"type": "transfer", "info": {
            "source": POOL_AUTH, "destination": ENAAT, "lamports": 400_000_000_000,
        }},
    })
    assert net_balance_reviewed_swap(raw, ENAAT) is None
    assert auditor.reconstruct_record(raw, ENAAT) is None
    raw2 = _jup6_hop_tx(ENAAT, ENAAT_SIG)
    raw2["meta"]["postBalances"][0] += 400_000_000_000
    assert net_balance_reviewed_swap(raw2, ENAAT) is None
    assert auditor.reconstruct_record(raw2, ENAAT) is None


def test_dc10_missing_timestamp_keeps_reason():
    dropped = auditor._losing_drop(MINT, Decimal("-1"), "USDC", None, "unflattened_losing_inventory")
    assert dropped["reason"] == "unflattened_losing_inventory"
    assert dropped["timestamp"] is None


def test_dc11_out_of_window_zero_value_not_in_keys_does_not_block():
    recs, evs = _base_clean()
    spam = _swap(
        signature="spam-airdrop", mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="1",
        usdc_pre="0", usdc_post="0", block_time=OLD_2024,
    )
    keys = spam["transaction"]["message"]["accountKeys"]
    keys[0] = "NotTheWallet11111111111111111111111111112"
    rr, aud, gate = _rr_gate(recs + [spam], evs)
    assert "spam-airdrop" not in rr["signatures"]
    assert "spam-airdrop" not in aud["signatures"]
    assert gate["passed"] is True


def test_dc6_unreviewed_swap_log_tip_fill_counts():
    unknown = "UnkRouter111111111111111111111111111111112"
    record = _swap(
        signature="tip-fill", mint=OTHER, token_ata=OTHER_ATA,
        token_pre="0", token_post="200000",
        usdc_pre="0", usdc_post="0", block_time=IN_WINDOW,
    )
    record["transaction"]["message"]["instructions"][0]["programId"] = unknown
    record["transaction"]["message"]["accountKeys"][5] = unknown
    record["meta"]["preBalances"][0] = 2_000_000_000
    record["meta"]["postBalances"][0] = 2_000_000_000 - 200_000
    record["meta"]["logMessages"] = ["Program log: Instruction: Swap"]
    assert raw_economic_keys_for_tx(record, WALLET) >= 1


def test_dc7_auditor_catches_planted_app_membership_bug(monkeypatch):
    import scanner.mass_search.result_relevant_coverage as rrc
    orig = rrc.relevant_membership

    def broken(*args, **kwargs):
        rows = orig(*args, **kwargs)
        for row in rows:
            if any("unreadable" in str(reason) for reason in row.get("reasons") or []):
                row["in_r"] = False
                row["reasons"] = []
        return rows

    monkeypatch.setattr(rrc, "relevant_membership", broken)
    recs, evs = _base_clean()
    extra = _unreadable_no_lists("planted", IN_WINDOW + 9)
    app = rrc.build_result_relevant(
        recs + [extra], {"events": evs}, WALLET,
        report_start=REPORT_START, report_end=REPORT_END,
        ledger=[{"mint": MINT}],
    )
    trades = [{
        "kind": "sell", "signature": e["signature"], "mint": e["mint"],
        "timestamp": e["timestamp"], "consideration_usdc": e["consideration_usdc"],
        "settlement_asset": "USDC",
    } for e in evs]
    aud = auditor.result_relevant_coverage(
        WALLET, recs + [extra], trades, [{"mint": MINT}],
        report_start=START_UNIX, report_end=END_UNIX,
    )
    assert extra["signature"] not in app["signatures"]
    assert extra["signature"] in aud["signatures"]
    gate = mandatory_coverage_gate({
        "record_breakdown": {"result_relevant": app},
        "independent_audit": {"result_relevant": aud},
    })
    assert gate["passed"] is False


def test_dc7_auditor_catches_planted_app_inflow_accept(monkeypatch):
    import scanner.investigation as inv
    monkeypatch.setattr(inv, "_non_route_wallet_flow", lambda *a, **k: False)
    monkeypatch.setattr(inv, "_route_flow_disagrees_with_wallet", lambda *a, **k: False)
    raw = _clmm_buy(native_post=1_999_995_000 + 500_000_000)
    raw["meta"]["innerInstructions"][0]["instructions"].append({
        "programId": "11111111111111111111111111111111",
        "parsed": {"type": "transfer", "info": {
            "source": THIRD,
            "destination": CLMM_WALLET, "lamports": 500_000_000,
        }},
    })
    planted = net_balance_reviewed_swap(raw, CLMM_WALLET)
    assert planted is not None
    assert auditor.reconstruct_record(raw, CLMM_WALLET) is None


def test_dc3_auditor_r_does_not_import_app():
    assert auditor.result_relevant_coverage.__module__ == "tools.independent_episode_audit"
    assert auditor._auditor_touched_mints.__module__ == "tools.independent_episode_audit"
    assert "scanner.mass_search.result_relevant_coverage" not in (
        auditor.result_relevant_coverage.__globals__.get("__name__", "")
    )


def test_failed_inwindow_unreadable_stays_out():
    recs, evs = _base_clean()
    extra = _unreadable_no_lists("e-failed", IN_WINDOW + 900)
    extra["meta"]["err"] = {"x": 1}
    rr, aud, gate = _rr_gate(recs + [extra], evs)
    assert extra["signature"] not in rr["signatures"]
    assert extra["signature"] not in aud["signatures"]
    assert gate["passed"] is True
    assert COVERAGE_GATE_VERSION == "result-relevant-v1"
