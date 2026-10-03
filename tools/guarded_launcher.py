"""Actual CLI under offline acceptance guards. Only for disposable QA data."""
import argparse,atexit,json,os,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--port',required=True);p.add_argument('--guard',required=True);args=p.parse_args()
os.environ.pop('HELIUS_API_KEY',None)
counts={'provider_requests':0,'credential_lookups':0}
def save():Path(args.guard).write_text(json.dumps(counts)+'\n')
def credentials(*a,**kw):counts['credential_lookups']+=1;save();raise AssertionError('Offline acceptance forbids credentials')
async def provider(*a,**kw):counts['provider_requests']+=1;save();raise AssertionError('Offline acceptance forbids provider dispatch')
sys.modules['keyring']=SimpleNamespace(get_keyring=lambda:object(),get_password=credentials,set_password=credentials)
import httpx
httpx.AsyncClient.send=provider;save();atexit.register(save)
from scanner.__main__ import main
raise SystemExit(main(['--data-dir',args.data,'--port',args.port,'--no-browser']))
