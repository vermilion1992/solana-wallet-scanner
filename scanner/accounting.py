"""Exact, conservative FIFO research accounting (not a tax or execution engine).

Normalized events:
  kind: buy, sell, transfer_in, transfer_out, internal_transfer, fee,
        unsupported, capital, wrap, or rent
  timestamp: timezone-aware UTC ISO string or integer Unix seconds; order: int
  mint: real mint identity; quantity_raw: unsigned integer STRING; decimals: int
  amount_sol: nonnegative decimal STRING or null (buy consideration/sell proceeds)
  fee_sol: nonnegative decimal STRING or null; paid_by_wallet: bool (default True)
  classification: meme / settlement / unknown (default unknown)
  signature, path, evidence:[hashes]: retained source provenance
Incoming transfers may specify basis_sol ONLY when provenance establishes basis.
A buy fee is capitalized and a sell fee deducted once. A standalone fee's amount_sol
is unallocated trading overhead, including failed-transaction fees. Sponsored fees
are excluded. Embedded venue fees must already be reflected in amount_sol.
An original fee event can remain visible with allocation=buy_basis/sell_exit and
allocated_trade_path. This display copy is excluded from overhead only after its
signature, time, route, payer and exact amount match one fee-bearing trade. Invalid
or duplicate allocation claims are rejected rather than silently dropping spend.

Callers provide complete opening-cost events before start, not a zero inventory
assumption. Unsupported events (including missing history) invalidate affected
metrics. Coverage remains a separate certificate; the ledger never proves global
historical ownership from a reconciled balance. Decimal arithmetic is used at high
precision; partial-lot allocations retain the remainder for exact basis conservation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
import re
from typing import Any

METHODOLOGY = 'fifo-v4'
D = Decimal
ZERO = D('0')
HUNDRED = D('100')
_DECIMAL = re.compile(r'^(?:0|[1-9]\d*)(?:\.\d+)?$')
_RAW = re.compile(r'^(?:0|[1-9]\d*)$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')


def decimal(value: Any, *, signed: bool = False, max_length: int = 100) -> Decimal:
    """Reject booleans, floats and nonfinite/coercive financial values."""
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError('Financial values must be finite decimal strings')
    body = value[1:] if signed and value.startswith('-') else value
    if not _DECIMAL.fullmatch(body):
        raise ValueError('Invalid decimal string')
    result = D(value)
    if not result.is_finite():
        raise ValueError('Nonfinite decimal')
    return result


def canonical(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return '0'
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def raw_quantity(value: Any) -> int:
    if not isinstance(value, str) or len(value) > 80 or not _RAW.fullmatch(value):
        raise ValueError('quantity_raw must be an unsigned integer string')
    return int(value)


def utc(value: Any) -> datetime:
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError('Timestamp is outside the supported UTC date range') from exc
    if not isinstance(value, str):
        raise ValueError('Timestamp must be timezone-aware ISO or integer seconds')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp needs an explicit timezone')
    return parsed.astimezone(timezone.utc)


def median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _metric(value, unit, population, *, reason=None, evidence=None):
    return {'value': canonical(value), 'unit': unit,
            'status': 'unknown' if value is None else 'known',
            'population': population, 'reason': reason if value is None else None,
            'evidence': sorted(set(evidence or []))}


def _hours(begin, finish):
    delta = finish - begin
    seconds = D(delta.days) * D('86400') + D(delta.seconds) + D(delta.microseconds) / D('1000000')
    return seconds / D('3600')


def validate_fee_allocations(events):
    """Map allocated display-fee indices to their unique fee-bearing trade.

    Legacy events without allocation metadata and explicit ``unallocated`` fees
    retain ordinary overhead treatment. An allocation is an accounting claim,
    never a hint: incomplete, mismatched or duplicated claims raise ValueError.
    The caller's observations are not modified.
    """
    trades = defaultdict(list)
    for index, event in enumerate(events):
        if event.get('kind') in ('buy', 'sell'):
            signature, path = event.get('signature'), event.get('path')
            if isinstance(signature, str) and isinstance(path, str):
                trades[(signature, path)].append(index)
    allocations = {}
    allocated_trades = set()
    for index, event in enumerate(events):
        if 'allocation' not in event and 'allocated_trade_path' not in event:
            continue
        if event.get('kind') != 'fee':
            raise ValueError('Fee allocation metadata belongs only to a fee event')
        allocation = event.get('allocation')
        if allocation == 'unallocated':
            if event.get('allocated_trade_path') is not None:
                raise ValueError('Unallocated fee cannot claim an allocated trade path')
            continue
        if allocation not in ('buy_basis', 'sell_exit'):
            raise ValueError('Fee allocation must be unallocated, buy_basis or sell_exit')
        signature = event.get('signature')
        path = event.get('allocated_trade_path')
        if not isinstance(signature, str) or not signature or not isinstance(path, str) or not path:
            raise ValueError('Allocated fee needs a signature and allocated trade path')
        matching = trades.get((signature, path), [])
        if len(matching) != 1:
            raise ValueError('Allocated fee must identify exactly one trade by signature and path')
        trade_index = matching[0]
        trade = events[trade_index]
        if trade_index in allocated_trades:
            raise ValueError('A trade fee cannot have duplicate allocation display events')
        expected_kind = 'buy' if allocation == 'buy_basis' else 'sell'
        if trade.get('kind') != expected_kind:
            raise ValueError('Fee allocation does not match the trade kind')
        if event.get('paid_by_wallet') is not True or trade.get('paid_by_wallet') is not True:
            raise ValueError('Allocated fees must be explicitly paid by the scoped wallet')
        if event.get('amount_sol') is None or trade.get('fee_sol') is None:
            raise ValueError('Allocated fees require known fee amounts on the fee event and trade')
        if decimal(event['amount_sol']) != decimal(trade['fee_sol']):
            raise ValueError('Allocated fee amount must exactly match the trade fee')
        if utc(event.get('timestamp')) != utc(trade.get('timestamp')):
            raise ValueError('Allocated fee and trade must have the same event time')
        allocations[index] = trade_index
        allocated_trades.add(trade_index)
    return allocations


def _metric_intervals(start, end, history_complete, declarations, evidence):
    """Describe independent history intervals without certifying raw evidence.

    Legacy history_complete is a trusted normalized-input declaration. Explicit
    complete intervals need bounds covering the required interval and primary
    SHA-256 evidence references. The application must independently verify those
    records before making such a declaration; hash syntax alone proves nothing.
    """
    bounds = {'report_period': (start, end),
              'four_weeks': (end - timedelta(days=28), end),
              'verification_90d': (end - timedelta(days=90), end)}
    if declarations is not None and (not isinstance(declarations, dict) or
                                      set(declarations) - set(bounds)):
        raise ValueError('Interval coverage must use report_period, four_weeks or verification_90d')
    result = {}
    for name, (required_start, required_end) in bounds.items():
        if declarations is None or name not in declarations:
            result[name] = {'interval': name, 'start': required_start.isoformat(),
                            'end': required_end.isoformat(),
                            'status': 'complete' if history_complete else 'partial',
                            'source': 'normalized_input_declaration',
                            'evidence': sorted(evidence),
                            'reason': None if history_complete else 'Complete history for this interval is not established'}
            continue
        record = declarations[name]
        if not isinstance(record, dict) or record.get('status') not in ('complete', 'partial', 'unknown'):
            raise ValueError('Each interval coverage record needs a complete, partial or unknown status')
        available_start, available_end = utc(record.get('start')), utc(record.get('end'))
        if available_end <= available_start:
            raise ValueError('Interval coverage needs a positive duration')
        hashes = record.get('evidence', [])
        if not isinstance(hashes, list) or any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in hashes):
            raise ValueError('Interval evidence must contain primary SHA-256 hashes')
        if record['status'] == 'complete' and not hashes:
            raise ValueError('A complete interval needs primary evidence references')
        reason = record.get('reason')
        if reason is not None and not isinstance(reason, str):
            raise ValueError('Interval coverage reason must be text')
        spans_required = available_start <= required_start and available_end >= required_end
        status = 'partial' if not spans_required and record['status'] == 'complete' else record['status']
        result[name] = {'interval': name, 'start': required_start.isoformat(),
                        'end': required_end.isoformat(), 'status': status,
                        'available_start': available_start.isoformat(),
                        'available_end': available_end.isoformat(),
                        'source': 'primary_evidence_declaration', 'evidence': sorted(set(hashes)),
                        'reason': ('Declared history does not span the required independent interval' if not spans_required else
                                   reason if reason else None if status == 'complete' else 'Complete history for this interval is not established')}
    return result


def analyze(events, start, end, opening_equity=None, closing_equity=None,
            external_deposits=None, external_withdrawals=None, history_complete=True,
            *, interval_coverage=None):
    """Build strict-zero episodes and period metrics over [start,end).

    Events before start recover opening lots; events at/after end are excluded.
    Economic inputs are event-time SOL equity/flow totals; all four are required.
    Synthetic normalized inputs are test data, never independently validated records.
    Four-week consistency always uses [end-28d,end), independent of display start.
    interval_coverage may declare report_period/four_weeks/verification_90d records
    with start, end, status and primary evidence hashes. It can establish the
    independent four-week history only; it never upgrades global history or policy.
    """
    with localcontext() as ctx:
        ctx.prec = 192
        return _analyze(events, utc(start), utc(end), opening_equity, closing_equity,
                        external_deposits, external_withdrawals, history_complete, interval_coverage)


def _analyze(events, start, end, opening_equity, closing_equity, deposits, withdrawals, history_complete,
             interval_coverage):
    if end <= start:
        raise ValueError('Reporting window must have positive duration')
    events = list(events)
    fee_allocations = validate_fee_allocations(events)
    verification_start = end - timedelta(days=90)
    normalized = []
    findings = []
    if not isinstance(history_complete, bool):
        raise ValueError('history_complete must be boolean')
    general_unknown = not history_complete
    ledger_unknown = False
    if not history_complete:
        findings.append({'severity': 'warning', 'title': 'History scope remains partial',
                         'detail': 'Observed events are retained; financial and episode populations remain unresolved until ownership and history scope are established.'})
    all_evidence = set()
    for index, original in enumerate(events):
        event = dict(original)
        all_evidence.update(event.get('evidence') or [])
        try:
            when = utc(event.get('timestamp'))
        except (ValueError, OverflowError, TypeError):
            general_unknown = True
            ledger_unknown = True
            findings.append({'severity': 'warning', 'title': 'Unresolved chronology',
                             'detail': 'An event has no usable event time; affected populations remain unknown.',
                             'evidence': event.get('evidence', [])})
            continue
        if when >= end:
            continue
        order = event.get('order', index)
        if not isinstance(order, int) or isinstance(order, bool):
            raise ValueError('Event order must be an integer')
        normalized.append((when, order, index, event))
    normalized.sort(key=lambda item: item[:3])
    # Same-time input order is only a display fallback, not blockchain chronology.
    by_time = defaultdict(list)
    for row in normalized:
        by_time[row[0]].append(row)
    for rows in by_time.values():
        by_mint = defaultdict(list)
        for row in rows:
            if row[3].get('mint'):
                by_mint[row[3]['mint']].append(row)
        for mint_rows in by_mint.values():
            if len(mint_rows) > 1 and (any('order' not in row[3] for row in mint_rows) or
                                      len({row[1] for row in mint_rows}) != len(mint_rows)):
                general_unknown = True
                ledger_unknown = True
                findings.append({'severity': 'warning', 'title': 'Ambiguous event order',
                                 'detail': 'Same-time events for one mint need distinct evidenced order.'})
    active = {}
    positions = []
    realised = []
    overhead = []
    traded_mints = set()
    uncertain_classification = False
    financial_unknown = general_unknown
    episode_unknown = general_unknown
    latest_decimals = {}
    latest_classification = {}

    def new_episode(mint, when, classification, order):
        episode = {'id': f'{mint}:{len(positions) + 1}', 'mint': mint,
                   'classification': classification, 'start': when, 'end': None, 'start_order': order, 'end_order': None,
                   'quantity': 0, 'acquired': 0, 'sold': 0, 'lots': [],
                   'buy_count': 0, 'sell_count': 0, 'basis': ZERO,
                   'proceeds': ZERO, 'exit_fees': ZERO, 'matched_basis': ZERO,
                   'unknown': False, 'quantity_unknown': False, 'basis_unknown': False,
                   'interrupted': False, 'first_sale': None, 'first_sale_unknown': False,
                   'disposals': [], 'evidence': set(), 'decimals': None}
        positions.append(episode)
        active[mint] = episode
        return episode

    def consume(episode, quantity):
        """Consume raw units, preserving remainder of every cost-bearing FIFO lot."""
        remaining = quantity
        basis = ZERO
        known = True
        while remaining and episode['lots']:
            lot = episode['lots'][0]
            take = min(lot['quantity'], remaining)
            if lot['basis'] is None:
                known = False
                episode['basis_unknown'] = True
            else:
                cost = lot['basis'] if take == lot['quantity'] else lot['basis'] * D(take) / D(lot['quantity'])
                basis += cost
                lot['basis'] -= cost
            lot['quantity'] -= take
            remaining -= take
            if not lot['quantity']:
                episode['lots'].pop(0)
        if remaining:
            known = False
            episode['unknown'] = True
            episode['quantity_unknown'] = True
        return basis if known else None

    for when, order, index, event in normalized:
        kind = event.get('kind')
        evidence = event.get('evidence') or []
        if not isinstance(evidence, list) or any(not isinstance(h, str) for h in evidence):
            raise ValueError('Evidence must be a list of hashes')
        in_window = start <= when < end
        classification = event.get('classification', 'unknown')
        if classification in ('market', 'read_non_trade', 'lp', 'quote_conversion', 'conversion'):
            classification = 'unknown'
        if classification not in ('meme', 'settlement', 'unknown'):
            raise ValueError('Invalid classification')
        if kind == 'lp':
            mint = event.get('mint')
            if mint or event.get('touches_result_relevant_mint'):
                episode_unknown = True
                if mint and mint in active:
                    active[mint]['unknown'] = True
                    active[mint]['quantity_unknown'] = True
            continue
        if kind == 'conversion':
            episode_unknown = True
            mint = event.get('mint')
            if mint and mint in active:
                active[mint]['unknown'] = True
                active[mint]['quantity_unknown'] = True
            continue
        if kind == 'non_trade':
            continue
        paid = event.get('paid_by_wallet', True)
        if not isinstance(paid, bool):
            raise ValueError('paid_by_wallet must be boolean')
        if kind == 'fee':
            amount = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
            # A settlement-only trade is outside this asset population. Its paid
            # fee remains period overhead rather than disappearing with that trade.
            if index in fee_allocations and events[fee_allocations[index]].get('classification', 'unknown') != 'settlement':
                continue
            if paid:
                overhead.append((when, amount, evidence))
                if in_window and amount is None:
                    financial_unknown = True
            continue
        if kind == 'unsupported':
            if when >= verification_start or event.get('affects_opening', True):
                general_unknown = financial_unknown = episode_unknown = True
                ledger_unknown = True
                findings.append({'severity': 'warning', 'title': 'Unsupported or incomplete activity',
                                 'detail': event.get('reason', 'A route cannot be reconstructed with the supported decoder.'),
                                 'evidence': evidence})
            continue
        if kind in ('capital', 'wrap', 'rent', 'internal_transfer'):
            continue
        if kind not in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            raise ValueError(f'Unknown event kind: {kind}')
        mint = event.get('mint')
        if not isinstance(mint, str) or not mint:
            raise ValueError('Asset events need a mint identity')
        quantity = raw_quantity(event.get('quantity_raw'))
        decimals = event.get('decimals')
        if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 255:
            raise ValueError('Mint decimals must be an integer from 0 to 255')
        if mint in latest_decimals and latest_decimals[mint] != decimals:
            raise ValueError('Conflicting decimals for one mint')
        latest_decimals[mint] = decimals
        if mint in latest_classification and latest_classification[mint] != classification:
            uncertain_classification = financial_unknown = episode_unknown = True
            ledger_unknown = True
            findings.append({'severity': 'warning', 'title': 'Conflicting mint classification',
                             'detail': f'{mint} has inconsistent settlement/meme classification.', 'evidence': evidence})
        latest_classification[mint] = classification
        if quantity == 0:
            raise ValueError('Asset event quantity must be positive')
        if classification == 'settlement':
            continue
        if classification == 'unknown':
            uncertain_classification = True
            financial_unknown = episode_unknown = True
            ledger_unknown = True
        if kind in ('buy', 'sell') and in_window:
            traded_mints.add(mint)
        episode = active.get(mint) or new_episode(mint, when, classification, order)
        episode['decimals'] = decimals
        episode['evidence'].update(evidence)
        if episode['classification'] != classification:
            episode['unknown'] = True
            uncertain_classification = True
        fee = decimal(event['fee_sol']) if event.get('fee_sol') is not None else (ZERO if 'fee_sol' not in event else None)
        if not paid:
            fee = ZERO
        if kind in ('buy', 'transfer_in'):
            if kind == 'buy':
                amount = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
                basis = amount + fee if amount is not None and fee is not None else None
                episode['buy_count'] += 1
            else:
                basis = decimal(event['basis_sol']) if event.get('basis_sol') is not None else None
                episode['interrupted'] = True
            episode['lots'].append({'quantity': quantity, 'basis': basis, 'timestamp': when,
                'order': order, 'signature': event.get('signature'), 'evidence': list(evidence),
                'acquisition_quantity': quantity})
            episode['quantity'] += quantity
            episode['acquired'] += quantity
            if basis is None:
                episode['unknown'] = True
                episode['basis_unknown'] = True
            else:
                episode['basis'] += basis
            continue
        # An unobserved opening inventory is unknown, never an invented zero-cost lot.
        if episode['quantity'] < quantity:
            gap = quantity - episode['quantity']
            episode['lots'].insert(0, {'quantity': gap, 'basis': None, 'timestamp': None})
            episode['quantity'] += gap
            episode['acquired'] += gap
            episode['unknown'] = True
            episode['quantity_unknown'] = True
            episode['basis_unknown'] = True
            findings.append({'severity': 'warning', 'title': 'Earlier inventory unresolved',
                             'detail': f'A disposal of {mint} needs {gap} earlier raw units and their cost.',
                             'evidence': evidence})
        basis = consume(episode, quantity)
        episode['quantity'] -= quantity
        if kind == 'transfer_out':
            episode['interrupted'] = True
        else:
            proceeds = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
            net = proceeds - basis - fee if proceeds is not None and basis is not None and fee is not None else None
            episode['sell_count'] += 1
            episode['sold'] += quantity
            if proceeds is not None:
                episode['proceeds'] += proceeds
            if fee is not None:
                episode['exit_fees'] += fee
            if basis is not None:
                episode['matched_basis'] += basis
            if net is None:
                episode['unknown'] = True
            if proceeds is not None and proceeds > ZERO and episode['first_sale'] is None:
                episode['first_sale'] = when
            elif proceeds is None and episode['first_sale'] is None:
                # Missing money cannot hide an earlier positive economic sale
                # behind a later observed one. Entry costs and exit fees do not
                # determine whether the gross sale consideration is positive.
                episode['first_sale_unknown'] = True
            episode['disposals'].append({'timestamp': when, 'quantity': quantity})
            realised.append({'timestamp': when, 'mint': mint, 'basis': basis, 'net': net,
                             'proceeds': proceeds, 'fee': fee, 'evidence': evidence})
            if in_window and net is None:
                financial_unknown = True
        if episode['quantity'] == 0:
            episode['end'] = when
            episode['end_order'] = order
            active.pop(mint, None)

    eligible = [p for p in positions if p['end'] is not None and start <= p['end'] < end]
    cohort = [p for p in eligible if not p['interrupted']]
    verification = [p for p in positions if p['end'] is not None and verification_start <= p['end'] < end and not p['interrupted']]
    # An interrupted candidate could conceal a full episode; do not omit it from fit.
    # Quantity/origin and strict-zero membership have different dependencies
    # from acquisition money. A known buy of ten units with missing cost can
    # still close a known two-hour episode when those ten units are sold.
    ambiguous = [p for p in positions if (p['end'] is None or p['end'] >= start) and
                 (p['quantity_unknown'] or p['interrupted'] or p['classification'] == 'unknown')]
    cohort_uncertain = episode_unknown or bool(ambiguous)
    verification_uncertain = episode_unknown or any(p['quantity_unknown'] or p['interrupted'] for p in positions if p['end'] is None or p['end'] >= verification_start)
    monetary_cohort_uncertain = cohort_uncertain or any(p['unknown'] for p in cohort)
    first_sale_uncertain = cohort_uncertain or any(p['first_sale_unknown'] for p in cohort)
    sales = [r for r in realised if start <= r['timestamp'] < end]
    known_net = sum((r['net'] for r in sales if r['net'] is not None), ZERO)
    known_overhead = sum((amount for when, amount, _ in overhead if start <= when < end and amount is not None), ZERO)
    profit = None if financial_unknown else known_net - known_overhead
    disposed_basis = sum((r['basis'] for r in sales if r['basis'] is not None), ZERO)
    realised_roi = profit / disposed_basis * HUNDRED if profit is not None and disposed_basis > ZERO else None
    holds = [_hours(p['start'], p['end']) for p in cohort]
    episode_profits = [p['proceeds'] - p['matched_basis'] - p['exit_fees'] for p in cohort]
    rois = [(p['proceeds'] - p['matched_basis'] - p['exit_fees']) / p['matched_basis'] * HUNDRED
            for p in cohort if p['matched_basis'] > ZERO]
    roi_uncertain = monetary_cohort_uncertain or len(rois) != len(cohort)
    count = len(cohort)
    win_rate = D(sum(p > ZERO for p in episode_profits)) / D(count) * HUNDRED if count and not monetary_cohort_uncertain else None
    rapid = D(sum(p['first_sale'] is not None and (p['first_sale'] - p['start']) <= timedelta(minutes=5) for p in cohort)) / D(count) * HUNDRED if count and not first_sale_uncertain else None
    buys = D(sum(p['buy_count'] for p in cohort)) / D(count) if count and not cohort_uncertain else None
    sells = D(sum(p['sell_count'] for p in cohort)) / D(count) if count and not cohort_uncertain else None
    intervals = _metric_intervals(start, end, history_complete, interval_coverage, all_evidence)
    four_week_coverage = intervals['four_weeks']
    weeks = []
    for week in range(4):
        week_end = end - timedelta(days=7 * week)
        week_start = week_end - timedelta(days=7)
        rows = [r for r in realised if week_start <= r['timestamp'] < week_end]
        fees = [(amount, evidence) for when, amount, evidence in overhead if week_start <= when < week_end]
        weekly_reason = (four_week_coverage['reason'] or 'Complete independent four-week history is not established') if four_week_coverage['status'] != 'complete' else (
            'Chronology, classification or unsupported activity remains unresolved' if ledger_unknown else
            'Acquisition basis or exit costs are unresolved for this week' if any(r['net'] is None for r in rows) else
            'Wallet-paid unallocated costs are unresolved for this week' if any(amount is None for amount, _ in fees) else None)
        value = None if weekly_reason else sum((r['net'] for r in rows), ZERO) - sum((amount for amount, _ in fees), ZERO)
        weekly_evidence = set(four_week_coverage['evidence'])
        weekly_evidence.update(h for row in rows for h in row['evidence'])
        weekly_evidence.update(h for _, hashes in fees for h in hashes)
        weeks.append({'start': week_start.isoformat(), 'end': week_end.isoformat(),
                      'profit_sol': canonical(value), 'status': 'unknown' if value is None else 'known',
                      'reason': weekly_reason, 'interval': 'four_weeks', 'evidence': sorted(weekly_evidence)})
    positive_weeks = sum(D(w['profit_sol']) > ZERO for w in weeks) if all(w['profit_sol'] is not None for w in weeks) else None
    mint_net = defaultdict(lambda: ZERO)
    for sale in sales:
        if sale['net'] is not None:
            mint_net[sale['mint']] += sale['net']
    positive_mint = max([ZERO] + [value for value in mint_net.values() if value > ZERO])
    concentration = positive_mint / profit * HUNDRED if profit is not None and profit > ZERO else None
    economic = None
    if all(value is not None for value in (opening_equity, closing_equity, deposits, withdrawals)):
        economic = decimal(closing_equity) - decimal(opening_equity) - decimal(deposits) + decimal(withdrawals)
    reason = 'Incomplete basis, chronology, classification or interrupted eligible episode'
    quantity_reason = 'Incomplete acquisition quantities, chronology, classification or interrupted eligible episode'
    first_sale_reason = 'Incomplete eligible episode population or first positive sale consideration'
    metrics = {
        'profit_sol': _metric(profit, 'SOL', 'In-window meme disposals less matched basis, exit costs and trading overhead', reason=reason, evidence=all_evidence),
        'realised_roi_pct': _metric(realised_roi, '%', 'Period net realised profit / disposed acquisition cost', reason=reason if financial_unknown else 'No positive disposed basis', evidence=all_evidence),
        'median_roi_pct': _metric(None if roi_uncertain else median(rois), '%', 'Whole-episode net ROI; strict-zero completed cohort', reason=reason if roi_uncertain else 'No completed episodes', evidence=all_evidence),
        'win_rate_pct': _metric(win_rate, '%', 'Net-positive strict-zero completed episodes / all completed episodes (breakeven included)', reason=reason if monetary_cohort_uncertain else 'No completed episodes', evidence=all_evidence),
        'median_hold_hours': _metric(None if cohort_uncertain else median(holds), 'hours', 'First acquisition to final sale; strict-zero closes inside reporting window', reason=quantity_reason if cohort_uncertain else 'No completed episodes', evidence=all_evidence),
        'completed_positions': _metric(None if cohort_uncertain else count, 'positions', 'Strict-zero completed episodes closing in report window', reason=quantity_reason, evidence=all_evidence),
        'completed_positions_90d': _metric(None if verification_uncertain else len(verification), 'positions', 'Strict-zero completed episodes closing in 90 days ending at report end', reason=quantity_reason, evidence=all_evidence),
        'traded_mints': _metric(None if uncertain_classification or general_unknown else len(traded_mints), 'mints', 'Distinct meme mint IDs traded in reporting window; settlement assets excluded', reason='Classification or scope unresolved', evidence=all_evidence),
        'rapid_sale_pct': _metric(rapid, '%', 'Completed episodes with first positive economic sale within five minutes', reason=first_sale_reason if first_sale_uncertain else 'No completed episodes', evidence=all_evidence),
        'avg_buys': _metric(buys, 'buys/episode', 'Buy events per strict-zero completed episode', reason=quantity_reason if cohort_uncertain else 'No completed episodes', evidence=all_evidence),
        'avg_sells': _metric(sells, 'sells/episode', 'Sale events per strict-zero completed episode', reason=quantity_reason if cohort_uncertain else 'No completed episodes', evidence=all_evidence),
        'positive_weeks': _metric(positive_weeks, 'weeks', 'Four independent consecutive seven-day periods over [report end - 28 days, report end)', reason='Independent four-week history, matched basis or costs remain unresolved', evidence=all_evidence | set(four_week_coverage['evidence'])),
        'largest_contribution_pct': _metric(concentration, '%', 'Highest positive aggregate realised P&L for one mint / positive net period P&L', reason=reason if financial_unknown else 'Net period profit is not positive', evidence=all_evidence),
        'economic_pnl_sol': _metric(economic, 'SOL', 'Closing equity - opening equity - external deposits + withdrawals', reason='Boundary equity and valued external flows must all be reconciled', evidence=all_evidence),
    }
    # A missing proof and an arithmetic domain with no defined answer are
    # different outcomes. These witnesses are produced from this FIFO pass,
    # never accepted from normalized event flags. Undefined metrics retain a
    # null numerical value; the application still verifies their dependencies.
    metric_domains = {key: {'status': 'defined' if metric['value'] is not None else 'unknown',
                            'reason_code': None, 'witness': {}}
                      for key, metric in metrics.items()}

    def undefined_domain(key, reason_code, witness):
        if metrics[key]['value'] is None:
            metric_domains[key] = {'status': 'undefined', 'reason_code': reason_code,
                                   'witness': witness}

    if profit is not None and profit <= ZERO:
        undefined_domain('largest_contribution_pct', 'nonpositive_period_profit',
                         {'profit_sol': canonical(profit)})
    if profit is not None and disposed_basis == ZERO:
        undefined_domain('realised_roi_pct', 'zero_disposed_basis',
                         {'disposed_basis_sol': '0', 'profit_sol': canonical(profit)})
    if not cohort_uncertain and count == 0:
        for key in ('median_hold_hours', 'win_rate_pct', 'rapid_sale_pct', 'avg_buys', 'avg_sells',
                    'median_roi_pct'):
            undefined_domain(key, 'empty_completed_cohort', {'completed_positions': '0'})
    elif not monetary_cohort_uncertain and count:
        zero_basis = [p['id'] for p in cohort if p['matched_basis'] == ZERO]
        if zero_basis:
            undefined_domain('median_roi_pct', 'zero_episode_basis',
                             {'completed_positions': str(count), 'zero_basis_episode_ids': zero_basis})
    rendered = []
    for episode in positions:
        state = 'interrupted' if episode['interrupted'] else ('unresolved' if episode['unknown'] or episode['classification'] == 'unknown' else ('closed' if episode['end'] else 'open'))
        quantity_known = not (episode_unknown or episode['quantity_unknown'] or
                              episode['interrupted'] or episode['classification'] == 'unknown')
        pnl = None if episode['unknown'] or episode['interrupted'] else episode['proceeds'] - episode['matched_basis'] - episode['exit_fees']
        basis_known = not (episode['basis_unknown'] or episode['quantity_unknown'] or episode['interrupted'])
        remaining_basis_known = not (episode['quantity_unknown'] or episode['interrupted']) and all(
            lot['basis'] is not None for lot in episode['lots'])
        sold_targets = {}
        for pct in (50, 90):
            target = D(episode['acquired']) * D(pct) / HUNDRED
            accumulated = 0
            hit = None
            for disposal in episode['disposals']:
                accumulated += disposal['quantity']
                if D(accumulated) >= target:
                    hit = disposal['timestamp']
                    break
            sold_targets[str(pct)] = canonical(_hours(episode['start'], hit)) if hit is not None else None
        rendered.append({'id': episode['id'], 'mint': episode['mint'], 'classification': episode['classification'],
                         'status': state, 'in_window': episode['end'] is None or episode['end'] >= start, 'start': episode['start'].isoformat(),
                         # Legacy status/timing fields remain observations for
                         # conditional consumers. These typed states describe
                         # strict normalized-input population dependencies.
                         'cohort_quantity_status': 'known' if quantity_known else 'unknown',
                         'monetary_status': 'unknown' if episode['unknown'] or episode['interrupted'] else 'known',
                         'first_sale_status': 'known' if quantity_known and not episode['first_sale_unknown'] else 'unknown',
                         'first_sale_observation_status': 'known' if not (episode['quantity_unknown'] or episode['interrupted'] or episode['first_sale_unknown']) else 'unknown',
                         'acquisition_basis_status': 'known' if basis_known else 'unknown',
                         'known_basis_sol': canonical(episode['basis']) if basis_known else None,
                         'known_matched_basis_sol': canonical(episode['matched_basis']) if basis_known else None,
                         'remaining_basis_status': 'known' if remaining_basis_known else 'unknown',
                         'remaining_basis_sol': canonical(sum((lot['basis'] for lot in episode['lots']), ZERO)) if remaining_basis_known else None,
                         'end': episode['end'].isoformat() if episode['end'] else None,
                         'start_order': episode['start_order'], 'end_order': episode['end_order'],
                         'remaining_lots': [{'quantity_raw': str(lot['quantity']),
                             'basis_sol': canonical(lot['basis']), 'basis_status': 'known' if lot['basis'] is not None else 'unknown',
                             'acquisition': {'signature': lot.get('signature'), 'evidence': lot.get('evidence', []),
                                 'timestamp': lot['timestamp'].isoformat() if lot['timestamp'] is not None else None,
                                 'order': lot.get('order'), 'quantity_raw': str(lot.get('acquisition_quantity', lot['quantity']))}}
                             for lot in episode['lots']],
                         'quantity_raw': str(episode['quantity']), 'acquired_raw': str(episode['acquired']),
                         'sold_raw': str(episode['sold']), 'decimals': episode['decimals'],
                         'buy_count': episode['buy_count'], 'sell_count': episode['sell_count'],
                         'basis_sol': None if episode['unknown'] else canonical(episode['basis']),
                         'matched_basis_sol': None if episode['unknown'] else canonical(episode['matched_basis']),
                         'proceeds_sol': canonical(episode['proceeds']), 'exit_fees_sol': canonical(episode['exit_fees']),
                         'pnl_sol': canonical(pnl), 'roi_pct': canonical(pnl / episode['matched_basis'] * HUNDRED) if pnl is not None and episode['matched_basis'] > ZERO else None,
                         'hold_hours': canonical(_hours(episode['start'], episode['end'])) if episode['end'] else None,
                         'first_sale_hours': canonical(_hours(episode['start'], episode['first_sale'])) if episode['first_sale'] else None,
                         'sold_50_pct_hours': sold_targets['50'], 'sold_90_pct_hours': sold_targets['90'],
                         'evidence': sorted(episode['evidence'])})
    counts = {key: sum(p['status'] == key and p['in_window'] for p in rendered) for key in ('closed', 'open', 'interrupted', 'unresolved')}
    metric_coverage = {key: {**intervals['four_weeks' if key == 'positive_weeks' else 'verification_90d' if key == 'completed_positions_90d' else 'report_period'],
                             'metric_status': metric['status']} for key, metric in metrics.items()}
    return {'metrics': metrics, 'positions': rendered, 'counts': counts, 'findings': findings,
            'counts_population': 'Episodes open or closing within the reporting window; earlier closed episodes remain visible for verification.',
            'weekly': list(reversed(weeks)), 'known_realised_profit_sol': canonical(known_net - known_overhead),
            'unallocated_overhead_sol': canonical(known_overhead),
            'metric_intervals': intervals, 'metric_coverage': metric_coverage,
            'metric_domains': metric_domains, 'metric_domain_methodology': METHODOLOGY,
            'notes': ['Analytical FIFO; strict-zero closes; raw mint identities; half-open UTC window.',
                      'A reconciled ledger does not establish historical account ownership completeness.',
                      'Unknown eligible episodes remain visible and block affected populations.',
                      'Missing acquisition money does not revoke independently supported quantity or holding populations.']}


def evaluate_policy(metrics, preset, evidence_verified=False):
    """Tri-state policy: any known FAIL wins; MATCH requires every gate and rule.

    evidence_verified may be True after an independent certificate, False, or a
    dict of gate names with PASS/FAIL/UNKNOWN. No financial headline bypasses gates.
    """
    checks = []
    gate_names = ('history', 'identity', 'basis', 'positions', 'fees', 'classification', 'valuation', 'findings')
    for name in gate_names:
        state = ('PASS' if evidence_verified else 'UNKNOWN') if isinstance(evidence_verified, bool) else evidence_verified.get(name, 'UNKNOWN')
        if state not in ('PASS', 'FAIL', 'UNKNOWN'):
            raise ValueError('Invalid evidence gate state')
        checks.append({'key': f'evidence_{name}', 'label': f'{name.title()} evidence', 'state': state,
                       'actual': None, 'expected': 'Verified',
                       'reason': 'Evidence gate verified' if state == 'PASS' else 'Independent coverage and review required'})
    rules = [
        ('profit_sol', 'Net realised profit', 'min_profit_sol', None),
        ('realised_roi_pct', 'Realised ROI', 'min_realised_roi_pct', None),
        ('median_roi_pct', 'Median episode ROI', 'min_median_roi_pct', None),
        ('win_rate_pct', 'Position win rate', 'min_win_rate_pct', 'max_win_rate_pct'),
        ('median_hold_hours', 'Median completed hold', 'min_hold_hours', 'max_hold_hours'),
        ('completed_positions', 'Completed positions', 'min_positions', None),
        ('completed_positions_90d', 'Completed positions in 90 days', 'min_positions_90d', None),
        ('traded_mints', 'Traded meme mints', 'min_mints', 'max_mints'),
        ('rapid_sale_pct', 'Rapid first-sale share', None, 'max_rapid_sale_pct'),
        ('avg_buys', 'Average buys per episode', 'min_avg_buys', 'max_avg_buys'),
        ('avg_sells', 'Average sells per episode', 'min_avg_sells', 'max_avg_sells'),
        ('positive_weeks', 'Positive weeks', 'min_positive_weeks', None),
        ('largest_contribution_pct', 'Largest token contribution', None, 'max_contribution_pct'),
    ]
    with localcontext() as ctx:
        ctx.prec = 192
        for key, label, lower_key, upper_key in rules:
            item = metrics.get(key, {})
            actual = item.get('value')
            lower = _threshold(preset[lower_key]) if lower_key else None
            upper = _threshold(preset[upper_key]) if upper_key else None
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f'Impossible threshold range for {key}')
            expected = f'>= {canonical(lower)}' if upper is None else f'<= {canonical(upper)}' if lower is None else f'{canonical(lower)} to {canonical(upper)}'
            if actual is None or item.get('status', 'known') != 'known':
                state = 'UNKNOWN'
                reason = item.get('reason') or 'Metric unresolved'
            else:
                value = decimal(actual, signed=True, max_length=512)
                state = 'PASS' if (lower is None or value >= lower) and (upper is None or value <= upper) else 'FAIL'
                reason = 'Within preset' if state == 'PASS' else 'Outside preset; a preference mismatch'
            checks.append({'key': key, 'label': label, 'state': state, 'actual': actual, 'expected': expected, 'reason': reason})
        if preset.get('require_positive_economic_pnl', True):
            item = metrics.get('economic_pnl_sol', {})
            value = item.get('value')
            state = 'UNKNOWN' if value is None or item.get('status', 'known') != 'known' else ('PASS' if decimal(value, signed=True, max_length=512) > ZERO else 'FAIL')
            checks.append({'key': 'economic_pnl_sol', 'label': 'Positive economic change', 'state': state,
                           'actual': value, 'expected': '> 0', 'reason': item.get('reason') if state == 'UNKNOWN' else 'Boundary equity and external flows considered'})
    states = {item['state'] for item in checks}
    return {'policy': 'MISS' if 'FAIL' in states else ('UNRESOLVED' if 'UNKNOWN' in states else 'MATCH'), 'checks': checks}


def _threshold(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return D(value)
    return decimal(value)
