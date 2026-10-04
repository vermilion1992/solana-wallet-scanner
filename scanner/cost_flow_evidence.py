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
from .accounting import raw_quantity
from .decoder import ASSOCIATED_ID, SYSTEM_ID, TOKEN_IDS
from .instruction_scope import inspect_instruction
from .investigation import WSOL
from .native_cash_observations import _instructions
from .providers import TOKEN_PROGRAM
from .position_evidence import _balance
from .transaction_format import _needs_instruction_view, original_instruction_paths

VERSION = 'raw-cost-flow-roles-v2'
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


def _refund_cash_trace(raw, view, instructions, context, observed, wallet, normalized):
    """Replay supported original account cash within this transaction, not P&L.

    Every intermediate balance is u64, closed accounts cannot be reused, and
    opaque relevant writes stay dependencies. Exact token units/owners/lifecycle
    are still supplied by the shared interpreter. Ordered gross effects remain
    in refund semantics so cancelling movements cannot masquerade as absence.
    """
    keys = context['keys']
    cash = dict(zip(keys, raw['meta']['preBalances']))
    units, native_accounts, closed, touched, native_post = {}, set(), set(), set(), {}
    effects, paths, reasons = defaultdict(list), defaultdict(list), defaultdict(list)
    denomination_paths = defaultdict(list)
    refunds = {}
    for account, pair in observed.get('boundaries', {}).items():
        point = pair.get('pre') if isinstance(pair, dict) else None
        if (isinstance(point, dict) and pair.get('program') == TOKEN_PROGRAM
                and point.get('mint') == WSOL and point.get('decimals') == 9):
            native_accounts.add(account)
            units[account] = raw_quantity(point['quantity']) if _usable(pair.get('checks', {}).get('quantities')) else None
            native_post[account] = raw_quantity(pair['post']['quantity']) if isinstance(pair.get('post'), dict) else None
            denomination_paths[account] += [pair[phase]['path'] for phase in ('pre', 'post')
                                           if isinstance(pair.get(phase), dict) and isinstance(pair[phase].get('path'), str)]
    # Cash denomination is independent of economic ownership. Foreign peers
    # can prove exact canonical WSOL cash effects from original boundaries,
    # without making their external transfers acquisitions, income or basis.
    candidates = {info.get(field) for _, instruction in instructions
        if isinstance(instruction, dict) and instruction.get('programId') == TOKEN_PROGRAM
        and isinstance(instruction.get('parsed'), dict)
        and isinstance((info := instruction['parsed'].get('info')), dict)
        for field in ('source', 'destination') if isinstance(info.get(field), str)}
    for account in candidates - native_accounts:
        try:
            pre = _balance(raw, keys, account, 'preTokenBalances')
            post = _balance(raw, keys, account, 'postTokenBalances')
            if (all(point['program_id'] == TOKEN_PROGRAM and point['mint'] == WSOL and point['decimals'] == 9
                    for point in (pre, post)) and pre['owner'] == post['owner']):
                native_accounts.add(account)
                units[account], native_post[account] = pre['quantity'], post['quantity']
                denomination_paths[account] += [pre['path'], post['path']]
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    for account in native_accounts:
        if units[account] is None or cash[account] < units[account]:
            cash[account], units[account] = None, None
            reasons[account].append('Canonical native cash is smaller than its required token units or units are unsupported')
    fee = raw['meta'].get('fee')
    fee_missing = fee is None
    if type(fee) is int and 0 <= fee <= U64_MAX and cash[keys[0]] is not None and cash[keys[0]] >= fee:
        cash[keys[0]] -= fee
    else:
        cash[keys[0]] = None  # Missing fee does not invent a target cash balance.
    possible_cash = {account: (value, value) if value is not None else None for account, value in cash.items()}
    if fee_missing and not reasons[keys[0]]:
        # The missing debit is nonnegative. Its exact value is unknown, but
        # successful later operations still cannot spend above opening cash.
        possible_cash[keys[0]] = (0, raw['meta']['preBalances'][0])

    def reject(accounts, reason, source_paths):
        for account in accounts:
            if account in cash:
                cash[account] = None
                possible_cash[account] = None
                units[account] = None
                reasons[account].append(reason)
                paths[account] += source_paths

    def move(kind, source, destination, amount, source_paths, *, token=False):
        if (source not in cash or destination not in cash or type(amount) is not int
                or not 0 <= amount <= U64_MAX or source in closed or destination in closed):
            raise ValueError('Native cash movement lacks unique live primary accounts or exact u64 quantity')
        if cash[source] is not None and cash[source] < amount:
            raise ValueError('Original native cash movement exceeds its intermediate source balance')
        source_bounds, destination_bounds = possible_cash[source], possible_cash[destination]
        if source_bounds is not None:
            lower, upper = source_bounds
            if upper < amount:
                raise ValueError('Original native cash movement exceeds every possible intermediate source balance')
            possible_cash[source] = ((max(lower, amount), upper) if source == destination else
                                     (max(0, lower - amount), upper - amount))
        if source != destination and destination_bounds is not None:
            lower, upper = destination_bounds
            if lower + amount > U64_MAX:
                raise ValueError('Original native cash movement overflows every possible destination balance')
            possible_cash[destination] = (lower + amount, min(U64_MAX, upper + amount))
        if token:
            if source not in native_accounts or destination not in native_accounts or units.get(source) is None or units.get(destination) is None:
                raise ValueError('Native token cash movement requires supported canonical ownership/unit endpoints on both accounts')
            if units[source] < amount:
                raise ValueError('Native token movement exceeds its intermediate source units')
            if source != destination:
                units[source] -= amount
                units[destination] += amount
                if units[destination] > U64_MAX:
                    raise ValueError('Native token movement exceeds its intermediate destination u64 units')
            source_paths = source_paths + denomination_paths[source] + denomination_paths[destination]
        if source != destination:
            if cash[source] is not None:
                cash[source] -= amount
            if cash[destination] is not None:
                cash[destination] += amount
                if cash[destination] > U64_MAX:
                    raise ValueError('Original native cash movement exceeds its intermediate destination u64 balance')
        if token and any(cash[account] is not None and cash[account] < units[account] for account in (source, destination)):
            raise ValueError('Canonical native cash is smaller than its intermediate token units')
        effect = {'kind': kind, 'source': source, 'destination': destination, 'lamports': str(amount)}
        for account in set((source, destination)):
            touched.add(account)
            effects[account].append(effect)
            paths[account] += source_paths

    zero_token = {'initializeAccount', 'initializeAccount2', 'initializeAccount3', 'syncNative',
                  'approve', 'approveChecked', 'revoke', 'freezeAccount', 'thawAccount',
                  'initializeImmutableOwner', 'getAccountDataSize', 'setAuthority'}
    for position, (path, instruction) in enumerate(instructions):
        references = set()
        source_paths = [path]
        try:
            inspection = inspect_instruction(instruction, keys, path=path)
            references = inspection['references'] & set(keys)
            source_paths = original_instruction_paths(raw, inspection['paths'] + [path + '.parsed.info'], normalized=normalized)
            if inspection['non_economic']:
                continue
            program = inspection['program']
            parsed = instruction.get('parsed')
            info = parsed.get('info') if isinstance(parsed, dict) else None
            kind = parsed.get('type') if isinstance(parsed, dict) else None
            if not isinstance(info, dict) or program not in keys:
                raise ValueError('Opaque relevant instruction has no exact native cash contract')
            if program == SYSTEM_ID and kind == 'transfer':
                if set(info) != {'source', 'destination', 'lamports'}:
                    raise ValueError('Native transfer fields differ from the reviewed RPC schema')
                if path.startswith('transaction.') and info['source'] not in context['signers']:
                    raise ValueError('Outer native cash source lacks primary signer evidence')
                move('system_transfer', info['source'], info['destination'], info['lamports'], source_paths)
            elif program == SYSTEM_ID and kind == 'createAccount':
                if set(info) != {'source', 'newAccount', 'owner', 'lamports', 'space'} or info.get('newAccount') not in cash:
                    raise ValueError('Native creation fields differ from the reviewed RPC schema')
                if cash[info['newAccount']] != 0 or info['newAccount'] in closed:
                    raise ValueError('Native creation/recreation lacks a supported zero lifecycle origin')
                if path.startswith('transaction.') and info['source'] not in context['signers']:
                    raise ValueError('Outer native creation lacks primary source signer')
                move('system_creation', info['source'], info['newAccount'], info['lamports'], source_paths)
            elif program == TOKEN_PROGRAM and kind in ('transfer', 'transferChecked'):
                source, destination = info.get('source'), info.get('destination')
                if source not in native_accounts and destination not in native_accounts:
                    # Shared token interpretation independently decides these
                    # units. They are cash-zero only for proved nonnative mints.
                    peers = [observed.get('boundaries', {}).get(account) for account in (source, destination)]
                    if not all(isinstance(pair, dict) and isinstance(pair.get('pre'), dict)
                               and pair['pre'].get('mint') != WSOL for pair in peers):
                        raise ValueError('Unclassified token movement has no native cash exclusion proof')
                    continue
                fields = {'source', 'destination', 'authority'} | ({'mint', 'tokenAmount'} if kind == 'transferChecked' else {'amount'})
                if set(info) != fields or info.get('authority') not in keys:
                    raise ValueError('Native token transfer lacks the reviewed single-authority schema')
                if path.startswith('transaction.') and info['authority'] not in context['signers']:
                    raise ValueError('Outer native token transfer lacks primary authority signer')
                token = info.get('tokenAmount')
                if kind == 'transferChecked' and (not isinstance(token, dict) or info['mint'] != WSOL
                        or WSOL not in keys or type(token.get('decimals')) is not int or token['decimals'] != 9
                        or set(token) - {'amount', 'decimals', 'uiAmount', 'uiAmountString'}):
                    raise ValueError('Checked native cash transfer disagrees with canonical mint/decimals')
                amount = raw_quantity(token.get('amount') if kind == 'transferChecked' else info.get('amount'))
                move('native_token_transfer', source, destination, amount, source_paths, token=True)
            elif program in TOKEN_IDS and kind == 'closeAccount':
                account = info.get('account')
                if (set(info) != {'account', 'destination', 'owner'} or account not in cash
                        or info.get('destination') not in cash or info.get('owner') not in keys):
                    raise ValueError('Native close lacks the reviewed single-authority primary account schema')
                if path.startswith('transaction.') and info['owner'] not in context['signers']:
                    raise ValueError('Outer native close lacks primary authority signer')
                amount = cash[account]
                if account in closed or info['destination'] in closed or account == info['destination']:
                    raise ValueError('Closure needs distinct live source and refund destination accounts')
                refund = {'lamports': str(amount) if amount is not None else None,
                    'reason': '; '.join(sorted(set(reasons[account]))) if amount is None else None,
                    'cash_effects': list(effects[account]), 'cash_accounts': {account, info['destination']},
                    'raw_paths': paths[account] + source_paths + [f'meta.preBalances.{keys.index(account)}']}
                for effect in refund['cash_effects']:
                    refund['cash_accounts'].update((effect['source'], effect['destination']))
                if amount is not None:
                    move('account_refund', account, info['destination'], amount, source_paths)
                else:
                    reject({info['destination']}, 'Required source cash before closure is unavailable', source_paths)
                cash[account] = 0
                possible_cash[account] = (0, 0)
                units[account] = 0
                closed.add(account)
                refunds[position] = refund
            elif program in TOKEN_IDS and kind in zero_token:
                # syncNative moves no cash. Unknown native/extension writes
                # never share this zero-effect whitelist.
                if kind == 'syncNative' and info.get('account') in native_accounts:
                    pair = observed['boundaries'][info['account']]
                    reserve = raw['meta']['preBalances'][keys.index(info['account'])] - int(pair['pre']['quantity'])
                    if cash[info['account']] is None or reserve < 0 or cash[info['account']] < reserve:
                        raise ValueError('Native sync lacks independently supported cash/reserve')
                    units[info['account']] = cash[info['account']] - reserve
            elif program == ASSOCIATED_ID and kind in ('create', 'createIdempotent'):
                if (set(info) != {'source', 'account', 'wallet', 'mint', 'systemProgram', 'tokenProgram'}
                        or info['systemProgram'] != SYSTEM_ID or info['tokenProgram'] not in TOKEN_IDS
                        or not isinstance(raw['meta'].get('innerInstructions'), list)):
                    raise ValueError('Associated wrapper lacks its exact reviewed CPI recording contract')
                # This builtin funds through separately recorded System CPIs;
                # it contributes no second direct native transfer.
            else:
                raise ValueError('Relevant instruction cash effect is unsupported')
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
            reject(references, str(exc), source_paths)
    mismatches = {account for account in touched if cash[account] is not None
                  and cash[account] != raw['meta']['postBalances'][keys.index(account)]}
    mismatches.update(account for account in touched & native_accounts
        if units[account] is not None and units[account] != native_post.get(account))
    mismatches.update(account for account in touched if possible_cash[account] is not None
        and not possible_cash[account][0] <= raw['meta']['postBalances'][keys.index(account)] <= possible_cash[account][1])
    for refund in refunds.values():
        refund['raw_paths'] += [f'meta.{phase}Balances.{keys.index(account)}'
            for account in sorted(refund['cash_accounts']) for phase in ('pre', 'post')]
        if keys[0] in refund['cash_accounts']:
            refund['raw_paths'].append('meta.fee')
        if (refund['cash_accounts'] & mismatches
                or any(cash[account] is None and not (account == keys[0] and fee_missing and not reasons[account])
                       for account in refund['cash_accounts'])):
            refund.update(lamports=None, reason='Reconstructed native cash disagrees with a required original closing account endpoint')
    return refunds


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
        refund_cash = _refund_cash_trace(raw, view, instructions, context, observed, wallet, normalized)
        authority_overrides = set()
        for _, instruction in instructions:
            parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) else None
            if (isinstance(info, dict) and parsed.get('type') == 'setAuthority'
                    and info.get('authorityType') in ('accountOwner', 'closeAccount')):
                authority_overrides.add(info.get('account'))
        created = set()
        proved_closures = {}
        for position, (path, instruction) in enumerate(instructions):
            parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) else None
            if (instruction.get('programId') not in TOKEN_IDS or not isinstance(info, dict)
                    or parsed.get('type') != 'closeAccount' or set(info) != {'account', 'destination', 'owner'}
                    or info.get('owner') != wallet or info.get('destination') != wallet
                    or info.get('account') in authority_overrides
                    or refund_cash.get(position, {}).get('lamports') is None
                    or (path.startswith('transaction.') and wallet not in context['signers'])):
                continue
            try:
                account = info['account']
                pair = _pair(observed, account, wallet)
                native = pair['program'] == TOKEN_PROGRAM and pair['pre'].get('mint') == WSOL and pair['pre'].get('decimals') == 9
                if (pair['program'] == instruction['programId'] and after[keys.index(account)] == 0
                        and pair['post'].get('quantity') == '0'
                        and (native or pair['pre'].get('quantity') == '0')):
                    proved_closures[account] = position
            except (ValueError, TypeError, KeyError, IndexError):
                continue
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
                    # present in this record. Existing funding needs an exact
                    # later executed wallet refund or canonical native units.
                    if account in authority_overrides:
                        continue
                    if account not in created:
                        native_principal = (pair['program'] == TOKEN_PROGRAM
                            and all(pair[phase].get('mint') == WSOL and pair[phase].get('decimals') == 9
                                    for phase in ('pre', 'post'))
                            and any(sync > position for sync in native_sync_paths[account])
                            and int(pair['post']['quantity']) - int(pair['pre']['quantity']) == native_funding[account]
                            and after[keys.index(account)] - before[keys.index(account)] == native_funding[account])
                        if not native_principal and proved_closures.get(account, -1) <= position:
                            continue
                    if (type(amount) is not int or not 0 <= amount <= U64_MAX or keys.count(account) != 1
                            or (path.startswith('transaction.') and wallet not in context['signers'])):
                        raise ValueError('Wallet-owned funding lacks the original source or exact u64 units')
                    role, lamports = ('wallet_owned_account_funding' if account in created or account in proved_closures else
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
                    refund = refund_cash.get(position, {})
                    if refund.get('lamports') is None:
                        raise ValueError(refund.get('reason') or 'Exact refund requires supported original ordered native cash movements')
                    role, lamports = 'wallet_owned_account_refund', refund['lamports']
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
                if role == 'wallet_owned_account_refund':
                    roles[_event_path(path, view)].update(cash_effects=refund['cash_effects'],
                        raw_paths=sorted(set(paths + refund['raw_paths'])))
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
    return Counter((row['role'], row['account'], row['program'], row['lamports'],
        tuple((effect['kind'], effect['source'], effect['destination'], effect['lamports'])
              for effect in row.get('cash_effects', []))) for row in roles.values())


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
                             ('wallet_owned_native_principal', 'wallet_owned_account_refund', 'wallet_owned_account_funding')}
            for row in admitted:
                if row['role'] == 'wallet_owned_account_refund':
                    for effect in row.get('cash_effects', []):
                        if effect['kind'] == 'native_token_transfer':
                            role_accounts.update((effect['source'], effect['destination']))
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
