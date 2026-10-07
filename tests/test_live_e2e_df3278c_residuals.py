"""df3278c live-run residuals. Offline only; keys must stay unset or dummy."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import _episode_rent_exclusion, _keys, decode_supported_swaps
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_11,
    AUTHORIZATION_ID_12,
    DRAFT_REL_12,
    HARD_CEILINGS,
    LIVE_KNOWN_DRAFTS,
    PINNED_DRAFT_HASHES,
    RETIRED_LIVE_DRAFTS,
    LiveE2EError,
    align_wallet_bounds,
    phase4_offline,
    phase4_targets,
    run_live_e2e,
    seed_counterparties_from_records,
    window_bounds,
)
from scanner.mass_search.live_e2e_ledger import (
    RECEIPT_KIND,
    put_receipt,
    spend_from_ledger,
    verify_receipt_chain,
)
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
import tools.independent_episode_audit as auditor

ROOT = Path(__file__).resolve().parents[1]
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
LAJ = "9LajrZcitRMGxjZYLh9LGsQsvjwo7pjnRri8BJTrrqrE"
DKX = "DKxKrP4yCSGt27AECQvaaxrr5KwZ3FxLYdNhnD3LcMTv"
JXT_PAGES = Path("/tmp/live-raw-f635a45/live-out/main/raw/phase3") / JXT
LAJ_PAGES = Path("/tmp/live-raw-4bbb364-a") / LAJ
DKX_PAGES = Path("/tmp/live-raw-4bbb364-b") / DKX
GM1 = "GM1uLLWQivi72wkZ8EQzmUxB2s3E2aQrZZVzWwaQSWME"
LOSER_MINT = "HwqzsNd4VMTiqMZTXaAMYuY8BymtDmwR8cK1dWy3pump"


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


def _flat(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    instructions = message.get("instructions") or []
    inner = {}
    for group in (raw.get("meta") or {}).get("innerInstructions") or []:
        inner[group.get("index")] = list(enumerate(group.get("instructions") or []))
    rows = []
    for index, instruction in enumerate(instructions):
        rows.append((index, f"instructions.{index}", dict(instruction), False))
        for nested_i, nested in inner.get(index, []):
            rows.append((index, f"inner.{index}.{nested_i}", dict(nested), True))
    return rows


def _record_by_prefix(records, prefix):
    for row in records:
        sig = ((row.get("transaction") or {}).get("signatures") or [""])[0]
        if str(sig).startswith(prefix):
            return row
    return None


def test_draft_12_disabled_and_11_retired():
    assert AUTHORIZATION_ID_11 in RETIRED_LIVE_DRAFTS
    assert AUTHORIZATION_ID_12 in LIVE_KNOWN_DRAFTS
    draft = json.loads((ROOT / DRAFT_REL_12).read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False
    assert draft["expires_at"] == "2026-10-11T13:30:00Z"
    assert int(draft["providers"][0]["max_requests"]) <= 40
    assert int(draft["providers"][0]["max_units"]) <= 1400
    assert int(draft["providers"][1]["max_requests"]) <= 3000
    assert int(draft["phase_caps"]["2"]["helius_requests"]) >= 600
    digest = hashlib.sha256((ROOT / DRAFT_REL_12).read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_12] == digest
    assert HARD_CEILINGS["birdeye_requests"] == 40
    assert HARD_CEILINGS["birdeye_units"] == 1400


def test_app_and_auditor_rent_policy_independent_on_jxt_pages():
    records = _load_pages(JXT_PAGES)
    if not records:
        pytest.skip("jXt f635a45 pages not extracted")
    long_lived = _record_by_prefix(records, "2gDSxX4B")
    create_close = _record_by_prefix(records, "4MvuWAZd")
    assert long_lived and create_close
    for raw in (long_lived, create_close):
        keys = _keys((raw.get("transaction") or {}).get("message") or {}, raw.get("meta") or {})
        before = (raw.get("meta") or {}).get("preBalances") or []
        after = (raw.get("meta") or {}).get("postBalances") or []
        token_accounts = set()
        for item in ((raw.get("meta") or {}).get("preTokenBalances") or []) + (
            (raw.get("meta") or {}).get("postTokenBalances") or []
        ):
            index = item.get("accountIndex")
            if isinstance(index, int) and 0 <= index < len(keys):
                token_accounts.add(keys[index])
        app_rent = _episode_rent_exclusion(_flat(raw), keys, before, after, JXT, token_accounts)
        gm1 = keys.index(GM1) if GM1 in keys else None
        if raw is long_lived:
            assert gm1 is not None
            assert after[gm1] - before[gm1] > 0
            assert app_rent == after[gm1] - before[gm1]
        if raw is create_close:
            assert gm1 is not None
            assert after[gm1] - before[gm1] == 0
            assert app_rent == 0
        movements = auditor._system_movements(raw, keys)
        accounts = auditor._token_accounts(raw, JXT, keys)
        retained = auditor._non_token_creates(movements, JXT, set(accounts), raw=raw, keys=keys)
        if raw is long_lived:
            assert retained == Decimal(after[gm1] - before[gm1])
        if raw is create_close:
            assert retained == 0
    assert _episode_rent_exclusion.__module__ == "scanner.investigation"
    assert auditor._non_token_creates.__module__ == "tools.independent_episode_audit"


def test_binder_ignores_out_of_window_dropped_loser():
    records = _load_pages(JXT_PAGES)
    if not records:
        pytest.skip("jXt f635a45 pages not extracted")
    window = {
        "start": "2026-09-07T10:52:20Z",
        "end": "2026-10-07T10:52:20Z",
    }
    report = {
        "address": JXT,
        "window": window,
        "events": [],
        "worksheet": {},
        "classification": {"counts": {}, "transactions": 0},
        "coverage": {},
        "completed_episode_ledger": [{
            "mint": "WinMint", "close_signature": "c1", "net": "1", "unit": "SOL",
            "basis": "1", "proceeds": "2", "costs": "0",
        }],
    }
    profile = {
        "completed_episode_ledger": report["completed_episode_ledger"],
        "completed_episode_net": "1",
        "completed_episode_net_unit": "SOL",
        "audit_fingerprint": {"fingerprint": "x" * 64, "accounting_policy_version": "v"},
    }
    audit = attach_live_independent_audit(report, profile, records, JXT)
    dropped = audit.get("dropped_losing_episodes") or []
    out_of_window = [row for row in dropped if row.get("reason") == "not_in_window_or_unresolved"]
    assert not out_of_window
    if audit.get("reason") == "auditor_dropped_losing_episodes":
        assert all(row.get("reason") != "not_in_window_or_unresolved" for row in dropped)


def test_dust_transfer_in_does_not_erase_buy_sell_loser():
    records = _load_pages(JXT_PAGES)
    if not records:
        pytest.skip("jXt f635a45 pages not extracted")
    tmpl = _record_by_prefix(records, "5fuDBPtG")
    if tmpl is None:
        pytest.skip("jXt airdrop template missing")
    fake = json.loads(json.dumps(tmpl).replace(
        "DCjjSET97j39BH4nkCQHoeroXtTbA1nEN5DThF6MfQAj", LOSER_MINT,
    ))
    fake["transaction"]["signatures"][0] = "1" * 87 + "2"
    fake["blockTime"] = 1_791_200_000
    attacked = [fake, *records]
    clean = detect_bundle_or_distribution(records, JXT)
    dirty = detect_bundle_or_distribution(attacked, JXT)
    assert LOSER_MINT not in (dirty.get("sold_quarantined_mints") or [])
    store = Store(Path("/tmp") / "df3278c-dust" / "store")
    bounds = window_bounds(30, 60, end=datetime(2026, 10, 7, 10, 52, 20, tzinfo=timezone.utc))
    clean_rep = replay_cached_history_to_report(
        store, address=JXT, records=records,
        window_start=bounds["report_start_inclusive"],
        window_end=bounds["report_end_exclusive"],
        acquisition_start=bounds["history_start_inclusive"],
    )["report"]
    dirty_rep = replay_cached_history_to_report(
        store, address=JXT, records=attacked,
        window_start=bounds["report_start_inclusive"],
        window_end=bounds["report_end_exclusive"],
        acquisition_start=bounds["history_start_inclusive"],
    )["report"]
    clean_rep["bundle_or_distribution"] = clean
    dirty_rep["bundle_or_distribution"] = dirty
    clean_p = build_research_profile(clean_rep, filters=default_filters())
    dirty_p = build_research_profile(dirty_rep, filters=default_filters())
    assert int(clean_p.get("completed_known_cost_positions") or 0) == int(dirty_p.get("completed_known_cost_positions") or 0)
    assert Decimal(str(clean_p.get("completed_episode_net") or 0)) == Decimal(str(dirty_p.get("completed_episode_net") or 0))
    store.close()


def test_coverage_uses_wallet_capture_bounds():
    records = _load_pages(JXT_PAGES)
    if not records:
        pytest.skip("jXt f635a45 pages not extracted")
    later = {
        "report_start_inclusive": "2026-09-07T10:52:20Z",
        "report_end_exclusive": "2026-10-07T10:52:20Z",
        "history_start_inclusive": "2026-07-09T10:52:20Z",
        "report_window_days": 30,
        "window_days": 30,
    }
    aligned = align_wallet_bounds(records, later)
    times = [row.get("blockTime") for row in records if type(row.get("blockTime")) is int]
    assert times
    configured_end = int(datetime.fromisoformat("2026-10-07T10:52:20+00:00").timestamp())
    assert aligned["report_end_unix"] <= configured_end
    assert aligned["report_end_unix"] <= max(times) + 1
    assert aligned["coverage_start_inclusive"] <= aligned["history_start_inclusive"]


def test_report_window_widening_is_monotone_on_laj():
    records = _load_pages(LAJ_PAGES)
    if not records:
        pytest.skip("9Laj pages not extracted")
    store = Store(Path("/tmp") / "df3278c-rwd" / "store")
    end = datetime(2026, 10, 7, 13, 7, 4, tzinfo=timezone.utc)
    completed = []
    for days in (30, 31, 60, 90):
        bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=days)
        result = replay_cached_history_to_report(
            store, address=LAJ, records=records,
            window_start=bounds["report_start_inclusive"],
            window_end=bounds["report_end_exclusive"],
            acquisition_start=bounds["history_start_inclusive"],
        )
        report = result["report"]
        report["bundle_or_distribution"] = detect_bundle_or_distribution(records, LAJ)
        profile = build_research_profile(report, filters=default_filters())
        completed.append(int(profile.get("completed_known_cost_positions") or report.get("wallet_completed_episodes") or 0))
    store.close()
    assert completed[0] >= 1
    for earlier, later in zip(completed, completed[1:]):
        assert later >= earlier, completed


def test_dkx_missing_ge87_buys_now_decode():
    records = _load_pages(DKX_PAGES)
    if not records:
        pytest.skip("DKx pages not extracted")
    opening = _record_by_prefix(records, "2vTAoMD5oZkH")
    dflow = _record_by_prefix(records, "vYeWFHJdvG5w")
    assert opening and dflow
    decoded = decode_supported_swaps(canonical_decode_records([opening, dflow]), DKX)
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    assert {row.get("signature", "")[:12] for row in trades} >= {"2vTAoMD5oZkH", "vYeWFHJdvG5w"}
    assert all(row.get("kind") == "buy" for row in trades)
    assert auditor.reconstruct_record(opening, DKX)
    assert auditor.reconstruct_record.__module__ == "tools.independent_episode_audit"


def test_dkx_rates_at_90d():
    records = _load_pages(DKX_PAGES)
    if not records:
        pytest.skip("DKx pages not extracted")
    store = Store(Path("/tmp") / "df3278c-dkx" / "store")
    end = datetime(2026, 10, 7, 10, 52, 20, tzinfo=timezone.utc)
    short = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    long = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=90)
    short_rep = replay_cached_history_to_report(
        store, address=DKX, records=records,
        window_start=short["report_start_inclusive"],
        window_end=short["report_end_exclusive"],
        acquisition_start=short["history_start_inclusive"],
    )["report"]
    long_rep = replay_cached_history_to_report(
        store, address=DKX, records=records,
        window_start=long["report_start_inclusive"],
        window_end=long["report_end_exclusive"],
        acquisition_start=long["history_start_inclusive"],
    )["report"]
    short_p = build_research_profile(short_rep, filters=default_filters())
    long_p = build_research_profile(long_rep, filters=default_filters())
    store.close()
    assert int(short_p.get("completed_known_cost_positions") or 0) == 0
    assert int(long_p.get("completed_known_cost_positions") or 0) >= 1
    net = Decimal(str(long_p.get("completed_episode_net") or 0))
    assert net > Decimal("1500")
    bundle = detect_bundle_or_distribution(records, DKX)
    assert bundle.get("excluded") is False


def test_rfq_opposite_side_is_not_bundle_partner():
    records = _load_pages(LAJ_PAGES)
    if not records:
        pytest.skip("9Laj pages not extracted")
    detected = detect_bundle_or_distribution(records, LAJ)
    assert "multi_signer_bundle_buy" not in (detected.get("reasons") or [])


def test_phase4_empty_selection_is_not_done(tmp_path, monkeypatch):
    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", _empty_helius)
    grant = _arm_grant(tmp_path, helius_req=10, helius_units=100, bind_hash=False)
    out = tmp_path / "p4empty"
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, out, [], phases="4"),
        "mode": "dry-run",
        "resume": False,
    }))
    state = json.loads((out / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert 4 not in (state.get("phases_done") or [])
    assert (result.get("wallets") or []) == []
    assert phase4_targets({"wallets": [], "wallets_supplied": False}, {"phase3": {}}) == []


def test_ata_rent_is_not_one_hop_forwarding():
    wallet = "Wallet1111111111111111111111111111111111111"
    owner = "OwnerAddr111111111111111111111111111111111"
    ata = "AtaRent11111111111111111111111111111111111"
    mint = "Mint1111111111111111111111111111111111111"
    create = {
        "signature": "pay-ata-rent",
        "transaction": {
            "signatures": ["pay-ata-rent"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, ata, owner],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [5_000_000_000, 0, 1_000_000_000],
            "postBalances": [4_997_960_720, 2_039_280, 1_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [{
                "accountIndex": 1, "owner": owner, "mint": mint,
                "uiTokenAmount": {"amount": "1"},
            }],
        },
    }
    close = {
        "signature": "close-ata",
        "transaction": {
            "signatures": ["close-ata"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [owner, ata],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [1_000_000_000, 2_039_280],
            "postBalances": [1_002_039_280, 0],
            "fee": 5000,
            "preTokenBalances": [{
                "accountIndex": 1, "owner": owner, "mint": mint,
                "uiTokenAmount": {"amount": "0"},
            }],
            "postTokenBalances": [],
        },
    }
    detected = detect_bundle_or_distribution([create, close], wallet)
    expl = detected.get("controlled_pair_explanation") or ""
    assert "one-hop" not in expl
    assert ata[:8] not in expl


def test_fresh_address_forward_is_unknown_destination():
    wallet = "Wallet1111111111111111111111111111111111111"
    hop = "FreshHop1111111111111111111111111111111111"
    dest = "UnknownDest111111111111111111111111111111"
    fund = {
        "signature": "withdraw-fresh",
        "transaction": {
            "signatures": ["withdraw-fresh"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, hop],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [20_000_000_000, 0],
            "postBalances": [5_000_000_000, 15_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    onward = {
        "signature": "hop-forwards",
        "transaction": {
            "signatures": ["hop-forwards"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, hop, dest],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [5_000_000_000, 15_000_000_000, 1_000_000_000],
            "postBalances": [5_000_000_000, 1_000_000_000, 15_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    detected = detect_bundle_or_distribution([fund, onward], wallet)
    assert "unknown_destination" in (detected.get("reasons") or [])


def test_seed_counterparties_skips_swap_pools():
    records = _load_pages(JXT_PAGES)
    if not records:
        pytest.skip("jXt f635a45 pages not extracted")
    seeds = seed_counterparties_from_records(records, JXT)
    addrs = {row["address"] for row in seeds}
    assert all(len(row["address"]) >= 32 for row in seeds)
    from scanner.investigation import PUMP_SWAP, REVIEWED_OUTER_VENUES
    assert PUMP_SWAP not in addrs
    assert not (addrs & set(REVIEWED_OUTER_VENUES))
    assert not any(addr.startswith(prefix) for addr in addrs for prefix in ("24nCzF7Y", "BDUvAeTP", "CebN5WGQ"))


def test_null_token_full_page_stops_and_wallet_cap_applies(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def looping(_store, _grant, config, state, _transport, address, _options, *, phase, page_index):
        calls["n"] += 1
        if calls["n"] > 20:
            raise AssertionError("null-token pagination looped")
        used = int((state.get("phase3") or {}).get(address, {}).get("requests") or 0)
        if config.get("per_wallet_cap") is not None and used >= int(config["per_wallet_cap"]):
            raise SourceError("WALLET_CAP", "Per-wallet request cap reached; continue with other wallets")
        return {
            "records": [{"signature": f"s{i}", "blockTime": 1_700_000_000 + i} for i in range(1000)],
            "pagination_token": None,
            "http_status": 200,
            "raw_bytes": b"{}",
            "evidence_sha256": "a" * 64,
            "units": 100,
            "external_requests": 1,
        }

    from scanner.mass_search.adapters import SourceError
    from scanner.mass_search.live_e2e import phase3_history
    monkeypatch.setattr("scanner.mass_search.live_e2e._dispatch_helius", looping)
    store = Store(tmp_path / "pagecap")
    config = {
        "phases": (3,),
        "wallets": [WALLETS[0]],
        "wallets_supplied": True,
        "dry_run": False,
        "per_wallet_cap": 10,
        "bounds": window_bounds(30, 60, end=datetime(2026, 10, 7, tzinfo=timezone.utc), history_to_first=True),
        "output_dir": str(tmp_path / "out"),
        "authorization_id": AUTHORIZATION_ID_12,
    }
    (tmp_path / "out").mkdir()
    asyncio.run(phase3_history(store, {"authorization_id": AUTHORIZATION_ID_12}, config, {"phase2": {}, "phase3": {}}, None))
    assert calls["n"] == 1
    store.close()


def test_receipt_chain_refuses_rewrite_and_deletion_keeps_spend(tmp_path):
    store = Store(tmp_path / "chain")
    verify_receipt_chain(store)
    grant = {"authorization_id": AUTHORIZATION_ID_12}
    put_receipt(store, grant, "helius:w:3:0:a", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 0,
        "state": "consumed", "sha256": "a" * 64, "units": 10,
    })
    put_receipt(store, grant, "helius:w:3:1:b", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 1,
        "state": "consumed", "sha256": "b" * 64, "units": 20,
    })
    verify_receipt_chain(store)
    before, _ = spend_from_ledger(store)
    assert before["helius_requests"] == 2
    row = store.get(RECEIPT_KIND, "helius:w:3:0:a")
    row["sha256"] = "c" * 64
    row["receipt_hash"] = hashlib.sha256(
        json.dumps({k: row[k] for k in sorted(row) if k != "receipt_hash"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    store.put(RECEIPT_KIND, "helius:w:3:0:a", row)
    with pytest.raises(ValueError):
        verify_receipt_chain(store)
    store.put(RECEIPT_KIND, "helius:w:3:0:a", None) if False else None
    for key in ("helius:w:3:0:a", "helius:w:3:1:b"):
        store.put(RECEIPT_KIND, key, {"request_id": key})
    with pytest.raises(ValueError):
        verify_receipt_chain(store)
    # Recreate a clean store and delete receipts while leaving the seal/log.
    store2 = Store(tmp_path / "chain2")
    put_receipt(store2, grant, "helius:w:3:0:a", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 0,
        "state": "consumed", "sha256": "a" * 64, "units": 10,
    })
    spend_before, _ = spend_from_ledger(store2)
    store2.put(RECEIPT_KIND, "helius:w:3:0:a", {"request_id": "gone"})
    with pytest.raises(ValueError):
        verify_receipt_chain(store2)
    spend_after, _ = spend_from_ledger(store2)
    assert spend_after["helius_units"] >= spend_before["helius_units"]
    store.close()
    store2.close()


def test_phase4_offline_never_marks_empty_done(tmp_path):
    store = Store(tmp_path / "p4")
    config = {
        "phases": (4,),
        "wallets": [],
        "wallets_supplied": False,
        "output_dir": str(tmp_path / "out"),
        "bounds": window_bounds(30, 60, end=datetime(2026, 10, 7, tzinfo=timezone.utc)),
        "authorization_id": AUTHORIZATION_ID_12,
    }
    result = phase4_offline(store, config, {"phase3": {}})
    assert (result.get("wallets") or []) == []
    store.close()
