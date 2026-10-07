"""Grant-scoped spend ledger, exclusive locks, and write-ahead receipts.

Caps are per authorization_id, not per output folder. A reserved, dispatched,
consumed, or failed receipt is spent and is never silently re-sent.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from pathlib import Path

from scanner.storage import Store

LEDGER_HOME_ENV = "SCANNER_LIVE_LEDGER_HOME"
LEDGER_ENV = "SCANNER_LIVE_LEDGER_DIR"
DEFAULT_LEDGER_ROOT = Path.home() / ".scanner" / "live-e2e-ledgers"
RECEIPT_KIND = "live_e2e_receipt"
GRANT_LOCK_NAME = "GRANT.lock"
OUTPUT_LOCK_NAME = "RUN.lock"
SPENT_STATES = frozenset({"reserved", "dispatched", "consumed", "failed"})
SPEND_KEYS = (
    "birdeye_requests",
    "birdeye_units",
    "helius_requests",
    "helius_units",
)

_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def empty_spend():
    return {key: 0 for key in SPEND_KEYS}


def empty_phase_spend():
    return {str(phase): empty_spend() for phase in (1, 2, 3, 4)}


def draft_artifact_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def committed_draft_hash(rel_path, *, repo_root, commit="HEAD"):
    """SHA-256 of the draft blob at a pinned git object. Working-tree edits do not count."""
    import subprocess

    spec = f"{commit}:{rel_path}"
    proc = subprocess.run(
        ["git", "show", spec],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"committed draft blob missing: {spec}")
    return hashlib.sha256(proc.stdout).hexdigest()


def committed_draft_payload(rel_path, *, repo_root, commit="HEAD"):
    import json
    import subprocess

    spec = f"{commit}:{rel_path}"
    proc = subprocess.run(
        ["git", "show", spec],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"committed draft blob missing: {spec}")
    return json.loads(proc.stdout.decode("utf-8")), hashlib.sha256(proc.stdout).hexdigest()


def provider_caps(grant):
    caps = empty_spend()
    for entry in grant.get("providers") or []:
        provider = entry.get("provider_id")
        if provider in ("birdeye", "helius"):
            caps[f"{provider}_requests"] = int(entry.get("max_requests") or 0)
            caps[f"{provider}_units"] = int(entry.get("max_units") or 0)
    return caps


def phase_caps_from_grant(grant):
    raw = grant.get("phase_caps") if isinstance(grant.get("phase_caps"), dict) else {}
    out = {}
    for phase in ("1", "2", "3", "4"):
        entry = raw.get(phase) or raw.get(int(phase)) or {}
        if not isinstance(entry, dict):
            continue
        cleaned = {}
        for key in SPEND_KEYS:
            if entry.get(key) is not None:
                cleaned[key] = int(entry[key])
        if cleaned:
            out[phase] = cleaned
    return out


def ledger_home():
    """Fixed per-user home. Caps are per authorization_id inside this home."""
    text = os.environ.get(LEDGER_HOME_ENV) or os.environ.get(LEDGER_ENV)
    if text:
        return Path(text)
    return DEFAULT_LEDGER_ROOT


def ledger_root(explicit=None):
    if explicit:
        return Path(explicit)
    return ledger_home()


def grant_ledger_path(authorization_id, explicit=None):
    ident = str(authorization_id or "unknown").replace("/", "_").replace("..", "_")
    home = ledger_home()
    canonical = home / ident
    if explicit:
        requested = Path(explicit)
        if requested.resolve() != home.resolve():
            raise ValueError(
                f"refusing second ledger dir {requested} for {ident}; "
                f"grant ledger is {canonical}"
            )
    return canonical


def open_grant_store(authorization_id, explicit=None):
    path = grant_ledger_path(authorization_id, explicit)
    if path.exists() and path.is_file():
        raise ValueError("grant ledger path must be a directory")
    path.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    if not hasattr(store, "reserve") or store.db is None:
        raise ValueError("durable grant ledger required")
    return store, path


def request_identity(provider, *, wallet, phase, page, cursor=None):
    cursor_text = "" if cursor in (None, "") else str(cursor)
    cursor_part = hashlib.sha256(cursor_text.encode("utf-8")).hexdigest()[:16]
    wallet_part = str(wallet or "_")
    return f"{provider}:{wallet_part}:{int(phase)}:{int(page)}:{cursor_part}"


def load_receipt(store, key):
    return store.get(RECEIPT_KIND, key)


def receipt_is_spent(receipt):
    if not isinstance(receipt, dict):
        return False
    if receipt.get("consumed") is True:
        return True
    return receipt.get("state") in SPENT_STATES


def put_receipt(store, grant, key, payload):
    receipt = {
        "request_id": key,
        "authorization_id": grant.get("authorization_id"),
        "consumed": payload.get("state") == "consumed",
        **payload,
    }
    store.put(RECEIPT_KIND, key, receipt)
    return receipt


def spend_from_ledger(store):
    spend = empty_spend()
    phase_spend = empty_phase_spend()
    for row in store.list(RECEIPT_KIND) or []:
        if not receipt_is_spent(row):
            continue
        provider = row.get("provider")
        if provider not in ("birdeye", "helius"):
            continue
        units = int(row.get("units") or 0)
        spend[f"{provider}_requests"] += 1
        spend[f"{provider}_units"] += units
        phase = str(row.get("phase") or "")
        if phase in phase_spend:
            phase_spend[phase][f"{provider}_requests"] += 1
            phase_spend[phase][f"{provider}_units"] += units
    return spend, phase_spend


def merge_spend(*parts):
    merged = empty_spend()
    for part in parts:
        for key in SPEND_KEYS:
            merged[key] = max(merged[key], int((part or {}).get(key) or 0))
    return merged


class ExclusiveLock:
    """Process flock + in-process thread lock. Non-blocking; refuse if held."""

    def __init__(self, path):
        self.path = Path(path)
        self.fd = None
        self._thread_lock = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(self.path.resolve()) if self.path.parent.exists() else str(self.path)
        with _THREAD_LOCKS_GUARD:
            if resolved not in _THREAD_LOCKS:
                _THREAD_LOCKS[resolved] = threading.Lock()
            tlock = _THREAD_LOCKS[resolved]
        if not tlock.acquire(blocking=False):
            raise LockHeld(f"exclusive lock held: {self.path}")
        self._thread_lock = tlock
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as error:
            tlock.release()
            self._thread_lock = None
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None
            if isinstance(error, BlockingIOError):
                raise LockHeld(f"exclusive lock held: {self.path}") from error
            raise LockHeld(f"exclusive lock held: {self.path}") from error
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(self.fd)
        return self

    def release(self):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self._thread_lock is not None:
            try:
                self._thread_lock.release()
            except RuntimeError:
                pass
            self._thread_lock = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


class LockHeld(RuntimeError):
    """Another run holds the grant or output lock."""


def lock_paths(ledger_path, output_dir):
    return ledger_path / GRANT_LOCK_NAME, Path(output_dir) / OUTPUT_LOCK_NAME


def integrity_record(*, original_sha256, written_sha256, scrubbed):
    return {
        "kind": "raw-page-integrity-v1",
        "original_sha256": original_sha256,
        "written_sha256": written_sha256,
        "scrubbed": bool(scrubbed),
        "note": (
            "original_sha256 is SHA-256 of the provider bytes before any scrub. "
            "The written copy is redacted when a secret appeared in the body; "
            "integrity of the original capture is the pre-scrub checksum."
        ),
    }


def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path
