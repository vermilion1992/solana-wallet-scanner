"""Distinct review control for ordinary native fee projection; unsigned dev edit."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from scanner.accounting import canonical, utc
from scanner.report_rebuild import freeze_report_inputs
from tests.test_report_rebuild import seed_report
from tests.test_indexed_report_integration import rebuild
from tests.test_discovery_integration_review import session, isolate_credentials_and_transport


def test_outside_window_unresolved_fee_does_not_erase_proved_current_fees(session):
    client, app, _ = session
    store = app.state.store
    parent, collected = seed_report(store)
    inside = deepcopy(collected['transactions'][0])
    outside = deepcopy(inside)
    signature = 'development-older-fee-missing'
    outside['signature'] = signature
    outside['raw']['transaction']['signatures'][0] = signature
    outside['raw']['slot'] -= 1000
    outside['raw']['blockTime'] = int((utc(parent['window']['start'])-timedelta(days=1)).timestamp())
    outside['raw']['meta']['fee'] = None
    outside['evidence_hash'] = store.archive(outside['raw'])
    collected['transactions'].append(outside)
    ref = {'kind':'transaction', 'signature':signature, 'hash':outside['evidence_hash']}
    collected['evidence'].append(ref)
    collected['checkpoint']['transactions'][signature] = {'signature':signature,'evidence_hash':outside['evidence_hash']}
    collected['checkpoint']['evidence'].append(ref)
    parent['collection_input_hash'] = freeze_report_inputs(store,parent['address'],parent['window'],collected)
    store.put('reports',parent['id'],parent)
    child = rebuild(client,parent)
    current = child['research']['wallet_fees_paid_sol']
    assert current is not None, child['research']
    metric = child['metrics']['observed_network_fees_sol']
    assert metric['status'] == 'known', {'expected_from_current_raw_projection':current,'actual':metric}
    assert metric['value'] == current
