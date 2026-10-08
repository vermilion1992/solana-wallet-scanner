"""Shared fail-closed preflight. Runs before every pricing path.

Order-independence: an allowlisted coverage-gap reason cannot be reached
until this preflight passes. Outer and inner, parsed and compiled.
"""
from __future__ import annotations

from scanner.decoder import ASSOCIATED_ID, SYSTEM_ID, TOKEN_IDS

JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
REVIEWED_ALLOCATE_SPACES = frozenset({137, 165, 170})
NONCE_KINDS = frozenset({
    "advanceNonce", "advanceNonceAccount",
    "withdrawNonceAccount", "initializeNonceAccount", "authorizeNonceAccount",
})
ALLOCATE_KINDS = frozenset({"allocate", "assign", "allocateWithSeed", "assignWithSeed"})
SYSTEM_TAG_ASSIGN = 1
SYSTEM_TAG_NONCE = 4
SYSTEM_TAG_WITHDRAW_NONCE = 5
SYSTEM_TAG_INIT_NONCE = 6
SYSTEM_TAG_AUTH_NONCE = 7
SYSTEM_TAG_ALLOCATE = 8
UNSAFE_SYSTEM_TAGS = frozenset({
    SYSTEM_TAG_ASSIGN, SYSTEM_TAG_NONCE, SYSTEM_TAG_WITHDRAW_NONCE,
    SYSTEM_TAG_INIT_NONCE, SYSTEM_TAG_AUTH_NONCE, SYSTEM_TAG_ALLOCATE,
})


def fail_closed_reason(raw, address, *, trade=False):
    """Return a non-allowlisted refusal reason, or None when the tx may proceed.

    `trade=True` also requires a wallet signer and present innerInstructions
    (C2 / net-balance priced trades). C1 plains use trade=False.
    """
    if not isinstance(raw, dict) or not address:
        return "Fail-closed preflight: raw transaction or wallet is missing"
    try:
        from scanner.investigation import (
            REVIEWED_INNER_PROGRAMS,
            _REVIEWED_LIFECYCLE_OWNERS,
            _data,
            _keys,
            _program,
        )
    except Exception:
        return "Fail-closed preflight: decoder helpers unavailable"
    transaction = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    try:
        keys = _keys(message, meta)
    except (ValueError, TypeError, KeyError, IndexError):
        return "Fail-closed preflight: account keys are unreadable"
    if address not in keys:
        return "Fail-closed preflight: wallet is absent from account keys"
    version = raw.get("version", "legacy")
    if version not in ("legacy", 0):
        return "Fail-closed preflight: transaction version has no reviewed compiled key contract"

    owned = {address}
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if not isinstance(row, dict) or row.get("owner") != address:
                continue
            index = row.get("accountIndex")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
                owned.add(keys[index])

    jupiter_short = False
    for role, instruction in _walk(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            return "Fail-closed preflight: instruction program is unreadable"
        parsed = _hydrate(instruction, keys, program)
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else {}
        if not isinstance(info, dict):
            info = {}

        if _mixed_conflict(instruction, parsed, keys):
            return "Fail-closed preflight: parsed and opaque instruction representations conflict"

        if program == JUPITER and role == "outer":
            try:
                payload = _data(instruction.get("data"))
            except (ValueError, TypeError, KeyError):
                payload = b""
            if len(payload) < 28:
                jupiter_short = True

        if program == SYSTEM_ID:
            unsafe = _system_unsafe(role, kind, info, instruction, keys, address, _REVIEWED_LIFECYCLE_OWNERS, _data)
            if unsafe:
                return unsafe

        if program in TOKEN_IDS:
            ident = _identity_conflict(raw, keys, parsed, instruction, program)
            if ident:
                return ident
            if kind == "closeAccount":
                account = info.get("account")
                dest = info.get("destination")
                if account in owned and dest not in (None, "", address):
                    return "Fail-closed preflight: token account closes to another recipient"

        if role == "inner" and program and program not in REVIEWED_INNER_PROGRAMS:
            touched = _touched(instruction, keys, info)
            if touched.intersection(owned):
                return (
                    "Fail-closed preflight: unknown inner program touches a "
                    f"wallet-owned account; inner venue {program} is not on the reviewed inner allowlist"
                )

    if _sponsored_rent_unverified(raw, address, keys):
        return "Fail-closed preflight: sponsored token-account rent is not wallet-funded"

    if jupiter_short:
        return "Fail-closed preflight: truncated Jupiter swap payload is not a reviewed layout"

    if trade:
        if not _wallet_is_signer(message, keys, address):
            return "Fail-closed preflight: priced trade requires the wallet to be a signer"
        inners = meta.get("innerInstructions")
        if not isinstance(inners, list) or not inners:
            return "Fail-closed preflight: priced trade requires inner instruction evidence"
    return None


def require_preflight(raw, address, *, trade=False):
    reason = fail_closed_reason(raw, address, trade=trade)
    if reason:
        raise ValueError(reason)


def _walk(raw):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for instruction in message.get("instructions") or []:
        if isinstance(instruction, dict):
            yield "outer", instruction
    groups = meta.get("innerInstructions")
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, dict):
            continue
        for instruction in group.get("instructions") or []:
            if isinstance(instruction, dict):
                yield "inner", instruction


def _hydrate(instruction, keys, program):
    parsed = instruction.get("parsed")
    if isinstance(parsed, dict) and parsed.get("type"):
        return parsed
    from scanner.mass_search.plain_tx_read import _hydrate_plain_instruction
    return _hydrate_plain_instruction(instruction, keys) or parsed


def _b58encode(data):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return ("1" * pad) + (encoded or "")


def _mixed_conflict(instruction, parsed, keys=None):
    if not isinstance(parsed, dict) or not parsed.get("type"):
        return False
    if instruction.get("accounts") == []:
        return True
    data = instruction.get("data")
    if data in (None, "", [], b""):
        return False
    # Live RPC often carries agreeing parsed+data. Refuse when compiled
    # hydration disagrees, or when SYSTEM/TOKEN data cannot hydrate to the
    # parsed type (the parsed+opaque `data` variant).
    from scanner.mass_search.plain_tx_read import _hydrate_plain_instruction
    compiled = _hydrate_plain_instruction(instruction, keys or [])
    if not isinstance(compiled, dict) or not compiled.get("type"):
        program = instruction.get("programId")
        kind = parsed.get("type")
        if program in {SYSTEM_ID, *TOKEN_IDS} or kind in {
            "transfer", "transferChecked", "transferCheckedWithFee",
            "allocate", "assign", "createAccount", "closeAccount", "advanceNonce",
        }:
            return True
        accounts = instruction.get("accounts")
        return accounts == [] or accounts is None
    if compiled.get("type") != parsed.get("type"):
        return True
    pinfo = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
    cinfo = compiled.get("info") if isinstance(compiled.get("info"), dict) else {}
    for field in ("source", "destination", "mint", "account", "newAccount", "lamports"):
        if field in cinfo and field in pinfo and cinfo[field] not in (None, "") and pinfo[field] not in (None, "") and cinfo[field] != pinfo[field]:
            return True
    return False


def _system_unsafe(role, kind, info, instruction, keys, address, reviewed_owners, data_fn):
    tag = None
    try:
        payload = data_fn(instruction.get("data")) if instruction.get("data") not in (None, "") else b""
    except (ValueError, TypeError, KeyError):
        payload = b""
    if len(payload) >= 4:
        tag = int.from_bytes(payload[:4], "little")
    if kind in ("withdrawNonceAccount", "initializeNonceAccount", "authorizeNonceAccount") or tag in (
        SYSTEM_TAG_WITHDRAW_NONCE, SYSTEM_TAG_INIT_NONCE, SYSTEM_TAG_AUTH_NONCE,
    ):
        return "Fail-closed preflight: nonce administration mutation is not swap lifecycle"
    is_nonce = kind in ("advanceNonce", "advanceNonceAccount") or tag == SYSTEM_TAG_NONCE
    if is_nonce and role == "inner":
        return "Fail-closed preflight: inner advanceNonce is not swap lifecycle"
    is_alloc = kind in ALLOCATE_KINDS or tag in (SYSTEM_TAG_ASSIGN, SYSTEM_TAG_ALLOCATE)
    if not is_alloc:
        return None
    account = info.get("account")
    if not account:
        accounts = instruction.get("accounts") or []
        resolved = []
        for item in accounts:
            if isinstance(item, str):
                resolved.append(item)
            elif isinstance(item, int) and 0 <= item < len(keys):
                resolved.append(keys[item])
        account = resolved[0] if resolved else None
    space = info.get("space")
    if space is None and tag == SYSTEM_TAG_ALLOCATE and len(payload) >= 12:
        space = int.from_bytes(payload[4:12], "little")
    owner = info.get("owner")
    if owner is None and tag == SYSTEM_TAG_ASSIGN and len(payload) >= 36:
        owner = _b58encode(payload[4:36])
    if role == "outer":
        return "Fail-closed preflight: outer System allocate/assign is not swap lifecycle"
    if account == address:
        return "Fail-closed preflight: System allocate/assign of the wallet is not swap lifecycle"
    if kind == "allocate" or tag == SYSTEM_TAG_ALLOCATE:
        if type(space) is int and space not in REVIEWED_ALLOCATE_SPACES:
            return f"Fail-closed preflight: System allocate space {space} is not a reviewed account layout"
    if kind == "assign" or tag == SYSTEM_TAG_ASSIGN:
        if owner and owner not in reviewed_owners:
            return "Fail-closed preflight: System assign owner is not a reviewed program"
        if not owner:
            return "Fail-closed preflight: System assign owner is not a reviewed program"
    return None


def _identity_conflict(raw, keys, parsed, instruction, program):
    if not isinstance(parsed, dict):
        return None
    kind = parsed.get("type")
    info = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
    if kind not in ("transfer", "transferChecked", "transferCheckedWithFee"):
        return None
    mint = info.get("mint")
    dec = (info.get("tokenAmount") or {}).get("decimals") if isinstance(info.get("tokenAmount"), dict) else None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for field in ("source", "destination"):
        account = info.get(field)
        if not account or account not in keys:
            continue
        idx = keys.index(account)
        for row in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
            if not isinstance(row, dict) or row.get("accountIndex") != idx:
                continue
            if mint and row.get("mint") and mint != row.get("mint"):
                return "Fail-closed preflight: parsed transfer disagrees with token identity"
            row_dec = (row.get("uiTokenAmount") or {}).get("decimals")
            if dec is not None and row_dec is not None and dec != row_dec:
                return "Fail-closed preflight: parsed transfer disagrees with token identity"
    return None


def _touched(instruction, keys, info):
    found = set()
    accounts = instruction.get("accounts") or []
    for item in accounts:
        if isinstance(item, str) and item:
            found.add(item)
        elif isinstance(item, int) and 0 <= item < len(keys):
            found.add(keys[item])
    for field in ("source", "destination", "account", "newAccount", "owner", "authority", "wallet", "mint"):
        value = info.get(field)
        if isinstance(value, str) and value:
            found.add(value)
    return found


def _wallet_is_signer(message, keys, address):
    header = message.get("header") if isinstance(message.get("header"), dict) else {}
    required = header.get("numRequiredSignatures")
    if isinstance(required, int) and not isinstance(required, bool) and required > 0:
        return keys and keys[0] == address
    entries = message.get("accountKeys") or []
    for item in entries:
        if isinstance(item, dict) and item.get("pubkey") == address:
            return item.get("signer") is True
    return bool(keys) and keys[0] == address


def _sponsored_rent_unverified(raw, address, keys):
    """Wallet-owned token-account lamports rose without a wallet-sourced create/transfer."""
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_native = meta.get("preBalances") or []
    post_native = meta.get("postBalances") or []
    owned_indexes = set()
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if not isinstance(row, dict) or row.get("owner") != address:
                continue
            index = row.get("accountIndex")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
                if keys[index] != address:
                    owned_indexes.add(index)
    funded = set()
    for _role, instruction in _walk(raw):
        try:
            from scanner.investigation import _program
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = _hydrate(instruction, keys, program)
        info = parsed.get("info") if isinstance(parsed, dict) else {}
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        if not isinstance(info, dict):
            info = {}
        source = info.get("source")
        dest = info.get("destination") or info.get("newAccount") or info.get("account")
        if program == SYSTEM_ID and kind in ("transfer", "createAccount", "createAccountWithSeed"):
            if dest in keys and source == address:
                funded.add(keys.index(dest))
        if program == ASSOCIATED_ID and dest in keys and source in (address, None):
            # ATA create is wallet-funded only when source/payer is the wallet
            # or omitted (legacy parsed shape). Third-party payer is not funded.
            if source in (address, None) and info.get("source") in (address, None) and info.get("wallet") in (address, None):
                if source == address or info.get("wallet") == address:
                    funded.add(keys.index(dest))
    for index in owned_indexes:
        if index >= len(pre_native) or index >= len(post_native):
            continue
        try:
            before, after = int(pre_native[index]), int(post_native[index])
        except (TypeError, ValueError):
            return True
        if after > before and index not in funded:
            return True
    return False
