"""Result-relevant coverage gate. Offline only. PRODUCT_READY stays false."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from scanner.investigation import JUPITER, USDC, WSOL
from scanner.mass_search.qualification_gates import coverage_shares, mandatory_coverage_gate
from scanner.mass_search.record_breakdown import partition_records
from scanner.mass_search.result_relevant_coverage import (
    COVERAGE_GATE_VERSION,
    build_result_relevant,
    lineage_mints,
    wallet_touched_mints,
)
from scanner.mass_search.workflow import coverage_eligibility
import tools.independent_episode_audit as auditor

WALLET = "RrelWallet1111111111111111111111111111112"
MINT = "RrelMint111111111111111111111111111111112"
OTHER = "RrelOther11111111111111111111111111111112"
TOKEN_ATA = "RrelTokAta1111111111111111111111111111112"
OTHER_ATA = "RrelOthAta1111111111111111111111111111112"
USDC_ATA = "RrelUsdcAta111111111111111111111111111112"
WSOL_ATA = "RrelWsolAta111111111111111111111111111112"
POOL_TOK = "RrelPoolTok111111111111111111111111111112"
POOL_USDC = "RrelPoolUsdc11111111111111111111111111112"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
REPORT_START = "2026-09-05T13:29:27Z"
REPORT_END = "2026-10-05T13:29:27Z"
START_UNIX = int(datetime.fromisoformat("2026-09-05T13:29:27+00:00").timestamp())
END_UNIX = int(datetime.fromisoformat("2026-10-05T13:29:27+00:00").timestamp())
IN_WINDOW = START_UNIX + 86400
OLD_2024 = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())


def _swap(
    *,
    signature,
    mint,
    token_ata,
    token_pre,
    token_post,
    usdc_pre,
    usdc_post,
    block_time,
    drop_mint=False,
):
    pre_token = [
        {"accountIndex": 1, "mint": mint, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
        {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_pre, "decimals": 6}},
    ]
    post_token = [
        {"accountIndex": 1, "mint": mint, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}},
        {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_post, "decimals": 6}},
    ]
    if drop_mint:
        pre_token[0] = {"accountIndex": 1, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}}
        post_token[0] = {"accountIndex": 1, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}}
    return {
        "signature": signature,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [WALLET, token_ata, USDC_ATA, POOL_TOK, POOL_USDC, JUPITER, TOKEN],
                "instructions": [{"programId": JUPITER, "accounts": [WALLET, token_ata, USDC_ATA], "data": "route"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "postBalances": [1_999_995_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "preTokenBalances": pre_token,
            "postTokenBalances": post_token,
        },
    }


def _decoded_sell(signature, mint=MINT, amount="100", timestamp=IN_WINDOW, kind="sell"):
    return {
        "kind": kind,
        "signature": signature,
        "mint": mint,
        "timestamp": timestamp,
        "amount_usdc": amount,
        "consideration_usdc": amount,
        "settlement_asset": "USDC",
    }


def _relevant(records, events, ledger=None):
    return build_result_relevant(
        records,
        {"events": events},
        WALLET,
        report_start=REPORT_START,
        report_end=REPORT_END,
        ledger=ledger,
    )


def test_unreadable_2024_unrelated_exited_token_no_longer_blocks():
    clean = _swap(
        signature="in-window-clean",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    old = _swap(
        signature="old-unrelated",
        mint=OTHER,
        token_ata=OTHER_ATA,
        token_pre="5000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="50000000",
        block_time=OLD_2024,
    )
    events = [_decoded_sell("in-window-clean")]
    relevant = _relevant([clean, old], events, ledger=[{"mint": MINT, "close_signature": "in-window-clean"}])
    assert "old-unrelated" not in relevant["signatures"]
    assert "in-window-clean" in relevant["signatures"]
    assert OTHER not in relevant["lineage_mints"]
    assert MINT in relevant["lineage_mints"]
    assert relevant["coverage_count_share"] == "1"
    assert relevant["coverage_value_share"] == "1"
    report = {
        "record_breakdown": {
            "result_relevant": relevant,
            "unsupported_swap_share_in_window": {
                "by_count": "0.5",
                "by_consideration": {"USDC": "0.5"},
            },
        }
    }
    gate = mandatory_coverage_gate(report)
    assert gate["passed"] is True
    shares = coverage_shares(report)
    assert shares["coverage_gate_version"] == COVERAGE_GATE_VERSION
    assert shares["coverage_count_share"] == "1"
    assert shares["coverage_count_share_whole_span"] == "0.5"


def test_unreadable_prewindow_lineage_mint_blocks():
    window_sell = _swap(
        signature="window-sell",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    old_lineage = _swap(
        signature="old-lineage",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="0",
        token_post="1000000",
        usdc_pre="100000000",
        usdc_post="0",
        block_time=OLD_2024,
    )
    events = [_decoded_sell("window-sell")]
    relevant = _relevant(
        [window_sell, old_lineage],
        events,
        ledger=[{"mint": MINT, "close_signature": "window-sell"}],
    )
    assert "old-lineage" in relevant["signatures"]
    assert relevant["gate_passed"] is False
    report = {"record_breakdown": {"result_relevant": relevant}}
    gate = mandatory_coverage_gate(report)
    assert gate["passed"] is False


def test_unreadable_in_window_trade_blocks():
    unsupported = _swap(
        signature="in-window-unsupported",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    relevant = _relevant([unsupported], [])
    assert "in-window-unsupported" in relevant["signatures"]
    assert relevant["unsupported_n"] == 1
    assert relevant["gate_passed"] is False
    gate = mandatory_coverage_gate({"record_breakdown": {"result_relevant": relevant}})
    assert gate["passed"] is False


def test_unreadable_indeterminable_mints_blocks():
    clean = _swap(
        signature="in-window-clean",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    unknown = _swap(
        signature="old-unknown-mints",
        mint=OTHER,
        token_ata=OTHER_ATA,
        token_pre="5000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="50000000",
        block_time=OLD_2024,
        drop_mint=True,
    )
    assert wallet_touched_mints(unknown, WALLET) is None
    events = [_decoded_sell("in-window-clean")]
    relevant = _relevant([clean, unknown], events, ledger=[{"mint": MINT}])
    assert "old-unknown-mints" in relevant["signatures"]
    assert relevant["gate_passed"] is False


def test_truncated_history_before_lineage_buy_still_blocks():
    relevant = {
        "version": COVERAGE_GATE_VERSION,
        "signatures": ["sell-only"],
        "size": 1,
        "empty": False,
        "lineage_mints": [MINT],
        "unsupported_swap_share": {"by_count": "0", "by_consideration": {"USDC": "0"}},
        "count_share": Decimal("1"),
        "value_share": Decimal("1"),
        "gate_passed": True,
    }
    report = {
        "record_breakdown": {"result_relevant": relevant},
        "worksheet": {"unresolved_basis_sales": 1},
    }
    profile = {
        "coverage_count_share": "1",
        "coverage_value_share": "1",
        "unresolved_basis_sales": 1,
        "result_relevant": relevant,
    }
    judged = coverage_eligibility(report, profile)
    assert judged["status"] != "provisional_eligible"
    assert judged["dependency_unresolved_basis"] is True


def test_app_auditor_r_disagreement_blocks():
    relevant = {
        "version": COVERAGE_GATE_VERSION,
        "signatures": ["app-only"],
        "size": 1,
        "empty": False,
        "lineage_mints": [MINT],
        "unsupported_swap_share": {"by_count": "0", "by_consideration": {"USDC": "0"}},
        "count_share": Decimal("1"),
        "value_share": Decimal("1"),
        "gate_passed": True,
    }
    report = {
        "record_breakdown": {"result_relevant": relevant},
        "independent_audit": {
            "result_relevant": {
                "signatures": ["auditor-only"],
                "gate_passed": True,
            }
        },
    }
    gate = mandatory_coverage_gate(report)
    assert gate["passed"] is False
    assert "disagree" in (gate.get("reason") or "")


def test_adding_unreadable_to_r_never_raises_coverage():
    clean = _swap(
        signature="in-window-clean",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    extra = _swap(
        signature="in-window-unreadable",
        mint=OTHER,
        token_ata=OTHER_ATA,
        token_pre="2000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="20000000",
        block_time=IN_WINDOW,
    )
    events = [_decoded_sell("in-window-clean")]
    base = _relevant([clean], events, ledger=[{"mint": MINT}])
    added = _relevant([clean, extra], events, ledger=[{"mint": MINT}])
    assert extra["signature"] in added["signatures"]
    assert Decimal(str(added["count_share"])) <= Decimal(str(base["count_share"]))
    assert Decimal(str(added["value_share"])) <= Decimal(str(base["value_share"]))


def test_empty_r_blocks():
    transfer = {
        "signature": "memo-only",
        "blockTime": IN_WINDOW,
        "transaction": {
            "signatures": ["memo-only"],
            "message": {"accountKeys": [WALLET], "instructions": []},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [1_000_000_000],
            "postBalances": [999_995_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    relevant = _relevant([transfer], [])
    assert relevant["empty"] is True
    gate = mandatory_coverage_gate({"record_breakdown": {"result_relevant": relevant}})
    assert gate["passed"] is False
    assert gate["reason"] == "empty result-relevant set"


def test_auditor_builds_r_without_app_import():
    sell = _swap(
        signature="aud-sell",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    old = _swap(
        signature="aud-old-unrelated",
        mint=OTHER,
        token_ata=OTHER_ATA,
        token_pre="5000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="50000000",
        block_time=OLD_2024,
    )
    trades = [{
        "kind": "sell",
        "signature": "aud-sell",
        "mint": MINT,
        "timestamp": IN_WINDOW,
        "quantity_raw": "1000000",
        "consideration_usdc": "100",
        "settlement_asset": "USDC",
        "observed_pre_quantity_raw": "1000000",
        "observed_post_quantity_raw": "0",
    }]
    episodes = [{"mint": MINT, "close_signature": "aud-sell"}]
    relevant = auditor.result_relevant_coverage(
        WALLET, [sell, old], trades, episodes,
        report_start=START_UNIX, report_end=END_UNIX,
    )
    assert auditor.result_relevant_coverage.__module__ == "tools.independent_episode_audit"
    assert "aud-old-unrelated" not in relevant["signatures"]
    assert "aud-sell" in relevant["signatures"]
    assert relevant["version"] == COVERAGE_GATE_VERSION


def test_lineage_ignores_quote_mints():
    events = [
        _decoded_sell("usdc-sell", mint=USDC),
        _decoded_sell("wsol-sell", mint=WSOL),
        _decoded_sell("token-sell", mint=MINT),
    ]
    lineage = lineage_mints(
        decoded_events=events,
        ledger=[{"mint": USDC}, {"mint": MINT}],
        report_start=REPORT_START,
        report_end=REPORT_END,
    )
    assert MINT in lineage
    assert USDC not in lineage
    assert WSOL not in lineage


def test_whole_span_partition_still_counts_old_unrelated():
    clean = _swap(
        signature="in-window-clean",
        mint=MINT,
        token_ata=TOKEN_ATA,
        token_pre="1000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="100000000",
        block_time=IN_WINDOW,
    )
    old = _swap(
        signature="old-unrelated",
        mint=OTHER,
        token_ata=OTHER_ATA,
        token_pre="5000000",
        token_post="0",
        usdc_pre="0",
        usdc_post="50000000",
        block_time=OLD_2024,
    )
    decoded = {"events": [_decoded_sell("in-window-clean")]}
    breakdown = partition_records(
        [clean, old], decoded, WALLET,
        window_start="2024-01-01T00:00:00Z",
        window_end=REPORT_END,
    )
    assert breakdown["in_window_swaps"] == 2
    relevant = _relevant([clean, old], decoded["events"], ledger=[{"mint": MINT}])
    assert relevant["denominator"] == 1
