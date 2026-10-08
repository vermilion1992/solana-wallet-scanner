"""CYrCnVS3 real-data fixture + D11-3/5/6/7/8. Offline; no live calls."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import DECODER_VERSION, WELL_KNOWN_INNER_AMMS, decode_supported_swaps
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_15,
    DRAFT_REL_15,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    remaining_caps,
    window_bounds,
)
from scanner.mass_search.qualification_gates import (
    BOT_THRESHOLD_RULE,
    HISTORY_AGE_RULE,
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
    is_economic_bot,
)
from scanner.mass_search.research_profile import (
    attach_live_independent_audit,
    build_research_profile,
    default_filters,
)
from scanner.storage import Store
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
CYRC = "CYrCnVS3QHNM6ohVMW17dxumzsVbYC9rXD1UaLrZGMBe"
CYRC_PAGES = ROOT / "tests/fixtures/live-raw/cyrcnvs3" / CYRC
HUMIDIFI = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"
JE3 = "JE3HT7SbCgXDQWV6xp3oiiAisDzq4HyZ8wyEVBDCs45Z"
PERPS = "PerPsCe2SJ7Q25CN4R5TTX4fmBdmknE2hQmqCt96fHL"
DFLOW_SELL = "5yk6KkgWYkYBfjLg"
JUP_SELL = "2HW2fQdwP6UqSc2ubBCk"
JE3_CLOSE = "5fJCqYXWYWCfTT74"
TRANSFER_IN_SOURCE = "EPsjwThfdCya8LsRqNJ4zCJV9zaoRehz2dRVwFXNUtrk"


def _records():
    pages = sorted(CYRC_PAGES.glob("page*.bin"))
    if not pages:
        raise AssertionError(f"CYrCnVS3 fixture pages missing: {CYRC_PAGES}")
    records = []
    for path in pages:
        payload = json.loads(path.read_bytes())
        records.extend((payload.get("result") or {}).get("data") or [])
    if not records:
        raise AssertionError("CYrCnVS3 fixture is empty")
    return records


def _replay(tmp_path, records):
    decoded = decode_supported_swaps(canonical_decode_records(records), CYRC)
    store = Store(tmp_path / "cyrc.sqlite")
    end = datetime(2026, 10, 8, tzinfo=timezone.utc)
    bounds = window_bounds(90, 60, end=end, history_to_first=True, report_window_days=90)
    result = replay_cached_history_to_report(
        store,
        address=CYRC,
        records=records,
        window_start=bounds["report_start_inclusive"],
        window_end=bounds["report_end_exclusive"],
        acquisition_start=bounds["history_start_inclusive"],
    )
    report = result["report"]
    profile = build_research_profile(
        report, filters=default_filters(), decoded=decoded, records=records, address=CYRC,
    )
    audit = attach_live_independent_audit(report, profile, records, CYRC)
    store.close()
    return decoded, report, profile, audit


def test_humidifi_published_id_is_reviewed():
    assert HUMIDIFI in WELL_KNOWN_INNER_AMMS
    assert HUMIDIFI in auditor.WELL_KNOWN_INNER_AMMS
    assert DECODER_VERSION == "spot-v29-jup6-exact-out-v2-v1"


def test_cyrc_dflow_decodes_and_jup_allocate_2440_stays_blocked(tmp_path):
    records = _records()
    decoded, report, profile, audit = _replay(tmp_path, records)
    events = decoded.get("events") or []
    dflow = [e for e in events if (e.get("signature") or "").startswith(DFLOW_SELL) and e.get("kind") == "sell"]
    assert dflow, "DFlow 2026-09-13 sell must decode after the HumidiFi pin"
    assert Decimal(str(dflow[0].get("amount_usdc") or dflow[0].get("consideration_usdc"))) == Decimal("5642.749444")
    unresolved = decoded.get("unresolved") or []
    jup = [row for row in unresolved if (row.get("signature") or "").startswith(JUP_SELL)]
    assert jup, "JUP 2026-09-13 sell must stay fail-closed"
    assert "2440" in (jup[0].get("reason") or "")
    assert "reviewed account layout" in (jup[0].get("reason") or "")


def test_cyrc_app_keeps_je3_flatten_auditor_drops_cdhzy_in_window(tmp_path):
    records = _records()
    _decoded, _report, profile, audit = _replay(tmp_path, records)
    ledger = profile.get("completed_episode_ledger") or []
    je3 = [row for row in ledger if str(row.get("mint") or "").startswith("JE3")]
    assert je3, "app omitted the completed JE3 flatten; that was the 4-vs-5 bug"
    assert any((row.get("close_signature") or "").startswith(JE3_CLOSE) for row in je3)
    app_net = Decimal(str(profile.get("completed_episode_net")))
    aud_net = Decimal(str(audit.get("independently_audited_episode_net")))
    assert abs(app_net - aud_net) <= Decimal("0.000002")
    drops = audit.get("dropped_losing_episodes") or []
    assert drops, "auditor must still drop the in-window CdhZy loser"
    cdh = [row for row in drops if str(row.get("mint") or "").startswith("CdhZy8wr")]
    assert cdh
    assert cdh[0]["reason"] == "unflattened_losing_inventory"
    assert 1790612980 == int(cdh[0]["timestamp"])
    loss = Decimal(str(cdh[0]["net_profit"]))
    assert loss < 0
    # Both headlines used to exclude −46.66 USDC and overstate P&L. Include it.
    expected = Decimal("1839.123183") + loss
    assert abs(app_net - expected) <= Decimal("0.01"), (app_net, expected, loss)
    assert abs(aud_net - expected) <= Decimal("0.01"), (aud_net, expected, loss)
    assert audit.get("included_dropped_losing_pnl")
    assert audit.get("status") == "not_independently_audited"
    assert audit.get("reason") == "auditor_dropped_losing_episodes"
    assert audit.get("episodes"), "D11-7: dropped-loser audits still persist episode details"


def test_cyrc_unresolved_perps_stay_transfer_in(tmp_path):
    records = _records()
    _decoded, _report, profile, _audit = _replay(tmp_path, records)
    assert int(profile.get("unresolved_basis_sales") or 0) >= 8
    detail = profile.get("unresolved_basis_sales_detail") or []
    perps = [row for row in detail if str(row.get("mint") or "").startswith("PerPs")]
    assert perps
    for row in perps:
        assert row["reason"] == "transfer_in_zero_basis", row
    sources = {row.get("transfer_in_source") for row in perps if row.get("transfer_in_source")}
    assert not sources or TRANSFER_IN_SOURCE in sources or any(
        str(src).startswith("EPsjwThf") for src in sources
    )


def test_cyrc_is_human_under_gt15(tmp_path):
    records = _records()
    _decoded, report, profile, _audit = _replay(tmp_path, records)
    maximum = int(profile.get("max_economic_trades_in_one_day") or 0)
    assert maximum == 9
    assert is_economic_bot(maximum) is False
    assert BOT_THRESHOLD_RULE == "economic_trades_per_utc_day"
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 15


def test_auth15_draft_hash_and_ceilings():
    path = ROOT / DRAFT_REL_15
    draft = json.loads(path.read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["authorization_id"] == AUTHORIZATION_ID_15
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_15] == digest
    assert digest == "f8167778625e87c9c8af5014b1760606013d10ce5c18c606fbbed5afbf49e4b6"
    nansen = next(row for row in draft["providers"] if row["provider_id"] == "nansen")
    helius = next(row for row in draft["providers"] if row["provider_id"] == "helius")
    birdeye = next(row for row in draft["providers"] if row["provider_id"] == "birdeye")
    assert nansen["max_requests"] == 200
    assert nansen["max_units"] == 400
    assert "profiler_dex_trades" in nansen["allowed_operations"]
    assert "tgm_pnl_leaderboard" in nansen["allowed_operations"]
    assert helius["max_units"] == 40000
    assert "getSignaturesForAddress" in helius["allowed_operations"]
    assert birdeye["max_requests"] == 0
    assert birdeye["max_units"] == 0
    assert HARD_CEILINGS["nansen_requests"] == 300
    assert HARD_CEILINGS["nansen_units"] == 600
    assert HARD_CEILINGS["helius_units"] == 80000
    assert HARD_CEILINGS["birdeye_units"] == 1400


def test_d11_3_remaining_caps_are_min_of_lifetime_and_run():
    config = {
        "caps": {
            "birdeye_requests": 40, "birdeye_units": 1400,
            "helius_requests": 4000, "helius_units": 40000,
            "nansen_requests": 200, "nansen_units": 400,
        },
        "run_caps": {
            "birdeye_requests": 10, "birdeye_units": 200,
            "helius_requests": 100, "helius_units": 1000,
            "nansen_requests": 20, "nansen_units": 40,
        },
    }
    lifetime_spend = {
        "birdeye_requests": 5, "birdeye_units": 100,
        "helius_requests": 10, "helius_units": 100,
        "nansen_requests": 190, "nansen_units": 380,
    }
    run_spend = {
        "birdeye_requests": 0, "birdeye_units": 0,
        "helius_requests": 0, "helius_units": 0,
        "nansen_requests": 5, "nansen_units": 10,
    }
    left = remaining_caps(config, lifetime_spend, run_spend=run_spend)
    assert left["nansen_requests"] == min(200 - 190, 20 - 5) == 10
    assert left["nansen_units"] == min(400 - 380, 40 - 10) == 20
    assert left["helius_units"] == min(40000 - 100, 1000 - 0) == 1000


def test_d11_6_named_config_defaults():
    assert BOT_THRESHOLD_RULE == "economic_trades_per_utc_day"
    assert HISTORY_AGE_RULE == "off"
    assert is_economic_bot(15) is False
    assert is_economic_bot(16) is True
    assert is_economic_bot(None) is False
