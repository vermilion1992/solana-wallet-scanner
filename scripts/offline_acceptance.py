#!/usr/bin/env python3
"""Offline invariant acceptance entry point.

Never enables capture, never reads provider secrets, never makes network calls.
Exits nonzero on failure or if a mandatory check is skipped.

Usage (from repo root):

    .venv/bin/python scripts/offline_acceptance.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06"
OUT = EVIDENCE / "offline-acceptance"
DRAFT = ROOT / "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"
LIVE_E2E_DRAFT = ROOT / "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json"
LIVE_E2E_DRAFT_NEXT = ROOT / "config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json"
LIVE_E2E_DRAFT_11 = ROOT / "config/live_authorization.live-e2e-proof-2026-10-11-mitch-draft.json"
LIVE_E2E_DRAFT_12 = ROOT / "config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json"
LIVE_E2E_DRAFT_13 = ROOT / "config/live_authorization.live-e2e-proof-2026-10-13-mitch-draft.json"
MANDATORY = [
    "tests/test_chatgpt_review_2026_10_07.py",
    "tests/test_chatgpt_review_2026_10_07_rereview.py",
    "tests/test_chatgpt_review_2026_10_07_0547.py",
    "tests/test_chatgpt_review_2026_10_07_0714.py",
    "tests/test_chatgpt_review_2026_10_07_0842.py",
    "tests/test_adversarial_0842_named_counterexamples.py",
    "tests/test_mass_search_mitch_requirements.py",
    "tests/test_grok_bot_2fe60bd_repros.py",
    "tests/test_live_e2e_filters_and_runner.py",
    "tests/test_live_e2e_spend_safety.py",
    "tests/test_live_e2e_live_result_fixes.py",
    "tests/test_live_e2e_bbc5bef_residuals.py",
    "tests/test_live_e2e_06cea26_residuals.py",
    "tests/test_live_e2e_f635a45_residuals.py",
    "tests/test_live_e2e_4bbb364_residuals.py",
    "tests/test_live_e2e_df3278c_residuals.py",
    "tests/test_live_e2e_venue_decode.py",
    "tests/test_live_e2e_affc623_s9.py",
    "tests/test_live_e2e_d1_d9.py",
    "tests/test_bot_rate_lead_gate.py",
    "tests/test_live_e2e_seed_sources.py",
]
FORBIDDEN_ENV = ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_API_KEYS", "HELIUS_RPC_URL", "NANSEN_API_KEY")


def _run(command, log_path, env):
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    return proc


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw = OUT / f"RAW_{stamp}.log"
    result_path = OUT / "RESULT.json"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in FORBIDDEN_ENV
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    if draft.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if draft.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "product_ready"}, indent=2), encoding="utf-8")
        return 2
    live_e2e = json.loads(LIVE_E2E_DRAFT.read_text(encoding="utf-8"))
    if live_e2e.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if live_e2e.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_product_ready"}, indent=2), encoding="utf-8")
        return 2
    live_e2e_next = json.loads(LIVE_E2E_DRAFT_NEXT.read_text(encoding="utf-8"))
    if live_e2e_next.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_next_draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if live_e2e_next.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_next_product_ready"}, indent=2), encoding="utf-8")
        return 2
    live_e2e_11 = json.loads(LIVE_E2E_DRAFT_11.read_text(encoding="utf-8"))
    if live_e2e_11.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_11_draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if live_e2e_11.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_11_product_ready"}, indent=2), encoding="utf-8")
        return 2
    live_e2e_12 = json.loads(LIVE_E2E_DRAFT_12.read_text(encoding="utf-8"))
    if live_e2e_12.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_12_draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if live_e2e_12.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_12_product_ready"}, indent=2), encoding="utf-8")
        return 2
    live_e2e_13 = json.loads(LIVE_E2E_DRAFT_13.read_text(encoding="utf-8"))
    if live_e2e_13.get("enabled") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_13_draft_enabled"}, indent=2), encoding="utf-8")
        return 2
    if live_e2e_13.get("PRODUCT_READY") is not False:
        result_path.write_text(json.dumps({"ok": False, "error": "live_e2e_13_product_ready"}, indent=2), encoding="utf-8")
        return 2

    steps = []
    failed = False
    skipped_mandatory = False

    pytest_cmd = [
        python, "-m", "pytest", "-q", "--tb=line",
        "-p", "no:cacheprovider",
        *MANDATORY,
    ]
    pytest_log = OUT / f"PYTEST_{stamp}.log"
    pytest_run = _run(pytest_cmd, pytest_log, env)
    text = pytest_log.read_text(encoding="utf-8")
    skipped = "skipped" in text.lower() and " skipped" in f" {text.lower()}"
    if pytest_run.returncode != 0:
        failed = True
    if "skipped" in text and pytest_run.returncode == 0:
        # pytest summary line like "N skipped"
        for token in text.split():
            if token.endswith("skipped") or token == "skipped":
                skipped_mandatory = True
    steps.append({
        "name": "invariant_pytest",
        "command": pytest_cmd,
        "exit": pytest_run.returncode,
        "log": str(pytest_log.relative_to(ROOT)),
        "mandatory": True,
    })

    from tests.test_grok_bot_2fe60bd_repros import frontend_smoke_cases

    cases_path = OUT / "mounted-cases.json"
    cases = frontend_smoke_cases()
    if not cases or "valid" not in cases or "headline999" not in cases:
        result_path.write_text(json.dumps({"ok": False, "error": "mounted_cases_missing"}, indent=2), encoding="utf-8")
        return 2
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    node_cmd = [
        "node", "--experimental-strip-types",
        str(ROOT / "frontend/scripts/assert-rereview-0842.mts"),
        str(cases_path),
    ]
    node_log = OUT / f"NODE_{stamp}.log"
    node_run = _run(node_cmd, node_log, env)
    if node_run.returncode != 0:
        failed = True
    steps.append({
        "name": "mounted_component_smoke",
        "command": node_cmd,
        "exit": node_run.returncode,
        "log": str(node_log.relative_to(ROOT)),
        "mandatory": True,
    })

    mutant_cmd = [python, str(ROOT / "scripts/verify_safety_mutants.py")]
    mutant_log = OUT / f"MUTANTS_{stamp}.log"
    mutant_run = _run(mutant_cmd, mutant_log, env)
    if mutant_run.returncode != 0:
        failed = True
    steps.append({
        "name": "safety_mutants",
        "command": mutant_cmd,
        "exit": mutant_run.returncode,
        "log": str(mutant_log.relative_to(ROOT)),
        "mandatory": True,
    })

    payload = {
        "kind": "offline-invariant-acceptance-v1",
        "ok": not failed and not skipped_mandatory,
        "skipped_mandatory": skipped_mandatory,
        "PRODUCT_READY": False,
        "draft_enabled": False,
        "provider_env_cleared": list(FORBIDDEN_ENV),
        "steps": steps,
        "pytest_log_excerpt": text[-800:],
        "created_at": stamp,
    }
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    raw.write_text(json.dumps(payload, indent=2) + "\n\n" + text, encoding="utf-8")
    if failed or skipped_mandatory:
        print(json.dumps({"ok": False, "result": str(result_path)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "result": str(result_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
