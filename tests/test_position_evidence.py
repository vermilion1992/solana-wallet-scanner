"""Synthetic multi-record acceptance and removal controls, plus a genuine buy gap.

Synthetic collector pages here do not authenticate mainnet or serve as financial
acceptance. The reviewed mainnet fixture remains one buy with nonzero stock.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scanner.collector import VERSION as COLLECTOR_VERSION
from scanner.history_evidence import derive_history_evidence
from scanner.investigation import PUMP_SWAP, WSOL, decode_supported_swaps
from scanner.providers import TOKEN_PROGRAM
from scanner.position_evidence import derive_position_evidence, _placement_relation
from scanner.storage import Store


def address(byte):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = int.from_bytes(bytes([byte]) * 32, 'big')
    result = ''
    while number:
        number, part = divmod(number, 58)
        result = alphabet[part] + result
    return result


WALLET, ACCOUNT, MINT, WSOL_ACCOUNT, POOL_TOKEN, POOL_WSOL, POOL = [address(i) for i in range(1, 8)]
START = 1_790_000_000
END = START + 30 * 86400
WINDOW = {'start': START, 'end': END}


def entry(signature, raw):
    return {'signature': signature, 'slot': raw['slot'], 'blockTime': raw['blockTime'],
            'err': raw['meta']['err'], 'confirmationStatus': 'finalized'}


def transfer(source, destination, quantity, mint=MINT):
    return {'programId': TOKEN_PROGRAM, 'parsed': {'type': 'transferChecked', 'info': {
        'source': source, 'destination': destination, 'mint': mint,
        'tokenAmount': {'amount': str(quantity), 'decimals': 9 if mint == WSOL else 6}}}}


def raw_exchange(signature, slot, when, before, after):
    buying = after > before
    amount = abs(after - before)
    keys = [WALLET, ACCOUNT, WSOL_ACCOUNT, POOL_TOKEN, POOL_WSOL]
    routes = [POOL, WALLET, address(8), MINT, WSOL, ACCOUNT, WSOL_ACCOUNT, POOL_TOKEN,
              POOL_WSOL, address(9), address(10), TOKEN_PROGRAM, TOKEN_PROGRAM,
              '11111111111111111111111111111111']
    encoded = hashlib.sha256(('global:' + ('buy' if buying else 'sell')).encode()).digest()[:8] + b'\0' * 16

    def balance(index, quantity, mint=MINT, owner=WALLET):
        return {'accountIndex': index, 'mint': mint, 'owner': owner, 'programId': TOKEN_PROGRAM,
                'uiTokenAmount': {'amount': str(quantity), 'decimals': 9 if mint == WSOL else 6}}

    pre_token = [balance(1, before), balance(2, 1_000_000_000 if buying else 0, WSOL),
                 balance(3, amount if buying else 0, owner=POOL), balance(4, 0 if buying else 1_000_000_000, WSOL, POOL)]
    post_token = [balance(1, after), balance(2, 0 if buying else 1_000_000_000, WSOL),
                  balance(3, 0 if buying else amount, owner=POOL), balance(4, 1_000_000_000 if buying else 0, WSOL, POOL)]
    pre_native = [10_000_000_000, 2_000_000, 2_000_000 + (1_000_000_000 if buying else 0),
                  2_000_000, 2_000_000 + (0 if buying else 1_000_000_000)]
    post_native = [9_999_995_000, 2_000_000, 2_000_000 + (0 if buying else 1_000_000_000),
                   2_000_000, 2_000_000 + (1_000_000_000 if buying else 0)]
    movements = [transfer(POOL_TOKEN, ACCOUNT, amount), transfer(WSOL_ACCOUNT, POOL_WSOL, 1_000_000_000, WSOL)] if buying else [transfer(ACCOUNT, POOL_TOKEN, amount), transfer(POOL_WSOL, WSOL_ACCOUNT, 1_000_000_000, WSOL)]
    return {'slot': slot, 'blockTime': when, 'version': 0,
            'transaction': {'signatures': [signature], 'message': {'accountKeys': keys,
                            'instructions': [{'programId': PUMP_SWAP, 'accounts': routes,
                                              'data': [base64.b64encode(encoded).decode(), 'base64']}]}},
            'meta': {'err': None, 'fee': 5000, 'preBalances': pre_native, 'postBalances': post_native,
                     'preTokenBalances': pre_token, 'postTokenBalances': post_token,
                     'innerInstructions': [{'index': 0, 'instructions': movements}]}}


class PositionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(self.folder.name)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.store.close)
        self.raws = [raw_exchange('synthetic-buy', 100, START + 3600, 0, 100),
                     raw_exchange('synthetic-partial-sale', 101, START + 2 * 3600, 100, 50),
                     raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 50, 0)]
        self.seed()

    def seed(self):
        self.anchor = self.store.archive({'method': 'getSlot', 'commitment': 'finalized', 'result': 1000})
        self.cp = {'version': COLLECTOR_VERSION, 'address': WALLET, 'start': START, 'end': END,
                   'basis_floor': START - 90 * 86400,
                   'snapshot': {'slot': 1000, 'commitment': 'finalized', 'anchor_evidence': self.anchor},
                   'accounts': {}, 'transactions': {}, 'evidence': [{'hash': self.anchor, 'kind': 'snapshot-slot'}],
                   'ordering': {}, 'account_scope': {'included_account_count': 2, 'omitted_account_count': 0}}
        self.records = []
        for raw in self.raws:
            signature = raw['transaction']['signatures'][0]
            digest = self.store.archive(raw)
            self.cp['transactions'][signature] = {'signature': signature, 'evidence_hash': digest}
            self.cp['evidence'].append({'hash': digest, 'kind': 'transaction', 'signature': signature})
            self.records.append({'signature': signature, 'evidence_hash': digest})
        self.pages = {}
        entries = sorted([entry(raw['transaction']['signatures'][0], raw) for raw in self.raws], key=lambda item: (item['slot'], item['signature']), reverse=True)
        for account in (WALLET, ACCOUNT):
            initial = self.store.archive({'method': 'getSignaturesForAddress', 'address': account,
                                         'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000}, 'result': entries})
            terminal = self.store.archive({'method': 'getSignaturesForAddress', 'address': account,
                                          'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000, 'before': entries[-1]['signature']}, 'result': []})
            self.pages[account] = (initial, terminal)
            self.cp['evidence'].extend([{'hash': initial, 'kind': 'signature-page'}, {'hash': terminal, 'kind': 'signature-page'}])
            self.cp['accounts'][account] = {'address': account, 'origin': 'wallet' if account == WALLET else 'event-time token-balance owner',
                                            'ownership_evidence': self.anchor if account == WALLET else self.records[0]['evidence_hash'],
                                            'cursor': entries[-1]['signature'], 'terminal': 'empty signature page', 'terminal_evidence': terminal}
        self.persist()

    def persist(self):
        key = hashlib.sha256(f'{WALLET}:{START}:{END}'.encode()).hexdigest()
        self.store.put('collector_checkpoints', key, self.cp)

    def derive(self, **kwargs):
        return derive_position_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp,
                                        collected={'transactions': self.records, 'checkpoint': self.cp}, **kwargs)

    def replace_raw(self, index, change):
        raw = deepcopy(self.raws[index])
        change(raw)
        self.raws[index] = raw
        self.seed()

    def rearchive_raw_without_changing_pages(self, index, change):
        raw = deepcopy(self.raws[index])
        change(raw)
        self.raws[index] = raw
        signature = raw['transaction']['signatures'][0]
        digest = self.store.archive(raw)
        self.cp['transactions'][signature]['evidence_hash'] = digest
        for record in self.records:
            if record['signature'] == signature:
                record['evidence_hash'] = digest
        for reference in self.cp['evidence']:
            if reference.get('kind') == 'transaction' and reference.get('signature') == signature:
                reference['hash'] = digest
        self.persist()
        return digest

    def link_raw_alternative(self, index, change, reverse=False):
        raw = deepcopy(self.raws[index])
        signature = raw['transaction']['signatures'][0]
        change(raw)
        digest = self.store.archive(raw)
        self.cp['evidence'].append({'hash': digest, 'kind': 'transaction', 'signature': signature})
        if reverse:
            self.cp['evidence'].reverse()
        self.persist()
        return digest

    def remove_archive(self, digest):
        for path in (self.store.path / 'evidence').glob(f'{digest}*'):
            path.unlink()

    def assert_unknown(self, result):
        self.assertEqual(result['counts']['known_closed'], 0)
        self.assertEqual(result['known_account_hold_median_hours']['status'], 'unknown')
        self.assertIsNone(result['known_account_hold_median_hours']['value'])
        self.assertTrue(all(position['hold_hours']['value'] is None for position in result['positions']))

    def test_multitransaction_account_strict_zero_branch_is_executable(self):
        result = self.derive()
        self.assertEqual(result['version'], 'account-position-evidence-v10')
        self.assertEqual(result['counts'], {'known_closed': 1, 'open': 0, 'unresolved': 0})
        self.assertEqual(result['account_scope']['candidate_account_count'], 1)
        self.assertEqual(result['account_scope']['inspected_account_count'], 1)
        self.assertEqual(result['account_scope']['omitted_account_count'], 0)
        self.assertIn('evaluated known subset', result['known_account_hold_median_hours']['population'])
        position = result['positions'][0]
        self.assertEqual(position['hold_hours']['value'], '6')
        self.assertEqual(position['opening_raw'], '0')
        self.assertEqual(position['closing_raw'], '0')
        self.assertEqual(position['acquired_raw'], '100')
        self.assertEqual(position['sold_raw'], '100')
        self.assertEqual(position['account'], ACCOUNT)
        for key in ('collection', 'identity', 'source_consistency', 'opening_zero', 'chronology', 'placement', 'quantities', 'continuity', 'strict_zero', 'hold'):
            self.assertEqual(position['stages'][key]['state'], 'PASS')
        self.assertIn('no wallet-wide', result['scope'])
        history = derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp)
        self.assertEqual(set(history['evidence_gates'].values()), {'UNKNOWN'})

    def test_hold_independent_of_missing_prices_native_costs_and_classification(self):
        for raw in self.raws:
            for key in ('fee', 'preBalances', 'postBalances'):
                raw['meta'].pop(key)
        self.seed()
        result = self.derive()
        self.assertEqual(result['positions'][0]['hold_hours']['value'], '6')
        for key in ('basis', 'fees', 'classification', 'valuation'):
            self.assertEqual(result['positions'][0]['stages'][key]['state'], 'UNKNOWN')
        records = [{**record, 'raw': self.store.evidence(record['evidence_hash'])} for record in self.records]
        self.assertEqual(decode_supported_swaps(records, WALLET)['coverage']['decoded_swaps'], 0)

    def test_linked_absolute_boundary_conflict_revokes_hold_without_delta_netting(self):
        original = deepcopy(self.raws)
        for index, offset, affected in ((0, 200, 'opening_zero'), (2, 1, 'strict_zero')):
            for reverse in (False, True):
                with self.subTest(index=index, reverse=reverse):
                    self.raws = deepcopy(original)
                    self.seed()
                    def alter(raw):
                        for field in ('preTokenBalances', 'postTokenBalances'):
                            row = next(row for row in raw['meta'][field] if row['accountIndex'] == 1)
                            row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + offset)
                    digest = self.link_raw_alternative(index, alter, reverse)
                    result = self.derive()
                    self.assert_unknown(result)
                    position = result['positions'][0]
                    for stage in ('source_consistency', 'quantities', 'continuity', affected):
                        self.assertEqual(position['stages'][stage]['state'], 'UNKNOWN')
                    self.assertIn(digest, position['stages']['source_consistency']['evidence'])
                    self.assertIn(digest, position['sources'])
                    history = derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp,
                                                      collected={'transactions': self.records})
                    fee = history['native_address_metrics']['observed']['wallet_network_fees_sol']
                    self.assertEqual(fee['value'], '0.000015')
                    self.assertEqual(fee['record_count'], 3)

    def test_distinct_archives_with_same_supported_semantics_preserve_hold(self):
        original = deepcopy(self.raws)
        def reorder(raw):
            for field in ('preTokenBalances', 'postTokenBalances'):
                raw['meta'][field].reverse()
        def omit_program(raw):
            for field in ('preTokenBalances', 'postTokenBalances'):
                for row in raw['meta'][field]:
                    row.pop('programId', None)
        changes = [lambda raw: raw['meta'].update(logMessages=[]), reorder, omit_program,
                   lambda raw: [raw['meta'].pop(field) for field in ('fee', 'preBalances', 'postBalances')]]
        for index in (0, 2):
            for change in changes:
                with self.subTest(index=index, change=change):
                    self.raws = deepcopy(original)
                    self.seed()
                    digest = self.link_raw_alternative(index, change)
                    result = self.derive()
                    self.assertEqual(result['counts']['known_closed'], 1)
                    self.assertEqual(result['positions'][0]['hold_hours']['value'], '6')
                    self.assertEqual(result['positions'][0]['stages']['source_consistency']['state'], 'PASS')
                    self.assertIn(digest, result['positions'][0]['sources'])
                    self.assertTrue(any(item['hash'] == digest for item in result['positions'][0]['source_paths']))

    def test_alternate_unsupported_operation_is_not_hidden_by_matching_boundary_facts(self):
        digest = self.link_raw_alternative(0, lambda raw: raw['transaction']['message']['instructions'].append(
            {'programId': address(40), 'accounts': [ACCOUNT], 'data': '1'}))
        result = self.derive()
        self.assert_unknown(result)
        position = result['positions'][0]
        self.assertEqual(position['stages']['source_consistency']['state'], 'UNKNOWN')
        self.assertIn(digest, position['sources'])
        self.assertIn('opaque account operation', position['stages']['source_consistency']['reason'])

    def test_malformed_transaction_alternative_is_inspectable_unknown(self):
        original = deepcopy(self.raws)
        for transaction in (None, [], 'malformed transaction'):
            with self.subTest(transaction=transaction):
                self.raws = deepcopy(original)
                self.seed()
                digest = self.link_raw_alternative(0, lambda raw: raw.update(transaction=transaction))
                result = self.derive()
                self.assert_unknown(result)
                position = result['positions'][0]
                self.assertEqual(position['stages']['source_consistency']['state'], 'UNKNOWN')
                self.assertIn(digest, position['sources'])
                self.assertIn(digest, position['stages']['source_consistency']['evidence'])
                self.assertTrue(any(item['hash'] == digest for item in position['source_paths']))
                history = derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp,
                                                  collected={'transactions': self.records})
                observed = history['native_address_metrics']['observed']
                for metric in ('wallet_network_fees_sol', 'native_wallet_delta_sol'):
                    self.assertEqual(observed[metric]['status'], 'unknown')
                    self.assertIsNone(observed[metric]['value'])

    def test_missing_distinct_boundary_archive_never_restores_a_known_hold(self):
        digest = self.link_raw_alternative(0, lambda raw: raw['meta'].update(logMessages=[]))
        self.assertEqual(self.derive()['counts']['known_closed'], 1)
        self.remove_archive(digest)
        result = self.derive(history_evidence={'source_consistency': 'PASS'})
        self.assert_unknown(result)
        self.assertIn(digest, result['positions'][0]['stages']['source_consistency']['evidence'])

    def test_complete_duplicate_link_index_preserves_scope_and_native_cap_is_independent(self):
        digest = self.link_raw_alternative(0, lambda raw: raw['meta'].update(logMessages=[]))
        late = self.cp['evidence'].pop()
        padding = deepcopy(next(reference for reference in self.cp['evidence'] if reference['kind'] == 'transaction'))
        self.cp['evidence'] += [deepcopy(padding) for _ in range(40001 - len(self.cp['evidence']) - 1)]
        self.cp['evidence'].append(late)
        self.persist()
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 1)
        position = result['positions'][0]
        source_set = position['source_set']
        self.assertEqual(source_set['state'], 'PASS')
        self.assertTrue(source_set['complete'])
        self.assertEqual(source_set['raw_reference_count'], 40001)
        self.assertEqual(source_set['authenticated_reference_count'], 40001)
        self.assertEqual(source_set['unique_hash_count'], 9)
        self.assertEqual(source_set['inspected_hash_count'], 9)
        self.assertEqual(source_set['omitted_hash_count'], 0)
        self.assertEqual(source_set['omitted_link_count'], 0)
        self.assertEqual(source_set['invalid_authenticated_link_count'], 0)
        self.assertIn('source_set', position['stages']['source_consistency']['dependencies'])
        self.assertIn(digest, position['sources'])
        history = derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp,
                                          collected={'transactions': self.records})
        for metric in history['native_address_metrics']['observed'].values():
            self.assertEqual(metric['status'], 'unknown')
            self.assertIsNone(metric['value'])

    def test_genuine_unique_source_budget_omission_cannot_certify_prefix_facts(self):
        from scanner.source_consistency import index_source_links
        def constrained_index(references, *, authenticated_references, max_unique_hashes):
            return index_source_links(references, authenticated_references=authenticated_references, max_unique_hashes=7)
        # Dependency injection changes only this unit's archive budget, while
        # preserving actual authenticated indexing and all stored source links.
        with patch('scanner.history_evidence.index_source_links', side_effect=constrained_index):
            result = self.derive(history_evidence={'source_set': {'state': 'PASS', 'complete': True}})
        self.assert_unknown(result)
        position = result['positions'][0]
        source_set = position['source_set']
        self.assertEqual(source_set['state'], 'UNKNOWN')
        self.assertFalse(source_set['complete'])
        self.assertEqual(source_set['unique_hash_count'], 8)
        self.assertEqual(source_set['inspected_hash_count'], 0)
        self.assertEqual(source_set['omitted_hash_count'], 8)
        self.assertEqual(source_set['omitted_scope'], 'entire-source-set')
        for stage in ('source_consistency', 'opening_zero', 'quantities', 'continuity', 'strict_zero', 'hold'):
            self.assertEqual(position['stages'][stage]['state'], 'UNKNOWN')

    def test_quantity_conflict_is_local_to_affected_episode(self):
        self.raws += [raw_exchange('synthetic-second-buy', 200, START + 2 * 86400, 0, 200),
                      raw_exchange('synthetic-second-sale', 202, START + 2 * 86400 + 4 * 3600, 200, 0)]
        self.seed()
        def offset(raw):
            for field in ('preTokenBalances', 'postTokenBalances'):
                raw['meta'][field][0]['uiTokenAmount']['amount'] = str(int(raw['meta'][field][0]['uiTokenAmount']['amount']) + 200)
        self.link_raw_alternative(0, offset)
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 1)
        self.assertEqual(result['positions'][0]['stages']['source_consistency']['state'], 'UNKNOWN')
        self.assertEqual(result['positions'][1]['hold_hours']['value'], '4')
        self.assertEqual(result['positions'][1]['stages']['source_consistency']['state'], 'PASS')

    def test_missing_intervening_raw_revokes_hold_with_targeted_recovery(self):
        self.remove_archive(self.records[1]['evidence_hash'])
        result = self.derive()
        self.assert_unknown(result)
        self.assertTrue(any(action['kind'] == 'retrieve_raw' and action.get('signature') == 'synthetic-partial-sale' for action in result['recovery_actions']))

    def test_missing_opening_raw_or_snapshot_revokes_hold(self):
        for digest in (self.records[0]['evidence_hash'], self.anchor):
            with self.subTest(digest=digest):
                self.seed()
                self.remove_archive(digest)
                self.assert_unknown(self.derive())

    def test_missing_page_or_terminal_receipt_revokes_hold(self):
        for page_index in (0, 1):
            with self.subTest(page_index=page_index):
                self.seed()
                self.remove_archive(self.pages[ACCOUNT][page_index])
                self.assert_unknown(self.derive())

    def test_missing_relevant_raw_balance_revokes_hold(self):
        self.replace_raw(1, lambda raw: raw['meta']['preTokenBalances'].pop(0))
        result = self.derive()
        self.assert_unknown(result)
        self.assertTrue(any(action['kind'] == 'recover_balance' for action in result['recovery_actions']))

    def test_ownership_change_and_quantity_discontinuity_revoke_hold(self):
        original = deepcopy(self.raws)
        changes = [lambda raw: raw['meta']['postTokenBalances'][0].update(owner=POOL),
                   lambda raw: raw['meta']['preTokenBalances'][0]['uiTokenAmount'].update(amount='101')]
        for change in changes:
            with self.subTest(change=change):
                self.raws = deepcopy(original)
                self.replace_raw(1, change)
                self.assert_unknown(self.derive())

    def test_explicit_token_program_identity_conflicts_revoke_hold(self):
        token_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
        original = deepcopy(self.raws)
        for scope in ('within_transaction', 'between_transactions'):
            with self.subTest(scope=scope):
                self.raws = deepcopy(original)
                if scope == 'within_transaction':
                    self.raws[0]['meta']['postTokenBalances'][0]['programId'] = token_2022
                else:
                    # Each sale is internally consistent with Token-2022, but
                    # contradicts the earlier account-program identity.
                    for raw in self.raws[1:]:
                        for name in ('preTokenBalances', 'postTokenBalances'):
                            raw['meta'][name][0]['programId'] = token_2022
                        raw['meta']['innerInstructions'][0]['instructions'][0]['programId'] = token_2022
                self.seed()
                self.assert_unknown(self.derive())

    def test_legacy_missing_program_annotations_use_explicit_token_operations(self):
        for raw in self.raws:
            for name in ('preTokenBalances', 'postTokenBalances'):
                raw['meta'][name][0].pop('programId')
        self.seed()
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 1)
        self.assertEqual(result['positions'][0]['program_id'], TOKEN_PROGRAM)

    def test_same_slot_order_is_required_and_removal_revokes_known_hold(self):
        self.raws[2]['slot'] = 101
        # Transactions from one slot share the slot timestamp. Both sales close
        # at the later instant, retaining the six-hour acquisition-to-close hold.
        self.raws[1]['blockTime'] = self.raws[2]['blockTime']
        self.seed()
        self.assert_unknown(self.derive())
        block = self.store.archive({'method': 'getBlock', 'slot': 101, 'result': {'signatures': ['synthetic-partial-sale', 'synthetic-final-sale']}})
        self.cp['evidence'].append({'hash': block, 'kind': 'block-order'})
        self.cp['ordering'] = {'synthetic-partial-sale': 0, 'synthetic-final-sale': 1}
        self.persist()
        self.assertEqual(self.derive()['positions'][0]['hold_hours']['value'], '6')
        self.remove_archive(block)
        self.assert_unknown(self.derive())

    def test_failed_receipt_updates_chronology_without_price_or_owner_changes(self):
        failed = deepcopy(self.raws[1])
        failed['transaction']['signatures'] = ['synthetic-failed']
        failed['slot'], failed['blockTime'] = 101, START + 2 * 3600
        failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
        # Later-slot final sale has an earlier canonical time than the failed record.
        sale = raw_exchange('synthetic-final-sale', 102, START + 3600 + 1800, 100, 0)
        self.raws = [self.raws[0], failed, sale]
        self.seed()
        result = self.derive()
        self.assert_unknown(result)
        self.assertEqual(result['positions'][0]['stages']['chronology']['state'], 'UNKNOWN')
        self.raws[-1]['blockTime'] = START + 7 * 3600
        self.seed()
        self.assertEqual(self.derive()['positions'][0]['hold_hours']['value'], '6')

    def test_slot_intervening_records_are_dependencies_before_timestamp_filtering(self):
        original_buy = deepcopy(self.raws[0])
        final = raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0)
        for timestamp in (END, END + 3600, START - 1, None):
            for remove_raw in (False, True):
                with self.subTest(timestamp=timestamp, remove_raw=remove_raw):
                    middle = raw_exchange('synthetic-window-crossing-failed', 101, timestamp, 100, 100)
                    middle['meta'].update(err={'InstructionError': [0, 'Custom']},
                                          preTokenBalances=[], postTokenBalances=[])
                    self.raws = [original_buy, middle, final]
                    self.seed()
                    if remove_raw:
                        self.remove_archive(self.records[1]['evidence_hash'])
                    result = self.derive()
                    self.assert_unknown(result)
                    self.assertTrue(any('synthetic-window-crossing-failed' in position['signatures'] for position in result['positions']))

    def test_conflicting_raw_slot_cannot_exclude_page_intervening_dependency(self):
        buy = deepcopy(self.raws[0])
        failed = raw_exchange('synthetic-placement-failed', 101, START + 3 * 3600, 100, 100)
        failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
        sale = raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0)
        for native_slot in (99, 103):
            with self.subTest(native_slot=native_slot):
                self.raws = deepcopy([buy, failed, sale])
                self.seed()
                digest = self.rearchive_raw_without_changing_pages(1, lambda raw: raw.update(slot=native_slot))
                result = self.derive()
                self.assert_unknown(result)
                position = next(p for p in result['positions'] if p['id'].endswith('synthetic-buy'))
                self.assertEqual(position['stages']['placement']['state'], 'UNKNOWN')
                self.assertIn('synthetic-placement-failed', position['signatures'])
                self.assertIn(digest, position['sources'])
                self.assertIn(digest, position['stages']['placement']['evidence'])

    def test_placement_revocation_is_local_to_intersected_episode(self):
        failed = raw_exchange('synthetic-placement-failed', 101, START + 3 * 3600, 100, 100)
        failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
        self.raws = [deepcopy(self.raws[0]), failed,
                     raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0),
                     raw_exchange('synthetic-second-buy', 200, START + 2 * 86400, 0, 200),
                     raw_exchange('synthetic-second-sale', 202, START + 2 * 86400 + 4 * 3600, 200, 0)]
        self.seed()
        digest = self.rearchive_raw_without_changing_pages(1, lambda raw: raw.update(slot=99))
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 1)
        first, second = result['positions']
        self.assertEqual(first['hold_hours']['status'], 'unknown')
        self.assertEqual(second['hold_hours']['value'], '4')
        proof = next(item for item in second['dependency_exclusions'] if item['signature'] == 'synthetic-placement-failed')
        self.assertEqual(proof['relation'], 'before')
        self.assertEqual(proof['slot_bounds'], {'bounded': True, 'min': 99, 'max': 101})
        self.assertIn(digest, proof['evidence'])
        self.assertIn(digest, second['hold_hours']['evidence'])
        self.assertNotIn('synthetic-placement-failed', second['signatures'])

    def test_contradictory_slots_wholly_outside_have_explicit_exclusion_proof(self):
        base = deepcopy(self.raws)
        for page_slot, native_slot, timestamp, relation in ((98, 99, START + 600, 'before'),
                                                          (104, 103, START + 8 * 3600, 'after')):
            with self.subTest(relation=relation):
                outside = raw_exchange('synthetic-excluded-failed', page_slot, timestamp, 0, 0)
                outside['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
                self.raws = deepcopy(base) + [outside]
                self.seed()
                digest = self.rearchive_raw_without_changing_pages(3, lambda raw: raw.update(slot=native_slot))
                result = self.derive()
                self.assertEqual(result['counts']['known_closed'], 1)
                position = result['positions'][0]
                self.assertEqual(position['hold_hours']['value'], '6')
                proof = next(item for item in position['dependency_exclusions'] if item['signature'] == 'synthetic-excluded-failed')
                self.assertEqual(proof['relation'], relation)
                self.assertEqual(proof['slot_bounds']['min'], min(page_slot, native_slot))
                self.assertEqual(proof['slot_bounds']['max'], max(page_slot, native_slot))
                self.assertIn(digest, proof['evidence'])
                self.assertIn(digest, position['hold_hours']['evidence'])

    def test_slot_and_index_bounds_never_exclude_potential_intersections(self):
        def bounds(slots, indices=None):
            return {'unbounded': False, 'slot_bounds': {'bounded': True, 'min': min(slots), 'max': max(slots)},
                    'indices_by_slot': indices or {}}
        opening, closing = (100, 1), (102, 2)
        cases = [
            (bounds([99]), 'before'), (bounds([103]), 'after'),
            (bounds([99, 103]), 'potential'), (bounds([100]), 'potential'), (bounds([102]), 'potential'),
            (bounds([100], {'100': {'bounded': True, 'min': 0, 'max': 0}}), 'before'),
            (bounds([102], {'102': {'bounded': True, 'min': 3, 'max': 3}}), 'after'),
            (bounds([100], {'100': {'bounded': True, 'min': 0, 'max': 2}}), 'potential'),
            ({'unbounded': True, 'slot_bounds': {'bounded': False}}, 'potential'), ({}, 'potential'),
        ]
        for placement, relation in cases:
            with self.subTest(placement=placement):
                self.assertEqual(_placement_relation(placement, opening, closing)[0], relation)

    def test_same_slot_exclusion_requires_archived_index_proof(self):
        failed = raw_exchange('synthetic-before-same-slot-failed', 100, START + 3600, 0, 0)
        failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
        self.raws = [deepcopy(self.raws[0]), failed,
                     raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0)]
        self.seed()
        block = self.store.archive({'method': 'getBlock', 'slot': 100, 'result': {
            'signatures': ['synthetic-before-same-slot-failed', 'synthetic-buy']}})
        self.cp['evidence'].append({'hash': block, 'kind': 'block-order'})
        self.cp['ordering'] = {'synthetic-before-same-slot-failed': 0, 'synthetic-buy': 1}
        self.persist()
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 1)
        position = result['positions'][0]
        self.assertNotIn('synthetic-before-same-slot-failed', position['signatures'])
        self.assertIn(block, result['account_placement_sources'][ACCOUNT])
        self.assertIn(block, position['hold_hours']['evidence'])
        self.remove_archive(block)
        self.assert_unknown(self.derive())

    def test_uncertain_exclusion_cap_is_explicit_and_does_not_partially_pass(self):
        # Consistent page-only placements are independently outside the episode,
        # but too many unresolved raw sources must not create an unbounded proof.
        for count in (64, 65):
            with self.subTest(count=count):
                self.raws = [raw_exchange('synthetic-buy', 100, START + 3600, 0, 100),
                             raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0)]
                for index in range(count):
                    outside = raw_exchange(f'synthetic-page-only-{index}', index + 1, START + index, 0, 0)
                    outside['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
                    self.raws.append(outside)
                self.seed()
                for record in self.records[2:]:
                    self.remove_archive(record['evidence_hash'])
                result = self.derive()
                position = next(p for p in result['positions'] if p['id'].endswith('synthetic-buy'))
                self.assertEqual(position['placement_scope'], {
                    'max_uncertain_exclusions': 64, 'inspected_uncertain_exclusions': 64,
                    'omitted_uncertain_exclusions': count - 64, 'complete': count == 64})
                self.assertLessEqual(len(position['dependency_exclusions']), 64)
                self.assertEqual(position['acquired_raw'], '100')
                self.assertEqual(position['sold_raw'], '100')
                self.assertEqual(position['hold_hours']['value'], '6' if count == 64 else None)
                self.assertEqual(position['stages']['placement']['state'], 'PASS' if count == 64 else 'UNKNOWN')

    def test_later_unrelated_out_of_window_records_preserve_earlier_known_episode(self):
        earlier = deepcopy(self.raws)
        for timestamp in (END, END + 3600):
            for remove_raw in (False, True):
                with self.subTest(timestamp=timestamp, remove_raw=remove_raw):
                    later = raw_exchange('synthetic-later-unrelated-failed', 103, timestamp, 0, 0)
                    later['meta'].update(err={'InstructionError': [0, 'Custom']},
                                         preTokenBalances=[], postTokenBalances=[])
                    self.raws = earlier + [later]
                    self.seed()
                    if remove_raw:
                        self.remove_archive(self.records[-1]['evidence_hash'])
                    result = self.derive()
                    self.assertEqual(result['counts']['known_closed'], 1)
                    position = next(p for p in result['positions'] if p['status'] == 'known_closed')
                    self.assertEqual(position['hold_hours']['value'], '6')
                    self.assertNotIn('synthetic-later-unrelated-failed', position['signatures'])

    def test_output_completed_population_remains_half_open_after_dependency_checks(self):
        for closing_time, expected in ((START, 1), (END - 1, 1), (END, 0), (END + 3600, 0)):
            with self.subTest(closing_time=closing_time):
                self.raws = [raw_exchange('synthetic-boundary-buy', 100, closing_time - 6 * 3600, 0, 100),
                             raw_exchange('synthetic-boundary-sale', 101, closing_time, 100, 0)]
                self.seed()
                result = self.derive()
                self.assertEqual(result['counts']['known_closed'], expected)
                if expected:
                    self.assertEqual(result['positions'][0]['hold_hours']['value'], '6')

    def test_missing_frozen_source_is_rejected_by_loader_without_direct_helper_pass(self):
        from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
        from scanner.storage import EvidenceError
        collected = {'transactions': self.records, 'checkpoint': self.cp,
                     'snapshot': self.cp['snapshot'], 'evidence': self.cp['evidence'], 'coverage': {}}
        report = {'source': 'live', 'address': WALLET, 'window': WINDOW,
                  'collection_input_hash': freeze_report_inputs(self.store, WALLET, WINDOW, collected)}
        self.remove_archive(self.records[1]['evidence_hash'])
        self.assert_unknown(self.derive())
        with self.assertRaises(EvidenceError):
            load_report_inputs(self.store, report)

    def test_missing_inner_recording_cannot_hide_intervening_zero_net_exchange(self):
        middle = raw_exchange('synthetic-zero-net-route', 101, START + 2 * 3600, 100, 100)
        final = raw_exchange('synthetic-final-sale', 102, START + 7 * 3600, 100, 0)
        for shape in ('missing', 'null', 'missing_group', 'null_group', 'duplicate_group'):
            with self.subTest(shape=shape):
                altered = deepcopy(middle)
                if shape == 'missing':
                    altered['meta'].pop('innerInstructions')
                elif shape == 'null':
                    altered['meta']['innerInstructions'] = None
                elif shape == 'missing_group':
                    altered['meta']['innerInstructions'] = [{'index': 0}]
                elif shape == 'null_group':
                    altered['meta']['innerInstructions'] = [{'index': 0, 'instructions': None}]
                else:
                    altered['meta']['innerInstructions'] = [{'index': 0, 'instructions': []}, {'index': 0, 'instructions': []}]
                self.raws = [raw_exchange('synthetic-buy', 100, START + 3600, 0, 100), altered, final]
                self.seed()
                result = self.derive()
                self.assert_unknown(result)
                self.assertTrue(any(action.get('signature') == 'synthetic-zero-net-route' and action['kind'] == 'recover_balance' for action in result['recovery_actions']))
        # Explicit recorded emptiness is distinct from disabled/missing recording.
        for recorded in ([], [{'index': 0, 'instructions': []}]):
            with self.subTest(recorded=recorded):
                explicit = deepcopy(middle)
                explicit['meta']['innerInstructions'] = recorded
                self.raws = [raw_exchange('synthetic-buy', 100, START + 3600, 0, 100), explicit, final]
                self.seed()
                self.assertEqual(self.derive()['counts']['known_closed'], 1)

    def test_individual_outside_transfer_cannot_be_netted_into_a_spot_episode(self):
        def change(raw):
            raw['transaction']['message']['instructions'].extend([transfer(ACCOUNT, POOL_TOKEN, 10), transfer(POOL_TOKEN, ACCOUNT, 10)])
        self.replace_raw(1, change)
        result = self.derive()
        self.assert_unknown(result)
        self.assertTrue(any('interrupts' in action['reason'] for action in result['recovery_actions']))

    def test_initial_unsupported_operation_is_not_hidden_from_recovery(self):
        self.raws = [self.raws[0]]
        self.raws[0]['transaction']['message']['instructions'].append({'programId': address(22), 'accounts': [ACCOUNT], 'data': '1'})
        self.seed()
        result = self.derive()
        self.assertEqual(result['counts']['known_closed'], 0)
        self.assertTrue(any(action['kind'] == 'recover_balance' and action.get('signature') == 'synthetic-buy' for action in result['recovery_actions']))

    def test_missing_opaque_account_references_are_not_an_exclusion_proof(self):
        original = deepcopy(self.raws)
        for missing in ({}, {'accounts': None}, {'accounts': 'invalid'}):
            with self.subTest(missing=missing):
                self.raws = deepcopy(original)
                self.raws[1]['transaction']['message']['instructions'].append({'programId': address(23), 'data': '1', **missing})
                self.seed()
                self.assert_unknown(self.derive())

    def test_account_specific_metadata_conflict_revokes_dependent_hold(self):
        page = self.store.evidence(self.pages[ACCOUNT][0])
        page['result'][1]['blockTime'] += 1
        new_hash = self.store.archive(page)
        old_hash = self.pages[ACCOUNT][0]
        self.cp['evidence'] = [ref for ref in self.cp['evidence'] if ref['hash'] != old_hash]
        self.cp['evidence'].append({'hash': new_hash, 'kind': 'signature-page'})
        self.persist()
        self.assert_unknown(self.derive())

    def test_imported_pass_flags_do_not_establish_primary_hold(self):
        self.remove_archive(self.anchor)
        forged = {'paging': {'accounts': [{'address': ACCOUNT, 'chain': {'state': 'PASS'}}]},
                  'evidence_gates': {key: 'PASS' for key in ('history', 'positions', 'basis')}}
        self.assert_unknown(self.derive(history_evidence=forged))

    def test_rebuild_reproducible_no_writes_or_usage(self):
        first = self.derive()
        rows = self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        files = set((self.store.path / 'evidence').iterdir())
        self.assertEqual(self.derive(), first)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], rows)
        self.assertEqual(set((self.store.path / 'evidence').iterdir()), files)
        self.assertEqual(derive_position_evidence(self.store, WALLET, WINDOW), first)
        raw_hashes = {record['evidence_hash'] for record in self.records}
        for key in ('collection', 'identity', 'quantities', 'continuity', 'chronology'):
            self.assertTrue(raw_hashes.issubset(set(first['positions'][0]['stages'][key]['evidence'])))

    def test_genuine_cached_buy_nonzero_inventory_remains_unknown_with_backfill(self):
        record = json.loads((Path(__file__).parent / 'fixtures/mainnet-pumpswap-buy-exact-quote.json').read_text())
        raw = record['raw']
        owner = raw['transaction']['message']['accountKeys'][0]['pubkey']
        digest = self.store.archive(raw)
        result = derive_position_evidence(self.store, owner,
                                          {'start': raw['blockTime'] - 86400, 'end': raw['blockTime'] + 86400},
                                          collected={'transactions': [{'signature': record['signature'], 'evidence_hash': digest}]})
        self.assert_unknown(result)
        candidate = next(position for position in result['positions'] if position['mint'] == 'GAwhcphCqCv5bKHmCiN4VDdNWfbXJL4npmkc8L3Q9S9H')
        self.assertEqual(candidate['opening_raw'], '44824210540')
        self.assertEqual(candidate['stages']['opening_zero']['state'], 'UNKNOWN')
        self.assertTrue(any(action['kind'] == 'acquisition_backfill' and action.get('before') == record['signature'] for action in result['recovery_actions']))
        self.assertFalse(any(position['status'] == 'known_closed' for position in result['positions']))


if __name__ == '__main__':
    unittest.main()
