#!/usr/bin/env python3
"""Pack canonical supplied inputs or the authorised partial QA cache; no network."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scanner.archive_input import canonical_bytes, validate_manifest


def pack_bundle(bundle, output):
    manifest = validate_manifest(bundle['manifest'])
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        for digest, payload in bundle['payloads'].items():
            raw = canonical_bytes(payload)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Payload hash does not match its name')
            archive.writestr(f'archives/{digest}.json.gz', gzip.compress(raw, mtime=0))


def pack_cache(corpus, output):
    original = json.loads(gzip.decompress((corpus/'manifest.json.gz').read_bytes()))
    report = original['report']
    frozen = json.loads(gzip.decompress((corpus/'archives'/f"{report['collection_input_hash']}.json.gz").read_bytes()))
    manifest = {'version': 'archived-wallet-input-v1', 'address': report['address'], 'window': report['window'],
                'dataset': 'real', 'transactions': [{'signature': t['signature'], 'hash': t['evidence_hash']} for t in frozen['transactions']],
                'evidence': frozen['evidence']}
    validate_manifest(manifest)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        for digest in original['archive_hashes']:
            archive.write(corpus/'archives'/f'{digest}.json.gz', f'archives/{digest}.json.gz')
    # Deliberately do not copy provider config/credentials/ledger or import a trusted checkpoint.


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path)
    p.add_argument('--partial-cache', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if bool(a.bundle) == bool(a.partial_cache):
        p.error('Choose one supplied canonical bundle or authorised partial cache')
    if a.bundle:
        pack_bundle(json.loads(a.bundle.read_text()), a.output)
    else:
        pack_cache(a.partial_cache, a.output)
    print(json.dumps({'output': str(a.output), 'sha256': hashlib.sha256(a.output.read_bytes()).hexdigest(),
                      'scope': 'Synthetic development' if a.bundle else 'Partial real sample; B3 remains blocked', 'provider_requests': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
