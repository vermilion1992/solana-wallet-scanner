"""Replay Phase 3/4 on every cached raw-page set at $0.

No provider calls. Keys must stay unset. Lists early_watch and proven
wallets so a later re-run can promote 1–2 episode watches automatically.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_16,
    _verify_saved_page,
    page_sort_key,
    phase4_offline,
    window_bounds,
)
from scanner.mass_search.research_profile import early_watch_label
from scanner.storage import Store

FORBIDDEN_ENV = (
    "HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_API_KEYS",
    "HELIUS_RPC_URL", "NANSEN_API_KEY",
)
DEFAULT_CACHE_ROOTS = (
    Path("/tmp/live-raw-f635a45/live-out/main/raw"),
    Path("/tmp/live-raw-06cea26/live-out/main/raw"),
    Path("/tmp/live-raw-both/live-e2e-cfe6e78/live-out/raw"),
    Path("/tmp/live-raw-both/live-e2e-bbc5bef/live-out/raw"),
    Path("/tmp/live-raw-4bbb364-a"),
    Path("/tmp/live-raw-4bbb364-b"),
    Path("/tmp/live-raw-df3278c/live-out/main/raw"),
    Path("/tmp/live_raw_affc623_dflow_top/runs/run7_affc623/raw"),
    Path("/tmp/live_raw_affc623_repro/runs/run7_affc623/raw"),
    Path("/tmp/live_raw_affc623_repro/runs/run_4bbb364/raw"),
    Path("/tmp/live_raw_affc623_repro/runs/run_f635a45/raw"),
    ROOT / "tests/fixtures/live-raw",
)
PROVEN = frozenset({"provisional_research_lead", "stronger_research_shortlist"})


def assert_offline():
    leaked = [key for key in FORBIDDEN_ENV if os.environ.get(key)]
    if leaked:
        raise SystemExit(f"refusing to run with provider env set: {leaked}")


def discover_cached_wallets(roots=None):
    """Map address → list of directories that hold page*.bin."""
    found = {}
    for root in roots or DEFAULT_CACHE_ROOTS:
        root = Path(root)
        if not root.exists():
            continue
        candidates = []
        if (root / "phase3").is_dir():
            candidates.append(root / "phase3")
        if any(root.glob("*/page*.bin")):
            candidates.append(root)
        if any(root.glob("*/**/page*.bin")):
            for wallet_dir in root.rglob("page0.bin"):
                candidates.append(wallet_dir.parent)
        for parent in candidates:
            if not parent.is_dir():
                continue
            if any(parent.glob("page*.bin")):
                found.setdefault(parent.name, []).append(parent)
                continue
            for wallet_dir in parent.iterdir():
                if wallet_dir.is_dir() and any(wallet_dir.glob("page*.bin")):
                    found.setdefault(wallet_dir.name, []).append(wallet_dir)
    return found


def _stage_pages(dest_root, address, wallet_dirs):
    dest = Path(dest_root) / "raw" / "phase3" / address
    dest.mkdir(parents=True, exist_ok=True)
    pages = []
    leftover = False
    for wallet_dir in wallet_dirs:
        for path in sorted(Path(wallet_dir).glob("page*.bin"), key=page_sort_key):
            target = dest / path.name
            if not target.exists():
                shutil.copy2(path, target)
            pages.append(target)
            try:
                _raw, _data, token = _verify_saved_page(path, f"{wallet_dir}/{path.name}")
            except Exception:
                continue
            leftover = leftover or bool(token)
    return dest, pages, leftover


def replay_cached_pages(output_dir, *, roots=None, report_window_days=30):
    """Re-run Phase 4 on every cached raw-page set. Spends $0."""
    assert_offline()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    found = discover_cached_wallets(roots)
    end = datetime.now(timezone.utc)
    bounds = window_bounds(30, 60, end=end, history_to_first=True, report_window_days=report_window_days)
    state = {"bounds": bounds, "phase3": {}, "run_spend": {}}
    wallets = []
    for address, dirs in sorted(found.items()):
        dest, pages, leftover = _stage_pages(output_dir, address, dirs)
        if not pages:
            continue
        wallets.append(address)
        state["phase3"][address] = {
            "pages": len(pages),
            "done": True,
            "pagination_token": leftover,
            "leftover_pagination_token": leftover,
        }
    store = Store(output_dir / "offline-replay-ledger")
    try:
        result = phase4_offline(
            store,
            {
                "bounds": bounds,
                "output_dir": str(output_dir),
                "wallets": wallets,
                "phases": (4,),
                "authorization_id": AUTHORIZATION_ID_16,
                "PRODUCT_READY": False,
            },
            state,
        )
    finally:
        store.close()
    rows = list((result or {}).get("wallets") or [])
    early = []
    proven = []
    for row in rows:
        level = row.get("lead_level") or ((row.get("qualification_level") or {}).get("level"))
        address = row.get("address")
        completed = int(row.get("completed_known_cost_positions") or row.get("completed_trades") or 0)
        if level == "early_watch":
            early.append({
                "address": address,
                "label": early_watch_label(completed or 1),
                "completed": completed,
                "net": row.get("realized_pnl_sol") or row.get("realized_pnl_usdc") or row.get("completed_episode_net"),
            })
        elif level in PROVEN:
            proven.append({
                "address": address,
                "level": level,
                "completed": completed,
                "net": row.get("realized_pnl_sol") or row.get("realized_pnl_usdc") or row.get("completed_episode_net"),
            })
    payload = {
        "kind": "offline-replay-cached-v1",
        "wallets_examined": len(wallets),
        "early_watch": early,
        "proven": proven,
        "spend_usd": "0",
        "PRODUCT_READY": False,
        "never_a_pass": True,
    }
    (output_dir / "OFFLINE_REPLAY.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    lines = [
        "# Offline replay ($0)",
        "",
        f"Examined: {len(wallets)}",
        f"Early watch: {len(early)}",
        f"Proven: {len(proven)}",
        "",
        "## Early watch – not proven",
        "",
    ]
    for row in early:
        lines.append(f"- {row['address']}: {row['label']}")
    lines.extend(["", "## Proven", ""])
    for row in proven:
        lines.append(f"- {row['address']}: {row['level']}")
    if not proven:
        lines.append("- none")
    lines.append("")
    text = "\n".join(lines)
    (output_dir / "OFFLINE_REPLAY.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return payload


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    output = Path(argv[0]) if argv else Path("/tmp/offline-replay-cached")
    extra_roots = [Path(item) for item in argv[1:]] or None
    return replay_cached_pages(output, roots=extra_roots)


if __name__ == "__main__":
    main()
