"""Distinct offline review experiments; not additional acceptance suite nodes."""
from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_retained_protocol_funding import originals, wrapped, b58, WALLET, WINDOW, lot
from scanner.investigation import _data
from scanner.wallet_evidence import derive_wallet_evidence

PATHS = ('scanner/investigation.py', 'scanner/wallet_evidence.py',
         'scanner/source_consistency.py', 'scanner/chronology_evidence.py',
         'scanner/archive_input.py', 'scanner/real_coverage.py',
         'scanner/report_view.py', 'scanner/research.py', 'scanner/app.py',
         'frontend/src/report.tsx', 'scanner/accounting.py')
def hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in PATHS}
before = hashes()
raws = originals()
buy, sell = wrapped(raws[83]), wrapped(raws[85])
oracle_path = ROOT / 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json'
oracle_bytes = oracle_path.read_bytes()
oracle = json.loads(oracle_bytes)['supported_selected_lots'][0]
assert oracle['conditional_lot_profit_lamports'] == {'numerator': '-13270924', 'denominator': '1'}
assert oracle['buy_basis_lamports'] == {'numerator': '565194018', 'denominator': '1'}
assert oracle['hold_seconds'] == 529

def assess(records, linked):
    initial = deepcopy((records, linked))
    receipt = derive_wallet_evidence(records, all_records=linked, wallet=WALLET,
        window=WINDOW, source_consistency={}, chronology={})
    assert (records, linked) == initial, 'Raw review inputs were mutated'
    return receipt, lot(receipt)

parent, expected = assess([buy, sell], [buy, sell])
assert expected['monetary_state'] == expected['timing_state'] == 'PASS'
assert expected['conditional_lot_profit_sol'] == '-0.013270924'
assert expected['conditional_basis_sol'] == '0.565194018'
with localcontext() as context:
    context.prec = 192
    assert Decimal(expected['conditional_hold_hours']) == Decimal(529) / Decimal(3600)
assert expected['wallet_population_state'] == expected['classification_state'] == 'UNKNOWN'
assert expected['qualification'] is False
assert parent['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'

bad_raw = deepcopy(raws[83])
creation = bad_raw['meta']['innerInstructions'][1]['instructions'][0]
data = bytearray(_data(creation['data']))
data[-32:] = _data(WALLET)  # Contradictory program ownership, unchanged native fee.
creation['data'] = b58(data)
bad = wrapped(bad_raw)
observations = []
for label, selected, linked in (
        ('parsed-primary-bad-alternative', [buy, sell], [buy, sell, bad]),
        ('bad-primary-original-alternative', [bad, sell], [bad, sell, buy]),
        ('permuted-alternatives', [sell, buy], [bad, sell, buy]),
        ('missing-known-alternative', [buy, sell], [buy, sell, {**bad, 'raw': None}])):
    receipt, result = assess(selected, linked)
    assert result['monetary_state'] == 'UNKNOWN', label
    assert all(result[field] is None for field in ('conditional_basis_sol', 'conditional_matched_basis_sol',
        'conditional_proceeds_sol', 'conditional_exit_fees_sol', 'conditional_lot_profit_sol',
        'conditional_lot_roi_pct')), label
    if label != 'missing-known-alternative':
        assert receipt['components']['native_fee']['state'] == 'PASS', label
    observations.append({'case': label, 'lot': result, 'native_fee_state': receipt['components']['native_fee']['state']})

disjoint = wrapped(raws[72])
_, unrelated = assess([buy, sell, disjoint], [disjoint, sell, buy])
assert unrelated['monetary_state'] == unrelated['timing_state'] == 'PASS'
assert unrelated['conditional_lot_profit_sol'] == '-0.013270924'
restored, restored_lot = assess([buy, sell], [buy, sell])
assert restored == parent and restored_lot == expected
after = hashes()
assert before == after, 'Reviewed application changed during replay'
print(json.dumps({'status': 'PASS', 'scope': 'Distinct read-only financial neighbor experiments; no additional acceptance test count.',
    'provider_requests': 0, 'credential_lookups': 0, 'source_sha256_before': before,
    'source_sha256_after': after, 'source_unchanged': before == after,
    'independent_oracle_sha256': hashlib.sha256(oracle_bytes).hexdigest(),
    'positive_lot': expected, 'negative_cases': observations, 'disjoint_lot': unrelated,
    'exact_restoration': restored == parent}, indent=2))
