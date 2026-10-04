"""Archived real sale arithmetic plus counterfactual nonce rejection controls.

The unchanged genuine source is a sale from already-held inventory. It verifies
transaction-level proceeds and fees, never its acquisition costs or wallet P&L.
Mutations are synthetic adversarial inputs, not independently observed records.
No provider call or current account observation is made by these tests.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scanner.accounting import analyze
from scanner.investigation import (decode_supported_swaps, RECENT_BLOCKHASHES_SYSVAR,
                                  DECODER_VERSION)
from scanner.research import summarize_research
from scanner.config import STRICT
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session


WALLET = 'DY5qAVztKXXPMY9enjbgvJxn6wPPZ1Ek34Jp3xJm4Lct'
HASH = '25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a'
SIGNATURE = '24sJMsaocWhShDJ7EtBpvyRXV8ieAgpPNBjgGGFfscVckF39QRopdfKiQhbasf2ZrCQzRkdsoBY11gFkpBFnHhFs'
FIXTURE = Path(__file__).parent / 'fixtures/mainnet-pumpswap-sell-durable-nonce.json'


def genuine():
    return json.loads(FIXTURE.read_text())


def trades(result):
    return [event for event in result['events'] if event['kind'] in ('buy', 'sell')]


def nonce_instruction(record):
    return record['raw']['transaction']['message']['instructions'][0]


def key_entry(record, pubkey):
    return next(entry for entry in record['raw']['transaction']['message']['accountKeys']
                if isinstance(entry, dict) and entry.get('pubkey') == pubkey)


def decode(record):
    return decode_supported_swaps([record], WALLET)


def test_genuine_raw_hash_and_sale_amounts_are_exact_without_promoting_inventory():
    record = genuine()
    original = deepcopy(record)
    raw = record['raw']
    encoded = json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == record['evidence_hash'] == HASH
    assert record['signature'] == raw['transaction']['signatures'][0] == SIGNATURE
    result = decode(record)
    assert not result['unresolved']
    assert len(trades(result)) == 1
    sale = trades(result)[0]
    assert sale['kind'] == 'sell'
    assert sale['mint'] == 'HXxJdaQbrYRvwTAM8M8mUPyoRPvmyuUbPFBRkiAAMASS'
    assert sale['quantity_raw'] == '5218627960'
    assert sale['amount_sol'] == '0.01134506'
    assert sale['fee_sol'] == '0.000042'
    assert sale['observed_pre_quantity_raw'] == '402359378326'
    assert sale['observed_post_quantity_raw'] == '397140750366'
    assert sale['classification'] == 'unknown'
    fee = next(event for event in result['events'] if event['kind'] == 'fee')
    assert fee['amount_sol'] == '0.000042'
    assert fee['allocation'] == 'sell_exit'
    assert fee['allocated_trade_path'] == sale['path'] == 'instructions.4'
    assert result['coverage']['decoder_version'] == DECODER_VERSION == 'spot-v4-durable-nonce'
    assert result['coverage']['complete'] is result['coverage']['history_complete'] is False
    administration = result['coverage']['non_economic_instructions']
    assert len(administration) == 1
    assert administration[0]['kind'] == 'advanceNonce'
    assert administration[0]['path'] == 'instructions.0'
    assert administration[0]['evidence'] == [HASH]
    assert record == original


def test_genuine_sale_earlier_inventory_basis_and_profit_remain_unknown():
    record = genuine()
    events = decode(record)['events']
    end = datetime.fromtimestamp(record['raw']['blockTime'], timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(days=30)
    accounting = analyze(events, start.isoformat(), end.isoformat(), history_complete=False)
    research = summarize_research(events, start.isoformat(), end.isoformat(), history_complete=False)
    assert accounting['metrics']['profit_sol']['value'] is None
    assert accounting['positions'][0]['basis_sol'] is None
    assert accounting['positions'][0]['matched_basis_sol'] is None
    assert accounting['positions'][0]['pnl_sol'] is None
    assert accounting['positions'][0]['exit_fees_sol'] == '0.000042'
    assert accounting['unallocated_overhead_sol'] == '0'
    assert research['supported_swaps'] == research['sales'] == 1
    assert research['observed_matched_sales'] == 0
    assert research['observed_unmatched_sales'] == 1
    assert research['observed_profit_sol'] is None
    assert research['conditional_observed_lot_profit_sol'] is None
    assert research['known_matched_profit_sol'] is None
    assert research['wallet_fees_paid_sol'] == '0.000042'
    assert research['unallocated_fees_sol'] == '0'


def test_offline_frozen_report_rebuild_uses_genuine_sale_receipts_without_claiming_profit(session, monkeypatch):
    """Real raw sources through the API; the selected receipt scope stays partial."""
    client, app, _ = session
    store = app.state.store
    record = genuine()
    source = json.loads((FIXTURE.parent / 'mainnet-pumpswap-sell-durable-nonce-sources.json').read_text())
    assert store.archive(record['raw']) == HASH
    references = [{'kind': 'transaction', 'signature': SIGNATURE, 'hash': HASH}]
    for observation in source['sources']:
        assert store.archive(observation['payload']) == observation['hash']
        # The source-selection descriptor calls this "anchor"; native collector
        # links use "snapshot-slot". Keep every genuine payload/hash unchanged.
        role = 'snapshot-slot' if observation['kind'] == 'anchor' else observation['kind']
        references.append({'kind': role, 'hash': observation['hash']})
    start, end = source['original_window']['start'], source['original_window']['end']
    window = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
              for key, value in source['original_window'].items()}
    checkpoint = {'version': source['original_checkpoint_version'], 'address': WALLET,
                  'start': start, 'end': end, 'basis_floor': start - 90 * 86400,
                  'snapshot': deepcopy(source['original_snapshot']),
                  'accounts': {WALLET: deepcopy(source['original_wallet_account'])},
                  'transactions': {SIGNATURE: {'signature': SIGNATURE, 'evidence_hash': HASH}},
                  'evidence': references, 'gaps': [], 'ordering': {}}
    identifier = hashlib.sha256(f'{WALLET}:{start}:{end}'.encode()).hexdigest()
    store.put('collector_checkpoints', identifier, checkpoint)
    collected = {'transactions': [record], 'checkpoint': checkpoint,
                 'snapshot': checkpoint['snapshot'], 'evidence': references,
                 'coverage': {'status': 'partial', 'history_scope_complete': False,
                              'selection_note': source['selection_note']}}
    original = {'id': 'saved-genuine-nonce-sale', 'scan_id': 'nonce-sale-fixture-job',
                'source': 'live', 'address': WALLET, 'created_at': '2026-10-02T14:48:55+00:00',
                'window': window, 'preset': deepcopy(STRICT), 'methodology': 'fifo-v3',
                'events': [], 'metrics': {}, 'checks': [], 'evidence': references,
                'evidence_status': 'partial', 'policy': 'UNRESOLVED', 'token_risk': [],
                'coverage': collected['coverage'],
                'collection_input_hash': freeze_report_inputs(store, WALLET, window, collected)}
    store.put('reports', original['id'], original)
    store.put('scans', original['scan_id'], {'id': original['scan_id'], 'status': 'paused',
                                          'audit_addresses': [WALLET], 'window': window,
                                          'preset': deepcopy(STRICT), 'budget_mode': 'setup-pilot'})
    calls = []

    async def forbidden_native(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Frozen genuine-sale reconstruction cannot dispatch provider calls')

    monkeypatch.setattr('scanner.providers.Gateway.rpc', forbidden_native)
    before_usage = client.get('/api/state').json()['usage']
    response = client.post('/api/reports/' + original['id'] + '/rebuild')
    assert response.status_code == 200, response.text
    child = client.get('/api/reports/' + response.json()['report_id']).json()
    assert child['id'] != original['id']
    assert child['rebuilt_from'] == original['id']
    assert store.get('reports', original['id']) == original
    assert child['window'] == original['window'] and child['preset'] == original['preset']
    sale = next(event for event in child['events'] if event['kind'] == 'sell')
    assert sale['quantity_raw'] == '5218627960'
    assert sale['amount_sol'] == '0.01134506'
    assert sale['fee_sol'] == '0.000042'
    assert child['coverage']['swap_reconstruction']['decoded_swaps'] == 1
    history = child['coverage']['history_evidence']
    receipt = next(item for item in history['record_provenance']['records'] if item['signature'] == SIGNATURE)
    assert receipt['state'] == 'PASS' and receipt['hash'] == HASH
    assert history['metric_decisions']['history']['state'] == 'UNKNOWN'
    assert all(state == 'UNKNOWN' for state in history['evidence_gates'].values())
    assert child['positions'][0]['basis_sol'] is None
    assert child['positions'][0]['pnl_sol'] is None
    assert child['metrics']['profit_sol']['value'] is None
    assert child['metrics']['profit_sol']['status'] == 'unknown'
    assert child['qualification']['qualified'] is False
    assert child['policy'] == 'UNRESOLVED' and child['evidence_status'] == 'partial'
    assert child['rebuild']['provider_requests'] == 0 and not calls
    assert client.get('/api/state').json()['usage'] == before_usage
    assert load_report_inputs(store, child)['transactions'][0]['raw'] == record['raw']
    assert store.evidence(HASH) == record['raw']


@pytest.mark.parametrize('amendment', [
    {'nonceAuthority': 'different-authority'},
    {'nonceAccount': 'missing-account'},
    {'nonceAccount': WALLET},
    {'recentBlockhashesSysvar': 'wrong-sysvar'},
    {'recentBlockhashesSysvar': None},
    {'lamports': 100},
])
def test_mismatched_nonce_semantics_cannot_skip_economic_activity(amendment):
    record = genuine()
    nonce_instruction(record)['parsed']['info'].update(amendment)
    result = decode(record)
    assert not trades(result)
    assert result['unresolved']
    fee = next(event for event in result['events'] if event['kind'] == 'fee')
    assert fee['amount_sol'] == '0.000042'
    assert fee['allocation'] == 'unallocated'


@pytest.mark.parametrize(('role', 'field', 'value'), [
    ('authority', 'signer', False), ('authority', 'signer', 1),
    ('nonce', 'writable', False), ('nonce', 'writable', 1),
    ('sysvar', 'writable', True), ('sysvar', 'signer', True),
])
def test_nonce_requires_explicit_primary_signer_and_account_roles(role, field, value):
    record = genuine()
    nonce = nonce_instruction(record)['parsed']['info']['nonceAccount']
    pubkey = WALLET if role == 'authority' else nonce if role == 'nonce' else RECENT_BLOCKHASHES_SYSVAR
    key_entry(record, pubkey)[field] = value
    assert not trades(decode(record))


@pytest.mark.parametrize('alteration', ['missing_info', 'missing_program', 'spoofed_program',
                                        'other_nonce_operation', 'not_first_outer', 'nested_nonce',
                                        'changed_nonce_balance', 'unconserved_native_balance',
                                        'missing_authority_roles'])
def test_malformed_nonce_or_primary_balance_proof_fails_closed(alteration):
    record = genuine()
    raw = record['raw']
    instruction = nonce_instruction(record)
    if alteration == 'missing_info':
        instruction['parsed'].pop('info')
    elif alteration == 'missing_program':
        instruction.pop('programId')
    elif alteration == 'spoofed_program':
        instruction['programId'] = 'unreviewed-program'
        instruction['program'] = 'system'
    elif alteration == 'other_nonce_operation':
        instruction['parsed']['type'] = 'withdrawNonce'
    elif alteration == 'not_first_outer':
        instructions = raw['transaction']['message']['instructions']
        instructions[0], instructions[1] = instructions[1], instructions[0]
    elif alteration == 'nested_nonce':
        raw['meta']['innerInstructions'][0]['instructions'].insert(0, deepcopy(instruction))
        raw['transaction']['message']['instructions'][0] = deepcopy(raw['transaction']['message']['instructions'][1])
    elif alteration == 'changed_nonce_balance':
        nonce = instruction['parsed']['info']['nonceAccount']
        index = next(i for i, entry in enumerate(raw['transaction']['message']['accountKeys']) if entry['pubkey'] == nonce)
        raw['meta']['postBalances'][index] += 1
        raw['meta']['postBalances'][0] -= 1  # Keep whole-record fee conservation.
    elif alteration == 'unconserved_native_balance':
        raw['meta']['postBalances'][-1] += 1
    else:
        keys = raw['transaction']['message']['accountKeys']
        keys[0] = keys[0]['pubkey']  # Pubkey text alone does not prove signing.
    result = decode(record)
    assert not trades(result)
    assert result['unresolved']
    assert result['coverage']['non_economic_instructions'] == []
