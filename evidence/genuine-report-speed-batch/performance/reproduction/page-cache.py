"""Read-only page-parse benchmark; this is not wallet acceptance evidence."""
import base64
from contextlib import nullcontext
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
import sys

sys.path.insert(0, '/workspace/solana-wallet-scanner')
import scanner.indexed_input as indexed

ROOT = Path('/workspace/outputs/report-proof-profile/baseline-ab62858/private-runtime/evidence')
OUT = Path('/workspace/outputs/report-proof-profile/validated-page-cache-benchmark.json')
HASHES = ('dc797aba5db7cd7884dc5719c46977080a40cdee31a863d8d310b10f1419e2d3',
          '58a27d6903c5cd63d4272430fa62a2d28c8adbaf8fc869d663920f9ca63b95e0')
pages, inputs = [], []
for digest in HASHES:
    path = ROOT / (digest + '.json.gz')
    original = path.read_bytes()
    raw = gzip.decompress(original)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise SystemExit('Original source archive hash mismatch')
    envelope = json.loads(raw)
    request = json.loads(base64.b64decode(envelope['request_base64']))
    wallet = request['params'][0]
    pages.append((envelope, wallet))
    inputs.append({'source_hash':digest,'compressed_sha256':hashlib.sha256(original).hexdigest(),
                   'compressed_bytes':len(original),'canonical_bytes':len(raw)})

results = []
for enabled in (False, True):
    measured, result_hashes = 0.0, []
    with patch.object(indexed, '_json', wraps=indexed._json) as parser:
        with patch.object(indexed, 'source_bytes', wraps=indexed.source_bytes) as exact:
            with indexed.validated_page_context() if enabled else nullcontext():
                # 42 validations, matching the observed invocation count. This
                # distribution is explicit; it is not an application timing.
                for repetition in range(21):
                    for envelope, wallet in pages:
                        begun = perf_counter()
                        value = indexed.validate_page_envelope(envelope, wallet)
                        measured += perf_counter() - begun
                        result_hashes.append(hashlib.sha256(json.dumps(value, ensure_ascii=False,
                            allow_nan=False, separators=(',', ':')).encode()).hexdigest())
                stats = indexed.validated_page_cache_stats()
            results.append({'cache_enabled':enabled,'page_validations':42,
                'validation_seconds':measured,'bounded_JSON_parses':parser.call_count,
                'exact_source_byte_verifications':exact.call_count,'stats':stats,
                'ordered_result_sha256':result_hashes})
if results[0]['ordered_result_sha256'] != results[1]['ordered_result_sha256']:
    raise SystemExit('Cache changed a page result')
receipt = {'kind':'read-only-identical-input-page-cache-benchmark','state':'PASS',
    'scope':'Repeated page interpretation only; not application/financial acceptance or full import timing',
    'inputs':inputs,'results':results,'all_result_bytes_identical':True,
    'validation_speedup':results[0]['validation_seconds']/results[1]['validation_seconds'],
    'provider_requests':0,'credential_lookups':0,'wallet_qualification_claim':False}
OUT.write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({key:receipt[key] for key in ('state','validation_speedup','all_result_bytes_identical')}))
print(json.dumps([{key:row[key] for key in ('cache_enabled','validation_seconds','bounded_JSON_parses',
    'exact_source_byte_verifications','stats')} for row in results]))
