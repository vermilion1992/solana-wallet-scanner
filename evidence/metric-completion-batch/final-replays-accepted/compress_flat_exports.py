"""Lossless storage representations of completed, public workflow exports.

Preserves original files, small receipts/logs and original acquisition fixtures.
Each gzip is independently extractable and checked against the original bytes.
Never descends into runtime data directories or other validation outputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[3]
BASES = [ROOT / 'evidence/metric-completion-batch' / name
         for name in ('final-replays', 'final-replays-accepted')]
THRESHOLD = 2 * 1024 * 1024
EXPORT = re.compile(r'^(?:parent-report|baseline-child|source-(?:missing|restored)-child|'
    r'lot-[0-9]+-[A-Za-z0-9_-]+-(?:missing|restored)-child|inspected-selected-sources|'
    r'partial-real-report|synthetic-parent|valuation_hash-missing-child|world_hash-missing-child)\.json$')


def byte_identity(stream):
    total, digest = 0, hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        digest.update(chunk)
    return total, digest.hexdigest()


def main():
    for base in BASES:
        records = []
        index = {'kind': 'lossless-completed-workflow-export-storage', 'state': 'INCOMPLETE',
            'scope': 'Only completed/interrupted own flat public report/source-inspection JSON exports over 2 MiB; originals retained. No runtime directories, active gates, original acquisition inputs, fixtures or small raw receipts/logs touched.',
            'started_at': datetime.now(timezone.utc).isoformat(), 'threshold_bytes': THRESHOLD,
            'originals_retained': True, 'records': records}
        def save():
            (base / 'STORAGE_INDEX.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
        save()
        for directory in sorted(base.iterdir()):
            if not directory.is_dir() or directory.is_symlink() or directory.name == 'data':
                continue
            for original in sorted(directory.iterdir()):
                if (not original.is_file() or original.is_symlink() or not EXPORT.fullmatch(original.name)
                        or original.stat().st_size <= THRESHOLD):
                    continue
                encoded = original.with_suffix(original.suffix + '.gz')
                if encoded.exists():
                    raise ValueError('Refusing to overwrite an existing storage representation: ' + str(encoded))
                with original.open('rb') as stream:
                    original_size, original_sha = byte_identity(stream)
                with original.open('rb') as source, encoded.open('wb') as target:
                    with gzip.GzipFile(filename='', fileobj=target, mode='wb', mtime=0) as compressed:
                        shutil.copyfileobj(source, compressed, length=1024 * 1024)
                with gzip.open(encoded, 'rb') as stream:
                    expanded_size, expanded_sha = byte_identity(stream)
                with encoded.open('rb') as stream:
                    encoded_size, encoded_sha = byte_identity(stream)
                with original.open('rb') as stream:
                    unchanged_size, unchanged_sha = byte_identity(stream)
                assert (original_size, original_sha) == (expanded_size, expanded_sha) == (unchanged_size, unchanged_sha)
                assert encoded_size < 100 * 1024 * 1024
                records.append({'original': str(original.relative_to(base)), 'original_bytes': original_size,
                    'original_sha256': original_sha, 'stored': str(encoded.relative_to(base)),
                    'stored_bytes': encoded_size, 'stored_sha256': encoded_sha, 'encoding': 'gzip',
                    'roundtrip_verified': True, 'original_unchanged': True,
                    'reconstruction': 'Decompress this individual gzip to recover exact original JSON bytes.'})
                save()
        index.update(state='PASS', finished_at=datetime.now(timezone.utc).isoformat(),
            original_bytes=sum(row['original_bytes'] for row in records),
            stored_bytes=sum(row['stored_bytes'] for row in records), compressed_files=len(records))
        save()
        print(json.dumps({'package': base.name, 'state': index['state'], 'files': len(records),
            'original_bytes': index['original_bytes'], 'stored_bytes': index['stored_bytes'],
            'originals_retained': True}), flush=True)


if __name__ == '__main__':
    main()
