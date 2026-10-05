
import atexit, asyncio, json, os, socket, sys
from pathlib import Path
from types import SimpleNamespace
import httpx
fixture_path = Path(os.environ['SCREENING_BROWSER_FIXTURES'])
fixture = json.loads(fixture_path.read_text())
guard_path = Path(os.environ['SCREENING_BROWSER_GUARD'])
counts = {'synthetic_provider_requests': 0, 'external_provider_requests': 0,
          'credential_lookups': 0, 'blocked_requests': 0, 'synthetic_subscriptions': 0,
          'transport': 'explicit offline synthetic test, no genuine provider collection', 'requests': []}
if guard_path.exists(): counts = json.loads(guard_path.read_text())
def save(): guard_path.write_text(json.dumps(counts, indent=2)+'\n')
def credential(*a, **k):
    counts['credential_lookups'] += 1; save()
    raise AssertionError('Offline browser verification forbids credential lookup')
sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)
def event(kind, method, path):
    counts[kind] += 1
    counts['requests'].append({'kind':kind, 'method':method, 'path':path})
    save()
async def transport(self, request):
    host, path = request.url.host, request.url.path
    if host == 'api.jup.ag' and path == '/swap/v2/order' and request.method == 'GET':
        params = dict(request.url.params)
        if set(params) - {'inputMint','outputMint','amount','swapMode','slippageBps'} or 'taker' in params:
            raise AssertionError('Paper quote must never include taker or execution parameters')
        event('synthetic_provider_requests', 'quote-only', path)
        amount = int(params['amount']); entering = params['inputMint'] == fixture['wsol']
        output = amount * 100 if entering else amount // 125
        return httpx.Response(200, request=request, json={'inputMint': params['inputMint'], 'outputMint': params['outputMint'],
            'inAmount': str(amount), 'outAmount': str(output), 'otherAmountThreshold': str(output),
            'swapMode':'ExactIn', 'slippageBps': int(params.get('slippageBps',0)), 'transaction':None,
            'taker':None, 'router':'metis', 'requestId':'synthetic-browser-quote-'+str(counts['synthetic_provider_requests']),
            'feeMint':fixture['wsol'], 'feeBps':10, 'platformFee':{'feeBps':10, 'feeMint':fixture['wsol']},
            'priceImpact':-0.1, 'priceImpactPct':'-0.001',
            'signatureFeeLamports':0, 'prioritizationFeeLamports':0, 'rentFeeLamports':0,
            'routePlan':[{'percent':100, 'bps':10000, 'swapInfo':{'label':'Synthetic schema route'}}],
            'synthetic_test_note':'Explicit offline transport fixture; no real quote or execution'})
    if host in ('api.mainnet-beta.solana.com','api.devnet.solana.com') and request.method == 'POST':
        body = json.loads(request.content)
        method, params = body.get('method'), body.get('params',[])
        event('synthetic_provider_requests', method, path)
        if method == 'getTransaction': result = deepcopy_json(fixture['transactions'].get(params[0]))
        elif method == 'getSignaturesForAddress':
            options = params[1] if len(params)>1 else {}
            result = [] if options.get('before') else fixture['entries'][:options.get('limit',1000)]
        elif method == 'getAccountInfo':
            if params[0] == fixture['wallet']:
                result = {'context':{'slot':fixture['slot']}, 'value':{'owner':'11111111111111111111111111111111','executable':False,'lamports':10_000_000_000,'data':['','base64'],'space':0}}
            else: result = {'context':{'slot':fixture['slot']},'value':None}
        elif method == 'getSlot': result = fixture['slot']
        elif method == 'getBalance': result = {'context':{'slot':fixture['slot']},'value':10_000_000_000}
        elif method == 'getTokenAccountsByOwner': result = {'context':{'slot':fixture['slot']},'value':[]}
        else:
            event('blocked_requests', method or 'unknown-rpc', path)
            raise AssertionError('Unsupported offline fixture RPC: '+str(method))
        return httpx.Response(200, request=request, json={'jsonrpc':'2.0','id':body.get('id'), 'result':result})
    event('blocked_requests', request.method, host+path)
    raise AssertionError('Offline browser verification blocked external dispatch: '+host+path)
def deepcopy_json(value): return json.loads(json.dumps(value))
httpx.AsyncHTTPTransport.handle_async_request = transport
# A separate socket guard prevents accidental transport substitutions.
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
def connect(self, address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
        event('blocked_requests','socket-connect',str(address[0]))
        raise OSError('Offline verification prohibits external sockets')
    return original_connect(self,address)
def connect_ex(self,address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
        event('blocked_requests','socket-connect',str(address[0]))
        return 111
    return original_connect_ex(self,address)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
# Supply a synthetic provider WebSocket, not application or browser route mocks.
class SyntheticSocket:
    def __init__(self): self.index = 0; self.request = None
    async def __aenter__(self):
        event('synthetic_subscriptions','connect','address-specific logsSubscribe')
        raise OSError('Synthetic subscription unavailable')
        return self
    async def __aexit__(self,*args): return None
    async def send(self,raw):
        self.request = json.loads(raw)
        assert self.request['method'] == 'logsSubscribe'
        assert self.request['params'][0]['mentions'] == [fixture['wallet']]
    async def recv(self): return json.dumps({'jsonrpc':'2.0','id':self.request['id'],'result':5})
    def __aiter__(self): return self
    async def __anext__(self):
        sequence = fixture['forward_signatures']
        if self.index >= 3:
            await asyncio.Future()
        index = self.index; self.index += 1
        await asyncio.sleep(.3 if index == 0 else .05 if index == 1 else 10)
        signature = sequence[0] if index < 2 else sequence[1]
        raw = fixture['transactions'][signature]
        return json.dumps({'jsonrpc':'2.0','method':'logsNotification','params':{'subscription':5,
            'result':{'context':{'slot':raw['slot']},'value':{'signature':signature,'err':None,'logs':['Synthetic offline browser notification']}}}})
def synthetic_connect(url,**kwargs):
    assert url == 'wss://api.mainnet-beta.solana.com'
    return SyntheticSocket()
import scanner.observer
scanner.observer.connect = synthetic_connect
save(); atexit.register(save)
