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
from .transaction_format import instruction_view, supported_transaction_format

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
    administration = []
    prepared = []
    for index, record in enumerate(transactions):
        raw = record.get('raw')
        if isinstance(raw, dict) and 'result' in raw:
            raw = raw['result']
        source_raw = raw
        raw = instruction_view(raw)
        prepared.append((record, raw, index, source_raw))
    slots = Counter(raw.get('slot') for _, raw, _, _ in prepared if isinstance(raw, dict))
    for record, raw, record_index, source_raw in prepared:
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
        normalization = None
        normalization_receipts = None
        administrative_context = None
        administrative_context_error = None

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
        if not supported_transaction_format(raw):
            unsupported('Unsupported transaction version')
            continue
        meta = raw.get('meta')
        message = raw.get('transaction', {}).get('message', {})
        if not isinstance(meta, dict) or not isinstance(message, dict):
            unsupported('Missing transaction metadata')
            continue
        keys = [entry.get('pubkey') if isinstance(entry, dict) else entry for entry in message.get('accountKeys', [])]
        loaded = meta.get('loadedAddresses')
        malformed_loaded = loaded is not None and (not isinstance(loaded, dict) or
            any(not isinstance(loaded.get(field), list) for field in ('writable', 'readonly')))
        if loaded is not None and not malformed_loaded and all(isinstance(entry, str) for entry in message.get('accountKeys', [])):
            keys.extend(loaded['writable'] + loaded['readonly'])
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
        if malformed_loaded:
            unsupported('Loaded account-key metadata is malformed; instruction identity remains unresolved', 'meta.loadedAddresses')
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
        inner_group_positions = {}
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
            inner_group_positions[group['index']] = group_index
        if invalid_inner:
            continue
        flattened = []
        for outer_index, instruction in enumerate(instructions):
            flattened.append((f'instructions.{outer_index}', instruction))
            for inner_index, nested in enumerate(inner.get(outer_index, [])):
                flattened.append((f'innerInstructions.{outer_index}.{inner_index}', nested))

        def token_identity(account):
            return ownership.get(account)

        def observe_administration(path, instruction, kind, info):
            """Validate the same parsed view for native and compiled evidence.

            These facts describe the referenced instruction only. They do not
            create ledger movement, acquisition basis, eligibility or history.
            The existing compiled bridge supplies independently checked bytes;
            parsed inputs still require the actual primary program/target keys.
            """
            nonlocal normalization, normalization_receipts, administrative_context, administrative_context_error
            from .compiled_instructions import (CompiledInstructionError, _pubkey, _SIZE_EXTENSIONS,
                                                normalize_transaction, resolve_account_keys)
            from .instruction_scope import InstructionEvidenceError, inspect_instruction
            parts = path.split('.')
            if parts[0] == 'instructions':
                source_path = 'transaction.message.' + path
            else:
                group_index = inner_group_positions[int(parts[1])]
                source_path = f'meta.innerInstructions.{group_index}.instructions.{parts[2]}'
            target_field = 'account' if kind == 'initializeImmutableOwner' else 'mint'
            try:
                if administrative_context is None and administrative_context_error is None:
                    try:
                        administrative_context = resolve_account_keys(source_raw)
                    except CompiledInstructionError as exc:
                        administrative_context_error = exc
                if administrative_context_error is not None:
                    raise administrative_context_error
                if administrative_context['keys'] != keys:
                    raise InstructionEvidenceError('Administrative account keys disagree with primary evidence',
                                                   ['transaction.message.accountKeys'])
                allowed = {'account'} if kind == 'initializeImmutableOwner' else {'mint', 'extensionTypes'}
                if set(info) - allowed:
                    raise InstructionEvidenceError('Administrative fields do not match the reviewed RPC schema', [source_path + '.parsed.info'])
                inspected = inspect_instruction(instruction, keys, path=source_path)
                if inspected['program'] not in TOKEN_IDS or inspected['program'] not in keys:
                    raise InstructionEvidenceError('Administrative token program is absent from primary account keys', [source_path + '.programId'])
                target = info.get(target_field)
                _pubkey(target, source_path + '.parsed.info.' + target_field)
                if keys.count(target) != 1:
                    raise InstructionEvidenceError('Administrative target must appear once in primary account keys', [source_path + '.parsed.info.' + target_field])
                if 'extensionTypes' in info and (not isinstance(info['extensionTypes'], list)
                        or any(not isinstance(item, str) or item not in _SIZE_EXTENSIONS for item in info['extensionTypes'])):
                    raise InstructionEvidenceError('Account-size query names an unsupported extension type', [source_path + '.parsed.info.extensionTypes'])
            except (CompiledInstructionError, InstructionEvidenceError) as exc:
                unsupported(str(exc), path)
                return
            if normalization is None:
                normalization = normalize_transaction(source_raw)
                # Each queried field belongs to this exact instruction. Index
                # the shared normalizer receipts once rather than rescanning
                # the whole transaction for every administrative observation.
                normalization_receipts = {row['path']: row for row in normalization['normalizations']}
            source_fields = [source_path + '.parsed.info.' + field for field in info]
            source_fields.extend(inspected['paths'])
            receipt = normalization_receipts.get(source_path)
            raw_paths = sorted(set(receipt['raw_paths'] if receipt is not None else
                                   source_fields + administrative_context['raw_paths']))
            administration.append({'signature': signature, 'timestamp': timestamp, 'path': path,
                'source_path': source_path, 'raw_paths': raw_paths, 'evidence': hashes,
                'program_id': inspected['program'], 'instruction': kind, 'target': target,
                'scope': 'Referenced administration only; no token movement, basis, classification or wallet population proof',
                'representation': 'derived-compiled' if receipt is not None else 'parsed'})

        for path, instruction in flattened:
            if not isinstance(instruction, dict):
                unsupported('Malformed instruction', path)
                continue
            program = instruction.get('program')
            program_id = instruction.get('programId')
            parsed = instruction.get('parsed')
            if 'parsed' in instruction and any(key in instruction for key in ('accounts', 'data')):
                unsupported('Parsed and opaque instruction representations conflict', path)
                continue
            if (program is not None and not isinstance(program, str) or
                program_id is not None and not isinstance(program_id, str)):
                unsupported('Instruction program identity has an invalid container type', path)
                continue
            expected_ids = {'system': {SYSTEM_ID}, 'spl-token': TOKEN_IDS,
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
            if kind in ('getAccountDataSize', 'initializeImmutableOwner'):
                observe_administration(path, instruction, kind, info)
                continue
            if kind in ('initializeMint', 'initializeMint2', 'initializeMultisig', 'initializeMultisig2'):
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
    return {'events': events, 'findings': findings, 'unresolved': unresolved, 'evidence': evidence,
            'administration': administration}
