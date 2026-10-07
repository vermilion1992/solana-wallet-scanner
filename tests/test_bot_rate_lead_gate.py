"""A wallet with >25 economic trades in any UTC day is never a lead.

Counts buy/sell on (signature, kind, mint) over full captured history.
Independent of the report window. Phase-2 triage samples are not enough.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_NEXT,
    _verify_saved_page,
    page_sort_key,
    phase4_offline,
    window_bounds,
)
from scanner.mass_search.qualification_gates import (
    GT25_ECONOMIC_TRADES_RULE,
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
    attach_economic_trade_rate,
    economic_trades_by_utc_day,
)
from scanner.mass_search.research_profile import qualification_level
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JXT_PAGES = ROOT / "tests/fixtures/live-raw/f635a45" / JXT
LEADS = {"provisional_research_lead", "stronger_research_shortlist"}


def _require_jxt_pages():
    if not JXT_PAGES.is_dir() or not list(JXT_PAGES.glob("page*.bin")):
        raise AssertionError(f"committed jXt fixture pages missing: {JXT_PAGES}")
    return JXT_PAGES


@pytest.mark.parametrize("rwd", [30, 90])
def test_wallet_over_25_economic_trades_per_utc_day_is_never_a_lead(tmp_path, rwd):
    pages_dir = _require_jxt_pages()
    end = datetime(2026, 10, 4, 17, 22, 3, tzinfo=timezone.utc)
    bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=rwd)
    dest = tmp_path / "out/raw/phase3" / JXT
    shutil.copytree(pages_dir, dest)
    os.system(f"chmod -R u+w {dest}")
    pages = sorted(dest.glob("page*.bin"), key=page_sort_key)
    _raw, _data, tok = _verify_saved_page(pages[-1])
    state = {
        "bounds": bounds,
        "phase3": {
            JXT: {
                "pages": len(pages),
                "done": True,
                "pagination_token": tok,
                "leftover_pagination_token": bool(tok),
            }
        },
    }
    store = Store(tmp_path / "led")
    res = phase4_offline(
        store,
        {
            "bounds": bounds,
            "output_dir": str(tmp_path / "out"),
            "wallets": [JXT],
            "phases": (4,),
            "authorization_id": AUTHORIZATION_ID_NEXT,
        },
        state,
    )
    store.close()
    row = res["wallets"][0]
    assert row["lead_level"] not in LEADS, (row["lead_level"], row["blocker"])
    assert row["lead_level"] == "insufficient_evidence"
    assert row["blocker"] and GT25_ECONOMIC_TRADES_RULE in row["blocker"]
    assert "25" in row["blocker"]
    assert "2026-10-01" in row["blocker"]
    assert int(row["max_economic_trades_in_one_day"]) == 102
    assert row["max_economic_trades_on"] == "2026-10-01"
    assert int(row["max_trades_per_day"]) == 102
    assert row["max_trades_per_day_on"] == "2026-10-01"


def test_economic_trades_dedupe_signature_kind_mint():
    events = [
        {"kind": "fee", "signature": "s1", "mint": "M", "timestamp": 1_775_000_000},
        {"kind": "buy", "signature": "s1", "mint": "M", "timestamp": 1_775_000_000},
        {"kind": "buy", "signature": "s1", "mint": "M", "timestamp": 1_775_000_000},
        {"kind": "sell", "signature": "s1", "mint": "M", "timestamp": 1_775_000_000},
        {"kind": "sell", "signature": "s2", "mint": "N", "timestamp": 1_775_000_001},
    ]
    by_day = economic_trades_by_utc_day(events)
    assert sum(by_day.values()) == 3


def test_gt25_mutation_without_cap_jxt_would_be_a_lead(tmp_path):
    """Mutation: raising the cap must restore the previous stronger shortlist."""
    import scanner.mass_search.qualification_gates as gates

    pages_dir = _require_jxt_pages()
    end = datetime(2026, 10, 4, 17, 22, 3, tzinfo=timezone.utc)
    bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    dest = tmp_path / "out/raw/phase3" / JXT
    shutil.copytree(pages_dir, dest)
    os.system(f"chmod -R u+w {dest}")
    pages = sorted(dest.glob("page*.bin"), key=page_sort_key)
    _raw, _data, tok = _verify_saved_page(pages[-1])
    state = {
        "bounds": bounds,
        "phase3": {
            JXT: {
                "pages": len(pages),
                "done": True,
                "pagination_token": tok,
                "leftover_pagination_token": bool(tok),
            }
        },
    }
    store = Store(tmp_path / "led")
    phase4_offline(
        store,
        {
            "bounds": bounds,
            "output_dir": str(tmp_path / "out"),
            "wallets": [JXT],
            "phases": (4,),
            "authorization_id": AUTHORIZATION_ID_NEXT,
        },
        state,
    )
    report = [row for row in store.list("reports") if row.get("address") == JXT][-1]
    profile = report["research_profile"]
    store.close()
    gated = qualification_level(report, profile)
    assert gated["level"] not in LEADS
    assert GT25_ECONOMIC_TRADES_RULE in (gated.get("reason") or "")
    original = gates.MAX_ECONOMIC_TRADES_PER_UTC_DAY
    try:
        gates.MAX_ECONOMIC_TRADES_PER_UTC_DAY = 10**9
        mutated = qualification_level(report, profile)
        assert mutated["level"] in LEADS, mutated
    finally:
        gates.MAX_ECONOMIC_TRADES_PER_UTC_DAY = original


def test_gt25_is_independent_of_report_window():
    """A burst outside a 30d window still blocks a lead."""
    burst = 1_767_225_600  # 2026-01-01
    events = [
        {
            "kind": "buy" if index % 2 == 0 else "sell",
            "signature": f"s{index}",
            "mint": f"M{index % 3}",
            "timestamp": burst + index,
        }
        for index in range(26)
    ]
    report = {"captured_history_events": events, "events": []}
    profile = {
        "completed_known_cost_positions": 20,
        "completed_episode_ledger": [
            {"mint": f"T{i}", "close_signature": f"c{i}", "net": "1", "unit": "SOL"}
            for i in range(20)
        ],
        "unresolved_basis_sales": 0,
        "concentration_detail": {"distinct_tokens": 4},
        "trading_activity": {"active_trading_days": 10, "span_days": 20},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
    }
    attach_economic_trade_rate(profile, events)
    attach_economic_trade_rate(report, events)
    judged = qualification_level(report, profile)
    assert judged["level"] == "insufficient_evidence"
    assert judged["lead_eligible"] is False
    assert judged["max_economic_trades_in_one_day"] == 26
    assert judged["max_economic_trades_on"] == "2026-01-01"
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 25
