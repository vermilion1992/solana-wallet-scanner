"""Bounded, evidence-linked spot swap reconstruction and current token checks.

One successful outer instruction from a recognized deployed spot venue is needed.
Its authority must be the investigated wallet. Net balances are then used to
collapse routed legs, never to decide that arbitrary movements constitute a swap.
The supported population is deliberately narrower than all Solana transactions:
single wallet input/output, SOL/wSOL settlement, parsed token CPIs, and no other
economic outer program. Explicit outside native transfers can be isolated, with
their economic role retained as unresolved. This module does not certify complete wallet history,
meme classification, profitability, sellability, or the honesty of a trader.

Account layouts / discriminator sources (retrieved 2026-10-02):
https://github.com/pump-fun/pump-public-docs/tree/main/idl
https://github.com/raydium-io/raydium-cp-swap/tree/master/programs/cp-swap/src
https://github.com/raydium-io/raydium-amm/blob/master/program/src/instruction.rs
https://github.com/orca-so/whirlpools/tree/main/programs/whirlpool/src/instructions
https://github.com/jup-ag/instruction-parser/blob/main/src/idl/jupiter.ts
https://github.com/jup-ag/jupiter-cpi/blob/main/src/lib.rs
Synthetic tests exercise these constraints. Archived raw mainnet golden fixtures
check PumpSwap buy_exact_quote_in and a sell with durable nonce administration;
other adapter routes have no successful live fixture. Neither fixture establishes
earlier acquisition costs, complete wallet positions or historical profitability.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
import base64

from .accounting import canonical, raw_quantity, decimal
from .decoder import SYSTEM_ID, COMPUTE_ID, ASSOCIATED_ID, TOKEN_IDS, MEMO_IDS

WSOL = 'So11111111111111111111111111111111111111112'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
JUPITER = 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4'
PUMP = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
PUMP_SWAP = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
PUMP_REVIEWED_NON_SWAP = (
    'distribute_fee_to_holders',
    'claim_cashback',
    'claim_cashback_v2',
    'collect_creator_fee',
    'collect_creator_fee_v2',
    'create',
    'create_v2',
    'migrate',
    'migrate_v2',
    'init_user_volume_accumulator',
    'sync_user_volume_accumulator',
    'close_user_volume_accumulator',
)
RAYDIUM_CPMM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
RAYDIUM_AMM = '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
WHIRLPOOL = 'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc'
OKX_DEX_ROUTER = 'proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u'
METEORA_DAMM_V2 = 'cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG'
DFLOW = 'DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH'
RFQ_FILL = '61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH'
OKX_SWAPTOC = bytes.fromhex('bbc9d433109bec3c')
OKX_SWAPTOB = bytes.fromhex('aa2955b184501f35')
RFQ_FILL_DISC = bytes.fromhex('a860b7a35c0a28a0')
DFLOW_SWAP_WITH_DESTINATION = bytes.fromhex('a8ac184dc59c8765')
REVIEWED_OUTER_VENUES = (
    JUPITER, PUMP, PUMP_SWAP, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL,
    METEORA_DAMM_V2, RFQ_FILL,
)
LAMPORTS = Decimal(1_000_000_000)
DECODER_VERSION = 'spot-v10-reviewed-venues-coverage-v1'
RECENT_BLOCKHASHES_SYSVAR = 'SysvarRecentB1ockHashes11111111111111111111'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_RAW_FIXTURE_ROUTES = {
    (PUMP_SWAP, 'buy_exact_quote_in'): {
        'state': 'RAW_MAINNET_GOLDEN',
        'fixture': 'tests/fixtures/mainnet-pumpswap-buy-exact-quote.json',
        'signature': '2w3FS5exzzoFkHXCdsfWreHApvEGq7WBfMas9qNBhhmsnLmBPURs2u1nVtTKDM2SQeDNw2rNrLbjMoSLQ3HNuYAo',
        'scope': 'One successful exact discriminator, wallet identity, amounts and separate native movements; no route-wide or history certificate',
    },
    (PUMP_SWAP, 'sell'): {
        'state': 'RAW_MAINNET_GOLDEN',
        'fixture': 'tests/fixtures/mainnet-pumpswap-sell-durable-nonce.json',
        'signature': '24sJMsaocWhShDJ7EtBpvyRXV8ieAgpPNBjgGGFfscVckF39QRopdfKiQhbasf2ZrCQzRkdsoBY11gFkpBFnHhFs',
        'raw_hash': '25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a',
        'scope': 'One successful sell with exact owned quantities, persistent wSOL proceeds and wallet-paid fee; earlier nonzero inventory cost remains unknown',
    },
    (JUPITER, 'route_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'fixture': 'tests/fixtures/retained_protocol_funding/jupiter-route-v2.json',
        'discriminator': 'bb64facc31c4af14',
        'scope': 'Official route_v2 accounts and discriminator; executed wallet deltas prove fills; USDC settlement stays USDC',
    },
    (JUPITER, 'shared_accounts_route_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'discriminator': 'd19853937cfed8e9',
        'scope': 'Official shared_accounts_route_v2 discriminator; authority index 1 and user token accounts 2/5 from genuine ranked pages',
    },
    (PUMP, 'sell_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'fixture': 'tests/fixtures/retained_protocol_funding/pump-native.json',
        'discriminator': '5df6823ce7e940b2',
        'scope': 'Official Pump sell_v2 accounts; user at 13, associated base/quote user at 14/15',
    },
    (PUMP, 'buy_exact_quote_in_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'fixture': 'tests/fixtures/retained_protocol_funding/pump-native.json',
        'discriminator': 'c2ab1c46684d5b2f',
        'scope': 'Official Pump buy_exact_quote_in_v2 accounts; user at 13, associated base/quote user at 14/15',
    },
}


def _integer(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError('Missing unsigned RPC integer')
    return value


def _anchor(name):
    return sha256(('global:' + name).encode()).digest()[:8]


def _data(value):
    if isinstance(value, list) and len(value) == 2 and value[1] == 'base64':
        return base64.b64decode(value[0], validate=True)
    if not isinstance(value, str) or len(value) > 40000:
        raise ValueError('Missing instruction bytes')
    number = 0
    for char in value:
        if char not in _B58:
            raise ValueError('Invalid base58 data')
        number = number * 58 + _B58.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, 'big')
    return b'\0' * (len(value) - len(value.lstrip('1'))) + body


def _keys(message, meta):
    entries = message.get('accountKeys')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Missing account keys')
    result = [item.get('pubkey') if isinstance(item, dict) else item for item in entries]
    if any(not isinstance(key, str) or not key for key in result):
        raise ValueError('Malformed account keys')
    if all(isinstance(item, str) for item in entries):
        loaded = meta.get('loadedAddresses') or {}
        if not isinstance(loaded, dict):
            raise ValueError('Malformed loaded account addresses')
        writable, readonly = loaded.get('writable', []), loaded.get('readonly', [])
        if not isinstance(writable, list) or not isinstance(readonly, list):
            raise ValueError('Malformed loaded account addresses')
        result += writable + readonly
        if any(not isinstance(key, str) or not key for key in result):
            raise ValueError('Malformed loaded account address')
    return result


def _message_signers(message, keys):
    """Message signers from parsed flags or header.numRequiredSignatures.

    Does not invent signers. Outer ATA still requires the funding source to be
    one of these keys; that check stays in normalize_instruction.
    """
    entries = message.get('accountKeys')
    if isinstance(entries, list) and entries and all(isinstance(item, dict) for item in entries):
        flagged = [item.get('pubkey') for item in entries if item.get('signer') is True]
        if flagged and all(isinstance(key, str) and key for key in flagged):
            return set(flagged)
        return set()
    header = message.get('header') if isinstance(message.get('header'), dict) else {}
    required = header.get('numRequiredSignatures')
    if type(required) is not int or isinstance(required, bool) or not 1 <= required <= len(keys):
        return set()
    return set(keys[:required])


def _program(instruction, keys):
    program = instruction.get('programId')
    if isinstance(program, str):
        return program
    index = instruction.get('programIdIndex')
    return keys[_integer(index)]


def _accounts(instruction, keys):
    accounts = instruction.get('accounts')
    if not isinstance(accounts, list):
        raise ValueError('Missing route accounts')
    return [keys[_integer(account)] if isinstance(account, int) else account for account in accounts]


def _route(instruction, keys):
    """Return a reviewed instruction layout; program names/log text are ignored."""
    program = _program(instruction, keys)
    payload = _data(instruction.get('data'))
    accounts = _accounts(instruction, keys)
    name, authority, owned_positions, expected = None, None, (), None
    if program == JUPITER:
        for candidate in ('route', 'route_with_token_ledger', 'exact_out_route',
                          'shared_accounts_route', 'shared_accounts_route_with_token_ledger',
                          'shared_accounts_exact_out_route'):
            if payload[:8] == _anchor(candidate):
                shared = candidate.startswith('shared_')
                offset = 9 if shared else 8
                count = int.from_bytes(payload[offset:offset + 4], 'little')
                tail_size = 11 if candidate.endswith('with_token_ledger') else 19
                # Every RoutePlanStep has at least one enum byte and the three
                # percentage/index bytes. Enum variants may carry more data.
                if not 1 <= count <= 128 or len(payload) < offset + 4 + 4 * count + tail_size:
                    raise ValueError('Jupiter route plan is absent or truncated')
                name = candidate
                authority, owned_positions = (2, (3, 6)) if shared else (1, (2, 3))
                break
        if name is None and payload[:8] == _anchor('route_v2'):
            if len(payload) < 28 or len(accounts) < 10:
                raise ValueError('Jupiter route_v2 layout is absent or truncated')
            name, authority, owned_positions = 'route_v2', 0, (1, 2)
        if name is None and payload[:8] == _anchor('shared_accounts_route_v2'):
            if len(payload) < 28 or len(accounts) < 12:
                raise ValueError('Jupiter shared_accounts_route_v2 layout is absent or truncated')
            name, authority, owned_positions = 'shared_accounts_route_v2', 1, (2, 5)
    elif program in (PUMP, PUMP_SWAP):
        names = ('buy', 'sell', 'buy_exact_sol_in') if program == PUMP else ('buy', 'sell', 'buy_exact_quote_in')
        for candidate in names:
            if payload[:8] == _anchor(candidate) and len(payload) >= 24:
                name = candidate
                authority, owned_positions = (6, (5,)) if program == PUMP else (1, (5, 6))
                expected = 'sell' if candidate == 'sell' else 'buy'
                break
        if name is None and program == PUMP:
            for candidate in ('sell_v2', 'buy_exact_quote_in_v2', 'buy_v2'):
                if payload[:8] == _anchor(candidate) and len(payload) >= 24 and len(accounts) > 15:
                    name = candidate
                    # Official IDL: associated_quote_user is ignored for legacy SOL quote.
                    authority, owned_positions = 13, (14,)
                    expected = 'sell' if candidate == 'sell_v2' else 'buy'
                    break
        if name is None and program == PUMP:
            for candidate in PUMP_REVIEWED_NON_SWAP:
                if payload[:8] == _anchor(candidate):
                    raise ValueError(
                        f'Reviewed Pump instruction {candidate} is not a spot swap'
                    )
    elif program == RAYDIUM_CPMM:
        for candidate in ('swap_base_input', 'swap_base_output'):
            if payload[:8] == _anchor(candidate) and len(payload) == 24 and len(accounts) >= 13:
                name, authority, owned_positions = candidate, 0, (4, 5)
                break
    elif program == RAYDIUM_AMM and len(payload) == 17:
        variants = {9: ('swap_base_in', (17, 18)), 11: ('swap_base_out', (17, 18)),
                    16: ('swap_base_in_v2', (8,)), 17: ('swap_base_out_v2', (8,))}
        if payload[0] in variants and len(accounts) in variants[payload[0]][1]:
            name, authority, owned_positions = variants[payload[0]][0], -1, (-3, -2)
    elif program == WHIRLPOOL:
        if payload[:8] == _anchor('swap') and len(payload) == 42 and len(accounts) >= 11:
            name, authority, owned_positions = 'swap', 1, (3, 5)
        elif payload[:8] == _anchor('swap_v2') and len(payload) >= 43 and len(accounts) >= 15:
            name, authority, owned_positions = 'swap_v2', 3, (7, 9)
    elif program == METEORA_DAMM_V2:
        if payload[:8] == _anchor('swap') and len(payload) >= 24 and len(accounts) >= 13:
            name, authority, owned_positions = 'swap', 8, (2, 3)
    elif program == RFQ_FILL:
        if payload[:8] == RFQ_FILL_DISC and len(payload) >= 16 and len(accounts) >= 11:
            name, authority, owned_positions = 'Fill', 0, (4,)
    if name is None:
        raise ValueError('No reviewed spot swap instruction for this program and discriminator')
    return {'program': program, 'instruction': name, 'authority': accounts[authority],
            'owned_accounts': [accounts[position] for position in owned_positions],
            'accounts': accounts, 'expected_kind': expected}


def _verify_nonce_administration(message, info, keys, pre_lamports, post_lamports,
                                 address, fee, outer, nested, *, raw=None):
    """Accept one narrow, non-economic System advanceNonce instruction.

    The caller has already checked the actual System Program identity. The
    successful primary instruction's exact parsed semantics, explicit signer,
    writable nonce identity, unchanged nonce balance and whole-record native
    conservation are required. No other nonce or System operation is inferred.
    """
    expected_fields = {'nonceAccount', 'nonceAuthority', 'recentBlockhashesSysvar'}
    if nested or outer != 0 or not isinstance(info, dict) or set(info) != expected_fields:
        raise ValueError('Nonce administration requires an exact first outer advanceNonce instruction')
    nonce = info.get('nonceAccount')
    if (not isinstance(nonce, str) or nonce in (address, RECENT_BLOCKHASHES_SYSVAR)
            or keys.count(nonce) != 1 or keys.count(address) != 1
            or info.get('nonceAuthority') != address
            or info.get('recentBlockhashesSysvar') != RECENT_BLOCKHASHES_SYSVAR
            or keys.count(RECENT_BLOCKHASHES_SYSVAR) != 1):
        raise ValueError('Nonce administration account, authority or recent-blockhashes sysvar identity is unresolved')
    entries = message.get('accountKeys')
    if isinstance(entries, list) and all(isinstance(entry, str) for entry in entries):
        from .compiled_instructions import key_roles
        roles = key_roles(raw)['keys']
        if [entry['pubkey'] for entry in roles] != keys:
            raise ValueError('Compiled nonce account roles disagree with resolved primary keys')
        entries = roles
    authority_entry = next((entry for entry in entries if isinstance(entry, dict) and entry.get('pubkey') == address), None)
    nonce_entry = next((entry for entry in entries if isinstance(entry, dict) and entry.get('pubkey') == nonce), None)
    sysvar_entry = next((entry for entry in entries if isinstance(entry, dict) and entry.get('pubkey') == RECENT_BLOCKHASHES_SYSVAR), None)
    if (not isinstance(authority_entry, dict) or authority_entry.get('signer') is not True
            or not isinstance(nonce_entry, dict) or nonce_entry.get('writable') is not True
            or not isinstance(sysvar_entry, dict) or sysvar_entry.get('writable') is not False
            or sysvar_entry.get('signer') is not False):
        raise ValueError('Nonce administration requires explicit primary signer and writable/read-only account roles')
    nonce_index = keys.index(nonce)
    if pre_lamports[nonce_index] != post_lamports[nonce_index]:
        raise ValueError('Nonce administration is non-economic only with unchanged nonce-account lamports')
    if sum(pre_lamports) - sum(post_lamports) != fee:
        raise ValueError('Nonce transaction native balances do not conserve the exact network fee')
    return {'kind': 'advanceNonce', 'nonce_account': nonce, 'authority': address,
            'economic_role': 'administration',
            'reason': 'First successful System advanceNonce changes nonce state only; nonce balance is unchanged and native endpoints conserve the network fee'}


def _verify_ephemeral_wrapped(flat, candidates, owned, keys, pre_lamports,
                              post_lamports, address, route, fee):
    """Prove temporary wSOL accounts from primary instructions, not ATA hints.

    Persistent accounts have event-time token balance evidence and keep that
    separate ownership/rent path. An account absent from both token endpoints
    needs creation, initialization, ordered flows and closure in this record.
    This proves only its transaction-local lifecycle, never wallet-wide history.
    """
    ephemeral = candidates - set(owned)
    if not ephemeral:
        return
    if sum(post_lamports) - sum(pre_lamports) != -fee:
        raise ValueError('Temporary wrapped SOL native balances do not reconcile to the network fee')
    route_position = next(index for index, row in enumerate(flat) if row[1] == route['path'])
    for account in ephemeral:
        if keys.count(account) != 1:
            raise ValueError('Temporary wrapped SOL account lacks one explicit account key')
        account_index = keys.index(account)
        if pre_lamports[account_index] != 0 or post_lamports[account_index] != 0:
            raise ValueError('Temporary wrapped SOL requires zero native endpoints; missing token balances are not a zero anchor')
        creations, initializations, closes, movements = [], [], [], []
        for position, (outer, path, instruction, _) in enumerate(flat):
            program = _program(instruction, keys)
            parsed = instruction.get('parsed')
            if not isinstance(parsed, dict):
                continue
            kind, info = parsed.get('type'), parsed.get('info', {})
            if program == SYSTEM_ID:
                if kind in ('createAccount', 'createAccountWithSeed') and info.get('newAccount') == account:
                    creations.append((position, info))
                elif kind == 'transfer' and account in (info.get('source'), info.get('destination')):
                    movements.append((position, outer, 'native', kind, program, info))
            elif program in TOKEN_IDS:
                if kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3') and info.get('account') == account:
                    initializations.append((position, program, info))
                elif kind == 'closeAccount' and info.get('account') == account:
                    closes.append((position, program, info))
                elif kind == 'syncNative' and info.get('account') == account:
                    movements.append((position, outer, 'sync', kind, program, info))
                elif kind in ('transfer', 'transferChecked') and account in (info.get('source'), info.get('destination')):
                    movements.append((position, outer, 'token', kind, program, info))
        if len(creations) != 1 or len(initializations) != 1 or len(closes) != 1:
            raise ValueError('Temporary wrapped SOL needs one primary creation, initialization and closure; ATA idempotence is not proof')
        creation_position, creation = creations[0]
        initialization_position, token_program, initialization = initializations[0]
        close_position, close_program, close = closes[0]
        rent = _integer(creation.get('lamports'))
        if (creation.get('source') != address or creation.get('owner') != token_program
                or token_program != 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
                or _integer(creation.get('space')) != 165 or rent == 0):
            raise ValueError('Temporary wrapped SOL creation lacks wallet-funded primary rent and native-token account identity')
        if initialization.get('owner') != address or initialization.get('mint') != WSOL:
            raise ValueError('Temporary wrapped SOL initialization lacks event-time wallet ownership and mint')
        if close_program != token_program or close.get('owner') != address or close.get('destination') != address:
            raise ValueError('Temporary wrapped SOL closure and rent refund must belong to the investigated wallet')
        if not creation_position < initialization_position < route_position < close_position:
            raise ValueError('Temporary wrapped SOL creation, initialization, route and closure ordering is unresolved')
        wrapped_units, pending_sync = 0, False
        for position, outer, movement_type, kind, program, info in sorted(movements):
            if not creation_position < position < close_position:
                raise ValueError('Temporary wrapped SOL movement lies outside its primary lifecycle')
            if movement_type == 'native':
                if info.get('source') != address or info.get('destination') != account:
                    raise ValueError('Temporary wrapped SOL funding or withdrawal has unresolved ownership and rent allocation')
                wrapped_units += _integer(info.get('lamports'))
                pending_sync = position > initialization_position
            elif movement_type == 'sync':
                if program != token_program or position <= initialization_position:
                    raise ValueError('Temporary wrapped SOL sync lacks its primary initialized token account')
                pending_sync = False
            else:
                if outer != route['index'] or program != token_program or position <= initialization_position:
                    raise ValueError('Temporary wrapped SOL transfer is outside the initialized supported route')
                checked = info.get('tokenAmount') if kind == 'transferChecked' else None
                quantity = raw_quantity(checked['amount'] if checked else info.get('amount'))
                if checked and (info.get('mint') != WSOL or _integer(checked.get('decimals')) != 9):
                    raise ValueError('Temporary wrapped SOL transfer disagrees with its primary mint and decimals')
                if info.get('source') == account:
                    if pending_sync:
                        raise ValueError('Temporary wrapped SOL funding lacks syncNative before its token debit')
                    wrapped_units -= quantity
                if info.get('destination') == account:
                    wrapped_units += quantity
                if wrapped_units < 0:
                    raise ValueError('Temporary wrapped SOL transfer exceeds evidenced lifecycle funding')
        # Closing a native token account returns its remaining wrapped units and
        # funded rent. The zero native endpoint, wallet beneficiary, ordered
        # primary proofs and exact native/quote reconciliations establish this
        # refund without counting rent or representation changes as trade cost.


def _canonical_user_volume_address(address):
    """Derive the primary-IDL PumpSwap PDA without signing or an SDK.

    Solana hashes seeds, bump, program and ProgramDerivedAddress, rejecting
    compressed Edwards points. The first off-curve bump is canonical; subgroup
    membership is insufficient for this check.
    """
    user, program = _data(address), _data(PUMP_SWAP)
    if len(user) != 32 or len(program) != 32:
        raise ValueError('User-volume PDA requires exact 32-byte public keys')
    prime = 2**255 - 19
    curve_d = -121665 * pow(121666, prime - 2, prime) % prime
    for bump in range(255, -1, -1):
        candidate = sha256(b'user_volume_accumulator' + user + bytes([bump]) + program + b'ProgramDerivedAddress').digest()
        y = (int.from_bytes(candidate, 'little') & (2**255 - 1)) % prime
        square = (y * y - 1) * pow(curve_d * y * y + 1, prime - 2, prime) % prime
        on_curve = square == 0 or pow(square, (prime - 1) // 2, prime) == 1
        if not on_curve:
            return candidate, bump
    raise ValueError('User-volume PDA has no supported canonical bump')


def _retained_user_volume_funding(flat, keys, before, after, address, route):
    """Locate one primary user-PDA creation separately from swap consideration.

    The pinned PumpSwap IDL places user_volume_accumulator at ordinal20 in buy
    and buy_exact_quote_in and derives it from the user. Allocation size is an
    observed fact, not a universal137-byte contract. No refund or valuation is
    inferred from the existence of a close instruction.
    """
    if route['program'] != PUMP_SWAP or route['instruction'] not in ('buy', 'buy_exact_quote_in') or len(route['accounts']) <= 20:
        return []
    account = route['accounts'][20]
    creates = []
    for outer, path, instruction, nested in flat:
        parsed = instruction.get('parsed')
        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
        if (_program(instruction, keys) == SYSTEM_ID and isinstance(parsed, dict)
            and parsed.get('type') in ('createAccount', 'createAccountWithSeed') and info.get('newAccount') == account):
            creates.append((outer, path, nested, parsed['type'], info))
    if not creates:
        return []
    derived, bump = _canonical_user_volume_address(address)
    if len(creates) != 1 or _data(account) != derived or keys.count(account) != 1:
        raise ValueError('Retained user-volume funding lacks one exact primary user PDA')
    outer, path, nested, kind, info = creates[0]
    index, lamports = keys.index(account), _integer(info.get('lamports'))
    # The native creation supplies the allocation; primary sources do not
    # promise a universal numeric LEN. Its size alone is not the role proof.
    space = _integer(info.get('space'))
    if (outer != route['index'] or not nested or kind != 'createAccount'
        or info.get('source') != address or info.get('owner') != PUMP_SWAP
        or not 0 < space <= 2**64 - 1 or not 0 < lamports <= 2**64 - 1
        or before[index] != 0 or after[index] != lamports
        or account in route['owned_accounts']):
        raise ValueError('Retained user-volume funding disagrees with primary payer/program/allocation/native endpoints')
    for _, other_path, instruction, _ in flat:
        if other_path == path or _program(instruction, keys) != SYSTEM_ID:
            continue
        parsed = instruction.get('parsed')
        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
        if account in (info.get('source'), info.get('destination'), info.get('newAccount')):
            raise ValueError('Retained user-volume account has another unresolved native movement')
    return [{'account': account, 'payer': address, 'program': PUMP_SWAP, 'lamports': lamports,
        'space': space, 'path': path, 'pda_bump': bump,
        'allocation_profile': 'Native creation allocation; no universal protocol LEN is inferred',
        'role': 'retained-user-volume-account-funding',
        'contract': 'pump-public-docs-cb188ce08b5069196eef1f3e4a0c43b70099793b',
        'contract_sha256': '2091433899b07d003d98118ae6cd3c628960fd393b40710b6e15bce6d0e7f2d1',
        'recovery_state': 'UNKNOWN', 'valuation_state': 'UNKNOWN',
        'reason': 'Exact user-PDA funding remains located in its program-owned native endpoint; trade quote is separate. Refund entitlement and economic value are unproved.'}]


def _unresolved_native_roles(flat, owned, wrapped, keys, before, address, route, retained, settlement):
    """Inspect gross wallet cash roles even when native endpoints cancel.

    Wrapped settlement proves the quote legs, not every other cash movement.
    The primary Pump ABI names curve3/fee1/creator-vault9 buy recipients;
    native sells pay the user from curve3. No other route account, mirrored
    movement or net-zero cash loop inherits a quote/cost role from endpoints.
    The pinned primary IDL is retained with the funding regression fixtures.
    """
    unresolved = []
    wallet_assets = {address, *owned, *wrapped}
    retained_paths = {item['path'] for item in retained}
    initializers = defaultdict(set)
    native_quote = not wrapped and route['program'] == PUMP
    quote_total = 0
    quote_recipients = set()
    if native_quote and settlement < 0:
        quote_recipients.update(route['accounts'][position] for position in (1, 3))
        if len(route['accounts']) > 9:
            quote_recipients.add(route['accounts'][9])
    for _outer, _path, instruction, _nested in flat:
        parsed = instruction.get('parsed')
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
        program = _program(instruction, keys)
        if program in TOKEN_IDS and kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3'):
            initializers[info.get('account')].add((program, info.get('mint'), info.get('owner')))
    for outer, path, instruction, _nested in flat:
        parsed = instruction.get('parsed')
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
        program = _program(instruction, keys)
        reason = None
        if program == SYSTEM_ID and kind == 'transfer' and outer == route['index']:
            source, destination = info.get('source'), info.get('destination')
            lamports = _integer(info.get('lamports'))
            if not lamports or source == destination or not wallet_assets.intersection((source, destination)):
                continue
            if source == address and destination in wrapped:
                continue  # Existing primary lifecycle/endpoint checks validate wrapping.
            if native_quote and (
                settlement < 0 and source == address and destination in quote_recipients
                or settlement > 0 and source == route['accounts'][3] and destination == address
            ):
                quote_total += lamports
                continue
            reason = 'Same-route native transfer has no supported wallet wrapping, cost or capital role'
        elif program == SYSTEM_ID and kind in ('createAccount', 'createAccountWithSeed') and info.get('source') == address:
            lamports = _integer(info.get('lamports'))
            account = info.get('newAccount')
            if not lamports or path in retained_paths:
                continue
            owned_rent = (account in owned or account in wrapped) and info.get('owner') in TOKEN_IDS
            owned_rent = owned_rent and account in keys and before[keys.index(account)] == 0
            mint = owned.get(account, {}).get('mint', WSOL if account in wrapped else None)
            owned_rent = owned_rent and (info.get('owner'), mint, address) in initializers[account]
            if owned_rent:
                continue  # Existing observed token reserve/lifecycle checks still apply.
            reason = 'Wallet-funded native creation has no supported owned-token rent or retained-PDA role'
        elif program in TOKEN_IDS and kind == 'closeAccount' and info.get('destination') == address:
            if info.get('account') in owned or info.get('account') in wrapped:
                continue
            reason = 'Closure of an account outside proved wallet ownership has an unresolved refund role and amount'
        if reason:
            unresolved.append({'state': 'UNKNOWN', 'path': path, 'program': program, 'kind': kind,
                               'facts': dict(info), 'reason': reason})
    if native_quote and quote_total > abs(settlement):
        unresolved.append({'state': 'UNKNOWN', 'path': route['path'], 'program': route['program'],
            'kind': 'nativeQuote', 'facts': {'observed_primary_quote_lamports': quote_total,
            'settlement_lamports': abs(settlement)},
            'reason': 'Explicit primary native quote legs exceed the isolated consideration; a cancelling role is unresolved'})
    return unresolved


# Official System allocate (tag 8, 12 bytes) / assign (tag 1, 36 bytes) from
# scanner.compiled_instructions._system. Used only as inner swap lifecycle —
# PumpSwap account setup on genuine Jupiter route_v2, or token-account sizes.
# Outer nonce/authority mutations must not inherit this exception.
_REVIEWED_LIFECYCLE_OWNERS = frozenset({
    *TOKEN_IDS, PUMP, PUMP_SWAP, JUPITER, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL,
    OKX_DEX_ROUTER, METEORA_DAMM_V2, DFLOW, RFQ_FILL,
})
_REVIEWED_ALLOCATE_SPACES = frozenset({137, 165, 170})


def _accept_inner_system_lifecycle(kind, info, *, nested, address):
    if not nested:
        raise ValueError('Outer System allocate/assign is not swap lifecycle')
    if not isinstance(info, dict):
        raise ValueError('System allocate/assign layout is absent')
    account = info.get('account')
    if not isinstance(account, str) or not account or account == address:
        raise ValueError('System allocate/assign account is outside swap lifecycle')
    allowed = {'account', 'space'} if kind == 'allocate' else {'account', 'owner'}
    if set(info) != allowed:
        raise ValueError('System allocate/assign layout is not the pinned System contract')
    if kind == 'allocate':
        space = info.get('space')
        if type(space) is not int or space not in _REVIEWED_ALLOCATE_SPACES:
            raise ValueError('System allocate space is not a reviewed account layout')
        return
    owner = info.get('owner')
    if owner not in _REVIEWED_LIFECYCLE_OWNERS:
        raise ValueError('System assign owner is not a reviewed program')


def decode_supported_swaps(transactions, address):
    """Decode record wrappers {signature,raw,evidence_hash,transaction_index?}.

    coverage describes this fetched sample only. complete and history_complete
    always remain False. No absence of a warning establishes complete evidence.
    A wallet-paid network fee is allocated to the exact single reconstructed
    trade only when no outside economic movement remains. Its display fee event
    retains the actual amount and links allocation to that same-signature trade
    path; accounting validates this link and excludes the display from overhead.
    Failed, unsupported or ambiguous transactions keep unallocated fee evidence.
    Sponsored fees stay excluded. meta.fee already includes priority fees.
    """
    events, findings, unresolved, evidence, administration = [], [], [], [], []
    rows = []
    for record in transactions:
        raw = record.get('raw') if isinstance(record, dict) else None
        if isinstance(raw, dict) and 'result' in raw:
            raw = raw['result']
        from .transaction_format import instruction_view
        raw = instruction_view(raw)
        rows.append((record if isinstance(record, dict) else {}, raw))
    slots = Counter(raw['slot'] for _, raw in rows if isinstance(raw, dict)
                    and isinstance(raw.get('slot'), int) and not isinstance(raw['slot'], bool))
    supported, failed, no_swap, conversions = 0, 0, 0, 0
    used_routes = set()
    for record, raw in rows:
        signature = record.get('signature')
        transaction = raw.get('transaction') if isinstance(raw, dict) else None
        actual = transaction.get('signatures', []) if isinstance(transaction, dict) else []
        if not isinstance(actual, list):
            actual = []
        if not signature:
            signature = actual[0] if actual else None
        digest = record.get('evidence_hash')
        hashes = [digest] if isinstance(digest, str) and digest else []
        if hashes:
            evidence.append({'kind': 'getTransaction', 'signature': signature, 'hash': digest})
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
                    event['order'] = slot * 1_000_000 + sequence
                elif isinstance(tx_index, int) and not isinstance(tx_index, bool) and tx_index >= 0:
                    event['order'] = slot * 1_000_000 + tx_index * 1_000 + sequence
            sequence += 1
            events.append(event)
            return event

        def unknown(reason, path='meta', mint=None):
            issue = {'signature': signature, 'path': path, 'reason': reason, 'evidence': hashes}
            if mint:
                issue['mint'] = mint
            unresolved.append(issue)
            emit('unsupported', path, reason=reason, **({'mint': mint} if mint else {}))
            findings.append({'severity': 'warning', 'title': 'Swap reconstruction gap',
                             'detail': reason, 'signature': signature, 'evidence': hashes})

        def uncertain_cash(reason, path, *, amount=None, direction=None, facts=None):
            # Cash-role uncertainty does not invalidate proved token operations
            # or their chronology. It still blocks complete monetary support.
            unresolved.append({'signature': signature, 'path': path, 'reason': reason,
                               'scope': 'native monetary roles', 'evidence': hashes})
            facts = facts or {}
            emit('capital', path, amount_sol=amount, direction=direction,
                 source=facts.get('source', facts.get('account')),
                 destination=facts.get('destination', facts.get('newAccount')),
                 economic_role='unknown', facts=facts, reason=reason)
            findings.append({'severity': 'warning', 'title': 'Native monetary role unresolved',
                             'detail': reason, 'signature': signature, 'evidence': hashes})

        try:
            if not isinstance(raw, dict):
                raise ValueError('Missing raw transaction result')
            if not signature or not actual or signature != actual[0]:
                raise ValueError('Transaction signature identity is missing or disagrees')
            _integer(timestamp)
            _integer(slot)
            version = raw.get('version', 'legacy')
            if isinstance(version, bool) or version not in ('legacy', 0, 1):
                raise ValueError('Unsupported transaction version')
            meta = raw.get('meta')
            message = raw.get('transaction', {}).get('message')
            if not isinstance(meta, dict) or not isinstance(message, dict) or 'err' not in meta:
                raise ValueError('Missing transaction metadata or success state')
            keys = _keys(message, meta)
            signers = _message_signers(message, keys)
            fee = _integer(meta.get('fee'))
            paid = keys[0] == address
            fee_sol = canonical(Decimal(fee) / LAMPORTS)
            fee_event = emit('fee', 'meta.fee', amount_sol=fee_sol,
                             paid_by_wallet=paid, fee_payer=keys[0], failed=meta['err'] is not None,
                             allocation='unallocated',
                             reason='meta.fee includes network and priority fees; do not subtract a second priority charge')
            if meta['err'] is not None:
                failed += 1
                continue
            if address not in keys:
                raise ValueError('Investigated wallet is absent from transaction account keys')
            if slots[slot] > 1:
                tx_index = record.get('transaction_index')
                if not isinstance(tx_index, int) or isinstance(tx_index, bool) or tx_index < 0:
                    raise ValueError('Same-slot ordering requires independently fetched block evidence')
            instructions = message.get('instructions')
            if not isinstance(instructions, list):
                raise ValueError('Missing instructions')
            routes = []
            for index, instruction in enumerate(instructions):
                if not isinstance(instruction, dict):
                    raise ValueError('Malformed instruction')
                if _program(instruction, keys) in REVIEWED_OUTER_VENUES:
                    route = _route(instruction, keys)
                    route.update(index=index, path=f'instructions.{index}')
                    routes.append(route)
            if not routes:
                no_swap += 1
                raise ValueError('No reviewed outer spot swap; transfers and balances alone do not prove trading')
            if len(routes) != 1:
                raise ValueError('Multiple outer swaps need separate instruction-level economic allocation')
            route = routes[0]
            used_routes.add((route['program'], route['instruction']))
            if route['authority'] != address:
                raise ValueError('Recognized swap authority is not the investigated wallet')
            pre_lamports, post_lamports = meta.get('preBalances'), meta.get('postBalances')
            if not isinstance(pre_lamports, list) or not isinstance(post_lamports, list) or len(pre_lamports) != len(keys) or len(post_lamports) != len(keys):
                raise ValueError('Incomplete native balance evidence')
            pre_lamports = [_integer(value) for value in pre_lamports]
            post_lamports = [_integer(value) for value in post_lamports]
            pre, post, identities = {}, {}, {}
            for field, target in (('preTokenBalances', pre), ('postTokenBalances', post)):
                balances = meta.get(field)
                if not isinstance(balances, list):
                    raise ValueError('Missing event-time token balances')
                for balance in balances:
                    index = _integer(balance['accountIndex'])
                    account = keys[index]
                    token = balance['uiTokenAmount']
                    decimals = _integer(token['decimals'])
                    if decimals > 255:
                        raise ValueError('Invalid token decimals')
                    owner, mint = balance.get('owner'), balance.get('mint')
                    if not isinstance(owner, str) or not isinstance(mint, str) or not mint:
                        raise ValueError('Missing event-time token ownership or mint')
                    identity = {'owner': owner, 'mint': mint, 'decimals': decimals, 'index': index}
                    if account in identities and identity != identities[account]:
                        raise ValueError('Token ownership, identity or decimals changed in transaction')
                    if account in target:
                        raise ValueError('Duplicate token account balance')
                    identities[account] = identity
                    target[account] = raw_quantity(token['amount'])
            owned = {account: value for account, value in identities.items() if value['owner'] == address}
            inner = defaultdict(list)
            groups = meta.get('innerInstructions')
            if groups is not None and not isinstance(groups, list):
                raise ValueError('Malformed inner instruction container')
            for group in groups or []:
                if not isinstance(group, dict) or not isinstance(group.get('instructions'), list):
                    raise ValueError('Malformed inner instruction association')
                outer = _integer(group['index'])
                if outer >= len(instructions) or outer in inner:
                    raise ValueError('Out-of-range or duplicate inner instruction association')
                inner[outer] = []
                for index, instruction in enumerate(group['instructions']):
                    if not isinstance(instruction, dict):
                        raise ValueError('Malformed inner instruction')
                    inner[outer].append((f'innerInstructions.{outer}.{index}', instruction))
            flat = []
            for index, instruction in enumerate(instructions):
                flat.append((index, f'instructions.{index}', dict(instruction), False))
                flat.extend((index, path, dict(nested), True) for path, nested in inner[index])
            flow = defaultdict(int)
            rent_funders, closures, allowed_wrapped = {}, {}, set()
            outside_native = []
            outside_native_delta = 0
            nonce_administration = []
            for outer, path, instruction, nested in flat:
                if 'parsed' in instruction and any(key in instruction for key in ('accounts', 'data')):
                    raise ValueError('Parsed and opaque instruction representations conflict')
                program = _program(instruction, keys)
                parsed = instruction.get('parsed')
                kind = parsed.get('type') if isinstance(parsed, dict) else None
                info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
                if kind is None and instruction.get('data') is not None and program in (SYSTEM_ID, ASSOCIATED_ID, *TOKEN_IDS):
                    try:
                        from .compiled_instructions import CompiledInstructionError, normalize_instruction
                        viewed = normalize_instruction(
                            instruction, keys, inner=nested, path=path,
                            signers=signers,
                        )
                        parsed = viewed['instruction'].get('parsed')
                        kind = parsed.get('type') if isinstance(parsed, dict) else None
                        info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
                        instruction['parsed'] = parsed
                        instruction['programId'] = viewed['instruction'].get('programId', program)
                    except (CompiledInstructionError, ValueError, KeyError, IndexError, TypeError):
                        pass
                if program in (COMPUTE_ID, *MEMO_IDS):
                    continue
                if program == ASSOCIATED_ID:
                    if kind not in ('create', 'createIdempotent'):
                        raise ValueError('Unparsed associated account administration')
                    if info.get('wallet') != address:
                        raise ValueError('Associated account creation for another wallet is outside swap scope')
                    account = info.get('account')
                    if info.get('mint') == WSOL:
                        allowed_wrapped.add(account)
                    if info.get('source') == address:
                        rent_funders[account] = address
                    continue
                if program == SYSTEM_ID:
                    if kind == 'advanceNonce':
                        nonce_administration.append({**_verify_nonce_administration(
                            message, info, keys, pre_lamports, post_lamports, address, fee, outer, nested, raw=raw),
                            'signature': signature, 'path': path, 'evidence': hashes})
                    elif kind == 'transfer':
                        source, destination = info.get('source'), info.get('destination')
                        lamports = _integer(info.get('lamports'))
                        if not lamports:
                            continue  # Transporting zero does not create a cash-role dependency.
                        if address not in (source, destination):
                            continue
                        if source == destination == address:
                            continue
                        other = destination if source == address else source
                        wrapping = other in allowed_wrapped or owned.get(other, {}).get('mint') == WSOL
                        if outer != route['index'] and not wrapping:
                            if nested:
                                raise ValueError('Unrelated inner native movement has unresolved economic scope')
                            delta = -lamports if source == address else lamports
                            outside_native_delta += delta
                            outside_native.append({'path': path, 'source': source, 'destination': destination,
                                                   'lamports': lamports, 'direction': 'withdrawal' if delta < 0 else 'deposit'})
                    elif kind in ('createAccount', 'createAccountWithSeed'):
                        account = info.get('newAccount')
                        if info.get('source') == address:
                            rent_funders[account] = address
                        elif address in (info.get('source'), account):
                            raise ValueError('Unresolved native account funding')
                    elif kind in ('allocate', 'assign'):
                        _accept_inner_system_lifecycle(kind, info, nested=nested, address=address)
                        continue
                    else:
                        raise ValueError('Unsupported system operation within swap transaction')
                    continue
                if program in TOKEN_IDS:
                    if kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3'):
                        account = info.get('account')
                        if info.get('owner') == address and info.get('mint') == WSOL:
                            allowed_wrapped.add(account)
                        continue
                    if kind in ('getAccountDataSize', 'syncNative', 'initializeImmutableOwner'):
                        continue
                    if kind == 'closeAccount':
                        account = info.get('account')
                        if info.get('destination') == address:
                            if owned.get(account, {}).get('mint') == WSOL and info.get('owner') != address:
                                raise ValueError('Wrapped SOL closure lacks the investigated wallet authority')
                            closures[account] = address
                        elif account in owned or account in allowed_wrapped:
                            raise ValueError('Token account closes to another recipient')
                        continue
                    if kind not in ('transfer', 'transferChecked'):
                        raise ValueError('Unsupported token permission, extension, mint or burn operation')
                    source, destination = info.get('source'), info.get('destination')
                    checked = info.get('tokenAmount') if kind == 'transferChecked' else None
                    quantity = raw_quantity(checked['amount'] if checked else info.get('amount'))
                    for account in (source, destination):
                        identity = identities.get(account)
                        if identity and checked and (_integer(checked.get('decimals')) != identity['decimals'] or info.get('mint') != identity['mint']):
                            raise ValueError('Parsed transfer disagrees with token identity')
                    if outer != route['index'] and any(account in owned for account in (source, destination)):
                        raise ValueError('Unrelated token transfer prevents swap quantity attribution')
                    flow[source] -= quantity
                    flow[destination] += quantity
                    continue
                if outer != route['index']:
                    raise ValueError('Unreviewed outer program may bundle other economic activity')
                # CPIs are part of a successful, verified route; net owned legs
                # still require exact parsed-transfer reconciliation below.
            _verify_ephemeral_wrapped(flat, allowed_wrapped, owned, keys, pre_lamports,
                                      post_lamports, address, route, fee)
            retained_funding = _retained_user_volume_funding(flat, keys, pre_lamports, post_lamports, address, route)
            if retained_funding:
                from .transaction_format import original_instruction_paths
                original = record.get('raw')
                original = original.get('result') if isinstance(original, dict) and 'result' in original else original
                for item in retained_funding:
                    _, outer, ordinal = item['path'].split('.')
                    group_index = next(index for index, group in enumerate(meta['innerInstructions']) if group['index'] == int(outer))
                    path = f'meta.innerInstructions.{group_index}.instructions.{ordinal}'
                    item['raw_paths'] = original_instruction_paths(original,
                        [path + '.parsed.info.' + field for field in ('source', 'newAccount', 'lamports', 'space', 'owner')])
            for account in route['owned_accounts']:
                if account not in owned and account not in allowed_wrapped:
                    raise ValueError('Route user account lacks event-time wallet ownership')
            deltas, decimals = defaultdict(int), {}
            rent_correction = 0
            for account, identity in owned.items():
                delta = post.get(account, 0) - pre.get(account, 0)
                mint, index = identity['mint'], identity['index']
                if mint == WSOL and identity['decimals'] != 9:
                    raise ValueError('Wrapped SOL decimals disagree with native units')
                if mint == WSOL and account not in post:
                    if post_lamports[index] != 0 or closures.get(account) != address:
                        raise ValueError('Missing wrapped SOL closing token balance requires a primary wallet closure and zero native endpoint')
                if mint == WSOL and account not in pre:
                    creations, initializations = [], []
                    for position, (_, path, instruction, _) in enumerate(flat):
                        parsed = instruction.get('parsed')
                        if not isinstance(parsed, dict):
                            continue
                        info, kind = parsed.get('info', {}), parsed.get('type')
                        program = _program(instruction, keys)
                        if program == SYSTEM_ID and kind in ('createAccount', 'createAccountWithSeed') and info.get('newAccount') == account:
                            creations.append((position, info))
                        if program in TOKEN_IDS and kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3') and info.get('account') == account:
                            initializations.append((position, program, info))
                    if (pre_lamports[index] != 0 or len(creations) != 1 or len(initializations) != 1
                            or creations[0][1].get('source') != address
                            or creations[0][1].get('owner') != initializations[0][1]
                            or initializations[0][1] != 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
                            or _integer(creations[0][1].get('space')) != 165
                            or _integer(creations[0][1].get('lamports')) == 0
                            or initializations[0][2].get('owner') != address
                            or initializations[0][2].get('mint') != WSOL
                            or not creations[0][0] < initializations[0][0] < next(
                                position for position, row in enumerate(flat) if row[1] == route['path'])):
                        raise ValueError('Missing wrapped SOL opening token balance requires primary wallet-funded creation and initialization; ATA idempotence is not proof')
                if mint != WSOL and delta != flow[account]:
                    raise ValueError('Wallet token delta does not reconcile to parsed swap transfers')
                if mint in decimals and decimals[mint] != identity['decimals']:
                    raise ValueError('Conflicting decimals across owned accounts for one mint')
                decimals[mint] = identity['decimals']
                deltas[mint] += delta
                native_delta = post_lamports[index] - pre_lamports[index]
                reserve_delta = native_delta - delta if mint == WSOL else native_delta
                if reserve_delta > 0:
                    if rent_funders.get(account) != address:
                        raise ValueError('Unproven or sponsored token account rent funding')
                    rent_correction += reserve_delta
                elif reserve_delta < 0:
                    if closures.get(account) != address:
                        raise ValueError('Unproven token account rent refund')
                    rent_correction += reserve_delta
            wallet_index = keys.index(address)
            settlement = (post_lamports[wallet_index] - pre_lamports[wallet_index]
                          + (fee if paid else 0) + rent_correction + deltas.pop(WSOL, 0)
                          - outside_native_delta + sum(item['lamports'] for item in retained_funding))
            wsol_accounts = allowed_wrapped | {account for account, identity in owned.items() if identity['mint'] == WSOL}
            if wsol_accounts and settlement != sum(flow[account] for account in wsol_accounts):
                raise ValueError('Isolated native consideration does not reconcile to wallet-owned wrapped SOL swap transfers')
            native_roles = _unresolved_native_roles(flat, owned, wsol_accounts, keys,
                pre_lamports, address, route, retained_funding, settlement)
            for role in native_roles:
                if role['path'].startswith('instructions.'):
                    role['raw_paths'] = ['transaction.message.' + role['path']]
                else:
                    _, outer, ordinal = role['path'].split('.')
                    group_index = next(index for index, group in enumerate(meta['innerInstructions']) if group['index'] == int(outer))
                    role['raw_paths'] = [f'meta.innerInstructions.{group_index}.instructions.{ordinal}']
            assets = [(mint, delta) for mint, delta in deltas.items() if delta]
            usdc_delta = next((delta for mint, delta in assets if mint == USDC), 0)
            other_assets = [(mint, delta) for mint, delta in assets if mint != USDC]
            usdc_settled = (
                not settlement
                and usdc_delta
                and len(other_assets) == 1
                and (other_assets[0][1] > 0) != (usdc_delta > 0)
            )
            if settlement and usdc_delta and other_assets:
                raise ValueError('SOL and USDC both moved; cross-settlement remains unresolved and is not converted')
            if usdc_settled:
                mint, quantity = other_assets[0]
                if mint == WSOL:
                    usdc_decimals = decimals.get(USDC)
                    if usdc_decimals is None:
                        raise ValueError('USDC settlement is missing event-time decimals')
                    with localcontext() as context:
                        context.prec = 192
                        amount_usdc = canonical(Decimal(abs(usdc_delta)) / (Decimal(10) ** usdc_decimals))
                        amount_sol = canonical(Decimal(abs(quantity)) / LAMPORTS)
                    from_asset = 'USDC' if usdc_delta < 0 else 'SOL'
                    to_asset = 'SOL' if usdc_delta < 0 else 'USDC'
                    emit('conversion', route['path'], mint=USDC, quantity_raw=str(abs(usdc_delta)),
                         decimals=usdc_decimals, amount_sol=amount_sol, amount_usdc=amount_usdc,
                         classification='quote_conversion', from_asset=from_asset, to_asset=to_asset,
                         source=route['program'], venue=route['program'], instruction=route['instruction'],
                         owner=address, fee_sol=fee_sol if paid else '0', paid_by_wallet=paid,
                         settlement_mint=USDC, settlement_asset='USDC',
                         reason='USDC↔SOL is a quote conversion, not a sale of a USDC or SOL position')
                    conversions += 1
                    continue
                kind = 'buy' if quantity > 0 else 'sell'
                if route['expected_kind'] and route['expected_kind'] != kind:
                    raise ValueError('Venue instruction direction conflicts with wallet exchange direction')
                usdc_decimals = decimals.get(USDC)
                if usdc_decimals is None:
                    raise ValueError('USDC settlement is missing event-time decimals')
                with localcontext() as context:
                    context.prec = 192
                    amount_usdc = canonical(Decimal(abs(usdc_delta)) / (Decimal(10) ** usdc_decimals))
                allocate_fee = paid and not outside_native and not native_roles
                excluded_funding_lamports = rent_correction + sum(item['lamports'] for item in retained_funding)
                excluded_funding_sol = canonical(Decimal(excluded_funding_lamports) / LAMPORTS)
                emit(kind, route['path'], mint=mint, quantity_raw=str(abs(quantity)),
                     decimals=decimals[mint], amount_sol=None, amount_usdc=amount_usdc,
                     classification='market',
                     source=route['program'], venue=route['program'], instruction=route['instruction'],
                     owner=address, fee_sol=fee_sol if allocate_fee else '0', paid_by_wallet=paid,
                     settlement_mint=USDC, settlement_asset='USDC',
                     excluded_funding_sol=excluded_funding_sol,
                     native_cash_role_state='UNKNOWN' if native_roles or outside_native else 'PASS',
                     unresolved_native_roles=native_roles,
                     retained_account_funding=[{**item, 'evidence': hashes} for item in retained_funding],
                     observed_pre_quantity_raw=str(sum(pre.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                     observed_post_quantity_raw=str(sum(post.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                     observation_scope='Transaction account keys only; no proof of wallet-wide zero inventory',
                     reason='Verified route_v2 and reconciled wallet USDC/token deltas; SOL fee stays SOL and is not USDC P&L')
                if allocate_fee:
                    fee_event['allocation'] = 'buy_basis' if kind == 'buy' else 'sell_exit'
                    fee_event['allocated_trade_path'] = route['path']
                    fee_event['settlement_note'] = 'Network fee is SOL; not converted into USDC consideration'
                supported += 1
                administration.extend(nonce_administration)
                for role in native_roles:
                    info = role['facts']
                    lamports = info.get('lamports') if role['kind'] in ('transfer', 'createAccount', 'createAccountWithSeed') else None
                    amount = canonical(Decimal(lamports) / LAMPORTS) if type(lamports) is int else None
                    direction = 'withdrawal' if info.get('source') in {address, *owned, *wsol_accounts} else 'deposit'
                    uncertain_cash(role['reason'], role['path'], amount=amount, direction=direction, facts=info)
                for movement in outside_native:
                    uncertain_cash('Outside native movement may be a trading fee, tip or capital flow; its economic role remains unresolved',
                        movement['path'], amount=canonical(Decimal(movement['lamports']) / LAMPORTS),
                        direction=movement['direction'], facts={'source': movement['source'], 'destination': movement['destination']})
                continue
            if len(assets) != 1:
                raise ValueError('Swap requires exactly one net non-SOL asset; crossquotes and multiple assets remain unresolved')
            mint, quantity = assets[0]
            if not settlement or (quantity > 0) == (settlement > 0):
                raise ValueError('No opposing SOL consideration for the evidenced asset exchange')
            from scanner.mass_search.verified_costs import is_verified_tip_account
            verified_tip_lamports = sum(
                item['lamports'] for item in outside_native
                if item.get('direction') == 'withdrawal' and is_verified_tip_account(item.get('destination'))
            )
            unverified_debit_lamports = sum(
                item['lamports'] for item in outside_native
                if item.get('direction') == 'withdrawal' and not is_verified_tip_account(item.get('destination'))
            )
            tips_lamports = verified_tip_lamports
            tips_sol = canonical(Decimal(tips_lamports) / LAMPORTS) if tips_lamports else '0'
            unverified_debits_sol = canonical(Decimal(unverified_debit_lamports) / LAMPORTS) if unverified_debit_lamports else '0'
            network_fee_sol = fee_sol if paid else '0'
            fees_and_tips_sol = canonical(Decimal(str(network_fee_sol)) + Decimal(str(tips_sol)))
            allocate_fee = paid and not outside_native and not native_roles
            if mint == USDC:
                usdc_decimals = decimals.get(USDC)
                if usdc_decimals is None:
                    raise ValueError('USDC settlement is missing event-time decimals')
                with localcontext() as context:
                    context.prec = 192
                    amount_usdc = canonical(Decimal(abs(quantity)) / (Decimal(10) ** usdc_decimals))
                    amount = canonical(Decimal(abs(settlement)) / LAMPORTS)
                from_asset = 'USDC' if quantity < 0 else 'SOL'
                to_asset = 'SOL' if quantity < 0 else 'USDC'
                emit('conversion', route['path'], mint=USDC, quantity_raw=str(abs(quantity)),
                     decimals=usdc_decimals, amount_sol=amount, amount_usdc=amount_usdc,
                     classification='quote_conversion', from_asset=from_asset, to_asset=to_asset,
                     source=route['program'], venue=route['program'], instruction=route['instruction'],
                     owner=address, fee_sol=fees_and_tips_sol, network_fee_sol=network_fee_sol,
                     tips_sol=tips_sol, paid_by_wallet=paid, settlement_mint=WSOL,
                     reason='USDC↔SOL is a quote conversion, not a sale of a USDC or SOL position')
                conversions += 1
                continue
            kind = 'buy' if quantity > 0 else 'sell'
            if route['expected_kind'] and route['expected_kind'] != kind:
                raise ValueError('Venue instruction direction conflicts with wallet exchange direction')
            with localcontext() as context:
                context.prec = 192
                amount = canonical(Decimal(abs(settlement)) / LAMPORTS)
            excluded_funding_lamports = rent_correction + sum(item['lamports'] for item in retained_funding)
            excluded_funding_sol = canonical(Decimal(excluded_funding_lamports) / LAMPORTS)
            emit(kind, route['path'], mint=mint, quantity_raw=str(abs(quantity)),
                 decimals=decimals[mint], amount_sol=amount, classification='unknown',
                 source=route['program'], venue=route['program'], instruction=route['instruction'],
                 owner=address, fee_sol=fees_and_tips_sol if allocate_fee else '0',
                 network_fee_sol=network_fee_sol, tips_sol=tips_sol,
                 fees_and_tips_sol=fees_and_tips_sol,
                 unverified_debits_sol=unverified_debits_sol,
                 sensitivity_unverified_debits_sol=unverified_debits_sol,
                 excluded_funding_sol=excluded_funding_sol,
                 paid_by_wallet=paid,
                 settlement_mint=WSOL,
                 native_cash_role_state='UNKNOWN' if native_roles or outside_native else 'PASS',
                 unresolved_native_roles=native_roles,
                 retained_account_funding=[{**item, 'evidence': hashes} for item in retained_funding],
                 observed_pre_quantity_raw=str(sum(pre.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                 observed_post_quantity_raw=str(sum(post.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                 observation_scope='Transaction account keys only; no proof of wallet-wide zero inventory',
                 reason=(
                     'Verified spot instruction and reconciled transaction-level owned net exchange; allocated network fee is linked to its display evidence'
                     if allocate_fee else
                     'Verified spot instruction and reconciled transaction-level owned net exchange; outside native stays unresolved and is listed separately from allocated fees'
                 ))
            if allocate_fee:
                fee_event['allocation'] = 'buy_basis' if kind == 'buy' else 'sell_exit'
                fee_event['allocated_trade_path'] = route['path']
                fee_event['tips_sol'] = tips_sol
                fee_event['network_fee_sol'] = network_fee_sol
            supported += 1
            administration.extend(nonce_administration)
            for role in native_roles:
                info = role['facts']
                lamports = info.get('lamports') if role['kind'] in ('transfer', 'createAccount', 'createAccountWithSeed') else None
                amount = canonical(Decimal(lamports) / LAMPORTS) if type(lamports) is int else None
                direction = 'withdrawal' if info.get('source') in {address, *owned, *wsol_accounts} else 'deposit'
                uncertain_cash(role['reason'], role['path'], amount=amount, direction=direction, facts=info)
            for movement in outside_native:
                uncertain_cash('Outside native movement may be a trading fee, tip or capital flow; its economic role remains unresolved',
                    movement['path'], amount=canonical(Decimal(movement['lamports']) / LAMPORTS),
                    direction=movement['direction'], facts={'source': movement['source'], 'destination': movement['destination']})
        except (ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
            unknown(str(exc))
    decoded_sigs = {event.get('signature') for event in events if event.get('kind') in ('buy', 'sell', 'conversion')}
    unsupported = []
    decoded_unresolved_cash = []
    seen_unsupported = set()
    seen_cash = set()
    for issue in unresolved:
        signature = issue.get('signature')
        if not signature:
            continue
        if signature in decoded_sigs:
            if signature in seen_cash:
                continue
            seen_cash.add(signature)
            decoded_unresolved_cash.append({
                'signature': signature,
                'reason': issue.get('reason'),
                'path': issue.get('path'),
                'classification': 'decoded_swap_unresolved_cash_role',
            })
            continue
        if signature in seen_unsupported:
            continue
        seen_unsupported.add(signature)
        unsupported.append({
            'signature': signature,
            'reason': issue.get('reason'),
            'path': issue.get('path'),
            'classification': 'unsupported_swap',
        })
    coverage = {'decoder_version': DECODER_VERSION, 'transactions': len(rows), 'decoded_swaps': supported,
                'supported_transactions': supported, 'failed_transactions': failed,
                'unresolved_transactions': len({issue['signature'] for issue in unresolved}),
                'unsupported_transactions': unsupported,
                'unsupported_tx_count': len(unsupported),
                'decoded_unresolved_cash': decoded_unresolved_cash,
                'decoded_unresolved_cash_count': len(decoded_unresolved_cash),
                'conversions': conversions,
                'unrecognized_transactions': no_swap, 'complete': False, 'history_complete': False,
                'scope': 'Fetched sample; recognized single spot routes with SOL/wSOL or USDC settlement',
                'classification': 'UNKNOWN', 'route_fixtures_independently_verified': False,
                'non_economic_instructions': administration,
                'fixture_validation': [{'program': program, 'instruction': instruction,
                                        'discriminator': (_anchor(instruction).hex() if program != RAYDIUM_AMM else None),
                                        **_RAW_FIXTURE_ROUTES.get((program, instruction), {'state': 'SYNTHETIC_ONLY',
                                            'scope': 'No successful raw mainnet golden fixture for this discriminator'})}
                                       for program, instruction in sorted(used_routes)]}
    return {'events': events, 'findings': findings, 'coverage': coverage,
            'unresolved': unresolved, 'evidence': evidence}


def inspect_token_risk(raw_mint_info, pool_observations=None):
    """Check present mint controls and provided present observations, never safety.

    Accept a getAccountInfo envelope/result/value or parsed account object.
    Optional observation dict: pools[{liquidity_usd}], owners[{owner,amount_raw}],
    owner_balances_complete (explicit bool), and evidence[hashes]. Pool API numbers
    may be decimal strings or integers; floats do not support precision-sensitive
    conclusions. Token account concentration is not owner concentration.
    """
    findings, gates = [], {}
    observations = pool_observations if isinstance(pool_observations, dict) else {}
    hashes = observations.get('evidence', [])
    if not isinstance(hashes, list) or any(not isinstance(value, str) for value in hashes):
        hashes = []

    def check(key, state, detail, severity=None, actual=None):
        gates[key] = {'state': state, 'detail': detail, 'actual': actual, 'evidence': hashes}
        if severity or state == 'UNKNOWN':
            findings.append({'key': key, 'severity': severity or 'info', 'title': key.replace('_', ' ').capitalize(),
                             'detail': detail, 'state': state, 'evidence': hashes})

    account = raw_mint_info
    if isinstance(account, dict) and 'result' in account:
        account = account['result']
    if isinstance(account, dict) and 'value' in account:
        account = account['value']
    info, extensions, supply = None, None, None
    if isinstance(account, dict):
        parsed = account.get('data', {}).get('parsed') if isinstance(account.get('data'), dict) else None
        if account.get('owner') in TOKEN_IDS and isinstance(parsed, dict) and parsed.get('type') == 'mint':
            info = parsed.get('info')
    if not isinstance(info, dict):
        check('mint_identity', 'UNKNOWN', 'Missing parsed mint account from a supported token program')
        check('mint_authority', 'UNKNOWN', 'Mint authority has not been observed')
        check('freeze_authority', 'UNKNOWN', 'Freeze authority has not been observed')
        check('token_extensions', 'UNKNOWN', 'Token extension controls have not been observed')
    else:
        check('mint_identity', 'PASS', 'Current RPC account owner and parsed type identify a token mint')
        for key, title in (('mintAuthority', 'mint_authority'), ('freezeAuthority', 'freeze_authority')):
            if key not in info:
                check(title, 'UNKNOWN', 'Authority field is absent from current mint evidence')
            elif info[key] is None:
                check(title, 'PASS', 'Authority is currently revoked; this does not establish historical behavior')
            elif isinstance(info[key], str) and info[key]:
                check(title, 'FAIL', 'Active authority can change token supply' if key == 'mintAuthority' else 'Active authority can freeze token accounts', 'warning', info[key])
            else:
                check(title, 'UNKNOWN', 'Malformed authority evidence')
        try:
            supply = raw_quantity(info.get('supply'))
        except ValueError:
            pass
        token_2022 = account['owner'] == 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
        extensions = info.get('extensions')
        if not token_2022:
            check('token_extensions', 'PASS', 'Legacy token program has no Token-2022 mint extensions')
        elif not isinstance(extensions, list):
            check('token_extensions', 'UNKNOWN', 'Token-2022 mint extension inventory is missing')
        else:
            risky, unknown = [], []
            passive = {'metadatapointer', 'tokenmetadata', 'grouppointer', 'groupmemberpointer',
                       'tokengroup', 'tokengroupmember', 'interestbearingconfig', 'scaleduiamount'}
            for extension in extensions:
                if not isinstance(extension, dict):
                    unknown.append('malformed extension')
                    continue
                name = extension.get('extension') or extension.get('type')
                normalized = str(name).replace('_', '').replace('-', '').lower()
                state = extension.get('state') or {}
                if not isinstance(state, dict):
                    state = {}
                if normalized == 'permanentdelegate':
                    risky.append('Permanent delegate can transfer or burn holder tokens')
                elif normalized == 'transferfeeconfig':
                    risky.append('Transfer fee configuration can change received quantity and execution costs')
                elif normalized == 'transferhook':
                    risky.append('Transfer hook executes external logic and may restrict transfers')
                elif normalized == 'defaultaccountstate':
                    value = state.get('accountState', state.get('state'))
                    if str(value).lower() in ('frozen', '2'):
                        risky.append('New token accounts default to frozen')
                    elif str(value).lower() not in ('initialized', '1'):
                        unknown.append('Default account state is unresolved')
                elif normalized in ('nontransferable', 'pausable', 'pausableconfig', 'confidentialtransfermint', 'confidentialtransferfeeconfig'):
                    risky.append(f'{name} may restrict ordinary token transfers')
                elif normalized not in passive:
                    unknown.append(f'Unreviewed extension: {name}')
            if risky:
                check('token_extensions', 'FAIL', '; '.join(risky), 'warning')
            elif unknown:
                check('token_extensions', 'UNKNOWN', '; '.join(unknown))
            else:
                check('token_extensions', 'PASS', 'No reviewed restrictive extension in the provided current inventory')
    pools = observations.get('pools')
    liquidity = []
    if isinstance(pools, list):
        for pool in pools:
            try:
                value = pool.get('liquidity_usd')
                value = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
                liquidity.append(decimal(value))
            except (ValueError, TypeError, AttributeError):
                continue
    if liquidity:
        total = sum(liquidity, Decimal(0))
        check('current_liquidity', 'PASS' if total > 0 else 'FAIL',
              'Provided pools report current liquidity; this is not executable depth or historical liquidity',
              'warning' if total == 0 else None, canonical(total))
    else:
        check('current_liquidity', 'UNKNOWN', 'Current liquidity has not been measured for a supported pool')
    check('liquidity_control', 'UNKNOWN', 'LP ownership, lock terms, concentrated liquidity positions and withdrawal rights require independent pool evidence')
    owners = observations.get('owners')
    amounts = defaultdict(int)
    valid_owners = isinstance(owners, list) and bool(owners)
    if valid_owners:
        try:
            for owner in owners:
                if not isinstance(owner.get('owner'), str) or not owner['owner']:
                    raise ValueError('Missing owner')
                amounts[owner['owner']] += raw_quantity(owner['amount_raw'])
        except (ValueError, KeyError, TypeError, AttributeError):
            valid_owners = False
    if valid_owners and supply and sum(amounts.values()) == supply and observations.get('owner_balances_complete') is True:
        with localcontext() as context:
            context.prec = 192
            largest = Decimal(max(amounts.values())) / Decimal(supply) * 100
            top10 = Decimal(sum(sorted(amounts.values(), reverse=True)[:10])) / Decimal(supply) * 100
        check('holder_concentration', 'FAIL' if largest > 20 else 'PASS',
              'Current largest owner and top ten shares use provided owner aggregation; pool/escrow attribution still needs review',
              'warning' if largest > 20 else None,
              {'largest_owner_pct': canonical(largest), 'top10_owner_pct': canonical(top10)})
    else:
        check('holder_concentration', 'UNKNOWN', 'Complete current balances grouped by owner and mint supply are required; top token accounts alone do not identify owner concentration')
    check('creator_links', 'UNKNOWN', 'Creator funding links, deployer holdings and coordinated accounts have not been investigated')
    check('historical_sellability', 'UNKNOWN', 'Current controls and reported liquidity do not prove historical or future exit execution')
    states = {value['state'] for value in gates.values()}
    return {'gates': gates, 'findings': findings, 'status': 'FLAGGED' if 'FAIL' in states else 'UNRESOLVED',
            'scope': 'Current observations only', 'safe': None,
            'notes': ['No legitimacy score or promise of safe copying.', 'Current checks cannot rule out scams, manipulation or future losses.']}
