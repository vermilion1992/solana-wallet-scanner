"""Pure, bounded compiled-instruction views; archived payloads are never changed.

Binary layouts are pinned in tests/fixtures/compiled_instructions/schema.json.
This is a representation adapter, not authentication, historical completeness,
DEX classification or a proof of CPI signer authority. Unsupported instructions
remain present as original evidence alongside explicit rejecting raw paths.
"""
from copy import deepcopy


METHOD = 'compiled-instructions-v2'
SYSTEM_ID = '11111111111111111111111111111111'
TOKEN_ID = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022_ID = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
COMPUTE_ID = 'ComputeBudget111111111111111111111111111111'
ASSOCIATED_ID = 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
MEMO_IDS = {'MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr',
            'Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo'}
RENT_ID = 'SysvarRent111111111111111111111111111111111'
RECENT_BLOCKHASHES_ID = 'SysvarRecentB1ockHashes11111111111111111111'
_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_BASE58 = {char: index for index, char in enumerate(_ALPHABET)}
_PROGRAM_NAMES = {SYSTEM_ID: 'system', TOKEN_ID: 'spl-token',
                  TOKEN_2022_ID: 'spl-token-2022', COMPUTE_ID: 'compute-budget',
                  ASSOCIATED_ID: 'spl-associated-token-account',
                  **{program: 'spl-memo' for program in MEMO_IDS}}
# Read-only GetAccountDataSize request descriptors. The u16 ordering is pinned
# to spl-token-2022-interface 3.1.1, not to the presentation enum ordering in
# Agave. Describing an extension request proves no extension/account state.
_SIZE_EXTENSIONS = (
    'uninitialized', 'transferFeeConfig', 'transferFeeAmount', 'mintCloseAuthority',
    'confidentialTransferMint', 'confidentialTransferAccount', 'defaultAccountState',
    'immutableOwner', 'memoTransfer', 'nonTransferable', 'interestBearingConfig',
    'cpiGuard', 'permanentDelegate', 'nonTransferableAccount', 'transferHook',
    'transferHookAccount', 'confidentialTransferFeeConfig', 'confidentialTransferFeeAmount',
    'metadataPointer', 'tokenMetadata', 'groupPointer', 'tokenGroup',
    'groupMemberPointer', 'tokenGroupMember', 'confidentialMintBurn', 'scaledUiAmount',
    'pausable', 'pausableAccount', 'permissionedBurn',
)


class CompiledInstructionError(ValueError):
    """A typed unsupported/malformed view, with original source coordinates."""
    def __init__(self, code, reason, paths):
        super().__init__(reason)
        self.code = code
        self.paths = sorted(set(paths))

    def receipt(self, path):
        return {'path': path, 'code': self.code, 'reason': str(self),
                'raw_paths': self.paths}


def _reject(code, reason, *paths):
    raise CompiledInstructionError(code, reason, paths)


def _base58_decode(text, path, maximum=1232):
    if not isinstance(text, str) or not text or len(text) > maximum * 2:
        _reject('invalid-base58', 'Missing, invalid or oversized base58 evidence', path)
    number = 0
    for char in text:
        if char not in _BASE58:
            _reject('invalid-base58', 'Non-base58 character in instruction evidence', path)
        number = number * 58 + _BASE58[char]
    leading = len(text) - len(text.lstrip('1'))
    size = (number.bit_length() + 7) // 8
    if size + leading > maximum:
        _reject('instruction-budget', 'Decoded instruction exceeds reviewed size bound', path)
    return b'\0' * leading + number.to_bytes(size, 'big')


def _base58_encode(data):
    number = int.from_bytes(data, 'big')
    chars = []
    while number:
        number, remainder = divmod(number, 58)
        chars.append(_ALPHABET[remainder])
    leading = len(data) - len(data.lstrip(b'\0'))
    return '1' * leading + ''.join(reversed(chars))


def _pubkey(value, path):
    if len(_base58_decode(value, path, 32)) != 32:
        _reject('invalid-pubkey', 'Public key is not exactly 32 decoded bytes', path)
    return value


def _loaded_shape(loaded, static_count):
    if not isinstance(loaded, dict) or any(not isinstance(loaded.get(k), list) for k in ('writable', 'readonly')):
        _reject('invalid-loaded-keys', 'Loaded addresses lack writable/readonly arrays', 'meta.loadedAddresses')
    if static_count + len(loaded['writable']) + len(loaded['readonly']) > 256:
        _reject('invalid-account-keys', 'Loaded key count exceeds the compiled u8 account-key bound',
                'transaction.message.accountKeys', 'meta.loadedAddresses')


def resolve_account_keys(raw):
    """Resolve static + loaded writable + loaded readonly keys and outer signers.

    jsonParsed keys already include lookup-table entries; source flags distinguish
    them. Missing loaded addresses for a compiled v0 lookup is a dependency.
    """
    if not isinstance(raw, dict):
        _reject('invalid-transaction', 'Transaction result is not an object', 'transaction')
    version = raw.get('version', 'legacy')
    if not (version == 'legacy' or type(version) is int and version == 0):
        _reject('unsupported-version', 'Transaction version has no reviewed compiled key contract', 'version')
    transaction = raw.get('transaction')
    message = transaction.get('message') if isinstance(transaction, dict) else None
    meta = raw.get('meta')
    if not isinstance(message, dict) or not isinstance(meta, dict):
        _reject('invalid-transaction', 'Missing transaction message or metadata',
                'transaction.message', 'meta')
    entries = message.get('accountKeys')
    if not isinstance(entries, list) or not entries or len(entries) > 256:
        _reject('invalid-account-keys', 'Account keys must be a nonempty bounded list',
                'transaction.message.accountKeys')
    shapes = {type(item) for item in entries}
    if len(shapes) != 1 or not shapes <= {str, dict}:
        _reject('mixed-account-keys', 'Account keys mix unsupported representations',
                'transaction.message.accountKeys')
    keys, signers = [], set()
    paths = ['transaction.message.accountKeys']
    if shapes == {dict}:
        for index, entry in enumerate(entries):
            path = f'transaction.message.accountKeys.{index}'
            keys.append(_pubkey(entry.get('pubkey'), path + '.pubkey'))
            if type(entry.get('signer')) is not bool or type(entry.get('writable')) is not bool:
                _reject('invalid-key-flags', 'Parsed key signer/writable flags must be booleans', path)
            if entry.get('source', 'transaction') not in ('transaction', 'lookupTable'):
                _reject('invalid-key-source', 'Unsupported parsed account-key source', path + '.source')
            if entry.get('source') == 'lookupTable' and entry['signer']:
                _reject('invalid-key-flags', 'Lookup-table account cannot be a transaction signer', path)
            if entry['signer']:
                signers.add(keys[-1])
        static = [entry for entry in entries if entry.get('source', 'transaction') == 'transaction']
        lookup_entries = [entry for entry in entries if entry.get('source') == 'lookupTable']
        if entries != static + lookup_entries:
            _reject('conflicting-key-order', 'Parsed lookup keys must follow static transaction keys',
                    'transaction.message.accountKeys')
        if version == 'legacy' and lookup_entries:
            _reject('conflicting-loaded-keys', 'Legacy transaction cannot contain parsed lookup account keys',
                    'version', 'transaction.message.accountKeys')
        header = message.get('header')
        if header is not None:
            if not isinstance(header, dict):
                _reject('invalid-header', 'Parsed message header is malformed', 'transaction.message.header')
            required = header.get('numRequiredSignatures')
            readonly_signed = header.get('numReadonlySignedAccounts')
            readonly_unsigned = header.get('numReadonlyUnsignedAccounts')
            if (any(type(v) is not int for v in (required, readonly_signed, readonly_unsigned)) or
                    not 1 <= required <= len(static) or not 0 <= readonly_signed < required or
                    not 0 <= readonly_unsigned <= len(static) - required):
                _reject('invalid-header', 'Parsed header signer/read-only counts are malformed', 'transaction.message.header')
            for index, entry in enumerate(static):
                writable = (index < required - readonly_signed if index < required else
                            index < len(static) - readonly_unsigned)
                if entry['signer'] is not (index < required) or entry['writable'] is not writable:
                    _reject('conflicting-key-flags', 'Parsed signer/writable roles contradict message header',
                            f'transaction.message.accountKeys.{index}', 'transaction.message.header')
            paths.append('transaction.message.header')
        loaded = meta.get('loadedAddresses')
        if loaded is not None:
            _loaded_shape(loaded, len(static))
            expected = {field: [entry['pubkey'] for entry in lookup_entries if entry['writable'] is writable]
                        for field, writable in (('writable', True), ('readonly', False))}
            if (any(loaded[field] != expected[field] for field in expected) or
                    [entry['pubkey'] for entry in lookup_entries] != loaded['writable'] + loaded['readonly']):
                _reject('conflicting-loaded-keys', 'Parsed and separately loaded account keys disagree',
                        'transaction.message.accountKeys', 'meta.loadedAddresses')
    else:
        keys = [_pubkey(item, f'transaction.message.accountKeys.{index}') for index, item in enumerate(entries)]
        header = message.get('header')
        if not isinstance(header, dict):
            _reject('missing-signers', 'Compiled outer signer evidence requires a message header',
                    'transaction.message.header')
        required = header.get('numRequiredSignatures')
        readonly_signed = header.get('numReadonlySignedAccounts')
        readonly_unsigned = header.get('numReadonlyUnsignedAccounts')
        if (any(type(v) is not int for v in (required, readonly_signed, readonly_unsigned)) or
                not 1 <= required <= len(keys) or not 0 <= readonly_signed < required or
                not 0 <= readonly_unsigned <= len(keys) - required):
            _reject('invalid-header', 'Invalid static message signer/read-only counts',
                    'transaction.message.header')
        signers = set(keys[:required])
        paths.append('transaction.message.header')
        lookups = message.get('addressTableLookups', [])
        if not isinstance(lookups, list) or len(lookups) > 256:
            _reject('invalid-lookups', 'Address table lookups must be a bounded list', 'transaction.message.addressTableLookups')
        loaded = meta.get('loadedAddresses')
        if lookups and loaded is None:
            _reject('missing-loaded-keys', 'Versioned lookup indices need loaded address evidence',
                    'transaction.message.addressTableLookups', 'meta.loadedAddresses')
        if loaded is not None:
            _loaded_shape(loaded, len(keys))
            paths.append('meta.loadedAddresses')
        if version == 'legacy' and (lookups or loaded and (loaded['writable'] or loaded['readonly'])):
            _reject('conflicting-loaded-keys', 'Legacy transaction cannot claim lookup-loaded accounts',
                    'version', 'meta.loadedAddresses', 'transaction.message.addressTableLookups')
        if loaded and (loaded['writable'] or loaded['readonly']) and not lookups:
            _reject('missing-lookups', 'Loaded accounts lack their compiled lookup count evidence',
                    'meta.loadedAddresses', 'transaction.message.addressTableLookups')
        if lookups:
            expected = {'writable': 0, 'readonly': 0}
            table_positions = {}
            for index, lookup in enumerate(lookups):
                path = f'transaction.message.addressTableLookups.{index}'
                if not isinstance(lookup, dict):
                    _reject('invalid-lookups', 'Malformed address-table lookup', path)
                table = _pubkey(lookup.get('accountKey'), path + '.accountKey')
                claimed = table_positions.setdefault(table, set())
                for field in expected:
                    indices = lookup.get(field + 'Indexes')
                    if (not isinstance(indices, list) or len(indices) > 256 or any(type(i) is not int or not 0 <= i <= 255 for i in indices)
                            or len(indices) != len(set(indices))):
                        _reject('invalid-lookups', 'Malformed or duplicate address-table indices', path + '.' + field + 'Indexes')
                    if claimed.intersection(indices):
                        _reject('conflicting-lookups', 'One address-table position is claimed by multiple compiled key roles',
                                path + '.' + field + 'Indexes')
                    claimed.update(indices)
                    expected[field] += len(indices)
                    if sum(expected.values()) + len(keys) > 256:
                        _reject('invalid-lookups', 'Address table indices exceed compiled account-key count bound',
                                'transaction.message.addressTableLookups')
            if any(len(loaded[field]) != expected[field] for field in expected):
                _reject('conflicting-loaded-keys', 'Loaded-address count disagrees with lookup indices',
                        'transaction.message.addressTableLookups', 'meta.loadedAddresses')
        if loaded is not None:
            for field in ('writable', 'readonly'):
                keys.extend(_pubkey(item, f'meta.loadedAddresses.{field}.{index}')
                            for index, item in enumerate(loaded[field]))
    if len(keys) > 256 or len(keys) != len(set(keys)):
        _reject('invalid-account-keys', 'Resolved keys exceed compiled index bounds or contain duplicate identities',
                'transaction.message.accountKeys', 'meta.loadedAddresses')
    return {'keys': keys, 'signers': signers, 'raw_paths': paths}


def key_roles(raw):
    """Validated full key table roles, for existing nonce administration checks.

    This is a derived view only. No key is added, reordered, signed or replaced.
    """
    context = resolve_account_keys(raw)
    entries = raw['transaction']['message']['accountKeys']
    if isinstance(entries[0], dict):
        roles = [{'pubkey': entry['pubkey'], 'signer': entry['signer'],
                  'writable': entry['writable'], 'source': entry.get('source', 'transaction')}
                 for entry in entries]
    else:
        header = raw['transaction']['message']['header']
        required = header['numRequiredSignatures']
        writable_signed = required - header['numReadonlySignedAccounts']
        writable_unsigned_end = len(entries) - header['numReadonlyUnsignedAccounts']
        roles = [{'pubkey': key, 'signer': index < required,
                  'writable': index < writable_signed if index < required else index < writable_unsigned_end,
                  'source': 'transaction'} for index, key in enumerate(entries)]
        loaded = raw['meta'].get('loadedAddresses') or {}
        roles.extend({'pubkey': key, 'signer': False, 'writable': writable, 'source': 'lookupTable'}
                     for field, writable in (('writable', True), ('readonly', False))
                     for key in loaded.get(field, []))
    return {'keys': roles, 'raw_paths': context['raw_paths'], 'method': METHOD}


def _exact(data, size, path):
    if len(data) != size:
        _reject('unsupported-layout', 'Instruction payload is truncated or has unreviewed trailing bytes', path + '.data')


def _arity(accounts, size, path):
    if len(accounts) != size:
        _reject('unsupported-account-arity', 'Instruction account arity has no reviewed layout', path + '.accounts')


def _signer_fields(info, accounts, index, name, signers, inner, path, program,
                   *, allow_extension_accounts=False):
    """Match primary RPC names; multisig threshold needs separate account state."""
    extra = accounts[index + 1:]
    if extra:
        if program == TOKEN_2022_ID and allow_extension_accounts:
            info[name] = accounts[index]
            info['extensionAccounts'] = list(extra)
            required = [accounts[index]]
        elif program == TOKEN_2022_ID:
            _reject('unsupported-extension-accounts', 'Token-2022 extra accounts may be extension roles', path + '.accounts')
        else:
            if len(extra) > 11 or len(extra) != len(set(extra)):
                _reject('unsupported-multisig', 'Multisig signer list exceeds or duplicates reviewed roles', path + '.accounts')
            info['multisig' + name[0].upper() + name[1:]] = accounts[index]
            info['signers'] = extra
            required = extra
    else:
        info[name] = accounts[index]
        required = [accounts[index]]
    if not inner and any(account not in signers for account in required):
        _reject('missing-required-signer', 'Required outer instruction signer is absent from message signer evidence',
                path + '.accounts', 'transaction.message.header')
    return required


def _sysvar(accounts, index, expected, path):
    if accounts[index] != expected:
        _reject('conflicting-sysvar', 'Instruction sysvar role has the wrong public key', path + '.accounts.' + str(index))


def _system(data, accounts, signers, inner, path):
    if len(data) < 4:
        _reject('unsupported-layout', 'System enum tag is truncated', path + '.data')
    tag = int.from_bytes(data[:4], 'little')
    sizes = {0: (52, 2), 1: (36, 1), 2: (12, 2), 4: (4, 3),
             5: (12, 5), 6: (36, 3), 7: (36, 2), 8: (12, 1)}
    if tag not in sizes:
        _reject('unsupported-opcode', 'System opcode has no reviewed fixed-width contract', path + '.data')
    length, arity = sizes[tag]
    _exact(data, length, path)
    _arity(accounts, arity, path)
    amount = int.from_bytes(data[4:12], 'little')
    required = []
    if tag == 0:
        kind = 'createAccount'
        info = {'source': accounts[0], 'newAccount': accounts[1], 'lamports': amount,
                'space': int.from_bytes(data[12:20], 'little'), 'owner': _base58_encode(data[20:52])}
        required = accounts[:2]
    elif tag == 1:
        kind, info, required = 'assign', {'account': accounts[0], 'owner': _base58_encode(data[4:36])}, accounts[:1]
    elif tag == 2:
        kind, info, required = 'transfer', {'source': accounts[0], 'destination': accounts[1], 'lamports': amount}, accounts[:1]
    elif tag == 4:
        _sysvar(accounts, 1, RECENT_BLOCKHASHES_ID, path)
        kind, info, required = 'advanceNonce', {'nonceAccount': accounts[0], 'recentBlockhashesSysvar': accounts[1],
                                              'nonceAuthority': accounts[2]}, accounts[2:3]
    elif tag == 5:
        _sysvar(accounts, 2, RECENT_BLOCKHASHES_ID, path)
        _sysvar(accounts, 3, RENT_ID, path)
        kind, info, required = 'withdrawFromNonce', {'nonceAccount': accounts[0], 'destination': accounts[1],
                                                    'recentBlockhashesSysvar': accounts[2], 'rentSysvar': accounts[3],
                                                    'nonceAuthority': accounts[4], 'lamports': amount}, accounts[4:5]
    elif tag == 6:
        _sysvar(accounts, 1, RECENT_BLOCKHASHES_ID, path)
        _sysvar(accounts, 2, RENT_ID, path)
        kind, info = 'initializeNonce', {'nonceAccount': accounts[0], 'recentBlockhashesSysvar': accounts[1],
                                        'rentSysvar': accounts[2], 'nonceAuthority': _base58_encode(data[4:36])}
    elif tag == 7:
        kind, info, required = 'authorizeNonce', {'nonceAccount': accounts[0], 'nonceAuthority': accounts[1],
                                                 'newAuthorized': _base58_encode(data[4:36])}, accounts[1:2]
    else:
        kind, info, required = 'allocate', {'account': accounts[0], 'space': amount}, accounts[:1]
    if not inner and any(account not in signers for account in required):
        _reject('missing-required-signer', 'Required outer System signer is not proved by message header',
                path + '.accounts', 'transaction.message.header')
    return kind, info, required


def _token(data, accounts, signers, inner, path, program):
    tag = data[0]
    kind = None
    info = {}
    required = []
    fixed = {1: (1, 4, 'initializeAccount'), 3: (9, 3, 'transfer'),
             4: (9, 3, 'approve'), 5: (1, 2, 'revoke'), 9: (1, 3, 'closeAccount'),
             12: (10, 4, 'transferChecked'), 13: (10, 4, 'approveChecked'),
             16: (33, 3, 'initializeAccount2'), 17: (1, 1, 'syncNative'),
             18: (33, 2, 'initializeAccount3'), 22: (1, 1, 'initializeImmutableOwner')}
    if tag in fixed:
        length, minimum, kind = fixed[tag]
        _exact(data, length, path)
        if len(accounts) < minimum:
            _reject('unsupported-account-arity', 'Token instruction is missing required account roles', path + '.accounts')
        if tag in (3, 4, 5, 9, 12, 13):
            token_2022_transfer = program == TOKEN_2022_ID and tag in (3, 12)
            if not token_2022_transfer and len(accounts) > minimum + 11:
                _reject('unsupported-account-arity', 'Token signer account list exceeds reviewed bound', path + '.accounts')
            if tag in (3, 4):
                info = {'source': accounts[0], 'destination' if tag == 3 else 'delegate': accounts[1],
                        'amount': str(int.from_bytes(data[1:9], 'little'))}
                required = _signer_fields(
                    info, accounts, 2, 'authority' if tag == 3 else 'owner', signers, inner, path, program,
                    allow_extension_accounts=token_2022_transfer,
                )
            elif tag == 5:
                info = {'source': accounts[0]}
                required = _signer_fields(info, accounts, 1, 'owner', signers, inner, path, program)
            elif tag == 9:
                info = {'account': accounts[0], 'destination': accounts[1]}
                # Token-2022 clients often repeat the owner as extra accounts.
                # Allow that encoding; other extra parties stay fail-closed.
                extra = accounts[3:]
                owner = accounts[2] if len(accounts) > 2 else None
                duplicate_owner = bool(extra) and program == TOKEN_2022_ID and owner and all(item == owner for item in extra)
                required = _signer_fields(
                    info, accounts, 2, 'owner', signers, inner, path, program,
                    allow_extension_accounts=duplicate_owner,
                )
            else:
                amount, decimals = int.from_bytes(data[1:9], 'little'), data[9]
                digits = str(amount).rjust(decimals + 1, '0')
                ui = (digits[:-decimals] + '.' + digits[-decimals:]).rstrip('0').rstrip('.') if decimals else digits
                info = {'source': accounts[0], 'mint': accounts[1], 'destination' if tag == 12 else 'delegate': accounts[2],
                        'tokenAmount': {'amount': str(amount), 'decimals': decimals, 'uiAmountString': ui}}
                required = _signer_fields(
                    info, accounts, 3, 'authority' if tag == 12 else 'owner', signers, inner, path, program,
                    allow_extension_accounts=token_2022_transfer,
                )
        else:
            _arity(accounts, minimum, path)
            info = {'account': accounts[0]}
            if tag in (1, 16, 18):
                info['mint'] = accounts[1]
                info['owner'] = accounts[2] if tag == 1 else _base58_encode(data[1:33])
                if tag != 18:
                    rent_index = 3 if tag == 1 else 2
                    _sysvar(accounts, rent_index, RENT_ID, path)
                    info['rentSysvar'] = accounts[rent_index]
    elif tag == 21:
        _arity(accounts, 1, path)
        kind, info = 'getAccountDataSize', {'mint': accounts[0]}
        # The classic Token program ignores trailing data for this opcode. Its
        # bytes remain in the original immutable source and receipt coordinates.
        # Token-2022 instead parses every trailing pair as a known u16 enum.
        if program == TOKEN_2022_ID:
            if (len(data) - 1) % 2:
                _reject('unsupported-layout', 'Token-2022 size query has a truncated extension type', path + '.data')
            extensions = []
            for offset in range(1, len(data), 2):
                number = int.from_bytes(data[offset:offset + 2], 'little')
                if number >= len(_SIZE_EXTENSIONS):
                    _reject('unsupported-extension-type', 'Token-2022 size query names an unknown pinned extension type', path + '.data')
                extensions.append(_SIZE_EXTENSIONS[number])
            if extensions:
                info['extensionTypes'] = extensions
    elif tag == 6:
        if len(data) < 3 or data[1] > 3 or data[2] not in (0, 1):
            _reject('unsupported-authority', 'Malformed option or unsupported Token authority type', path + '.data')
        _exact(data, 3 if data[2] == 0 else 35, path)
        if not 2 <= len(accounts) <= 13:
            _reject('unsupported-account-arity', 'Authority operation lacks bounded authority roles', path + '.accounts')
        authority = ('mintTokens', 'freezeAccount', 'accountOwner', 'closeAccount')[data[1]]
        kind, info = 'setAuthority', {'mint' if data[1] < 2 else 'account': accounts[0],
                                      'authorityType': authority,
                                      'newAuthority': None if data[2] == 0 else _base58_encode(data[3:35])}
        required = _signer_fields(info, accounts, 1, 'authority', signers, inner, path, program)
    elif tag == 26 and program == TOKEN_2022_ID:
        if len(data) < 2:
            _reject('unsupported-layout', 'Token-2022 transfer-fee extension is truncated', path + '.data')
        sub = data[1]
        if sub == 1:
            # TransferCheckedWithFee: amount u64, decimals u8, fee u64
            _exact(data, 19, path)
            if len(accounts) < 4:
                _reject('unsupported-account-arity', 'transferCheckedWithFee is missing required account roles', path + '.accounts')
            amount, decimals = int.from_bytes(data[2:10], 'little'), data[10]
            fee = int.from_bytes(data[11:19], 'little')
            digits = str(amount).rjust(decimals + 1, '0')
            ui = (digits[:-decimals] + '.' + digits[-decimals:]).rstrip('0').rstrip('.') if decimals else digits
            kind, info = 'transferCheckedWithFee', {
                'source': accounts[0], 'mint': accounts[1], 'destination': accounts[2],
                'tokenAmount': {'amount': str(amount), 'decimals': decimals, 'uiAmountString': ui},
                'fee': str(fee),
            }
            required = _signer_fields(
                info, accounts, 3, 'authority', signers, inner, path, program,
                allow_extension_accounts=True,
            )
        else:
            _reject('unsupported-opcode', 'Token-2022 transfer-fee sub-instruction has no reviewed layout', path + '.data')
    elif tag in (0, 20):
        if len(data) < 35 or data[34] not in (0, 1):
            _reject('unsupported-layout', 'Malformed mint authority option', path + '.data')
        _exact(data, 35 if data[34] == 0 else 67, path)
        _arity(accounts, 2 if tag == 0 else 1, path)
        kind, info = 'initializeMint' if tag == 0 else 'initializeMint2', {
            'mint': accounts[0], 'decimals': data[1], 'mintAuthority': _base58_encode(data[2:34])}
        if data[34]:
            info['freezeAuthority'] = _base58_encode(data[35:67])
        if tag == 0:
            _sysvar(accounts, 1, RENT_ID, path)
            info['rentSysvar'] = accounts[1]
    else:
        _reject('unsupported-opcode', 'Token opcode/extension has no reviewed binary normalization contract', path + '.data')
    return kind, info, required


def normalize_instruction(instruction, keys, *, signers=None, inner=False, path='instruction', key_paths=()):
    """Return a distinct instruction view + original paths, or a typed failure.

    For inner CPI instructions signer roles are reported as runtime-CPI, never
    asserted to be message signers (program-derived invoke_signed is possible).
    """
    if not isinstance(instruction, dict):
        _reject('invalid-instruction', 'Instruction is not an object', path)
    if not isinstance(keys, list) or len(keys) > 256 or any(not isinstance(k, str) for k in keys):
        _reject('invalid-account-keys', 'Resolved account keys have an unsupported shape', 'transaction.message.accountKeys')
    programs = []
    if 'programId' in instruction:
        programs.append(_pubkey(instruction['programId'], path + '.programId'))
    if 'programIdIndex' in instruction:
        index = instruction['programIdIndex']
        if type(index) is not int or not 0 <= index < len(keys) or index > 255:
            _reject('invalid-program-index', 'Program index is outside compiled account keys', path + '.programIdIndex')
        programs.append(_pubkey(keys[index], path + '.programIdIndex'))
    if not programs or len(set(programs)) != 1:
        _reject('conflicting-program', 'Program identity is absent or conflicting', path + '.programId', path + '.programIdIndex')
    program = programs[0]
    name = instruction.get('program')
    names = ({'spl-token', 'spl-token-2022'} if program == TOKEN_2022_ID else
             {_PROGRAM_NAMES[program]} if program in _PROGRAM_NAMES else set())
    if name is not None and name not in names:
        _reject('conflicting-program', 'Program alias contradicts reviewed program identity', path + '.program', path + '.programId')
    if 'parsed' in instruction:
        if any(field in instruction for field in ('accounts', 'data')):
            _reject('mixed-representation', 'Parsed and opaque representations cannot replace each other',
                    path + '.parsed', path + '.accounts', path + '.data')
        return {'instruction': deepcopy(instruction), 'normalization': None}
    key_set = set(keys)
    if program not in key_set:
        _reject('invalid-program-membership', 'Opaque instruction program is absent from the primary key table',
                path + '.programId' if 'programId' in instruction else path + '.programIdIndex',
                'transaction.message.accountKeys')
    accounts = instruction.get('accounts')
    if not isinstance(accounts, list) or len(accounts) > 256:
        _reject('invalid-account-list', 'Opaque instruction lacks a bounded account list', path + '.accounts')
    types = {type(item) for item in accounts}
    if len(types) > 1 or not types <= {int, str}:
        _reject('mixed-account-list', 'Opaque accounts mix indices/addresses or invalid types', path + '.accounts')
    resolved = []
    for index, account in enumerate(accounts):
        field = path + '.accounts.' + str(index)
        if type(account) is int:
            if not 0 <= account < len(keys) or account > 255:
                _reject('invalid-account-index', 'Account index is outside compiled account keys', field)
            account = keys[account]
        account = _pubkey(account, field)
        if account not in key_set:
            _reject('invalid-account-membership', 'Opaque instruction account is absent from the primary key table',
                    field, 'transaction.message.accountKeys')
        resolved.append(account)
    text = instruction.get('data')
    data = b'' if text == '' and (program == ASSOCIATED_ID or program in MEMO_IDS) else _base58_decode(text, path + '.data')
    receipt = {'path': path, 'raw_paths': sorted(set([path + '.data', path + '.accounts',
                path + '.programId' if 'programId' in instruction else path + '.programIdIndex', *key_paths])),
               'method': METHOD, 'program': program,
               'signer_evidence': 'runtime-cpi-not-message-signers' if inner else 'message-header',
               'required_signer_roles': []}
    if program == COMPUTE_ID or program in MEMO_IDS:
        view = deepcopy(instruction)
        view['programId'] = program
        receipt['kind'] = 'opaque-non-economic'
        return {'instruction': view, 'normalization': receipt}
    if program not in (SYSTEM_ID, TOKEN_ID, TOKEN_2022_ID, ASSOCIATED_ID):
        _reject('unsupported-program', 'Program has no reviewed compiled semantic adapter', path + '.programIdIndex', path + '.data')
    if signers is None and not inner:
        _reject('missing-signers', 'Outer compiled instruction requires explicit signer evidence', 'transaction.message.header')
    if program == ASSOCIATED_ID:
        if data not in (b'', b'\0', b'\1'):
            _reject('unsupported-opcode', 'Associated-account opcode has no reviewed creation layout', path + '.data')
        if data == b'' and len(resolved) == 7 and resolved[6] == RENT_ID:
            _arity(resolved, 7, path)
        else:
            _arity(resolved, 6, path)
        if resolved[4] != SYSTEM_ID or resolved[5] not in (TOKEN_ID, TOKEN_2022_ID):
            _reject('conflicting-program', 'Associated creation has incompatible System/Token account roles', path + '.accounts')
        if not inner and resolved[0] not in (signers or set()):
            _reject('missing-required-signer', 'Associated-account funding source is not a message signer',
                    path + '.accounts', 'transaction.message.header')
        kind = 'createIdempotent' if data == b'\1' else 'create'
        info = {'source': resolved[0], 'account': resolved[1], 'wallet': resolved[2],
                'mint': resolved[3], 'systemProgram': resolved[4], 'tokenProgram': resolved[5]}
        if len(resolved) == 7:
            info['rentSysvar'] = resolved[6]
        required = resolved[:1]
    else:
        kind, info, required = (_system(data, resolved, signers or set(), inner, path) if program == SYSTEM_ID else
                                _token(data, resolved, signers or set(), inner, path, program))
    receipt['kind'] = kind
    receipt['required_signer_roles'] = required
    view = {field: deepcopy(value) for field, value in instruction.items()
            if field not in ('programIdIndex', 'accounts', 'data', 'program', 'programId')}
    view.update({'programId': program, 'program': _PROGRAM_NAMES[program],
                 'parsed': {'type': kind, 'info': info}})
    return {'instruction': view, 'normalization': receipt}


def normalize_transaction(raw):
    """Derived RPC view + failures; no source mutation, provider access or trust flags.

    ``raw`` may be a transaction result or JSON-RPC result envelope. Every inner
    group must have a valid unique parent; malformed groups stay explicit.
    """
    view = deepcopy(raw)
    result = view.get('result') if isinstance(view, dict) and 'result' in view else view
    output = {'raw': view, 'method': METHOD, 'normalizations': [], 'issues': []}
    if not isinstance(result, dict):
        output['issues'].append({'path': 'transaction', 'code': 'invalid-transaction',
                                 'reason': 'Missing transaction result', 'raw_paths': ['transaction']})
        return output
    transaction = result.get('transaction')
    message = transaction.get('message') if isinstance(transaction, dict) else None
    meta = result.get('meta')
    if not isinstance(message, dict) or not isinstance(meta, dict):
        output['issues'].append({'path': 'transaction', 'code': 'invalid-transaction',
                                 'reason': 'Missing message/metadata', 'raw_paths': ['transaction.message', 'meta']})
        return output
    # Failed instructions did not execute. Their payloads cannot erase fee proof.
    if meta.get('err') is not None:
        return output
    instructions, groups = message.get('instructions'), meta.get('innerInstructions')
    groups = [] if groups is None else groups
    if not isinstance(instructions, list) or not isinstance(groups, list):
        output['issues'].append({'path': 'transaction.message.instructions', 'code': 'invalid-instruction-containers',
                                 'reason': 'Instruction containers are malformed',
                                 'raw_paths': ['transaction.message.instructions', 'meta.innerInstructions']})
        return output
    if len(instructions) > 10000 or len(groups) > 10000 or sum(len(g.get('instructions', [])) if isinstance(g, dict) and isinstance(g.get('instructions'), list) else 0 for g in groups) > 10000:
        output['issues'].append({'path': 'transaction.message.instructions', 'code': 'instruction-budget',
                                 'reason': 'Instruction inspection exceeds explicit adapter bound',
                                 'raw_paths': ['transaction.message.instructions', 'meta.innerInstructions']})
        return output
    flattened = [(instructions, index, f'transaction.message.instructions.{index}', False)
                 for index in range(len(instructions))]
    seen = set()
    for index, group in enumerate(groups):
        path = f'meta.innerInstructions.{index}'
        if (not isinstance(group, dict) or type(group.get('index')) is not int or
                not 0 <= group['index'] < len(instructions) or group['index'] in seen or
                not isinstance(group.get('instructions'), list)):
            output['issues'].append({'path': path, 'code': 'invalid-inner-association',
                                     'reason': 'Inner group has malformed or duplicated outer association', 'raw_paths': [path]})
            continue
        seen.add(group['index'])
        flattened.extend((group['instructions'], child, path + f'.instructions.{child}', True)
                         for child in range(len(group['instructions'])))
    # Unchanged parsed inputs need no new signer/header assumptions.
    opaque = any(not isinstance(items[index], dict) or 'parsed' not in items[index] or
                 any(field in items[index] for field in ('accounts', 'data')) for items, index, _, _ in flattened)
    if not opaque:
        return output
    try:
        context = resolve_account_keys(result)
    except CompiledInstructionError as error:
        output['issues'].append(error.receipt('transaction.message.accountKeys'))
        return output
    for items, index, path, inner in flattened:
        try:
            normalized = normalize_instruction(items[index], context['keys'], signers=context['signers'],
                                               inner=inner, path=path, key_paths=context['raw_paths'])
            items[index] = normalized['instruction']
            if normalized['normalization'] is not None:
                output['normalizations'].append(normalized['normalization'])
        except CompiledInstructionError as error:
            output['issues'].append(error.receipt(path))
    return output
