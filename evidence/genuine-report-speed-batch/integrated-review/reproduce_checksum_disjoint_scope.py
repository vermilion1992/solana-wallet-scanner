"""Unsigned direct-interface probe, no provider or credential execution."""
from pathlib import Path
import hashlib,json
from scanner.inventory_evidence import inventory_source,derive_inventory_evidence,inventory_request_affinities
from scanner.json_boundary import canonical_bytes
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
SYSTEM='11111111111111111111111111111111'
def address(seed):
 alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';number=int.from_bytes(bytes([seed])*32,'big');encoded=''
 while number:number,digit=divmod(number,58);encoded=alphabet[digit]+encoded
 return encoded
WALLET=address(21);OTHER=address(22)
def source(method,params,value):
 request=json.dumps({'jsonrpc':'2.0','id':7,'method':method,'params':params}).encode()
 response=json.dumps({'jsonrpc':'2.0','id':7,'result':{'context':{'slot':1000},'value':value}}).encode()
 payload=inventory_source(request,response)
 return {'kind':'inventory-source','hash':hashlib.sha256(canonical_bytes(payload)).hexdigest(),'payload':payload}
base=[source('getAccountInfo',[WALLET,{'encoding':'base64','commitment':'finalized'}],{'owner':SYSTEM,'executable':False,'lamports':1000,'data':['','base64']}),source('getBalance',[WALLET,{'commitment':'finalized'}],1000)]
for program in (TOKEN,TOKEN2022):base.append(source('getTokenAccountsByOwner',[WALLET,{'programId':program},{'encoding':'jsonParsed','commitment':'finalized'}],[]))
valid_disjoint=source('getBalance',[OTHER,{'commitment':'finalized'}],1000)
invalid_disjoint={**valid_disjoint,'hash':'0'*64}
results={}
for name,rows in [('baseline',base),('valid-disjoint',base+[valid_disjoint]),('checksum-invalid-disjoint',base+[invalid_disjoint])]:
 value=derive_inventory_evidence(rows,wallet=WALLET)
 results[name]={'same_slot_inventory_state':value['components']['same_slot_inventory']['state'],'native_balance_state':value['components']['native_balance']['state'],'source_dependencies':value['source_dependencies'],'affinities':inventory_request_affinities(rows,wallet=WALLET)}
obj={'kind':'independent-unsigned-direct-interface-probe','draft_module_sha256':hashlib.sha256(Path('/workspace/solana-wallet-scanner/scanner/inventory_evidence.py').read_bytes()).hexdigest(),'results':results,'checksum_invalid_source_retained':invalid_disjoint['hash'] in results['checksum-invalid-disjoint']['source_dependencies'],'application_API_executed':False,'provider_requests':0,'credential_lookups':0,'network_requests':0,'source_or_Git_mutations':False}
p=Path('/workspace/outputs/genuine-wallet-report-review/CHECKSUM_DISJOINT_SCOPE_PROBE.json');p.write_text(json.dumps(obj,indent=2)+'\n');print(json.dumps({'baseline':results['baseline']['same_slot_inventory_state'],'valid_disjoint':results['valid-disjoint']['same_slot_inventory_state'],'checksum_invalid_disjoint':results['checksum-invalid-disjoint']['same_slot_inventory_state'],'checksum_invalid_source_retained':obj['checksum_invalid_source_retained'],'report':str(p)}))
