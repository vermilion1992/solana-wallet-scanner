"""Declared formats for the application's existing parsed native RPC schema.

This is an application support boundary, not a statement that other versions
are invalid on Solana. A new version needs its own reviewed parser/schema
contract. RPC results omitting version retain the existing legacy convention.
Execution, account keys, instructions and monetary fields have separate checks.
"""


def supported_transaction_format(raw):
    if not isinstance(raw, dict):
        return False
    version = raw.get('version', 'legacy')
    return version == 'legacy' or type(version) is int and version == 0


def instruction_view(raw):
    """Derive reviewed compiled instruction representations without source writes.

    Unknown/malformed operations remain in the view. Native identity, execution,
    chronology, quantities and metric scope keep their own existing validators.
    """
    from .compiled_instructions import normalize_transaction
    if not _needs_instruction_view(raw):
        return raw
    return normalize_transaction(raw)['raw']


def _needs_instruction_view(raw):
    from .compiled_instructions import SYSTEM_ID, TOKEN_ID, TOKEN_2022_ID, COMPUTE_ID, MEMO_IDS, ASSOCIATED_ID
    result = raw.get('result', raw) if isinstance(raw, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get('meta'), dict) or result['meta'].get('err') is not None:
        return False
    transaction = result.get('transaction')
    message = transaction.get('message') if isinstance(transaction, dict) else None
    if not isinstance(message, dict):
        return False
    entries = message.get('accountKeys')
    entries = entries if isinstance(entries, list) else []
    keys = [entry.get('pubkey') if isinstance(entry, dict) else entry for entry in entries]
    loaded = result['meta'].get('loadedAddresses')
    if all(isinstance(entry, str) for entry in entries) and isinstance(loaded, dict):
        for name in ('writable', 'readonly'):
            if isinstance(loaded.get(name), list):
                keys += loaded[name]
    supported = {SYSTEM_ID, TOKEN_ID, TOKEN_2022_ID, COMPUTE_ID, ASSOCIATED_ID} | MEMO_IDS
    outer = message.get('instructions')
    outer = outer if isinstance(outer, list) else []
    groups = result['meta'].get('innerInstructions')
    groups = groups if isinstance(groups, list) else []
    instructions = list(outer)
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get('instructions'), list):
            instructions.extend(group['instructions'])
    for instruction in instructions:
        if not isinstance(instruction, dict) or 'parsed' in instruction:
            continue
        program = instruction.get('programId')
        index = instruction.get('programIdIndex')
        if program is None and type(index) is int and 0 <= index < len(keys):
            program = keys[index]
        if isinstance(program, str) and program in supported:
            return True
    return False


def original_instruction_paths(raw, paths, *, normalized=None):
    """Map derived instruction field paths back to their original byte inputs."""
    from .compiled_instructions import normalize_transaction
    if normalized is None and not _needs_instruction_view(raw):
        return sorted(set(paths))
    normalized = normalize_transaction(raw) if normalized is None else normalized
    result = set()
    for path in paths:
        receipt = next((row for row in normalized['normalizations']
                        if path == row['path'] or path.startswith(row['path'] + '.')), None)
        result.update(receipt['raw_paths'] if receipt is not None else [path])
    return sorted(result)
