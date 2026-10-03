"""Executable finite-world development coverage, never real-wallet acceptance."""
from copy import deepcopy
from decimal import Decimal
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from scanner.archive_input import (import_archive, load_archive, decode_archive, analyze_archive,
                                  canonical_bytes, MAX_ENTRY, MAX_UPLOAD)
from scanner.storage import Store
from scanner.app import create_app

FIXTURE = Path(__file__).resolve().parents[1]/'scanner/examples/archive-wallet-synthetic.json'


def bundle():
    return json.loads(FIXTURE.read_text())


def packed(value):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', canonical_bytes(value['manifest']))
        for digest, payload in value['payloads'].items():
            archive.writestr(f'archives/{digest}.json.gz', gzip.compress(canonical_bytes(payload), mtime=0))
    return stream.getvalue()


def derive(store, value):
    digest = import_archive(store, packed(value))
    loaded = load_archive(store, digest)
    events, swaps = decode_archive(loaded)
    result, events, coverage = analyze_archive(loaded, events)
    return result, coverage, digest


def test_raw_inputs_reach_fifo_with_partial_sales_loss_breakeven_reentry_and_failed_fee(tmp_path):
    result, coverage, _ = derive(Store(tmp_path), bundle())
    assert coverage['population_state'] == 'PASS'
    assert coverage['real_acceptance'] == 'NOT_APPLICABLE_SYNTHETIC'
    # Independent pencil ledger: A1 3 - 1 - 3*0.000005; A2/B each 1-2-2*0.000005;
    # C 1.000010-1-2*0.000005; D 1.5-1-2*0.000005; failed fee 0.000005.
    expected = {'profit_sol': '0.49995', 'median_roi_pct': '0', 'win_rate_pct': '40',
                'median_hold_hours': '24', 'completed_positions': '5', 'completed_positions_90d': '5',
                'traded_mints': '4', 'rapid_sale_pct': '0', 'avg_buys': '1', 'avg_sells': '1.2',
                'positive_weeks': '2', 'economic_pnl_sol': '0.499955', 'observed_network_fees_sol': '0.000055'}
    assert {k: result['metrics'][k]['value'] for k in expected} == expected
    assert sorted(p['pnl_sol'] for p in result['positions']) == sorted(['1.999985','-1.00001','-1.00001','0','0.49999'])
    assert len(coverage['account_quantity_points']) == 11
    assert all('historical_marks' not in coverage['metric_requirements'][k]['dependencies'] for k in ('profit_sol','median_hold_hours'))
    with __import__('decimal').localcontext() as ctx:
        ctx.prec = 192
        assert Decimal(result['metrics']['realised_roi_pct']['value']) == Decimal('0.49995')/Decimal('7.000025')*100


@pytest.mark.parametrize('loss', ['valuation', 'classification', 'ownership', 'transaction', 'coherent_omission'])
def test_required_source_loss_revokes_only_supported_dependencies_and_exact_restore_recovers(tmp_path, loss):
    store = Store(tmp_path); value = bundle(); result, coverage, digest = derive(store, value)
    manifest = value['manifest']
    selected = manifest['transactions'][2]['hash']
    lost = {'valuation': manifest['valuation_hash'], 'classification': manifest['classification_hashes'][0],
            'ownership': manifest['world_hash'], 'transaction': selected, 'coherent_omission': selected}[loss]
    path = store.path/'evidence'/f'{lost}.json.gz'; before = path.read_bytes(); path.unlink()
    if loss == 'coherent_omission':
        altered = deepcopy(value); altered['manifest']['transactions'] = [r for r in altered['manifest']['transactions'] if r['hash'] != selected]
        del altered['payloads'][selected]
        _, _, altered_digest = derive(store, altered)
        loaded = load_archive(store, altered_digest)
    else:
        loaded = load_archive(store, digest)
    events, _ = decode_archive(loaded); changed, _, changed_coverage = analyze_archive(loaded, events)
    if loss == 'valuation':
        assert changed['metrics']['economic_pnl_sol']['status'] == 'unknown'
        assert changed['metrics']['profit_sol']['value'] == '0.49995'
        assert changed['metrics']['median_hold_hours']['value'] == '24'
    else:
        assert changed['metrics']['profit_sol']['status'] == 'unknown'
    if loss in ('valuation', 'classification', 'ownership'):
        assert changed['metrics']['observed_network_fees_sol']['value'] == '0.000055'
    assert changed_coverage['source_receipts'] or changed_coverage['gaps']
    path.write_bytes(before)
    loaded = load_archive(store, digest); events, _ = decode_archive(loaded)
    restored, _, _ = analyze_archive(loaded, events)
    assert restored['metrics'] == result['metrics']


def test_duplicates_and_reference_permutation_do_not_count_trades_or_fees_twice(tmp_path):
    value = bundle(); store = Store(tmp_path); original, _, _ = derive(store, value)
    value['manifest']['transactions'] = list(reversed(value['manifest']['transactions'] * 2))
    duplicate, _, _ = derive(store, value)
    assert duplicate['metrics'] == original['metrics'] and duplicate['positions'] == original['positions']


def replace_payload(value, digest, payload):
    replacement = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    value['payloads'].pop(digest)
    value['payloads'][replacement] = payload
    return replacement


def test_shorter_verification_history_does_not_erase_proved_reporting_period(tmp_path):
    value = bundle(); world_hash = value['manifest']['world_hash']
    world = deepcopy(value['payloads'][world_hash]); world['start'] = '2026-05-20T00:00:00+00:00'
    value['manifest']['world_hash'] = replace_payload(value, world_hash, world)
    result, coverage, _ = derive(Store(tmp_path), value)
    assert result['metrics']['profit_sol']['value'] == '0.49995'
    assert result['metrics']['positive_weeks']['value'] == '2'
    assert result['metrics']['completed_positions']['value'] == '5'
    assert result['metrics']['completed_positions_90d']['status'] == 'unknown'


def test_unknown_trade_fee_keeps_quantity_only_timing_but_not_profit(tmp_path):
    value = bundle(); original = value['manifest']['transactions'][1]
    raw = deepcopy(value['payloads'][original['hash']]); raw['meta']['fee'] = None
    replacement = replace_payload(value, original['hash'], raw)
    original['hash'] = replacement
    world_hash = value['manifest']['world_hash']; world = deepcopy(value['payloads'][world_hash])
    world['transactions'][1]['hash'] = replacement
    value['manifest']['world_hash'] = replace_payload(value, world_hash, world)
    result, coverage, _ = derive(Store(tmp_path), value)
    assert result['metrics']['profit_sol']['status'] == 'unknown'
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert coverage['quantity_population_state'] == 'PASS'
    assert len(coverage['quantity_episodes']) == 5
    assert sorted(e['hold_hours']['value'] for e in coverage['quantity_episodes']) == sorted(['24','24','24','72','696'])


@pytest.mark.parametrize('field,bad', [('slot',[]),('meta',[]),('transaction',None),('blockTime',None)])
def test_malformed_native_record_retains_gap_without_crashing(tmp_path, field, bad):
    value = bundle(); row=value['manifest']['transactions'][0]
    raw=deepcopy(value['payloads'][row['hash']]);raw[field]=bad
    replacement=replace_payload(value,row['hash'],raw);row['hash']=replacement
    result, coverage, _=derive(Store(tmp_path),value)
    assert result['metrics']['profit_sol']['status']=='unknown'
    assert coverage['population_state']=='UNKNOWN'


def test_unknown_incoming_basis_is_not_a_free_profitable_acquisition(tmp_path):
    value=bundle();row=value['manifest']['transactions'][0];raw=deepcopy(value['payloads'][row['hash']])
    instruction=deepcopy(raw['meta']['innerInstructions'][0]['instructions'][1])
    raw['transaction']['message']['instructions']=[instruction];raw['meta']['innerInstructions']=[]
    raw['meta']['postTokenBalances'][1]=deepcopy(raw['meta']['preTokenBalances'][1])
    raw['meta']['postTokenBalances'][3]=deepcopy(raw['meta']['preTokenBalances'][3])
    raw['meta']['postBalances'][2]=raw['meta']['preBalances'][2]
    raw['meta']['postBalances'][4]=raw['meta']['preBalances'][4]
    replacement=replace_payload(value,row['hash'],raw);row['hash']=replacement
    world_hash=value['manifest']['world_hash'];world=deepcopy(value['payloads'][world_hash]);world['transactions'][0]['hash']=replacement
    value['manifest']['world_hash']=replace_payload(value,world_hash,world)
    store=Store(tmp_path);result,coverage,digest=derive(store,value)
    loaded=load_archive(store,digest);events,_=decode_archive(loaded)
    assert any(e['kind']=='transfer_in' and e.get('basis_sol') is None for e in events)
    assert result['metrics']['profit_sol']['status']=='unknown'
    assert any(p['basis_sol'] is None and p['pnl_sol'] is None for p in result['positions'])
    assert result['metrics']['observed_network_fees_sol']['value']=='0.000055'


def test_compressed_expansion_and_upload_limits_are_enforced_without_writes(tmp_path):
    store=Store(tmp_path)
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('manifest.json',canonical_bytes(bundle()['manifest']))
        archive.writestr('archives/'+'a'*64+'.json.gz',gzip.compress(b' '*(MAX_ENTRY+1)))
    with pytest.raises(ValueError,match='Expanded'):import_archive(store,stream.getvalue())
    with pytest.raises(ValueError,match='upload'):import_archive(store,b' '*(MAX_UPLOAD+1))
    assert store.list('artifacts')==[]


@pytest.mark.parametrize('variant',['program-id','program-label','inner-index','inner-group','inner-instructions'])
@pytest.mark.parametrize('role',['selected','alternative'])
def test_malformed_instruction_containers_are_dependencies_with_preserved_fee_observations(tmp_path,variant,role):
    value=bundle();row=value['manifest']['transactions'][1];raw=deepcopy(value['payloads'][row['hash']])
    if variant=='program-id':raw['transaction']['message']['instructions'][0]['programId']={}
    elif variant=='program-label':
        raw['transaction']['message']['instructions'][0]['programId']='unreviewed-program'
        raw['transaction']['message']['instructions'][0]['program']={}
    elif variant=='inner-index':raw['meta']['innerInstructions'][0]['index']=[]
    elif variant=='inner-group':raw['meta']['innerInstructions']=[[]]
    else:raw['meta']['innerInstructions'][0]['instructions']={}
    h=hashlib.sha256(canonical_bytes(raw)).hexdigest();value['payloads'][h]=raw
    if role=='selected':row['hash']=h
    else:value['manifest']['evidence']=[{'kind':'transaction','signature':row['signature'],'hash':h}]
    store=Store(tmp_path);result,coverage,digest=derive(store,value)
    assert result['metrics']['profit_sol']['status']=='unknown'
    assert result['metrics']['observed_network_fees_sol']['value']=='0.000055'
    assert coverage['population_state']=='UNKNOWN'
    # Exercise the shared generic decoder directly, outside the archive container guard.
    from scanner.decoder import decode_transactions
    decoded=decode_transactions([{'signature':row['signature'],'raw':raw,'evidence_hash':h}],value['manifest']['address'])
    assert any(e['kind']=='unsupported' for e in decoded['events'])
    assert any(e['kind']=='fee' and e['amount_sol']=='0.000005' for e in decoded['events'])


def test_malformed_program_identity_normal_api_import_creates_an_unresolved_report(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import scanner.app as application
    monkeypatch.setattr(application,'Credentials',lambda _:SimpleNamespace(key=None,storage='none',backend=None))
    value=bundle();row=value['manifest']['transactions'][1];raw=deepcopy(value['payloads'][row['hash']]);raw['transaction']['message']['instructions'][0]['programId']={}
    h=hashlib.sha256(canonical_bytes(raw)).hexdigest();value['payloads'][h]=raw;row['hash']=h
    with TestClient(create_app(tmp_path,'isolated-test-session'),base_url='http://127.0.0.1:8765') as client:
        csrf=client.get('/api/bootstrap',headers={'X-Launch-Token':'isolated-test-session'}).json()['csrf']
        response=client.post('/api/archives/import',content=packed(value),headers={'X-CSRF-Token':csrf})
        assert response.status_code==200,response.text
        report=client.get('/api/reports/'+response.json()['report_id']).json()
        assert report['metrics']['profit_sol']['status']=='unknown'
        assert report['metrics']['observed_network_fees_sol']['value']=='0.000055'
        assert report['qualification']['qualified'] is False


def test_claimed_real_world_or_completion_boolean_cannot_certify_a_wallet(tmp_path):
    value = bundle(); value['manifest']['dataset'] = 'real'
    result, coverage, _ = derive(Store(tmp_path), value)
    assert coverage['real_acceptance'] == 'BLOCKED' and coverage['population_state'] == 'UNKNOWN'
    assert result['metrics']['profit_sol']['status'] == 'unknown'
    assert result['metrics']['observed_network_fees_sol']['status'] == 'known'
    value['manifest']['complete'] = True
    with pytest.raises(ValueError, match='completion'):
        import_archive(Store(tmp_path/'reject'), packed(value))


def test_conflicting_linked_alternative_is_not_outvoted_or_fixed_by_hiding_its_bytes(tmp_path):
    value = bundle(); original = value['manifest']['transactions'][0]
    raw = deepcopy(value['payloads'][original['hash']]); raw['meta']['fee'] += 1
    other = hashlib.sha256(canonical_bytes(raw)).hexdigest(); value['payloads'][other] = raw
    value['manifest']['evidence'] = [{'kind':'getTransaction','signature':original['signature'],'hash':other}]
    store = Store(tmp_path); result, coverage, digest = derive(store, value)
    assert result['metrics']['profit_sol']['status'] == 'unknown'
    assert coverage['population_state'] == 'UNKNOWN'
    (store.path/'evidence'/f'{other}.json.gz').unlink()
    loaded = load_archive(store,digest); events,_ = decode_archive(loaded); changed,_,_ = analyze_archive(loaded,events)
    assert changed['metrics']['profit_sol']['status'] == 'unknown'


def test_archive_paths_hashes_and_expansion_are_bounded_before_mutation(tmp_path):
    store = Store(tmp_path)
    for name, raw in [('../escape', b'x'), ('archives/'+'a'*64+'.json.gz',gzip.compress(b'{}'))]:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('manifest.json',canonical_bytes(bundle()['manifest']));archive.writestr(name,raw)
        with pytest.raises(ValueError): import_archive(store,stream.getvalue())
    assert store.list('artifacts') == []


def test_normal_app_import_rebuild_sources_and_exports_preserve_parent_and_use_no_provider(tmp_path, monkeypatch):
    import httpx
    from types import SimpleNamespace
    import scanner.app as app_module
    async def denied(*args, **kwargs): raise AssertionError('Offline import cannot dispatch a provider request')
    monkeypatch.setattr(httpx.AsyncClient,'post',denied)
    monkeypatch.setattr(app_module,'Credentials',lambda *_: SimpleNamespace(key=None,storage='none',backend=None))
    app=create_app(tmp_path,'private-test-token')
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/archives/import',content=packed(bundle())).status_code == 401
        csrf=client.get('/api/bootstrap',headers={'X-Launch-Token':'private-test-token'}).json()['csrf']
        assert client.post('/api/archives/import',content=packed(bundle())).status_code == 403
        client.headers['X-CSRF-Token']=csrf
        response=client.post('/api/archives/import',content=packed(bundle()),headers={'content-type':'application/zip'})
        assert response.status_code == 200,response.text
        identifier=response.json()['report_id']; original=client.get(f'/api/export/reports/{identifier}.json').content
        report=json.loads(original)
        assert report['source']=='demo' and report['qualification']['qualified'] is False
        assert report['metrics']['profit_sol']['value']=='0.49995'
        assert client.get(f"/api/evidence/{report['archive_input_hash']}").status_code==200
        source=bundle()['manifest']['valuation_hash']; file=app.state.store.path/'evidence'/f'{source}.json.gz'; bytes_before=file.read_bytes();file.unlink()
        child=client.post(f'/api/reports/{identifier}/rebuild').json()['report_id']
        newer=client.get(f'/api/reports/{child}').json()
        assert newer['metrics']['profit_sol']['value']=='0.49995' and newer['metrics']['economic_pnl_sol']['status']=='unknown'
        assert newer['archive_input_hash']==report['archive_input_hash'] and newer['preset']==report['preset']
        file.write_bytes(bytes_before)
        child=client.post(f'/api/reports/{identifier}/rebuild').json()['report_id']
        assert client.get(f'/api/reports/{child}').json()['metrics']==report['metrics']
        assert client.get(f'/api/export/reports/{identifier}.json').content==original
        assert '0.49995' in client.get(f'/api/export/reports/{child}.csv').text
