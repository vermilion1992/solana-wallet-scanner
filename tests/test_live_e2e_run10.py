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
    real = L.replay_cached_history_to_report

    def boom(*args, **kwargs):
        if kwargs.get("address") == big:
            raise sqlite3.DataError("string or blob too big")
        return real(*args, **kwargs)

    monkeypatch.setattr(L, "replay_cached_history_to_report", boom)
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
    cov = coverage_shares({"record_breakdown": breakdown})
    assert cov["value_share"] == Decimal("0")
    gate = mandatory_coverage_gate({"record_breakdown": breakdown}, min_share=Decimal("0.95"))
    assert gate.get("passed") is not True
    assert SOL_SWAP_FLOOR == Decimal("0.003")


def test_disk_sensitive_tests_skip_with_reason_when_volume_is_tiny(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", lambda _path: type("U", (), {"free": 1024})())
    with pytest.raises(pytest.skip.Exception, match="free disk"):
        skip_if_low_disk(tmp_path, need_mb=256)
