import sys,json
sys.path.insert(0,'/workspace/research-search-b')
from scanner.investigation import decode_supported_swaps
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.capture_catalog import WINDOWS
from scanner.mass_search.g3_history import decoder_events_by_mint, _ordered_inventory_rows, completed_episodes
from scanner.mass_search.live_g1 import independent_fifo_worksheet
from scanner.mass_search.settlement import settlement_of
ing=json.load(open('INGEST_RESULT.json'))
def load(a):
    recs=json.load(open(ing['entries'][a]['path']))['result']['data']
    dec=decode_supported_swaps(canonical_decode_records(recs), a)
    bm,tr=decoder_events_by_mint(dec,address=a,window_start=WINDOWS['report_start_inclusive'],window_end=WINDOWS['report_end_exclusive'],acquisition_start=WINDOWS['acquisition_support_start_inclusive'])
    return recs,dec,bm
if __name__=='__main__':
    for a in sys.argv[1:]:
        recs,dec,bm=load(a)
        print('==',a[:6],'decoded events',len(dec['events']),'mints in window',len(bm))
        for m,rows in bm.items():
            raw_order=[r['kind'] for r in rows if not r.get('timestamp_missing')]
            srt=[r['kind'] for r in _ordered_inventory_rows(rows)]
            try: independent_fifo_worksheet([r for r in rows if not r.get('timestamp_missing')]); u='ok'
            except ValueError as e: u='ERR '+str(e)
            try: independent_fifo_worksheet(_ordered_inventory_rows(rows)); s='ok'
            except ValueError as e: s='ERR '+str(e)
            print(' ',m[:6],settlement_of(rows[0])[:4],'raw',''.join(k[0] for k in raw_order)[:40],'sorted',''.join(k[0] for k in srt)[:40],'| unsorted:',u,'| sorted:',s)
        print(' episodes', completed_episodes(bm)['wallet_completed_episodes'])
