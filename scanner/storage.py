"""Serialized SQLite writes, content-addressed evidence and durable quota reservations."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
import uuid
import zlib


class QuotaExceeded(Exception):
    pass


class EvidenceError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir):
        self.path = Path(data_dir).expanduser().resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for folder in ("evidence", "exports", "backups", "logs"):
            (self.path / folder).mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path / "scanner.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS records (
          kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
          updated_at TEXT NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS reservations (
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, method TEXT NOT NULL,
          cost INTEGER NOT NULL CHECK(cost > 0), cycle TEXT NOT NULL,
          state TEXT NOT NULL, charged INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS quota_cycle ON reservations(provider,cycle);
        """)
        self.db.commit()
        from .mass_search.schema import ensure_schema
        ensure_schema(self.db)
        try:
            os.chmod(self.path / "scanner.sqlite", 0o600)
        except OSError:
            pass

    def get(self, kind, id, default=None):
        with self.lock:
            row = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else default

    def list(self, kind):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM records WHERE kind=? ORDER BY updated_at DESC,id", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind, id, payload):
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self.lock, self.db:
            self.db.execute("INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (kind, id, encoded, now()))

    def delete(self, kind, id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, id))

    def archive(self, payload):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        dest = self.path / "evidence" / f"{digest}.json.gz"
        if dest.exists():
            self.evidence(digest)
            return digest
        fd, temporary = tempfile.mkstemp(prefix=".archive-", dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(gzip.compress(encoded, mtime=0))
                file.flush()
                os.fsync(file.fileno())
            # A completed immutable record becomes visible atomically.
            with self.lock:
                if not dest.exists():
                    os.replace(temporary, dest)
            self.put("artifacts", digest, {"hash": digest, "bytes": len(encoded), "created_at": now()})
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return digest

    def evidence(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise EvidenceError("Invalid evidence identifier")
        try:
            data = gzip.decompress((self.path / "evidence" / f"{digest}.json.gz").read_bytes())
        except (OSError, EOFError, zlib.error) as error:
            raise EvidenceError("Evidence is missing or unreadable") from error
        if hashlib.sha256(data).hexdigest() != digest:
            raise EvidenceError("Evidence checksum mismatch; report cannot be verified")
        return json.loads(data)

    def reserve(self, provider, method, cost, cycle, cap):
        if type(cost) is not int or cost < 1 or type(cap) is not int or cap < 1:
            raise ValueError("Metered costs and caps must be positive integers")
        reservation = uuid.uuid4().hex
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                total = self.db.execute("SELECT COALESCE(SUM(CASE WHEN state IN ('reserved','dispatched') THEN cost WHEN state='settled' AND charged=1 THEN cost ELSE 0 END),0) FROM reservations WHERE provider=? AND cycle=?", (provider, cycle)).fetchone()[0]
                if total + cost > cap:
                    raise QuotaExceeded("Free application credit cap reached, including pending reservations")
                timestamp = now()
                self.db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,'reserved',0,?,?)", (reservation, provider, method, cost, cycle, timestamp, timestamp))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return reservation

    def dispatch(self, reservation):
        with self.lock, self.db:
            result = self.db.execute("UPDATE reservations SET state='dispatched',updated_at=? WHERE id=? AND state='reserved'", (now(), reservation))
            if result.rowcount != 1:
                raise ValueError("Reservation is not undispatched")

    def settle(self, reservation, charge=True):
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()
            if not row or row[0] not in ("reserved", "dispatched"):
                raise ValueError("Reservation cannot be settled")
            if row[0] == "dispatched" and not charge:
                raise ValueError("Dispatched request must be conservatively charged")
            self.db.execute("UPDATE reservations SET state='settled',charged=?,updated_at=? WHERE id=?", (int(charge), now(), reservation))

    def release(self, reservation):
        with self.lock, self.db:
            result = self.db.execute("UPDATE reservations SET state='released',updated_at=? WHERE id=? AND state='reserved'", (now(), reservation))
            if result.rowcount != 1:
                raise ValueError("Only an undispatched reservation can be released")

    def usage(self, provider, cycle, cap):
        with self.lock:
            row = self.db.execute("SELECT COALESCE(SUM(CASE WHEN state='dispatched' OR (state='settled' AND charged=1) THEN cost ELSE 0 END),0) used, COALESCE(SUM(CASE WHEN state='reserved' THEN cost ELSE 0 END),0) reserved FROM reservations WHERE provider=? AND cycle=?", (provider, cycle)).fetchone()
        return {"used": row[0], "reserved": row[1], "cap": cap, "remaining": max(0, cap - row[0] - row[1]), "cycle_start": cycle}

    def backup(self):
        with self.lock:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            dest = self.path / "backups" / stamp
            dest.mkdir(mode=0o700)
            connection = sqlite3.connect(dest / "scanner.sqlite")
            try:
                self.db.backup(connection)
            finally:
                connection.close()
            (dest / "evidence").mkdir()
            manifest = {"version": 1, "created_at": now(), "files": {}}
            for source in sorted((self.path / "evidence").glob("*.json.gz")):
                self.evidence(source.name.split(".")[0])
                target = dest / "evidence" / source.name
                shutil.copy2(source, target)
                manifest["files"][f"evidence/{source.name}"] = hashlib.sha256(target.read_bytes()).hexdigest()
            manifest["files"]["scanner.sqlite"] = hashlib.sha256((dest / "scanner.sqlite").read_bytes()).hexdigest()
            (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
            return {"path": str(dest), "files": len(manifest["files"]), "created_at": manifest["created_at"]}

    def stats(self):
        files = list((self.path / "evidence").glob("*.json.gz"))
        return {"data_dir": str(self.path), "evidence_files": len(files), "evidence_bytes": sum(f.stat().st_size for f in files), "free_disk_bytes": shutil.disk_usage(self.path).free}

    def close(self):
        with self.lock:
            self.db.close()
