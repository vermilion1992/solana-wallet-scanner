"""Small independent direct/API diff review; no full acceptance claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import sys

from reproduce import ROOT, OUT, controls, summarize
from test_wallet_evidence import derive, record, WALLET
from test_position_evidence import WINDOW, address
from scanner.archive_input import canonical_bytes, pack_bytes, VERSION
from scanner.decoder import SYSTEM_ID


def direct():
    results = {}
    for name, (raw, expected) in controls().items():
        alternative = deepcopy(raw)
        alternative['meta']['logMessages'] = ['Optional independently retained receipt']
        link = record(alternative)
        original = deepcopy(raw)
        parent = derive([raw], alternatives=[link])
        receipt = parent['cost_flow_evidence']['transactions'][raw['transaction']['signatures'][0]]
        refunds = [r for r in receipt['admitted_internal_roles'] if r['role'] == 'wallet_owned_account_refund']
        assert len(refunds) == 1 and int(refunds[0]['lamports']) == expected['refund_lamports']
        assert receipt['check']['state'] == 'PASS'
        assert parent['components']['observed_economic_roles']['state'] == 'PASS'
        assert parent['components']['native_fee']['state'] == 'PASS'
        assert parent['components']['historical_population']['state'] == 'UNKNOWN'
        assert parent['cost_flow_evidence']['provider_requests'] == parent['cost_flow_evidence']['credential_lookups'] == 0
        assert raw == original
        lost = derive([raw], alternatives=[{**link, 'raw': None}])
        assert lost['components']['observed_economic_roles']['state'] == 'UNKNOWN'
        assert lost['cost_flow_evidence']['transactions'][raw['transaction']['signatures'][0]]['check']['state'] == 'UNKNOWN'
        changed = deepcopy(alternative)
        changed['meta']['postBalances'][0] += 1
        conflict = derive([raw], alternatives=[record(changed)])
        assert conflict['components']['observed_economic_roles']['state'] == 'UNKNOWN'
        assert derive([raw], alternatives=[link]) == parent
        # Independent unsupported endpoint, opaque operation and signer controls.
        for variant in ('unexplained-native-credit', 'missing-signers', 'opaque-relevant'):
            broken = deepcopy(raw)
            if variant == 'unexplained-native-credit':
                broken['meta']['postBalances'][0] += 1
                # Keep global native conservation valid. A foreign debit funds
                # this unexplained wallet credit; network fee stays independent.
                broken['meta']['postBalances'][3] -= 1
            elif variant == 'missing-signers':
                broken['transaction']['message'].pop('header')
            else:
                program = address(55)
                broken['transaction']['message']['accountKeys'].append(program)
                broken['meta']['preBalances'].append(1)
                broken['meta']['postBalances'].append(1)
                broken['transaction']['message']['instructions'].insert(0,
                    {'programId': program, 'accounts': [WALLET, raw['transaction']['message']['accountKeys'][1]], 'data': '1'})
            blocked = derive([broken])
            assert blocked['components']['observed_economic_roles']['state'] == 'UNKNOWN', variant
            assert blocked['components']['native_fee']['state'] == 'PASS', variant
        results[name] = {'state': 'PASS', 'exact_refund_lamports': str(expected['refund_lamports']),
            'linked_loss_conflict_restoration': 'PASS', 'endpoint_signer_opaque_controls': 'PASS',
            'independent_fee_isolation': 'PASS', 'historical_population': 'UNKNOWN'}
    return results


def api():
    import httpx
    import scanner.app as app_module
    from fastapi.testclient import TestClient

    counts = {'provider': 0, 'credential': 0}
    active = [False]

    class EmptyCredentials:
        storage, backend = 'none', None
        def __init__(self, *_):
            pass
        @property
        def key(self):
            if active[0]:
                counts['credential'] += 1
                raise AssertionError('Offline workflow cannot look up a credential')
            return None

    async def denied(*_args, **_kwargs):
        counts['provider'] += 1
        raise AssertionError('Offline workflow cannot dispatch a provider')

    raw, expected = controls()['system-topup-close']
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['Independent optional receipt']
    selected_hash = hashlib.sha256(canonical_bytes(raw)).hexdigest()
    alt_hash = hashlib.sha256(canonical_bytes(alternative)).hexdigest()
    signature = raw['transaction']['signatures'][0]
    manifest = {'version': VERSION, 'address': WALLET, 'window': WINDOW, 'dataset': 'real',
        'transactions': [{'signature': signature, 'hash': selected_hash}],
        'evidence': [{'signature': signature, 'kind': 'getTransaction', 'hash': alt_hash}]}
    content = pack_bytes({'manifest': manifest, 'payloads': {selected_hash: raw, alt_hash: alternative}})
    with tempfile.TemporaryDirectory(prefix='mixed-cash-review-') as runtime, \
            patch.object(app_module, 'Credentials', EmptyCredentials), \
            patch.object(httpx.AsyncClient, 'post', denied):
        app = app_module.create_app(Path(runtime), 'mixed-accounting-review-session')
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            active[0] = True
            csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'mixed-accounting-review-session'}).json()['csrf']
            client.headers['X-CSRF-Token'] = csrf
            imported = client.post('/api/archives/import', content=content, headers={'content-type': 'application/zip'})
            assert imported.status_code == 200, imported.text
            parent_id = imported.json()['report_id']
            original = client.get(f'/api/export/reports/{parent_id}.json').content
            parent = json.loads(original)
            parent_adapter = parent['coverage']['wallet_evidence']
            assert parent_adapter['components']['observed_economic_roles']['state'] == 'PASS'
            roles = parent_adapter['cost_flow_evidence']['transactions'][signature]['admitted_internal_roles']
            assert any(r['role'] == 'wallet_owned_account_refund' and int(r['lamports']) == expected['refund_lamports'] for r in roles)
            assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000005'
            assert parent['metrics']['profit_sol']['status'] == 'unknown'
            assert parent['qualification']['qualified'] is False
            alt_path = app.state.store.path / 'evidence' / f'{alt_hash}.json.gz'
            retained = alt_path.read_bytes()
            alt_path.unlink()
            lost = client.post(f'/api/reports/{parent_id}/rebuild')
            assert lost.status_code == 200, lost.text
            child = client.get('/api/reports/' + lost.json()['report_id']).json()
            assert child['coverage']['wallet_evidence']['components']['observed_economic_roles']['state'] == 'UNKNOWN'
            alt_path.write_bytes(retained)
            restored = client.post(f'/api/reports/{parent_id}/rebuild')
            assert restored.status_code == 200, restored.text
            child_id = restored.json()['report_id']
            child = client.get('/api/reports/' + child_id).json()
            assert child['coverage']['wallet_evidence']['components']['observed_economic_roles']['state'] == 'PASS'
            assert child['metrics'] == parent['metrics']
            assert client.get(f'/api/export/reports/{parent_id}.json').content == original
            assert '0.000005' in client.get(f'/api/export/reports/{child_id}.csv').text
            assert counts == {'provider': 0, 'credential': 0}
            active[0] = False
            return {'state': 'PASS', 'refund_lamports': str(expected['refund_lamports']),
                'fee_sol': '0.000005', 'profit_state': 'unknown',
                'parent_immutable': True, 'alt_loss_restoration': True,
                'json_csv_export': True, **counts}


def main():
    result = {'scope': 'Read-only current mixed refund diff; synthetic interface controls, no genuine B3',
        'direct': direct(), 'normal_offline_api': api(), 'state': 'PASS',
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    (OUT / sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
