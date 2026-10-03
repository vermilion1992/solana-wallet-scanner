"""Normalize instruction evidence before proving named-account irrelevance.

Compiled/partially decoded account lists and fully parsed instructions have
separate supported shapes. A mixed parsed/accounts or parsed/data shape has no
reviewed reconciliation contract here, so neither representation may win.
These local checks do not authenticate a transaction on Solana.
"""
from .decoder import TOKEN_IDS, SYSTEM_ID, ASSOCIATED_ID, COMPUTE_ID, MEMO_IDS

_TOKEN_REFERENCES = {
    'transfer': ('source', 'destination'),
    'transferChecked': ('source', 'destination', 'mint'),
    'approve': ('source', 'delegate'), 'approveChecked': ('source', 'delegate', 'mint'),
    'revoke': ('source',), 'closeAccount': ('account', 'destination'),
    'mintTo': ('mint', 'account'), 'mintToChecked': ('mint', 'account'),
    'burn': ('account', 'mint'), 'burnChecked': ('account', 'mint'),
    'freezeAccount': ('account', 'mint'), 'thawAccount': ('account', 'mint'),
    'initializeAccount': ('account', 'mint'), 'initializeAccount2': ('account', 'mint'),
    'initializeAccount3': ('account', 'mint'), 'initializeImmutableOwner': ('account',),
    'syncNative': ('account',), 'getAccountDataSize': ('mint',),
    'initializeMint': ('mint',), 'initializeMint2': ('mint',),
}
# Agave parse_token.rs, pinned schema reference in the conformance fixture.
# Extension authority types need their own reviewed contracts before admission.
_AUTHORITY_TARGETS = {'mintTokens': 'mint', 'freezeAccount': 'mint',
                      'accountOwner': 'account', 'closeAccount': 'account'}
_SYSTEM_REFERENCES = {
    'transfer': ('source', 'destination'), 'transferWithSeed': ('source', 'destination', 'sourceBase'),
    'createAccount': ('source', 'newAccount'), 'createAccountWithSeed': ('source', 'newAccount', 'base'),
    'assign': ('account',), 'assignWithSeed': ('account', 'base'),
    'allocate': ('account',), 'allocateWithSeed': ('account', 'base'),
    'advanceNonce': ('nonceAccount', 'nonceAuthority', 'recentBlockhashesSysvar'),
    'initializeNonce': ('nonceAccount',), 'authorizeNonce': ('nonceAccount',),
    'withdrawNonce': ('nonceAccount', 'destination'),
}
_ASSOCIATED_REFERENCES = {'create': ('account', 'source', 'mint', 'wallet'),
                         'createIdempotent': ('account', 'source', 'mint', 'wallet')}


class InstructionEvidenceError(ValueError):
    def __init__(self, reason, paths):
        super().__init__(reason)
        self.paths = sorted(set(paths))


def inspect_instruction(instruction, keys, *, path):
    """Return validated program/reference facts, or rejecting raw field paths.

    Parsed reference strings preserve the existing conservative info traversal.
    Operation semantics remain the quantity parser's responsibility. An empty
    opaque account list can prove disjointness; a parsed instruction cannot use
    that list to hide contradictory participation. Failed transactions are
    handled atomically by the caller, before executed-instruction analysis.
    """
    def reject(reason, *fields):
        raise InstructionEvidenceError(reason, [path + '.' + field for field in fields])

    if not isinstance(instruction, dict):
        raise InstructionEvidenceError('Malformed instruction evidence', [path])
    programs, program_paths = [], []
    if 'programId' in instruction:
        program = instruction['programId']
        if not isinstance(program, str) or not program:
            reject('Malformed instruction program identity', 'programId')
        programs.append(program)
        program_paths.append(path + '.programId')
    if 'programIdIndex' in instruction:
        index = instruction['programIdIndex']
        if type(index) is not int or not 0 <= index < len(keys):
            reject('Instruction program index is outside primary account keys', 'programIdIndex')
        programs.append(keys[index])
        program_paths.append(path + '.programIdIndex')
    if not programs:
        reject('Missing instruction program identity', 'programId', 'programIdIndex')
    if len(set(programs)) != 1:
        reject('Instruction program representations disagree', 'programId', 'programIdIndex')
    program, references, reference_paths = programs[0], set(), []
    if 'parsed' in instruction:
        competing = [field for field in ('accounts', 'data') if field in instruction]
        if competing:
            reject('Mixed parsed and opaque instruction representations have no supported reconciliation contract',
                   'parsed', 'parsed.info', *competing)
        parsed = instruction['parsed']
        if program in MEMO_IDS and isinstance(parsed, str):
            return {'program': program, 'references': references, 'paths': program_paths + [path + '.parsed'],
                    'non_economic': True, 'shape': 'parsed-memo'}
        info = parsed.get('info') if isinstance(parsed, dict) else None
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if (program not in TOKEN_IDS | {SYSTEM_ID, ASSOCIATED_ID} or not isinstance(info, dict) or not info
            or not isinstance(kind, str) or not kind):
            reject('Parsed instruction lacks a supported program/type/info representation', 'parsed', 'programId')
        contract = (_TOKEN_REFERENCES if program in TOKEN_IDS else
                    _SYSTEM_REFERENCES if program == SYSTEM_ID else _ASSOCIATED_REFERENCES).get(kind)
        if program in TOKEN_IDS and kind == 'setAuthority':
            authority = info.get('authorityType')
            target = _AUTHORITY_TARGETS.get(authority) if isinstance(authority, str) else None
            if target is None:
                reject('Token authority type has no supported target contract', 'parsed.info.authorityType')
            competing_target = 'account' if target == 'mint' else 'mint'
            if competing_target in info:
                reject('Token authority target fields contradict the supported authority type',
                       'parsed.info.authorityType', 'parsed.info.' + target, 'parsed.info.' + competing_target)
            contract = (target,)
        if program in TOKEN_IDS and kind in ('approve', 'approveChecked', 'revoke') and 'account' in info:
            reject('Token permission target must use the RPC source field', 'parsed.info.source', 'parsed.info.account')
        if contract is None:
            reject('Parsed operation has no supported account-reference contract', 'parsed.type', 'parsed.info')
        for field in contract:
            if not isinstance(info.get(field), str) or not info[field]:
                reject('Parsed operation lacks a valid required account reference', 'parsed.info.' + field)
        pending = [(path + '.parsed.info.' + key, value) for key, value in info.items()]
        while pending:
            field, value = pending.pop()
            if isinstance(value, str) and value:
                references.add(value)
                reference_paths.append(field)
            elif isinstance(value, dict):
                pending.extend((field + '.' + key, item) for key, item in value.items())
            elif isinstance(value, list):
                pending.extend((field + '.' + str(index), item) for index, item in enumerate(value))
        shape = 'parsed'
    else:
        accounts = instruction.get('accounts')
        if not isinstance(accounts, list):
            reject('Opaque instruction lacks a valid account-reference list', 'accounts')
        types = set()
        for index, value in enumerate(accounts):
            field = 'accounts.' + str(index)
            if type(value) is int:
                if not 0 <= value < len(keys):
                    reject('Instruction account reference is outside primary account keys', field)
                references.add(keys[value])
                types.add('index')
            elif isinstance(value, str) and value:
                references.add(value)
                types.add('address')
            else:
                reject('Instruction account reference is malformed', field)
            reference_paths.append(path + '.' + field)
        if len(types) > 1:
            reject('Instruction account list mixes compiled indices and decoded addresses', 'accounts')
        shape = 'opaque'
        reference_paths.append(path + '.accounts')
    return {'program': program, 'references': references,
            'paths': sorted(set(program_paths + reference_paths)), 'shape': shape,
            'non_economic': program == COMPUTE_ID or program in MEMO_IDS}
