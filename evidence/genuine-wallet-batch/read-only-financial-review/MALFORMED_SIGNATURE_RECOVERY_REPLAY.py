"""Replay retained malformed source bytes through scoped and normal adapters."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from scanner.wallet_evidence import _selected_lot_observations, derive_wallet_evidence
from test_position_evidence import WALLET, WINDOW
from test_wallet_evidence import record
from test_real_coverage import closing_raws

first = ROOT / 'evidence/genuine-wallet-batch/read-only-financial-review/MALFORMED_SIGNATURE_RECOVERY_FIRST.json'
source = json.loads(first.read_text())['source']
before = deepcopy(source)
binding = hashlib.sha256((ROOT / 'scanner/wallet_evidence.py').read_bytes()).hexdigest()
try:
    assert _selected_lot_observations([], {}, {}, {}, {}, [], [], [source], WALLET) == []
    rows = [record(raw) for raw in closing_raws()]
    result = derive_wallet_evidence(rows, all_records=rows, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={}, raw_sources=[source])
    assert source == before
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert all(lot['monetary_state'] == 'UNKNOWN' and lot['conditional_lot_profit_sol'] is None
        for lot in result['query_accounting']['supported_selected_lots'])
    outcome = {'status': 'PASS', 'whole_wallet_profit_state': result['metric_dependencies']['profit_sol']['state'],
        'supported_selected_lots': result['query_accounting']['supported_selected_lots'], 'raw_input_unchanged': source == before}
except Exception as exc:
    outcome = {'status': 'FAIL', 'exception': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
print(json.dumps({'scope': 'Distinct malformed-signature/surrogate sibling replay; no genuine or complete-wallet acceptance',
    'source_sha256': binding, 'original_reproduction_sha256': hashlib.sha256(first.read_bytes()).hexdigest(),
    'outcome': outcome}, indent=2))
if outcome['status'] != 'PASS':
    raise SystemExit(1)
