#!/usr/bin/env python3
"""Create deterministic, lossless Git evidence alternatives without deletion.

Restrict this operator helper to the three new evidence directories. No source
changes, credential access, provider calls or release archives. Originals remain
in place, including every prior/failed receipt. Run only for completed outputs.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SCOPES = tuple(ROOT / 'evidence' / name for name in (
    'genuine-wallet-batch', 'real-completion-batch', 'b3-candidate-preparation'))
EXCLUDE_COMPONENTS = {'data', 'baseline', 'node_modules', '.git', '__pycache__',
                      '.venv', 'credentials', 'keyring', '.secrets', 'sessions', 'private'}
TEXT_SUFFIXES = {'.json', '.jsonl', '.ndjson', '.log', '.txt', '.csv', '.html', '.har'}
THRESHOLD = 1_000_000
INDEX = SCOPES[0] / 'EVIDENCE_STORAGE_INDEX.json'


def sha_file(path):
    digest = hashlib.sha256()
    length = 0
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            length += len(chunk)
    return length, digest.hexdigest()


def excluded(path):
    parts = set(path.relative_to(ROOT).parts)
    if parts.intersection(EXCLUDE_COMPONENTS):
        return 'Private runtime, dependency or source-baseline subtree'
    name = path.name.lower()
    if (name.startswith('.env') or any(word in name for word in (
            'session', 'cookie', 'credential', 'launch', 'server', 'secret'))
            or any(name.endswith(suffix) for suffix in ('.sqlite', '.sqlite3', '.db', '-wal', '-shm', '.lock'))):
        return 'Private/session/server/database artifact name'
    return None


def compress(path):
    before = path.stat()
    original_size, original_hash = sha_file(path)
    destination = path.with_name(path.name + '.gz')
    assert not destination.is_symlink(), 'Compression target cannot be a symlink'
    if not destination.exists():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix=path.name + '.',
                                             suffix='.gzip-pending', delete=False) as output:
                temporary = Path(output.name)
                with path.open('rb') as source, gzip.GzipFile(filename='', mode='wb',
                        fileobj=output, compresslevel=9, mtime=0) as packed:
                    shutil.copyfileobj(source, packed, 1024 * 1024)
            assert path.stat().st_mtime_ns == before.st_mtime_ns and path.stat().st_size == before.st_size, 'Original changed during compression'
            temporary.rename(destination)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    with destination.open('rb') as handle:
        header = handle.read(10)
    assert header[:2] == b'\x1f\x8b' and header[3] == 0 and header[4:8] == bytes(4), 'Gzip must omit filename/time metadata'
    restored_hash = hashlib.sha256()
    restored_size = 0
    with gzip.open(destination, 'rb') as restored:
        while chunk := restored.read(1024 * 1024):
            restored_hash.update(chunk)
            restored_size += len(chunk)
    assert restored_size == original_size and restored_hash.hexdigest() == original_hash, 'Fresh decompression must recover exact original bytes'
    assert sha_file(path) == (original_size, original_hash), 'Original changed after compression'
    packed_size, packed_hash = sha_file(destination)
    return {'original_path': str(path.relative_to(ROOT)), 'original_bytes': original_size,
            'original_sha256': original_hash, 'compressed_path': str(destination.relative_to(ROOT)),
            'compressed_bytes': packed_size, 'compressed_sha256': packed_hash,
            'gzip_mtime': 0, 'gzip_embedded_filename': False,
            'fresh_decompression_bytes': restored_size, 'fresh_decompression_sha256': restored_hash.hexdigest(),
            'original_retained': True, 'recommended_git_representation': 'compressed_path'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completed-subdir', action='append', default=[],
                        help='Repository-relative completed output subtree approved for compression')
    parser.add_argument('--complete-current-snapshot', action='store_true',
                        help='Use only after root confirms all current outputs have finished')
    args = parser.parse_args()
    approved = []
    for name in args.completed_subdir:
        path = (ROOT / name).resolve(strict=True)
        assert any(path.is_relative_to(scope) for scope in SCOPES), 'Completed directory is outside authorized scope'
        assert path.is_dir(), 'Completed output must be a directory'
        approved.append(path)
    assert approved or args.complete_current_snapshot, 'Completed output authorization is required'
    tracked = set(subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True,
                                stdout=subprocess.PIPE).stdout.decode().split('\0'))
    eligible, omissions, deferred = [], [], []
    for scope in SCOPES:
        for path in sorted(scope.rglob('*')):
            relative = str(path.relative_to(ROOT))
            if path == INDEX:
                continue
            if path.is_symlink():
                omissions.append({'path': relative, 'reason': 'Symlink is outside the regular-file packaging contract'})
                continue
            if not path.is_file():
                continue
            reason = excluded(path)
            if reason:
                omissions.append({'path': relative, 'reason': reason})
                continue
            if relative in tracked:
                continue
            if path.suffix not in TEXT_SUFFIXES or path.stat().st_size <= THRESHOLD:
                continue
            if not args.complete_current_snapshot and not any(path.is_relative_to(p) for p in approved):
                deferred.append({'path': relative, 'reason': 'Awaiting final output completion confirmation'})
                continue
            eligible.append(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        packed = list(pool.map(compress, eligible))
    result = {'kind': 'lossless-git-evidence-storage-index-v1',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'state': 'VERIFIED', 'authorized_scopes': [str(p.relative_to(ROOT)) for p in SCOPES],
              'packaging_only': True, 'source_modified': False, 'originals_deleted': False,
              'provider_requests': 0, 'credential_reads': 0, 'release_zip_created': False,
              'threshold_bytes': THRESHOLD, 'threshold_rule': 'Strictly greater than 1,000,000 bytes',
              'completed_output_subdirs': [str(p.relative_to(ROOT)) for p in approved],
              'current_snapshot_completion_confirmed': args.complete_current_snapshot,
              'entries': packed, 'omitted_private_artifacts': omissions, 'deferred': deferred,
              'original_total_bytes': sum(row['original_bytes'] for row in packed),
              'compressed_total_bytes': sum(row['compressed_bytes'] for row in packed),
              'tracked_oracles_and_inputs': 'Existing Git-tracked files are never compressed or edited.',
              'other_files': 'ZIPs, existing gzip files, binary captures and files <=threshold retain their existing representation.',
              'reconstruction': 'For each entry decompress compressed_path with standard gzip and verify original_bytes/original_sha256. Existing receipt references keep original path/hash; compression changes storage only.',
              'tracking_instruction': 'Stage either original_path or compressed_path per entry, preferably compressed_path; do not stage omissions/private subtrees. Originals remain locally for direct replays.',
              'acceptance_claim': 'Storage round-trip verification only; no application or genuine-wallet acceptance.'}
    INDEX.write_text(json.dumps(result, indent=2) + '\n')
    size, digest = sha_file(INDEX)
    print(json.dumps({'state': result['state'], 'entries': len(packed),
                      'original_bytes': result['original_total_bytes'],
                      'compressed_bytes': result['compressed_total_bytes'],
                      'deferred': len(deferred), 'private_artifact_omissions': len(omissions),
                      'index': str(INDEX.relative_to(ROOT)), 'index_bytes': size, 'index_sha256': digest}))


if __name__ == '__main__':
    main()
