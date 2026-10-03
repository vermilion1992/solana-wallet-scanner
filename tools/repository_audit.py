#!/usr/bin/env python3
"""Read-only pre-push audit of tracked files, reachable Git history and replay inputs.

This is a local credential-pattern/path check, not a guarantee against every
possible secret. It never reads environment/keyring credentials or contacts a
provider. Findings contain paths and rule names, never matching values.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE = re.compile(r'(^|/)(?:\.env(?:\..*)?|credentials?|keyring|\.secrets|\.solana)(?:/|$)|\.(?:db|sqlite3?|pem|key|p12|pfx)(?:$|-)', re.I)
SAMPLES = {'.env.example', '.env.sample'}
UUID = rb'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
RULES = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})\b'),
    'aws-access-key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'literal-api-credential': re.compile(rb'(?i)(?:api[-_]?key|authorization|password|secret)[\s"\x27:=]+(?:bearer\s+)?' + UUID),
    'literal-opaque-credential': re.compile(rb'(?i)\b(?:api[-_]?key|access_token|private[-_]?key|authorization|password|secret)\b["\x27]?\s*[:=]\s*["\x27](?:bearer\s+)?([A-Za-z0-9_/+=-]{20,})["\x27]'),
    'credential-query': re.compile(rb'(?i)(?:api-key|api_key|apikey)=([A-Za-z0-9_-]{16,})'),
}
PLACEHOLDERS = {b'your-api-key-here', b'synthetic-offline-key'}
GUARD_PATHS = ('.env', '.env.local', 'credentials/helius.json', 'keyring/provider.key',
               'local-data/wallets.sqlite3', 'private.sqlite3', 'private.db-wal', '.solana/id.json')
CORPUS = 'evidence/runs/real-cache'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def sensitive_path(path):
    return Path(path).name not in SAMPLES and bool(SENSITIVE.search(path))


def inspect_bytes(raw, path, findings, counters, depth=0):
    if depth > 5:
        findings.append({'path': path, 'rule': 'nested-archive-depth'})
        return
    if raw.startswith(b'\x1f\x8b'):
        try:
            inspect_bytes(gzip.decompress(raw), path + '!gzip', findings, counters, depth + 1)
        except (OSError, EOFError):
            findings.append({'path': path, 'rule': 'unreadable-gzip'})
        return
    if raw.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for name in archive.namelist():
                    if not name.endswith('/'):
                        if sensitive_path(name):
                            findings.append({'path': path + '!' + name, 'rule': 'sensitive-archive-path'})
                        inspect_bytes(archive.read(name), path + '!' + name, findings, counters, depth + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile):
            findings.append({'path': path, 'rule': 'unreadable-zip'})
        return
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError:
        return
    counters['text_payloads'] += 1
    for name, pattern in RULES.items():
        matches = list(pattern.finditer(raw))
        if name == 'credential-query':
            matches = [m for m in matches if m.group(1).lower() not in PLACEHOLDERS]
        if matches:
            findings.append({'path': path, 'rule': name, 'matches': len(matches)})
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return
    if isinstance(value, list) and len(value) in (32, 64) and all(type(x) is int and 0 <= x <= 255 for x in value):
        findings.append({'path': path, 'rule': 'possible-solana-private-key-array'})


def audit(root=ROOT, *, require_corpus=True):
    root = Path(root)
    findings, counters = [], {'current_files': 0, 'history_blobs': 0, 'text_payloads': 0}
    names = [n for n in git(root, 'ls-files', '-z').decode().split('\0') if n]
    file_hashes = {}
    inspected = set()
    for name in names:
        if sensitive_path(name):
            findings.append({'path': name, 'rule': 'sensitive-tracked-path'})
        path = root / name
        if not path.is_file() or path.is_symlink():
            findings.append({'path': name, 'rule': 'missing-or-symbolic-tracked-file'})
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        file_hashes[name] = digest
        counters['current_files'] += 1
        if digest not in inspected:
            inspect_bytes(raw, name, findings, counters)
            inspected.add(digest)
    objects = git(root, 'rev-list', '--objects', '--all').decode().splitlines()
    types = git(root, 'cat-file', '--batch-check=%(objectname) %(objecttype)', '--batch-all-objects').decode()
    blobs = {line.split()[0] for line in types.splitlines() if line.endswith(' blob')}
    for line in objects:
        oid, _, path = line.partition(' ')
        if oid not in blobs:
            continue
        if path and sensitive_path(path):
            findings.append({'path': path, 'object': oid, 'rule': 'sensitive-history-path'})
        raw = git(root, 'cat-file', 'blob', oid)
        counters['history_blobs'] += 1
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in inspected:
            inspect_bytes(raw, 'history:' + oid + ':' + path, findings, counters)
            inspected.add(digest)
    guards = {}
    for name in GUARD_PATHS:
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', name], cwd=root)
        guards[name] = result.returncode == 0
        if not guards[name]:
            findings.append({'path': name, 'rule': 'runtime-path-not-ignored'})
    corpus = root / CORPUS
    corpus_files = list((corpus / 'archives').glob('*.json.gz'))
    if require_corpus:
        required = [str(p.relative_to(root)) for p in corpus_files] + [CORPUS + '/manifest.json.gz']
        if len(corpus_files) != 63 or any(n not in names for n in required):
            findings.append({'path': CORPUS, 'rule': 'required-replay-corpus-not-tracked'})
        for path in corpus_files:
            digest = path.name.removesuffix('.json.gz')
            if hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() != digest:
                findings.append({'path': str(path.relative_to(root)), 'rule': 'corpus-content-hash'})
    return {'kind': 'pre-push-repository-audit', 'state': 'PASS' if not findings else 'BLOCKED',
            'scope': 'Tracked files and reachable history, nested ZIP/gzip credential patterns, runtime ignore protections and retained replay corpus. Not an exhaustive secret guarantee.',
            'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'branch': git(root, 'branch', '--show-current').decode().strip(), 'counts': counters,
            'runtime_ignore_guards': guards, 'replay_corpus_archives': len(corpus_files),
            'file_hashes': file_hashes, 'findings': findings,
            'network_requests': 0, 'credential_lookups': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = audit(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ('state', 'head', 'branch', 'counts', 'findings')}))
    raise SystemExit(0 if record['state'] == 'PASS' else 2)
