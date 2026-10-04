"""Read-only direct generic replay; no wallet acceptance or financial oracle."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import gzip
import hashlib
import httpx
import json
import keyring
from pathlib import Path
import subprocess

from scanner.decoder import decode_transactions

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz'
OUTPUT = ROOT / 'evidence/genuine-wallet-batch/GENERIC_ADMIN_RAW_REPLAY.json'
BASELINE = 'f9756b56326c21826fc8e93a13fc57748cbba2c6'
WALLET = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
raw_bytes = gzip.decompress(RAW.read_bytes())
digest = hashlib.sha256(raw_bytes).hexdigest()
assert digest == '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
rows = json.loads(raw_bytes)['result']['data']
records = [{'signature': row['transaction']['signatures'][0], 'raw': row,
            'evidence_hash': digest} for row in rows]
original = deepcopy(records)
calls = {'provider_requests': 0, 'credential_lookups': 0}
def no_provider(*args, **kwargs):
    calls['provider_requests'] += 1
    raise AssertionError('Provider request forbidden during direct replay')
def no_credential(*args, **kwargs):
    calls['credential_lookups'] += 1
    raise AssertionError('Credential lookup forbidden during direct replay')
httpx.Client.request = no_provider
httpx.AsyncClient.request = no_provider
keyring.get_password = no_credential
baseline_bytes = subprocess.check_output(['git', 'show', BASELINE + ':scanner/decoder.py'], cwd=ROOT)
namespace = {'__name__': 'scanner._f975_generic_replay', '__package__': 'scanner'}
exec(compile(baseline_bytes, BASELINE + ':scanner/decoder.py', 'exec'), namespace)
baseline = namespace['decode_transactions'](records, WALLET)
current = decode_transactions(records, WALLET)
def summary(result):
    return {'events': dict(Counter(event['kind'] for event in result['events'])),
            'unsupported_reasons': dict(Counter(event['reason'] for event in result['events'] if event['kind'] == 'unsupported')),
            'administration': dict(Counter(item['instruction'] for item in result.get('administration', []))),
            'fee_events': [{'signature': event['signature'], 'amount_sol': event['amount_sol'],
                           'paid_by_wallet': event['paid_by_wallet'], 'failed': event['failed']}
                          for event in result['events'] if event['kind'] == 'fee']}
before, after = summary(baseline), summary(current)
assert before['fee_events'] == after['fee_events']
assert after['administration']['initializeImmutableOwner'] == 109
assert before['events']['unsupported'] - after['events']['unsupported'] == 109
assert after['events']['unsupported'] > 0
assert not any(event['kind'] in ('buy', 'sell') for event in current['events'])
assert records == original
assert gzip.decompress(RAW.read_bytes()) == raw_bytes
assert calls == {'provider_requests': 0, 'credential_lookups': 0}
output = {'scope': 'Direct generic decoder only, all87 original lifetime indexed records. This is not the saved report fallback-event population or wallet qualification.',
          'baseline_commit': BASELINE, 'baseline_decoder_sha256': hashlib.sha256(baseline_bytes).hexdigest(),
          'current_decoder_sha256': hashlib.sha256((ROOT / 'scanner/decoder.py').read_bytes()).hexdigest(),
          'new_test_sha256': hashlib.sha256((ROOT / 'tests/test_generic_administration.py').read_bytes()).hexdigest(),
          'shared_compiled_normalizer_sha256': hashlib.sha256((ROOT / 'scanner/compiled_instructions.py').read_bytes()).hexdigest(),
          'raw_input': str(RAW.relative_to(ROOT)), 'raw_input_sha256': digest, 'raw_records': len(rows),
          'before': before, 'after': after,
          'original_records_unchanged': True, 'original_raw_bytes_unchanged': True,
          'fees_exactly_preserved': True, 'unknown_routes_preserved': True,
          'administration_scope': 'Diagnostic original-reference facts only; no ledger event, cost basis, classification, ownership population, policy or qualification proof.',
          'administrative_receipts': current['administration'], 'offline': calls,
          'PRODUCT_READY': False, 'new_application_acceptance': False}
OUTPUT.write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({'records': len(rows), 'before_events': before['events'], 'after_events': after['events'],
                  'administration': after['administration'], 'offline': calls,
                  'source': output['current_decoder_sha256'], 'output_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}, indent=2))
