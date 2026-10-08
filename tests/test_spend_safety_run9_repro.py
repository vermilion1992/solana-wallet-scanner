"""Independent spend-safety checks for PR #8 tip 02712bf (run-9 executor). Offline, $0.
Sockets are blocked for every test; live transports are replaced by counting fakes."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import scanner.mass_search.live_e2e as L
from scanner.mass_search.adapters import BIRDEYE_TOKEN_TXS_PATH, SourceError
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH, NANSEN_PNL_SUMMARY_PATH, SEED_NANSEN, SEED_TOKEN_INTERSECT,
)

ROOT = L.ROOT
REAL_SCANNER = Path("/home/box/.scanner")
ARMED_13 = Path("/workspace/research-search-b-live/live-e2e-8b/armed/"
                "live_authorization.live-e2e-proof-2026-10-13-mitch.ARMED.86cc710.local.json")
FIX = ROOT / "tests/fixtures/seed_sources"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
W1 = "4zTQe6QiUWqAD8czsGpXdm8hMHNnh38DF19KS5mXKBa3"
W2 = "9T546uDgKfBjDENngY4fehrkfrfAQ17Ua7UdyzGHuU3z"
W3 = "CAcPyBM3t7NhrFDAVxToqoBoM8zumrXf8NPsj7Pn9pa9"


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    if not root.exists():
        return "absent"
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("NETWORK BLOCKED")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    for k in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "NANSEN_API_KEY", "HELIUS_API_KEYS", "HELIUS_RPC_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SCANNER_BIRDEYE_BACKOFF_SEC", "0")
    monkeypatch.setenv("SCANNER_BIRDEYE_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("SCANNER_HELIUS_MIN_INTERVAL_SEC", "0")


@pytest.fixture
def scratch_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.delenv("SCANNER_LIVE_LEDGER_DIR", raising=False)
    return home


def _fx(name):
    return json.loads((FIX / name).read_text())


# ---------------------------------------------------------------- 1. dry-run never writes a real ledger
CLI = [sys.executable, "-c",
       "import socket,runpy,sys;"
       "socket.socket.connect=lambda *a:(_ for _ in ()).throw(RuntimeError('NETWORK BLOCKED'));"
       "sys.argv=['live_e2e']+sys.argv[1:];"
       "runpy.run_module('scanner.mass_search.live_e2e',run_name='__main__')"]


def _cli(args, env_extra, unset=()):
    env = {k: v for k, v in os.environ.items() if k not in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "NANSEN_API_KEY", *unset)}
    env.update({"HELIUS_API_KEY": "dummy-h", "BIRDEYE_API_KEY": "dummy-b", "NANSEN_API_KEY": "dummy-n", "PYTHONPATH": str(ROOT)})
    env.update(env_extra)
    return subprocess.run(CLI + args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)


@pytest.mark.parametrize("grant_kind", ["draft13", "armed13"])
@pytest.mark.parametrize("ledger_env", ["unset", "scratch"])
def test_dry_run_writes_nothing_to_real_ledger(tmp_path, monkeypatch, grant_kind, ledger_env):
    if grant_kind == "armed13" and not ARMED_13.exists():
        pytest.skip("armed copy not present")
    grant = str(ROOT / L.DRAFT_REL_13) if grant_kind == "draft13" else str(ARMED_13)
    before = tree_hash(REAL_SCANNER)
    env = {"HOME": "/home/box"}
    unset = ("SCANNER_LIVE_LEDGER_HOME", "SCANNER_LIVE_LEDGER_DIR")
    if ledger_env == "scratch":
        env["SCANNER_LIVE_LEDGER_HOME"] = str(tmp_path / "scratch")
    out = tmp_path / "out"
    r = _cli(["--dry-run", "--grant", grant, "--discovery", "--seed-source", "token_intersect,nansen",
              "--history-to-first", "--per-wallet-cap", "6", "--nansen-profile-cap", "3", "--output", str(out)],
             env, unset=unset)
    assert r.returncode == 0, r.stderr[-2000:]
    plan = json.loads((out / "DRY_RUN_PLAN.json").read_text())
    assert plan["dry_run"] is True
    assert tree_hash(REAL_SCANNER) == before, "dry-run modified /home/box/.scanner"
    if ledger_env == "unset":
        assert (out / L.DRY_RUN_LEDGER_DIRNAME).exists()


# ---------------------------------------------------------------- 2. armed ledger refused in dry-run
@pytest.mark.parametrize("how", ["env_home", "env_dir", "ledger_dir_flag", "subdir_flag", "symlink_env"])
def test_dry_run_refuses_armed_ledger_path(tmp_path, how):
    before = tree_hash(REAL_SCANNER)
    real = "/home/box/.scanner/live-e2e-ledgers"
    env = {"HOME": "/home/box"}
    unset = ("SCANNER_LIVE_LEDGER_HOME", "SCANNER_LIVE_LEDGER_DIR")
    extra = []
    if how == "env_home":
        env["SCANNER_LIVE_LEDGER_HOME"] = real
    elif how == "env_dir":
        env["SCANNER_LIVE_LEDGER_DIR"] = real
    elif how == "ledger_dir_flag":
        extra = ["--ledger-dir", real]
    elif how == "subdir_flag":
        extra = ["--ledger-dir", real + "/live-e2e-proof-2026-10-13-mitch"]
    elif how == "symlink_env":
        link = tmp_path / "ln"
        link.symlink_to(real)
        env["SCANNER_LIVE_LEDGER_HOME"] = str(link)
    r = _cli(["--dry-run", "--grant", str(ROOT / L.DRAFT_REL_13), "--discovery", "--seed-source", "nansen",
              "--output", str(tmp_path / "out")] + extra, env, unset=unset)
    assert r.returncode != 0, "dry-run accepted an armed ledger path"
    assert "armed" in (r.stderr + r.stdout).lower() or "refus" in (r.stderr + r.stdout).lower()
    assert tree_hash(REAL_SCANNER) == before


# ---------------------------------------------------------------- 3. plan >= runtime (retry headroom is allowed)
def _cfg(tmp_path, **raw):
    base = {"mode": "dry-run", "grant_path": str(ROOT / L.DRAFT_REL_13), "output_dir": str(tmp_path / "out"),
            "phases": "1", "discovery": True, "wallets": ""}
    base.update(raw)
    cfg = L.validate_config(base)
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def _state():
    return {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}


@pytest.mark.parametrize("profile_cap", [None, 0, 1, 5, 100])
def test_nansen_plan_vs_runtime_profile_cap(tmp_path, monkeypatch, scratch_home, profile_cap):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture")
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    rows = [{"address": a, "realized_pnl_usd": 1} for a in (W1, W2, W3, JUP, BONK)]
    cfg = _cfg(tmp_path, seed_source="nansen", nansen_profile_cap=profile_cap)
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {NANSEN_LEADERBOARD_PATH: {"data": rows}, NANSEN_PNL_SUMMARY_PATH: {"realized_pnl_usd": 1}}
    st = _state()
    plan = L.plan_request_counts(cfg, st)
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    calls = [c for c in rec.calls if c.get("provider") == "nansen"]
    assert st["spend"]["nansen_requests"] == len(calls)
    assert st["spend"]["nansen_requests"] <= plan["totals"]["nansen_requests"]
    assert st["spend"]["nansen_units"] <= plan["totals"]["nansen_units"]
    assert st["spend"]["nansen_requests"] <= cfg["caps"]["nansen_requests"]
    if profile_cap is not None:
        profiles = sum(1 for c in calls if c.get("path") == NANSEN_PNL_SUMMARY_PATH)
        assert profiles <= profile_cap


def test_birdeye_token_intersect_plan_equals_runtime(tmp_path, scratch_home):
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC])
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    st = _state()
    plan = L.plan_request_counts(cfg, st)
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert st["spend"]["birdeye_requests"] == len(rec.calls)
    assert plan["totals"]["birdeye_requests"] >= st["spend"]["birdeye_requests"]
    assert plan["totals"]["birdeye_units"] >= st["spend"]["birdeye_units"]


def test_birdeye_token_list_plan_equals_runtime(tmp_path, scratch_home):
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    cfg = _cfg(tmp_path, seed_source="token_intersect")
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {L.BIRDEYE_TOKEN_LIST_PATH: _fx("token_list_durable.json"),
                    BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    st = _state()
    plan = L.plan_request_counts(cfg, st)
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert plan["totals"]["birdeye_requests"] >= st["spend"]["birdeye_requests"]
    assert plan["totals"]["birdeye_units"] >= st["spend"]["birdeye_units"]


# Helius: real _dispatch_helius on the live branch with a counting fake transport and a scratch ledger.
def _gta_page(address, page_index, n_pages, per_page=5, t0=1_791_000_000):
    recs = []
    for i in range(per_page):
        t = t0 - (page_index * per_page + i) * 86400 * 3
        recs.append({"blockTime": t, "slot": 300_000_000 - page_index * per_page - i,
                     "transaction": {"signatures": [f"{address[:6]}-{page_index}-{i}"],
                                     "message": {"accountKeys": [address], "instructions": []}},
                     "meta": {"err": None, "fee": 5000, "preBalances": [10**9], "postBalances": [10**9 - 5000],
                              "preTokenBalances": [], "postTokenBalances": []}})
    tok = f"tok-{address[:6]}-{page_index + 1}" if page_index + 1 < n_pages else None
    raw = json.dumps({"jsonrpc": "2.0", "result": {"data": recs, "paginationToken": tok}}).encode()
    return {"records": recs, "pagination_token": tok, "http_status": 200, "raw_bytes": raw,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(), "units": 0, "external_requests": 1}


class FakeHelius:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def __call__(self, address, *, options, page_index=0):
        self.calls.append((address, page_index, (options or {}).get("paginationToken")))
        return _gta_page(address, page_index, self.pages.get(address, 1))


def _live_cfg(tmp_path, wallets, cap, phases="3", out="out"):
    cfg = L.validate_config({"mode": "dry-run", "grant_path": str(ROOT / L.DRAFT_REL_13),
                             "output_dir": str(tmp_path / out), "phases": phases, "discovery": False,
                             "seed_source": "nansen", "wallets": ",".join(wallets), "per_wallet_cap": cap,
                             "history_to_first": True})
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    cfg["dry_run"] = False  # exercise the paid branch against a scratch ledger + fake transport
    return cfg


def _enabled_grant():
    g = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    g["enabled"] = True
    return g


@pytest.mark.parametrize("cap", [4, 6, 9])
def test_helius_phase3_plan_is_upper_bound(tmp_path, monkeypatch, scratch_home, cap):
    pages = {W1: 10, W2: 2, W3: 4}
    fake = FakeHelius(pages)
    monkeypatch.setattr(L, "_live_helius", fake)
    cfg = _live_cfg(tmp_path, [W1, W2, W3], cap)
    st = _state()
    st["wallets"] = [W1, W2, W3]
    st["phase2"] = {a: {"address": a, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 100}
                    for a in (W1, W2, W3)}
    st["bounds"] = cfg["bounds"]
    plan = L.plan_request_counts(cfg, st)
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase3_history(store, _enabled_grant(), cfg, st, L.RecorderTransport()))
    store.close()
    assert len(fake.calls) == st["spend"]["helius_requests"]
    assert st["spend"]["helius_requests"] <= plan["totals"]["helius_requests"], (plan["phase3_page_estimates"], fake.calls)
    assert st["spend"]["helius_units"] <= plan["totals"]["helius_units"]
    for a, n in pages.items():
        assert sum(1 for c in fake.calls if c[0] == a) <= max(0, cap - 3)


# ---------------------------------------------------------------- 4. 429 keeps paid pages; retries inside caps
class FakeBirdeye:
    """Live-branch Birdeye fake: 429 on calls [after, after+times)."""
    def __init__(self, body, after, times=None):
        self.body, self.after, self.times, self.calls = body, after, times, []

    async def __call__(self, method, path, params):
        self.calls.append((path, dict(params or {})))
        n = len(self.calls)
        if n >= self.after and (self.times is None or n < self.after + self.times):
            raise SourceError("RATE_LIMITED", "Birdeye rate limit", http_status=429, retryable=True)
        raw = json.dumps(self.body).encode()
        return {"status": 200, "body": self.body, "fetched_at": "x", "raw_bytes": raw}


@pytest.mark.parametrize("fail", [{"after": 5}, {"after": 5, "times": 1}, {"after": 1}, {"after": 9, "times": 1}])
@pytest.mark.parametrize("cap_req", [9, 10, 11, 40])
def test_429_live_branch_keeps_pages_and_retries_inside_caps(tmp_path, monkeypatch, scratch_home, fail, cap_req):
    fake = FakeBirdeye(_fx("token_txs_seek.json"), fail["after"], fail.get("times"))
    monkeypatch.setattr(L, "_live_birdeye", fake)
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC],
               max_birdeye_requests=cap_req)
    cfg["dry_run"] = False
    store, _ = open_grant_store(cfg["authorization_id"])
    st = _state()
    try:
        asyncio.run(L.phase1_discovery(store, grant, cfg, st, L.RecorderTransport()))
    except SourceError as e:
        assert e.state in ("CAP_EXCEEDED", "RATE_LIMITED")
    ledger_spend, _ = L.spend_from_ledger(store)
    store.close()
    assert len(fake.calls) <= cap_req, "more Birdeye HTTP calls than the cap"
    assert st["spend"]["birdeye_requests"] == len(fake.calls) == ledger_spend["birdeye_requests"]
    assert st["spend"]["birdeye_units"] <= cfg["caps"]["birdeye_units"]
    if fail["after"] > 1:
        raw = Path(cfg["output_dir"]) / "raw/phase1/token-intersect.bin"
        assert raw.exists() and raw.stat().st_size > 2, "paid pages not kept"
        ok = (st.get("seed_source_progress") or {}).get(SEED_TOKEN_INTERSECT, {}).get("paid_pages") or 0
        assert ok >= min(fail["after"] - 1, 9)


@pytest.mark.parametrize("fail", [{"after": 5}, {"after": 5, "times": 1}, {"after": 1}])
@pytest.mark.parametrize("cap_req", [9, 10, 11, 40])
def test_429_dry_run_keeps_pages_and_retries_inside_caps(tmp_path, scratch_home, fail, cap_req):
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC],
               max_birdeye_requests=cap_req)
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    rec.fail_at = {BIRDEYE_TOKEN_TXS_PATH: dict(fail)}
    st = _state()
    try:
        asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    except SourceError as e:
        assert e.state in ("CAP_EXCEEDED", "RATE_LIMITED")
    store.close()
    assert len(rec.calls) <= cap_req, "more Birdeye calls than the cap"
    assert st["spend"]["birdeye_requests"] <= cap_req
    assert st["spend"]["birdeye_units"] <= cfg["caps"]["birdeye_units"]
    ok_pages = (st.get("seed_source_progress") or {}).get(SEED_TOKEN_INTERSECT, {}).get("paid_pages")
    if fail.get("after", 1) > 1:
        raw = Path(cfg["output_dir"]) / "raw/phase1/token-intersect.bin"
        assert raw.exists() and raw.stat().st_size > 2, "paid pages not kept"
        assert ok_pages and ok_pages >= fail["after"] - 1


def test_429_always_bounded_attempts_per_page(tmp_path, scratch_home):
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC])
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    rec.fail_at = {BIRDEYE_TOKEN_TXS_PATH: {"after": 1}}
    st = _state()
    with pytest.raises(SourceError):
        asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert len(rec.calls) == 1 + L.BIRDEYE_RATE_LIMIT_RETRIES


# ---------------------------------------------------------------- 5. --resume --phases 2 loads the phase-1 pool (CLI level)
def test_cli_resume_phase2_loads_pool(tmp_path, monkeypatch, scratch_home):
    orig = L.RecorderTransport.__init__

    def init(self):
        orig(self)
        self.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    monkeypatch.setattr(L.RecorderTransport, "__init__", init)
    out = tmp_path / "out"
    base = {"mode": "dry-run", "grant_path": str(ROOT / L.DRAFT_REL_13), "output_dir": str(out),
            "seed_source": "token_intersect", "birdeye_tokens": [JUP, BONK, USDC]}
    r1 = asyncio.run(L.run_live_e2e({**base, "phases": "1", "discovery": True, "wallets": ""}))
    st1 = json.loads((out / L.STATE_NAME).read_text())
    pool = st1["wallets"]
    assert pool, r1
    r2 = asyncio.run(L.run_live_e2e({**base, "phases": "2", "discovery": False, "wallets": "", "resume": True}))
    st2 = json.loads((out / L.STATE_NAME).read_text())
    assert set(st2.get("phase2") or {}) == set(pool), (r2, list(st2.get("phase2") or {}))
    assert 2 in st2["phases_done"]


# ---------------------------------------------------------------- 6. deepening never refetches paid pages
def test_deepen_resume_in_new_process_state_no_refetch(tmp_path, monkeypatch, scratch_home):
    fake = FakeHelius({W1: 12, W2: 3})
    monkeypatch.setattr(L, "_live_helius", fake)
    grant = _enabled_grant()
    cfg = _live_cfg(tmp_path, [W1, W2], 5)
    st = _state()
    st["wallets"] = [W1, W2]
    st["phase2"] = {a: {"address": a, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 100}
                    for a in (W1, W2)}
    st["bounds"] = cfg["bounds"]
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase3_history(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    first = list(fake.calls)
    assert sorted((a, p) for a, p, _ in first) == [(W1, 0), (W1, 1), (W2, 0), (W2, 1)]
    L.save_state(cfg["output_dir"], st)
    # new "process": reload state from disk, raise the cap
    st2 = json.loads((Path(cfg["output_dir"]) / L.STATE_NAME).read_text())
    cfg2 = _live_cfg(tmp_path, [W1, W2], 9)
    store, _ = open_grant_store(cfg2["authorization_id"])
    L.reconcile_state_spend(store, st2)
    asyncio.run(L.phase3_history(store, grant, cfg2, st2, L.RecorderTransport()))
    store.close()
    new = fake.calls[len(first):]
    assert not any((a, p) in {(x, y) for x, y, _ in first} for a, p, _ in new), f"refetched: {new}"
    assert sorted((a, p) for a, p, _ in new) == [(W1, 2), (W1, 3), (W1, 4), (W1, 5), (W2, 2)]
    assert st2["phase3"][W2]["history_complete"] is not False or st2["phase3"][W2].get("window_covered")
    # receipts: exactly one consumed receipt per (wallet, page)
    assert st2["spend"]["helius_requests"] == len(fake.calls)


def test_deepen_with_missing_raw_page_refuses_not_resends(tmp_path, monkeypatch, scratch_home):
    fake = FakeHelius({W1: 12})
    monkeypatch.setattr(L, "_live_helius", fake)
    grant = _enabled_grant()
    cfg = _live_cfg(tmp_path, [W1], 5)
    st = _state()
    st["wallets"] = [W1]
    st["phase2"] = {W1: {"address": W1, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 100}}
    st["bounds"] = cfg["bounds"]
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase3_history(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    n = len(fake.calls)
    # wipe the cursor (simulate state loss) and delete a paid page: must not re-send page 0/1
    st["phase3"] = {}
    (Path(cfg["output_dir"]) / f"raw/phase3/{W1}/page1.bin").unlink()
    cfg2 = _live_cfg(tmp_path, [W1], 7)
    store, _ = open_grant_store(cfg2["authorization_id"])
    try:
        asyncio.run(L.phase3_history(store, grant, cfg2, st, L.RecorderTransport()))
    except SourceError:
        pass
    store.close()
    resent = [c for c in fake.calls[n:] if c[1] in (0, 1)]
    assert not resent, f"re-sent paid pages: {resent}"


# ---------------------------------------------------------------- 7. free-space refusal before any paid request
def test_free_space_refusal_before_any_paid_request(tmp_path, monkeypatch):
    if not ARMED_13.exists():
        pytest.skip("armed copy not present")
    before = tree_hash(REAL_SCANNER)
    calls = []

    async def no_call(*a, **k):
        calls.append(a)
        raise AssertionError("paid transport reached")
    for name in ("_live_birdeye", "_live_helius", "_live_nansen"):
        monkeypatch.setattr(L, name, no_call)
    monkeypatch.setenv("HOME", "/home/box")
    monkeypatch.delenv("SCANNER_LIVE_LEDGER_HOME", raising=False)
    monkeypatch.delenv("SCANNER_LIVE_LEDGER_DIR", raising=False)
    monkeypatch.setenv("SCANNER_MIN_FREE_DISK_MB", str(10**9))
    for k in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "NANSEN_API_KEY"):
        monkeypatch.setenv(k, "dummy-not-a-key")
    with pytest.raises(L.LiveE2EError, match="Free disk space"):
        asyncio.run(L.run_live_e2e({"mode": "live", "grant_path": str(ARMED_13), "output_dir": str(tmp_path / "out"),
                                    "phases": "1", "discovery": True, "seed_source": "nansen", "wallets": ""}))
    assert not calls
    assert tree_hash(REAL_SCANNER) == before, "refused run still touched the real ledger"


# ---------------------------------------------------------------- 8. no secrets in repo; drafts disabled
def test_drafts_enabled_false():
    drafts = sorted((ROOT / "config").glob("live_authorization*draft*.json"))
    assert drafts
    for p in drafts:
        assert json.loads(p.read_text()).get("enabled") is False, p.name


def test_no_live_key_values_in_repo():
    keys = [v for v in (os.environ.get("REAL_KEYS_FOR_GREP_ONLY") or "").split("\n") if len(v) > 8]
    if not keys:
        pytest.skip("key values not provided to this process")
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_file() and ".venv" not in p.parts and "node_modules" not in p.parts and ".git" not in p.parts:
            b = p.read_bytes()
            if any(k.encode() in b for k in keys):
                hits.append(str(p.relative_to(ROOT)))
    assert not hits, f"{len(hits)} files contain a live key value"


def test_plan_has_no_retry_headroom_under_429(tmp_path, monkeypatch, scratch_home):
    """Documented caveat, not a cap breach: a retried 429 makes live runtime exceed the plan by the
    retries (plan 9, runtime 10). Caps still bind (see test_429_live_branch_*)."""
    fake = FakeBirdeye(_fx("token_txs_seek.json"), 5, 1)
    monkeypatch.setattr(L, "_live_birdeye", fake)
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC])
    cfg["dry_run"] = False
    plan = L.plan_request_counts(cfg, _state())
    store, _ = open_grant_store(cfg["authorization_id"])
    st = _state()
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    assert st["spend"]["birdeye_requests"] <= plan["totals"]["birdeye_requests"], (
        st["spend"]["birdeye_requests"], plan["totals"]["birdeye_requests"])


# ---------------------------------------------------------------- DS-3 (found during run 9): plan < runtime
@pytest.mark.parametrize("cap,in_window", [(16, 100), (12, 10), (40, 100)])
def test_ds3_phase3_plan_understates_runtime_when_cap_exceeds_density_estimate(tmp_path, monkeypatch, scratch_home, cap, in_window):
    """Runtime pages to per_wallet_cap (htf), but the plan is min(density estimate, cap headroom)."""
    pages = {W1: 50}
    fake = FakeHelius(pages)
    monkeypatch.setattr(L, "_live_helius", fake)
    cfg = _live_cfg(tmp_path, [W1], cap)
    st = _state()
    st["wallets"] = [W1]
    st["phase2"] = {W1: {"address": W1, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": in_window}}
    st["bounds"] = cfg["bounds"]
    plan = L.plan_request_counts(cfg, st)
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase3_history(store, _enabled_grant(), cfg, st, L.RecorderTransport()))
    store.close()
    assert len(fake.calls) <= cap - 3  # the per-wallet cap still binds
    assert st["spend"]["helius_requests"] <= plan["totals"]["helius_requests"], (
        "plan", plan["phase3_page_estimates"], "runtime", len(fake.calls))


# ---------------------------------------------------------------- DS-4 (found during run 9): triage double-count
def test_ds4_triage_source_spend_double_counts_for_explicit_wallets(tmp_path, monkeypatch, scratch_home):
    """--wallets seeds have no seed_source, so triage pages are booked to helius_triage twice."""
    fake = FakeHelius({W1: 1})
    monkeypatch.setattr(L, "_live_helius", fake)
    cfg = _live_cfg(tmp_path, [W1], 6, phases="2")
    cfg["seed_sources"] = ["token_intersect"]
    st = _state()
    st["wallets"] = [W1]
    st["bounds"] = cfg["bounds"]
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase2_prescreen(store, _enabled_grant(), cfg, st, L.RecorderTransport()))
    store.close()
    paid = len(fake.calls)
    booked = sum(int(v.get("requests") or 0) for v in (st.get("source_spend") or {}).values())
    assert paid == st["spend"]["helius_requests"]
    assert booked == paid, (paid, st.get("source_spend"))
