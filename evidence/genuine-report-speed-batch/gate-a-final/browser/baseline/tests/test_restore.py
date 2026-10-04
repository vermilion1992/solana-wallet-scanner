"""Backups restore data faithfully without creating traversal or overwrite paths."""
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from scanner.restore import RestoreError, restore_backup


def backup_fixture(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    db = sqlite3.connect(backup / "scanner.sqlite")
    db.execute("CREATE TABLE records (value TEXT)")
    db.execute("INSERT INTO records VALUES ('saved report')")
    db.commit()
    db.close()
    evidence = json.dumps({"signature": "verified"}, sort_keys=True).encode()
    name = f"evidence/{hashlib.sha256(evidence).hexdigest()}.json.gz"
    (backup / "evidence").mkdir()
    (backup / name).write_bytes(gzip.compress(evidence, mtime=0))
    files = {name: hashlib.sha256((backup / name).read_bytes()).hexdigest(),
             "scanner.sqlite": hashlib.sha256((backup / "scanner.sqlite").read_bytes()).hexdigest()}
    (backup / "manifest.json").write_text(json.dumps({"version": 1, "files": files}))
    return backup


@pytest.mark.parametrize("zipped", [False, True])
def test_restores_verified_data_to_new_destination(tmp_path, zipped):
    backup = backup_fixture(tmp_path)
    source = backup
    if zipped:
        source = tmp_path / "backup.zip"
        with zipfile.ZipFile(source, "w") as archive:
            for path in backup.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(backup).as_posix())
    restored = restore_backup(source, tmp_path / "restored")
    db = sqlite3.connect(restored / "scanner.sqlite")
    try:
        assert db.execute("SELECT value FROM records").fetchone()[0] == "saved report"
    finally:
        db.close()
    evidence_name = next((backup / "evidence").iterdir()).name
    assert (restored / "evidence" / evidence_name).read_bytes() == (backup / "evidence" / evidence_name).read_bytes()


def test_refuses_existing_data_and_preserves_it(tmp_path):
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "active"
    destination.mkdir()
    live = destination / "scanner.sqlite"
    live.write_bytes(b"live data")
    with pytest.raises(RestoreError, match="never overwritten"):
        restore_backup(backup, destination)
    assert live.read_bytes() == b"live data"


def test_checksum_failure_leaves_no_partial_restore(tmp_path):
    backup = backup_fixture(tmp_path)
    (backup / "scanner.sqlite").write_bytes(b"corrupted")
    destination = tmp_path / "restored"
    with pytest.raises(RestoreError, match="Checksum mismatch"):
        restore_backup(backup, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".scanner-restore-*"))


def test_rejects_manifest_traversal(tmp_path):
    backup = backup_fixture(tmp_path)
    manifest = json.loads((backup / "manifest.json").read_text())
    manifest["files"]["../outside.txt"] = "0" * 64
    (backup / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RestoreError, match="Unsafe"):
        restore_backup(backup, tmp_path / "restored")
    assert not (tmp_path.parent / "outside.txt").exists()


def test_rejects_zip_traversal_even_if_not_in_manifest(tmp_path):
    backup = backup_fixture(tmp_path)
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.write(backup / "manifest.json", "manifest.json")
        archive.writestr("../outside.txt", b"unsafe")
    with pytest.raises(RestoreError, match="Unsafe"):
        restore_backup(source, tmp_path / "restored")
    assert not (tmp_path / "outside.txt").exists()


def test_rejects_symlinked_backup_files(tmp_path):
    backup = backup_fixture(tmp_path)
    database = backup / "scanner.sqlite"
    other = tmp_path / "outside.sqlite"
    database.rename(other)
    try:
        database.symlink_to(other)
    except OSError:
        pytest.skip("symbolic links unavailable on this platform")
    with pytest.raises(RestoreError, match="Symbolic links"):
        restore_backup(backup, tmp_path / "restored")


def test_rejects_duplicate_manifest_keys(tmp_path):
    backup = backup_fixture(tmp_path)
    (backup / "manifest.json").write_text('{"version":1,"version":1,"files":{}}')
    with pytest.raises(RestoreError, match="Duplicate manifest"):
        restore_backup(backup, tmp_path / "restored")


def test_restores_into_existing_empty_directory(tmp_path):
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "restored"
    destination.mkdir()
    assert restore_backup(backup, destination) == destination
    assert (destination / "scanner.sqlite").exists()
