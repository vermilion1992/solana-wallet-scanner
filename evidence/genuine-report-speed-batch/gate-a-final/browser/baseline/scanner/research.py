"""Conditional strategy observations for supported broad-token spot swaps.

This is a second, explicitly scoped view, separate from strict meme policy. The
FIFO implementation is reused on PRIVATE copies with a generic asset population;
this never changes source classifications or emits a policy MATCH. Fetched buys
alone do not prove zero earlier wallet inventory. Default profitability is null.

`conditional_observed_lot_profit_sol` models only sales fully matched to fetched
purchase lots, less wallet-paid fees, assuming no undiscovered earlier inventory
or intervening flows. It excludes sales whose observed basis cannot be matched and
is not whole-wallet P&L. Its explicit counts and limitations accompany the number.
An independent opening anchor can establish an attributable subset:
 opening_inventory[mint] = {quantity_raw:'0', timestamp:UTC time, evidence:[hashes],
   scope:'wallet_owned_mint', verified:True, intervening_flows_complete:True}
The anchor must cover ALL wallet-owned accounts for the mint and all intervening
flows, not just a route account's pre-token balance or today's account enumeration.
The app does not manufacture these certificates from a sampled transaction.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from copy import deepcopy

from .accounting import analyze, canonical, decimal, raw_quantity, utc, median, validate_fee_allocations

D = Decimal
ZERO = D('0')


def summarize_research(events, start, end, *, history_complete=False,
                       opening_inventory=None, findings=None):
    """Return evidence-linked observations; never certify copy execution or safety."""
    if not isinstance(history_complete, bool):
        raise ValueError('history_complete must be boolean')
    with localcontext() as context:
        context.prec = 192
        return _summarize(events, utc(start), utc(end), history_complete,
                          opening_inventory or {}, findings or [])


def _summarize(events, start, end, history_complete, anchors, supplied_findings):
    if end <= start:
        raise ValueError('Reporting window must have positive duration')
    if not isinstance(anchors, dict):
        raise ValueError('opening_inventory must be a mint-keyed object')
    source_events = deepcopy(list(events))
    fee_allocations = validate_fee_allocations(source_events)
    risk_findings = [dict(item) for item in supplied_findings]
    ordered = []
    chronology_unknown = False
    gap_mints = set()
    global_gap = False
    hashes = set()
    supported_swaps = 0
    for index, event in enumerate(source_events):
        event_hashes = event.get('evidence') or []
        if not isinstance(event_hashes, list) or any(not isinstance(item, str) for item in event_hashes):
            raise ValueError('Evidence must be a list of hashes')
        hashes.update(event_hashes)
        try:
            when = utc(event.get('timestamp'))
        except (ValueError, TypeError, OverflowError):
            chronology_unknown = global_gap = True
            continue
        if when >= end:
            continue
        order = event.get('order', index)
        if not isinstance(order, int) or isinstance(order, bool):
            raise ValueError('Event order must be an integer')
        ordered.append((when, order, index, event))
        if event.get('kind') in ('buy', 'sell') and start <= when:
            supported_swaps += 1
        if event.get('kind') == 'unsupported':
            if event.get('mint'):
                gap_mints.add(event['mint'])
            else:
                global_gap = True
    ordered.sort(key=lambda row: row[:3])
    ties = defaultdict(list)
    for row in ordered:
        if row[3].get('kind') in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            ties[(row[0], row[3].get('mint'))].append(row)
    if any(len(rows) > 1 and (any('order' not in row[3] for row in rows) or
                              len({row[1] for row in rows}) != len(rows)) for rows in ties.values()):
        chronology_unknown = True

    trusted_mints = set()
    for mint, anchor in anchors.items():
        if not isinstance(anchor, dict):
            raise ValueError('Invalid opening inventory anchor')
        quantity = raw_quantity(anchor.get('quantity_raw'))
        anchor_time = utc(anchor.get('timestamp'))
        provenance = anchor.get('evidence')
        first = next((when for when, _, _, event in ordered if event.get('mint') == mint and
                      event.get('kind') in ('buy', 'sell', 'transfer_in', 'transfer_out')), None)
        eligible = (quantity == 0 and anchor.get('scope') == 'wallet_owned_mint' and
                    anchor.get('verified') is True and anchor.get('intervening_flows_complete') is True and
                    isinstance(provenance, list) and bool(provenance) and
                    all(isinstance(item, str) and item for item in provenance) and
                    first is not None and anchor_time <= first and
                    not global_gap and mint not in gap_mints and not chronology_unknown)
        if eligible:
            trusted_mints.add(mint)
            hashes.update(provenance)
        else:
            risk_findings.append({'severity': 'warning', 'title': 'Opening inventory anchor insufficient',
                                  'detail': f'{mint}: scoped zero inventory and complete intervening flows are not established.',
                                  'evidence': provenance if isinstance(provenance, list) else []})

    lots = defaultdict(list)
    conditional_net = ZERO
    verified_net = ZERO
    conditional_matches = verified_matches = sales = 0
    overhead = ZERO
    wallet_fees = ZERO
    missing_fee = False
    unknown_transactions = sum(event.get('kind') == 'unsupported' for _, _, _, event in ordered)
    sale_details = []
    for when, _, event_index, event in ordered:
        kind = event.get('kind')
        paid = event.get('paid_by_wallet', True)
        if not isinstance(paid, bool):
            raise ValueError('paid_by_wallet must be boolean')
        in_window = start <= when
        if kind == 'fee':
            amount = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
            if event_index in fee_allocations:
                # Keep the original fee observation visible. Its validated trade
                # already carries this exact cost into FIFO basis or sale costs.
                continue
            if paid and in_window:
                if amount is None:
                    missing_fee = True
                else:
                    overhead += amount
                    wallet_fees += amount
            continue
        if kind not in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            continue
        mint = event.get('mint')
        if not isinstance(mint, str) or not mint:
            raise ValueError('Asset events require real mint identities')
        quantity = raw_quantity(event.get('quantity_raw'))
        if not quantity:
            raise ValueError('Swap quantities must be positive')
        fee = decimal(event['fee_sol']) if event.get('fee_sol') is not None else (ZERO if 'fee_sol' not in event else None)
        if not paid:
            fee = ZERO
        if in_window and kind in ('buy', 'sell'):
            if fee is None:
                missing_fee = True
            else:
                wallet_fees += fee
        if kind in ('transfer_in', 'transfer_out'):
            trusted_mints.discard(mint)
            for lot in lots[mint]:
                lot['verified'] = False
        if kind in ('buy', 'transfer_in'):
            amount = decimal(event['amount_sol']) if kind == 'buy' and event.get('amount_sol') is not None else None
            basis = amount + fee if amount is not None and fee is not None else None
            lots[mint].append({'quantity': quantity, 'basis': basis,
                               'verified': mint in trusted_mints and basis is not None})
            continue
        available = sum(lot['quantity'] for lot in lots[mint])
        if available < quantity:
            lots[mint].insert(0, {'quantity': quantity - available, 'basis': None, 'verified': False})
            # A sale larger than the anchored balance contradicts the certificate.
            trusted_mints.discard(mint)
            for lot in lots[mint]:
                lot['verified'] = False
        remaining = quantity
        basis = ZERO
        matched = True
        verified = True
        while remaining:
            lot = lots[mint][0]
            take = min(remaining, lot['quantity'])
            if lot['basis'] is None:
                matched = False
            else:
                part = lot['basis'] if take == lot['quantity'] else lot['basis'] * D(take) / D(lot['quantity'])
                basis += part
                lot['basis'] -= part
            verified = verified and lot['verified']
            remaining -= take
            lot['quantity'] -= take
            if lot['quantity'] == 0:
                lots[mint].pop(0)
        if kind == 'transfer_out':
            continue
        proceeds = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
        net = proceeds - basis - fee if matched and proceeds is not None and fee is not None else None
        if not in_window:
            continue
        sales += 1
        attributable = net is not None and verified and not chronology_unknown
        if net is not None and not chronology_unknown:
            conditional_matches += 1
            conditional_net += net
        if attributable:
            verified_matches += 1
            verified_net += net
        sale_details.append({'mint': mint, 'timestamp': when.isoformat(), 'quantity_raw': str(quantity),
                             'conditional_matched_basis_sol': canonical(basis) if matched else None,
                             'conditional_profit_sol': canonical(net) if not chronology_unknown else None,
                             'attributable': attributable, 'evidence': event.get('evidence', []),
                             'reason': 'Independent opening inventory and intervening flows verified' if attributable else
                                       'Earlier inventory or unmatched cost remains unresolved; observed-lot model only'})
    conditional_profit = conditional_net - overhead if conditional_matches and not missing_fee and not chronology_unknown else None
    known_matched = verified_net if verified_matches else None
    observed_profit = verified_net - overhead if sales and verified_matches == sales and not missing_fee and not global_gap and not gap_mints and not chronology_unknown else None

    # The accounting engine supplies observed episode quantities, not classification.
    generic_events = []
    for event in source_events:
        copied = dict(event)
        if copied.get('kind') in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            copied['classification'] = 'meme'  # Private generic population only.
        generic_events.append(copied)
    accounting = analyze(generic_events, start.isoformat(), end.isoformat(), history_complete=False)
    episodes = []
    for position in accounting['positions']:
        if not position['in_window']:
            continue
        attributable = position['mint'] in trusted_mints and position['status'] == 'closed' and not chronology_unknown
        observation = dict(position)
        observation.pop('classification', None)
        observation['scope'] = 'Observed supported swaps; episode boundaries conditional on zero undiscovered inventory'
        observation['attributable'] = attributable
        observation['conditional'] = not attributable
        observation['observed_start'] = observation.pop('start')
        observation['observed_end'] = observation.pop('end')
        episodes.append(observation)
    closed = [p for p in episodes if p['status'] == 'closed']
    usable = closed if not chronology_unknown else []

    def typical(key):
        values = [decimal(p[key], signed=True, max_length=512) for p in usable if p.get(key) is not None]
        return canonical(median(values))

    rapid = sum(decimal(p['first_sale_hours'], max_length=512) <= D(1) / D(12) for p in usable if p.get('first_sale_hours') is not None)
    rapid_pct = canonical(D(rapid) / D(len(usable)) * D(100)) if usable else None
    unresolved_basis = sales - verified_matches
    risk_findings.append({'severity': 'warning', 'title': 'Opening inventory is not inferred from fetched buys',
                          'detail': 'A sampled purchase does not prove zero earlier inventory across every wallet-owned account. Profit and strategy timings are conditional unless an independent opening anchor and complete flows establish the episode.',
                          'evidence': sorted(hashes)})
    if unknown_transactions or chronology_unknown:
        risk_findings.append({'severity': 'warning', 'title': 'Unresolved activity can interrupt observed episodes',
                              'detail': 'Unsupported routes, missing chronology or transfers may change FIFO basis and episode boundaries.',
                              'evidence': sorted(hashes)})
    limits = [
        'Research covers supported SOL-settled spot swaps in the fetched subset, not complete wallet P&L or strict meme-policy qualification.',
        'Conditional observed-lot profit assumes no earlier undiscovered holdings or intervening asset flows. Sales without matched fetched basis are excluded and counted explicitly.',
        'Episode duration, first sale and 50%/90% exits describe fetched observed quantities; undiscovered acquisitions or transfers may change those boundaries.',
        'Wallet-paid buy fees enter FIFO basis, including purchases before the window; only disposed units consume that basis. Exit fees are deducted once. Validated original fee display events are not counted again; unallocated fees remain period overhead and sponsored fees are excluded.',
        'Current token controls and liquidity observations cannot establish historical execution, copy-trade fill prices, legitimacy or future returns.',
    ]
    return {'version': 'supported-subset-research-v2', 'scope': 'supported spot swaps in fetched subset',
            'history_complete': history_complete, 'wallet_profit_verified': False,
            'opening_inventory_verified_mints': sorted(trusted_mints),
            'observed_profit_sol': canonical(observed_profit), 'known_matched_profit_sol': canonical(known_matched),
            'conditional_observed_lot_profit_sol': canonical(conditional_profit),
            'conditional_profit_population': 'In-window sales fully matched to fetched purchase lots, less supplied wallet-paid overhead; unresolved sales excluded',
            'supported_swaps': supported_swaps, 'sales': sales, 'matched_sales': verified_matches,
            'observed_matched_sales': conditional_matches, 'unresolved_basis_sales': unresolved_basis,
            'observed_unmatched_sales': sales - conditional_matches, 'closed_episodes': len(closed),
            'verified_closed_episodes': sum(p['attributable'] for p in closed),
            'strategy_population': 'Observed strict-zero episodes closing in the selected window; boundaries remain conditional on undiscovered inventory',
            'conditional_median_hold_hours': typical('hold_hours'),
            'conditional_first_sale_hours': typical('first_sale_hours'),
            'conditional_exit_50_hours': typical('sold_50_pct_hours'),
            'conditional_exit_90_hours': typical('sold_90_pct_hours'),
            'conditional_rapid_sale_pct': rapid_pct,
            'wallet_fees_paid_sol': None if missing_fee else canonical(wallet_fees),
            'unallocated_fees_sol': None if missing_fee else canonical(overhead),
            'unresolved_transactions': unknown_transactions, 'chronology_unknown': chronology_unknown,
            'episodes': episodes, 'sales_detail': sale_details, 'evidence': sorted(hashes),
            'risk_findings': risk_findings, 'limitations': limits}
