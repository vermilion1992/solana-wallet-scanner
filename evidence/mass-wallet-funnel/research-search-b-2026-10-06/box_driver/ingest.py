#!/usr/bin/env python3
"""Offline ingest of research-search captures through the app's own replay path (LOCAL)."""
import hashlib, json, sys
from pathlib import Path
REPO = Path(sys.argv[1] if len(sys.argv) > 1 else '/workspace/research-search-b')
DATA = Path(sys.argv[2] if len(sys.argv) > 2 else '/workspace/research-search-b-live/appdata')
sys.path.insert(0, str(REPO))
LIVE = Path('/workspace/research-search-b-live')
from scanner.storage import Store
from scanner.mass_search import workflow as W
from scanner.mass_search.capture_catalog import WINDOWS, catalog_by_address as base_catalog
from scanner.investigation import DECODER_VERSION

manifest = json.loads((LIVE / 'CAPTURE_MANIFEST.json').read_text())['pages']
order = [c['address'] for c in W.research_search_proposal()['selected_candidates']]
combined_dir = LIVE / 'combined'; combined_dir.mkdir(exist_ok=True)
entries = {}
for addr in order:
    pages = sorted([m for m in manifest.values() if m['address'] == addr], key=lambda m: m['page_index'])
    data, src = [], []
    for m in pages:
        raw = Path(m['raw_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == m['raw_sha256'], 'raw drift'
        data.extend(json.loads(raw)['result']['data'])
        src.append({'page_index': m['page_index'], 'raw_sha256': m['raw_sha256']})
    sigs = [r['transaction']['signatures'][0] for r in data]
    assert len(sigs) == len(set(sigs)), f'duplicate signatures across pages for {addr}'
    body = {'kind': 'research-search-combined-capture-v1', 'address': addr, 'source_pages': src,
            'result': {'data': data}}
    path = combined_dir / f'{addr}.json'
    path.write_text(json.dumps(body, separators=(',', ':')))
    entries[addr] = {
        'address': addr, 'mode': 'genuine_gta', 'path': str(path),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'corpus_kind': 'GENUINE_REPLAY',
        'label': 'Genuine ranked-100 research-search capture (2 newest-first GTA pages)', 'not_proof': False,
        'raise_on_replay': False, 'windows': dict(WINDOWS), 'decoder_version': DECODER_VERSION,
        'evidence_status': 'cached_capture', 'authorization_id': 'live-ranked100-research-search-2026-10-06-mitch',
        'source_id': 'ranked100-research-search-b-replay', 'source_pages': src}

def patched():
    out = base_catalog(); out.update(entries); return out
W.catalog_by_address = patched
DATA.mkdir(parents=True, exist_ok=True)
store = Store(DATA)
results = {}
try:
    for addr in order:
        try:
            r = W.replay_captured_wallet(store, addr, force=True)
            results[addr] = {'report_id': r['report_id'], 'visible_report': r.get('visible_report')}
        except Exception as exc:
            import traceback
            tb = traceback.extract_tb(exc.__traceback__)
            results[addr] = {'error': f'{type(exc).__name__}: {exc}', 'where': [f'{Path(f.filename).name}:{f.lineno}:{f.name}' for f in tb[-4:]]}
finally:
    store.close()
json.dump({'entries': entries, 'results': results}, open(LIVE / 'INGEST_RESULT.json', 'w'), indent=2, default=str)
print(json.dumps(results, indent=1))
