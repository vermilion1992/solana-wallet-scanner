"""D11-1..4 fold. Offline only. PRODUCT_READY stays false."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scanner.mass_search.live_e2e import (
    DRAFT_PATH,
    discovered_seed_pool,
    load_committed_draft,
    phase3_wallets,
    phase4_targets,
    plan_request_counts,
    unscreened_address_set,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import _read_draft_bytes, committed_draft_payload
from scanner.mass_search.qualification_gates import (
    HISTORY_AGE_RULE,
    HISTORY_AGE_RULE_HELIUS,
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
)
from scanner.mass_search.seed_sources import nansen_dex_trades_drop

ROOT = Path(__file__).resolve().parents[1]
WALLET_A = "D11aWallet1111111111111111111111111111112"
WALLET_B = "D11bWallet1111111111111111111111111111112"
# 9T546u: Nansen coverage from 2026-08-17; Helius first sig 2026-07-05.
NANSEN_LATE = int(datetime(2026, 8, 17, tzinfo=timezone.utc).timestamp())
HELIUS_EARLY = int(datetime(2026, 7, 5, tzinfo=timezone.utc).timestamp())
NOW = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
DRAFT_REL = "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"


def test_d11_1_live_e2e_calibrate_plan_is_dex_not_leaderboard(tmp_path):
    wallets = tmp_path / "calibrate.json"
    wallets.write_text(
        '[{"address": "%s", "label": "bot"}, {"address": "%s", "label": "human"}]\n'
        % (WALLET_A, WALLET_B),
        encoding="utf-8",
    )
    cfg = validate_config({
        "mode": "dry-run",
        "grant_path": DRAFT_PATH,
        "output_dir": tmp_path / "out",
        "phases": "1",
        "nansen_calibrate_wallets": str(wallets),
        "nansen_dex_trades_max_pages": 3,
        "window_days": 30,
        "earlier_history_days": 60,
    })
    cfg["nansen_enabled"] = True
    cfg["caps"] = {**cfg["caps"], "nansen_requests": 200, "nansen_units": 400}
    plan = plan_request_counts(cfg)
    nansen = ((plan.get("seed_plan") or {}).get("per_source") or {}).get("nansen") or {}
    assert nansen["calibration"] is True
    assert nansen["leaderboard_requests"] == 0
    assert nansen["dex_trades_requests"] == 6
    assert nansen["requests"] >= nansen["dex_trades_requests"]
    assert plan["PRODUCT_READY"] is False


def test_d11_2_file_tree_when_git_unavailable(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("No such file or directory: 'git'")

    monkeypatch.setattr("subprocess.run", boom)
    raw, source = _read_draft_bytes(DRAFT_REL, repo_root=ROOT)
    assert source == "file_tree"
    assert raw
    payload, digest = committed_draft_payload(DRAFT_REL, repo_root=ROOT)
    assert payload.get("authorization_id")
    assert payload.get("schema_version")
    pin = payload.get("pinned_ledger_home")
    if pin:
        assert Path(str(pin)).is_absolute()
    assert len(digest) == 64


def test_d11_2_missing_draft_names_file_tree_not_pin(tmp_path):
    with pytest.raises(ValueError, match="file tree also missing") as err:
        _read_draft_bytes("config/does-not-exist-draft.json", repo_root=tmp_path)
    assert "pinned_ledger_home must be an absolute path" not in str(err.value)
    with pytest.raises(Exception, match="file tree|could not be read|draft blob missing") as live_err:
        load_committed_draft("config/does-not-exist-draft.json")
    assert "pinned_ledger_home must be an absolute path" not in str(live_err.value)


def test_d11_3_unscreened_stay_out_of_downstream():
    state = {
        "wallets": [WALLET_A, WALLET_B],
        "unscreened_wallets": [{"address": WALLET_B, "reason": "cap_reached", "screen": "nansen_dex_trades"}],
        "phase2": {
            WALLET_A: {"address": WALLET_A, "dropped": False},
            WALLET_B: {"address": WALLET_B, "dropped": False},
        },
        "phase3": {
            WALLET_A: {"done": True},
            WALLET_B: {"done": True},
        },
        "discoveries": {"x": {"addresses": [WALLET_A, WALLET_B]}},
    }
    assert unscreened_address_set(state) == {WALLET_B}
    cfg = {"wallets": [WALLET_A, WALLET_B], "wallets_supplied": False, "readable_first": False}
    assert WALLET_B not in discovered_seed_pool(cfg, state)
    assert phase3_wallets(cfg, state) == [WALLET_A]
    assert WALLET_B not in phase4_targets(cfg, state)


def test_d11_4_nansen_late_coverage_does_not_age_drop():
    assert HISTORY_AGE_RULE == "off"
    # 9T546u shape: Nansen first seen 2026-08-17 (~52d), Helius from 2026-07-05.
    stats = {"max_per_day": 3, "busiest_day": "2026-09-01", "earliest_unix": NANSEN_LATE}
    default = nansen_dex_trades_drop(stats, now_unix=NOW)
    assert default["dropped"] is False
    helius_old = nansen_dex_trades_drop(
        stats,
        now_unix=NOW,
        helius_first_sig_unix=HELIUS_EARLY,
        age_rule=HISTORY_AGE_RULE_HELIUS,
    )
    assert helius_old["dropped"] is False
    helius_new = nansen_dex_trades_drop(
        stats,
        now_unix=NOW,
        helius_first_sig_unix=NOW - 10 * 86400,
        age_rule=HISTORY_AGE_RULE_HELIUS,
    )
    assert helius_new["dropped"] is True
    assert any("history_lt" in reason for reason in helius_new["drop_reasons"])
    busy = nansen_dex_trades_drop(
        {"max_per_day": MAX_ECONOMIC_TRADES_PER_UTC_DAY + 1, "busiest_day": "2026-01-01", "earliest_unix": NANSEN_LATE},
        now_unix=NOW,
    )
    assert busy["dropped"] is True
    assert busy["can_only_drop"] is True
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 15
