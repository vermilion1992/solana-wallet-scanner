"""Original-record System transfer observations, separate from economic roles.

An executed transfer touching the wallet address proves a gross native movement.
It does not prove a capital deposit/withdrawal, expense, tip, trade consideration,
all owned-account movements, or complete wallet history. In particular, matching
net endpoints cannot erase equal incoming and outgoing transfers.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import re

from .accounting import utc
from .collector import _valid_account
from .compiled_instructions import normalize_transaction, resolve_account_keys
from .chronology_evidence import assess_chronology, assess_interval_membership
from .decoder import SYSTEM_ID
from .instruction_scope import inspect_instruction
from .source_consistency import assess_source_consistency, apply_unresolved_chronology, SOURCE_HASH_LIMIT
from .transaction_format import _needs_instruction_view, original_instruction_paths, supported_transaction_format

VERSION = 'native-cash-observations-v1'
SCOPE = ('Selected executed System transfer instructions touching the wallet address; '
         'economic roles, owned-account aggregate movements and wallet history are separate')
HASH = re.compile(r'^[a-f0-9]{64}$')
U64_MAX = 2**64 - 1
MAX_INSTRUCTIONS = 100_000


def _check(known, reason, evidence=(), paths=()):
    hashes = sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'reason': reason,
            'scope': SCOPE, 'evidence': hashes, 'raw_paths': sorted(set(paths))}


def _instructions(raw):
    """Validate complete outer/inner association before admitting any prefix."""
    outer = raw['transaction']['message'].get('instructions')
    inner = raw['meta'].get('innerInstructions')
    if not isinstance(outer, list) or inner is not None and not isinstance(inner, list):
        raise ValueError('Executed instruction containers are malformed')
    groups, seen = {}, set()
    for group_index, group in enumerate(inner or []):
        index = group.get('index') if isinstance(group, dict) else None
        rows = group.get('instructions') if isinstance(group, dict) else None
        if type(index) is not int or not 0 <= index < len(outer) or index in seen or not isinstance(rows, list):
            raise ValueError('Executed inner instruction association is malformed or duplicated')
        seen.add(index)
        groups[index] = [(f'meta.innerInstructions.{group_index}.instructions.{i}', row)
                         for i, row in enumerate(rows)]
    count = len(outer) + sum(len(rows) for rows in groups.values())
    if count > MAX_INSTRUCTIONS:
        raise ValueError('Executed transfer inspection budget exceeded; no prefix certifies the set')
    return [(path, instruction) for index, instruction in enumerate(outer)
            for path, instruction in [(f'transaction.message.instructions.{index}', instruction)] + groups.get(index, [])]


def _version(record, wallet):
    """Derive only transfer facts from one immutable native representation."""
    digest, raw = record.get('evidence_hash'), record.get('raw')
    evidence = [digest]
    result = {'movements': [], 'gaps': [], 'failed': None, 'gross_in': 0, 'gross_out': 0,
              'self_transfer': 0, 'paths': []}
    try:
        if not isinstance(raw, dict) or not supported_transaction_format(raw):
            raise ValueError('Original native record is missing or unsupported')
        transaction, meta = raw.get('transaction'), raw.get('meta')
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        if (not isinstance(signatures, list) or not signatures or signatures[0] != record.get('signature')
                or not isinstance(meta, dict) or 'err' not in meta):
            raise ValueError('Original signature or execution result is unresolved')
        result['failed'] = meta['err'] is not None
        if result['failed']:
            result['paths'] = ['meta.err']
            return result  # Attempted instructions did not move funds.
        context = resolve_account_keys(raw)
        keys = context['keys']
        normalized = normalize_transaction(raw) if _needs_instruction_view(raw) else None
        view = normalized['raw'] if normalized is not None else raw
        inner_recording = isinstance(meta.get('innerInstructions'), list)
        for path, instruction in _instructions(view):
            try:
                inspection = inspect_instruction(instruction, keys, path=path)
                if inspection['program'] != SYSTEM_ID:
                    if (path.startswith('transaction.') and not inner_recording
                            and not inspection['non_economic'] and wallet in inspection['references']):
                        # An opaque wallet-touching program may invoke a
                        # System transfer. Net endpoints can hide cancelling
                        # gross movements; an unrecorded CPI is not an empty
                        # recorded list. Explicitly disjoint instructions and
                        # non-CPI System/Compute/Memo builtins retain their
                        # independent transfer observations.
                        result['paths'] += inspection['paths'] + [
                            'meta.innerInstructions' if 'innerInstructions' in meta else 'meta']
                        raise ValueError('Wallet-touching CPI inner transfer recording is unavailable')
                    continue
                if SYSTEM_ID not in keys or instruction.get('program') not in (None, 'system'):
                    raise ValueError('System program identity disagrees with the primary instruction schema')
                parsed = instruction.get('parsed')
                kind = parsed.get('type') if isinstance(parsed, dict) else None
                if kind != 'transfer':
                    # Other System operations are outside this transfer-only
                    # population. Unsupported opaque System instructions may
                    # themselves be transfers and cannot certify its absence.
                    if not isinstance(parsed, dict):
                        raise ValueError('System instruction has no supported transfer interpretation')
                    continue
                info = parsed.get('info')
                if not isinstance(info, dict) or set(info) != {'source', 'destination', 'lamports'}:
                    raise ValueError('System transfer fields disagree with the reviewed RPC schema')
                source, destination, lamports = info['source'], info['destination'], info['lamports']
                if (not _valid_account(source) or not _valid_account(destination)
                        or keys.count(source) != 1 or keys.count(destination) != 1
                        or type(lamports) is not int or not 0 <= lamports <= U64_MAX):
                    raise ValueError('System transfer identities or u64 quantity are invalid')
                if path.startswith('transaction.') and source not in context['signers']:
                    raise ValueError('Outer System transfer source lacks primary signer evidence')
                if wallet not in (source, destination):
                    continue
                direction = ('self' if source == destination == wallet else
                             'out' if source == wallet else 'in')
                paths = original_instruction_paths(raw,
                    inspection['paths'] + [path + '.parsed.info.lamports'], normalized=normalized)
                row = {'source': source, 'destination': destination, 'lamports': str(lamports),
                       'direction': direction, 'raw_paths': paths, 'evidence': [digest],
                       'check': _check(True, 'Executed System transfer has exact primary identities and quantity.', evidence, paths),
                       'economic_role': 'UNKNOWN'}
                result['movements'].append(row)
                result['paths'] += paths
                result['gross_' + direction if direction != 'self' else 'self_transfer'] += lamports
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                result['gaps'].append(str(exc))
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result['gaps'].append(str(exc))
    return result


def _semantics(value):
    return value['failed'], [(row['source'], row['destination'], row['lamports'], row['direction'])
                             for row in value['movements']]


def project_native_cash_observations(*, selected, raw_versions, wallet, window, consistency, chronology):
    """Internal projection of fresh shared interpreters; no imported receipts.

    Normal report construction supplies selected/raw_versions and source/clock
    derivations from the same current original evidence. The public wrapper
    below establishes those bindings independently for standalone replay.
    """
    if not _valid_account(wallet):
        raise ValueError('A valid public wallet address is required')
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('A positive observation window is required')
    if sum(len(rows) for rows in raw_versions.values()) > SOURCE_HASH_LIMIT:
        raise ValueError('Native transfer sources exceed the fixed record budget')
    result = {'version': VERSION, 'scope': SCOPE, 'wallet_population_state': 'UNKNOWN',
              'economic_roles_state': 'UNKNOWN', 'qualification': False,
              'transactions': {}, 'intervals': {}, 'provider_requests': 0, 'credential_lookups': 0}
    source_set = consistency.get('source_set', {})
    for signature in sorted(selected):
        versions = list(raw_versions.get(signature, []))
        facts = [_version(row, wallet) for row in versions]
        primary = next((value for row, value in zip(versions, facts)
                        if row.get('evidence_hash') == selected[signature].get('evidence_hash')), None)
        hashes = [row.get('evidence_hash') for row in versions]
        group = consistency.get('transactions', {}).get(signature, {})
        identity = group.get('identity', {})
        execution = group.get('native', {}).get('checks', {}).get('execution', {})
        agree = primary is not None and bool(facts) and all(_semantics(row) == _semantics(primary) for row in facts)
        gaps = sorted({gap for value in facts for gap in value['gaps']})
        known = (agree and not gaps and source_set.get('state') == identity.get('state') == 'PASS'
                 and execution.get('state') == 'PASS')
        reason = ('Every linked native version supports the same executed gross System transfers.' if known else
                  '; '.join(gaps) or 'Frozen source identity, execution, source inventory or alternative transfer facts disagree.')
        check = _check(known, reason, hashes + source_set.get('evidence', []),
                       (path for value in facts for path in value['paths']))
        native_fee = group.get('native', {}).get('wallet_network_fees_sol', {})
        fee_lamports = None
        if native_fee.get('state') == 'PASS':
            from .investigation import _keys
            raw = selected[signature].get('raw')
            if isinstance(raw, dict) and isinstance(raw.get('meta'), dict):
                keys = _keys(raw['transaction']['message'], raw['meta'])
                value = raw['meta'].get('fee') if keys and keys[0] == wallet else 0 if keys else None
                if type(value) is int and 0 <= value <= U64_MAX:
                    fee_lamports = str(value)
        movements = [{**row, 'check': _check(known, reason, check['evidence'], row['raw_paths'])}
                     for row in primary['movements']] if primary is not None else []
        result['transactions'][signature] = {
            'gross_in_lamports': str(primary['gross_in']) if known else None,
            'gross_out_lamports': str(primary['gross_out']) if known else None,
            'transfer_net_lamports': str(primary['gross_in'] - primary['gross_out']) if known else None,
            'self_transfer_lamports': str(primary['self_transfer']) if known else None,
            'failed': primary['failed'] if primary is not None else None,
            'movements': movements,
            'transfer_check': check,
            'network_fee': {'lamports': fee_lamports, 'check': _check(fee_lamports is not None,
                native_fee.get('reason', 'Wallet-paid raw network fee is unresolved'), native_fee.get('evidence', hashes))},
            'economic_role': _check(False,
                'Direction alone does not establish capital, payment, tip, consideration or economic cost.', hashes),
            'gaps': gaps}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        totals, checks, memberships, evidence, paths = {'in': 0, 'out': 0}, [], {}, [], []
        for signature, row in result['transactions'].items():
            membership = assess_interval_membership(chronology, signature, begin, end)
            memberships[signature] = membership
            if membership['state'] == 'PASS' and membership.get('member') is False:
                # A proved exclusion contributes exact selected-scope zero.
                # Its original clock dependencies remain in the receipt so
                # losing that proof cannot silently retain the zero result.
                # The clock can exclude this named record, but it cannot
                # exclude an unassignable still-linked record from the
                # selected source inventory. Keep that independent guard
                # without requiring outside-window transfer/fee decoding.
                checks.append(source_set.get('state') == 'PASS')
                evidence += membership['evidence'] + source_set.get('evidence', [])
                continue
            check = row['transfer_check']
            zero = check['state'] == 'PASS' and row['gross_in_lamports'] == row['gross_out_lamports'] == '0'
            known = check['state'] == 'PASS' and (membership['state'] == 'PASS' or zero)
            checks.append(known)
            evidence += check['evidence'] + membership['evidence']
            paths += check['raw_paths']
            if known:
                totals['in'] += int(row['gross_in_lamports'])
                totals['out'] += int(row['gross_out_lamports'])
        known = bool(checks) and all(checks)
        result['intervals'][name] = {'start': begin.isoformat(), 'end': end.isoformat(),
            'gross_in_lamports': str(totals['in']) if known else None,
            'gross_out_lamports': str(totals['out']) if known else None,
            'transfer_net_lamports': str(totals['in'] - totals['out']) if known else None,
            'check': _check(known, 'Each selected nonzero gross transfer has independently supported interval placement; '
                'these totals do not certify a complete wallet population.', evidence, paths),
            'memberships': memberships, 'wallet_population_state': 'UNKNOWN', 'economic_roles_state': 'UNKNOWN'}
    return result


def derive_native_cash_observations(records, *, all_records, wallet, window, raw_sources=(), source_receipts=()):
    """Standalone replay from hash-bound bodies/indexed pointers and originals."""
    from .wallet_positions import _verified_records
    from .wallet_evidence import _resolved_sources, _clock_inputs, raw_native_dependencies
    records, all_records = list(records), list(all_records)
    if len(records) > SOURCE_HASH_LIMIT or len(all_records) > SOURCE_HASH_LIMIT:
        raise ValueError('Native transfer sources exceed the fixed record budget')
    if any(not isinstance(row, dict) or not isinstance(row.get('signature'), str) or not row['signature']
           for row in records):
        raise ValueError('Selected transfer records require explicit signature identities')
    sources = _resolved_sources(list(raw_sources), list(source_receipts))
    selected = _verified_records(records, sources)
    selected_by_signature = {}
    for row in sorted(selected, key=lambda value: str(value.get('evidence_hash'))):
        selected_by_signature.setdefault(row['signature'], row)
    negative = raw_native_dependencies(sources, (), selected_by_signature)
    versions = defaultdict(dict)
    for row in _verified_records(all_records + records + negative, sources):
        key, digest = row.get('signature'), row.get('evidence_hash')
        if digest in versions[key] and versions[key][digest].get('raw') != row.get('raw'):
            versions[key][digest] = {**versions[key][digest], 'raw': None}
        else:
            versions[key].setdefault(digest, row)
    linked = [row for key in sorted(versions, key=repr) for digest, row in sorted(versions[key].items(), key=lambda pair: repr(pair[0]))]
    pages, blocks, indexed, contents = _clock_inputs(sources, (), wallet)
    consistency = assess_source_consistency(linked, wallet=wallet, page_receipts=pages,
        indexed_receipts=indexed, archive_contents=contents)
    chronology = apply_unresolved_chronology(assess_chronology(linked, page_receipts=pages,
        block_receipts=blocks, indexed_receipts=indexed), linked, contents)
    return project_native_cash_observations(selected=selected_by_signature,
        raw_versions={key: list(rows.values()) for key, rows in versions.items()},
        wallet=wallet, window=window, consistency=consistency, chronology=chronology)
