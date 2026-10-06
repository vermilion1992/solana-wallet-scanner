"""Independent recon using tools/independent_capture_reconciliation.py::_fifo (no app accounting)."""
import sys, json, importlib.util
from decimal import Decimal
from pathlib import Path
REPO = Path(sys.argv[1] if len(sys.argv) > 1 else '/workspace/research-search-b')
DATA = Path(sys.argv[2] if len(sys.argv) > 2 else '/workspace/research-search-b-live/appdata')
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else '/workspace/research-search-b-live/recon')
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location('icr', REPO / 'tools/independent_capture_reconciliation.py')
icr = importlib.util.module_from_spec(spec); spec.loader.exec_module(icr)
from datetime import datetime
from scanner.investigation import decode_supported_swaps
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.capture_catalog import WINDOWS
from scanner.mass_search.settlement import USDC
from scanner.storage import Store
ing = json.load(open('/workspace/research-search-b-live/INGEST_RESULT.json'))
def ts(s): return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
acq, end = ts(WINDOWS['acquisition_support_start_inclusive']), ts(WINDOWS['report_end_exclusive'])
OUT.mkdir(parents=True, exist_ok=True)
store = Store(DATA)
summary = {}
for addr, entry in ing['entries'].items():
    recs = json.loads(Path(entry['path']).read_text())['result']['data']
    dec = decode_supported_swaps(canonical_decode_records(recs), addr)
    per_asset = {'SOL': [], 'USDC': []}
    for ev in dec['events']:
        if ev.get('kind') not in ('buy', 'sell'): continue
        t = ev.get('timestamp')
        if not isinstance(t, (int, float)) or t < acq or t >= end: continue
        usdc = ev.get('settlement_mint') == USDC or ev.get('amount_usdc') not in (None, '')
        asset = 'USDC' if usdc else 'SOL'
        per_asset[asset].append({'kind': ev['kind'], 'mint': ev['mint'], 'quantity_raw': ev['quantity_raw'],
            'consideration': (ev.get('amount_usdc') if usdc else ev.get('amount_sol')) or '0',
            'fee_sol': ev.get('fee_sol') or '0', 'signature': ev.get('signature'), 'timestamp': t, 'order': ev.get('order')})
    fifo = {}
    for asset, trades in per_asset.items():
        if not trades: continue
        trades.sort(key=lambda r: (r['timestamp'], r.get('order') if isinstance(r.get('order'), int) else 0, r['signature'] or ''))
        fifo[asset] = icr._fifo(trades, asset=asset)
    res = ing['results'][addr]
    rep = store.get('reports', res['report_id']) if res.get('report_id') else None
    app = {}
    if rep:
        ws = rep.get('worksheet') or {}
        app = {'total_profit_sol': ws.get('total_profit_sol'), 'total_profit_usdc': ws.get('total_profit_usdc'),
               'sale_net_profit_sol': ws.get('sale_net_profit_sol'), 'sale_net_profit_usdc': ws.get('sale_net_profit_usdc')}
    cmp = {}
    for asset, f in fifo.items():
        indep_sales = [s['net_profit'] for s in f['known_cost_sells']]
        app_sales = app.get(f'sale_net_profit_{asset.lower()}') or []
        app_total = app.get(f'total_profit_{asset.lower()}')
        same_total = (app_total is not None and f['total_profit'] is not None and Decimal(str(app_total)).quantize(Decimal('1e-9')) == Decimal(f['total_profit']))
        same_sales = sorted(Decimal(x).quantize(Decimal('1e-9')) for x in app_sales) == sorted(Decimal(x) for x in indep_sales)
        status = 'AGREE' if (same_total and same_sales) else ('APP_MISSING' if not app_sales and indep_sales else ('BOTH_EMPTY' if not app_sales and not indep_sales else 'DISAGREE'))
        cmp[asset] = {'independent_total': f['total_profit'], 'app_total': app_total, 'independent_known_cost_sells': len(indep_sales),
                      'app_sales': len(app_sales), 'independent_unresolved_basis_sales': len(f['unresolved_basis_sales']),
                      'independent_open_lots': len(f['open_lots']), 'status': status}
    out = {'kind': 'independent-capture-reconciliation-v1', 'imports_app_accounting': False, 'wallet': addr,
           'capture_sha256': entry['sha256'], 'source_pages': entry['source_pages'], 'window': WINDOWS,
           'decoder_is_shared_with_app': True, 'fifo': fifo, 'app_report_id': res.get('report_id'), 'app_error': res.get('error'),
           'comparison': cmp, 'PRODUCT_READY': False}
    (OUT / f'{addr}.json').write_text(json.dumps(out, indent=2) + '\n')
    summary[addr] = {'app_error': res.get('error'), 'comparison': cmp}
store.close()
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, indent=2) + '\n')
for a, s in summary.items():
    print(a[:6], s['app_error'] or '', json.dumps(s['comparison']))
