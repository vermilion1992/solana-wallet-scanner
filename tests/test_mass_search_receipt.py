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


def test_recorded_g4_receipt_stays_synthetic_and_incomplete_for_live():
    evidence = Path(__file__).resolve().parents[1] / "evidence" / "mass-wallet-funnel"
    receipt = evidence / "ee7c645a3a7b499bb150b1ac84b96ced" / "receipt.json"
    checker = PACKAGE / "tools" / "check_receipt_contract.py"
    payload = json.loads(receipt.read_text())
    assert payload["corpus_kind"] == "SYNTHETIC"
    assert payload["claims"]["strict_full_wallet_ready"] is False
    assert payload["budget"]["live_authorized"] is False
    development = subprocess.run(
        [sys.executable, str(checker), str(receipt), "--profile", "development",
         "--evidence-root", str(receipt.parent)],
        cwd=PACKAGE, capture_output=True, text=True,
    )
    live = subprocess.run(
        [sys.executable, str(checker), str(receipt), "--profile", "live-search",
         "--evidence-root", str(receipt.parent)],
        cwd=PACKAGE, capture_output=True, text=True,
    )
    assert development.returncode == 0, development.stdout + development.stderr
    assert json.loads(development.stdout)["state"] == "CONTRACT_VALID"
    assert live.returncode == 2
    assert json.loads(live.stdout)["state"] == "INCOMPLETE"
