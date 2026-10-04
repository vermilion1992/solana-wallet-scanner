"""Admit proved internal native representation changes to the existing ledger.

Account creation/funding and token-account closure are not automatically fees,
capital flows or income. When original executed instructions and every linked
account boundary establish wallet ownership, they are internal native movement.
The ordinary endpoint reconciler still has to explain the complete transaction.
External transfers keep their unresolved economic roles, even if they net to zero.
This module supplies events to the existing FIFO, never a second P&L calculator.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import re

from .compiled_instructions import normalize_transaction, resolve_account_keys
from .decoder import ASSOCIATED_ID, SYSTEM_ID, TOKEN_IDS
from .instruction_scope import inspect_instruction
from .investigation import WSOL
from .native_cash_observations import _instructions
from .providers import TOKEN_PROGRAM
from .transaction_format import _needs_instruction_view, original_instruction_paths

VERSION = 'raw-cost-flow-roles-v1'
HASH = re.compile(r'^[a-f0-9]{64}$')
U64_MAX = 2**64 - 1
MAX_EVENTS = 200_000
SCOPE = 'Original selected transaction roles; complete historical wallet population is independently required'


def _check(known, reason, evidence=(), paths=()):
    hashes = sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'reason': reason,
            'evidence': hashes, 'raw_paths': sorted(set(paths)), 'scope': SCOPE}


def _usable(check):
    return isinstance(check, dict) and check.get('state') == 'PASS' and bool(check.get('evidence'))


def _pair(observed, account, wallet):
    pair = observed.get('boundaries', {}).get(account)
    if (not isinstance(pair, dict) or pair.get('program') not in TOKEN_IDS
            or not all(_usable(pair.get('checks', {}).get(k)) for k in ('ownership', 'quantities', 'lifecycle'))
            or any(not isinstance(pair.get(phase), dict) or pair[phase].get('owner') != wallet
                   for phase in ('pre', 'post'))):
        raise ValueError('Internal native role needs agreeing event-time wallet ownership, units and lifecycle')
    return pair


def _event_path(path, raw):
    if path.startswith('transaction.message.'):
        return path[len('transaction.message.'):]
    parts = path.split('.')
    group = raw['meta']['innerInstructions'][int(parts[2])]
    return f"innerInstructions.{group['index']}.{parts[4]}"


def _prior_native_mutation(instructions, position, account, keys, *, native):
    """Do not present an opening lamport endpoint as an intratx refund.

    The current role contract has no intermediate account-cash reconstructor.
    Earlier native-affecting operations therefore retain that dependency rather
    than misreporting an exact refund. Proven unrelated/token-only operations
    remain separately usable.
    """
    for path, instruction in instructions[:position]:
        inspection = inspect_instruction(instruction, keys, path=path)
        if account not in inspection['references'] or inspection['non_economic']:
            continue
        parsed = instruction.get('parsed')
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if inspection['program'] == SYSTEM_ID:
            if kind not in ('allocate', 'allocateWithSeed', 'assign', 'assignWithSeed'):
                return True
        elif inspection['program'] in TOKEN_IDS:
            if kind == 'closeAccount' or native and kind in ('transfer', 'transferChecked', 'mintTo', 'mintToChecked', 'burn', 'burnChecked'):
                return True
        else:
            return True
    return False


def _roles(record, observed, wallet):
    raw = record.get('raw')
    roles, gaps = {}, []
    try:
        if not isinstance(raw, dict) or not isinstance(raw.get('meta'), dict) or 'err' not in raw['meta']:
            raise ValueError('Original executed native record is unavailable')
        if raw['meta']['err'] is not None:
            return roles, gaps  # Atomic failure has no committed administration.
        context = resolve_account_keys(raw)
        keys = context['keys']
        normalized = normalize_transaction(raw) if _needs_instruction_view(raw) else None
        view = normalized['raw'] if normalized is not None else raw
        before, after = raw['meta'].get('preBalances'), raw['meta'].get('postBalances')
        if (not isinstance(before, list) or not isinstance(after, list) or len(before) != len(keys)
                or len(after) != len(keys) or any(type(v) is not int or not 0 <= v <= U64_MAX for v in before + after)):
            raise ValueError('Native internal roles need the complete exact u64 endpoint arrays')
        instructions = _instructions(view)
        authority_overrides = set()
        for _, instruction in instructions:
            parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) else None
            if (isinstance(info, dict) and parsed.get('type') == 'setAuthority'
                    and info.get('authorityType') in ('accountOwner', 'closeAccount')):
                authority_overrides.add(info.get('account'))
        created = set()
        deferred = []
        native_funding = Counter()
        native_sync_paths = defaultdict(list)
        for position, (_, instruction) in enumerate(instructions):
            parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) else None
            if not isinstance(info, dict):
                continue
            if instruction.get('programId') == SYSTEM_ID and parsed.get('type') == 'transfer':
                amount = info.get('lamports')
                if (info.get('source') == wallet and type(amount) is int and 0 <= amount <= U64_MAX
                        and isinstance(info.get('destination'), str)):
                    native_funding[info['destination']] += amount
            if instruction.get('programId') == TOKEN_PROGRAM and parsed.get('type') == 'syncNative':
                if isinstance(info.get('account'), str):
                    native_sync_paths[info['account']].append(position)
        for position, (path, instruction) in enumerate(instructions):
            parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
            kind = parsed.get('type') if isinstance(parsed, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) else None
            program = instruction.get('programId') if isinstance(instruction, dict) else None
            candidate = ((program == SYSTEM_ID and kind in ('createAccount', 'transfer'))
                         or (program in TOKEN_IDS and kind in ('closeAccount', 'syncNative'))
                         or (program == ASSOCIATED_ID and kind in ('create', 'createIdempotent')))
            if not candidate:
                continue
            try:
                inspection = inspect_instruction(instruction, keys, path=path)
                if program not in keys or inspection['program'] != program or not isinstance(info, dict):
                    raise ValueError('Internal role program disagrees with the primary account keys')
                account, role, lamports = None, None, None
                if program == SYSTEM_ID and kind == 'createAccount':
                    if set(info) != {'source', 'newAccount', 'owner', 'lamports', 'space'}:
                        raise ValueError('Account creation fields differ from the reviewed RPC schema')
                    if info['source'] != wallet:
                        continue
                    account = info['newAccount']
                    pair = _pair(observed, account, wallet)
                    amount, space = info['lamports'], info['space']
                    if (info['owner'] != pair['program'] or type(amount) is not int or not 0 <= amount <= U64_MAX
                            or type(space) is not int or not 165 <= space <= 10_485_760
                            or keys.count(account) != 1 or before[keys.index(account)] != 0
                            or account in authority_overrides
                            or (path.startswith('transaction.') and wallet not in context['signers'])):
                        raise ValueError('Wallet-funded creation lacks exact program, source, size or zero native origin')
                    role, lamports = 'wallet_owned_account_funding', str(amount)
                    created.add(account)
                elif program == SYSTEM_ID and kind == 'transfer':
                    if set(info) != {'source', 'destination', 'lamports'}:
                        raise ValueError('Internal transfer fields differ from the reviewed RPC schema')
                    if info['source'] != wallet or info['destination'] == wallet:
                        continue
                    account = info['destination']
                    pair = observed.get('boundaries', {}).get(account)
                    if not isinstance(pair, dict):
                        continue  # An outside address has no invented economic role.
                    _pair(observed, account, wallet)
                    amount = info['lamports']
                    # A token owner field alone does not establish historical
                    # close/refund authority. New initialized accounts have
                    # protocol default authority only while no override is
                    # present in this record. Existing-account top-ups remain
                    # unresolved even when owned native endpoint sums net out.
                    if account in authority_overrides:
                        continue
                    if account not in created:
                        native_principal = (pair['program'] == TOKEN_PROGRAM
                            and all(pair[phase].get('mint') == WSOL and pair[phase].get('decimals') == 9
                                    for phase in ('pre', 'post'))
                            and any(sync > position for sync in native_sync_paths[account])
                            and int(pair['post']['quantity']) - int(pair['pre']['quantity']) == native_funding[account]
                            and after[keys.index(account)] - before[keys.index(account)] == native_funding[account])
                        if not native_principal:
                            continue
                    if (type(amount) is not int or not 0 <= amount <= U64_MAX or keys.count(account) != 1
                            or (path.startswith('transaction.') and wallet not in context['signers'])):
                        raise ValueError('Wallet-owned funding lacks the original source or exact u64 units')
                    role, lamports = ('wallet_owned_account_funding' if account in created else
                                     'wallet_owned_native_principal'), str(amount)
                elif program in TOKEN_IDS and kind == 'closeAccount':
                    if set(info) != {'account', 'destination', 'owner'}:
                        raise ValueError('Account closure fields differ from the reviewed single-owner RPC schema')
                    account = info['account']
                    pair = observed.get('boundaries', {}).get(account)
                    if not isinstance(pair, dict) or info['destination'] != wallet:
                        continue
                    pair = _pair(observed, account, wallet)
                    index = keys.index(account)
                    native = pair['pre'].get('mint') == WSOL and pair['program'] == TOKEN_PROGRAM and pair['pre'].get('decimals') == 9
                    if (pair['program'] != program or info['owner'] != wallet or after[index] != 0
                            or account in authority_overrides
                            or (not native and pair['pre'].get('quantity') != '0')
                            or pair['post'].get('quantity') != '0'
                            or (path.startswith('transaction.') and wallet not in context['signers'])):
                        raise ValueError('Internal closure needs wallet authority, an allowed quantity and zero native close endpoint')
                    if _prior_native_mutation(instructions, position, account, keys, native=native):
                        raise ValueError('Opening native balance is not an exact refund after a preceding native-affecting operation')
                    role, lamports = 'wallet_owned_account_refund', str(before[index])
                elif program in TOKEN_IDS and kind == 'syncNative':
                    if set(info) != {'account'}:
                        raise ValueError('Native synchronization fields differ from the reviewed RPC schema')
                    account = info['account']
                    pair = observed.get('boundaries', {}).get(account)
                    if not isinstance(pair, dict):
                        continue
                    pair = _pair(observed, account, wallet)
                    if (program != TOKEN_PROGRAM or pair['program'] != TOKEN_PROGRAM
                            or account in authority_overrides
                            or any(pair[phase].get('mint') != WSOL or pair[phase].get('decimals') != 9
                                   for phase in ('pre', 'post'))):
                        raise ValueError('Internal synchronization requires canonical legacy wrapped SOL')
                    role, lamports = 'wallet_owned_native_representation', '0'
                else:
                    deferred.append((path, info, inspection))
                    continue
                paths = original_instruction_paths(raw, inspection['paths'], normalized=normalized)
                roles[_event_path(path, view)] = {'role': role, 'account': account, 'program': program,
                    'lamports': lamports, 'raw_paths': paths}
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                gaps.append(str(exc))
        for path, info, inspection in deferred:
            account = info.get('account')
            if (set(info) != {'source', 'account', 'wallet', 'mint', 'systemProgram', 'tokenProgram'}
                    or info.get('systemProgram') != SYSTEM_ID
                    or info.get('tokenProgram') != observed.get('boundaries', {}).get(account, {}).get('program')
                    or account not in created or account in authority_overrides
                    or info.get('source') != wallet or info.get('wallet') != wallet
                    or info.get('mint') != observed.get('boundaries', {}).get(account, {}).get('post', {}).get('mint')):
                continue
            roles[_event_path(path, view)] = {'role': 'wallet_owned_account_creation', 'account': account,
                'program': ASSOCIATED_ID, 'lamports': '0',
                'raw_paths': original_instruction_paths(raw, inspection['paths'], normalized=normalized)}
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        gaps.append(str(exc))
    return roles, gaps


def _semantics(roles):
    return Counter((row['role'], row['account'], row['program'], row['lamports']) for row in roles.values())


def project_cost_flow_evidence(*, selected, raw_versions, transactions, consistency, ledger_events, wallet):
    """Consume fresh ordinary-path derivations and return existing-schema events.

    Linked sources remain mandatory. This is an internal composition seam, not a
    receipt importer; the normal caller replays all originals before using it.
    """
    if len(ledger_events) > MAX_EVENTS:
        raise ValueError('Cost/flow role events exceed the fixed ledger inspection budget')
    events = deepcopy(list(ledger_events))
    groups = defaultdict(list)
    for event in events:
        groups[event.get('signature')].append(event)
    receipts = {}
    for signature in sorted(selected):
        versions = list(raw_versions.get(signature, []))
        observed = transactions.get(signature, {})
        facts = [_roles(record, observed, wallet) for record in versions]
        primary = next((roles for record, (roles, _) in zip(versions, facts)
                        if record.get('evidence_hash') == selected[signature].get('evidence_hash')), None)
        source = consistency.get('transactions', {}).get(signature, {})
        checks = source.get('native', {}).get('checks', {})
        required = [consistency.get('source_set'), observed.get('checks', {}).get('identity'),
                    checks.get('transaction_format'), checks.get('execution')]
        gaps = sorted({gap for _, errors in facts for gap in errors})
        agrees = primary is not None and bool(facts) and all(_semantics(roles) == _semantics(primary) for roles, _ in facts)
        known = agrees and not gaps and all(_usable(check) for check in required)
        hashes = [record.get('evidence_hash') for record in versions]
        paths = [path for roles, _ in facts for row in roles.values() for path in row['raw_paths']]
        check = _check(known, 'Every linked original supports the same wallet-internal native administration roles.'
            if known else '; '.join(gaps) or 'Required linked identity, execution, format or internal-role facts disagree.', hashes, paths)
        admitted = []
        if known:
            for event in groups[signature]:
                role = primary.get(event.get('path'))
                if event.get('kind') not in ('rent', 'wrap', 'capital') or role is None:
                    continue
                original_kind = event['kind']
                event.update(kind='internal_transfer', original_kind=original_kind,
                    economic_role=role['role'], native_movement_lamports='0',
                    reason='Executed movement retains lamports within evidenced wallet-owned accounts; it creates no purchase, fee or income.',
                    evidence=check['evidence'], raw_paths=role['raw_paths'])
                admitted.append({'event_path': event['path'], **role, 'check': check})
            # The generic decoder retains an auxiliary mint-aggregate WSOL
            # delta. It is corroboration, not a second economic movement, only
            # when EVERY changing owned native account has a proved sync or
            # closure role. Net equality or a single account cannot discharge
            # other accounts/unsupported native movements.
            changing, native_scope_complete = [], True
            for account, pair in observed.get('boundaries', {}).items():
                if not isinstance(pair, dict):
                    native_scope_complete = False
                    continue
                phases = [pair.get(phase) for phase in ('pre', 'post')]
                native_phase = any(isinstance(point, dict) and point.get('mint') == WSOL
                                   and point.get('owner') == wallet for point in phases)
                if not native_phase:
                    if not any(isinstance(point, dict) and point.get('mint') != WSOL for point in phases):
                        native_scope_complete = False
                    continue
                if (not all(isinstance(point, dict) and point.get('owner') == wallet and point.get('mint') == WSOL
                            and point.get('decimals') == 9 for point in phases)
                        or pair.get('program') != TOKEN_PROGRAM
                        or not all(_usable(pair.get('checks', {}).get(key)) for key in ('ownership', 'quantities', 'lifecycle'))):
                    native_scope_complete = False
                    continue
                if pair['pre']['quantity'] != pair['post']['quantity']:
                    changing.append(account)
            role_accounts = {row['account'] for row in admitted if row['role'] in
                             ('wallet_owned_native_principal', 'wallet_owned_account_refund')}
            observed_units_known = native_scope_complete and bool(changing) and all(account in role_accounts
                and observed['boundaries'][account]['program'] == TOKEN_PROGRAM
                and all(observed['boundaries'][account][phase].get('mint') == WSOL
                        and observed['boundaries'][account][phase].get('decimals') == 9 for phase in ('pre', 'post'))
                and all(_usable(observed['boundaries'][account]['checks'].get(key))
                        for key in ('ownership', 'quantities', 'lifecycle')) for account in changing)
            if observed_units_known:
                for event in groups[signature]:
                    if event.get('kind') == 'wrap' and event.get('path') == 'meta.tokenBalances' and event.get('mint') == WSOL:
                        event.update(kind='internal_transfer', original_kind='wrap',
                            economic_role='corroborating_native_units', native_movement_lamports='0',
                            evidence=check['evidence'], raw_paths=check['raw_paths'],
                            reason='Every changed native-account unit is already bound to a supported original sync/closure role; this aggregate is no second movement.')
        receipts[signature] = {'check': check, 'admitted_internal_roles': admitted,
            'unresolved_economic_paths': sorted({event.get('path', 'meta') for event in groups[signature]
                if event.get('kind') not in ('buy', 'sell', 'fee', 'internal_transfer')}),
            'wallet_population_state': 'UNKNOWN'}
    return {'version': VERSION, 'scope': SCOPE, 'ledger_events': events, 'transactions': receipts,
            'provider_requests': 0, 'credential_lookups': 0, 'qualification': False}
