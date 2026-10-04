"""Typed indexed placement/order conformance; no historical-population proof."""
from copy import deepcopy
import gzip
import hashlib
import json

import pytest

from scanner.accounting import utc
from scanner.archive_input import canonical_bytes
from scanner.chronology_evidence import assess_chronology, assess_interval_membership, reconcile_placements
from scanner.indexed_input import convert_indexed_archive, validate_page_envelope
from test_indexed_input import WALLET, WINDOW, PROBE, native, page, sources, unpack, upload


AT = 1783175556
START, END = utc(AT-1), utc(AT+10)


def typed(records, *, ident=1, options=None, outgoing=None):
    manifest, payloads = unpack(convert_indexed_archive(upload([page(records, ident=ident, options=options, outgoing=outgoing)])[2]))
    return sources(manifest, payloads)[0]


def records(raws, indexed=None):
    return [{'signature': raw['transaction']['signatures'][0], 'raw': deepcopy(raw),
             'evidence_hash': hashlib.sha256(canonical_bytes(raw)).hexdigest(),
             **({'indexed_source_hash': indexed['hash']} if indexed else {})} for raw in raws]


def block(signatures, *, slot=100, timestamp=AT):
    payload = {'method': 'getBlock', 'slot': slot, 'result': {'signatures': signatures, 'blockTime': timestamp}}
    return {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}


def same_slot():
    return [native('opening', slot=100, index=3), native('closing', slot=100, index=8)]


def test_typed_exact_page_proves_selected_same_slot_indices_without_fabricating_a_full_block():
    raws = same_slot(); source = typed(raws); rows = records(raws, source)
    before = deepcopy((rows, source))
    unsupported = assess_chronology(rows)
    assert unsupported['transactions']['opening']['order_state'] == 'UNKNOWN'
    result = assess_chronology(rows, indexed_receipts=[source])
    assert result['version'] == 'slot-chronology-evidence-v3' and result['state'] == 'PASS'
    assert {s: r['transaction_index'] for s, r in result['transactions'].items()} == {'opening': 3, 'closing': 8}
    placement = result['placements']['opening']
    assert placement['indices_by_slot']['100'] == {'bounded': True, 'min': 3, 'max': 3, 'possible_indices': [3]}
    assert any(f['kind'] == 'indexed-page' and f['raw_path'] == 'result.data.0' for f in placement['facts'])
    assert all(f['kind'] != 'block-order' for f in placement['facts'])
    assert (rows, source) == before


def test_standalone_transaction_index_and_caller_page_pass_flags_supply_no_order_proof():
    raws = same_slot(); rows = records(raws)
    result = assess_chronology(rows)
    assert result['transactions']['opening']['transaction_index'] is None
    fake = {'hash': 'a'*64, 'payload': {'state': 'PASS', 'signature': 'opening', 'slot': 100, 'transactionIndex': 3}}
    assert assess_chronology(rows, indexed_receipts=[fake])['transactions']['opening']['order_state'] == 'UNKNOWN'


def test_real_full_block_order_cross_checks_indexed_indices_without_expanding_population():
    raws = same_slot(); source = typed(raws)
    signature_list = [f'unrelated-{i}' for i in range(9)]
    signature_list[3], signature_list[8] = 'opening', 'closing'
    result = assess_chronology(records(raws, source), indexed_receipts=[source], block_receipts=[block(signature_list)])
    assert result['state'] == 'PASS' and set(result['transactions']) == {'opening', 'closing'}
    assert result['transactions']['closing']['transaction_index'] == 8


def test_conflicting_real_block_order_revokes_order_but_keeps_independent_fee_window_membership():
    raws = same_slot(); source = typed(raws)
    result = assess_chronology(records(raws, source), indexed_receipts=[source], block_receipts=[block(['opening', 'closing'])])
    assert result['transactions']['opening']['order_state'] == 'UNKNOWN'
    assert result['transactions']['opening']['transaction_index'] is None
    assert result['transactions']['opening']['time_state'] == 'PASS'
    assert assess_interval_membership(result, 'opening', START, END)['member'] is True


def test_every_alternative_index_survives_permutation_and_retains_finite_conflict_envelope():
    raws = same_slot(); first = typed(raws)
    alternate_raws = deepcopy(raws); alternate_raws[1]['transactionIndex'] = 9
    second = typed(alternate_raws, ident=2)
    for indexed in ([first, second], [second, first], [first, first, second]):
        result = assess_chronology(records(raws, first), indexed_receipts=indexed)
        row = result['transactions']['closing']
        assert row['order_state'] == 'UNKNOWN' and row['time_state'] == 'PASS'
        assert row['placement']['indices_by_slot']['100']['possible_indices'] == [8, 9]
        assert row['placement']['indices_by_slot']['100']['bounded'] is True
        assert assess_interval_membership(result, 'closing', START, END)['member'] is True


@pytest.mark.parametrize('alternative_time,known,member', [(AT+1, True, True), (AT+10, False, None), (AT+20, False, None)])
def test_half_open_fee_membership_uses_all_linked_indexed_clock_possibilities(alternative_time, known, member):
    raw = native('selected', slot=100)
    primary = typed([raw])
    alternative = typed([dict(raw, blockTime=alternative_time)], ident=2)
    result = assess_chronology(records([raw], primary), indexed_receipts=[primary, alternative])
    assert result['transactions']['selected']['time_state'] == 'UNKNOWN'
    membership = assess_interval_membership(result, 'selected', START, END)
    assert membership['state'] == ('PASS' if known else 'UNKNOWN') and membership['member'] is member


@pytest.mark.parametrize('bad_time', [None, True, '1783175556', 10**30])
def test_missing_or_malformed_indexed_clock_never_preserves_window_certainty(bad_time):
    raw = native('selected', slot=100)
    source = typed([dict(raw, blockTime=bad_time)])
    result = assess_chronology(records([raw], source), indexed_receipts=[source])
    assert result['transactions']['selected']['time_state'] == 'UNKNOWN'
    assert assess_interval_membership(result, 'selected', START, END)['state'] == 'UNKNOWN'


@pytest.mark.parametrize('loss', ['missing', 'corrupt', 'wrong-hash'])
def test_required_page_loss_does_not_strengthen_clock_and_exact_restore_recovers(loss):
    raws = same_slot(); original = typed(raws); rows = records(raws, original)
    good = assess_chronology(rows, indexed_receipts=[original])
    changed = deepcopy(original)
    if loss == 'missing': changed['payload'] = None
    if loss == 'corrupt': changed['payload']['response_base64'] = 'corrupt'
    if loss == 'wrong-hash': changed['payload']['response_hash'] = 'a'*64
    missing = assess_chronology(rows, indexed_receipts=[changed])
    assert missing['transactions']['opening']['state'] == 'UNKNOWN'
    assert missing['placements']['opening']['unbounded'] is True
    assert assess_interval_membership(missing, 'opening', START, END)['state'] == 'UNKNOWN'
    assert assess_chronology(rows, indexed_receipts=[original]) == good


def test_missing_page_association_is_negative_scope_and_does_not_erase_an_independent_slot():
    selected = native('selected', slot=100)
    unrelated = native('unrelated', slot=200)
    first, second = typed([selected]), typed([unrelated])
    rows = records([selected], first) + records([unrelated], second)
    result = assess_chronology(rows, indexed_receipts=[first, {'hash': second['hash'], 'payload': None}])
    assert result['transactions']['selected']['state'] == 'PASS'
    assert result['transactions']['unrelated']['state'] == 'UNKNOWN'
    assert assess_interval_membership(result, 'selected', START, END)['member'] is True


@pytest.mark.parametrize('variant', ['bad-named-record', 'unassignable-disjoint'])
def test_readable_disjoint_malformed_sibling_keeps_selected_index_and_fee_clock(variant):
    good = native('selected', slot=100)
    bad = native('unrelated', slot=200)
    if variant == 'bad-named-record': bad['meta'] = []
    else: bad['transaction']['signatures'] = []
    source = typed([good, bad])
    assert validate_page_envelope(source['payload'])['state'] == 'UNKNOWN'
    result = assess_chronology(records([good], source), indexed_receipts=[source])
    row = result['transactions']['selected']
    assert result['state'] == 'UNKNOWN'  # Bad source remains in global audit.
    assert row['state'] == 'PASS' and row['transaction_index'] == 0
    assert assess_interval_membership(result, 'selected', START, END)['member'] is True


def test_unassignable_same_slot_dependency_cannot_be_called_disjoint_or_order_complete():
    good = native('selected', slot=100)
    bad = native('unrelated', slot=100, index=1); bad['transaction']['signatures'] = []
    source = typed([good, bad])
    result = assess_chronology(records([good], source), indexed_receipts=[source])
    assert result['transactions']['selected']['order_state'] == 'UNKNOWN'
    assert any(f['raw_path'] == 'result.data.1' for f in result['placements']['selected']['facts'] if f['kind'] == 'indexed-page')


def test_bad_cursor_metadata_cannot_prove_order_but_does_not_change_independently_bound_native_time():
    raws = same_slot(); source = typed(raws, outgoing='100:0')
    # Change to a malformed cursor while preserving exact new source hashes.
    payload = deepcopy(source['payload'])
    import base64
    response = json.loads(base64.b64decode(payload['response_base64']))
    response['result']['paginationToken'] = []
    encoded = json.dumps(response).encode()
    payload['response_base64'] = base64.b64encode(encoded).decode()
    payload['response_hash'] = hashlib.sha256(encoded).hexdigest()
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}
    result = assess_chronology(records(raws, source), indexed_receipts=[source])
    assert result['transactions']['opening']['order_state'] == 'UNKNOWN'
    assert result['transactions']['opening']['time_state'] == 'PASS'
    assert assess_interval_membership(result, 'opening', START, END)['member'] is True


def test_same_slot_collision_between_separate_valid_indexed_sources_is_a_conflict():
    first_raw, second_raw = native('first', slot=100, index=3), native('second', slot=100, index=3)
    first, second = typed([first_raw]), typed([second_raw], ident=2)
    result = assess_chronology(records([first_raw], first)+records([second_raw], second), indexed_receipts=[first, second])
    assert result['transactions']['first']['order_state'] == 'UNKNOWN'
    assert any('same saved index' in c['reason'] for c in result['conflicts'])


def test_indexed_source_budget_overflow_accepts_no_arbitrary_prefix():
    raws = same_slot(); source = typed(raws)
    result = assess_chronology(records(raws, source), indexed_receipts=[source]*257)
    assert result['transactions']['opening']['state'] == 'UNKNOWN'
    assert result['indexed_sources'][0]['reason'] == 'Indexed source inspection budget exceeded'


def test_genuine_sample_native_indices_reach_shared_chronology_without_claiming_history_population():
    pages = [(PROBE.joinpath(name+'-request.json').read_bytes(), gzip.decompress(PROBE.joinpath(name+'-response.raw.gz').read_bytes()))
             for name in ('02-all-index', '03-all-continuation')]
    manifest, payloads = unpack(convert_indexed_archive(upload(pages)[2]))
    indexed = sources(manifest, payloads)
    rows = []
    for source in indexed:
        rows.extend(records(validate_page_envelope(source['payload'])['records'], source))
    result = assess_chronology(rows, indexed_receipts=indexed)
    assert result['state'] == 'PASS' and len(result['transactions']) == 200
    assert all(row['transaction_index'] is not None for row in result['transactions'].values())
    assert all(row['transaction_index'] == native_row['raw']['transactionIndex'] for native_row in rows
               for row in [result['transactions'][native_row['signature']]])
    assert all(assess_interval_membership(result, row['signature'], utc(WINDOW['start']), utc(WINDOW['end']))['member'] is True for row in rows)
    assert 'historical_population' not in result


def test_indexed_timestamp_outside_supported_utc_range_is_not_a_known_canonical_clock():
    raw = native('selected', slot=100, when=10**30)
    source = typed([raw], options={'filters': {'status': 'any', 'tokenAccounts': 'all'}})
    result = assess_chronology(records([raw], source), indexed_receipts=[source])
    assert result['transactions']['selected']['time_state'] == 'UNKNOWN'
    assert result['transactions']['selected']['canonical_time'] is None
    assert assess_interval_membership(result, 'selected', START, END)['state'] == 'UNKNOWN'


def test_oversized_signature_is_unassignable_and_cannot_prove_same_slot_disjointness():
    good, bad = native('selected', slot=100), native('x'*129, slot=100, index=1)
    source = typed([good, bad])
    result = assess_chronology(records([good], source), indexed_receipts=[source])
    assert result['transactions']['selected']['order_state'] == 'UNKNOWN'
    assert result['indexed_sources'][0]['unassignable_record_count'] == 1


def test_native_record_budget_overflow_does_not_certify_previously_inspected_prefix(monkeypatch):
    import scanner.indexed_input as indexed
    raws = same_slot(); source = typed(raws)
    monkeypatch.setattr(indexed, 'MAX_LINKS', 1)
    result = assess_chronology(records(raws, source), indexed_receipts=[source])
    assert result['transactions']['opening']['state'] == 'UNKNOWN'
    assert result['indexed_sources'][0]['reason'] == 'Indexed native record inspection budget exceeded'
