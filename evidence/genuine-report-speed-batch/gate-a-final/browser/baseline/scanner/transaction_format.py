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
