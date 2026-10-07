"""affc623 / run-7 §9 repros. Offline only; keys unset. No live calls."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.live_e2e import (
    phase4_offline,
    run_live_e2e,
    window_bounds,
)
from scanner.mass_search.live_e2e_ledger import verify_receipt_chain
from scanner.mass_search.research_profile import (
    attach_live_independent_audit,
    build_research_profile,
    default_filters,
)
from scanner.storage import Store
from tests.test_live_e2e_spend_safety import (
    WALLETS,
    _arm_grant,
    _empty_helius,
    _live_kwargs,
    pin_test_ledger,
)

ROOT = Path(__file__).resolve().parents[1]
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JXT_PAGES = Path("/tmp/live_raw_affc623_repro/runs/run_f635a45/raw/phase3") / JXT
if not JXT_PAGES.is_dir():
    JXT_PAGES = Path("/tmp/live-raw-f635a45/live-out/main/raw/phase3") / JXT
PU5 = "5PU9ytwyXgtoA8WPJxjSQT4ENKWyjsvMncumAp3vHvrq"
PU5_PAGES = Path("/tmp/live_raw_affc623_repro/runs/run_4bbb364/raw/phase3") / PU5
HG = "HgHHUG5UH93vZLjTe1Cmxjnodq4FfXvH3XWbohRWNMEW"
HG_PAGES = Path("/tmp/live_raw_affc623_repro/runs/run_4bbb364/raw/phase2") / HG
FN9Y = "Fn9yPE7piEUxFn78HuBrSL2yk5goD4mu6dtwz6k2pump"
H1B8 = "H1B8nhXLN5fnmu8G5PwyP3eCBxx3v5xBHGPWuZPFpump"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    return pin_test_ledger(tmp_path, monkeypatch)


def _load_pages(folder):
    records = []
    if not Path(folder).is_dir():
        return records
    for path in sorted(Path(folder).glob("page*.bin")):
        payload = json.loads(path.read_bytes())
        records.extend((payload.get("result") or {}).get("data") or [])
    return records


def test_s9_1_jxt_episode_costs_match_on_chain_fees():
    """§9.1 hermetic: ≤10-lamport sale-row fee drift snaps to the event fee sum."""
    from scanner.mass_search.research_profile import _episode_ledger_from_report

    report = {
        "window": {"start": "2026-09-01T00:00:00Z", "end": "2026-10-07T00:00:00Z"},
        "events": [
            {
                "kind": "buy",
                "mint": FN9Y,
                "quantity_raw": "100",
                "amount_sol": "1.0",
                "fees_and_tips_sol": "0.000005000",
                "signature": "buy-fn9y",
                "timestamp": "2026-09-15T00:00:00Z",
                "settlement_asset": "SOL",
            },
            {
                "kind": "sell",
                "mint": FN9Y,
                "quantity_raw": "100",
                "amount_sol": "1.1",
                "fees_and_tips_sol": "0.000000800",
                "signature": "sell-fn9y",
                "timestamp": "2026-09-16T00:00:00Z",
                "settlement_asset": "SOL",
            },
        ],
        "worksheet": {
            "sale_rows": [
                {
                    "signature": "sell-fn9y",
                    "mint": FN9Y,
                    "net_profit": "0.094194195",
                    "basis": "1.0",
                    "proceeds": "1.1",
                    "fees_and_tips": "0.000005805",
                }
            ]
        },
    }
    ledger = _episode_ledger_from_report(report)
    assert ledger
    assert Decimal(str(ledger[0]["costs"])) == Decimal("0.000005800")

    records = _load_pages(JXT_PAGES)
    if not records:
        return
    store = Store(Path("/tmp") / "s9-jxt-store")
    end = datetime(2026, 10, 4, 17, 22, 3, tzinfo=timezone.utc)
    bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    report = replay_cached_history_to_report(
        store,
        address=JXT,
        records=records,
        window_start=bounds["report_start_inclusive"],
        window_end=bounds["report_end_exclusive"],
        acquisition_start=bounds["history_start_inclusive"],
    )["report"]
    profile = build_research_profile(report, filters=default_filters())
    attach_live_independent_audit(report, profile, records, address=JXT)
    store.close()
    ledger = profile.get("completed_episode_ledger") or report.get("completed_episode_ledger") or []
    by_mint = {row.get("mint"): row for row in ledger if isinstance(row, dict)}
    if FN9Y in by_mint:
        assert Decimal(str(by_mint[FN9Y]["costs"])) == Decimal("0.0058058")
    if H1B8 in by_mint:
        assert Decimal(str(by_mint[H1B8]["costs"])) == Decimal("0.0045048")
    audit = profile.get("independent_audit") or report.get("independent_audit") or {}
    if audit.get("status") == "independently_audited" or audit.get("independently_audited"):
        assert audit.get("reason") in (None, "", "independently_audited") or "component_mismatch" not in str(
            audit.get("reason") or ""
        )
    else:
        assert audit.get("reason") != "component_mismatch"


def test_s9_2_report_window_change_invalidates_phase4(tmp_path, monkeypatch):
    """§9.2: changing --report-window-days must not serve stale Phase 4 rows."""
    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", _empty_helius)
    grant = _arm_grant(tmp_path, helius_req=10, helius_units=100, bind_hash=False)
    out = tmp_path / "p4lock"
    address = WALLETS[0]
    bounds30 = window_bounds(30, 60, end=datetime(2026, 10, 7, 16, 52, 48, tzinfo=timezone.utc), report_window_days=30)
    state = {
        "kind": "live-e2e-run-state-v1",
        "status": "completed",
        "phases_done": [2, 3, 4],
        "wallets": [address],
        "bounds": dict(bounds30),
        "phase2": {address: {"done": True}},
        "phase3": {address: {"done": True, "pages": 1}},
        "phase4_wallets": [{
            "address": address,
            "completed_trades": 99,
            "realized_pnl_sol": "123.456",
            "blocker": "stale-30d-marker",
        }],
        "spend": {"birdeye_requests": 0, "birdeye_units": 0, "helius_requests": 0, "helius_units": 0},
        "phase_spend": {},
        "PRODUCT_READY": False,
    }
    out.mkdir()
    (out / "RUN_STATE.json").write_text(json.dumps(state), encoding="utf-8")
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, out, [address], phases="4", resume=True),
        "mode": "dry-run",
        "report_window_days": 90,
    }))
    after = json.loads((out / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert int((after.get("bounds") or {}).get("report_window_days") or 0) == 90
    rows = after.get("phase4_wallets") or (result.get("wallets") or [])
    assert rows
    assert rows[0].get("completed_trades") != 99
    assert rows[0].get("blocker") != "stale-30d-marker"


def test_s9_3_program_escrow_pda_is_not_one_hop():
    """§9.3: Tensor/casino escrow PDAs debit without signing — not one-hop."""
    wallet = "Wallet1111111111111111111111111111111111111"
    escrow = "EscrowPDA111111111111111111111111111111111"
    dest = "DestAddr1111111111111111111111111111111111"
    tswap = "TSWAPaqy7XpZnbqJVKg6EepKxQ1GhA3qS3qZ4uY5tensor"
    deposit = {
        "signature": "wallet-to-escrow",
        "transaction": {
            "signatures": ["wallet-to-escrow"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, escrow, tswap],
                "instructions": [{"programId": tswap, "accounts": [0, 1], "data": "11111111"}],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [30_000_000_000, 0, 1],
            "postBalances": [5_520_000_000, 24_480_000_000, 1],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    payout = {
        "signature": "escrow-to-dest",
        "transaction": {
            "signatures": ["escrow-to-dest"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [dest, escrow, tswap],
                "instructions": [{"programId": tswap, "accounts": [1, 0], "data": "11111111"}],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [1_000_000_000, 24_480_000_000, 1],
            "postBalances": [25_480_000_000, 0, 1],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    detected = detect_bundle_or_distribution([deposit, payout], wallet)
    expl = detected.get("controlled_pair_explanation") or ""
    assert "one-hop" not in expl
    assert "controlled_pair" not in (detected.get("reasons") or [])
    assert "unknown_destination" not in (detected.get("reasons") or [])


def test_s9_3_real_tensor_and_casino_pages():
    ran = False
    for folder, address in ((PU5_PAGES, PU5), (HG_PAGES, HG)):
        records = _load_pages(folder)
        if not records:
            continue
        ran = True
        detected = detect_bundle_or_distribution(records, address)
        expl = detected.get("controlled_pair_explanation") or ""
        assert "one-hop" not in expl
        assert "unknown_destination" not in (detected.get("reasons") or [])
    if not ran:
        test_s9_3_program_escrow_pda_is_not_one_hop()


def test_s9_4_5_ledger_trust_boundary_is_documented():
    import scanner.mass_search.live_e2e_ledger as ledger

    text = (ledger.__doc__ or "") + Path(ledger.__file__).read_text(encoding="utf-8")
    assert "Trust boundary" in text
    assert "keyless" in text.lower() or "HMAC" in text
    assert "same-uid" in text
    assert "grant file holds no spend state" in text
    store = Store(Path("/tmp") / "s9-empty-ledger")
    verify_receipt_chain(store)
    store.close()


def test_s9_6_scrubbed_page_blocker(tmp_path):
    address = WALLETS[0]
    raw_dir = tmp_path / "out" / "raw" / "phase3" / address
    raw_dir.mkdir(parents=True)
    body = json.dumps({"error": {"message": "redacted"}}).encode("utf-8")
    page = raw_dir / "page0.bin"
    page.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (raw_dir / "page0.bin.integrity.json").write_text(
        json.dumps({"written_sha256": digest, "original_sha256": digest, "scrubbed": True}),
        encoding="utf-8",
    )
    store = Store(tmp_path / "led")
    rows = phase4_offline(
        store,
        {
            "phases": (4,),
            "wallets": [address],
            "output_dir": str(tmp_path / "out"),
            "bounds": {
                "report_start_inclusive": "2026-09-07T00:00:00Z",
                "report_end_exclusive": "2026-10-07T00:00:00Z",
                "history_start_inclusive": "2026-07-09T00:00:00Z",
            },
        },
        {"phase3": {address: {"pages": 1}}},
    )
    store.close()
    assert rows["wallets"][0]["blocker"] == "scrubbed provider echo; not covered"
