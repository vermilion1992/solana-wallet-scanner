import json,zipfile,hashlib,collections
from pathlib import Path
OUT=Path('/workspace/outputs/mixed-accounting-route-inventory')
inv=json.loads((OUT/'ROUTE_INVENTORY.json').read_text()); a=inv['archives'][0];wallet=a['wallet'];alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def rawbytes(text):
 n=0
 for c in text:n=n*58+alphabet.index(c)
 return b'\0'*(len(text)-len(text.lstrip('1')))+n.to_bytes((n.bit_length()+7)//8,'big')
idlpath=Path('tests/fixtures/retained_protocol_funding/pump_amm.json');idl=json.loads(idlpath.read_text());schemas={x['name']:x for x in idl['instructions']};buy=schemas['buy']; wanted=bytes(buy['discriminator']);rows=[]
with zipfile.ZipFile(a['archive']) as z:
 for rec in a['records']:
  if not rec['success'] or not any('No reviewed spot swap instruction' in x['reason'] for x in rec['unresolved']):continue
  body=z.read(rec['source_member']);obj=json.loads(body);r=next(x for x in obj['result']['data'] if x['transaction']['signatures'][0]==rec['signature']);msg=r['transaction']['message'];meta=r['meta'];keys=msg['accountKeys']+meta.get('loadedAddresses',{}).get('writable',[])+meta.get('loadedAddresses',{}).get('readonly',[])
  for oi,ix in enumerate(msg['instructions']):
   if keys[ix['programIdIndex']]!='pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA' or rawbytes(ix['data'])[:8]!=wanted:continue
   roles={x['name']:keys[p] for x,p in zip(buy['accounts'],ix['accounts'])}
   if roles['user']!=wallet:continue
   quote=[];base=[];exports=[];pdafunding=[]
   for gi,g in enumerate(meta.get('innerInstructions',[])):
    for ii,n in enumerate(g['instructions']):
     b=rawbytes(n.get('data',''));nk=[keys[p] for p in n.get('accounts',[])];np=keys[n['programIdIndex']];path=f'meta.innerInstructions.{gi}.instructions.{ii}'
     if np in ['TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'] and len(b)==10 and b[0]==12 and g['index']==oi:
      qty=int.from_bytes(b[1:9],'little'); dec=b[9]
      if nk[0]==roles['user_quote_token_account'] and nk[1]=='So11111111111111111111111111111111111111112' and nk[3]==wallet and dec==9:quote.append({'path':path,'lamports':qty,'destination':nk[2]})
      if nk[2]==roles['user_base_token_account'] and nk[1]==roles['base_mint']:base.append({'path':path,'quantity_raw':str(qty),'decimals':dec,'source':nk[0]})
     if np=='11111111111111111111111111111111' and len(b)==52 and int.from_bytes(b[:4],'little')==0 and nk[0]==wallet and nk[1]==roles['user_volume_accumulator']:
      pdafunding.append({'path':path,'lamports':int.from_bytes(b[4:12],'little'),'space':int.from_bytes(b[12:20],'little')})
   for xi,n in enumerate(msg['instructions']):
    b=rawbytes(n.get('data',''));nk=[keys[p] for p in n.get('accounts',[])];np=keys[n['programIdIndex']]
    if np in ['TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'] and len(b)==10 and b[0]==12 and nk[0]==roles['user_base_token_account'] and nk[1]==roles['base_mint']:
     exports.append({'path':f'transaction.message.instructions.{xi}','quantity_raw':str(int.from_bytes(b[1:9],'little')),'decimals':b[9],'destination':nk[2]})
   rows.append({'signature':rec['signature'],'original_source_hash':rec['source_hash'],'source_member':rec['source_member'],'slot':r['slot'],'blockTime':r['blockTime'],'raw_fee_lamports':meta['fee'],'user':wallet,'base_mint':roles['base_mint'],'quote_mint':roles['quote_mint'],'base_received':base,'base_exported':exports,'exact_quote_instruction_legs':quote,'quoted_instruction_total_lamports':sum(x['lamports'] for x in quote) if roles['quote_mint']=='So11111111111111111111111111111111111111112' else None,'volume_account_funding':pdafunding,'current_decoder_result':rec['unresolved'],'wallet_pnl':'UNKNOWN','whole_trade_cost_allocation':'UNKNOWN','limitations':['No historical acquisition/population completeness from these rows.','All base units subsequently leave this wallet in a separate original outer instruction; external economic role is unproved.','Exact quote movement is not a wallet-wide trade or economic profit certificate.','IDL names account roles; native Pump-PDA closure refund recipient/amount semantics require independent acceptance, not only zero endpoints.']})
result={'version':'retained-route-worked-opportunities-v1','source_identity':inv['head'],'provider_calls':0,'credential_lookups':0,'source_mutations':0,'full_report_builds':0,'oracle':'Independent tiny base58 + fixed SPL transferChecked raw-byte integer decoding. Account roles read from retained primary PumpSwap IDL, not production route table. Inspection only, not acceptance.','schemas':[{'path':str(idlpath),'sha256':hashlib.sha256(idlpath.read_bytes()).hexdigest(),'commit':'cb188ce08b5069196eef1f3e4a0c43b70099793b'},{'path':'tests/fixtures/compiled_instructions/spl-token-interface-instruction.rs','sha256':hashlib.sha256(Path('tests/fixtures/compiled_instructions/spl-token-interface-instruction.rs').read_bytes()).hexdigest()}],'wallet_authority_buy_candidates':rows}
(OUT/'WORKED_ROUTE_OPPORTUNITIES.json').write_text(json.dumps(result,indent=2)+'\n')
print('genuine wallet-authority candidates',len(rows))
for r in rows:print(r['signature'][:12],r['base_mint'],r['quoted_instruction_total_lamports'],r['base_received'][0]['quantity_raw'] if r['base_received'] else None,'export',r['base_exported'][0]['quantity_raw'] if r['base_exported'] else None)
