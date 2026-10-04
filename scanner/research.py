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
VERSION = 'supported-subset-research-v3-native-roles'


def summarize_research(events, start, end, *, history_complete=False,
                       opening_inventory=None, findings=None, wallet_evidence=None):
    """Return evidence-linked observations; never certify copy execution or safety."""
    if not isinstance(history_complete, bool):
        raise ValueError('history_complete must be boolean')
    with localcontext() as context:
        context.prec = 192
        return _summarize(events, utc(start), utc(end), history_complete,
                          opening_inventory or {}, findings or [], wallet_evidence)


def _summarize(events, start, end, history_complete, anchors, supplied_findings, wallet_evidence):
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
    # A missing role remains compatible with legacy event-only models. An
    # explicit unsupported or malformed role is never a proved capital role.
    cash_gaps = [row for row in ordered if row[3].get('kind') == 'capital'
                 and 'economic_role' in row[3]
                 and row[3]['economic_role'] != 'administration']
    cash_keys = {(row[3]['signature'], row[0]) for row in cash_gaps
                 if isinstance(row[3].get('signature'), str)}
    period_cash_gap = any(when >= start for when, _, _, _ in cash_gaps)
    from .wallet_evidence import VERSION as WALLET_VERSION
    receipt_valid = (isinstance(wallet_evidence, dict) and wallet_evidence.get('version') == WALLET_VERSION
                     and isinstance(wallet_evidence.get('transactions'), dict))
    # A fresh raw-derived scoped receipt can prove one episode independent of
    # an unrelated missing timestamp. The global population and aggregate
    # chronology remain unresolved. Legacy event-only models cannot prove that
    # separation and retain their existing global conservatism.

    def source_check(event, key):
        if wallet_evidence is None:
            return True  # Legacy event-only development models remain supported.
        signature = event.get('signature')
        row = wallet_evidence['transactions'].get(signature) if receipt_valid and isinstance(signature, str) else None
        checks = row.get('checks') if isinstance(row, dict) else None
        receipt = checks.get(key) if isinstance(checks, dict) else None
        return isinstance(receipt, dict) and receipt.get('state') == 'PASS'

    def physical_known(event):
        if wallet_evidence is None:
            return True
        signature, mint = event.get('signature'), event.get('mint')
        row = wallet_evidence['transactions'].get(signature) if receipt_valid and isinstance(signature, str) else None
        aggregates = row.get('mint_aggregates') if isinstance(row, dict) else None
        aggregate = aggregates.get(mint) if isinstance(aggregates, dict) and isinstance(mint, str) else None
        receipt = aggregate.get('check') if isinstance(aggregate, dict) else None
        return isinstance(receipt, dict) and receipt.get('state') == 'PASS'

    def money_known(event, when):
        state = event.get('native_cash_role_state', 'PASS')
        signature = event.get('signature')
        no_cash_gap = not isinstance(signature, str) or (signature, when) not in cash_keys
        return (isinstance(state, str) and state == 'PASS' and no_cash_gap
                and event.get('amount_sol') is not None
                and (event.get('paid_by_wallet', True) is False or event.get('fee_sol', '0') is not None)
                and source_check(event, 'identity') and source_check(event, 'cost_roles')
                and source_check(event, 'clock') and fee_known(event) and physical_known(event))

    def fee_known(event):
        if wallet_evidence is None:
            return True
        signature = event.get('signature')
        row = wallet_evidence['transactions'].get(signature) if receipt_valid and isinstance(signature, str) else None
        fee = row.get('network_fee') if isinstance(row, dict) else None
        receipt = fee.get('check') if isinstance(fee, dict) else None
        try:
            raw_quantity(fee.get('lamports'))
        except (ValueError, TypeError, AttributeError):
            return False
        return isinstance(receipt, dict) and receipt.get('state') == 'PASS'

    # The producer appends one projection receipt in transaction insertion
    # order. Consume those existing interval proofs, including transactions
    # whose selected timestamp is outside the period but has an in-period
    # linked possibility. Exact time is not required for a known fee sum.
    period_fee_total, period_fee_unknown = ZERO, False
    period_memberships = {}
    if wallet_evidence is not None:
        intervals = wallet_evidence.get('intervals') if receipt_valid else None
        period = intervals.get('report_period') if isinstance(intervals, dict) else None
        period_memberships = period.get('selected_record_membership') if isinstance(period, dict) else None
        projections = wallet_evidence.get('fee_projection_checks') if receipt_valid else None
        if not (isinstance(period_memberships, dict) and isinstance(projections, list)
                and len(projections) == len(wallet_evidence['transactions'])):
            period_fee_unknown = True
            period_memberships = {}
        else:
            for (signature, row), projection in zip(wallet_evidence['transactions'].items(), projections):
                fee = row.get('network_fee') if isinstance(row, dict) else None
                check = fee.get('check') if isinstance(fee, dict) else None
                try:
                    lamports = raw_quantity(fee.get('lamports'))
                    native_known = isinstance(check, dict) and check.get('state') == 'PASS'
                except (ValueError, TypeError, AttributeError):
                    lamports, native_known = None, False
                if native_known and lamports == 0:
                    continue  # Independently proved zero survives every placement.
                membership = period_memberships.get(signature)
                if not (isinstance(projection, dict) and projection.get('state') == 'PASS'
                        and isinstance(membership, dict) and membership.get('state') == 'PASS'
                        and isinstance(membership.get('member'), bool)):
                    period_fee_unknown = True
                elif membership['member']:
                    if native_known:
                        period_fee_total += D(lamports) / D(1_000_000_000)
                    else:
                        period_fee_unknown = True

    def fee_in_period(event, selected_membership):
        if wallet_evidence is None:
            return selected_membership
        membership = period_memberships.get(event.get('signature'))
        return isinstance(membership, dict) and membership.get('state') == 'PASS' and membership.get('member') is True

    # Episode references are attached to the existing lot-consumption loop.
    # No timestamp-only matching or separate quantity/accounting engine is used.
    episode_ordinals, active_episodes, episode_roles = defaultdict(int), {}, {}
    ties = defaultdict(list)
    for row in ordered:
        if row[3].get('kind') in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            ties[(row[0], row[3].get('mint'))].append(row)
    if any(len(rows) > 1 and (any('order' not in row[3] for row in rows) or
                              len({row[1] for row in rows}) != len(rows)) for rows in ties.values()):
        chronology_unknown = True
    scoped_chronology_available = not chronology_unknown or receipt_valid

    # Reuse the one existing private FIFO analysis, then bind its episode to
    # the fresh named-account proof by raw dependencies and exact episode
    # quantities/bounds. Global position IDs differ between decoder views.
    generic_events = []
    for event in source_events:
        copied = dict(event)
        if copied.get('kind') in ('buy', 'sell', 'transfer_in', 'transfer_out'):
            copied['classification'] = 'meme'  # Private generic population only.
        generic_events.append(copied)
    accounting = analyze(generic_events, start.isoformat(), end.isoformat(), history_complete=False)
    query = wallet_evidence.get('query_accounting') if receipt_valid else None
    inspection = query.get('selected_lot_inspection') if isinstance(query, dict) else None
    supported_lots = query.get('supported_selected_lots') if isinstance(query, dict) else None
    proofs = supported_lots if (isinstance(inspection, dict) and inspection.get('state') == 'PASS'
                               and isinstance(supported_lots, list)) else []
    proof_index = defaultdict(list)
    for proof in proofs:
        if not isinstance(proof, dict):
            continue
        bounds = proof.get('fifo_bounds')
        if not (isinstance(bounds, dict) and all(isinstance(proof.get(k), str) for k in ('mint', 'acquired_raw', 'disposed_raw', 'remaining_raw'))
                and isinstance(bounds.get('start'), str) and (bounds.get('end') is None or isinstance(bounds.get('end'), str))
                and type(proof.get('buy_count')) is int and type(proof.get('sell_count')) is int):
            continue
        key = (proof['mint'], bounds['start'], bounds.get('end'), proof['acquired_raw'], proof['disposed_raw'],
               proof['remaining_raw'], proof['buy_count'], proof['sell_count'])
        proof_index[key].append(proof)
    position_support, position_ordinals = {}, defaultdict(int)
    for position in accounting['positions']:
        mint = position['mint']; position_ordinals[mint] += 1
        evidence = set(position.get('evidence', []))
        matches = []
        key = (mint, position['start'], position['end'], position['acquired_raw'], position['sold_raw'],
               position['quantity_raw'], position['buy_count'], position['sell_count'])
        for proof in proof_index.get(key, []):
            proof_hashes = proof.get('evidence')
            signatures = proof.get('required_signatures')
            if not (isinstance(proof_hashes, list) and all(isinstance(h, str) for h in proof_hashes)
                    and evidence and evidence <= set(proof_hashes)
                    and isinstance(signatures, list) and all(isinstance(s, str) and s for s in signatures)):
                continue
            matches.append(proof)
        position_support[(mint, position_ordinals[mint])] = matches[0] if len(matches) == 1 else None

    def episode_support(key, field, event):
        if wallet_evidence is None:
            return True
        proof = position_support.get(key)
        signature = event.get('signature')
        return (isinstance(proof, dict) and proof.get(field) == 'PASS' and isinstance(signature, str)
                and signature in proof.get('required_signatures', []))

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
    missing_fee = period_fee_unknown
    asset_gaps = sum(event.get('kind') == 'unsupported' for _, _, _, event in ordered)
    trade_gaps = sum(event.get('kind') in ('buy', 'sell') and not money_known(event, when)
                    and (not isinstance(event.get('signature'), str) or (event['signature'], when) not in cash_keys)
                    for when, _, _, event in ordered)
    unknown_transactions = asset_gaps + len(cash_gaps) + trade_gaps
    sale_details = []
    for when, _, event_index, event in ordered:
        kind = event.get('kind')
        paid = event.get('paid_by_wallet', True)
        if not isinstance(paid, bool):
            raise ValueError('paid_by_wallet must be boolean')
        in_window = start <= when
        if kind == 'fee':
            projected_in_window = fee_in_period(event, in_window)
            if projected_in_window and not fee_known(event):
                missing_fee = True
            amount = decimal(event['amount_sol']) if event.get('amount_sol') is not None else None
            if event_index in fee_allocations:
                # Keep the original fee observation visible. Its validated trade
                # already carries this exact cost into FIFO basis or sale costs.
                continue
            if paid and projected_in_window:
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
        if mint not in active_episodes:
            episode_ordinals[mint] += 1
            active_episodes[mint] = (mint, episode_ordinals[mint])
            episode_roles[active_episodes[mint]] = {'buy_unknown': False, 'sell_unknown': False, 'timing_unknown': False, 'quantity_unknown': False}
        role = episode_roles[active_episodes[mint]]
        if not physical_known(event) or not source_check(event, 'identity') or not episode_support(active_episodes[mint], 'quantity_state', event):
            role['quantity_unknown'] = True
        scoped_origin = episode_support(active_episodes[mint], 'origin_state', event)
        scoped_clocks = episode_support(active_episodes[mint], 'chronology_state', event)
        if not source_check(event, 'clock') or role['quantity_unknown'] or not scoped_origin or not scoped_clocks:
            role['timing_unknown'] = True
        price_supported = money_known(event, when) and scoped_origin and scoped_clocks and not role['quantity_unknown']
        if kind in ('buy', 'sell') and not price_supported:
            role[kind + '_unknown'] = True
        fee = decimal(event['fee_sol']) if event.get('fee_sol') is not None else (ZERO if 'fee_sol' not in event else None)
        if not paid:
            fee = ZERO
        if fee_in_period(event, in_window) and kind in ('buy', 'sell'):
            if fee is None or not fee_known(event):
                missing_fee = True
            else:
                wallet_fees += fee
        if kind in ('transfer_in', 'transfer_out'):
            trusted_mints.discard(mint)
            for lot in lots[mint]:
                lot['verified'] = False
        if kind in ('buy', 'transfer_in'):
            amount = decimal(event['amount_sol']) if kind == 'buy' and event.get('amount_sol') is not None and price_supported else None
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
        if not lots[mint]:
            active_episodes.pop(mint, None)
        if kind == 'transfer_out':
            continue
        proceeds = decimal(event['amount_sol']) if event.get('amount_sol') is not None and price_supported else None
        net = proceeds - basis - fee if matched and proceeds is not None and fee is not None else None
        if not in_window:
            continue
        sales += 1
        attributable = net is not None and verified and scoped_chronology_available
        if net is not None and scoped_chronology_available:
            conditional_matches += 1
            conditional_net += net
        if attributable:
            verified_matches += 1
            verified_net += net
        sale_details.append({'mint': mint, 'timestamp': when.isoformat(), 'quantity_raw': str(quantity),
                             'conditional_matched_basis_sol': canonical(basis) if matched else None,
                             'conditional_profit_sol': canonical(net) if scoped_chronology_available else None,
                             'attributable': attributable, 'evidence': event.get('evidence', []),
                             'reason': 'Independent opening inventory and intervening flows verified' if attributable else
                                       'Earlier inventory or unmatched cost remains unresolved; observed-lot model only'})
    if wallet_evidence is not None:
        wallet_fees = period_fee_total
    conditional_profit = conditional_net - overhead if conditional_matches and not missing_fee and not chronology_unknown and not period_cash_gap else None
    known_matched = verified_net if verified_matches else None
    observed_profit = verified_net - overhead if sales and verified_matches == sales and not missing_fee and not global_gap and not gap_mints and not chronology_unknown and not period_cash_gap else None

    # The already-computed accounting engine supplies observed episode quantities.
    episodes = []
    rendered_ordinals = defaultdict(int)
    for position in accounting['positions']:
        rendered_ordinals[position['mint']] += 1
        role = episode_roles.get((position['mint'], rendered_ordinals[position['mint']]))
        if role is None:
            role = {'buy_unknown': True, 'sell_unknown': True, 'timing_unknown': True, 'quantity_unknown': True}
        if not position['in_window']:
            continue
        money_supported = (not (role['buy_unknown'] or role['sell_unknown'] or role['timing_unknown'])
                           and position['status'] == 'closed'
                           and all(position.get(key) is not None for key in ('basis_sol', 'matched_basis_sol', 'proceeds_sol', 'pnl_sol')))
        attributable = position['mint'] in trusted_mints and position['status'] == 'closed' and scoped_chronology_available and money_supported
        observation = dict(position)
        observation.pop('classification', None)
        observation['scope'] = 'Observed supported swaps; episode boundaries conditional on zero undiscovered inventory'
        observation['attributable'] = attributable
        observation['conditional'] = not attributable
        observation['monetary_state'] = 'PASS' if money_supported else 'UNKNOWN'
        observation['quantity_state'] = 'UNKNOWN' if role['quantity_unknown'] else 'PASS'
        observation['timing_state'] = 'PASS' if scoped_chronology_available and not role['timing_unknown'] else 'UNKNOWN'
        if role['buy_unknown'] or role['timing_unknown']:
            observation.update(basis_sol=None, matched_basis_sol=None)
        if role['sell_unknown'] or role['timing_unknown']:
            observation['proceeds_sol'] = None
        if not money_supported:
            observation.update(pnl_sol=None, roi_pct=None)
        if observation['timing_state'] == 'UNKNOWN':
            for key in ('hold_hours', 'first_sale_hours', 'sold_50_pct_hours', 'sold_90_pct_hours'):
                observation[key] = None
        observation['observed_start'] = observation.pop('start')
        observation['observed_end'] = observation.pop('end')
        episodes.append(observation)
    closed = [p for p in episodes if p['status'] == 'closed']
    usable = closed if not chronology_unknown and all(p['timing_state'] == 'PASS' for p in closed) else []

    def typical(key):
        values = [decimal(p[key], signed=True, max_length=512) for p in usable if p.get(key) is not None]
        return canonical(median(values))

    rapid = sum(decimal(p['first_sale_hours'], max_length=512) <= D(1) / D(12) for p in usable if p.get('first_sale_hours') is not None)
    rapid_pct = canonical(D(rapid) / D(len(usable)) * D(100)) if usable else None
    unresolved_basis = sales - verified_matches
    risk_findings.append({'severity': 'warning', 'title': 'Opening inventory is not inferred from fetched buys',
                          'detail': 'A sampled purchase does not prove zero earlier inventory across every wallet-owned account. Profit and strategy timings are conditional unless an independent opening anchor and complete flows establish the episode.',
                          'evidence': sorted(hashes)})
    if asset_gaps or chronology_unknown:
        risk_findings.append({'severity': 'warning', 'title': 'Unresolved activity can interrupt observed episodes',
                              'detail': 'Unsupported routes, missing chronology or transfers may change FIFO basis and episode boundaries.',
                              'evidence': sorted(hashes)})
    if cash_gaps or trade_gaps:
        risk_findings.append({'severity': 'warning', 'title': 'Native monetary roles remain unresolved',
            'detail': 'Unknown cash movements or linked cost/identity/clock dependencies revoke affected monetary results. Independently supported quantities, timings and network fees remain separate.',
            'evidence': sorted(hashes)})
    limits = [
        'Research covers supported SOL-settled spot swaps in the fetched subset, not complete wallet P&L or strict meme-policy qualification.',
        'Conditional observed-lot profit assumes no earlier undiscovered holdings or intervening asset flows. Sales without matched fetched basis are excluded and counted explicitly.',
        'Episode duration, first sale and 50%/90% exits describe fetched observed quantities; undiscovered acquisitions or transfers may change those boundaries.',
        'Wallet-paid buy fees enter FIFO basis, including purchases before the window; only disposed units consume that basis. Exit fees are deducted once. Validated original fee display events are not counted again; unallocated fees remain period overhead and sponsored fees are excluded.',
        'Current token controls and liquidity observations cannot establish historical execution, copy-trade fill prices, legitimacy or future returns.',
    ]
    return {'version': VERSION, 'scope': 'supported spot swaps in fetched subset',
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
            'scoped_chronology_unknown': any(role['timing_unknown'] for role in episode_roles.values()),
            'episodes': episodes, 'sales_detail': sale_details, 'evidence': sorted(hashes),
            'risk_findings': risk_findings, 'limitations': limits}
