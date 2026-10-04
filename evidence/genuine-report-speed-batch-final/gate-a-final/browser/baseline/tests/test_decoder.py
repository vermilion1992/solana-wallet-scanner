"""Synthetic RPC records exercise conservative decoding, not live DEX support."""
import unittest
from copy import deepcopy

from scanner.decoder import decode_transactions, SYSTEM_ID
from scanner.accounting import analyze

WALLET = 'synthetic-wallet'
TOKEN = 'synthetic-mint'
TOKEN_ID = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TIME = 1767571200  # 2026-01-05T00:00:00Z


def balance(index, amount, owner=WALLET, mint=TOKEN):
    return {'accountIndex': index, 'mint': mint, 'owner': owner,
            'uiTokenAmount': {'amount': str(amount), 'decimals': 6,
                              'uiAmount': float(amount) / 1e6}}


def transfer(source='source', destination='destination', quantity='100'):
    return {'program': 'spl-token', 'programId': TOKEN_ID,
            'parsed': {'type': 'transferChecked', 'info': {'source': source,
                'destination': destination, 'mint': TOKEN,
                'tokenAmount': {'amount': quantity, 'decimals': 6}}}}


def record(instructions=None):
    return {'signature': 'synthetic-signature', 'evidence_hash': 'synthetic-hash',
            'raw': {'slot': 100, 'blockTime': TIME, 'version': 'legacy',
                    'transaction': {'signatures': ['synthetic-signature'], 'message': {
                        'accountKeys': [WALLET, 'source', 'destination'],
                        'instructions': instructions if instructions is not None else [transfer()]}},
                    'meta': {'fee': 5000, 'err': None,
                             'preTokenBalances': [balance(1, 100), balance(2, 0, 'counterparty')],
                             'postTokenBalances': [balance(1, 0), balance(2, 100, 'counterparty')],
                             'innerInstructions': []}}}


class DecoderTests(unittest.TestCase):
    def decode(self, entry):
        return decode_transactions([entry], WALLET)

    def test_parsed_transfer_and_exact_wallet_fee_not_swap(self):
        result = self.decode(record())
        self.assertEqual([e['kind'] for e in result['events']], ['fee', 'transfer_out'])
        self.assertEqual(result['events'][0]['amount_sol'], '0.000005')
        movement = result['events'][1]
        self.assertEqual(movement['quantity_raw'], '100')
        self.assertEqual(movement['mint'], TOKEN)
        self.assertEqual(movement['classification'], 'unknown')
        self.assertEqual(movement['evidence'], ['synthetic-hash'])
        self.assertEqual(movement['path'], 'instructions.0')
        self.assertNotIn('sell', [e['kind'] for e in result['events']])

    def test_failed_transaction_only_fee_no_invented_execution(self):
        entry = record()
        entry['raw']['meta']['err'] = {'InstructionError': [0, 'Custom']}
        result = self.decode(entry)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['kind'], 'fee')
        self.assertTrue(result['events'][0]['failed'])
        report = analyze(result['events'], '2026-01-01T00:00:00Z', '2026-01-31T00:00:00Z')
        self.assertEqual(report['metrics']['profit_sol']['value'], '-0.000005')

    def test_sponsor_paid_fee_excluded(self):
        entry = record([])
        entry['raw']['transaction']['message']['accountKeys'][0] = 'sponsor'
        entry['raw']['meta']['postTokenBalances'] = deepcopy(entry['raw']['meta']['preTokenBalances'])
        result = self.decode(entry)
        self.assertFalse(result['events'][0]['paid_by_wallet'])
        report = analyze(result['events'], '2026-01-01T00:00:00Z', '2026-01-31T00:00:00Z')
        self.assertEqual(report['metrics']['profit_sol']['value'], '0')

    def test_balance_deltas_never_prove_swap(self):
        result = self.decode(record([]))
        self.assertTrue(result['unresolved'])
        self.assertTrue(any('do not reconcile' in e.get('reason', '') for e in result['events']))
        self.assertFalse(any(e['kind'] in ('buy', 'sell') for e in result['events']))

    def test_unknown_dex_with_inner_transfers_explicit_unsupported(self):
        entry = record([{'programId': 'unreviewed-dex', 'accounts': [1, 2], 'data': 'unknown'}])
        entry['raw']['meta']['innerInstructions'] = [{'index': 0, 'instructions': [transfer()]}]
        result = self.decode(entry)
        self.assertEqual([e['kind'] for e in result['events']], ['fee', 'unsupported', 'transfer_out'])
        self.assertIn('do not prove a swap', result['events'][1]['reason'])
        self.assertEqual(result['events'][2]['path'], 'innerInstructions.0.0')
        report = analyze(result['events'], '2026-01-01T00:00:00Z', '2026-01-31T00:00:00Z')
        self.assertIsNone(report['metrics']['profit_sol']['value'])

    def test_internal_accounts_only_when_event_ownership_evidenced(self):
        entry = record()
        for field in ('preTokenBalances', 'postTokenBalances'):
            entry['raw']['meta'][field][1]['owner'] = WALLET
        result = self.decode(entry)
        self.assertEqual(result['events'][1]['kind'], 'internal_transfer')
        entry['raw']['meta']['postTokenBalances'][1]['owner'] = 'other'
        result = self.decode(entry)
        self.assertTrue(any('ownership changed' in issue['reason'] for issue in result['unresolved']))

    def test_malformed_metadata_and_unknown_version_retained(self):
        entry = record()
        entry['raw']['meta'] = None
        self.assertTrue(self.decode(entry)['unresolved'])
        entry = record()
        entry['raw']['version'] = 2
        self.assertTrue(any('version' in issue['reason'] for issue in self.decode(entry)['unresolved']))
        entry['raw'] = None
        self.assertTrue(any('Missing transaction' in issue['reason'] for issue in self.decode(entry)['unresolved']))

    def test_missing_block_time_is_not_fabricated(self):
        entry = record()
        entry['raw']['blockTime'] = None
        result = self.decode(entry)
        self.assertTrue(result['unresolved'])
        self.assertTrue(all(e['timestamp'] is None for e in result['events']))
        report = analyze(result['events'], '2026-01-01T00:00:00Z', '2026-01-31T00:00:00Z')
        self.assertIsNone(report['metrics']['profit_sol']['value'])

    def test_same_slot_order_needs_block_evidence(self):
        first, second = record(), record()
        second['signature'] = 'another-signature'
        result = decode_transactions([first, second], WALLET)
        self.assertTrue(any('Same-slot' in issue['reason'] for issue in result['unresolved']))
        first['transaction_index'], second['transaction_index'] = 0, 1
        result = decode_transactions([first, second], WALLET)
        self.assertFalse(any('Same-slot' in issue['reason'] for issue in result['unresolved']))

    def test_native_transfer_capital_not_profit(self):
        instruction = {'program': 'system', 'programId': SYSTEM_ID,
                       'parsed': {'type': 'transfer', 'info': {'source': 'external',
                            'destination': WALLET, 'lamports': 1234567890}}}
        entry = record([instruction])
        entry['raw']['meta']['postTokenBalances'] = deepcopy(entry['raw']['meta']['preTokenBalances'])
        result = self.decode(entry)
        self.assertEqual(result['events'][1]['kind'], 'capital')
        self.assertEqual(result['events'][1]['amount_sol'], '1.23456789')
        report = analyze(result['events'], '2026-01-01T00:00:00Z', '2026-01-31T00:00:00Z')
        self.assertEqual(report['metrics']['profit_sol']['value'], '-0.000005')

    def test_mint_raw_strings_ui_float_ignored(self):
        entry = record()
        entry['raw']['meta']['preTokenBalances'][0]['uiTokenAmount']['uiAmount'] = float('nan')
        result = self.decode(entry)
        self.assertEqual(result['events'][1]['quantity_raw'], '100')
        entry['raw']['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = 100.0
        self.assertTrue(self.decode(entry)['unresolved'])

    def test_supported_name_with_wrong_program_identity_is_not_trusted(self):
        entry = record()
        entry['raw']['transaction']['message']['instructions'][0]['programId'] = 'unreviewed-program'
        result = self.decode(entry)
        self.assertTrue(any('program identity' in issue['reason'] for issue in result['unresolved']))
        self.assertFalse(any(e['kind'] in ('transfer_in', 'transfer_out') for e in result['events']))

    def test_native_self_transfer_is_internal(self):
        instruction = {'program': 'system', 'programId': SYSTEM_ID,
                       'parsed': {'type': 'transfer', 'info': {'source': WALLET,
                            'destination': WALLET, 'lamports': 1000000000}}}
        entry = record([instruction])
        entry['raw']['meta']['postTokenBalances'] = deepcopy(entry['raw']['meta']['preTokenBalances'])
        self.assertEqual(self.decode(entry)['events'][1]['kind'], 'internal_transfer')

    def test_boolean_version_is_not_legacy_or_v0(self):
        for value in (False, True):
            with self.subTest(value=value):
                entry = record()
                entry['raw']['version'] = value
                result = self.decode(entry)
                self.assertTrue(any('version' in issue['reason'] for issue in result['unresolved']))
                self.assertFalse(any(e['kind'] == 'transfer_out' for e in result['events']))

    def test_json_rpc_envelope(self):
        entry = record()
        entry['raw'] = {'jsonrpc': '2.0', 'id': 1, 'result': entry['raw']}
        self.assertEqual(self.decode(entry)['events'][1]['kind'], 'transfer_out')


if __name__ == '__main__':
    unittest.main()
