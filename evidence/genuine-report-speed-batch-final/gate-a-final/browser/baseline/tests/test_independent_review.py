"""Imported v0.3.1 independent controls; synthetic inputs certify no wallet.

The zero-net flow case is a deliberately modified fixture, not an observed
mainnet transaction or a valid signed transaction. R5 is an ordinary regression
assertion here; no expected failures conceal an unfixed defect.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scanner.accounting import analyze
from scanner.evidence_audit import audit_raw_bundle

FIXTURES = Path(__file__).parent / 'fixtures'
END = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def synthetic_history():
    rows = []
    # Explicit synthetic realizations: three wins and one loss, over four weeks.
    for index, (days, gross) in enumerate([(25, '3'), (18, '1'), (11, '4'), (4, '5')]):
        sale = END - timedelta(days=days)
        for kind, stamp, amount in [('buy', sale - timedelta(hours=2), '2'),
                                    ('sell', sale, gross)]:
            rows.append({'kind': kind, 'timestamp': stamp.isoformat(),
                'mint': f'synthetic-mint-{index}', 'quantity_raw': '100',
                'decimals': 6, 'classification': 'meme', 'amount_sol': amount,
                'fee_sol': '0', 'order': len(rows), 'path': 'synthetic-fill',
                'signature': f'synthetic-{index}-{kind}',
                'evidence': ['independent-synthetic-history']})
    return rows


def bundle():
    return json.loads((FIXTURES / 'real-transaction-audit-mainnet.json').read_text())


def rehash_mutation(value):
    value['test_control'] = 'SYNTHETIC modified fixture; no chain authentication or signature validity'
    for record in value['transactions']:
        record['evidence_hash'] = sha256(json.dumps(record['raw'], sort_keys=True,
            ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    return value


def synthetic_zero_net_flows():
    """Preserve the review's second-signer, fee and endpoint remapping control."""
    value = bundle()
    raw = value['transactions'][0]['raw']
    meta, message = raw['meta'], raw['transaction']['message']
    wallet = value['address']
    donor = message['instructions'][8]['parsed']['info']['destination']
    old_keys = message['accountKeys']
    donor_index = next(index for index, key in enumerate(old_keys) if key['pubkey'] == donor)
    order = [0, donor_index] + [index for index in range(1, len(old_keys)) if index != donor_index]
    remap = {old: new for new, old in enumerate(order)}
    message['accountKeys'] = [old_keys[index] for index in order]
    message['accountKeys'][1]['signer'] = True
    for field in ('preBalances', 'postBalances'):
        meta[field] = [meta[field][index] for index in order]
    for field in ('preTokenBalances', 'postTokenBalances'):
        for balance in meta[field]:
            balance['accountIndex'] = remap[balance['accountIndex']]
    raw['transaction']['signatures'].append('1' * 64)  # Encoding only; not a valid signature claim.
    message['instructions'].append({'program': 'system',
        'programId': '11111111111111111111111111111111', 'stackHeight': 1,
        'parsed': {'type': 'transfer', 'info': {'source': donor,
                    'destination': wallet, 'lamports': 3_500_000}}})
    meta['postBalances'][0] += 3_500_000 - 5_000
    meta['postBalances'][1] -= 3_500_000
    meta['fee'] += 5_000
    return rehash_mutation(value)


@pytest.mark.parametrize('days', [1, 7, 14, 21, 28, 30, 90])
def test_independent_weekly_population_with_win_and_loss(days):
    result = analyze(synthetic_history(), (END - timedelta(days=days)).isoformat(), END.isoformat())
    assert [week['profit_sol'] for week in result['weekly']] == ['1', '-1', '2', '3']
    assert result['metrics']['positive_weeks']['value'] == '3'
    assert result['metric_coverage']['positive_weeks']['start'] == (END - timedelta(days=28)).isoformat()


@pytest.mark.parametrize('days', [7, 14, 21, 30])
def test_missing_coverage_stays_unknown(days):
    result = analyze(synthetic_history(), (END - timedelta(days=days)).isoformat(),
                     END.isoformat(), history_complete=False)
    assert result['metrics']['positive_weeks']['status'] == 'unknown'
    assert all(week['profit_sol'] is None for week in result['weekly'])


@pytest.mark.parametrize('days', [7, 30])
def test_unknown_cost_in_older_week_does_not_disappear(days):
    rows = synthetic_history()
    rows[1]['fee_sol'] = None
    result = analyze(rows, (END - timedelta(days=days)).isoformat(), END.isoformat())
    assert result['metrics']['positive_weeks']['status'] == 'unknown'
    assert result['weekly'][0]['profit_sol'] is None


def test_end_exclusive_and_28_day_start_inclusive():
    rows = synthetic_history()
    rows += [{'kind': 'fee', 'timestamp': stamp.isoformat(), 'amount_sol': amount,
              'paid_by_wallet': True, 'evidence': ['independent-synthetic-fee']}
             for stamp, amount in [(END, '100'), (END - timedelta(days=28), '0.5'),
                 (END - timedelta(days=28, microseconds=1), '100')]]
    result = analyze(rows, (END - timedelta(days=7)).isoformat(), END.isoformat())
    assert [week['profit_sol'] for week in result['weekly']] == ['0.5', '-1', '2', '3']


def test_bundled_record_has_reproducible_gross_amount_not_wallet_profit():
    value = bundle()
    report = audit_raw_bundle(value)
    assert report['metrics']['gross_buy_consideration_sol']['value'] == '0.25'
    assert report['metrics']['native_wallet_delta_sol']['value'] == '-0.253641389'
    assert report['metrics']['wallet_profit_sol']['value'] is None
    assert report['certificate']['financial_qualification'] == 'UNRESOLVED'
    assert report == audit_raw_bundle(value)


@pytest.mark.parametrize('removal', ['fee', 'owner', 'owned_account'])
def test_missing_evidence_cannot_certify_trade_or_wallet(removal):
    value = bundle()
    raw = value['transactions'][0]['raw']
    if removal == 'fee':
        del raw['meta']['fee']
    elif removal == 'owner':
        row = next(row for row in raw['meta']['preTokenBalances'] if row.get('owner') == value['address'])
        del row['owner']
    else:
        value['scope']['accounts'].remove('47YKPtLHM5joKbW5hCFhXhZcigp4Xb9NrGpiKFjfsNUM')
    result = audit_raw_bundle(rehash_mutation(value))
    assert result['certificate']['status'] == 'INCOMPLETE'
    assert result['metrics']['gross_buy_consideration_sol']['value'] is None
    assert result['metrics']['wallet_profit_sol']['value'] is None
    assert result['certificate']['wallet_history_complete'] is False


def test_import_cannot_self_declare_verified_source_or_wallet_profit():
    value = bundle()
    value['transactions'][0]['raw']['review_control'] = 'synthetic change'
    value.update(history_complete=True, financial_qualification='QUALIFIED', source='mainnet')
    result = audit_raw_bundle(rehash_mutation(value))
    assert result['source'] == 'unverified-import'
    assert result['certificate']['checks']['chain_provenance']['state'] == 'UNKNOWN'
    assert result['certificate']['financial_qualification'] == 'UNRESOLVED'


@pytest.mark.parametrize('which', ['scope', 'transaction'])
def test_duplicate_record_or_signature_does_not_inflate_counts(which):
    value = bundle()
    if which == 'scope':
        value['scope']['signatures'] *= 2
    else:
        value['transactions'] *= 2
    result = audit_raw_bundle(value)
    assert result['certificate']['checks']['transaction_set']['state'] == 'FAIL'
    assert result['metrics']['transaction_count']['value'] is None


def test_zero_net_control_has_unknown_flows_and_protects_wallet_gate():
    result = audit_raw_bundle(synthetic_zero_net_flows())
    capital = [event for event in result['events'] if event['kind'] == 'capital']
    net = sum(Decimal(event['amount_sol']) * (1 if event['direction'] == 'deposit' else -1)
              for event in capital)
    assert len(capital) == 3 and net == 0
    assert all(event['economic_role'] == 'unknown' for event in capital)
    assert result['source'] == 'unverified-import'
    assert result['certificate']['checks']['native_reconciliation']['state'] == 'PASS'
    assert next(event for event in result['events'] if event['kind'] == 'fee')['allocation'] == 'unallocated'
    assert result['certificate']['financial_qualification'] == 'UNRESOLVED'
    assert result['metrics']['wallet_profit_sol']['value'] is None


def test_offsetting_unknown_transfers_must_not_pass_fee_allocation():
    result = audit_raw_bundle(synthetic_zero_net_flows())
    assert result['certificate']['checks']['fee_allocation']['state'] == 'UNKNOWN'
