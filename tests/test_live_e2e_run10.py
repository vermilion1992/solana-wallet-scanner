"""Run-10 regressions. Offline only: no live calls, no secrets."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import scanner.mass_search.live_e2e as L
from scanner.investigation import JUPITER, USDC
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.g3_history import load_cached_page, persist_page
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.qualification_gates import coverage_shares, mandatory_coverage_gate
from scanner.mass_search.record_breakdown import SOL_SWAP_FLOOR, partition_records
from scanner.mass_search.result_relevant_coverage import build_result_relevant
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    SEED_NANSEN,
    SEED_TOKEN_INTERSECT,
    load_known_wallets_from_outputs,
)
from scanner.storage import Store
from tests.conftest import skip_if_low_disk

ROOT = L.ROOT
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
W1 = "4zTQe6QiUWqAD8czsGpXdm8hMHNnh38DF19KS5mXKBa3"
W2 = "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"
FIX = ROOT / "tests/fixtures/seed_sources"
TOKEN_X = "TokenX1111111111111111111111111111111111111"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.setenv("SCANNER_BIRDEYE_BACKOFF_SEC", "0")
    monkeypatch.setenv("SCANNER_BIRDEYE_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("SCANNER_HELIUS_MIN_INTERVAL_SEC", "0")
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


def _cfg(tmp_path, **raw):
    out = raw.pop("out", "out")
    base = {
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / out),
        "phases": "1",
        "discovery": True,
        "wallets": "",
    }
    base.update(raw)
    cfg = L.validate_config(base)
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def _fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _sha_sidecar(path, raw):
    digest = hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw)
    path.with_name(path.name + ".integrity.json").write_text(
        json.dumps({"written_sha256": digest, "original_sha256": digest, "scrubbed": False}),
        encoding="utf-8",
    )
    return digest


def _addr(i, tf="x"):
    digest = hashlib.sha256(f"{tf}-{i}".encode()).hexdigest()
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int(digest, 16)
    s = ""
    while len(s) < 44:
        s += alphabet[n % 58]
        n //= 58
    return s


class FakeNansen:
    def __init__(self, per_page=50, pages=1, n_trades=None):
        self.calls, self.per_page, self.pages, self.n_trades = [], per_page, pages, n_trades

    def rows(self, tf, page):
        if page > self.pages:
            return []
        out = []
        for i in range((page - 1) * self.per_page, page * self.per_page):
            out.append({
                "address": _addr(i, tf),
                "realized_pnl_usd": 1000 - i,
                "n_trades": (self.n_trades(i) if self.n_trades else 10),
            })
        return out

    async def __call__(self, method, path, body=None):
        self.calls.append((path, json.loads(json.dumps(body or {}))))
        if path == NANSEN_LEADERBOARD_PATH:
            tf = body.get("timeframe") or body.get("date", {}).get("from")
            page = int((body.get("pagination") or {}).get("page") or body.get("page") or 1)
            payload = {"data": self.rows(tf, page)}
            units = "5"
        else:
            payload = {"realized_pnl_usd": 1}
            units = "1"
        raw = json.dumps(payload).encode()
        return {
            "status": 200,
            "body": payload,
            "fetched_at": "x",
            "raw_bytes": raw,
            "billing": {"credits_cost": units},
        }


def test_d10_6_phase4_cache_row_has_no_size_bound(tmp_path):
    store = Store(tmp_path)
    store.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
    records = [{"transaction": {"signatures": [f"s{i}"]}, "blockTime": i, "pad": "x" * 200} for i in range(1000)]
    payload = {"kind": "g3-history-page-v2", "records": records}
    try:
        persist_page(store, "auth", "W", 0, payload)
    except sqlite3.DataError as error:
        pytest.fail(f"single-row persist of a large corpus raised {error!r}; one large wallet blocks all of Phase 4")
    loaded = load_cached_page(store, "auth", "W", 0)
    assert loaded is not None
    assert len(loaded.get("records") or []) == 1000
    store.close()


def test_d10_6_one_wallet_failure_does_not_block_phase4(tmp_path, monkeypatch):
    skip_if_low_disk(tmp_path, need_mb=64)
    big = "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK"
    small = "7jsNiaEV8HzBHjYPDEddeZGJsmNwkCvdaPqDdgptc7WA"
    out = tmp_path / "out"
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "4",
        "discovery": False,
        "wallets": f"{big},{small}",
    })
    for address, sig in ((big, "big-sig"), (small, "small-sig")):
        rec = [{
            "blockTime": 1_791_000_000,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [address]}},
            "meta": {"err": None, "fee": 5000, "preBalances": [10**9], "postBalances": [10**9 - 5000]},
        }]
        raw_dir = out / "raw" / "phase3" / address
        raw_dir.mkdir(parents=True)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"data": rec, "paginationToken": None}}).encode()
        _sha_sidecar(raw_dir / "page0.bin", body)
    state = {
        "phase3": {
            big: {"pages": 1, "done": True},
            small: {"pages": 1, "done": True},
        },
        "phase2": {},
        "seed_metadata": {},
    }
    def boom(*args, **kwargs):
        address = kwargs.get("address")
        if address == big:
            raise sqlite3.DataError("string or blob too big")
        return {
            "report": {
                "id": f"stub-{address}",
                "address": address,
                "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
                "metrics": {},
                "record_breakdown": {
                    "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {}},
                },
            }
        }

    monkeypatch.setattr(L, "replay_cached_history_to_report", boom)
    monkeypatch.setattr(L, "decode_supported_swaps", lambda *args, **kwargs: {"events": [], "unresolved": []})
    monkeypatch.setattr(L, "inject_undecoded_buy_taints", lambda decoded, *args, **kwargs: decoded)
    monkeypatch.setattr(L, "build_research_profile", lambda *args, **kwargs: {
        "qualification_level": "insufficient_evidence",
        "completed_trades": 0,
    })
    monkeypatch.setattr(L, "attach_live_independent_audit", lambda *args, **kwargs: {
        "status": "not_independently_audited",
    })
    store = Store(tmp_path / "store")
    result = L.phase4_offline(store, cfg, state)
    store.close()
    by_addr = {row["address"]: row for row in result["wallets"]}
    assert set(by_addr) == {big, small}
    assert by_addr[big]["lead_level"] == "insufficient_evidence"
    assert "phase4_wallet_failed" in str(by_addr[big]["blocker"])
    assert by_addr[small]["lead_level"] is not None


def test_d10_7_dry_run_does_not_write_placeholder_pages(tmp_path):
    address = W1
    cfg = _cfg(tmp_path, phases="2", discovery=False, wallets=address, seed_source="nansen")
    cfg["dry_run"] = True
    store, _ = open_grant_store(cfg["authorization_id"])
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    state = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend()}
    asyncio.run(L._dispatch_helius(
        store, grant, cfg, state, L.RecorderTransport().helius, address,
        {"transactionDetails": "full", "limit": 100},
        phase=3, page_index=0,
    ))
    store.close()
    planted = Path(cfg["output_dir"]) / "raw" / "phase3" / address / "page0.bin"
    assert not planted.exists(), "dry-run must never write recorder pages into the output folder"


def test_d10_7_live_rejects_placeholder_page_loudly(tmp_path):
    address = W1
    out = tmp_path / "live-out"
    dest = out / "raw" / "phase3" / address
    dest.mkdir(parents=True)
    dest.joinpath("page0.bin").write_bytes(L.DRY_RUN_HELIUS_PLACEHOLDER_RAW)
    cfg = {
        "output_dir": str(out),
        "dry_run": False,
        "explicit_retry": False,
    }
    store = Store(tmp_path / "store")
    grant = {
        "authorization_id": "live-e2e-proof-2026-10-13-mitch",
        "enabled": True,
        "providers": [{
            "provider_id": "helius",
            "allowed_operations": ["getTransactionsForAddress"],
            "cycle_start": "2026-10-07T00:00:00Z",
            "max_units": 30000,
        }],
    }
    state = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend()}

    async def transport(*_args, **_kwargs):
        raise AssertionError("placeholder page must not dispatch HTTP")

    with pytest.raises(SourceError, match="dry-run placeholder") as raised:
        asyncio.run(L._dispatch_helius(
            store, grant, cfg, state, transport, address,
            {"transactionDetails": "full", "limit": 1000},
            phase=3, page_index=0,
        ))
    store.close()
    assert getattr(raised.value, "state", None) == "DRY_RUN_PLACEHOLDER"


def test_d10_1_known_loader_reads_run_state_in_directory(tmp_path):
    prior = tmp_path / "prior-out"
    prior.mkdir()
    payload = {
        "wallets": [W1],
        "phase2": {W2: {"address": W2}},
        "phase3": {"9hciHnHzEyLHtjbeUzpp6ZRt4Y4HQbZg4Vx9sFAGGiup": {"done": True}},
    }
    (prior / "RUN_STATE.json").write_text(json.dumps(payload), encoding="utf-8")
    known = load_known_wallets_from_outputs([str(prior)])
    assert W1 in known
    assert W2 in known
    assert "9hciHnHzEyLHtjbeUzpp6ZRt4Y4HQbZg4Vx9sFAGGiup" in known


def test_d10_2_ti_import_by_prior_output_dir(tmp_path):
    prior = tmp_path / "prior"
    phase1 = prior / "raw" / "phase1"
    phase1.mkdir(parents=True)
    page = _fx("token_txs_seek.json")
    raw = b"\n".join(json.dumps(page, separators=(",", ":")).encode() for _ in range(9))
    (phase1 / "token-intersect.bin").write_bytes(raw)
    _sha_sidecar(phase1 / "token-intersect-abc123.bin", raw)
    (prior / "RUN_STATE.json").write_text(json.dumps({
        "seed_source_progress": {SEED_TOKEN_INTERSECT: {"tokens": [JUP, BONK, USDC_MINT]}},
        "discoveries": {"ti": {"seed_source": SEED_TOKEN_INTERSECT, "tokens": [JUP, BONK, USDC_MINT]}},
    }), encoding="utf-8")
    cfg = _cfg(tmp_path, seed_source="token_intersect", import_raw_dir=str(prior), out="fresh")
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    result = asyncio.run(L.phase1_discovery(store, L.load_grant(ROOT / L.DRAFT_REL_13), cfg, st, rec))
    store.close()
    assert rec.calls == []
    assert st["spend"]["birdeye_requests"] == 0
    assert st.get("wallets")
    ti = (result.get("per_source") or {}).get(SEED_TOKEN_INTERSECT) or result
    assert ti.get("imported") is True or result.get("count")


def test_d10_3_profiles_run_after_prefilter(tmp_path, monkeypatch):
    fake = FakeNansen(pages=1, n_trades=lambda i: 9000 if i % 2 == 0 else 10)
    monkeypatch.setattr(L, "_live_nansen", fake)
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture")
    cfg = _cfg(tmp_path, seed_source="nansen", nansen_leaderboard_pages=1, nansen_profile_cap=10)
    cfg["dry_run"] = False
    cfg["nansen_enabled"] = True
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec := L.RecorderTransport()))
    store.close()
    profiled = {(b.get("address") or b.get("wallet_address")) for p, b in fake.calls if p == NANSEN_PNL_SUMMARY_PATH}
    dropped = set(st.get("nansen_prefilter_dropped") or {})
    assert profiled
    assert dropped
    assert not (profiled & dropped), f"{len(profiled & dropped)} profiler credits spent on prefilter-dropped wallets"


def test_d10_4_prefilter_dropped_list_survives_second_pass(tmp_path):
    a, b = _addr(1, "d"), _addr(2, "d")
    meta = {
        a: {"primary_seed_source": SEED_NANSEN, "seed_sources": [SEED_NANSEN], "vendor_metrics": {"n_trades": 9000}, "timeframe": 90},
        b: {"primary_seed_source": SEED_NANSEN, "seed_sources": [SEED_NANSEN], "vendor_metrics": {"n_trades": 10}, "timeframe": 90},
    }
    cfg = {"wallets": [a, b], "output_dir": str(tmp_path)}
    st = {"wallets": [a, b], "seed_metadata": meta, "phase2": {}}
    L.apply_nansen_vendor_prefilter(cfg, st)
    L.apply_nansen_vendor_prefilter(cfg, st)
    assert st["nansen_prefilter_dropped_addresses"] == [a]


def test_d10_5_resume_phase2_plan_counts_state_pool(tmp_path):
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "2",
        "discovery": False,
        "wallets": "",
        "resume": True,
        "seed_source": "nansen",
        "history_to_first": True,
    })
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    st = {
        "wallets": [W1, W2],
        "bounds": cfg["bounds"],
        "spend": L.empty_spend(),
        "phase_spend": L.empty_phase_spend(),
    }
    plan = L.plan_request_counts(cfg, st)
    assert plan["wallet_count"] == 2
    assert plan["totals"]["helius_requests"] >= 6


def test_gu81_usdc_quoted_value_share_not_zeroed_by_sol_residue():
    """Gu81 +8513 USDC / 10 episodes showed value share 0 because fee/rent SOL
    created a 100% unsupported SOL bucket. That is a valuation bug, not a gate change.
    """
    wallet = "Gu81PufB1kmHWMA1RdvPry1qvGNMDP8JfAmYGCcS9Vur"
    stamp = int(datetime(2026, 5, 28, tzinfo=timezone.utc).timestamp())
    decoded = {
        "events": [{
            "signature": "usdc-buy",
            "kind": "buy",
            "amount_usdc": "851.306",
            "mint": TOKEN_X,
        }],
        "unresolved": [],
    }
    usdc_raw = {
        "blockTime": stamp,
        "transaction": {
            "signatures": ["usdc-buy"],
            "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10**10, 1],
            "postBalances": [10**10 - 5000, 1],
            "preTokenBalances": [
                {"owner": wallet, "mint": USDC, "uiTokenAmount": {"amount": "851306000"}},
                {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": USDC, "uiTokenAmount": {"amount": "0"}},
                {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}},
            ],
        },
    }
    dust_raw = {
        "blockTime": stamp + 60,
        "transaction": {
            "signatures": ["sol-dust"],
            "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10**10, 1],
            "postBalances": [10**10 - 5000 + 2_000_000, 1],
            "preTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}}],
            "postTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}}],
        },
    }
    start = datetime.fromtimestamp(stamp - 3600, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(stamp + 3600, tz=timezone.utc).isoformat()
    breakdown = partition_records(
        [usdc_raw, dust_raw], decoded, wallet, window_start=start, window_end=end,
    )
    shares = breakdown["unsupported_swap_share_in_window"]["by_consideration"]
    assert "SOL" not in shares
    assert shares.get("USDC") in (None, "0")
    # Gate fields are R, not whole-span. Build R from the same records so a
    # USDC-quoted buy is not unknown just because SOL dust exists.
    breakdown["result_relevant"] = build_result_relevant(
        [usdc_raw, dust_raw], decoded, wallet,
        report_start=start, report_end=end, ledger=[{"mint": TOKEN_X}],
    )
    report = {"record_breakdown": breakdown}
    cov = coverage_shares(report)
    assert cov["value_share"] is not None
    assert cov["value_share"] > Decimal("0")
    gate = mandatory_coverage_gate(report, min_share=Decimal("0.95"))
    assert gate.get("passed") is True or cov["value_share"] >= Decimal("0.95")


def test_gu81_real_unsupported_sol_still_blocks_value_share():
    wallet = "Gu81PufB1kmHWMA1RdvPry1qvGNMDP8JfAmYGCcS9Vur"
    stamp = int(datetime(2026, 5, 28, tzinfo=timezone.utc).timestamp())
    decoded = {
        "events": [{
            "signature": "usdc-buy",
            "kind": "buy",
            "amount_usdc": "851.306",
            "mint": TOKEN_X,
        }],
        "unresolved": [],
    }
    usdc_raw = {
        "blockTime": stamp,
        "transaction": {
            "signatures": ["usdc-buy"],
            "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10**10, 1],
            "postBalances": [10**10 - 5000, 1],
            "preTokenBalances": [
                {"owner": wallet, "mint": USDC, "uiTokenAmount": {"amount": "851306000"}},
                {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": USDC, "uiTokenAmount": {"amount": "0"}},
                {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}},
            ],
        },
    }
    sol_raw = {
        "blockTime": stamp + 60,
        "transaction": {
            "signatures": ["sol-swap"],
            "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10**10, 1],
            "postBalances": [10**10 - 5000 + 500_000_000, 1],
            "preTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}}],
            "postTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}}],
        },
    }
    start = datetime.fromtimestamp(stamp - 3600, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(stamp + 3600, tz=timezone.utc).isoformat()
    breakdown = partition_records(
        [usdc_raw, sol_raw], decoded, wallet, window_start=start, window_end=end,
    )
    shares = breakdown["unsupported_swap_share_in_window"]["by_consideration"]
    assert Decimal(str(shares["SOL"])) == Decimal("1")
    breakdown["result_relevant"] = build_result_relevant(
        [usdc_raw, sol_raw], decoded, wallet,
        report_start=start, report_end=end, ledger=[{"mint": TOKEN_X}],
    )
    cov = coverage_shares({"record_breakdown": breakdown})
    assert cov["value_share"] == Decimal("0")
    gate = mandatory_coverage_gate({"record_breakdown": breakdown}, min_share=Decimal("0.95"))
    assert gate.get("passed") is not True
    assert SOL_SWAP_FLOOR == Decimal("0.003")


def test_disk_sensitive_tests_skip_with_reason_when_volume_is_tiny(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", lambda _path: type("U", (), {"free": 1024})())
    with pytest.raises(pytest.skip.Exception, match="free disk"):
        skip_if_low_disk(tmp_path, need_mb=256)


def _bjcx_shaped_record(i, pad=4000):
    """Realistic GTA-sized record: signature, keys, meta, and a large pad."""
    return {
        "blockTime": 1_791_000_000 - i,
        "slot": 400_000_000 - i,
        "transaction": {
            "signatures": [f"BJcxSig{i:06d}" + "x" * 40],
            "message": {
                "accountKeys": [
                    "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK",
                    JUPITER,
                    USDC,
                ],
                "instructions": [{"programId": JUPITER, "data": "x" * 80}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10**10, 1, 1],
            "postBalances": [10**10 - 5000, 1, 1],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "logMessages": ["Program log: Instruction: Route"],
            "pad": "R" * pad,
        },
    }


def test_d10_6_persist_20k_realistic_records_is_linear(tmp_path):
    """≥20k BJcx-shaped records must chunk in linear time, not re-encode the growing blob."""
    skip_if_low_disk(tmp_path, need_mb=512)
    store = Store(tmp_path)
    store.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 512_000)
    records = [_bjcx_shaped_record(i, pad=4000) for i in range(20_000)]
    payload = {"kind": "g3-history-page-v2", "records": records, "address": "BJcx"}
    started = datetime.now(timezone.utc)
    persist_page(store, "auth", "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK", 0, payload)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    loaded = load_cached_page(store, "auth", "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK", 0)
    store.close()
    assert loaded is not None
    assert len(loaded.get("records") or []) == 20_000
    assert elapsed < 25, f"persist_page of 20k realistic records took {elapsed:.1f}s; still quadratic?"


def test_d10_6_bjcx_synthetic_capture_finishes_phase4(tmp_path, monkeypatch):
    skip_if_low_disk(tmp_path, need_mb=256)
    big = "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK"
    small = "7jsNiaEV8HzBHjYPDEddeZGJsmNwkCvdaPqDdgptc7WA"
    out = tmp_path / "out"
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "4",
        "discovery": False,
        "wallets": f"{big},{small}",
    })
    cfg["phase4_wallet_timeout_sec"] = 120
    records = [_bjcx_shaped_record(i, pad=2500) for i in range(3000)]
    raw_dir = out / "raw" / "phase3" / big
    raw_dir.mkdir(parents=True)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"data": records, "paginationToken": None}}).encode()
    _sha_sidecar(raw_dir / "page0.bin", body)
    small_dir = out / "raw" / "phase3" / small
    small_dir.mkdir(parents=True)
    tiny = [_bjcx_shaped_record(0, pad=20)]
    _sha_sidecar(
        small_dir / "page0.bin",
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"data": tiny, "paginationToken": None}}).encode(),
    )
    state = {
        "phase3": {big: {"pages": 1, "done": True}, small: {"pages": 1, "done": True}},
        "phase2": {},
        "seed_metadata": {},
    }

    def persist_then_stub(store, **kwargs):
        address = kwargs.get("address")
        persist_page(
            store,
            kwargs.get("authorization_id") or "auth",
            address,
            0,
            {"kind": "g3-history-page-v2", "records": kwargs.get("records") or []},
        )
        return {
            "report": {
                "id": f"stub-{address}",
                "address": address,
                "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
                "metrics": {},
                "record_breakdown": {
                    "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {}},
                },
            }
        }

    monkeypatch.setattr(L, "replay_cached_history_to_report", persist_then_stub)
    monkeypatch.setattr(L, "decode_supported_swaps", lambda *args, **kwargs: {"events": [], "unresolved": []})
    monkeypatch.setattr(L, "inject_undecoded_buy_taints", lambda decoded, *args, **kwargs: decoded)
    monkeypatch.setattr(L, "build_research_profile", lambda *args, **kwargs: {
        "qualification_level": "insufficient_evidence",
        "completed_trades": 0,
    })
    monkeypatch.setattr(L, "attach_live_independent_audit", lambda *args, **kwargs: {
        "status": "not_independently_audited",
    })
    store = Store(tmp_path / "store")
    store.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 256_000)
    started = datetime.now(timezone.utc)
    result = L.phase4_offline(store, cfg, state)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    loaded = load_cached_page(store, cfg.get("authorization_id") or L.AUTHORIZATION_ID, big, 0)
    store.close()
    by_addr = {row["address"]: row for row in result["wallets"]}
    assert set(by_addr) == {big, small}
    assert by_addr[big]["lead_level"] is not None
    assert "phase4_timeout" not in str(by_addr[big].get("blocker") or "")
    assert loaded is not None
    assert len(loaded.get("records") or []) == 3000
    assert elapsed < 60, f"BJcx synthetic Phase 4 took {elapsed:.1f}s"


def test_d10_6_phase4_timeout_is_fail_closed_and_batch_continues(tmp_path, monkeypatch):
    skip_if_low_disk(tmp_path, need_mb=64)
    slow = "BJcxXxr2mSr71SVJaqvHHmdxHUrYRvC4sct1wMNZxirK"
    fast = "7jsNiaEV8HzBHjYPDEddeZGJsmNwkCvdaPqDdgptc7WA"
    out = tmp_path / "out"
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "4",
        "discovery": False,
        "wallets": f"{slow},{fast}",
    })
    cfg["phase4_wallet_timeout_sec"] = 1
    for address, sig in ((slow, "slow-sig"), (fast, "fast-sig")):
        rec = [{
            "blockTime": 1_791_000_000,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [address]}},
            "meta": {"err": None, "fee": 5000, "preBalances": [10**9], "postBalances": [10**9 - 5000]},
        }]
        raw_dir = out / "raw" / "phase3" / address
        raw_dir.mkdir(parents=True)
        _sha_sidecar(
            raw_dir / "page0.bin",
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"data": rec, "paginationToken": None}}).encode(),
        )
    state = {
        "phase3": {slow: {"pages": 1, "done": True}, fast: {"pages": 1, "done": True}},
        "phase2": {},
        "seed_metadata": {},
    }

    def maybe_sleep(*args, **kwargs):
        address = kwargs.get("address")
        if address == slow:
            import time
            time.sleep(3)
        return {
            "report": {
                "id": f"stub-{address}",
                "address": address,
                "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
                "metrics": {},
                "record_breakdown": {
                    "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {}},
                },
            }
        }

    monkeypatch.setattr(L, "replay_cached_history_to_report", maybe_sleep)
    monkeypatch.setattr(L, "decode_supported_swaps", lambda *args, **kwargs: {"events": [], "unresolved": []})
    monkeypatch.setattr(L, "inject_undecoded_buy_taints", lambda decoded, *args, **kwargs: decoded)
    monkeypatch.setattr(L, "build_research_profile", lambda *args, **kwargs: {
        "qualification_level": "insufficient_evidence",
        "completed_trades": 0,
    })
    monkeypatch.setattr(L, "attach_live_independent_audit", lambda *args, **kwargs: {
        "status": "not_independently_audited",
    })
    store = Store(tmp_path / "store")
    result = L.phase4_offline(store, cfg, state)
    store.close()
    by_addr = {row["address"]: row for row in result["wallets"]}
    assert set(by_addr) == {slow, fast}
    assert by_addr[slow]["lead_level"] == "insufficient_evidence"
    assert "phase4_timeout" in str(by_addr[slow]["blocker"])
    assert by_addr[fast]["lead_level"] is not None
    assert "phase4_timeout" not in str(by_addr[fast].get("blocker") or "")


def test_d10_2_ti_import_recovers_tokens_from_page_bodies(tmp_path):
    prior = tmp_path / "prior"
    phase1 = prior / "raw" / "phase1"
    phase1.mkdir(parents=True)
    listing = _fx("token_list_durable.json")
    txs = _fx("token_txs_seek.json")
    pages = [listing] + [txs] * 18
    raw = b"\n".join(json.dumps(page, separators=(",", ":")).encode() for page in pages)
    _sha_sidecar(phase1 / "token-intersect-deadbeefcafe.bin", raw)
    (prior / "RUN_STATE.json").write_text(json.dumps({
        "seed_source_progress": {SEED_TOKEN_INTERSECT: {
            "paid_pages": 13,
            "tokens": [
                "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
                "So11111111111111111111111111111111111111112",
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            ],
        }},
    }), encoding="utf-8")
    cfg = _cfg(tmp_path, seed_source="token_intersect", import_raw_dir=str(prior), out="fresh")
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    result = asyncio.run(L.phase1_discovery(store, L.load_grant(ROOT / L.DRAFT_REL_13), cfg, st, rec))
    store.close()
    assert rec.calls == []
    ti = (result.get("per_source") or {}).get(SEED_TOKEN_INTERSECT) or result
    assert ti.get("imported") is True
    assert ti.get("tokens") or st.get("wallets")
    assert st.get("wallets")


def test_d10_2_ti_import_without_tokens_fails_loudly(tmp_path):
    prior = tmp_path / "prior"
    phase1 = prior / "raw" / "phase1"
    phase1.mkdir(parents=True)
    page = {"success": True, "data": {"items": [{"owner": W1, "blockUnixTime": 1900000000, "txType": "swap"}]}}
    raw = json.dumps(page, separators=(",", ":")).encode()
    _sha_sidecar(phase1 / "token-intersect-abad1dea0001.bin", raw)
    (prior / "RUN_STATE.json").write_text("{}", encoding="utf-8")
    cfg = _cfg(tmp_path, seed_source="token_intersect", import_raw_dir=str(prior), out="fresh")
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    with pytest.raises(SourceError, match="tokens unknown"):
        asyncio.run(L.phase1_discovery(store, L.load_grant(ROOT / L.DRAFT_REL_13), cfg, st, rec))
    store.close()
    assert rec.calls == []
    assert not st.get("wallets")


def test_usdt_quoted_unsupported_moves_value_share():
    wallet = "UsdtCov11111111111111111111111111111111111"
    stamp = int(datetime(2026, 5, 28, tzinfo=timezone.utc).timestamp())
    from scanner.investigation import USDT
    decoded_events = [{
        "signature": f"sol-buy-{i}",
        "kind": "buy",
        "amount_sol": "0.5",
        "mint": TOKEN_X,
    } for i in range(200)]
    records = []
    for i in range(200):
        records.append({
            "blockTime": stamp + i,
            "transaction": {
                "signatures": [f"sol-buy-{i}"],
                "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
            },
            "meta": {
                "err": None,
                "fee": 5000,
                "preBalances": [10**10, 1],
                "postBalances": [10**10 - 500_000_000, 1],
                "preTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}}],
                "postTokenBalances": [{"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}}],
            },
        })
    for i in range(2):
        records.append({
            "blockTime": stamp + 300 + i,
            "transaction": {
                "signatures": [f"usdt-undecoded-{i}"],
                "message": {"accountKeys": [wallet, JUPITER], "instructions": [{"programId": JUPITER}]},
            },
            "meta": {
                "err": None,
                "fee": 5000,
                "preBalances": [10**10, 1],
                "postBalances": [10**10 - 5000, 1],
                "preTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "5000000000"}},
                    {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "0"}},
                ],
                "postTokenBalances": [
                    {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "0"}},
                    {"owner": wallet, "mint": TOKEN_X, "uiTokenAmount": {"amount": "1000"}},
                ],
            },
        })
    start = datetime.fromtimestamp(stamp - 3600, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(stamp + 3600, tz=timezone.utc).isoformat()
    breakdown = partition_records(
        records, {"events": decoded_events, "unresolved": []}, wallet,
        window_start=start, window_end=end,
    )
    shares = breakdown["unsupported_swap_share_in_window"]["by_consideration"]
    assert "USDT" in shares
    assert Decimal(str(shares["USDT"])) == Decimal("1")
    breakdown["result_relevant"] = build_result_relevant(
        records, {"events": decoded_events, "unresolved": []}, wallet,
        report_start=start, report_end=end, ledger=[{"mint": TOKEN_X}],
    )
    cov = coverage_shares({"record_breakdown": breakdown})
    assert cov["value_share"] == Decimal("0")
    gate = mandatory_coverage_gate({"record_breakdown": breakdown}, min_share=Decimal("0.95"))
    assert gate.get("passed") is not True


@pytest.mark.skip(reason=(
    "asserts archived run-10 RUN_STATE / misplaced dry-run page files that are "
    "not in this tree; behavioural D10-7 checks cover the defect"
))
def test_d10_7_dry_run_placeholder_page_shape():
    root = Path(__file__).resolve().parents[1] / "logs/misplaced_dry_pages_p3x"
    pages = sorted(root.glob("*/page0.bin"))
    assert len(pages) == 6
    bodies = {p.read_bytes() for p in pages}
    assert bodies == {b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'}
    state = json.loads((
        Path(__file__).resolve().parents[1] / "logs/RUN_STATE.nansen10.after_p3x_refused.json"
    ).read_text())
    cursor = state["phase3"]["47hGpFXAkbWFtfpeAo4Hr2KcxAWVpaUH5ojAbwzzxobN"]
    assert cursor["history_complete_reason"] != "unreceipted_page", cursor
