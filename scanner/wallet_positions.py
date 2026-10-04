"""Selected mint-aggregate position admission over the existing FIFO ledger.

The production helper consumes *fresh* internal wallet-evidence receipts, never
an archive's positions or completion flags. It carries observed account states
across selected transactions, including transfers between owned accounts, and
admits open holdings alongside completed episodes. This is an observed account
population: unknown historical accounts and intervening activity remain a
separate requirement. There is no second cost-basis or profit calculator here.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
import hashlib
import re

from .accounting import raw_quantity, utc
from .chronology_evidence import assess_interval_membership
from .investigation import WSOL
from .json_boundary import canonical_bytes

VERSION = 'wallet-position-population-v1'
HASH = re.compile(r'^[a-f0-9]{64}$')
SCOPE = ('Selected wallet-owned token-account population; hidden accounts and '
         'unobserved intervening activity remain unproved')


def _check(known, reason, evidence=(), *, dependencies=(), scope=SCOPE):
    hashes = sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'reason': reason,
            'scope': scope, 'evidence': hashes, 'dependencies': sorted(set(dependencies))}


def _combine(checks, reason, *, dependencies=(), scope=SCOPE):
    checks = list(checks)
    return _check(bool(checks) and all(row.get('state') == 'PASS' for row in checks), reason,
                  (h for row in checks for h in row.get('evidence', [])),
                  dependencies=set(dependencies) | {dependency for row in checks for dependency in row.get('dependencies', [])},
                  scope=scope)


def _clock_check(clocks, signature, evidence):
    clock = clocks.get('transactions', {}).get(signature, {})
    return _check(clock.get('state') == clock.get('time_state') == 'PASS',
                  clock.get('reason', 'Selected chronology is unavailable'),
                  list(evidence) + clock.get('evidence', []), dependencies=['raw_chronology'])


def _placement(clocks, signature):
    clock = clocks.get('transactions', {}).get(signature, {})
    values = [clock.get(field) for field in ('canonical_time', 'slot', 'transaction_index')]
    return tuple(value if type(value) is int else -1 for value in values) + (signature,)


def _ordered(clocks, previous, following):
    a, b = _placement(clocks, previous), _placement(clocks, following)
    return (a[0] >= 0 and b[0] >= 0 and a[1] >= 0 and b[1] >= 0
            and (a[0], a[1]) <= (b[0], b[1])
            and (a[1] != b[1] or 0 <= a[2] < b[2]))


def _owned_quantity(point, wallet, mint):
    if not isinstance(point, dict):
        raise ValueError('An exact selected account endpoint is missing')
    quantity = raw_quantity(point.get('quantity'))
    decimals = point.get('decimals')
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError('The endpoint decimal identity is missing')
    return quantity if point.get('owner') == wallet and point.get('mint') == mint else 0


def project_wallet_positions(*, selected, raw_versions, transactions, clocks,
                             consistency, fifo_positions, ledger_events, wallet,
                             window, cohorts, inspection, lots):
    """Project freshly derived internal receipts without repeating raw walks.

    ``fifo_positions`` must be the existing ``analyze`` output from the current
    raw-decoded ledger. ``lots`` and ``cohorts`` are current typed projections of
    that same ledger. Normal report construction owns this private interface;
    imported/advisory positions and flags never reach it. The public wrapper
    below rechecks bytes and rederives all of these inputs independently.
    """
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('Position population needs a positive report window')
    all_hashes = [row.get('evidence_hash') for versions in raw_versions.values() for row in versions]
    frozen_hashes = {h for h in all_hashes if isinstance(h, str) and HASH.fullmatch(h)}
    ledger_hashes = {h for event in ledger_events for h in event.get('evidence', [])
                     if isinstance(h, str) and HASH.fullmatch(h)}
    source_set = consistency.get('source_set', {})
    inventory = _check(source_set.get('state') == 'PASS' and inspection.get('state') == 'PASS',
        'Every frozen selected/linked source and physical inspection remains represented.',
        all_hashes + source_set.get('evidence', []),
        dependencies=['linked_native_source_inventory', 'complete_physical_inspection'])
    lot_by_id = {lot['id']: lot for lot in lots}
    account_rows = defaultdict(list)
    mint_accounts = defaultdict(set)
    for signature, observed in transactions.items():
        membership = assess_interval_membership(clocks, signature, utc(0), end)
        if membership['state'] == 'PASS' and membership.get('member') is False:
            continue
        for account, pair in observed.get('boundaries', {}).items():
            account_rows[account].append((signature, pair))
            for phase in ('pre', 'post'):
                point = pair.get(phase)
                if isinstance(point, dict) and point.get('owner') == wallet and point.get('mint') != WSOL:
                    mint_accounts[point['mint']].add(account)
    fifo_by_mint = defaultdict(list)
    for position in fifo_positions:
        if position['mint'] != WSOL:
            fifo_by_mint[position['mint']].append(position)
    result = {'version': VERSION, 'scope': SCOPE, 'at': end.isoformat(),
        'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN',
        'valuation_state': 'UNKNOWN', 'qualification': False, 'mints': {},
        'intervals': {}, 'evidence': sorted(frozen_hashes),
        'provider_requests': 0, 'credential_lookups': 0}
    for mint in sorted(set(mint_accounts) | set(fifo_by_mint)):
        checks, endpoints, decimals, opening, closing = [], [], set(), 0, 0
        required_signatures, excluded_signatures = set(), set()
        for account in sorted(mint_accounts[mint]):
            ordered = sorted(account_rows[account], key=lambda row: _placement(clocks, row[0]))
            relevant = []
            for signature, pair in ordered:
                membership = assess_interval_membership(clocks, signature, utc(0), end)
                if membership['state'] == 'PASS' and membership.get('member') is False:
                    excluded_signatures.add(signature)
                    continue
                required_signatures.add(signature)
                observed = transactions[signature]
                physical = [pair.get('checks', {}).get(key, {}) for key in ('quantities', 'ownership', 'lifecycle')]
                identity = observed.get('checks', {}).get('identity', {})
                bound = (signature in selected and bool(raw_versions.get(signature))
                         and set(observed.get('evidence', [])) <= frozen_hashes
                         and bool(observed.get('evidence')))
                checks += physical + [identity, _clock_check(clocks, signature, observed.get('evidence', [])),
                    _check(bound and membership['state'] == 'PASS',
                        'Account endpoints bind frozen selected/alternative sources before the exact report end.',
                        observed.get('evidence', []) + membership['evidence'],
                        dependencies=['frozen_account_endpoints', 'report_end_membership'])]
                relevant.append((signature, pair))
            if not relevant:
                continue
            for (before_signature, before), (after_signature, after) in zip(relevant, relevant[1:]):
                a, b = before.get('post'), after.get('pre')
                matching = (isinstance(a, dict) and isinstance(b, dict)
                    and all(a.get(key) == b.get(key) for key in ('quantity', 'owner', 'mint', 'decimals')))
                checks.append(_check(matching and _ordered(clocks, before_signature, after_signature),
                    'Consecutive selected observations carry one exact account state in evidenced order.',
                    transactions[before_signature].get('evidence', []) + transactions[after_signature].get('evidence', []),
                    dependencies=['selected_account_continuity']))
            first_signature, first = relevant[0]
            last_signature, last = relevant[-1]
            try:
                begin, finish = first['pre'], last['post']
                before_quantity = _owned_quantity(begin, wallet, mint)
                after_quantity = _owned_quantity(finish, wallet, mint)
                for _, pair in relevant:
                    for phase in ('pre', 'post'):
                        point = pair.get(phase)
                        if point and point.get('mint') == mint:
                            decimals.add(point.get('decimals'))
                opening += before_quantity
                closing += after_quantity
                endpoints.append({'account': account, 'opening_raw': str(before_quantity),
                    'remaining_raw': str(after_quantity), 'first_signature': first_signature,
                    'last_signature': last_signature,
                    'evidence': sorted({h for signature, _ in relevant for h in transactions[signature].get('evidence', [])})})
            except (ValueError, TypeError, KeyError):
                checks.append(_check(False, 'One required account endpoint or quantity is malformed.', all_hashes))
        # An unavailable unassigned/selected record cannot silently disappear
        # from an observed population. It may contain another account or episode.
        for signature, versions in raw_versions.items():
            if signature in required_signatures or signature in excluded_signatures:
                continue
            membership = assess_interval_membership(clocks, signature, utc(0), end)
            if membership['state'] == 'PASS' and membership.get('member') is False:
                continue
            observed = transactions.get(signature)
            linked = consistency.get('transactions', {}).get(signature, {})
            identity = linked.get('identity', {})
            format_check = linked.get('native', {}).get('checks', {}).get('transaction_format', {})
            unavailable = (any(not isinstance(row.get('raw'), dict) for row in versions)
                or identity.get('state') != 'PASS' or format_check.get('state') != 'PASS'
                or observed is not None and bool(observed.get('gaps')))
            if unavailable:
                checks.append(_check(False, 'A frozen unavailable, identity-invalid or unsupported source cannot be excluded from this selected account population.',
                    (row.get('evidence_hash') for row in versions), dependencies=['source_affinity']))
        endpoints_check = _combine([inventory] + checks + [_check(bool(endpoints) and len(decimals) == 1,
            'Observed mint identity and every account endpoint have exact integer units.', all_hashes)],
            'Exact selected account quantities are independent of purchase costs, fees and valuations.',
            dependencies=['selected_owned_account_endpoints', 'selected_account_continuity'])
        positions = fifo_by_mint[mint]
        fifo_remaining = sum(raw_quantity(position['quantity_raw']) for position in positions)
        origins = [_check(lot_by_id.get(position['id'], {}).get('origin_state') == 'PASS',
            'The FIFO episode starts from a supported raw zero boundary and observed acquisition quantities.',
            position.get('evidence', []), dependencies=['observed_fifo_origin']) for position in positions]
        reconciliation = _combine([endpoints_check] + origins + [_check(bool(positions) and opening == 0
            and closing == fifo_remaining and all(position['status'] != 'interrupted' for position in positions),
            'Existing FIFO remaining units equal carried mint aggregate endpoints; open episodes are admitted.',
            all_hashes, dependencies=['existing_fifo_quantity_reconciliation']),
            _check(all(bool(position.get('evidence')) and set(position['evidence']) <= ledger_hashes & frozen_hashes
                       for position in positions),
                'FIFO episodes bind the current raw-decoded ledger and its frozen source hashes.', all_hashes,
                dependencies=['current_fifo_source_binding'])],
            'Observed episode population supports closed and open holdings together without certifying historical wallet scope.')
        rendered = []
        for position in positions:
            lot = lot_by_id.get(position['id'], {})
            physical = _check(lot.get('quantity_state') == lot.get('origin_state') == lot.get('chronology_state') == 'PASS',
                'This episode retains its own physical, origin and chronology dependencies.', lot.get('evidence', position.get('evidence', [])))
            is_closed = position.get('end') is not None and position['quantity_raw'] == '0' and position['status'] != 'interrupted'
            is_open = position.get('end') is None and raw_quantity(position['quantity_raw']) > 0 and position['status'] != 'interrupted'
            rendered.append({'id': position['id'], 'mint': mint, 'start': position['start'], 'end': position['end'],
                'observed_closed': is_closed, 'observed_open': is_open, 'quantity_state': physical['state'],
                'remaining_raw': position['quantity_raw'] if physical['state'] == 'PASS' else None,
                'monetary_state': lot.get('monetary_state', 'UNKNOWN'),
                'conditional_profit_sol': lot.get('conditional_lot_profit_sol') if lot.get('monetary_state') == 'PASS' else None,
                'remaining_cost_basis_state': lot.get('remaining_cost_basis_state', 'UNKNOWN'),
                'conditional_remaining_basis_sol': lot.get('conditional_remaining_basis_sol') if lot.get('remaining_cost_basis_state') == 'PASS' else None,
                'timing_state': lot.get('timing_state', 'UNKNOWN'),
                'conditional_hold_hours': lot.get('conditional_hold_hours') if lot.get('timing_state') == 'PASS' else None,
                'checks': {'physical': physical}, 'evidence': physical['evidence']})
        result['mints'][mint] = {'accounts': endpoints, 'decimals': next(iter(decimals)) if len(decimals) == 1 else None,
            'quantity_state': endpoints_check['state'], 'position_state': reconciliation['state'],
            'selected_opening_raw': str(opening) if endpoints_check['state'] == 'PASS' else None,
            'selected_remaining_raw': str(closing) if endpoints_check['state'] == 'PASS' else None,
            'fifo_remaining_raw': str(fifo_remaining), 'episodes': rendered,
            'candidate_closed_count': sum(row['observed_closed'] for row in rendered),
            'candidate_open_count': sum(row['observed_open'] for row in rendered),
            'required_signatures': sorted(required_signatures),
            'checks': {'quantity': endpoints_check, 'population': reconciliation},
            'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN', 'qualification': False}
    selected_activity = cohorts.get('open_stock', {}).get('checks', {}).get('quantity', {})
    # The existing stock census inspects *all* selected activity before end,
    # including activity that might conceal an otherwise unobserved mint. Its
    # quantity/origin proof has no monetary or valuation dependency.
    observed = _combine([inventory, selected_activity] + [row['checks']['population'] for row in result['mints'].values()],
        'Observed mint-aggregate admission retains closed and open FIFO episodes; full historical population remains separate.',
        dependencies=['observed_mint_aggregate_endpoints', 'observed_fifo_episodes'])
    if not result['mints']:
        observed = _check(False, 'No supported observed asset episode population is present.', all_hashes)
    result['checks'] = {'inventory': inventory, 'selected_activity': deepcopy(selected_activity),
        'observed_population': observed,
        'historical_population': _check(False, 'Selected endpoints do not prove hidden or formerly owned historical accounts.',
            all_hashes, dependencies=['accepted_historical_owner_population'], scope='Wallet-wide historical owner population')}
    # Each interval consumes the existing per-metric cohort proof. Open stock
    # is never added as a requirement of completed-cohort timing or realised P&L.
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        current = cohorts.get('intervals', {}).get(name, {})
        exact = current.get('start') == begin.isoformat() and current.get('end') == end.isoformat()
        closed = deepcopy(current.get('closed_cohort', {})) if exact else {}
        if not closed:
            unknown = _check(False, 'The current independently scoped closed-cohort receipt is missing.', all_hashes)
            closed = {'population_state': 'UNKNOWN', 'monetary_state': 'UNKNOWN', 'timing_state': 'UNKNOWN',
                      'checks': {'population': unknown, 'monetary': unknown, 'timing': unknown}}
        result['intervals'][name] = {'start': begin.isoformat(), 'end': end.isoformat(), 'closed_cohort': closed,
            'wallet_population_state': 'UNKNOWN', 'qualification': False}
    return result


def _verified_records(records, raw_sources):
    """Verify a raw body or reproduce its exact frozen indexed pointer hash."""
    from .wallet_evidence import _resolved_sources, _indexed_native_rows
    from .indexed_input import RECORD_VERSION
    preimages = {}
    for source in _resolved_sources(raw_sources, ()):
        if source.get('payload') is None:
            continue
        raws, _, _, indexed = _indexed_native_rows(source['payload'])
        if not indexed:
            continue
        for ordinal, raw in enumerate(raws):
            try:
                signature = raw['transaction']['signatures'][0]
                native_hash = hashlib.sha256(canonical_bytes(raw, string_keys=True)).hexdigest()
                pointer = {'version': RECORD_VERSION, 'source_hash': source['hash'], 'ordinal': ordinal,
                           'signature': signature, 'native_hash': native_hash}
                pointer_hash = hashlib.sha256(canonical_bytes(pointer, string_keys=True)).hexdigest()
                for digest in (native_hash, source['hash'], pointer_hash):
                    key = signature, digest
                    if key in preimages and preimages[key] != raw:
                        preimages[key] = None
                    else:
                        preimages.setdefault(key, raw)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
    result = []
    for original in records:
        row = dict(original) if isinstance(original, dict) else {'signature': None, 'evidence_hash': None, 'raw': None}
        try:
            raw, digest = row.get('raw'), row.get('evidence_hash')
            transaction = raw.get('transaction') if isinstance(raw, dict) else None
            signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
            identity_bound = (isinstance(signatures, list) and bool(signatures)
                              and signatures[0] == row.get('signature'))
            direct = isinstance(raw, dict) and hashlib.sha256(canonical_bytes(raw, string_keys=True)).hexdigest() == digest
            recovered = preimages.get((row.get('signature'), digest))
            if not identity_bound or not direct and (recovered is None or recovered != raw):
                row['raw'] = None
        except (ValueError, TypeError, KeyError):
            row['raw'] = None
        result.append(row)
    return result


def derive_wallet_positions(records, *, all_records, wallet, window, raw_sources=(), source_receipts=(),
                            positions=None, events=(), history_evidence=None, source_consistency=None, chronology=None):
    """Public raw-evidence wrapper; supplied calculations/flags are ignored."""
    from .wallet_evidence import derive_wallet_evidence
    records, all_records = list(records), list(all_records)
    raw_sources, source_receipts = list(raw_sources), list(source_receipts)
    sources = raw_sources + source_receipts
    selected_records = _verified_records(records, sources)
    linked = _verified_records(all_records, sources)
    evidence = derive_wallet_evidence(selected_records, all_records=linked, wallet=wallet, window=window,
        raw_sources=raw_sources, source_receipts=source_receipts, source_consistency={}, chronology={})
    return evidence['query_accounting']['position_population']
