#!/usr/bin/env python3
"""Deliberate safety mutants. Each must make the named behavioral test fail.

Source is restored after every mutant. A syntax/import crash is not coverage.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable

MUTANTS = [
    {
        "id": "CERT-ledger-bind",
        "path": "scanner/mass_search/qualification_gates.py",
        "old": "    rows = list(ledger or [])\n    if not rows:\n        return False\n",
        "new": "    rows = list(ledger or [])\n    if not rows:\n        return True\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_empty_or_missing_ledger_is_non_certifying",
    },
    {
        "id": "STATE-evidence-class",
        "path": "scanner/mass_search/qualification_gates.py",
        "old": "    profile[\"evidence_class\"] = classify_evidence(report or {}, eval_profile)\n",
        "new": "    profile[\"evidence_class\"] = profile.get(\"evidence_class\") or classify_evidence(report or {}, eval_profile)\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_saved_decisions_rebuild_evidence_class_and_funnels",
    },
    {
        "id": "CAP-A-store-authority",
        "path": "scanner/mass_search/history_ingest.py",
        "old": "    if store is not None:\n        saved = store.get(NEXT_CAPTURE_STATE_KIND, (draft or {}).get(\"authorization_id\"))\n        if saved:\n            return saved\n        return empty_next_capture_state()\n    if state is not None:\n        return state\n",
        "new": "    if state is not None:\n        return state\n    if store is not None:\n        saved = store.get(NEXT_CAPTURE_STATE_KIND, (draft or {}).get(\"authorization_id\"))\n        if saved:\n            return saved\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_durable_store_ignores_stale_or_empty_supplied_state",
    },
    {
        "id": "CAP-B-progress-bind",
        "path": "scanner/mass_search/history_ingest.py",
        "old": "    if not previous_progress:\n        return previous_progress\n    if not replay_bound_to_last_dispatch(last_dispatch, replay_receipts):\n        return {\"named_dependency_observations\": []}\n",
        "new": "    if previous_progress is not None:\n        return previous_progress\n    if not replay_bound_to_last_dispatch(last_dispatch, replay_receipts):\n        return {\"named_dependency_observations\": []}\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_reservation_invalidates_last_dispatch_and_binds_progress",
    },
    {
        "id": "CAP-E-remaining",
        "path": "scanner/mass_search/history_ingest.py",
        "old": "        if remaining is None:\n            return refuse(\"quota_not_bound\", \"Remaining approved allowance is not a strict non-negative integer\")\n        if total_used >= remaining:\n            return refuse(\"quota_exhausted\", \"Remaining approved allowance is already consumed\")\n",
        "new": "        if remaining is None:\n            return refuse(\"quota_not_bound\", \"Remaining approved allowance is not a strict non-negative integer\")\n        if False and total_used >= remaining:\n            return refuse(\"quota_exhausted\", \"Remaining approved allowance is already consumed\")\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_remaining_quota_enforced_at_reservation",
    },
    {
        "id": "M4-keep-saved-funnel",
        "path": "scanner/mass_search/qualification_gates.py",
        "old": "    profile[\"funnel\"] = classify_candidate(\n",
        "new": "    profile[\"funnel\"] = profile.get(\"funnel\") or classify_candidate(\n",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_saved_decisions_rebuild_evidence_class_and_funnels",
    },
    {
        "id": "M9-receipt-page",
        "path": "scanner/mass_search/history_ingest.py",
        "old": "    if receipt.get(\"page_identity\") in (None, \"\"):\n        return False\n    required = (\"response_id\", \"page_identity\", \"address\", \"authorization_id\", \"attempt\")\n",
        "new": "    required = (\"response_id\", \"address\", \"authorization_id\", \"attempt\")\n",
        "test": "tests/test_grok_bot_2fe60bd_repros.py::test_b6_page_less_receipt_is_single_use_and_bound",
    },
    {
        "id": "JS2-contradictory-representation",
        "path": "frontend/src/format.ts",
        "old": "    if (left.length !== right.length || left.some((key, index) => key !== right[index])) return null;\n    return listed;",
        "new": "    return listed;",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_mounted_component_trees_reject_invalid_and_stale_payloads",
    },
    {
        "id": "JS4-headline-units",
        "path": "frontend/src/format.ts",
        "old": "    && (!profileUnit || !auditorUnit || profileUnit === auditorUnit)",
        "new": "",
        "test": "tests/test_chatgpt_review_2026_10_07_0842.py::test_mounted_component_trees_reject_invalid_and_stale_payloads",
    },
]


def apply(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"mutant site missing in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main():
    snapshots = {mutant["path"]: (ROOT / mutant["path"]).read_text(encoding="utf-8") for mutant in MUTANTS}
    results = []
    failed = False
    for mutant in MUTANTS:
        path = ROOT / mutant["path"]
        path.write_text(snapshots[mutant["path"]], encoding="utf-8")
        apply(path, mutant["old"], mutant["new"])
        try:
            proc = subprocess.run(
                [PYTHON, "-m", "pytest", "-q", "--tb=no", mutant["test"]],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            caught = proc.returncode != 0
            if not caught:
                failed = True
            results.append({"id": mutant["id"], "caught": caught, "exit": proc.returncode})
            print(f"{mutant['id']}: {'caught' if caught else 'MISSED'}")
        finally:
            path.write_text(snapshots[mutant["path"]], encoding="utf-8")
    if failed:
        print("safety mutant missed", file=sys.stderr)
        return 1
    print(json_dumps(results))
    return 0


def json_dumps(value):
    import json
    return json.dumps(value)


if __name__ == "__main__":
    raise SystemExit(main())
