"""Package receipt checker stays a structural guard, not live proof."""
import json
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "work_packages" / "mass_wallet_search_v1"


def test_synthetic_receipt_is_incomplete_for_live_profile():
    receipt = PACKAGE / "fixtures" / "receipt.synthetic.example.json"
    checker = PACKAGE / "tools" / "check_receipt_contract.py"
    completed = subprocess.run(
        [sys.executable, str(checker), str(receipt), "--profile", "live-search"],
        cwd=PACKAGE, capture_output=True, text=True,
    )
    assert completed.returncode == 2
    development = subprocess.run(
        [sys.executable, str(checker), str(receipt), "--profile", "development"],
        cwd=PACKAGE, capture_output=True, text=True,
    )
    assert development.returncode == 0
    payload = json.loads(receipt.read_text())
    assert payload["corpus_kind"] == "SYNTHETIC"
    assert payload["claims"]["strict_full_wallet_ready"] is False
