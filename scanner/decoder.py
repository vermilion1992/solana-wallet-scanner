"""Conservative native-RPC decoder: observed transfers and wallet-paid fees.

There are intentionally no trusted DEX swap adapters in this release. Parsed token
transfers inside unknown programs are evidence of movement, not proven buys/sells.
Balance deltas never manufacture swaps, prices, meme classifications or free basis.
Unknown programs, missing metadata, authority changes and non-reconciled movements
produce explicit unsupported events. Extending this decoder requires independently
reviewed raw fixtures for each route and version, including allocation of fees.
"""
from collections import Counter, defaultdict
from decimal import Decimal

from .accounting import raw_quantity, canonical

TOKEN_PROGRAMS = {'spl-token', 'spl-token-2022'}
TOKEN_IDS = {'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
             'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'}
SYSTEM_ID = '11111111111111111111111111111111'
COMPUTE_ID = 'ComputeBudget111111111111111111111111111111'
ASSOCIATED_ID = 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
MEMO_IDS = {'MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr',
            'Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo'}
LAMPORTS = Decimal('1000000000')


def _lamports(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError('Lamports must be a nonnegative RPC integer')
    return canonical(Decimal(value) / LAMPORTS)


def decode_transactions(transactions, address):
    """Return normalized evidence-linked events; never claim historical completeness.

    Input records are {signature, raw, evidence_hash, transaction_index?}. raw is
    getTransaction result or its JSON-RPC envelope. Optional transaction_index must
    originate from supported getBlock evidence, not signature sorting.
    """
    events = []
    findings = []
    unresolved = []
    evidence = []
    prepared = []
    for index, record in enumerate(transactions):
        raw = record.get('raw')
        if isinstance(raw, dict) and 'result' in raw:
            raw = raw['result']
        prepared.append((record, raw, index))
    slots = Counter(raw.get('slot') for _, raw, _ in prepared if isinstance(raw, dict))
    for record, raw, record_index in prepared:
        signature = record.get('signature')
        if not signature:
            signatures = raw.get('transaction', {}).get('signatures', []) if isinstance(raw, dict) else []
            signature = signatures[0] if signatures else 'unknown'
        digest = record.get('evidence_hash')
        hashes = [digest] if digest else []
        if digest:
            evidence.append({'hash': digest, 'kind': 'getTransaction', 'signature': signature})
        timestamp = raw.get('blockTime') if isinstance(raw, dict) else None
        slot = raw.get('slot') if isinstance(raw, dict) else None
        sequence = 0

        def emit(kind, path, **fields):
            nonlocal sequence
            event = {'kind': kind, 'timestamp': timestamp, 'signature': signature,
                     'path': path, 'evidence': hashes, **fields}
            if isinstance(slot, int) and not isinstance(slot, bool):
                tx_index = record.get('transaction_index')
                if slots[slot] == 1:
                    event['order'] = slot * 1000000 + sequence
                elif isinstance(tx_index, int) and not isinstance(tx_index, bool) and tx_index >= 0:
                    event['order'] = slot * 1000000 + tx_index * 1000 + sequence
            sequence += 1
            events.append(event)
            return event

        def unsupported(reason, path='meta', mint=None):
            emit('unsupported', path, reason=reason, **({'mint': mint} if mint else {}))
            unresolved.append({'signature': signature, 'path': path, 'reason': reason, 'evidence': hashes})
            findings.append({'severity': 'warning', 'title': 'Decoder scope gap', 'detail': reason,
                             'evidence': hashes})

        if not isinstance(raw, dict):
            unsupported('Missing transaction result is not an empty transaction')
            continue
        if timestamp is None or not isinstance(timestamp, int) or isinstance(timestamp, bool):
            unsupported('Missing block time; exact window inclusion is unresolved')
        version = raw.get('version', 'legacy')
        if isinstance(version, bool) or version not in ('legacy', 0):
            unsupported('Unsupported transaction version')
            continue
        meta = raw.get('meta')
        message = raw.get('transaction', {}).get('message', {})
        if not isinstance(meta, dict) or not isinstance(message, dict):
            unsupported('Missing transaction metadata')
            continue
        keys = [entry.get('pubkey') if isinstance(entry, dict) else entry for entry in message.get('accountKeys', [])]
        loaded = meta.get('loadedAddresses') or {}
        if all(isinstance(entry, str) for entry in message.get('accountKeys', [])):
            keys.extend(loaded.get('writable', []) + loaded.get('readonly', []))
        payer = keys[0] if keys else None
        try:
            fee = _lamports(meta.get('fee'))
        except ValueError:
            unsupported('Missing or invalid network fee')
            fee = None
        emit('fee', 'meta.fee', amount_sol=fee, paid_by_wallet=payer == address,
             fee_payer=payer, failed=meta.get('err') is not None,
             reason='Network fee includes priority fees; no separate priority subtraction')
        if not keys:
            unsupported('Missing fee payer account keys')
        if meta.get('err') is not None:
            findings.append({'severity': 'info', 'title': 'Failed transaction retained',
                             'detail': 'Only the incurred wallet fee is retained; instructions did not execute successfully.',
                             'evidence': hashes})
            continue
        if isinstance(slot, int) and slots[slot] > 1 and 'transaction_index' not in record:
            unsupported('Same-slot transaction ordering needs supported block evidence')

        pre = {}
        post = {}
        identities = {}
        conflicting = set()

        def read_balances(rows, target, path):
            for number, balance in enumerate(rows or []):
                try:
                    account_index = balance['accountIndex']
                    if not isinstance(account_index, int) or isinstance(account_index, bool) or account_index < 0:
                        raise ValueError('Invalid token account index')
                    account = keys[account_index]
                    mint = balance['mint']
                    token = balance['uiTokenAmount']
                    decimals = token['decimals']
                    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 255:
                        raise ValueError('Invalid token decimals')
                    amount = raw_quantity(token['amount'])
                    owner = balance.get('owner')
                    identity = {'mint': mint, 'decimals': decimals, 'owner': owner}
                    previous = identities.get(account)
                    if previous and previous != identity:
                        conflicting.add(account)
                    identities[account] = identity
                    target[account] = {'amount': amount, **identity}
                except (KeyError, IndexError, ValueError, TypeError):
                    unsupported('Token identity or integer balance is missing', f'{path}.{number}')

        read_balances(meta.get('preTokenBalances'), pre, 'meta.preTokenBalances')
        read_balances(meta.get('postTokenBalances'), post, 'meta.postTokenBalances')
        for account in conflicting:
            unsupported('Token account identity or ownership changed; event-time identity needs review', mint=identities[account].get('mint'))
        flow = defaultdict(int)
        ownership = {account: dict(identity) for account, identity in identities.items() if account not in conflicting}
        inner = defaultdict(list)
        instructions = message.get('instructions')
        groups = meta.get('innerInstructions')
        if not isinstance(instructions, list) or groups is not None and not isinstance(groups, list):
            unsupported('Successful instruction containers are malformed', 'transaction.message.instructions')
            continue
        invalid_inner = False
        for group_index, group in enumerate(groups or []):
            if (not isinstance(group, dict) or type(group.get('index')) is not int or
                not 0 <= group['index'] < len(instructions) or group['index'] in inner or
                not isinstance(group.get('instructions'), list)):
                unsupported('Inner instruction association is malformed or duplicated', f'meta.innerInstructions.{group_index}')
                invalid_inner = True
                break
            inner[group['index']].extend(group['instructions'])
        if invalid_inner:
            continue
        flattened = []
        for outer_index, instruction in enumerate(instructions):
            flattened.append((f'instructions.{outer_index}', instruction))
            for inner_index, nested in enumerate(inner.get(outer_index, [])):
                flattened.append((f'innerInstructions.{outer_index}.{inner_index}', nested))

        def token_identity(account):
            return ownership.get(account)

        for path, instruction in flattened:
            if not isinstance(instruction, dict):
                unsupported('Malformed instruction', path)
                continue
            program = instruction.get('program')
            program_id = instruction.get('programId')
            parsed = instruction.get('parsed')
            if (program is not None and not isinstance(program, str) or
                program_id is not None and not isinstance(program_id, str)):
                unsupported('Instruction program identity has an invalid container type', path)
                continue
            expected_ids = {'system': {SYSTEM_ID}, 'spl-token': {'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'},
                            'spl-token-2022': {'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'},
                            'spl-associated-token-account': {ASSOCIATED_ID}, 'compute-budget': {COMPUTE_ID}}
            if program in expected_ids and program_id not in expected_ids[program]:
                unsupported('Parsed program name does not establish a supported program identity', path)
                continue
            if program_id == COMPUTE_ID or program == 'compute-budget' or program_id in MEMO_IDS or program == 'spl-memo':
                continue
            if program_id == ASSOCIATED_ID or program == 'spl-associated-token-account':
                if isinstance(parsed, dict) and parsed.get('type') in ('create', 'createIdempotent'):
                    info = parsed.get('info', {})
                    account = info.get('account')
                    if account and info.get('mint') and info.get('wallet'):
                        existing = ownership.get(account, {})
                        ownership[account] = {'owner': info['wallet'], 'mint': info['mint'], 'decimals': existing.get('decimals')}
                    emit('rent', path, reason='Account creation is refundable rent, not an automatic trading expense')
                else:
                    unsupported('Unparsed associated-account instruction', path)
                continue
            if not isinstance(parsed, dict):
                unsupported('No reviewed decoder for this instruction/program; balance deltas do not prove a swap', path)
                continue
            kind = parsed.get('type')
            info = parsed.get('info', {})
            if not isinstance(info, dict):
                unsupported('Malformed parsed instruction', path)
                continue
            if program == 'system' or program_id == SYSTEM_ID:
                if kind == 'transfer':
                    source, destination = info.get('source'), info.get('destination')
                    if address not in (source, destination):
                        continue
                    try:
                        amount = _lamports(info.get('lamports'))
                    except ValueError:
                        unsupported('Invalid native transfer quantity', path)
                        continue
                    if source == destination == address:
                        emit('internal_transfer', path, amount_sol=amount, reason='Native self-transfer is internal movement')
                        continue
                    native_account = destination if source == address else source
                    identity = token_identity(native_account)
                    if identity and identity.get('owner') == address and identity.get('mint') == 'So11111111111111111111111111111111111111112':
                        emit('wrap', path, amount_sol=amount, reason='Native SOL representation change')
                    else:
                        emit('capital', path, direction='withdrawal' if source == address else 'deposit',
                             amount_sol=amount, reason='External native movement; not trading profit')
                elif kind in ('createAccount', 'createAccountWithSeed'):
                    emit('rent', path, reason='Account funding may include rent or wrapping; not a proven trade')
                elif kind in ('allocate', 'assign', 'allocateWithSeed', 'assignWithSeed'):
                    emit('rent', path, reason='Account administration is not a proven trade')
                else:
                    unsupported('Unsupported system instruction', path)
                continue
            if program not in TOKEN_PROGRAMS and program_id not in TOKEN_IDS:
                unsupported('No reviewed exchange adapter; observed token movements do not prove prices or buys/sells', path)
                continue
            if kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3'):
                account = info.get('account')
                identity = ownership.get(account, {})
                if account and info.get('mint') and info.get('owner'):
                    ownership[account] = {'mint': info['mint'], 'owner': info['owner'], 'decimals': identity.get('decimals')}
                else:
                    unsupported('Incomplete account initialization identity', path)
                continue
            if kind in ('initializeMint', 'initializeMint2', 'initializeMultisig', 'initializeMultisig2', 'getAccountDataSize'):
                continue
            if kind in ('approve', 'approveChecked', 'revoke'):
                findings.append({'severity': 'info', 'title': 'Token permission instruction',
                                 'detail': f'{kind} observed. Permissions alone do not establish misconduct.', 'evidence': hashes})
                continue
            if kind == 'closeAccount':
                emit('rent', path, reason='Refundable token-account rent or unwrap; not automatic income')
                ownership.pop(info.get('account'), None)
                continue
            if kind == 'syncNative':
                emit('wrap', path, reason='Wrapped SOL representation synchronization')
                continue
            if kind not in ('transfer', 'transferChecked'):
                unsupported('Unsupported token operation, extension, mint/burn or ownership change', path)
                if kind == 'setAuthority':
                    ownership.pop(info.get('account'), None)
                continue
            source, destination = info.get('source'), info.get('destination')
            source_id, destination_id = token_identity(source), token_identity(destination)
            identities_in_flow = [identity for identity in (source_id, destination_id) if identity]
            if not identities_in_flow:
                unsupported('Transfer account ownership and mint are unresolved', path)
                continue
            reference = identities_in_flow[0]
            mint = info.get('mint', reference.get('mint'))
            if any(identity.get('mint') != mint for identity in identities_in_flow):
                unsupported('Transfer mint identities disagree', path, mint)
                continue
            try:
                token = info.get('tokenAmount') if kind == 'transferChecked' else None
                quantity = raw_quantity(token['amount'] if token else info.get('amount'))
                decimals = token['decimals'] if token else reference.get('decimals')
                if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 255:
                    raise ValueError('Missing decimals')
                if any(identity.get('decimals') is not None and identity['decimals'] != decimals for identity in identities_in_flow):
                    raise ValueError('Conflicting transfer decimals')
            except (KeyError, ValueError, TypeError):
                unsupported('Transfer amount or mint decimals unresolved', path, mint)
                continue
            flow[source] -= quantity
            flow[destination] += quantity
            source_owned = source_id is not None and source_id.get('owner') == address
            destination_owned = destination_id is not None and destination_id.get('owner') == address
            if not source_owned and not destination_owned:
                # A missing counterparty owner does not affect the evidenced owned side.
                if any(identity.get('owner') is None for identity in identities_in_flow):
                    unsupported('Event-time transfer ownership is missing', path, mint)
                continue
            if quantity == 0:
                continue
            movement = 'internal_transfer' if source_owned and destination_owned else 'transfer_out' if source_owned else 'transfer_in'
            emit(movement, path, mint=mint, quantity_raw=str(quantity), decimals=decimals,
                 classification='settlement' if mint == 'So11111111111111111111111111111111111111112' else 'unknown',
                 source=source, destination=destination,
                 reason='Evidenced owned-account movement; no trusted economic exchange classification')
        for account in set(pre) | set(post):
            before, after = pre.get(account), post.get(account)
            identity = after or before
            if identity.get('owner') != address:
                continue
            difference = (after or {}).get('amount', 0) - (before or {}).get('amount', 0)
            if difference != flow[account]:
                if identity.get('mint') == 'So11111111111111111111111111111111111111112':
                    emit('wrap', 'meta.tokenBalances', mint=identity['mint'], reason='Wrapped SOL balance change retained as representation evidence; no trading P&L inferred')
                else:
                    unsupported('Observed token balance changes do not reconcile to supported parsed movements', 'meta.tokenBalances', identity.get('mint'))
    if transactions:
        findings.append({'severity': 'warning', 'title': 'Live exchange decoding is limited',
                         'detail': 'This build supports parsed transfers, account administration and fees. It has no reviewed DEX buy/sell adapters or historical meme classifier; live trading metrics remain unresolved.'})
    return {'events': events, 'findings': findings, 'unresolved': unresolved, 'evidence': evidence}
