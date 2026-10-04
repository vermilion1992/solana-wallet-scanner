"""Compare this optimization with the preserved exact Git source, offline."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import scanner.compiled_instructions as compiled
import scanner.source_consistency as candidate
from test_source_fact_reuse import (SCENARIOS, SIGNATURE, WALLET, development_record,
                                    linked, scenario)

BASELINE = '1040215f498b1317b1b942838994127f43a822bd'
original = subprocess.run(['git', 'show', f'{BASELINE}:scanner/source_consistency.py'],
                          cwd=ROOT, capture_output=True, check=True).stdout
baseline = types.ModuleType('scanner._source_consistency_frozen_baseline')
baseline.__package__ = 'scanner'
exec(compile(original, 'preserved-source-consistency.py', 'exec'), baseline.__dict__)


def invoke(module, records, accounts):
    return module.assess_source_consistency(records, accounts={SIGNATURE: accounts}, wallet=WALLET)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def run():
    paths = ['scanner/source_consistency.py', 'scanner/compiled_instructions.py',
             'scanner/transaction_format.py', 'tests/test_source_fact_reuse.py']
    source_before = {path: sha((ROOT / path).read_bytes()) for path in paths}
    matches, costs = [], []
    with patch('scanner.providers.Gateway.rpc', side_effect=AssertionError('Provider calls forbidden')) as rpc:
        with patch('keyring.get_password', side_effect=AssertionError('Credentials forbidden')) as credentials:
            for name in SCENARIOS:
                raw, accounts = scenario(name)
                alternative = deepcopy(raw)
                alternative['meta']['optionalProviderField'] = 'distinct archived variant'
                records = [linked(raw), linked(alternative)]
                inputs_before = sha(canonical(records))
                for operation, inputs in (
                    ('selected', records[:1]), ('alternatives', records),
                    ('permutation', records[::-1]), ('duplicate-links', records + records),
                    ('source-loss', [records[0], {**records[1], 'raw': None}]),
                    ('restored', records)):
                    expected = invoke(baseline, inputs, accounts)
                    actual = invoke(candidate, inputs, accounts)
                    assert actual == expected, (name, operation)
                    matches.append({'scenario': name, 'operation': operation,
                                    'state': actual['state'], 'result_sha256': sha(canonical(actual)),
                                    'equality': True})
                assert inputs_before == sha(canonical(records)), name
            for count in (1, 8, 32, 96):
                raw, accounts = development_record(count)
                records = [linked(raw)]
                row = {'accounts': count}
                for label, module in (('baseline', baseline), ('candidate', candidate)):
                    with patch.object(compiled, 'normalize_transaction', wraps=compiled.normalize_transaction) as normalizations:
                        started = time.perf_counter()
                        result = invoke(module, records, accounts)
                        elapsed = time.perf_counter() - started
                    assert result['state'] == 'PASS'
                    row[label] = {'normalizations': normalizations.call_count,
                                  'seconds': elapsed, 'result_sha256': sha(canonical(result))}
                assert row['baseline']['normalizations'] == count
                assert row['candidate']['normalizations'] == 1
                assert row['baseline']['result_sha256'] == row['candidate']['result_sha256']
                costs.append(row)
            assert rpc.call_count == credentials.call_count == 0
    source_after = {path: sha((ROOT / path).read_bytes()) for path in paths}
    assert source_before == source_after
    return {'state': 'PASS', 'purpose': 'Performance reuse preserves exact existing semantic output; no new wallet acceptance claim.',
            'baseline_commit': BASELINE, 'baseline_source_sha256': sha(original),
            'candidate_sources': source_before, 'source_unchanged': True,
            'complete_result_comparisons': matches, 'normalization_cost_controls': costs,
            'provider_requests': 0, 'credential_lookups': 0,
            'scope': 'Unsigned synthetic implementation controls only; PRODUCT_READY remains false.',
            'initial_test_failure': 'A duplicate-link equality assertion incorrectly expected source multiplicity counters to stay unchanged. Original log retained; corrected test explicitly checks counters and compares only semantic fact checks.'}


if __name__ == '__main__':
    output = run()
    path = Path(__file__).with_name('SOURCE_FACT_REUSE_PROOF.json')
    path.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'state': output['state'], 'comparisons': len(output['complete_result_comparisons']),
                      'normalization_controls': output['normalization_cost_controls'],
                      'provider_requests': 0, 'credential_lookups': 0}))
