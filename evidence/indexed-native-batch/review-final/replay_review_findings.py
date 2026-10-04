#!/usr/bin/env python3
"""Read-only, offline review controls; unsigned conversion is not B3 evidence."""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from test_indexed_input import upload, page, unpack, sources, WALLET, WINDOW
from test_compiled_report_integration import (
    compiled_development_copy, SELL, asset_account, wallet,
)
from scanner.indexed_input import convert_indexed_archive, describe_pages
from scanner.wallet_evidence import _observe
from scanner.compiled_instructions import normalize_transaction


def main():
    manifest, payloads = unpack(convert_indexed_archive(upload([page()])[2]))
    good = sources(manifest, payloads)[0]
    checks = []
    for variant in ('missing', 'checksum-mismatch'):
        bad = deepcopy(good)
        if variant == 'missing':
            bad['payload'] = None
        else:
            bad['payload']['response_hash'] = 'a' * 64
        states = [describe_pages(rows, WALLET, WINDOW)['state']
                  for rows in ([good, bad], [bad, good])]
        checks.append({'id': 'IDX-REVIEW-DUPLICATE-' + variant,
                       'expected': ['UNKNOWN', 'UNKNOWN'], 'observed': states,
                       'passing': states == ['UNKNOWN', 'UNKNOWN'],
                       'scope': 'Typed source topology interface; no complete population/qualification claim'})
    duplicate = describe_pages([good, good], WALLET, WINDOW)
    checks.append({'id': 'IDX-REVIEW-DUPLICATE-POSITIVE',
                   'expected': 'PASS', 'observed': duplicate['state'],
                   'passing': duplicate['state'] == 'PASS' and len(duplicate['pages']) == 1})
    record = compiled_development_copy(SELL)
    preserved = deepcopy(record)
    observation = _observe(record, wallet(record))
    receipts = normalize_transaction(record['raw'])['normalizations']
    boundary = observation['boundaries'][asset_account(record)]
    paths = {p for check in boundary['checks'].values() for p in check['raw_paths']}
    invalid = sorted(p for p in paths
                     if any(p.startswith(row['path'] + '.parsed') for row in receipts))
    checks.append({'id': 'IDX-REVIEW-COMPILED-OBSERVATION-RAW-PATHS',
                   'expected': {'quantity_state': 'PASS', 'derived_only_raw_paths': []},
                   'observed': {'quantity_state': boundary['checks']['quantities']['state'],
                                'derived_only_raw_paths': invalid},
                   'passing': boundary['checks']['quantities']['state'] == 'PASS' and not invalid,
                   'scope': 'Original compiled data/account paths must support derived observation citations'})
    checks.append({'id': 'IDX-REVIEW-COMPILED-SOURCE-IMMUTABILITY',
                   'passing': record == preserved,
                   'normalizations': len(receipts),
                   'scope': 'Unsigned pinned-layout conversion, not a genuine compiled transaction'})
    for check in checks:
        print(json.dumps(check, sort_keys=True))
    result = {'kind': 'offline-read-only-review-findings-replay',
              'state': 'PASS_IN_SCOPE' if all(c['passing'] for c in checks) else 'CURRENT_REPRODUCTIONS',
              'checks': checks,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'provider_calls': 0, 'credential_lookups': 0,
              'new_application_acceptance': False, 'B3': 'BLOCKED', 'PRODUCT_READY': False}
    print(json.dumps({'summary': result['state'], 'engineering_controls': len(checks)}))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['state'] == 'PASS_IN_SCOPE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
