#!/usr/bin/env python3
"""Verify compressed evidence from a Git checkout or retained local originals.

This reads only the index and its compressed/raw evidence. It never creates a
report, reads private runtime state, extracts an archive or dispatches a request.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCOPES = tuple(ROOT / 'evidence' / name for name in (
    'genuine-wallet-batch', 'real-completion-batch', 'b3-candidate-preparation'))
PRIVATE_COMPONENTS = {'data', 'baseline', 'node_modules', '.git', '__pycache__',
                      '.venv', 'credentials', 'keyring', '.secrets', 'sessions', 'private'}


def hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def confined(name):
    assert isinstance(name, str) and not Path(name).is_absolute(), 'Evidence entry must be a relative path'
    candidate = ROOT / name
    assert not candidate.is_symlink(), 'Evidence entry must not be a symlink'
    resolved = candidate.resolve()
    assert any(resolved.is_relative_to(scope) for scope in SCOPES), 'Evidence entry must stay in the three authorized scopes'
    assert not set(resolved.relative_to(ROOT).parts).intersection(PRIVATE_COMPONENTS), 'Private subtree cannot be verification input'
    filename = resolved.name.lower()
    assert not filename.startswith('.env') and not any(word in filename for word in (
        'session', 'cookie', 'credential', 'launch', 'server', 'secret')), 'Private artifact name cannot be verification input'
    assert not any(filename.endswith(suffix) for suffix in ('.sqlite', '.sqlite3', '.db', '-wal', '-shm', '.lock'))
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'evidence/genuine-wallet-batch/EVIDENCE_STORAGE_INDEX.json')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--staging-plan', type=Path)
    args = parser.parse_args()
    index_path = args.index.resolve()
    index_path = confined(str(index_path.relative_to(ROOT)))
    index_raw = index_path.read_bytes()
    index = json.loads(index_raw)
    assert index['kind'] == 'lossless-git-evidence-storage-index-v1'
    original_presence = 0
    compressed_paths, substituted_originals = set(), set()
    for row in index['entries']:
        compressed = confined(row['compressed_path'])
        original = confined(row['original_path'])
        assert row['compressed_path'] not in compressed_paths
        compressed_paths.add(row['compressed_path'])
        substituted_originals.add(row['original_path'])
        with compressed.open('rb') as stream:
            assert hash_stream(stream) == (row['compressed_bytes'], row['compressed_sha256'])
        with gzip.open(compressed, 'rb') as restored:
            assert hash_stream(restored) == (row['original_bytes'], row['original_sha256'])
        if original.exists():
            with original.open('rb') as retained:
                assert hash_stream(retained) == (row['original_bytes'], row['original_sha256'])
            original_presence += 1
    assert sum(row['original_bytes'] for row in index['entries']) == index['original_total_bytes']
    assert sum(row['compressed_bytes'] for row in index['entries']) == index['compressed_total_bytes']
    receipt = {'kind': 'fresh-process-lossless-storage-verification-v1', 'state': 'PASS',
               'checked_utc': datetime.now(timezone.utc).isoformat(),
               'index_sha256': hashlib.sha256(index_raw).hexdigest(),
               'compressed_entries_checked': len(index['entries']),
               'fresh_decompression_matches_original_hashes': True,
               'present_originals_reread_and_verified': original_presence,
               'provider_requests': 0, 'credential_reads': 0,
               'application_acceptance_claimed': False}
    if args.receipt:
        assert args.receipt.resolve().is_relative_to(ROOT / 'evidence/genuine-wallet-batch/storage')
        assert not args.receipt.exists(), 'Verification receipt must not overwrite history'
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    if args.staging_plan:
        assert args.staging_plan.resolve().is_relative_to(ROOT / 'evidence/genuine-wallet-batch/storage')
        spec = importlib.util.spec_from_file_location('evidence_storage_contract', Path(__file__).with_name('reconcile_storage.py'))
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        paths, omissions = [], []
        for scope in helper.SCOPES:
            for path in scope.rglob('*'):
                relative = str(path.relative_to(ROOT))
                if path.is_symlink():
                    omissions.append({'path': relative, 'reason': 'symlink'})
                    continue
                if not path.is_file():
                    continue
                reason = helper.excluded(path)
                if reason or relative in substituted_originals:
                    omissions.append({'path': relative, 'reason': reason or 'exact bytes represented by indexed gzip'})
                    continue
                if path.name.endswith('.gzip-pending'):
                    omissions.append({'path': relative, 'reason': 'incomplete compression'})
                    continue
                paths.append(relative)
        if str(args.staging_plan.relative_to(ROOT)) not in paths:
            paths.append(str(args.staging_plan.relative_to(ROOT)))
        plan = {'kind': 'nonmutating-evidence-staging-plan-v1', 'index_sha256': receipt['index_sha256'],
                'scope': 'Only the three newly authorized evidence directories; application/docs staging remains root-owned.',
                'suggested_git_paths': sorted(paths), 'do_not_stage': sorted(omissions, key=lambda row: row['path']),
                'git_mutations_performed': False, 'originals_deleted': False,
                'provider_requests': 0, 'credential_reads': 0}
        args.staging_plan.write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
