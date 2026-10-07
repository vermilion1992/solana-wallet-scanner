"""Grant-scoped spend ledger, exclusive locks, and write-ahead receipts.

Caps are per authorization_id, not per output folder. A reserved, dispatched,
consumed, or failed receipt is spent and is never silently re-sent.

Trust boundary (affc623 §9.4 / §9.5): the chain, head, seal and
reservations all live in the same Store/SQLite. An attacker with write
access to that DB can recompute a keyless chain or delete receipts +
log + head + seal + reservations and reset spend to 0.

There is no defense against a same-uid writer. The grant file holds no spend state,
so it cannot stop a reset. Ledger directories are typically
0755 and owned by the same uid every agent on the box runs as; sqlite
files may be 0600 but remain writable by that uid. The host filesystem
ACL is not a boundary between same-uid processes. Provider-side usage
checks before each run are the remaining control. Do not treat a
rewritten DB as an integrity proof.
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
# Absolute. --live must not relocate the ledger when HOME changes.
DEFAULT_LEDGER_ROOT = Path("/home/box/.scanner/live-e2e-ledgers")
RECEIPT_KIND = "live_e2e_receipt"
CHAIN_ENTRY_KIND = "live_e2e_chain_entry"
CHAIN_HEAD_KIND = "live_e2e_chain"
SPEND_SEAL_KIND = "live_e2e_spend_seal"
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


def _receipt_canonical_bytes(receipt):
    body = {name: receipt[name] for name in sorted(receipt) if name != "receipt_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def verify_receipt_integrity(receipt):
    """Recompute receipt_hash from the immutable body. Tampered rows fail."""
    if not isinstance(receipt, dict):
        raise ValueError("receipt is not an object")
    stored = receipt.get("receipt_hash")
    expected = hashlib.sha256(_receipt_canonical_bytes(receipt)).hexdigest()
    if not stored or stored != expected:
        raise ValueError("receipt_hash does not match the receipt body")
    return expected


def _chain_entries(store):
    if not hasattr(store, "list"):
        return []
    rows = list(store.list(CHAIN_ENTRY_KIND) or [])
    return sorted(rows, key=lambda row: int(row.get("seq") or 0))


def _spend_seal(store):
    if not hasattr(store, "get"):
        return None
    return store.get(SPEND_SEAL_KIND, "current")


def _seal_nonzero(seal):
    spend = (seal or {}).get("spend") if isinstance(seal, dict) else None
    if not isinstance(spend, dict):
        return False
    return any(int(spend.get(key) or 0) > 0 for key in SPEND_KEYS)


def verify_receipt_chain(store):
    """Verify the append-only receipt log and current receipt bodies.

    Empty store (no receipts, no log, no head, no spend seal) is OK.
    A broken, rewritten, or deleted chain is refused. Missing prev hashes
    are not skipped.
    """
    rows = list(store.list(RECEIPT_KIND) or []) if hasattr(store, "list") else []
    entries = _chain_entries(store)
    head = store.get(CHAIN_HEAD_KIND, "head") if hasattr(store, "get") else None
    seal = _spend_seal(store)
    if not rows and not entries:
        if _seal_nonzero(seal):
            raise ValueError("spend seal exists but chain log and receipts are missing")
        if isinstance(head, dict) and head.get("receipt_hash"):
            raise ValueError("chain head exists without receipts or log")
        return True
    if rows and not entries:
        raise ValueError("receipts exist but append-only chain log is missing")
    if entries and not rows:
        raise ValueError("chain log exists but receipts were deleted")
    by_hash = {}
    for row in rows:
        digest = verify_receipt_integrity(row)
        if digest in by_hash and by_hash[digest].get("request_id") != row.get("request_id"):
            raise ValueError("duplicate receipt_hash for distinct request ids")
        by_hash[digest] = row
    logged = {entry.get("receipt_hash") for entry in entries}
    for row in rows:
        if row.get("receipt_hash") not in logged:
            raise ValueError("receipt missing from append-only chain log")
    prev = None
    latest_by_key = {}
    for entry in entries:
        if entry.get("prev_receipt_hash") != prev:
            raise ValueError("append-only chain prev mismatch")
        latest_by_key[entry.get("request_id")] = entry
        prev = entry.get("receipt_hash")
    for row in rows:
        latest = latest_by_key.get(row.get("request_id"))
        if not latest or latest.get("receipt_hash") != row.get("receipt_hash"):
            raise ValueError("receipt rewritten off the append-only chain")
    if not isinstance(head, dict) or not head.get("receipt_hash"):
        raise ValueError("receipts exist but live_e2e_chain head is missing")
    if head.get("receipt_hash") != entries[-1].get("receipt_hash"):
        raise ValueError("chain head does not match last log entry")
    return True


def _reservation_spend(store):
    spend = empty_spend()
    if not hasattr(store, "db") or store.db is None:
        return spend
    try:
        rows = store.db.execute(
            "SELECT provider, cost, state, charged FROM reservations"
        ).fetchall()
    except Exception:
        return spend
    for provider, cost, state, charged in rows:
        if provider not in ("birdeye", "helius"):
            continue
        if state not in ("reserved", "dispatched") and not (state == "settled" and charged):
            continue
        spend[f"{provider}_requests"] += 1
        spend[f"{provider}_units"] += int(cost or 0)
    return spend


def _receipt_spend(store):
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


def _write_spend_seal(store, spend, phase_spend):
    previous = _spend_seal(store) if hasattr(store, "get") else None
    prev_hash = (previous or {}).get("seal_hash") if isinstance(previous, dict) else None
    body = {
        "spend": spend,
        "phase_spend": phase_spend,
        "prev_seal_hash": prev_hash,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    store.put(SPEND_SEAL_KIND, "current", {**body, "seal_hash": digest})
    return digest


def put_receipt(store, grant, key, payload):
    head = store.get(CHAIN_HEAD_KIND, "head") if hasattr(store, "get") else None
    prev_hash = (head or {}).get("receipt_hash") if isinstance(head, dict) else None
    seq = int((head or {}).get("seq") or 0) + 1
    receipt = {
        "request_id": key,
        "authorization_id": grant.get("authorization_id"),
        "consumed": payload.get("state") == "consumed",
        "prev_receipt_hash": prev_hash,
        **payload,
    }
    receipt["receipt_hash"] = hashlib.sha256(_receipt_canonical_bytes(receipt)).hexdigest()
    store.put(RECEIPT_KIND, key, receipt)
    store.put(CHAIN_ENTRY_KIND, f"{seq:08d}", {
        "seq": seq,
        "request_id": key,
        "receipt_hash": receipt["receipt_hash"],
        "prev_receipt_hash": prev_hash,
        "state": receipt.get("state"),
        "sha256": receipt.get("sha256"),
        "units": receipt.get("units"),
        "provider": receipt.get("provider"),
        "phase": receipt.get("phase"),
    })
    store.put(CHAIN_HEAD_KIND, "head", {
        "receipt_hash": receipt["receipt_hash"],
        "request_id": key,
        "seq": seq,
    })
    spend, phase_spend = spend_from_ledger(store)
    _write_spend_seal(store, spend, phase_spend)
    return receipt


def spend_from_ledger(store):
    receipt_spend, receipt_phase = _receipt_spend(store)
    reserve_spend = _reservation_spend(store)
    seal = _spend_seal(store)
    seal_spend = (seal or {}).get("spend") if isinstance(seal, dict) else None
    seal_phase = (seal or {}).get("phase_spend") if isinstance(seal, dict) else None
    spend = merge_spend(receipt_spend, reserve_spend, seal_spend)
    phase_spend = empty_phase_spend()
    for phase in phase_spend:
        phase_spend[phase] = merge_spend(
            (receipt_phase or {}).get(phase),
            (seal_phase or {}).get(phase),
        )
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
