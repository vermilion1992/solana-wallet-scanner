"""Live-result defects A–E. Offline only. PRODUCT_READY stays false."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scanner.investigation import LIGHTHOUSE, TOKEN_2022_ID, decode_supported_swaps
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import (
    DRAFT_PATH,
    LiveE2EError,
    classify_programs,
    collect_program_ids,
    phase4_offline,
    run_live_e2e,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import (
    RECEIPT_KIND,
    committed_draft_hash,
    grant_ledger_path,
    spend_from_ledger,
)
from scanner.mass_search.research_profile import (
    _report_end_unix,
    apply_research_window,
    build_research_profile,
    default_filters,
)
from scanner.storage import Store
from tests.test_live_e2e_spend_safety import (
    FAKE_BIRDEYE,
    FAKE_HELIUS,
    WALLETS,
    _arm_grant,
    _empty_helius,
    _live_kwargs,
)


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(tmp_path / "ledger"))


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_HELIUS)
    monkeypatch.setenv("BIRDEYE_API_KEY", FAKE_BIRDEYE)
    monkeypatch.delenv("HELIUS_KEY", raising=False)

FIXTURE_DIR = Path("tests/fixtures/live-e2e-phase3")


def _load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_classifier_resolves_program_id_index_and_inners():
    keys = [
        "11111111111111111111111111111111",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9",
    ]
    records = [{
        "transaction": {
            "message": {
                "accountKeys": keys,
                "instructions": [{"programIdIndex": 1, "accounts": [], "data": ""}],
            }
        },
        "meta": {
            "loadedAddresses": {"writable": [], "readonly": []},
            "innerInstructions": [{
                "index": 0,
                "instructions": [{"programIdIndex": 3, "accounts": [], "data": ""}],
            }],
        },
    }]
    found = collect_program_ids(records)
    assert keys[1] in found
    assert keys[3] in found
    classified = classify_programs(records)
    labels = {row["label"] for row in classified["blockers"]}
    assert "FLASHX Axiom" in labels
    assert "Token-2022 observed-only" not in labels


def test_classifier_on_attached_okx_page():
    payload = _load_fixture("okx-swaptob.json")
    classified = classify_programs([payload["record"]])
    assert "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u" in classified["program_counts"]
    labels = {row["label"] for row in classified["blockers"]}
    assert "OKX SwapTob" not in labels


def test_phase4_uses_genuine_replay(tmp_path, monkeypatch, fake_keys):
    seen = {}

    def fake_replay(*args, **kwargs):
        seen.update(kwargs)
        return {
            "report": {
                "id": "r1",
                "address": kwargs["address"],
                "events": [],
                "coverage": {},
                "record_breakdown": {},
            }
        }

    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.replay_cached_history_to_report", fake_replay
    )
    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.decode_supported_swaps",
        lambda records, address: {"events": [], "coverage": {}},
    )
    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.build_research_profile",
        lambda report, filters=None, decoded=None: {
            "qualification_level": {"level": "insufficient_evidence"},
            "independent_audit": {},
            "completed_known_cost_positions": 0,
            "scoped_pnl_by_quote_asset": {},
            "PRODUCT_READY": False,
        },
    )
    address = WALLETS[0]
    raw_dir = tmp_path / "out" / "raw" / "phase3" / address
    raw_dir.mkdir(parents=True)
    (raw_dir / "page0.bin").write_bytes(b'{"result":{"data":[{"signature":"s"}]}}')
    store = Store(tmp_path / "store")
    config = {
        "phases": (4,),
        "wallets": [address],
        "output_dir": str(tmp_path / "out"),
        "bounds": {
            "report_start_inclusive": "2026-09-07T00:00:00Z",
            "report_end_exclusive": "2026-10-07T00:00:00Z",
            "history_start_inclusive": "2026-07-09T00:00:00Z",
        },
        "authorization_id": "live-e2e-proof-2026-10-07-mitch",
    }
    phase4_offline(store, config, {"phase3": {address: {"pages": 1}}})
    assert seen["corpus_kind"] == "GENUINE_REPLAY"
    store.close()


def test_in_window_ledger_and_zero_completed_hides_pnl():
    start = int(datetime(2026, 9, 7, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp())
    pre = start - 86400
    report = {
        "id": "win",
        "address": "W",
        "source": "mass-search",
        "window": {"start": "2026-09-07T00:00:00Z", "end": "2026-10-07T00:00:00Z"},
        "events": [],
        "completed_episode_ledger": [
            {"mint": "M", "net": "10", "unit": "SOL", "closed_at": pre},
        ],
        "wallet_completed_episodes": 1,
        "completed_episode_net": "10",
        "worksheet": {
            "settlement_asset": "SOL",
            "total_profit_sol": "10",
            "by_quote_asset": {"SOL": {"total_profit_sol": "10"}},
        },
    }
    profile = build_research_profile(report, filters=default_filters())
    assert profile["completed_known_cost_positions"] == 0
    assert profile["scoped_pnl"] is None
    assert profile["scoped_pnl_by_quote_asset"] == {}
    assert profile["scoped_pnl_unit"] is None


def test_fl2a_drops_stale_currency_and_fl2b_anchors_report_end():
    report_end = "2026-10-07T07:51:22Z"
    last_activity = "2026-09-26T00:10:23Z"
    last_ts = int(datetime(2026, 9, 26, 0, 10, 23, tzinfo=timezone.utc).timestamp())
    in_window_ts = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp())
    report = {
        "window": {"start": "2026-09-07T07:51:22Z", "end": report_end},
        "in_window_span": {"end": last_activity},
        "created_at": report_end,
        "events": [
            {"kind": "sell", "timestamp": last_ts, "mint": "M1"},
            {"kind": "sell", "timestamp": in_window_ts, "mint": "M2"},
        ],
        "completed_episode_ledger": [
            {"mint": "SOLMINT", "net": "-1.614", "unit": "SOL", "closed_at": last_ts},
            {"mint": "USDCMINT", "net": "347.34", "unit": "USDC", "closed_at": in_window_ts},
        ],
        "worksheet": {
            "settlement_asset": "mixed",
            "total_profit_sol": "-1.614",
            "total_profit_usdc": "347.34",
            "by_quote_asset": {
                "SOL": {"total_profit_sol": "-1.614"},
                "USDC": {"total_profit_usdc": "347.34"},
            },
        },
    }
    assert _report_end_unix(report) == int(datetime(2026, 10, 7, 7, 51, 22, tzinfo=timezone.utc).timestamp())
    clipped = apply_research_window(report, 7)
    assert {ep.get("unit") for ep in clipped["completed_episode_ledger"]} == {"USDC"}
    assert clipped["wallet_completed_episodes"] == 1
    assert "SOL" not in (clipped["worksheet"].get("by_quote_asset") or {})
    assert clipped["worksheet"].get("total_profit_sol") is None
    assert clipped["worksheet"]["by_quote_asset"]["USDC"]["total_profit_usdc"] == "347.34"

    dormant = apply_research_window({
        **report,
        "completed_episode_ledger": [
            {"mint": "M1", "net": "-0.0048", "unit": "SOL", "closed_at": last_ts},
        ],
        "events": [{"kind": "sell", "timestamp": last_ts, "mint": "M1"}],
    }, 7)
    assert dormant["wallet_completed_episodes"] == 0
    assert dormant["completed_episode_ledger"] == []


def test_missing_page_is_blocked_not_covered(tmp_path, monkeypatch, fake_keys):
    from scanner.mass_search.live_e2e import _replay_saved_page

    with pytest.raises(SourceError, match="not covered"):
        _replay_saved_page({"output_dir": str(tmp_path)}, 3, WALLETS[0], 0, 100)
    address = WALLETS[0]
    store = Store(tmp_path / "store")
    config = {
        "phases": (4,),
        "wallets": [address],
        "output_dir": str(tmp_path / "out"),
        "bounds": {
            "report_start_inclusive": "2026-09-07T00:00:00Z",
            "report_end_exclusive": "2026-10-07T00:00:00Z",
            "history_start_inclusive": "2026-07-09T00:00:00Z",
        },
    }
    rows = phase4_offline(store, config, {"phase3": {address: {"pages": 2}}})
    assert rows["wallets"][0]["blocker"] == "missing raw page; not covered"
    store.close()


def test_n1_second_ledger_dir_refused(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path)
    validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    with pytest.raises(LiveE2EError, match="second ledger dir"):
        validate_config({
            **_live_kwargs(tmp_path, grant, tmp_path / "out2", WALLETS[:1]),
            "ledger_dir": str(tmp_path / "other-ledger"),
        })
    path = grant_ledger_path("live-e2e-proof-2026-10-07-mitch")
    assert path == Path(tmp_path / "ledger" / "live-e2e-proof-2026-10-07-mitch")


def test_n2_missing_hash_and_working_tree_hash_refused(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path, bind_hash=False)
    with pytest.raises(LiveE2EError, match="draft_artifact_hash is required"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    grant = _arm_grant(tmp_path, extra={"draft_artifact_hash": "ab" * 32})
    with pytest.raises(LiveE2EError, match="not bound to the committed draft"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    committed = committed_draft_hash(
        "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json",
        repo_root=DRAFT_PATH.parents[1],
    )
    working = hashlib.sha256(DRAFT_PATH.read_bytes()).hexdigest()
    assert committed == working


def test_missing_phase_caps_inherit_draft(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path, phase_caps={})
    raw = json.loads(grant.read_text(encoding="utf-8"))
    raw.pop("phase_caps", None)
    grant.write_text(json.dumps(raw), encoding="utf-8")
    cfg = validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    assert cfg["caps"]["phase_caps"]["2"]["helius_requests"] == 200


def test_explicit_retry_appends_receipt(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise SourceError("UNSUPPORTED_SCHEMA", "boom")
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "retry"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    assert first["spend"]["helius_requests"] == 1
    second = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:1], phases="2", resume=True, explicit_retry=True,
    )))
    assert second["spend"]["helius_requests"] >= 3
    store = Store(tmp_path / "ledger" / second["authorization_id"])
    receipts = list(store.list(RECEIPT_KIND) or [])
    keys = [row.get("request_id") for row in receipts]
    assert any(":retry" in (key or "") for key in keys)
    ledger, _ = spend_from_ledger(store)
    assert ledger["helius_requests"] >= 3
    store.close()


def test_resume_window_days_mismatch_refused(tmp_path, monkeypatch, fake_keys):
    async def helius(*args, **kwargs):
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    out = tmp_path / "win"
    asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    with pytest.raises(LiveE2EError, match="window-days"):
        asyncio.run(run_live_e2e(_live_kwargs(
            tmp_path, grant, out, WALLETS[:1], phases="2", resume=True, window_days=7,
        )))


def test_okx_swaptob_reconciles_on_attached_tx():
    payload = _load_fixture("okx-swaptob.json")
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell")]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["instruction"] == "SwapTob"
    assert trade["quantity_raw"] == "100000000000"
    assert trade["amount_usdc"]
    assert trade["settlement_asset"] == "USDC"


def test_dflow_layout_is_pinned_but_stays_blocked_without_reconciliation():
    from scanner.investigation import DFLOW, DFLOW_SWAP, _accounts, _data, _keys, _program, _route

    payload = _load_fixture("dflow-swap.json")
    raw = payload["record"]
    message = raw["transaction"]["message"]
    keys = _keys(message, raw["meta"])
    instruction = next(ix for ix in message["instructions"] if _program(ix, keys) == DFLOW)
    assert _data(instruction.get("data"))[:8] == DFLOW_SWAP
    route = _route(instruction, keys)
    assert route["instruction"] == "swap"
    assert route["authority"] == payload["address"]
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell")]
    assert trades == []
    reasons = [row.get("reason") for row in decoded.get("unresolved") or []]
    assert reasons


def test_token_2022_decodes_from_attached_page():
    payload = _load_fixture("token2022-transfer.json")
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    assert decoded["coverage"]["transactions"] == 1
    reasons = " ".join(row.get("reason") or "" for row in decoded.get("unresolved") or [])
    assert "Token-2022 extra accounts may be extension roles" not in reasons


def test_lighthouse_is_infra_not_a_venue():
    assert LIGHTHOUSE == "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"
    records = [{
        "transaction": {"message": {"instructions": [{"programId": LIGHTHOUSE}]}},
    }]
    classified = classify_programs(records)
    assert classified["blockers"] == []
    assert TOKEN_2022_ID
