import json, sys
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, '/workspace/research-search-b')
from scanner.storage import Store
from scanner.mass_search import workflow as W
LIVE = Path('/workspace/research-search-b-live')
ing = json.load(open(LIVE / 'INGEST_RESULT.json'))
man = json.load(open(LIVE / 'CAPTURE_MANIFEST.json'))['pages']
cands = {c['address']: c for c in W.research_search_proposal()['selected_candidates']}
store = Store(LIVE / 'appdata')
view = W.ranked_workflow_view(store)
screen = {r['address']: r for r in view['research_screen']['rows']}
rows = []
for addr in ing['entries']:
    rec = json.load(open(LIVE / 'recon' / f'{addr}.json'))
    res = ing['results'][addr]
    rep = store.get('reports', res['report_id']) if res.get('report_id') else None
    prof = (rep or {}).get('research_profile') or {}
    pages = [m for m in man.values() if m['address'] == addr]
    # independent flat-to-flat episodes per asset from recon trade order
    indep = {}
    for asset, f in rec['fifo'].items():
        sells = f['known_cost_sells']; unres = f['unresolved_basis_sales']; open_lots = f['open_lots']
        mints_sold = defaultdict(int)
        for s in sells: mints_sold[s['mint']] += 1
        open_mints = {o['mint'] for o in open_lots}
        unres_mints = {u['mint'] for u in unres}
        closed_mints = [m for m in mints_sold if m not in open_mints]
        indep[asset] = {'matched_pnl': f['total_profit'], 'known_cost_sales': len(sells), 'unresolved_basis_sales': len(unres),
                        'open_lots': len(open_lots), 'mints_fully_closed_in_sample': len(closed_mints),
                        'partial_sales_on_unbacked_mints': len([m for m in mints_sold if m in unres_mints])}
    ws = (rep or {}).get('worksheet') or {}
    rows.append({
        'address': addr, 'short': f'{addr[:4]}…{addr[-4:]}', 'provider_rank': cands[addr]['provider_rank'],
        'provider_trade_count': cands[addr]['trade_count'], 'pages': len(pages), 'records': sum(m['record_count'] for m in pages),
        'newest_block_time': max(m['newest_block_time'] for m in pages), 'oldest_block_time': min(m['oldest_block_time'] for m in pages),
        'app_report_id': res.get('report_id'), 'app_error': res.get('error'),
        'app_decoded_swaps_all_pages': ((rep or {}).get('coverage') or {}).get('decoded_swaps'),
        'app_in_window_trade_events': len((rep or {}).get('events') or []),
        'app_completed_known_cost_positions': prof.get('completed_known_cost_positions'),
        'app_wallet_completed_episodes': (rep or {}).get('wallet_completed_episodes'),
        'app_matched_pnl': {'SOL': ws.get('total_profit_sol'), 'USDC': ws.get('total_profit_usdc')},
        'app_unresolved_basis_sales': prof.get('unresolved_basis_sales'),
        'app_hold_t90_seconds': prof.get('hold_t90_seconds'), 'app_final_hold_seconds': prof.get('final_hold_seconds'),
        'app_qualification_category': (prof.get('qualification_category') or {}).get('category') or (screen.get(addr, {}).get('qualification_category') or {}).get('category'),
        'app_research_screen_outcome': screen.get(addr, {}).get('outcome'),
        'app_worksheet_reconciliation': ((rep or {}).get('worksheet_reconciliation') or {}).get('status'),
        'independent': indep, 'recon_comparison': rec['comparison'],
        'meets_two_fixed_screen_defaults_on_app_numbers': bool(prof) and int(prof.get('completed_known_cost_positions') or 0) >= 3,
    })
store.close()
out = {'kind': 'research-search-b-per-wallet-results-v1', 'attempt': 1, 'application_commit': '78678d18d8f74304380588410bdef2ae4bc4530b',
       'window': ing['entries'][next(iter(ing['entries']))]['windows'], 'research_screen': {k: view['research_screen'][k] for k in ('outcome', 'counts', 'thresholds_fixed_before_evaluation')},
       'rows': rows, 'PRODUCT_READY': False}
(LIVE / 'RESULTS_TABLE.json').write_text(json.dumps(out, indent=2) + '\n')
for r in rows:
    i = r['independent']
    print(r['short'], r['provider_rank'], r['pages'], r['app_in_window_trade_events'], r['app_completed_known_cost_positions'], r['app_matched_pnl'], {a: (v['matched_pnl'], v['known_cost_sales'], v['unresolved_basis_sales'], v['open_lots'], v['mints_fully_closed_in_sample']) for a, v in i.items()}, r['app_qualification_category'], r['app_research_screen_outcome'], r['app_error'] or '')
print(out['research_screen'])
