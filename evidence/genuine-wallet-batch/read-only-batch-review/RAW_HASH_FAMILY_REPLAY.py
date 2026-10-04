"""Read-only synthetic raw-byte hash-boundary review; no providers or credentials.

This is a diagnostic, not a genuine accounting oracle or application acceptance.
Call with a new output filename so first failures remain unchanged.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_indexed_source_dependencies import native, source
from test_position_evidence import WALLET, WINDOW
from test_real_coverage import archived_query_bundle, archive_assessment
from test_wallet_evidence import record
from scanner.archive_input import import_archive, pack_bytes
from scanner.indexed_input import canonical_bytes
from scanner.real_coverage import derive_indexed_coverage
from scanner.storage import Store
from scanner.wallet_evidence import _selected_lot_observations


def replay():
    raw = native(slot=111_491_820)
    matrix = []
    for wrapper in ('page', 'native'):
        for condition, value in [('valid-unicode', '\u03bb'), ('invalid-surrogate', '\ud800')]:
            row = source([raw], native=wrapper == 'native')
            response = json.loads(base64.b64decode(row['payload']['response_base64']))
            target = response['result']['data'][0] if wrapper == 'page' else response['result']
            target['unusedProviderText'] = value
            response_raw = json.dumps(response, separators=(',', ':')).encode()
            row['payload']['response_base64'] = base64.b64encode(response_raw).decode()
            row['payload']['response_hash'] = hashlib.sha256(response_raw).hexdigest()
            row['hash'] = hashlib.sha256(canonical_bytes(row['payload'])).hexdigest()
            facts = {}
            for operation in ('archive-load', 'query-bind', 'lot-recovery'):
                try:
                    if operation == 'archive-load':
                        with tempfile.TemporaryDirectory(prefix='scanner-readonly-native-family-') as directory:
                            store = Store(Path(directory))
                            manifest = import_archive(store, pack_bytes(archived_query_bundle(raw, [row])))
                            _, result, assessment = archive_assessment(store, manifest)
                            observed = {'query_state': assessment['query_coverage']['intervals']['report_period']['state'],
                                        'wallet_profit_status': result['metrics']['profit_sol']['status']}
                    elif operation == 'query-bind':
                        result = derive_indexed_coverage([record(raw)], all_records=[record(raw)], raw_sources=[row],
                            wallet=WALLET, window=WINDOW, source_consistency={}, chronology={})
                        observed = {'query_state': result['intervals']['report_period']['state'],
                                    'historical_population_state': result['historical_population']['state']}
                    else:
                        result = _selected_lot_observations([], {}, {}, {}, {}, {}, [], [row], WALLET)
                        observed = {'observed_lots': len(result)}
                    facts[operation] = {'state': 'NO_EXCEPTION', **observed}
                except Exception as error:
                    facts[operation] = {'state': 'EXCEPTION', 'type': type(error).__name__,
                        'reason': str(error), 'traceback': traceback.format_exc()}
            matrix.append({'wrapper': wrapper, 'value_condition': condition, 'operations': facts})
    return {'scope': 'Current-source synthetic escaped-provider-byte shared hash-boundary diagnostic; no genuine expectation changes, providers or credentials.',
            'source_hashes': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in
                ['scanner/archive_input.py', 'scanner/real_coverage.py', 'scanner/wallet_evidence.py']},
            'matrix': matrix}


if __name__ == '__main__':
    output = Path(sys.argv[1])
    result = replay()
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=True)
        stream.write('\n')
    print(json.dumps({'output': str(output), 'exceptions': sum(
        value['state'] == 'EXCEPTION' for row in result['matrix'] for value in row['operations'].values())}))
