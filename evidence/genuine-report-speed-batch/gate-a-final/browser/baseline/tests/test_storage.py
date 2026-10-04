"""Durable quota conservation and evidence integrity without provider traffic."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import sqlite3

import pytest

from scanner.storage import EvidenceError, QuotaExceeded, Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def test_quota_pending_dispatch_charge_and_release_conserve_headroom(store):
    first = store.reserve("helius", "getTransaction", 3, "cycle-a", 10)
    second = store.reserve("helius", "getSlot", 4, "cycle-a", 10)
    assert store.usage("helius", "cycle-a", 10) == {
        "used": 0, "reserved": 7, "cap": 10, "remaining": 3, "cycle_start": "cycle-a"}
    store.dispatch(first)
    assert store.usage("helius", "cycle-a", 10)["used"] == 3
    assert store.usage("helius", "cycle-a", 10)["reserved"] == 4
    with pytest.raises(ValueError, match="undispatched"):
        store.release(first)
    with pytest.raises(ValueError, match="conservatively charged"):
        store.settle(first, charge=False)
    store.settle(first)
    store.release(second)
    usage = store.usage("helius", "cycle-a", 10)
    assert (usage["used"], usage["reserved"], usage["remaining"]) == (3, 0, 7)
    assert store.usage("helius", "cycle-b", 10)["remaining"] == 10
    with pytest.raises(ValueError):
        store.dispatch(first)
    with pytest.raises(ValueError):
        store.settle(first)


def test_restart_retains_pending_and_in_flight_quota(tmp_path):
    path = tmp_path / "data"
    instance = Store(path)
    pending = instance.reserve("helius", "getSlot", 2, "cycle", 6)
    dispatched = instance.reserve("helius", "getTransaction", 3, "cycle", 6)
    instance.dispatch(dispatched)
    instance.close()
    reopened = Store(path)
    try:
        usage = reopened.usage("helius", "cycle", 6)
        assert (usage["used"], usage["reserved"], usage["remaining"]) == (3, 2, 1)
        with pytest.raises(QuotaExceeded):
            reopened.reserve("helius", "getTransaction", 2, "cycle", 6)
        reopened.release(pending)
        reopened.settle(dispatched)
        assert reopened.usage("helius", "cycle", 6)["remaining"] == 3
    finally:
        reopened.close()


def test_concurrent_reservations_cannot_overspend(store):
    def attempt(_):
        try:
            return store.reserve("helius", "getTransaction", 3, "cycle", 10)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(attempt, range(40)))
    assert sum(item is not None for item in outcomes) == 3
    assert store.usage("helius", "cycle", 10)["remaining"] == 1
    assert store.usage("helius", "cycle", 10)["reserved"] == 9


@pytest.mark.parametrize("cost,cap", [(True, 10), (0, 10), (-1, 10), (1.5, 10), (1, False), (1, 0)])
def test_invalid_quota_inputs_create_no_reservation(store, cost, cap):
    with pytest.raises(ValueError):
        store.reserve("helius", "getSlot", cost, "cycle", cap)
    assert store.usage("helius", "cycle", 10)["reserved"] == 0


def test_undispatched_cancel_can_be_settled_without_charge(store):
    reservation = store.reserve("helius", "getSlot", 1, "cycle", 10)
    store.settle(reservation, charge=False)
    assert store.usage("helius", "cycle", 10)["remaining"] == 10
    with pytest.raises(ValueError):
        store.release(reservation)


def test_evidence_is_content_addressed_and_deduplicated(store):
    payload = {"signature": "fixture", "raw": {"z": 2, "a": 1}}
    digest = store.archive(payload)
    assert digest == store.archive({"raw": {"a": 1, "z": 2}, "signature": "fixture"})
    assert store.evidence(digest) == payload
    assert store.stats()["evidence_files"] == 1
    assert len(store.list("artifacts")) == 1
    assert not list((store.path / "evidence").glob(".archive-*"))


def test_concurrent_evidence_archive_has_one_verified_artifact(store):
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: store.archive({"same": "record"}), range(24)))
    assert len(set(results)) == 1
    assert store.evidence(results[0]) == {"same": "record"}
    assert store.stats()["evidence_files"] == 1


@pytest.mark.parametrize("digest", ["../scanner.sqlite", "A" * 64, "0" * 63, None])
def test_evidence_identifier_cannot_traverse_storage(store, digest):
    with pytest.raises(EvidenceError, match="Invalid evidence"):
        store.evidence(digest)


def test_replaced_evidence_is_rejected_and_not_silently_overwritten(store):
    payload = {"value": "original"}
    digest = store.archive(payload)
    location = store.path / "evidence" / f"{digest}.json.gz"
    location.write_bytes(gzip.compress(b'{"value":"changed"}'))
    with pytest.raises(EvidenceError, match="checksum"):
        store.evidence(digest)
    with pytest.raises(EvidenceError, match="checksum"):
        store.archive(payload)


@pytest.mark.parametrize("broken", [b"not gzip", b"\x1f\x8b\x08\x00" + b"\0" * 6 + b"\x07" + b"\0" * 8])
def test_malformed_compression_reports_integrity_error(store, broken):
    digest = store.archive({"value": "original"})
    (store.path / "evidence" / f"{digest}.json.gz").write_bytes(broken)
    with pytest.raises(EvidenceError, match="unreadable"):
        store.evidence(digest)


def test_backup_captures_wal_data_and_all_checksum_verified_evidence(store):
    digest = store.archive({"signature": "synthetic"})
    store.put("reports", "r1", {"id": "r1", "evidence": [digest]})
    backup = store.backup()
    from pathlib import Path
    path = Path(backup["path"])
    manifest = json.loads((path / "manifest.json").read_text())
    assert manifest["version"] == 1
    assert set(manifest["files"]) == {"scanner.sqlite", f"evidence/{digest}.json.gz"}
    for name, checksum in manifest["files"].items():
        assert hashlib.sha256((path / name).read_bytes()).hexdigest() == checksum
    db = sqlite3.connect(path / "scanner.sqlite")
    try:
        payload = db.execute("SELECT payload FROM records WHERE kind='reports' AND id='r1'").fetchone()[0]
        assert json.loads(payload)["evidence"] == [digest]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()
    store.put("reports", "r1", {"id": "r1", "new": True})
    assert "new" not in json.loads(payload)


def test_backup_refuses_corrupt_evidence(store):
    digest = store.archive({"signature": "synthetic"})
    (store.path / "evidence" / f"{digest}.json.gz").write_bytes(b"damaged")
    with pytest.raises(EvidenceError):
        store.backup()


def test_nonfinite_json_cannot_enter_database_or_evidence(store):
    with pytest.raises(ValueError):
        store.put("reports", "bad", {"value": float("nan")})
    with pytest.raises(ValueError):
        store.archive({"value": float("inf")})
    assert store.get("reports", "bad") is None
    assert store.stats()["evidence_files"] == 0
