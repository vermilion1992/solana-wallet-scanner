import json,zipfile,hashlib,collections,sys
from pathlib import Path
sys.path.insert(0,str(Path('/workspace/solana-wallet-scanner')))
from scanner.investigation import decode_supported_swaps,_keys,_program,_route,_data
from scanner.transaction_format import instruction_view
OUT=Path('/workspace/outputs/mixed-accounting-route-inventory')
ARCHIVES=['evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip','evidence/genuine-report-speed-batch/performance/inputs/genuine200-input.zip']
result={'head':'bad28e11d7a281aa201eb08761e2a17161a9180a','scope':'Original retained raw records only; each record individually interpreted to inspect route support. Does not establish interrecord ordering or complete history. No provider calls/credential lookups.','archives':[]}
for archive in ARCHIVES:
 with zipfile.ZipFile(archive) as z:
  manifest=json.loads(z.read('manifest.json'));wallet=manifest['address']; recs={}; alts=collections.Counter()
  for n in sorted(z.namelist()):
   if not n.startswith('raw/'):continue
   body=z.read(n);digest=hashlib.sha256(body).hexdigest(); obj=json.loads(body); r=obj.get('result') if isinstance(obj,dict) else None
   raws=r.get('data',[]) if isinstance(r,dict) and isinstance(r.get('data'),list) else [r] if isinstance(r,dict) and isinstance(r.get('transaction'),dict) else []
   for raw in raws:
    sig=raw.get('transaction',{}).get('signatures',[None])[0]
    if not sig: continue
    alts[sig]+=1
    if sig not in recs:recs[sig]={'signature':sig,'raw':raw,'evidence_hash':digest,'source_member':n}
  rows=[]
  for sig,rec in recs.items():
   raw=rec['raw']; view=instruction_view(raw);meta=view.get('meta',{});msg=view.get('transaction',{}).get('message',{})
   try:keys=_keys(msg,meta)
   except Exception as e: keys=[]
   routeinfo=[]
   for i,ix in enumerate(msg.get('instructions',[])):
    try:
     prog=_program(ix,keys);payload=_data(ix.get('data')) if 'data' in ix else None
     ri={'index':i,'program':prog,'parsed_kind':ix.get('parsed',{}).get('type'),'discriminator':payload[:8].hex() if payload else None,'payload_bytes':len(payload) if payload else 0,'account_count':len(ix.get('accounts',[]))}
     try:rr=_route(ix,keys);ri['reviewed_route']={k:v for k,v in rr.items() if k!='accounts'}
     except Exception:pass
     routeinfo.append(ri)
    except Exception as e:routeinfo.append({'index':i,'shape_error':str(e)})
   dec=decode_supported_swaps([rec],wallet)
   events=[{k:e.get(k) for k in ['kind','mint','quantity_raw','decimals','gross_sol','fees_sol','amount_sol','path','reason'] if k in e} for e in dec['events']]
   balances=[]
   for phase in ['preTokenBalances','postTokenBalances']:
    for b in meta.get(phase,[]) or []:
     if b.get('owner')==wallet:balances.append({'phase':phase,'index':b.get('accountIndex'),'mint':b.get('mint'),'amount':b.get('uiTokenAmount',{}).get('amount'),'decimals':b.get('uiTokenAmount',{}).get('decimals')})
   row={'signature':sig,'source_hash':rec['evidence_hash'],'source_member':rec['source_member'],'alternative_count':alts[sig]-1,'slot':raw.get('slot'),'blockTime':raw.get('blockTime'),'success':meta.get('err') is None,'fee_lamports':meta.get('fee'),'wallet_payer':bool(keys) and keys[0]==wallet,'outer':routeinfo,'owned_balances':balances,'events':events,'unresolved':dec['unresolved']}
   rows.append(row)
  unsupported=[r for r in rows if r['success'] and not any(e['kind'] in ['buy','sell'] for e in r['events'])]
  summary={'unique_records':len(rows),'alternatives':sum(alts.values())-len(rows),'successes':sum(r['success'] for r in rows),'supported_swaps':sum(any(e['kind'] in ['buy','sell'] for e in r['events']) for r in rows),'unsupported_successes':len(unsupported),'reason_counts':dict(collections.Counter(x['reason'] for r in unsupported for x in r['unresolved'])),'outer_program_counts':dict(collections.Counter(ix.get('program','MALFORMED') for r in unsupported for ix in r['outer']))}
  result['archives'].append({'archive':archive,'archive_sha256':hashlib.sha256(Path(archive).read_bytes()).hexdigest(),'wallet':wallet,'summary':summary,'records':rows})
(OUT/'ROUTE_INVENTORY.json').write_text(json.dumps(result,indent=2)+'\n')
for a in result['archives']:print(json.dumps({'archive':a['archive'],'summary':a['summary']},indent=2))
