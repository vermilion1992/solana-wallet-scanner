"""Raw settlement observations for the ordinary economic evidence path.

An observed transaction phase is neither a report-boundary inventory nor equity.
Native SOL and the legacy wrapped-SOL mint have a protocol denomination in SOL;
other assets need an accepted historical mark. Account rent/reserve lamports are
kept separately and never added to token units or presumed refundable equity.
This adapter reads fresh shared evidence checks, never imported valuation flags.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
import re

from .accounting import canonical, raw_quantity, utc
from .investigation import _keys, WSOL
from .providers import TOKEN_PROGRAM
from .transaction_format import supported_transaction_format

VERSION = 'economic-raw-observations-v3'
MAX_RECORDS = 40_000
MAX_ACCOUNT_PHASES = 200_000
_HASH = re.compile(r'^[a-f0-9]{64}$')
_U64 = 2**64 - 1
_LAMPORTS = Decimal(10**9)
_SCOPE = 'Selected original transaction phases; no complete inventory, equity or external-flow population claim'


def _refs(*rows):
    return sorted({digest for row in rows if isinstance(row, dict)
        for digest in (row.get('evidence') if isinstance(row.get('evidence'), list) else [])
        if isinstance(digest, str) and _HASH.fullmatch(digest)})


def _check(known, reason, evidence=(), *, dependencies=(), scope=_SCOPE, **fields):
    hashes = sorted({h for h in evidence if isinstance(h, str) and _HASH.fullmatch(h)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'reason': reason,
            'evidence': hashes, 'scope': scope, 'dependencies': list(dependencies), **fields}


def _usable(row):
    return (isinstance(row, dict) and row.get('state') == 'PASS'
        and isinstance(row.get('evidence'), list) and bool(row['evidence'])
        and all(isinstance(h, str) and _HASH.fullmatch(h) for h in row['evidence']))


def _combine(rows, reason, *, dependencies=(), interval=None):
    rows = list(rows)
    gaps = [row.get('reason') if isinstance(row, dict) else 'A required derived dependency is unavailable'
            for row in rows if not _usable(row)]
    return _check(bool(rows) and not gaps, reason if not gaps else '; '.join(
        sorted({gap for gap in gaps if isinstance(gap, str) and gap})) or reason,
        _refs(*rows), dependencies=dependencies,
        scope='Internally derived genuine economic dependencies; numerical inputs remain separately required',
        **({'interval': interval} if interval else {}))


def _scoped(components, key, interval):
    if key + '_by_interval' in components:
        values = components[key + '_by_interval']
        return values.get(interval) if isinstance(values, dict) else None
    return components.get(key)


def _native_phase(raw, wallet):
    if not isinstance(raw, dict) or not supported_transaction_format(raw):
        raise ValueError('Native phase has no supported original transaction format')
    tx, meta = raw.get('transaction'), raw.get('meta')
    message = tx.get('message') if isinstance(tx, dict) else None
    if not isinstance(message, dict) or not isinstance(meta, dict):
        raise ValueError('Native phase lacks its original message or metadata')
    keys = _keys(message, meta)
    before, after = meta.get('preBalances'), meta.get('postBalances')
    if (not keys or len(set(keys)) != len(keys) or not isinstance(before, list)
            or not isinstance(after, list) or len(before) != len(after) or len(before) != len(keys)
            or any(type(v) is not int or not 0 <= v <= _U64 for v in before + after)):
        raise ValueError('Native phase requires exact unique keys and complete u64 balance arrays')
    if wallet not in keys:
        return {'present': False, 'pre': None, 'post': None, 'raw_paths': ['transaction.message.accountKeys']}
    index = keys.index(wallet)
    return {'present': True, 'pre': str(before[index]), 'post': str(after[index]),
        'raw_paths': [f'meta.preBalances.{index}', f'meta.postBalances.{index}']}


def _native_observation(signature, variants, consistency, wallet):
    hashes = [r.get('evidence_hash') for r in variants]
    group = consistency.get('transactions', {}).get(signature, {})
    checks = group.get('native', {}).get('checks', {})
    required = [group.get('identity'), checks.get('transaction_format'), checks.get('source_set'),
                checks.get('wallet_pre'), checks.get('wallet_post')]
    observations, gaps = [], []
    for row in variants:
        try:
            observations.append(_native_phase(row.get('raw'), wallet))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            gaps.append(str(exc))
    phase_values = lambda r: (r['present'], r['pre'], r['post'])
    agrees = bool(observations) and not gaps and all(phase_values(r) == phase_values(observations[0]) for r in observations)
    known = agrees and all(_usable(row) for row in required)
    check = _check(known, 'Every linked original supports the same native-address phase balances; fees and token marks are independent.'
        if known else '; '.join(sorted(set(gaps))) or 'A linked native phase, identity, format or absolute balance disagrees or is unavailable.',
        hashes + _refs(*required), dependencies=['linked_native_phase_identity', 'linked_native_absolute_balances'])
    value = {**observations[0], 'raw_paths': sorted({p for row in observations for p in row['raw_paths']})} if known else {
        'present': None, 'pre': None, 'post': None, 'raw_paths': []}
    return {'signature': signature, 'check': check, **value,
        'pre_sol': canonical(Decimal(value['pre']) / _LAMPORTS) if value['pre'] is not None else None,
        'post_sol': canonical(Decimal(value['post']) / _LAMPORTS) if value['post'] is not None else None}


def _token_observations(transactions, wallet, reserve_marks=None, clocks=None):
    reserve_marks, clocks = reserve_marks or {}, clocks or {}
    mark_index = defaultdict(list)
    for index, row in enumerate(reserve_marks.get('marks', [])):
        mark_index[row['signature'], row['phase'], row['mint']].append((index, row))
    phases, marks = {}, []
    if sum(2 * len(row.get('boundaries', {})) for row in transactions.values()) > MAX_ACCOUNT_PHASES:
        return {}, [], True
    for signature, transaction in sorted(transactions.items()):
        output = {'pre': [], 'post': []}
        for account, pair in sorted(transaction.get('boundaries', {}).items()):
            checks = pair.get('checks', {})
            required = [checks.get(k) for k in ('ownership', 'quantities', 'lifecycle')]
            for phase in ('pre', 'post'):
                point = pair.get(phase)
                if not isinstance(point, dict) or point.get('owner') != wallet:
                    continue
                quantity, value, mark, known, gap = None, None, None, False, None
                price_refs, price_indexes, ratio, valuation_method = [], [], None, None
                try:
                    quantity = raw_quantity(point.get('quantity'))
                    if quantity > _U64 or not all(_usable(row) for row in required):
                        raise ValueError('Linked token ownership/absolute units/lifecycle are unresolved')
                    if point.get('mint') == WSOL:
                        if pair.get('program') != TOKEN_PROGRAM or type(point.get('decimals')) is not int or point['decimals'] != 9:
                            raise ValueError('Wrapped SOL denomination needs the exact legacy native mint and nine decimals')
                        mark, value, known = '1', canonical(Decimal(quantity) / _LAMPORTS), True
                    elif quantity == 0:
                        value, known = '0', True
                    else:
                        price_refs = [reserve_marks.get('records', {}).get(signature, {})]
                        candidates = mark_index.get((signature, phase, point.get('mint')), [])
                        clock = clocks.get('transactions', {}).get(signature, {})
                        valid = [(index, row) for index, row in candidates if _usable(row.get('check'))
                            and row.get('base_decimals') == point.get('decimals')
                            and row.get('base_program') == pair.get('program')
                            and row.get('slot') == clock.get('slot')
                            and row.get('block_time') == clock.get('canonical_time')
                            and clock.get('state') == clock.get('time_state') == 'PASS']
                        ratios = [(int(row['price_ratio_numerator']), int(row['price_ratio_denominator']))
                                  for _, row in valid]
                        if valid and len(valid) == len(candidates) and all(
                            numerator * ratios[0][1] == ratios[0][0] * denominator
                            for numerator, denominator in ratios):
                            numerator, denominator = ratios[0]
                            mark = valid[0][1]['mark_sol_per_token']
                            value = canonical(Decimal(quantity) * Decimal(numerator)
                                / (Decimal(10**point['decimals']) * Decimal(denominator)))
                            ratio = {'numerator': str(numerator), 'denominator': str(denominator)}
                            valuation_method = reserve_marks['method']
                            price_indexes = [index for index, _ in valid]
                            price_refs += [row['check'] for _, row in valid]
                            known = True
                        else:
                            gap = ('Contemporaneous raw pool marks disagree or do not match this exact owned-token phase.'
                                   if candidates else 'Nonzero nonsettlement units have no accepted exact-phase historical SOL mark')
                except (ValueError, TypeError) as exc:
                    gap = str(exc)
                check = _check(known, gap or ('Exact-phase reserve-ratio spot value; no report-boundary or executable liquidation assertion.'
                    if valuation_method else 'Protocol wrapped SOL denomination, with no rent/reserve double counting.'
                    if mark else 'Proved zero token units need no historical price; account lamports remain separate.'),
                    _refs(*required, *price_refs), dependencies=['linked_token_phase_identity', 'linked_token_phase_units']
                        + ([] if known else ['accepted_historical_asset_mark']))
                row = {'account': account, 'mint': point.get('mint'), 'program': pair.get('program'),
                    'decimals': point.get('decimals'), 'quantity_raw': str(quantity) if quantity is not None else None,
                    'mark_sol_per_token': mark, 'observed_token_value_sol': value if known else None,
                    'check': check, 'account_lamports_value_state': 'UNKNOWN'}
                if valuation_method:
                    row.update(valuation_method=valuation_method, mark_ratio=ratio,
                               reserve_mark_indexes=price_indexes, executable_liquidation_state='UNKNOWN')
                output[phase].append(row)
                if mark and point.get('mint') == WSOL:
                    marks.append({'signature': signature, 'phase': phase, 'mint': WSOL,
                        'program': TOKEN_PROGRAM, 'mark_sol_per_token': '1', 'check': check})
        phases[signature] = output
    return phases, marks, False


def _boundary_candidates(native, wallet_evidence, window):
    start, end = utc(window['start']), utc(window['end'])
    clocks = wallet_evidence.get('chronology', {}).get('transactions', {})
    intervals = wallet_evidence.get('intervals', {})
    query_intervals = wallet_evidence.get('query_coverage', {}).get('intervals', {})
    output = {}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        members = intervals.get(name, {}).get('selected_record_membership', {})
        query = query_intervals.get(name, {})
        chosen, required = [], []
        for signature, row in native.items():
            membership = members.get(signature, {})
            if _usable(membership) and membership.get('member') is False:
                continue
            clock = clocks.get(signature, {})
            required.extend([membership, row['check'], clock])
            if (not _usable(membership) or membership.get('member') is not True
                    or not _usable(row['check']) or not _usable(clock) or row['present'] is None):
                continue
            if row['present']:
                chosen.append((clock.get('slot'), clock.get('transaction_index'), signature, row))
        # Shared chronology already decides same-slot ordering. A single
        # transaction in a slot needs no imported transaction-index hint.
        chosen.sort(key=lambda r: (r[0], -1 if r[1] is None else r[1], r[2]))
        continuous = all(a[3]['post'] == b[3]['pre'] for a, b in zip(chosen, chosen[1:]))
        known = bool(chosen) and continuous and all(_usable(row) for row in required)
        check = _check(known, 'First/last selected native-address phases form a continuous candidate chain; unseen history remains a separate dependency.'
            if known else 'A required selected phase/clock is unavailable or consecutive absolute native balances do not reconcile.',
            _refs(*required), dependencies=['complete_native_address_history', 'provider_format_population'],
            scope='Conditional selected native-address boundary candidates only', interval=name)
        projection = _check(known and _usable(query) and query.get('supported_record_state') == 'PASS'
            and query.get('format_population_state') == 'PASS',
            'Exact native boundary projection additionally needs a complete supported provider format population.',
            check['evidence'] + _refs(query), dependencies=['complete_native_address_history', 'provider_format_population'], interval=name)
        output[name] = {'start': begin.isoformat(), 'end': end.isoformat(),
            'opening_native_lamports_candidate': chosen[0][3]['pre'] if known else None,
            'closing_native_lamports_candidate': chosen[-1][3]['post'] if known else None,
            'selected_wallet_records': [r[2] for r in chosen], 'check': check,
            'native_boundary_projection': projection, 'wallet_equity_state': 'UNKNOWN'}
    return output


def derive_economic_evidence(records, *, all_records, wallet, window, wallet_evidence, raw_sources=()):
    """Project raw supported observations without manufacturing economic inputs.

    The ordinary adapter supplies freshly derived shared consistency, chronology
    and component checks. These are internal results, not uploadable certificates.
    A complete genuine inventory/marks/capital-role adapter is still required;
    useful native phases and wrapped-SOL denomination do not replace it.
    """
    records, all_records = list(records), list(all_records)
    if len(records) + len(all_records) > 2 * MAX_RECORDS:
        raise ValueError('Economic raw observations exceed the fixed linked-record budget')
    selected = {r['signature'] for r in records if isinstance(r, dict) and isinstance(r.get('signature'), str)}
    linked = defaultdict(dict)
    for row in all_records + records:
        if not isinstance(row, dict) or row.get('signature') not in selected:
            continue
        key = row.get('evidence_hash')
        existing = linked[row['signature']].get(key)
        if existing is not None and existing.get('raw') != row.get('raw'):
            row = {**row, 'raw': None}
        linked[row['signature']][key] = row
    if sum(len(v) for v in linked.values()) > MAX_RECORDS:
        raise ValueError('Economic raw observations exceed the fixed distinct linked-record budget')
    consistency = wallet_evidence.get('source_consistency', {})
    from .historical_reserve_marks import project_historical_reserve_marks
    reserve_marks = project_historical_reserve_marks(records, all_records=all_records,
        raw_sources=raw_sources, consistency=consistency, chronology=wallet_evidence.get('chronology', {}))
    with localcontext() as context:
        context.prec = 100
        native = {signature: _native_observation(signature, list(variants.values()), consistency, wallet)
                  for signature, variants in sorted(linked.items())}
        tokens, marks, token_budget = _token_observations(wallet_evidence.get('transactions', {}), wallet,
            reserve_marks, wallet_evidence.get('chronology', {}))
        boundaries = _boundary_candidates(native, wallet_evidence, window)
    components = wallet_evidence.get('components', {})
    intervals = wallet_evidence.get('intervals', {})
    queries = wallet_evidence.get('query_coverage', {}).get('intervals', {})
    exact_boundaries = wallet_evidence.get('inventory_observations', {}).get('components', {}).get('report_boundaries')
    component_checks, zero_external_flow_inputs = {}, {}
    boundary_checks, mark_checks, flow_checks = {}, {}, {}
    for name in ('report_period', 'four_weeks', 'verification_90d'):
        query = queries.get(name, {})
        format_population = _check(query.get('format_population_state') == 'PASS',
            'The documented query must include the complete supported native format population, independently of endpoint/schema access.',
            _refs(query), dependencies=['accepted_provider_format_population'], interval=name)
        boundary_checks[name] = _combine([components.get('historical_population'), intervals.get(name),
            format_population, exact_boundaries],
            'Exact all-account opening/closing inventories are independently supported.',
            dependencies=['historical_population', 'independent_interval_records', 'provider_format_population',
                          'exact_all_account_report_boundaries'], interval=name)
        mark_checks[name] = _combine([boundary_checks[name], _scoped(components, 'historical_marks', name)],
            'Every required nonzero boundary asset has an accepted historical SOL mark; protocol denomination alone does not cover other assets.',
            dependencies=['exact_boundary_assets', 'accepted_historical_asset_marks'], interval=name)
        # Existing role reconstruction only passes when every selected gross
        # movement has trade/network-fee/internal semantics and reconciles raw
        # native wealth. With complete population/interval/format proof, that
        # can establish zero external flows. Direction/netting alone cannot.
        flow_checks[name] = _combine([components.get('historical_population'), intervals.get(name),
            format_population, _scoped(components, 'observed_economic_roles', name)],
            'Complete supported trade/fee/internal roles establish no external deposits or withdrawals in this independent interval.',
            dependencies=['historical_population', 'independent_interval_records', 'provider_format_population',
                          'complete_gross_economic_roles'], interval=name)
        if _usable(flow_checks[name]):
            zero_external_flow_inputs[name] = {'external_deposits': '0', 'external_withdrawals': '0'}
    component_checks.update(boundary_inventory_by_interval=boundary_checks, historical_marks_by_interval=mark_checks,
        valued_external_flows_by_interval=flow_checks,
        boundary_inventory=boundary_checks['report_period'], historical_marks=mark_checks['report_period'],
        valued_external_flows=flow_checks['report_period'],
        observed_native_boundary_candidates_by_interval={name: row['check'] for name, row in boundaries.items()},
        observed_protocol_settlement_marks=_combine((row['check'] for row in marks),
            'Every observed legacy wrapped-SOL unit is denominated at one SOL per token; rent/reserve lamports are separately unvalued.'))
    dependencies = {name: component_checks[name] for name in
        ('boundary_inventory', 'historical_marks', 'valued_external_flows')}
    # Existing complete economic inputs must come from the accepted source
    # adapters, not inferred from selected native endpoints or a unit mark.
    # Exact-phase reserve marks are usable observations, but are not a genuine
    # all-account boundary inventory/mark/flow completion contract.
    return {'version': VERSION, 'scope': _SCOPE, 'observed_native_phases': native,
        'observed_token_phases': tokens, 'protocol_settlement_marks': marks,
        'historical_reserve_marks': reserve_marks,
        'boundary_candidates_by_interval': boundaries,
        'native_cash_observation_binding': {
            'path': 'wallet_evidence.native_cash_observations',
            'version': (wallet_evidence.get('native_cash_observations') or {}).get('version'),
            'evidence': _refs(*[(row or {}).get('transfer_check') for row in
                (wallet_evidence.get('native_cash_observations') or {}).get('transactions', {}).values()])},
        'economic_input_dependencies': dependencies, 'component_checks': component_checks,
        'zero_external_flow_inputs': zero_external_flow_inputs,
        # No supported source here derives exact opening/closing equity. Even
        # an independently accepted zero-flow result cannot supply those two
        # absent numerical inputs or activate complete economic P&L.
        'economic_inputs': {},
        'inspection_budget': {'max_linked_records': MAX_RECORDS, 'linked_records': sum(len(v) for v in linked.values()),
                              'max_account_phases': MAX_ACCOUNT_PHASES, 'account_phases_exceeded': token_budget},
        'remaining_source_contracts': ['exact_all_account_boundary_inventory', 'exact_boundary_nonsettlement_marks',
                                      'complete_valued_external_flow_roles'],
        'qualification': False, 'provider_requests': 0, 'credential_lookups': 0}
