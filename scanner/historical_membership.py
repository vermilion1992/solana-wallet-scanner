"""Raw-derived membership at evidenced token-account checkpoints and operations.

This is a local evidence admission interface, not an exhaustive historical owner
index.  It uses the existing token interpreter and linked-source/clock validators.
Even agreeing sparse checkpoints cannot establish ownership between transactions,
and caller completion flags or terminal address queries supply no population proof.
"""
from __future__ import annotations

from collections import defaultdict
import re

from .collector import _valid_account
from .decoder import TOKEN_IDS
from .source_consistency import SOURCE_HASH_LIMIT

VERSION = 'historical-membership-evidence-v1'
SCOPE = 'Selected token-account checkpoints and committed operations only'


def _receipt(known, reason, hashes=(), paths=(), dependencies=()):
    from .wallet_evidence import HASH
    evidence = sorted({h for h in hashes if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and evidence else 'UNKNOWN', 'scope': SCOPE,
            'reason': reason, 'evidence': evidence,
            'raw_paths': sorted({p for p in paths if isinstance(p, str) and p}),
            'dependencies': sorted(set(dependencies))}


def _endpoint(pair, phase, wallet, check):
    value = pair.get(phase) if isinstance(pair, dict) else None
    known = check['state'] == 'PASS' and isinstance(value, dict)
    # The shared interpreter can supply a zero quantity using create/close proof.
    # Such a convenience endpoint is not an initialized token-account owner.
    native = known and str(value.get('path', '')).startswith(f'meta.{phase}TokenBalances.')
    present = native if known else None
    return {'state': check['state'], 'present': present,
            'owner': value.get('owner') if known and present else None,
            'wallet_member': (present and value.get('owner') == wallet) if known else None,
            'mint': value.get('mint') if known and present else None,
            'check': check}


def _coordinate(raw, path):
    """Use the already validated outer/inner association, never array ordinal alone."""
    outer = re.fullmatch(r'transaction\.message\.instructions\.([0-9]+)', path or '')
    if outer:
        return int(outer[1]), 0, 0
    inner = re.fullmatch(r'meta\.innerInstructions\.([0-9]+)\.instructions\.([0-9]+)', path or '')
    if inner and isinstance(raw, dict):
        meta = raw.get('meta')
        groups = meta.get('innerInstructions') if isinstance(meta, dict) else None
        group = groups[int(inner[1])] if isinstance(groups, list) and int(inner[1]) < len(groups) else None
        index = group.get('index') if isinstance(group, dict) else None
        if type(index) is int and index >= 0:
            return index, 1, int(inner[2])
    return None


def _operation_steps(observation, account, raw):
    rows = [row for row in observation.get('lifecycle', [])
            if row.get('applied') is True and row.get('account') == account]
    for transfer in observation.get('transfers', []):
        if account in (transfer.get('source'), transfer.get('destination')):
            rows.append({'kind': 'token-transfer', 'account': account, 'path': transfer.get('path'),
                         'raw_paths': transfer.get('raw_paths', [transfer.get('path')]),
                         'facts': {key: transfer.get(key) for key in ('source', 'destination', 'mint', 'quantity_raw')}})
    placed = [(row, _coordinate(raw, row.get('path'))) for row in rows]
    complete = all(coordinate is not None for _, coordinate in placed)
    return [row for row, _ in sorted(placed, key=lambda item: item[1] or (-1, -1, -1))], complete


def _admit_observations(selected, versions, consistency, clocks, wallet, *, raw_versions=None):
    """Internal composition of freshly derived shared proof structures.

    Normal reports call this only with their current _observe results and current
    assess_source_consistency/assess_chronology output. Public imported receipts
    cannot enter here; use derive_historical_membership for raw inputs instead.
    Monetary fields never participate in membership admission.
    """
    if not _valid_account(wallet):
        raise ValueError('A valid public wallet is required')
    result = {'version': VERSION, 'scope': SCOPE, 'wallet': wallet, 'transactions': {},
              'accounts': {}, 'provider_requests': 0, 'credential_lookups': 0}
    account_rows, all_evidence, membership_checks = defaultdict(list), [], []
    source_set = consistency.get('source_set', {})
    for signature, primary in sorted(selected.items()):
        variants = list(versions.get(signature, []))
        chosen = next((row for row in variants if row.get('hash') == primary.get('evidence_hash')), None)
        identity = consistency.get('transactions', {}).get(signature, {}).get('identity', {})
        hashes = [row.get('hash') for row in variants] + identity.get('evidence', [])
        if source_set.get('state') != 'PASS':
            hashes += source_set.get('evidence', [])
        all_evidence.extend(hashes)
        identity_known = identity.get('state') == 'PASS' and source_set.get('state') == 'PASS'
        clock = clocks.get('transactions', {}).get(signature, {})
        placement = _receipt(clock.get('time_state') == 'PASS' and clock.get('state') == 'PASS',
            clock.get('reason', 'Shared raw chronology is unavailable.'),
            hashes + clock.get('evidence', []), dependencies=['raw_chronology'])
        tx = {'signature': signature, 'evidence': sorted({h for h in hashes if isinstance(h, str)}),
              'accounts': {}, 'attempts': [], 'clock': {
                  'slot': clock.get('slot'), 'canonical_time': clock.get('canonical_time'),
                  'transaction_index': clock.get('transaction_index'), 'check': placement}}
        result['transactions'][signature] = tx
        if chosen is None:
            tx['check'] = _receipt(False, 'The selected raw observation is unavailable.', hashes,
                                    dependencies=['selected_raw_observation'])
            membership_checks.append(tx['check'])
            continue
        if not identity_known or any(row.get('gaps') for row in variants):
            membership_checks.append(_receipt(False,
                'An unusable or unassignable selected/linked observation may contain token-account membership activity.',
                hashes, dependencies=['linked_native_identity', 'complete_selected_operation_inspection']))
        tx['attempts'] = [{key: row.get(key) for key in ('kind', 'account', 'path', 'raw_paths')}
                          for row in chosen.get('lifecycle', []) if row.get('applied') is False]
        relevant = sorted({account for row in variants for account in row.get('boundaries', {})})
        from .wallet_evidence import MAX_ACCOUNT_STEPS
        if len(relevant) * len(variants) > MAX_ACCOUNT_STEPS:
            tx['check'] = _receipt(False, 'The account-union/version inspection budget is exceeded; no prefix is admitted.',
                                    hashes, dependencies=['complete_account_version_inspection'])
            membership_checks.append(tx['check'])
            continue
        for account in relevant:
            pairs = [row.get('boundaries', {}).get(account) for row in variants]
            pair = chosen.get('boundaries', {}).get(account)
            from .wallet_evidence import _semantic
            agrees = pair is not None and all(p is not None and _semantic(p) == _semantic(pair)
                and p.get('program') == pair.get('program') for p in pairs)
            evidence_paths = [p for boundary in pairs if boundary for p in
                              boundary.get('checks', {}).get('ownership', {}).get('raw_paths', [])]
            valid_owners = all(_valid_account(p[phase]['owner']) for p in pairs if p
                               for phase in ('pre', 'post') if p.get(phase))
            endpoint_check = _receipt(identity_known and agrees and valid_owners and all(
                p.get('checks', {}).get('ownership', {}).get('state') == 'PASS' for p in pairs if p),
                'Every linked version reconciles the same token-account owner endpoints.' if agrees else
                'A required linked owner endpoint is absent or conflicting.', hashes, evidence_paths,
                ['linked_native_identity', 'phase_specific_token_ownership'])
            pair = pair or next((p for p in pairs if p), {})
            before, after = (_endpoint(pair, phase, wallet, endpoint_check) for phase in ('pre', 'post'))
            bodies = {row.get('evidence_hash'): row.get('raw') for row in
                      (raw_versions or {}).get(signature, [])}
            bodies.setdefault(primary.get('evidence_hash'), primary.get('raw'))
            steps, steps_placed = _operation_steps(chosen, account, bodies.get(chosen.get('hash')))
            semantic = [(row['kind'], row.get('facts')) for row in steps]
            lifecycle_agrees = steps_placed and all(
                placed and [(row['kind'], row.get('facts')) for row in alternative_steps] == semantic
                for alternative_steps, placed in (_operation_steps(row, account, bodies.get(row.get('hash')))
                                                  for row in variants))
            execution = consistency.get('transactions', {}).get(signature, {}).get('accounts', {}).get(
                account, {}).get('checks', {}).get('execution', {})
            lifecycle_known = endpoint_check['state'] == 'PASS' and lifecycle_agrees and execution.get('state') == 'PASS' and all(
                p.get('checks', {}).get('lifecycle', {}).get('state') == 'PASS' for p in pairs if p)
            owner, present = before['owner'], before['present']
            events, transition_valid = [], lifecycle_known
            for row in steps:
                facts, kind = row.get('facts', {}), row.get('kind')
                event_before = {'present': present, 'owner': owner,
                                'wallet_member': present and owner == wallet if present is not None else None}
                program_valid = facts.get('program') in TOKEN_IDS and facts.get('program') == pair.get('program')
                if kind == 'token-transfer':
                    transition_valid = transition_valid and present is True
                elif isinstance(kind, str) and kind.startswith('initializeAccount'):
                    transition_valid = transition_valid and program_valid and present is False and (
                        facts.get('mint') == (pair.get('post') or {}).get('mint') and _valid_account(facts.get('owner')))
                    present, owner = True, facts.get('owner')
                elif kind == 'setAuthority' and facts.get('authorityType') == 'accountOwner':
                    transition_valid = transition_valid and program_valid and present is True and (
                        facts.get('authority') == owner and _valid_account(facts.get('newAuthority')))
                    owner = facts.get('newAuthority')
                elif kind == 'closeAccount':
                    # Close authority can be a delegate; it is not token ownership.
                    transition_valid = transition_valid and program_valid and present is True
                    present, owner = False, None
                elif kind == 'setAuthority' and facts.get('authorityType') == 'closeAccount':
                    transition_valid = transition_valid and program_valid
                else:
                    transition_valid = False
                events.append({'kind': kind, 'program': facts.get('program'), 'facts': facts,
                    'path': row.get('path'), 'raw_paths': row.get('raw_paths', [row.get('path')]),
                    'before': event_before, 'after': {'present': present, 'owner': owner,
                        'wallet_member': present and owner == wallet if present is not None else None}})
            transition_valid = transition_valid and present == after['present'] and owner == after['owner']
            event_check = _receipt(transition_valid,
                'Executed initialization, owner changes and closure reconcile at instruction-time.' if transition_valid else
                'The committed operation chain is missing, conflicting, unsupported or inconsistent with owner endpoints.',
                hashes, evidence_paths + [p for row in events for p in row['raw_paths']],
                ['linked_native_identity', 'consistent_execution', 'executed_lifecycle_chain'])
            for event in events:
                event['check'] = event_check
                if event_check['state'] != 'PASS':
                    event['before'] = event['after'] = {'present': None, 'owner': None, 'wallet_member': None}
            receipt = {'account': account, 'program': pair.get('program'), 'pre': before, 'post': after,
                       'operations': [row for row in events if row['kind'] != 'token-transfer'],
                       'instruction_membership': events,
                       'endpoint_check': endpoint_check, 'event_time_check': event_check,
                       'historical_interval_check': _receipt(False,
                           'A transaction checkpoint does not prove unseen ownership before, after or between records.',
                           hashes, dependencies=['complete_account_lifecycle_history'])}
            tx['accounts'][account] = receipt
            account_rows[account].append({'signature': signature, **receipt, 'clock': tx['clock']})
            membership_checks.append(event_check)
        tx['check'] = _receipt(bool(tx['accounts']) and all(row['event_time_check']['state'] == 'PASS'
            for row in tx['accounts'].values()), 'Membership of the token accounts evidenced in this transaction only.', hashes)
    for account, rows in sorted(account_rows.items()):
        def order(row):
            clock = row['clock']
            return (clock['slot'] if type(clock['slot']) is int else -1,
                    clock['transaction_index'] if type(clock['transaction_index']) is int else -1, row['signature'])
        ordered = sorted(rows, key=order)
        links = []
        for previous, following in zip(ordered, ordered[1:]):
            a, b = previous['clock'], following['clock']
            located = a['check']['state'] == b['check']['state'] == 'PASS'
            order_known = located and type(a['slot']) is int and type(b['slot']) is int and (
                a['slot'] < b['slot'] or a['slot'] == b['slot'] and type(a['transaction_index']) is int
                and type(b['transaction_index']) is int and a['transaction_index'] < b['transaction_index'])
            endpoint_known = previous['post']['state'] == following['pre']['state'] == 'PASS'
            matching = endpoint_known and all(previous['post'][key] == following['pre'][key]
                                              for key in ('present', 'owner', 'mint'))
            hashes = previous['endpoint_check']['evidence'] + following['endpoint_check']['evidence']
            links.append({'previous_signature': previous['signature'], 'following_signature': following['signature'],
                'checkpoint_agreement': _receipt(order_known and matching,
                    'Ordered selected owner checkpoints agree; intervening lifecycle is still unproved.', hashes,
                    dependencies=['raw_chronology', 'owner_endpoints']),
                'interval_membership': _receipt(False, 'Matching checkpoints cannot exclude an unseen reassignment and restoration.',
                                               hashes, dependencies=['complete_account_lifecycle_history'])})
        result['accounts'][account] = {'checkpoints': ordered, 'checkpoint_links': links,
            'lifecycle_complete': False, 'historical_interval_state': 'UNKNOWN'}
    result['observed_event_membership'] = _receipt(bool(membership_checks) and all(
        row['state'] == 'PASS' for row in membership_checks),
        'Membership at selected executed token-account operations only.', all_evidence,
        dependencies=['linked_native_identity', 'executed_lifecycle_chain']
            + [dependency for row in membership_checks for dependency in row.get('dependencies', [])])
    result['historical_population'] = _receipt(False,
        'No accepted source enumerates every historically owned, closed or reassigned account for both token programs; '
        'terminal address-query paging and current account lists do not establish that population.',
        all_evidence, dependencies=['accepted_exhaustive_historical_owner_enumeration'])
    result['checks'] = {'observed_membership': result['observed_event_membership'],
                        'historical_population': result['historical_population']}
    return result


def derive_historical_membership(records, *, all_records, wallet, raw_sources=(), source_receipts=()):
    """Replay original selected/linked raw sources using the normal proof engine.

    Public caller assessments, events, completion declarations and position flags
    are deliberately absent. Indexed wrapper dependencies use their exact source
    hashes, not a hash of a reconstructed semantic record. No source IO is made.
    """
    from .wallet_evidence import (_observe, _resolved_sources, raw_native_dependencies,
        _clock_inputs, _safe_raw, with_derived_order, MAX_ACCOUNT_STEPS)
    from .source_consistency import assess_source_consistency, apply_unresolved_chronology
    from .chronology_evidence import assess_chronology
    if not _valid_account(wallet):
        raise ValueError('A valid public wallet is required')
    selected, linked = {}, {}
    selected_rows = list(records)
    for row in sorted(selected_rows, key=lambda row: str(row.get('evidence_hash')) if isinstance(row, dict) else ''):
        if not isinstance(row, dict) or not isinstance(row.get('signature'), str) or not row['signature']:
            raise ValueError('Selected raw records require explicit signature identities')
        selected.setdefault(row['signature'], row)
    sources = _resolved_sources(raw_sources, source_receipts)
    negative = raw_native_dependencies(sources, (), selected)
    # The report loader already checked hashes before the internal projection.
    # Public direct callers must establish that same raw/pointer binding here.
    from .archive_input import canonical_bytes
    from .indexed_input import IndexedResolver, RECORD_VERSION
    import hashlib
    payloads = {row['hash']: row['payload'] for row in sources
                if row.get('payload') is not None and not row.get('invalid_body')}
    resolver = IndexedResolver(lambda digest, _role: payloads.get(digest), address=wallet)
    negative_bodies = {(row.get('signature'), row.get('evidence_hash')): row.get('raw')
                       for row in negative if row.get('raw') is not None}

    def bound(row):
        raw, digest = row.get('raw'), row.get('evidence_hash')
        if raw is None:
            return row
        try:
            verified = hashlib.sha256(canonical_bytes(raw)).hexdigest() == digest
            if not verified:
                verified = negative_bodies.get((row.get('signature'), digest)) == raw
            pointer = payloads.get(digest)
            if not verified and isinstance(pointer, dict) and pointer.get('version') == RECORD_VERSION:
                resolved = resolver.resolve(pointer)
                verified = (resolved['state'] == 'PASS' and resolved['raw'] == raw
                            and pointer.get('signature') == row.get('signature'))
            return row if verified else {**row, 'raw': None}
        except (ValueError, TypeError, UnicodeError, OverflowError):
            return {**row, 'raw': None}

    for row in list(all_records) + selected_rows + negative:
        if not isinstance(row, dict):
            continue
        row = bound(row)
        key = row.get('signature'), row.get('evidence_hash')
        if key in linked and linked[key].get('raw') != row.get('raw'):
            linked[key] = {**linked[key], 'raw': None}
        else:
            linked.setdefault(key, row)
    if len(linked) > SOURCE_HASH_LIMIT:
        raise ValueError('Historical membership exceeds the fixed record inspection limit')
    linked = [linked[key] for key in sorted(linked, key=repr)]
    steps = sum(len(raw['meta'].get(name, [])) for row in linked
                if isinstance(raw := row.get('raw'), dict) and isinstance(raw.get('meta'), dict)
                for name in ('preTokenBalances', 'postTokenBalances') if isinstance(raw['meta'].get(name), list))
    pages, blocks, indexed, contents = _clock_inputs(sources, (), wallet)
    safe = [{key: value for key, value in row.items() if key != 'transaction_index'} |
            {'raw': row.get('raw') if _safe_raw(row.get('raw')) else None} for row in linked]
    consistency = assess_source_consistency(safe, wallet=wallet, page_receipts=pages,
        indexed_receipts=indexed, archive_contents=contents)
    clocks = apply_unresolved_chronology(assess_chronology(safe, page_receipts=pages,
        block_receipts=blocks, indexed_receipts=indexed), safe, contents)
    versions, raw_versions = defaultdict(list), defaultdict(list)
    for row in linked:
        observed = (_observe(with_derived_order([row], clocks)[0], wallet) if steps <= MAX_ACCOUNT_STEPS else
                    {'signature': row.get('signature'), 'hash': row.get('evidence_hash'),
                     'boundaries': {}, 'lifecycle': [], 'gaps': ['Account observation budget exceeded.']})
        versions[row.get('signature')].append(observed)
        raw_versions[row.get('signature')].append(row)
    return _admit_observations(selected, versions, consistency, clocks, wallet, raw_versions=raw_versions)
