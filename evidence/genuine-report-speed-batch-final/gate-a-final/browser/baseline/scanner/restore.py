"""Verify and restore a backup into a new, empty data directory.

This command never overwrites an active data directory. Both the directory
format emitted by Store.backup() and ZIPs of that directory's contents work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from urllib.parse import quote
import zipfile

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_BACKUP_BYTES = 16 * 1024 * 1024 * 1024
MAX_FILES = 100_000
FILE_PATH = re.compile(r"(?:scanner\.sqlite|evidence/[a-f0-9]{64}\.json\.gz)\Z")
CHECKSUM = re.compile(r"[a-f0-9]{64}\Z")


class RestoreError(ValueError):
    """A backup cannot be safely restored."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RestoreError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def _manifest(encoded: bytes) -> dict:
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise RestoreError("Backup manifest is too large")
    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RestoreError("Backup manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise RestoreError("Unsupported backup manifest version")
    files = value.get("files")
    if not isinstance(files, dict) or "scanner.sqlite" not in files or len(files) > MAX_FILES:
        raise RestoreError("Manifest must list scanner.sqlite and a bounded set of evidence files")
    for name, checksum in files.items():
        if not isinstance(name, str) or not FILE_PATH.fullmatch(name):
            raise RestoreError(f"Unsafe or unsupported backup path: {name}")
        if not isinstance(checksum, str) or not CHECKSUM.fullmatch(checksum):
            raise RestoreError(f"Invalid SHA-256 checksum for {name}")
    return value


@contextmanager
def _open_backup(source: Path):
    if source.is_symlink():
        raise RestoreError("Backup source must not be a symbolic link")
    if source.is_dir():
        manifest_path = source / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RestoreError("Backup directory requires a regular manifest.json file")
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise RestoreError("Backup manifest is too large")
        manifest = _manifest(manifest_path.read_bytes())
        names = set()
        total_size = 0
        for directory, subdirs, files in os.walk(source, followlinks=False):
            for item in subdirs + files:
                candidate = Path(directory) / item
                relative = candidate.relative_to(source).as_posix()
                if candidate.is_symlink():
                    raise RestoreError(f"Symbolic links are forbidden in backups: {relative}")
                if candidate.is_dir():
                    if relative != "evidence":
                        raise RestoreError(f"Unexpected backup directory: {relative}")
                else:
                    if not stat.S_ISREG(candidate.stat().st_mode):
                        raise RestoreError(f"Backup contains a non-regular file: {relative}")
                    names.add(relative)
                    total_size += candidate.stat().st_size
        if names != set(manifest["files"]) | {"manifest.json"}:
            raise RestoreError("Backup files do not match its manifest")
        if total_size > MAX_BACKUP_BYTES:
            raise RestoreError("Backup exceeds the 16 GiB restore limit")

        @contextmanager
        def opener(name):
            with (source / name).open("rb") as stream:
                yield stream

        yield manifest, opener
        return
    if not source.is_file():
        raise RestoreError("Backup source must be a backup directory or ZIP file")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RestoreError("Backup is not a readable ZIP file") from exc
    with archive:
        names = set()
        total_size = 0
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 2:
            raise RestoreError("Backup ZIP has too many entries")
        for info in infos:
            name = info.filename
            if name in names:
                raise RestoreError(f"Duplicate ZIP path: {name}")
            names.add(name)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RestoreError(f"Symbolic links are forbidden in backups: {name}")
            if info.flag_bits & 1:
                raise RestoreError("Encrypted ZIP backups are unsupported")
            if info.is_dir():
                if name != "evidence/":
                    raise RestoreError(f"Unsafe or unexpected ZIP directory: {name}")
            elif name != "manifest.json" and not FILE_PATH.fullmatch(name):
                raise RestoreError(f"Unsafe or unsupported ZIP path: {name}")
            total_size += info.file_size
        if total_size > MAX_BACKUP_BYTES:
            raise RestoreError("Backup exceeds the 16 GiB restore limit")
        if "manifest.json" not in names:
            raise RestoreError("Backup ZIP requires manifest.json at its root")
        if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
            raise RestoreError("Backup manifest is too large")
        manifest = _manifest(archive.read("manifest.json"))
        if names - {"evidence/"} != set(manifest["files"]) | {"manifest.json"}:
            raise RestoreError("Backup ZIP files do not match its manifest")

        @contextmanager
        def opener(name):
            with archive.open(name) as stream:
                yield stream

        yield manifest, opener


def _empty_destination(destination: Path) -> None:
    if destination.is_symlink():
        raise RestoreError("Restore destination must not be a symbolic link")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RestoreError("Restore destination must be a new or empty directory; existing data is never overwritten")


def restore_backup(source: str | Path, destination: str | Path) -> Path:
    """Restore only files listed in a verified v1 manifest, committing atomically."""
    source = Path(source).expanduser().absolute()
    destination = Path(destination).expanduser().absolute()
    _empty_destination(destination)
    source_real = source.resolve()
    destination_real = destination.resolve()
    if source_real == destination_real or source_real in destination_real.parents or destination_real in source_real.parents:
        raise RestoreError("Backup source and destination must be separate locations")
    stage = None
    try:
        with _open_backup(source) as (manifest, opener):
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".scanner-restore-", dir=destination.parent))
            total_size = 0
            for name, expected in manifest["files"].items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with opener(name) as incoming, target.open("xb") as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        total_size += len(chunk)
                        if total_size > MAX_BACKUP_BYTES:
                            raise RestoreError("Backup exceeds the 16 GiB restore limit")
                        digest.update(chunk)
                        outgoing.write(chunk)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                os.chmod(target, 0o600)
                if digest.hexdigest() != expected:
                    raise RestoreError(f"Checksum mismatch: {name}")
            try:
                database = sqlite3.connect(f"file:{quote(str(stage / 'scanner.sqlite'))}?mode=ro&immutable=1", uri=True)
                try:
                    result = database.execute("PRAGMA quick_check").fetchall()
                finally:
                    database.close()
                if result != [("ok",)]:
                    raise RestoreError("Backup SQLite database failed its integrity check")
            except sqlite3.Error as exc:
                raise RestoreError("Backup scanner.sqlite is not a valid SQLite database") from exc
            # Store creates its other subdirectories when first opened.
            (stage / "evidence").mkdir(exist_ok=True)
            _empty_destination(destination)
            if destination.exists():
                destination.rmdir()
            os.rename(stage, destination)
            stage = None
        return destination
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise RestoreError(f"Backup could not be restored: {exc}") from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a verified backup into a new, empty directory.")
    parser.add_argument("backup", type=Path, help="backup directory, or ZIP containing manifest.json at its root")
    parser.add_argument("--destination", type=Path, required=True, help="new or empty data directory; never use the active directory")
    args = parser.parse_args(argv)
    try:
        destination = restore_backup(args.backup, args.destination)
    except RestoreError as exc:
        parser.error(str(exc))
    print(f"Verified backup restored to {destination}")
    print(f'Launch it with: python -m scanner --data-dir "{destination}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
