"""Source-backed recovery of individual token-account strict-zero episodes.

This quantity-only resolver uses the native collector's archived paging/ordering
receipts and the existing spot instruction layouts. It establishes a narrower
fact than a wallet position: one specifically named token account goes from zero
through supported acquisitions/disposals to a final sale at zero, with continuous
wallet ownership, quantities and chronology. Other owned accounts, hidden earlier
round trips, asset classification and whole-wallet economic coverage are outside
this fact. A known scoped hold never supplies the PDF's wallet median or a MATCH.

Native provider/collector records are the local trust boundary. Checksums establish
archive integrity, not independent mainnet authenticity. No network calls, writes,
imported completeness flags, fee amounts or market prices establish these holds.
The only genuine reviewed buy fixture has nonzero opening stock; it cannot provide
a completed episode. Synthetic tests exercise the positive reconstruction branch.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal, localcontext
from datetime import datetime, timezone
import hashlib
import json
import re

from .accounting import canonical, raw_quantity, median
from .collector import _timestamp, _valid_account
from .history_evidence import derive_history_evidence
from .investigation import (_keys, _route, PUMP, PUMP_SWAP,
                            JUPITER, RAYDIUM_AMM, RAYDIUM_CPMM, WHIRLPOOL, WSOL)
from .decoder import TOKEN_IDS, SYSTEM_ID, ASSOCIATED_ID
from .storage import EvidenceError
from .source_consistency import SOURCE_HASH_LIMIT
from .transaction_format import supported_transaction_format
from .instruction_scope import inspect_instruction, InstructionEvidenceError

VERSION = 'account-position-evidence-v12'
_HASH = re.compile(r'^[a-f0-9]{64}$')
VENUES = {PUMP, PUMP_SWAP, JUPITER, RAYDIUM_AMM, RAYDIUM_CPMM, WHIRLPOOL}
HOLD_NEEDS = ('collection', 'identity', 'source_consistency', 'opening_zero', 'chronology', 'placement', 'quantities',
              'continuity', 'strict_zero')
MAX_UNCERTAIN_EXCLUSIONS = 64
BASE_FACTS = ('source_set', 'archive_dependencies', 'native_identity', 'transaction_format', 'account_membership', 'execution')
BOUNDARY_FACTS = ('pre_quantity', 'post_quantity', 'owner', 'mint', 'decimals', 'program')


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if type(value) is int else None


def _check(known, reason, evidence=(), dependencies=()):
    return {'state': 'PASS' if known else 'UNKNOWN', 'reason': reason,
            'evidence': sorted(set(evidence)), 'dependencies': list(dependencies)}


def _placement_relation(placement, opening, closing):
    """Exclude only an archived placement envelope wholly outside the episode.

    An uncertain same-slot index spans that entire slot. Contradictory facts on
    opposite sides therefore cannot be resolved by choosing one raw/page value.
    Bounds are derived afresh by history evidence, never from caller PASS flags.
    """
    placement = placement if isinstance(placement, dict) else {}
    bounds = placement.get('slot_bounds', {})
    bounds = bounds if isinstance(bounds, dict) else {}
    lower, upper = bounds.get('min'), bounds.get('max')
    if (placement.get('unbounded') is not False or bounds.get('bounded') is not True
            or type(lower) is not int or type(upper) is not int or not 0 <= lower <= upper
            or not isinstance(opening, tuple) or type(opening[0]) is not int
            or (closing is not None and (not isinstance(closing, tuple) or type(closing[0]) is not int))):
        return 'potential', 'Available archived facts do not bound this receipt outside the native episode.'
    if upper < opening[0]:
        return 'before', 'Every archived slot placement lies before the episode opening.'
    if closing is not None and lower > closing[0]:
        return 'after', 'Every archived slot placement lies after the episode closing.'
    indices = placement.get('indices_by_slot', {})
    indices = indices if isinstance(indices, dict) else {}

    def index_bounds(slot):
        values = indices.get(str(slot), {})
        values = values if isinstance(values, dict) else {}
        first, last = values.get('min'), values.get('max')
        return (first, last) if (values.get('bounded') is True and type(first) is int
                                and type(last) is int and 0 <= first <= last) else None

    before_indices, after_indices = index_bounds(upper), index_bounds(lower)
    if upper == opening[0] and type(opening[1]) is int and before_indices is not None and before_indices[1] < opening[1]:
        return 'before', 'All possible slots/recorded same-slot indices precede the opening transaction.'
    if closing is not None and lower == closing[0] and type(closing[1]) is int and after_indices is not None and after_indices[0] > closing[1]:
        return 'after', 'All possible slots/recorded same-slot indices follow the closing transaction.'
    return 'potential', 'The archived slot/index placement envelope may intersect this account episode.'


def _balance(raw, keys, account, name):
    rows = raw['meta'].get(name)
    if not isinstance(rows, list):
        raise ValueError(f'Missing {name} ownership/quantity boundary')
    matches = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Malformed token balance evidence')
        account_index = row.get('accountIndex')
        if type(account_index) is not int or not 0 <= account_index < len(keys):
            raise ValueError('Malformed token balance account index')
        if keys[account_index] != account:
            continue
        token = row.get('uiTokenAmount')
        if not isinstance(token, dict):
            raise ValueError('Missing raw token quantity')
        amount = raw_quantity(token.get('amount'))
        decimals = token.get('decimals')
        if amount > 2**64 - 1 or type(decimals) is not int or not 0 <= decimals <= 255:
            raise ValueError('Token quantity or decimals exceed the supported integer domain')
        if not isinstance(row.get('owner'), str) or not _valid_account(row.get('mint')):
            raise ValueError('Missing event-time token owner or mint identity')
        if row.get('programId') is not None and row['programId'] not in TOKEN_IDS:
            raise ValueError('Unsupported token account program identity')
        matches.append({'quantity': amount, 'mint': row['mint'], 'owner': row['owner'],
                        'decimals': decimals, 'program_id': row.get('programId'), 'path': f'meta.{name}.{index}'})
    if len(matches) != 1:
        raise ValueError(f'Exactly one {name} boundary for this account is required')
    return matches[0]


def _quantity_point(raw, wallet, account):
    """Validate account-level exchange quantities without SOL consideration/fees."""
    from .transaction_format import instruction_view, original_instruction_paths
    original = raw
    raw = instruction_view(raw)
    if not supported_transaction_format(raw):
        raise ValueError('Transaction format is unsupported by this application')
    meta = raw.get('meta')
    transaction = raw.get('transaction')
    message = transaction.get('message') if isinstance(transaction, dict) else None
    if not isinstance(meta, dict) or 'err' not in meta or not isinstance(message, dict):
        raise ValueError('Missing explicit execution status or transaction message')
    keys = _keys(message, meta)
    if keys.count(account) != 1 or wallet not in keys:
        raise ValueError('Account/wallet identity is absent or duplicated in primary account keys')
    if meta['err'] is not None and not meta.get('preTokenBalances') and not meta.get('postTokenBalances'):
        return {'kind': 'failed', 'pre': None, 'post': None, 'mint': None,
                'decimals': None, 'program_id': None, 'paths': ['meta.err']}
    before = _balance(raw, keys, account, 'preTokenBalances')
    after = _balance(raw, keys, account, 'postTokenBalances')
    if before['owner'] != wallet or after['owner'] != wallet:
        raise ValueError('Event-time token ownership is not continuously the scoped wallet')
    if (before['mint'], before['decimals']) != (after['mint'], after['decimals']):
        raise ValueError('Account mint/decimals changed across the transaction')
    if before['program_id'] is not None and after['program_id'] is not None and before['program_id'] != after['program_id']:
        raise ValueError('Native token-program identity changed across transaction boundaries')
    if before['mint'] == WSOL:
        return None  # Native representation/settlement is not a traded-asset episode.
    point = {'pre': before['quantity'], 'post': after['quantity'], 'mint': before['mint'],
             'decimals': before['decimals'], 'program_id': before['program_id'] or after['program_id'], 'paths': [before['path'], after['path']]}
    if meta['err'] is not None:
        if point['pre'] != point['post']:
            raise ValueError('Failed transaction has inconsistent token quantity boundaries')
        return {**point, 'kind': 'failed'}
    instructions = message.get('instructions')
    if not isinstance(instructions, list):
        raise ValueError('Missing successful instruction records')
    routes, outer_views = [], []
    for index, instruction in enumerate(instructions):
        view = inspect_instruction(instruction, keys, path=f'transaction.message.instructions.{index}')
        outer_views.append(view)
        if view['program'] in VENUES:
            route = _route(instruction, keys)
            if account in route['owned_accounts']:
                if route['authority'] != wallet:
                    raise ValueError('Supported route authority differs from the scoped wallet')
                routes.append((index, route))
    if len(routes) > 1:
        raise ValueError('Multiple relevant outer exchanges need individual quantity allocation')
    route_index, route = routes[0] if routes else (None, None)
    recorded_inner = meta.get('innerInstructions')
    if route is not None and not isinstance(recorded_inner, list):
        raise ValueError('Relevant successful spot route lacks recorded inner-instruction evidence')
    if recorded_inner is not None and not isinstance(recorded_inner, list):
        raise ValueError('Recorded inner-instruction evidence is malformed')
    flat = [(index, f'transaction.message.instructions.{index}', instruction, False, outer_views[index])
            for index, instruction in enumerate(instructions)]
    seen_inner_groups = set()
    for group_index, group in enumerate(recorded_inner or []):
        if not isinstance(group, dict) or type(group.get('index')) is not int or not 0 <= group['index'] < len(instructions):
            raise ValueError('Malformed inner instruction association')
        if group['index'] in seen_inner_groups:
            raise ValueError('Duplicate inner-instruction groups cannot be treated as independent source flows')
        seen_inner_groups.add(group['index'])
        nested_instructions = group.get('instructions')
        if not isinstance(nested_instructions, list):
            raise ValueError('Inner-instruction group lacks an explicit recorded instruction list')
        for index, instruction in enumerate(nested_instructions):
            path = f'meta.innerInstructions.{group_index}.instructions.{index}'
            flat.append((group['index'], path, instruction, True, inspect_instruction(instruction, keys, path=path)))
    inward = outward = 0
    for outer, path, instruction, nested, view in flat:
        program = view['program']
        if view['non_economic']:
            point['paths'] += view['paths']
            continue
        if account not in view['references']:
            point['paths'] += view['paths']  # Retain the actual disjointness witness.
            continue
        point['paths'] += view['paths']
        if not nested and route is not None and outer == route_index:
            point['paths'].append(path)
            continue
        parsed = instruction.get('parsed')
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
        if not isinstance(info, dict):
            raise ValueError('Malformed parsed account operation')
        if program in TOKEN_IDS:
            if point['program_id'] is not None and point['program_id'] != program:
                raise ValueError('Parsed token operation conflicts with native token-program identity')
            point['program_id'] = program
            if kind in ('transfer', 'transferChecked'):
                source, destination = info.get('source'), info.get('destination')
                token = info.get('tokenAmount') if kind == 'transferChecked' else None
                amount = raw_quantity(token.get('amount') if isinstance(token, dict) else info.get('amount'))
                if amount > 2**64 - 1:
                    raise ValueError('Transfer quantity exceeds u64')
                if kind == 'transferChecked' and (not isinstance(token, dict) or
                    token.get('decimals') != before['decimals'] or type(token.get('decimals')) is not int or
                    info.get('mint') != before['mint']):
                    raise ValueError('Parsed transfer disagrees with account mint/decimals')
                if source == destination == account:
                    continue
                if amount and (route is None or outer != route_index or not nested):
                    raise ValueError('An external token transfer interrupts the supported exchange episode')
                inward += amount if destination == account else 0
                outward += amount if source == account else 0
                point['paths'].append(path)
            elif kind in ('approve', 'approveChecked', 'revoke', 'getAccountDataSize'):
                point['paths'].append(path)  # Known no-quantity permission/read operations.
            else:
                raise InstructionEvidenceError('Token ownership, mint/burn, closure or extension operation needs separate reconstruction',
                                               view['paths'] + [path + '.parsed.type', path + '.parsed.info'])
        elif program == SYSTEM_ID and kind == 'transfer':
            point['paths'].append(path)  # Non-wSOL account rent/lamports do not change this token quantity.
        elif program == ASSOCIATED_ID and kind in ('create', 'createIdempotent') and info.get('wallet') == wallet and info.get('mint') == before['mint']:
            point['paths'].append(path)
        else:
            raise ValueError('An opaque account operation prevents quantity/episode reconstruction')
    delta = point['post'] - point['pre']
    if inward - outward != delta:
        raise ValueError('Primary account balance change does not reconcile to parsed route transfers')
    if inward and outward:
        raise ValueError('Opposing account movements require separate economic episodes; netting is insufficient')
    point['paths'] = original_instruction_paths(original, point['paths'])
    if delta:
        if route is None:
            raise ValueError('A quantity change lacks a supported economic exchange instruction')
        kind = 'buy' if delta > 0 else 'sell'
        if route['expected_kind'] is not None and route['expected_kind'] != kind:
            raise ValueError('Spot instruction direction disagrees with the primary account quantity change')
        return {**point, 'kind': kind}
    return {**point, 'kind': 'unchanged'}


def derive_position_evidence(store, address, window, checkpoint=None, collected=None, *, history_evidence=None):
    """Read archived sources only; caller `history_evidence` never supplies PASS.

    Recompute current account-specific chronology receipts from Store so stale, removed or forged
    certificates cannot preserve a known hold. This also makes frozen rebuilds
    reproduce their dependencies. Recovery actions are plans, never RPC dispatches.
    """
    collected = collected if isinstance(collected, dict) else {}
    history = derive_history_evidence(store, address, window, checkpoint=checkpoint, collected=collected)
    consistency_table = history.get('source_consistency', {})
    consistency_table = consistency_table if isinstance(consistency_table, dict) else {}
    history_source_set = history.get('source_set', consistency_table.get('source_set', {}))
    history_source_set = history_source_set if isinstance(history_source_set, dict) else {}
    start, end = _timestamp(window['start']), _timestamp(window['end'])
    cp = checkpoint if isinstance(checkpoint, dict) else (collected or {}).get('checkpoint', {})
    cp = cp if isinstance(cp, dict) else {}
    if not cp:
        identifier = hashlib.sha256(f'{address}:{start}:{end}'.encode()).hexdigest()
        persisted = store.get('collector_checkpoints', identifier)
        cp = persisted if isinstance(persisted, dict) else {}
    selected = (collected or {}).get('transactions')
    if not isinstance(selected, list):
        selected = list(cp.get('transactions', {}).values()) if isinstance(cp.get('transactions'), dict) else []
    raw_by_signature, cache = {}, {}

    def read(digest):
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            return None
        if digest not in cache:
            try:
                value = store.evidence(digest)
                encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
                cache[digest] = value if hashlib.sha256(encoded).hexdigest() == digest else None
            except (EvidenceError, OSError, ValueError, TypeError, KeyError, RuntimeError):
                cache[digest] = None
        return cache[digest]

    for record in selected[:10_000]:
        if not isinstance(record, dict):
            continue
        signature, digest = record.get('signature'), record.get('evidence_hash')
        raw = read(digest)
        if isinstance(signature, str) and isinstance(raw, dict):
            raw_by_signature[signature] = (digest, raw)
    accounts = {item['address']: item for item in history['paging']['accounts'] if item['address'] != address}
    for _, raw in raw_by_signature.values():
        try:
            keys = _keys(raw['transaction']['message'], raw['meta'])
            for name in ('preTokenBalances', 'postTokenBalances'):
                for balance in raw['meta'].get(name) or []:
                    index = balance.get('accountIndex')
                    if (balance.get('owner') == address and type(index) is int and 0 <= index < len(keys)
                        and _valid_account(keys[index]) and balance.get('mint') != WSOL):
                        accounts.setdefault(keys[index], {'address': keys[index], 'chain': {'state': 'UNKNOWN', 'evidence': []}, 'receipts': []})
        except (ValueError, TypeError, KeyError, IndexError):
            pass
    checkpoint_accounts = cp.get('accounts', {})
    checkpoint_accounts = checkpoint_accounts if isinstance(checkpoint_accounts, dict) else {}
    candidate_accounts = (set(checkpoint_accounts) - {address}) | set(accounts)
    account_items = list(accounts.items())[:1000]
    inspected_accounts = {account for account, _ in account_items}
    account_scope = {'candidate_account_count': len(candidate_accounts),
                     'inspected_account_count': len(inspected_accounts),
                     'omitted_account_count': len(candidate_accounts - inspected_accounts),
                     'population': 'Named frozen checkpoint accounts and source-derived token-account candidates; evaluated account subset only'}
    positions, actions, account_placement_sources = [], [], {}
    action_keys = set()
    quantity_validations = {}

    def validate_sources(account, receipt, point=None):
        """Reconcile metric facts, then validate each linked archive's operations.

        Raw balance agreement alone cannot exclude an unsupported instruction in
        a competing archive. Prices, native consideration and fee amounts are
        deliberately outside these scoped quantity/ownership dependencies.
        """
        key = (account, receipt['signature'])
        if key in quantity_validations:
            return quantity_validations[key]
        shared = receipt.get('source_consistency', {})
        shared = shared if isinstance(shared, dict) else {}
        checks = shared.get('checks', {})
        checks = checks if isinstance(checks, dict) else {}
        source_set = shared.get('source_set', receipt.get('source_set', history_source_set))
        source_set = source_set if isinstance(source_set, dict) else {}
        counts = ('raw_reference_count', 'authenticated_reference_count', 'unique_link_count',
                  'unique_hash_count', 'inspected_hash_count', 'omitted_hash_count',
                  'omitted_link_count', 'invalid_link_count', 'invalid_authenticated_link_count',
                  'unauthenticated_link_count')
        budget = source_set.get('budget', {})
        budget = budget if isinstance(budget, dict) else {}
        maximum_hashes = budget.get('max_unique_hashes')
        set_complete = (source_set.get('state') == 'PASS' and source_set.get('complete') is True
                        and all(type(source_set.get(name)) is int and source_set[name] >= 0 for name in counts)
                        and type(maximum_hashes) is int and 1 <= maximum_hashes <= SOURCE_HASH_LIMIT
                        and source_set['raw_reference_count'] >= source_set['unique_link_count'] >= source_set['unique_hash_count']
                        and source_set['authenticated_reference_count'] >= source_set['unique_link_count']
                        and source_set['unique_hash_count'] <= maximum_hashes
                        and source_set['inspected_hash_count'] == source_set['unique_hash_count']
                        and source_set['omitted_hash_count'] == source_set['omitted_link_count']
                        == source_set['invalid_link_count'] == source_set['invalid_authenticated_link_count']
                        == source_set['unauthenticated_link_count'] == 0)
        hashes = shared.get('native_hashes', [])
        hashes = sorted(set(hashes)) if isinstance(hashes, list) and all(isinstance(value, str) for value in hashes) else []
        evidence = set(shared.get('evidence', [])) | set(hashes)
        paths, errors, points = [], [], []
        # An incomplete inspection is already a required UNKNOWN dependency.
        # Do not bypass its shared IO budget by opening all omitted alternatives.
        for digest in hashes if set_complete else []:
            raw = read(digest)
            try:
                if not isinstance(raw, dict):
                    raise ValueError('A collector-linked native archive is unavailable')
                candidate = _quantity_point(raw, address, account)
                if candidate is None:
                    raise ValueError('A linked archive does not support this scoped account quantity operation')
                points.append(candidate)
                paths.append({'signature': receipt['signature'], 'hash': digest,
                              'paths': sorted(set(candidate['paths']) | {'meta.err'})})
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                errors.append(str(exc))
                if isinstance(exc, InstructionEvidenceError):
                    from .transaction_format import original_instruction_paths
                    paths.append({'signature': receipt['signature'], 'hash': digest,
                                  'paths': original_instruction_paths(raw, exc.paths),
                                  'state': 'UNKNOWN', 'reason': str(exc)})
        shared_paths = shared.get('source_paths', [])
        for item in shared_paths if isinstance(shared_paths, list) else []:
            if isinstance(item, dict) and isinstance(item.get('hash'), str) and isinstance(item.get('paths'), list):
                paths.append({'signature': receipt['signature'], 'hash': item['hash'], 'paths': list(item['paths'])})
        def semantics(value):
            return tuple(value.get(name) for name in ('kind', 'pre', 'post', 'mint', 'decimals', 'program_id'))
        if point is None and isinstance(read(receipt.get('hash')), dict):
            try:
                point = _quantity_point(read(receipt['hash']), address, account)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError):
                point = None
        atomic_failed = (point is not None and point.get('kind') == 'failed' and point.get('pre') is None)
        needs = BASE_FACTS if atomic_failed else BASE_FACTS + BOUNDARY_FACTS
        facts_known = set_complete and all(isinstance(checks.get(name), dict) and checks[name].get('state') == 'PASS' for name in needs)
        operations_known = bool(hashes) and len(points) == len(hashes) and point is not None
        semantic_known = operations_known and all(semantics(candidate) == semantics(point) for candidate in points)
        identity_needs = BASE_FACTS if atomic_failed else BASE_FACTS + ('owner', 'mint', 'decimals', 'program')
        identity_known = set_complete and operations_known and all(isinstance(checks.get(name), dict) and checks[name].get('state') == 'PASS' for name in identity_needs)
        known = facts_known and semantic_known
        reason = ('Every linked native archive reconciles required account facts and supports the same quantity/ownership operation.' if known else
                  '; '.join(dict.fromkeys(errors + ([source_set.get('reason', 'Authenticated source-set completeness is unresolved.')] if not set_complete else []) +
                                           ([shared.get('reason', 'Required linked account facts are unresolved.')] if not facts_known else []) +
                                           (['Linked archives do not all support the same absolute quantity and instruction semantics.'] if not semantic_known else []))))
        result = {'known': known, 'identity_known': identity_known, 'reason': reason, 'evidence': sorted(evidence), 'source_paths': paths,
                  'dependencies': list(needs) + ['supported_operations_in_every_linked_native_archive']}
        quantity_validations[key] = result
        return result

    def recover(kind, account, reason, *, signature=None, slot=None):
        key = (kind, account, signature, slot)
        if key in action_keys:
            return
        action_keys.add(key)
        methods = {'acquisition_backfill': 'getSignaturesForAddress', 'retrieve_raw': 'getTransaction',
                   'resume_cursor': 'getSignaturesForAddress', 'retrieve_order': 'getBlock',
                   'recover_balance': 'getTransaction', 'recover_closing_sale': 'getSignaturesForAddress'}
        action = {'kind': kind, 'account': account, 'reason': reason, 'requires_network': kind in methods,
                  'method': methods.get(kind), 'budget_guard': 'Existing provider allowlist, entitlement, free quota and durable reservations remain required'}
        if signature:
            action['signature'] = signature
        if slot is not None:
            action['slot'] = slot
        if kind == 'acquisition_backfill' and signature:
            action['before'] = signature
        elif kind in ('resume_cursor', 'recover_closing_sale'):
            action['before'] = cp.get('accounts', {}).get(account, {}).get('cursor')
        actions.append(action)

    def emit(episode, receipt_map, uncertain_rows):
        if episode is None:
            return
        # Episode membership is established in canonical slot/transaction order
        # first. Only the completed output cohort uses the UTC reporting window.
        # An intervening future/missing timestamp must never skip a dependency.
        if episode['end'] is not None and not start <= episode['end'] < end:
            return
        if episode['end'] is None and type(episode['first_time']) is int and episode['first_time'] >= end:
            return
        # Sorting is useful for quantity reconstruction but cannot establish
        # exclusion when another archived source gives a different placement.
        # Revisit the complete named-account receipt set before certifying each
        # candidate, including records sorted before its opening/after its sale.
        placement_known, placement_hashes, exclusions, disputed = True, set(), [], []
        included_uncertain = 0
        included = set(episode['signatures'])
        for signature in included:
            receipt = receipt_map.get(signature, {})
            placement = receipt.get('placement', {})
            placement = placement if isinstance(placement, dict) else {}
            hashes = set(placement.get('evidence', [])) | set(receipt.get('evidence', []))
            placement_hashes.update(hashes)
            included_uncertain += (receipt.get('state') != 'PASS' or receipt.get('ordering', {}).get('state') != 'PASS' or placement.get('state') != 'PASS')
            if placement.get('state') != 'PASS':
                placement_known = False
                disputed.append(signature)
        checked_outside, limit_reached = 0, False
        for receipt in uncertain_rows:
            signature = receipt['signature']
            if signature in included:
                continue
            if checked_outside >= MAX_UNCERTAIN_EXCLUSIONS:
                placement_known, limit_reached = False, True
                break
            checked_outside += 1
            placement = receipt.get('placement', {})
            placement = placement if isinstance(placement, dict) else {}
            hashes = set(placement.get('evidence', [])) | set(receipt.get('evidence', []))
            placement_hashes.update(hashes)
            relation, reason = _placement_relation(placement, episode['opening_order'], episode['closing_order'])
            if relation != 'potential':
                exclusions.append({'signature': signature, 'state': 'PASS', 'relation': relation,
                                   'reason': reason, 'evidence': sorted(hashes),
                                   'slot_bounds': deepcopy(placement.get('slot_bounds', {})),
                                   'index_bounds': deepcopy(placement.get('indices_by_slot', {}))})
                continue
            placement_known = False
            disputed.append(signature)
            episode['signatures'].append(signature)
            for key in ('collection', 'chronology', 'continuity'):
                prior = episode['stages'][key]
                episode['stages'][key] = _check(False, reason, set(prior['evidence']) | hashes, prior['dependencies'])
            recover('resolve_metadata', episode['account'],
                    'Resolve every archived slot/index placement before excluding this potentially intervening account receipt.', signature=signature)
        episode['sources'].update(placement_hashes)
        placement_reason = ('Every included receipt has reconciled placement; unresolved excluded receipts have disjoint archived bounds and reconciled outside records follow verified native order.' if placement_known else
                            f'More than {MAX_UNCERTAIN_EXCLUSIONS} unresolved outside receipts exceed this candidate exclusion proof limit; potentially intersecting dependencies were not discarded.' if limit_reached else
                            'Potentially intersecting account receipts have unresolved placement: ' + ', '.join(disputed))
        episode['stages']['placement'] = _check(placement_known, placement_reason,
                                               placement_hashes, ('all_account_receipt_placements', 'native_episode_boundaries', 'disjoint_exclusion_bounds'))
        source_known, source_hashes, source_needs, source_reasons = True, set(), set(), []
        source_path_index = {(item['signature'], item['hash']): item for item in episode['paths']}
        for signature in episode['signatures']:
            validation = validate_sources(episode['account'], receipt_map.get(signature, {'signature': signature}))
            source_known = source_known and validation['known']
            source_hashes.update(validation['evidence'])
            source_needs.update(validation['dependencies'])
            if not validation['known']:
                source_reasons.append(f'{signature}: {validation["reason"]}')
            for path in validation['source_paths']:
                path_key = (path['signature'], path['hash'])
                existing = source_path_index.get(path_key)
                if existing is None:
                    existing = deepcopy(path)
                    episode['paths'].append(existing)
                    source_path_index[path_key] = existing
                else:
                    existing['paths'] = sorted(set(existing['paths']) | set(path['paths']))
        episode['sources'].update(source_hashes)
        episode['stages']['source_consistency'] = _check(source_known,
                                                        'Required account facts and supported operations reconcile across every linked native archive.' if source_known else '; '.join(dict.fromkeys(source_reasons)),
                                                        source_hashes, sorted(source_needs))
        stages, sources = episode['stages'], sorted(episode['sources'])
        hold_known = episode['end'] is not None and all(stages[key]['state'] == 'PASS' for key in HOLD_NEEDS)
        stages['hold'] = _check(hold_known, 'Account-scoped quantity/ownership/zero/chronology dependencies are satisfied.' if hold_known else 'A required source-backed account episode dependency remains unresolved.', sources, HOLD_NEEDS)
        for name in ('basis', 'fees', 'classification', 'valuation'):
            stages[name] = _check(False, 'Not derived by this quantity-only account resolver; separate financial/population evidence is required.', (), ('financial_ledger' if name in ('basis', 'fees') else 'historical_' + name,))
        with localcontext() as context:
            context.prec = 192
            hours = canonical(Decimal(episode['end'] - episode['start']) / Decimal(3600)) if hold_known else None
        status = 'known_closed' if hold_known else 'open' if episode['end'] is None and all(stages[key]['state'] == 'PASS' for key in HOLD_NEEDS if key != 'strict_zero') else 'unresolved'
        positions.append({'id': f'{episode["account"]}:{episode["first_signature"]}', 'account': episode['account'],
                          'mint': episode['mint'], 'decimals': episode['decimals'], 'program_id': episode['program_id'], 'status': status,
                          'start': _iso(episode['start']), 'end': _iso(episode['end']),
                          'opening_raw': str(episode['opening']) if episode['opening'] is not None else None,
                          'closing_raw': str(episode['last']) if episode['last'] is not None else None,
                          'acquired_raw': str(episode['acquired']), 'sold_raw': str(episode['sold']),
                          'hold_hours': {'status': 'known' if hold_known else 'unknown', 'value': hours, 'unit': 'hours',
                                         'evidence': sources, 'population': 'This named token account only; not a wallet-wide position'},
                          'stages': stages, 'sources': sources, 'signatures': episode['signatures'],
                          'source_paths': episode['paths'], 'dependency_exclusions': exclusions,
                          'source_set': {**{key: deepcopy(value) for key, value in history_source_set.items() if key != 'evidence'},
                                         'evidence': sorted(source_hashes),
                                         'evidence_scope': 'Required account-episode archives; the shared authenticated index is in history_evidence.source_consistency.source_set'},
                          'placement_scope': {'max_uncertain_exclusions': MAX_UNCERTAIN_EXCLUSIONS,
                                              'inspected_uncertain_exclusions': checked_outside,
                                              'omitted_uncertain_exclusions': len(uncertain_rows) - included_uncertain - checked_outside,
                                              'complete': not limit_reached}})

    for account, certificate in account_items:
        chain = certificate.get('chain', {})
        chain_known = chain.get('state') == 'PASS'
        if not chain_known:
            recover('resume_cursor', account, 'Restore a connected archived account cursor chain and terminal receipt before accepting its episode history.')
        receipts = {item['signature']: item for item in certificate.get('receipts', []) if isinstance(item, dict) and isinstance(item.get('signature'), str)}
        rows = list(receipts.values())
        for signature, (digest, raw) in raw_by_signature.items():
            try:
                keys = _keys(raw['transaction']['message'], raw['meta'])
            except (ValueError, TypeError, KeyError):
                continue
            if account in keys and signature not in receipts:
                rows.append({'signature': signature, 'hash': digest, 'state': 'UNKNOWN', 'slot': raw.get('slot'),
                             'canonical_time': raw.get('blockTime'), 'evidence': [], 'ordering': {'state': 'UNKNOWN'}})
        slot_counts = Counter(row.get('slot') for row in rows if type(row.get('slot')) is int)
        rows.sort(key=lambda row: (row.get('slot') if type(row.get('slot')) is int else -1,
                                  row.get('ordering', {}).get('transaction_index') if type(row.get('ordering', {}).get('transaction_index')) is int else -1))
        receipt_map = {row['signature']: row for row in rows}
        uncertain_rows = [row for row in rows if (row.get('state') != 'PASS'
                                                 or row.get('ordering', {}).get('state') != 'PASS'
                                                 or row.get('placement', {}).get('state') != 'PASS')]
        # Shared once per account, rather than copying every outside raw hash
        # into every episode. Uncertain exclusions retain their direct hashes.
        account_placement_sources[account] = sorted({digest for row in rows
                                                     for digest in row.get('placement', {}).get('evidence', [])})
        active = None
        for receipt in rows:
            signature = receipt['signature']
            raw_item = raw_by_signature.get(signature)
            digest = receipt.get('hash')
            raw = read(digest)
            when = raw.get('blockTime') if isinstance(raw, dict) else receipt.get('canonical_time')
            slot = raw.get('slot') if isinstance(raw, dict) else receipt.get('slot')
            source_hashes = set(chain.get('evidence', [])) | set(receipt.get('evidence', [])) | set(certificate.get('ownership', {}).get('evidence', []))
            if isinstance(digest, str) and read(digest) is not None:
                source_hashes.add(digest)
            order = receipt.get('ordering', {})
            ordering_known = order.get('state') == 'PASS' and (slot_counts[slot] < 2 or type(order.get('transaction_index')) is int)
            receipt_known = receipt.get('state') == 'PASS' and isinstance(raw, dict) and raw_item is not None and raw_item[0] == digest
            point = None
            error = None
            try:
                if not isinstance(raw, dict):
                    raise ValueError('Required archived transaction is absent')
                point = _quantity_point(raw, address, account)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                error = str(exc)
            validation = validate_sources(account, receipt, point)
            source_known = validation['known']
            identity_known = validation['identity_known']
            source_hashes.update(validation['evidence'])
            if not source_known:
                recover('recover_balance', account, validation['reason'], signature=signature)
            if not receipt_known:
                recover('retrieve_raw' if raw is None else 'resolve_metadata', account,
                        'This account-specific archived page/transaction receipt is missing or contradictory.', signature=signature)
            if not ordering_known and type(slot) is int:
                recover('retrieve_order', account, 'Restore archived same-slot block signature order and matching transaction index.', slot=slot)
            if point is None:
                if active is not None:
                    for key in ('collection', 'identity', 'quantities', 'continuity'):
                        prior = active['stages'][key]
                        active['stages'][key] = _check(False, error or 'A required account operation is unresolved', source_hashes | set(prior['evidence']), prior['dependencies'])
                    chrono = active['stages']['chronology']
                    time_ok = type(when) is int and type(active['last_time']) is int and when >= active['last_time']
                    active['stages']['chronology'] = _check(chrono['state'] == 'PASS' and ordering_known and time_ok, 'Every slot-intervening record requires canonical time and transaction order even when outside the display window.', source_hashes | set(chrono['evidence']) | set(order.get('evidence', [])), chrono['dependencies'])
                    active['last_time'] = when
                    active['sources'].update(source_hashes | set(order.get('evidence', [])))
                    active['signatures'].append(signature)
                if error:
                    recover('recover_balance', account, error, signature=signature)
                continue
            if point['kind'] == 'failed' and point['pre'] is None:
                if active is not None:
                    active['stages']['collection'] = _check(active['stages']['collection']['state'] == 'PASS' and receipt_known and chain_known, 'Every intervening account-specific receipt must remain available.', source_hashes | set(active['stages']['collection']['evidence']), active['stages']['collection']['dependencies'])
                    active['stages']['chronology'] = _check(active['stages']['chronology']['state'] == 'PASS' and ordering_known and type(when) is int and type(active['last_time']) is int and when >= active['last_time'], 'Failed execution changes no token quantity; canonical order/time still required.', source_hashes | set(active['stages']['chronology']['evidence']) | set(order.get('evidence', [])), active['stages']['chronology']['dependencies'])
                    active['last_time'] = when
                    if not source_known:
                        for key in ('quantities', 'continuity'):
                            prior = active['stages'][key]
                            active['stages'][key] = _check(False, validation['reason'], source_hashes | set(prior['evidence']), prior['dependencies'])
                    if not identity_known:
                        prior = active['stages']['identity']
                        active['stages']['identity'] = _check(False, validation['reason'], source_hashes | set(prior['evidence']), prior['dependencies'])
                    active['sources'].update(source_hashes | set(order.get('evidence', [])))
                    active['signatures'].append(signature)
                    active['paths'].append({'signature': signature, 'hash': digest, 'paths': point['paths']})
                continue
            if point['kind'] in ('unchanged', 'failed') and active is None:
                continue
            if active is not None and point['pre'] == 0 and point['kind'] == 'buy':
                # A fresh primary zero can begin another supported episode; the
                # unresolved preceding episode is retained rather than erased.
                emit(active, receipt_map, uncertain_rows)
                active = None
            if active is None:
                opening_known = point['kind'] == 'buy' and point['pre'] == 0 and source_known
                active = {'account': account, 'mint': point['mint'], 'decimals': point['decimals'], 'program_id': point['program_id'],
                          'first_signature': signature, 'first_time': when, 'start': when if opening_known and type(when) is int else None,
                          'end': None, 'opening': point['pre'], 'last': point['pre'], 'last_time': when,
                          'opening_order': (slot, order.get('transaction_index')), 'closing_order': None,
                          'acquired': 0, 'sold': 0, 'sources': set(), 'signatures': [], 'paths': [],
                          'stages': {
                              'collection': _check(chain_known and receipt_known, 'Connected collector cursor chain and specific account-page receipt required.', source_hashes, ('native_cursor_chain', 'account_signature_receipts', 'snapshot_anchor')),
                              'identity': _check(identity_known, 'Every linked raw token boundary must identify the same account, mint, decimals, program and wallet owner.', source_hashes, ('native_identity', 'account_membership', 'execution', 'owner', 'mint', 'decimals', 'program')),
                              'opening_zero': _check(opening_known, 'Reconciled linked pre-acquisition quantity is zero.' if opening_known else 'Opening quantity/acquisition is nonzero or its linked evidence is unresolved; a history cutoff is not zero.', source_hashes, ('primary_pre_quantity', 'supported_acquisition', 'linked_source_consistency')),
                              'chronology': _check(ordering_known and type(when) is int, 'Canonical transaction timestamps and native slot/block order required.', source_hashes | set(order.get('evidence', [])), ('canonical_time', 'native_slot_order', 'same_slot_block_order')),
                              'quantities': _check(source_known, 'All linked absolute raw quantities must agree and reconcile with individual supported route transfers.', source_hashes, ('raw_integer_balances', 'parsed_route_transfers', 'recognized_instruction_layout', 'linked_source_consistency')),
                              'continuity': _check(source_known, 'Reconciled intervening raw boundaries must exactly match prior post-quantity and identity.', source_hashes, ('account_page_population', 'continuous_owned_quantity', 'linked_source_consistency')),
                              'strict_zero': _check(False, 'A final supported sale returning this same account to strict zero is required.', (), ('final_sale', 'primary_post_quantity')),
                          }}
                if not opening_known:
                    recover('acquisition_backfill', account, 'Recover the preceding account-level zero boundary and every intervening supported acquisition/flow; do not assume the observed opening stock is free or new.', signature=signature)
            program_agrees = point['program_id'] is None or active['program_id'] is None or point['program_id'] == active['program_id']
            continuity = (point['pre'] == active['last'] and point['mint'] == active['mint'] and point['decimals'] == active['decimals'] and program_agrees)
            if not program_agrees:
                active['stages']['identity'] = _check(False, 'Native token-program identity contradicts the previous account boundary.', source_hashes | set(active['stages']['identity']['evidence']), active['stages']['identity']['dependencies'])
            time_known = type(when) is int and type(active['last_time']) is int and when >= active['last_time']
            for key, okay, reason in (
                    ('collection', receipt_known and chain_known, 'All required account-page/raw collection receipts remain available.'),
                    ('chronology', ordering_known and time_known, 'Every required canonical time and slot/block order agrees.'),
                    ('continuity', continuity and source_known, 'Every reconciled quantity/identity boundary continues exactly from the previous record.'),
                    ('identity', program_agrees and identity_known, 'Every linked event-time owner, mint, decimals and native token-program identity agrees.'),
                    ('quantities', source_known, 'Every linked absolute account quantity and supported movement agrees.')):
                active['stages'][key] = _check(active['stages'][key]['state'] == 'PASS' and okay, reason, source_hashes | set(order.get('evidence', [])) | set(active['stages'][key]['evidence']), active['stages'][key].get('dependencies', []))
            if not continuity:
                recover('recover_balance', account, 'Raw account quantity/identity discontinuity requires the missing intervening flow or corrected primary record.', signature=signature)
            active['sources'].update(source_hashes | set(order.get('evidence', [])))
            active['signatures'].append(signature)
            active['paths'].append({'signature': signature, 'hash': digest, 'paths': point['paths']})
            active['last'], active['last_time'] = point['post'], when
            active['program_id'] = point['program_id'] or active['program_id']
            active['acquired'] += point['post'] - point['pre'] if point['kind'] == 'buy' else 0
            active['sold'] += point['pre'] - point['post'] if point['kind'] == 'sell' else 0
            if point['post'] == 0:
                closes = point['kind'] == 'sell' and source_known and active['stages']['opening_zero']['state'] == 'PASS'
                active['end'] = when if type(when) is int else None
                active['closing_order'] = (slot, order.get('transaction_index'))
                active['stages']['strict_zero'] = _check(closes, 'Supported final disposal has reconciled linked post-balances of exactly zero.' if closes else 'Observed zero lacks reconciled linked evidence for a supported acquisition-to-sale episode.', source_hashes, ('final_sale', 'primary_post_quantity', 'opening_zero', 'linked_source_consistency'))
                emit(active, receipt_map, uncertain_rows)
                active = None
        if active is not None:
            recover('recover_closing_sale', account, 'This account-scoped episode has no evidenced final zero sale in the frozen report population.')
            emit(active, receipt_map, uncertain_rows)
    known = [position for position in positions if position['status'] == 'known_closed']
    with localcontext() as context:
        context.prec = 192
        value = canonical(median([Decimal(position['hold_hours']['value']) for position in known]))
    evidence = sorted({digest for position in known for digest in position['sources']})
    return {'version': VERSION, 'scope': 'Individual token-account strict-zero episodes; no wallet-wide population claim',
            'trust_boundary': 'Checksum-verified archived native collector/provider receipts; not independent mainnet authentication',
            'counts': {'known_closed': len(known), 'open': sum(p['status'] == 'open' for p in positions),
                       'unresolved': sum(p['status'] == 'unresolved' for p in positions)},
            'known_account_hold_median_hours': {'status': 'known' if known else 'unknown', 'value': value,
                                              'unit': 'hours', 'population': 'Only the evaluated known subset of individually evidenced closed token-account episodes; not the median of all supplied accounts or the wallet completed-position median', 'evidence': evidence},
            'positions': positions, 'recovery_actions': actions, 'account_placement_sources': account_placement_sources,
            'account_scope': account_scope,
            'limitations': ['Other token accounts and historical wallet-wide ownership are not covered by a named-account zero boundary.',
                            'A known scoped hold never establishes full-wallet holding populations, meme classification, ROI, fees or equity.',
                            'Financial and aggregate wallet gates remain independent; recovery actions require existing quota/entitlement controls and are never dispatched by this offline resolver.']}
