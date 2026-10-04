"""Independent R6 controls using synthetic local archives, never mainnet proof.

The reviewer supplied a Markdown report, not its evidence ZIP. These controls
reconstruct the described trust-boundary defect with the shipped history builder.
Their signatures and account histories are deliberately synthetic.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib

import pytest

from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import derive_position_evidence
from scanner.providers import TOKEN_PROGRAM
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from tests import test_history_evidence as history_builder
from tests import test_investigation as swap_builder


WALLET = history_builder.WALLET
TOKEN_ACCOUNT = history_builder.TOKEN_ACCOUNT
# Base58(SHA256('review-v032-synthetic-token-account')); no chain provenance.
POSITION_ACCOUNT = '93o2mC3LXJCK5Mw9zpf6s9yCv4AorsJogKscstatc23z'
START = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
WINDOW = {"start": START, "end": END}
IDENTIFIER = hashlib.sha256(f"{WALLET}:{START}:{END}".encode()).hexdigest()


class SyntheticHistory:
    def __init__(self):
        self.builder = history_builder.HistoryEvidenceTests(methodName="runTest")
        self.builder.setUp()
        self.store = self.builder.store
        self.cp = self.builder.cp
        self.cp.update(start=START, end=END, basis_floor=START - 90 * 86400,
                       accounts={}, transactions={},
                       evidence=[{"hash": self.builder.anchor, "kind": "snapshot-slot"}],
                       account_scope={"included_account_count": 2, "omitted_account_count": 0})
        self.builder.entries = [self.builder.entry("at-end", END, 1500)]
        self.add_transaction("inside", END - 86400, 1200)
        self.add_transaction("boundary", START - 1, 1100)
        self.builder.entries.append(self.builder.entry("older-basis", self.cp["basis_floor"] - 1, 900))
        ownership = {"method": "getTokenAccountsByOwner", "owner": WALLET,
                     "program": TOKEN_PROGRAM,
                     "result": {"context": {"slot": 2000}, "value": [
                         {"pubkey": TOKEN_ACCOUNT, "account": {"data": {"parsed": {
                             "info": {"owner": WALLET}}}}}]}}
        self.ownership_hash = self.store.archive(ownership)
        # Match the native collector's actual role; the ownership blob is unchanged.
        self.cp["evidence"].append({"kind": "owned-accounts", "hash": self.ownership_hash})
        self.pages = {account: deepcopy(self.builder.entries) for account in (WALLET, TOKEN_ACCOUNT)}
        self.save_pages()

    def close(self):
        self.builder.doCleanups()

    def add_transaction(self, signature, timestamp, slot):
        old_hash = self.builder.add_transaction(signature, timestamp, slot)
        raw = self.store.evidence(old_hash)
        raw["transaction"]["message"]["accountKeys"].append(TOKEN_ACCOUNT)
        raw["meta"]["preBalances"].append(0)
        raw["meta"]["postBalances"].append(0)
        digest = self.store.archive(raw)
        self.cp["transactions"][signature]["evidence_hash"] = digest
        for reference in self.cp["evidence"]:
            if reference.get("kind") == "transaction" and reference.get("signature") == signature:
                reference["hash"] = digest
        return digest

    def save_pages(self):
        self.cp["evidence"] = [reference for reference in self.cp["evidence"]
                               if reference["kind"] != "signature-page"]
        for account, entries in self.pages.items():
            digest = self.builder.add_page(entries, address=account)
            receipt = self.builder.account(account, digest, entries[-1]["signature"])
            if account != WALLET:
                receipt["ownership_evidence"] = self.ownership_hash
            self.cp["accounts"][account] = receipt
        self.save()

    def save(self):
        self.store.put("collector_checkpoints", IDENTIFIER, self.cp)

    def mutate_entry(self, account, signature, **changes):
        entry = next(entry for entry in self.pages[account] if entry["signature"] == signature)
        entry.update(changes)
        self.save_pages()

    def retime_transaction(self, signature, timestamp):
        record = self.cp["transactions"][signature]
        raw = self.store.evidence(record["evidence_hash"])
        raw["blockTime"] = timestamp
        digest = self.store.archive(raw)
        record["evidence_hash"] = digest
        for reference in self.cp["evidence"]:
            if reference.get("kind") == "transaction" and reference.get("signature") == signature:
                reference["hash"] = digest
        for entries in self.pages.values():
            next(entry for entry in entries if entry["signature"] == signature)["blockTime"] = timestamp
        self.save_pages()

    def replace_transaction(self, signature, raw):
        digest = self.store.archive(raw)
        self.cp["transactions"][signature]["evidence_hash"] = digest
        for reference in self.cp["evidence"]:
            if reference.get("kind") == "transaction" and reference.get("signature") == signature:
                reference["hash"] = digest
        for entries in self.pages.values():
            entry = next(entry for entry in entries if entry["signature"] == signature)
            entry.update(slot=raw["slot"], blockTime=raw["blockTime"], err=raw["meta"]["err"])
        self.save_pages()

    def derive(self, *, checkpoint=None, selected=None):
        collected = {} if selected is None else {"transactions": [
            deepcopy(self.cp["transactions"][signature]) for signature in selected]}
        return derive_history_evidence(self.store, WALLET, WINDOW,
                                       checkpoint=self.cp if checkpoint is None else checkpoint,
                                       collected=collected)


@pytest.fixture
def synthetic_history():
    history = SyntheticHistory()
    try:
        yield history
    finally:
        history.close()


@pytest.mark.parametrize("field,value", [
    ("blockTime", START),
    ("slot", 1101),
    ("err", {"InstructionError": [0, "Custom"]}),
    ("confirmationStatus", "confirmed"),
])
def test_r6_matching_token_receipt_cannot_certify_contradictory_wallet_period(
        synthetic_history, field, value):
    history = synthetic_history
    history.mutate_entry(WALLET, "boundary", **{field: value})
    result = history.derive()
    period = result["paging"]["wallet_address_intervals"]["report_period"]
    assert period["state"] == "UNKNOWN", period
    assert result["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["value"] is None
    observed = result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]
    assert observed["status"] == "known" and observed["value"] == "0.00001"
    delta = result["native_address_metrics"]["observed"]["native_wallet_delta_sol"]
    assert delta["status"] == "known" and delta["value"] == "-0.00001"
    assert result["evidence_gates"]["history"] == "UNKNOWN"
    assert result["metric_decisions"]["profit_sol"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("account", [WALLET, TOKEN_ACCOUNT])
@pytest.mark.parametrize("field,value,canonical", [
    ("blockTime", START, START - 1),
    ("slot", 1101, 1100),
    ("err", {"InstructionError": [0, "Custom"]}, None),
    ("confirmationStatus", "confirmed", "finalized"),
])
def test_account_specific_conflicts_are_explicit_and_correction_recovers_receipts(
        synthetic_history, account, field, value, canonical):
    history = synthetic_history
    history.mutate_entry(account, "boundary", **{field: value})
    result = history.derive()
    assert result["paging"]["intervals"]["report_period"]["state"] == "UNKNOWN"
    conflicts = result["paging"]["conflicts"]
    conflict = next(item for item in conflicts if item["account"] == account
                    and item["signature"] == "boundary" and item["field"] == field)
    assert conflict["page_value"] == value
    assert conflict["canonical_value"] == canonical
    assert conflict["canonical_hash"] == history.cp["transactions"]["boundary"]["evidence_hash"]
    assert history.store.evidence(conflict["page_hash"])["address"] == account
    assert result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"
    history.mutate_entry(account, "boundary", **{field: canonical})
    corrected = history.derive()
    period = corrected["paging"]["wallet_address_intervals"]["report_period"]
    fees = corrected["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]
    assert corrected["paging"]["conflicts"] == []
    assert period["state"] == "PASS" and period["required_transactions"] == 1
    assert fees["status"] == "known" and fees["value"] == "0.000005"
    assert corrected["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"
    assert corrected["metric_decisions"]["profit_sol"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("account", [WALLET, TOKEN_ACCOUNT])
@pytest.mark.parametrize("signature,raw_time,page_time,count,fees", [
    ("boundary", START - 1, START, 1, "0.000005"),
    ("boundary", START, START - 1, 2, "0.00001"),
    ("inside", END - 1, END, 1, "0.000005"),
    ("inside", END, END - 1, 0, "0"),
])
def test_canonical_lower_inclusive_upper_exclusive_membership_after_reconciliation(
        synthetic_history, account, signature, raw_time, page_time, count, fees):
    history = synthetic_history
    history.retime_transaction(signature, raw_time)
    history.mutate_entry(account, signature, blockTime=page_time)
    conflicted = history.derive()
    assert conflicted["paging"]["intervals"]["report_period"]["state"] == "UNKNOWN"
    assert conflicted["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["status"] == "unknown"
    assert conflicted["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"
    history.mutate_entry(account, signature, blockTime=raw_time)
    corrected = history.derive()
    period = corrected["paging"]["wallet_address_intervals"]["report_period"]
    assert period["state"] == "PASS" and period["required_transactions"] == count
    metric = corrected["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]
    assert metric["status"] == "known" and metric["value"] == fees


@pytest.mark.parametrize("account", [WALLET, TOKEN_ACCOUNT])
@pytest.mark.parametrize("signature,field,value", [
    ("at-end", "blockTime", END - 1),
    ("at-end", "slot", 1501),
    ("at-end", "err", {"InstructionError": [0, "Custom"]}),
    ("at-end", "confirmationStatus", "confirmed"),
    ("older-basis", "blockTime", START - 90 * 86400 + 1),
    ("older-basis", "slot", 901),
    ("older-basis", "err", {"InstructionError": [0, "Custom"]}),
    ("older-basis", "confirmationStatus", "confirmed"),
])
def test_rawless_boundary_markers_require_consistent_account_receipts(
        synthetic_history, account, signature, field, value):
    history = synthetic_history
    canonical = next(entry[field] for entry in history.pages[account] if entry["signature"] == signature)
    history.mutate_entry(account, signature, **{field: value})
    result = history.derive()
    interval = "report_period" if signature == "at-end" else "verification_90d"
    assert result["paging"]["intervals"][interval]["state"] == "UNKNOWN"
    assert result["native_address_metrics"]["periods"][interval]["wallet_network_fees_sol"]["status"] == "unknown"
    assert result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"
    history.mutate_entry(account, signature, **{field: canonical})
    corrected = history.derive()
    assert corrected["paging"]["intervals"][interval]["state"] == "PASS"
    assert corrected["native_address_metrics"]["periods"][interval]["wallet_network_fees_sol"]["status"] == "known"


@pytest.mark.parametrize("account", [WALLET, TOKEN_ACCOUNT])
def test_exact_selected_record_set_keeps_its_own_totals_and_validates_other_boundary_receipts(
        synthetic_history, account):
    history = synthetic_history
    history.mutate_entry(account, "boundary", blockTime=START)
    result = history.derive(selected=["inside"])
    assert result["paging"]["intervals"]["report_period"]["state"] == "UNKNOWN"
    observed = result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]
    assert observed["status"] == "known" and observed["value"] == "0.000005"
    assert observed["record_count"] == 1
    assert result["native_address_metrics"]["observed"]["native_wallet_delta_sol"]["value"] == "-0.000005"
    history.mutate_entry(account, "boundary", blockTime=START - 1)
    corrected = history.derive(selected=["inside"])
    assert corrected["paging"]["wallet_address_intervals"]["report_period"]["state"] == "PASS"
    metric = corrected["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]
    assert metric["status"] == "known" and metric["value"] == "0.000005"
    assert corrected["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["record_count"] == 1
    assert corrected["paging"]["intervals"]["verification_90d"]["state"] == "UNKNOWN"


def test_frozen_source_rebuild_cannot_inherit_a_later_corrected_receipt_set(synthetic_history):
    history = synthetic_history
    history.mutate_entry(WALLET, "boundary", blockTime=START)
    original_cp = deepcopy(history.cp)
    original_records = list(deepcopy(history.cp["transactions"]).values())
    collected = {"checkpoint": original_cp, "snapshot": deepcopy(original_cp["snapshot"]),
                 "transactions": original_records, "evidence": deepcopy(original_cp["evidence"]),
                 "coverage": {"status": "partial"}}
    report = {"id": "synthetic-v032-original", "source": "live", "address": WALLET, "window": deepcopy(WINDOW),
              "collection_input_hash": freeze_report_inputs(history.store, WALLET, WINDOW, collected)}
    # A saved parent binds each exact manifest. Later collector receipts must
    # not rewrite either independently frozen synthetic source set.
    history.store.put("reports", report["id"], report)
    original_report = deepcopy(report)
    history.mutate_entry(WALLET, "boundary", blockTime=START - 1)
    corrected_cp = deepcopy(history.cp)
    corrected_collected = {"checkpoint": corrected_cp, "snapshot": deepcopy(corrected_cp["snapshot"]),
                           "transactions": original_records, "evidence": deepcopy(corrected_cp["evidence"]),
                           "coverage": {"status": "partial"}}
    corrected_report = {"id": "synthetic-v032-corrected", "source": "live", "address": WALLET,
                        "window": deepcopy(WINDOW), "collection_input_hash": freeze_report_inputs(
                            history.store, WALLET, WINDOW, corrected_collected)}
    history.store.put("reports", corrected_report["id"], corrected_report)
    # Model a persisted append-only receipt superset after collection resumed.
    known = {(item.get("kind"), item.get("hash"), item.get("signature")) for item in history.cp["evidence"]}
    history.cp["evidence"].extend(item for item in original_cp["evidence"]
                                  if (item.get("kind"), item.get("hash"), item.get("signature")) not in known)
    history.save()
    loaded = load_report_inputs(history.store, report)
    assert loaded["checkpoint"] == original_cp
    frozen = derive_history_evidence(history.store, WALLET, WINDOW,
                                     checkpoint=loaded["checkpoint"], collected=loaded)
    corrected_loaded = load_report_inputs(history.store, corrected_report)
    current = derive_history_evidence(history.store, WALLET, WINDOW,
                                      checkpoint=corrected_loaded["checkpoint"], collected=corrected_loaded)
    assert frozen["paging"]["wallet_address_intervals"]["report_period"]["state"] == "UNKNOWN"
    assert frozen["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"
    assert current["paging"]["wallet_address_intervals"]["report_period"]["state"] == "PASS"
    assert current["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["value"] == "0.000005"
    assert report == original_report and loaded["checkpoint"] == original_cp


def test_disconnected_other_account_page_cannot_supply_the_frozen_upper_boundary(synthetic_history):
    history = synthetic_history
    for account in history.pages:
        history.pages[account] = [entry for entry in history.pages[account] if entry["signature"] != "at-end"]
    history.save_pages()
    history.builder.add_page([history.builder.entry("detached-at-end", END, 1500)],
                             address=TOKEN_ACCOUNT, before="unlinked-cursor")
    history.save()
    result = history.derive()
    assert result["paging"]["wallet_address_intervals"]["report_period"]["state"] == "UNKNOWN"
    assert result["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["status"] == "unknown"
    assert result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"] == "0.00001"


def remap_synthetic(value):
    """Reuse the existing quantity route, without claiming its keys are mainnet data."""
    replacements = {swap_builder.WALLET: WALLET, 'wallet-token': POSITION_ACCOUNT,
                    swap_builder.TOKEN: swap_builder.PUMP}
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [remap_synthetic(item) for item in value]
    if isinstance(value, dict):
        return {key: remap_synthetic(item) for key, item in value.items() if key != 'uiAmount'}
    return value


@pytest.fixture
def synthetic_position(synthetic_history):
    history = synthetic_history
    history.pages[POSITION_ACCOUNT] = history.pages.pop(TOKEN_ACCOUNT)
    history.cp['accounts'].pop(TOKEN_ACCOUNT)
    ownership = history.store.evidence(history.ownership_hash)
    ownership['result']['value'][0]['pubkey'] = POSITION_ACCOUNT
    history.ownership_hash = history.store.archive(ownership)
    for reference in history.cp['evidence']:
        if reference['kind'] == 'owned-accounts':
            reference['hash'] = history.ownership_hash
    for signature, sell, timestamp, slot in [('boundary', False, START + 100, 1100),
                                             ('inside', True, START + 150, 1200)]:
        raw = remap_synthetic(swap_builder.record(sell=sell)['raw'])
        raw['transaction']['signatures'] = [signature]
        raw.update(slot=slot, blockTime=timestamp)
        history.replace_transaction(signature, raw)
    return history


def position_result(history):
    return derive_position_evidence(history.store, WALLET, WINDOW,
                                     checkpoint=history.cp,
                                     collected={'transactions': list(history.cp['transactions'].values())})


def test_scoped_primary_zero_episode_can_be_known_without_financial_price_or_fee_inputs(synthetic_position):
    history = synthetic_position
    assert position_result(history)['counts']['known_closed'] == 1
    for signature in ('boundary', 'inside'):
        raw = history.store.evidence(history.cp['transactions'][signature]['evidence_hash'])
        for key in ('fee', 'preBalances', 'postBalances'):
            raw['meta'].pop(key)
        # Settlement consideration is independent of this non-wSOL account hold.
        raw['meta']['innerInstructions'][0]['instructions'] = [
            instruction for instruction in raw['meta']['innerInstructions'][0]['instructions']
            if instruction['parsed']['info']['mint'] != swap_builder.WSOL]
        history.replace_transaction(signature, raw)
    result = position_result(history)
    assert result['counts']['known_closed'] == 1
    position = result['positions'][0]
    assert position['opening_raw'] == '0' and position['closing_raw'] == '0'
    assert position['hold_hours']['status'] == 'known'
    assert {position['stages'][key]['state'] for key in ('basis', 'fees', 'classification', 'valuation')} == {'UNKNOWN'}
    assert history.derive()['metric_decisions']['profit_sol']['state'] == 'UNKNOWN'


def test_intervening_failed_receipt_advances_canonical_chronology(synthetic_position):
    history = synthetic_position
    history.add_transaction('failed-between', START + 200, 1150)
    failed = history.store.evidence(history.cp['transactions']['failed-between']['evidence_hash'])
    failed['transaction']['message']['accountKeys'] = [WALLET, POSITION_ACCOUNT]
    failed['meta']['err'] = {'InstructionError': [0, 'Custom']}
    for account, entries in history.pages.items():
        entries.append(history.builder.entry('failed-between', START + 200, 1150, failed['meta']['err']))
        entries.sort(key=lambda entry: entry['slot'], reverse=True)
    history.replace_transaction('failed-between', failed)
    result = position_result(history)
    assert result['counts']['known_closed'] == 0
    position = next(position for position in result['positions'] if position['account'] == POSITION_ACCOUNT)
    assert position['stages']['chronology']['state'] == 'UNKNOWN'
    assert position['hold_hours']['value'] is None


@pytest.mark.parametrize('opaque', [
    {'programId': TOKEN_PROGRAM, 'data': '1'},
    {'programId': TOKEN_PROGRAM, 'accounts': None, 'data': '1'},
    {'programId': TOKEN_PROGRAM, 'accounts': 'unresolved-reference-list', 'parsed': {'type': 'opaque', 'info': {}}},
])
def test_unresolved_opaque_reference_sets_cannot_certify_scoped_quantity_history(synthetic_position, opaque):
    history = synthetic_position
    raw = history.store.evidence(history.cp['transactions']['boundary']['evidence_hash'])
    raw['transaction']['message']['instructions'].append(opaque)
    history.replace_transaction('boundary', raw)
    result = position_result(history)
    assert result['counts']['known_closed'] == 0
    assert result['known_account_hold_median_hours']['status'] == 'unknown'


@pytest.mark.parametrize('source', ['buy', 'sell', 'account_page', 'ownership', 'anchor'])
def test_required_source_removal_revokes_hold_without_imported_certificate_shortcuts(synthetic_position, source):
    history = synthetic_position
    original = position_result(history)
    assert original['counts']['known_closed'] == 1
    digest = {
        'buy': history.cp['transactions']['boundary']['evidence_hash'],
        'sell': history.cp['transactions']['inside']['evidence_hash'],
        'account_page': history.cp['accounts'][POSITION_ACCOUNT]['terminal_evidence'],
        'ownership': history.ownership_hash,
        'anchor': history.builder.anchor,
    }[source]
    assert digest in original['positions'][0]['sources']
    assert digest in original['positions'][0]['hold_hours']['evidence']
    (history.store.path / 'evidence' / f'{digest}.json.gz').unlink()
    result = derive_position_evidence(history.store, WALLET, WINDOW,
                                      checkpoint=history.cp,
                                      collected={'transactions': list(history.cp['transactions'].values())},
                                      history_evidence={'all_gates': 'PASS', 'saved_positions': original})
    assert result['counts']['known_closed'] == 0
    assert result['known_account_hold_median_hours']['status'] == 'unknown'
    assert result['known_account_hold_median_hours']['value'] is None
    if source in ('account_page', 'ownership'):
        # Wallet-page raw native arithmetic has independent proof dependencies.
        assert history.derive()['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.00001'


def test_same_slot_order_removal_revokes_hold_but_preserves_additive_native_fees(synthetic_position):
    history = synthetic_position
    raw = history.store.evidence(history.cp['transactions']['inside']['evidence_hash'])
    raw['slot'] = 1100
    raw['blockTime'] = START + 100
    history.replace_transaction('inside', raw)
    block = history.store.archive({'method': 'getBlock', 'slot': 1100,
                                   'result': {'signatures': ['boundary', 'inside']}})
    history.cp['evidence'].append({'kind': 'block-order', 'hash': block})
    history.cp['ordering'] = {'boundary': 0, 'inside': 1}
    history.save()
    assert position_result(history)['counts']['known_closed'] == 1
    (history.store.path / 'evidence' / f'{block}.json.gz').unlink()
    result = position_result(history)
    assert result['counts']['known_closed'] == 0
    position = next(position for position in result['positions'] if position['account'] == POSITION_ACCOUNT)
    assert position['stages']['chronology']['state'] == 'UNKNOWN'
    assert history.derive()['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.00001'


@pytest.mark.parametrize('scope', ['within_transaction', 'between_transactions'])
def test_explicit_token_program_identity_conflicts_cannot_preserve_known_episode(synthetic_position, scope):
    history = synthetic_position
    token_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
    for signature in ('boundary', 'inside'):
        raw = history.store.evidence(history.cp['transactions'][signature]['evidence_hash'])
        index = raw['transaction']['message']['accountKeys'].index(POSITION_ACCOUNT)
        for name in ('preTokenBalances', 'postTokenBalances'):
            row = next(row for row in raw['meta'][name] if row['accountIndex'] == index)
            row['programId'] = TOKEN_PROGRAM
            if scope == 'within_transaction' and signature == 'boundary' and name == 'postTokenBalances':
                row['programId'] = token_2022
            if scope == 'between_transactions' and signature == 'inside':
                row['programId'] = token_2022
        history.replace_transaction(signature, raw)
    result = position_result(history)
    assert result['counts']['known_closed'] == 0
    assert result['known_account_hold_median_hours']['status'] == 'unknown'
