"""C1/C2 exact-reconcile READ classification. Unknown stays unreadable.

Proof gates do not change. A transaction is READ only when every wallet SOL
and token delta is explained by parsed instructions (C1) or a recognized
wallet-edge shape (C2). No assumed prices, no silent zero-proceeds, no
cost-lowering transfer-in (DC-9).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext

from scanner.decoder import ASSOCIATED_ID, COMPUTE_ID, MEMO_IDS, SYSTEM_ID, TOKEN_IDS
from scanner.investigation import (
    DFLOW,
    JUPITER,
    LIGHTHOUSE,
    METEORA_DLMM,
    OKX_DEX_ROUTER,
    PUMP,
    PUMP_SWAP,
    RFQ_FILL,
    USDC,
    USDT,
    WSOL,
    _keys,
    _route_flow_disagrees_with_wallet,
    _third_party_pool_leg,
)

READ_KINDS = frozenset({
    "buy", "sell", "conversion", "non_trade", "transfer_in", "transfer_out", "lp",
})
TRADE_KINDS = frozenset({"buy", "sell", "conversion"})
QUOTE_MINTS = frozenset({WSOL, USDC, USDT, "SOL"})
TOKEN_2022_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
OKX_VAULT = "va1t8sdGkReA6XFgAeZGXmdQoiEtMirwy4ifLv7yGdH"
G2G_SPAM = "G2GMMDKkw3LXXNRNLyLMy3myki3yi7tjdyxbBbGrBqrg"
JITO_TIP_ROUTER = "RouterBmuRBkPUbgEDMtdvTZ75GBdSREZR5uGUxxxpb"
PLAIN_PROGRAMS = frozenset({
    SYSTEM_ID, ASSOCIATED_ID, COMPUTE_ID, LIGHTHOUSE, *TOKEN_IDS, *MEMO_IDS,
})
EDGE_SWAP_PROGRAMS = frozenset({
    OKX_DEX_ROUTER, JUPITER, PUMP, PUMP_SWAP, RFQ_FILL, DFLOW,
})
EDGE_NON_TRADE_PROGRAMS = frozenset({
    G2G_SPAM, JITO_TIP_ROUTER, OKX_VAULT,
})
REVIEWED_OUTER_PROGRAMS = frozenset({
    *PLAIN_PROGRAMS, *EDGE_SWAP_PROGRAMS, *EDGE_NON_TRADE_PROGRAMS, METEORA_DLMM,
})
# Coverage-gap first-path reasons that may fill a C2 trade. Anything else stays
# unreadable. Prefix match; keep this list explicit and short.
C2_COVERAGE_GAP_PREFIXES = (
    "No reviewed outer spot swap",
    "No reviewed spot swap instruction for this program",
    "Jupiter route",
)
G2G_MAX_NATIVE_LAMPORTS = 10_000_000
JITO_MAX_NATIVE_LAMPORTS = 1_000_000_000
PUMP_DISTRIBUTE_DISC = bytes.fromhex("623691610246ad2b")
PUMP_BUY_DISC = bytes.fromhex("66063d1201daebea")
DFLOW_ORDER_SETUP_DISC = bytes.fromhex("414b3f4ceb5b5b88")
DFLOW_SWAP_DISC = bytes.fromhex("f8c69e91e17587c8")
OKX_EDGE_DISCS = frozenset({
    bytes.fromhex("aa2955b184501f35"),
    bytes.fromhex("93f17b64f484ae76"),
    bytes.fromhex("bbc9d433109bec3c"),
})
JUPITER_EDGE_DISCS = frozenset({
    bytes.fromhex("bb64facc31c4af14"),
    bytes.fromhex("e517cb977ae3ad2a"),
    bytes.fromhex("d19853937cfed8e9"),
})
RFQ_EDGE_DISCS = frozenset({bytes.fromhex("a860b7a35c0a28a0")})
PUMPSWAP_EDGE_DISCS = frozenset({bytes.fromhex("33e685a4017f83ad")})
LAMPORTS = Decimal(1_000_000_000)
SOL_DUST_LAMPORTS = 100_000
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _canonical(value):
    with localcontext() as ctx:
        ctx.prec = 192
        quantized = Decimal(value).quantize(Decimal("0.000000001"))
        text = format(quantized, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text


def _b58decode(value):
    if isinstance(value, list) and len(value) == 2 and value[1] == "base64":
        import base64
        return base64.b64decode(value[0], validate=True)
    if not isinstance(value, str) or not value:
        return b""
    number = 0
    for char in value:
        if char not in _B58:
            return b""
        number = number * 58 + _B58.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + body


def _program_of(instruction, keys):
    program = instruction.get("programId")
    if isinstance(program, str) and program:
        return program
    index = instruction.get("programIdIndex")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
        return keys[index]
    return None


def _iter_instructions(raw):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    for index, instruction in enumerate(message.get("instructions") or []):
        if isinstance(instruction, dict):
            yield "outer", index, instruction
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get("instructions") or []:
            if isinstance(instruction, dict):
                yield "inner", group.get("index"), instruction


def _account_keys(raw):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    try:
        return _keys(message, meta)
    except (ValueError, TypeError, KeyError, IndexError):
        return []


def _int_amount(value):
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _wallet_owned_accounts(raw, address, keys):
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    owned = {}
    decimals = {}
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if not isinstance(row, dict) or row.get("owner") != address:
                continue
            index = row.get("accountIndex")
            mint = row.get("mint")
            if not isinstance(index, int) or not isinstance(mint, str) or not mint:
                continue
            if index < 0 or index >= len(keys):
                continue
            owned[keys[index]] = mint
            token = row.get("uiTokenAmount") or {}
            dec = token.get("decimals")
            if isinstance(dec, int) and not isinstance(dec, bool):
                decimals[mint] = dec
    return owned, decimals


def _wallet_actual_deltas(raw, address, keys):
    """Wallet native lamports (fee-adjusted) and raw token deltas by mint.

    None when any owned token row is unreadable.
    """
    if not isinstance(raw, dict) or not address or not keys or address not in keys:
        return None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_native = meta.get("preBalances") or []
    post_native = meta.get("postBalances") or []
    idx = keys.index(address)
    if idx >= len(pre_native) or idx >= len(post_native):
        return None
    try:
        native = int(post_native[idx]) - int(pre_native[idx])
    except (TypeError, ValueError):
        return None
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) and not isinstance(meta.get("fee"), bool) else 0
    if keys[0] == address:
        native += fee
    tokens = defaultdict(int)
    decimals = {}
    for field, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        rows = meta.get(field)
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                return None
            if row.get("owner") != address:
                continue
            mint = row.get("mint")
            amount = (row.get("uiTokenAmount") or {}).get("amount")
            if mint in (None, "") or amount in (None, ""):
                return None
            qty = _int_amount(amount)
            if qty is None:
                return None
            tokens[mint] += qty * sign
            dec = (row.get("uiTokenAmount") or {}).get("decimals")
            if isinstance(dec, int) and not isinstance(dec, bool):
                decimals[mint] = dec
    return {
        "native": native,
        "tokens": dict(tokens),
        "decimals": decimals,
        "fee": fee,
        "paid": keys[0] == address,
    }


def _programs_present(raw, keys):
    found = []
    for _kind, _index, instruction in _iter_instructions(raw):
        program = _program_of(instruction, keys)
        if program:
            found.append(program)
    return found


def _disc_of(instruction):
    return _b58decode(instruction.get("data"))[:8]


def _outer_discs(raw, keys, program):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    discs = []
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        if _program_of(instruction, keys) == program:
            discs.append(_disc_of(instruction))
    return discs


def _event(kind, *, path="meta.wallet_edge", **fields):
    return {"kind": kind, "path": path, "fields": fields}


def _sol_fields(native_lamports, decimals_map, tokens):
    wsol = tokens.get(WSOL, 0)
    sol = native_lamports + wsol
    fields = {}
    if sol:
        fields["amount_sol"] = _canonical(Decimal(abs(sol)) / LAMPORTS)
        fields["consideration_sol"] = fields["amount_sol"]
    usdc = tokens.get(USDC, 0)
    if usdc:
        dec = decimals_map.get(USDC, 6)
        fields["amount_usdc"] = _canonical(Decimal(abs(usdc)) / (Decimal(10) ** dec))
    usdt = tokens.get(USDT, 0)
    if usdt:
        dec = decimals_map.get(USDT, 6)
        fields["amount_usdt"] = _canonical(Decimal(abs(usdt)) / (Decimal(10) ** dec))
    return fields, sol


def _hydrate_plain_instruction(instruction, keys):
    """Parse compiled System/Token/ATA/Compute so C1 can read live compiled plains."""
    program = _program_of(instruction, keys)
    data = _b58decode(instruction.get("data"))
    accounts = instruction.get("accounts") or []
    resolved = []
    for item in accounts:
        if isinstance(item, str):
            resolved.append(item)
        elif isinstance(item, int) and 0 <= item < len(keys):
            resolved.append(keys[item])
    accounts = resolved
    if program == COMPUTE_ID:
        return {"type": "setComputeUnitLimit", "info": {}}
    if program in MEMO_IDS:
        return {"type": "memo", "info": {}}
    if program == ASSOCIATED_ID:
        return {"type": "createIdempotent" if data == b"\x01" else "create", "info": {
            "source": accounts[0] if accounts else None,
            "account": accounts[1] if len(accounts) > 1 else None,
            "wallet": accounts[2] if len(accounts) > 2 else None,
        }}
    if program == SYSTEM_ID and len(data) >= 4:
        tag = int.from_bytes(data[:4], "little")
        amount = int.from_bytes(data[4:12], "little") if len(data) >= 12 else 0
        if tag == 2 and len(accounts) >= 2:
            return {"type": "transfer", "info": {"source": accounts[0], "destination": accounts[1], "lamports": amount}}
        if tag == 0 and len(accounts) >= 2:
            return {"type": "createAccount", "info": {"source": accounts[0], "newAccount": accounts[1], "lamports": amount}}
        if tag == 4:
            return {"type": "advanceNonce", "info": {}}
        if tag == 1:
            owner = None
            if len(data) >= 36:
                from scanner.mass_search.fail_closed_preflight import _b58encode
                owner = _b58encode(data[4:36])
            return {"type": "assign", "info": {"account": accounts[0] if accounts else None, "owner": owner}}
        if tag == 8:
            space = int.from_bytes(data[4:12], "little") if len(data) >= 12 else None
            return {"type": "allocate", "info": {"account": accounts[0] if accounts else None, "space": space}}
        return None
    if program in TOKEN_IDS and data:
        tag = data[0]
        if tag == 3 and len(data) >= 9 and len(accounts) >= 3:
            return {"type": "transfer", "info": {
                "source": accounts[0], "destination": accounts[1], "authority": accounts[2],
                "amount": str(int.from_bytes(data[1:9], "little")),
            }}
        if tag == 12 and len(data) >= 10 and len(accounts) >= 4:
            return {"type": "transferChecked", "info": {
                "source": accounts[0], "mint": accounts[1], "destination": accounts[2],
                "authority": accounts[3],
                "tokenAmount": {"amount": str(int.from_bytes(data[1:9], "little")), "decimals": data[9]},
            }}
        if tag == 9 and len(accounts) >= 2:
            return {"type": "closeAccount", "info": {
                "account": accounts[0], "destination": accounts[1],
                "owner": accounts[2] if len(accounts) > 2 else None,
            }}
        if tag == 17:
            return {"type": "syncNative", "info": {"account": accounts[0] if accounts else None}}
        if tag in (1, 16, 18):
            return {"type": "initializeAccount3", "info": {"account": accounts[0] if accounts else None}}
    return None


def _plain_explained(raw, address, keys, actual):
    """Explain wallet deltas from System/Token/ATA/ComputeBudget/Memo only.

    Returns (explained_native, explained_tokens) or None when an instruction
    cannot be parsed or a non-plain program is present.
    """
    owned, _decimals = _wallet_owned_accounts(raw, address, keys)
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_native = meta.get("preBalances") or []
    wsol_pre = {}
    for row in meta.get("preTokenBalances") or []:
        if not isinstance(row, dict) or row.get("owner") != address or row.get("mint") != WSOL:
            continue
        index = row.get("accountIndex")
        qty = _int_amount((row.get("uiTokenAmount") or {}).get("amount"))
        if isinstance(index, int) and 0 <= index < len(keys) and qty is not None:
            wsol_pre[keys[index]] = qty
    for row in meta.get("postTokenBalances") or []:
        if not isinstance(row, dict) or row.get("owner") != address or row.get("mint") != WSOL:
            continue
        index = row.get("accountIndex")
        if isinstance(index, int) and 0 <= index < len(keys):
            owned[keys[index]] = WSOL
    running = {}
    for idx, amount in enumerate(pre_native):
        if idx < len(keys):
            try:
                running[keys[idx]] = int(amount)
            except (TypeError, ValueError):
                return None
    explained_native = 0
    explained_tokens = defaultdict(int)
    for _role, _index, instruction in _iter_instructions(raw):
        program = _program_of(instruction, keys)
        if not program:
            return None
        if program not in PLAIN_PROGRAMS:
            return None
        if program in {COMPUTE_ID, LIGHTHOUSE, *MEMO_IDS}:
            continue
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        if not parsed or not parsed.get("type"):
            parsed = _hydrate_plain_instruction(instruction, keys) or parsed
        kind = parsed.get("type") if parsed else None
        info = parsed.get("info") if parsed and isinstance(parsed.get("info"), dict) else {}
        if program == ASSOCIATED_ID:
            if kind not in ("create", "createIdempotent", None):
                return None
            continue
        if program == SYSTEM_ID:
            if kind == "transfer":
                lamports = _int_amount(info.get("lamports"))
                if lamports is None:
                    return None
                source, dest = info.get("source"), info.get("destination")
                if source == address:
                    explained_native -= lamports
                if dest == address:
                    explained_native += lamports
                if dest and owned.get(dest) == WSOL:
                    explained_tokens[WSOL] += lamports
                if source in running:
                    running[source] -= lamports
                if dest:
                    running[dest] = running.get(dest, 0) + lamports
                continue
            if kind in ("createAccount", "createAccountWithSeed"):
                lamports = _int_amount(info.get("lamports"))
                if lamports is None:
                    return None
                source = info.get("source")
                new_account = info.get("newAccount")
                if source == address:
                    explained_native -= lamports
                if source in running:
                    running[source] -= lamports
                if new_account:
                    running[new_account] = running.get(new_account, 0) + lamports
                continue
            if kind in ("allocate", "assign", "advanceNonce", "allocateWithSeed", "assignWithSeed"):
                continue
            if kind is None:
                return None
            return None
        if program in TOKEN_IDS:
            if kind in ("initializeAccount", "initializeAccount2", "initializeAccount3",
                        "getAccountDataSize", "initializeImmutableOwner"):
                continue
            if kind == "syncNative":
                continue
            if kind == "closeAccount":
                account = info.get("account")
                dest = info.get("destination")
                refund = running.get(account)
                if refund is None and account in keys:
                    acc_idx = keys.index(account)
                    if acc_idx < len(pre_native):
                        try:
                            refund = int(pre_native[acc_idx])
                        except (TypeError, ValueError):
                            return None
                if dest == address and refund is not None:
                    explained_native += refund
                if account in wsol_pre:
                    explained_tokens[WSOL] -= wsol_pre[account]
                if account in running:
                    running[account] = 0
                continue
            if kind in ("transfer", "transferChecked", "transferCheckedWithFee"):
                checked = info.get("tokenAmount") if kind in ("transferChecked", "transferCheckedWithFee") else None
                qty = _int_amount((checked or {}).get("amount") if checked else info.get("amount"))
                mint = info.get("mint") or owned.get(info.get("source")) or owned.get(info.get("destination"))
                if qty is None or not mint:
                    return None
                source, dest = info.get("source"), info.get("destination")
                if dest and dest not in owned:
                    for row in meta.get("postTokenBalances") or []:
                        if not isinstance(row, dict):
                            continue
                        index = row.get("accountIndex")
                        if isinstance(index, int) and 0 <= index < len(keys) and keys[index] == dest:
                            if row.get("owner") == address:
                                owned[dest] = row.get("mint") or mint
                                mint = mint or row.get("mint")
                            break
                if source in owned:
                    explained_tokens[mint] -= qty
                if dest in owned:
                    explained_tokens[mint] += qty
                continue
            if kind in ("mintTo", "mintToChecked"):
                checked = info.get("tokenAmount") if kind == "mintToChecked" else None
                qty = _int_amount((checked or {}).get("amount") if checked else info.get("amount"))
                dest = info.get("account") or info.get("destination")
                mint = info.get("mint") or owned.get(dest)
                if qty is None or not mint:
                    return None
                if dest in owned or any(
                    isinstance(row, dict) and row.get("owner") == address and row.get("mint") == mint
                    and isinstance(row.get("accountIndex"), int)
                    and 0 <= row["accountIndex"] < len(keys)
                    and keys[row["accountIndex"]] == dest
                    for row in (meta.get("postTokenBalances") or [])
                ):
                    explained_tokens[mint] += qty
                continue
            if kind in ("burn", "burnChecked"):
                checked = info.get("tokenAmount") if kind == "burnChecked" else None
                qty = _int_amount((checked or {}).get("amount") if checked else info.get("amount"))
                account = info.get("account")
                mint = info.get("mint") or owned.get(account)
                if qty is None or not mint:
                    return None
                if account in owned:
                    explained_tokens[mint] -= qty
                continue
            if kind in ("setAuthority", "approve", "approveChecked", "revoke"):
                continue
            return None
    # Wrap / unwrap: leftover native opposite leftover WSOL is explained.
    leftover_native = actual["native"] - explained_native
    leftover_wsol = actual["tokens"].get(WSOL, 0) - explained_tokens.get(WSOL, 0)
    if leftover_native + leftover_wsol == 0:
        explained_native += leftover_native
        if leftover_wsol:
            explained_tokens[WSOL] += leftover_wsol
    return explained_native, dict(explained_tokens)


def _deltas_match(actual, explained_native, explained_tokens):
    if actual["native"] != explained_native:
        return False
    actual_tokens = {mint: qty for mint, qty in actual["tokens"].items() if qty}
    explained = {mint: qty for mint, qty in explained_tokens.items() if qty}
    return actual_tokens == explained


def _classify_token_effects(actual, *, program=None, instruction=None, reason=""):
    tokens = {mint: qty for mint, qty in actual["tokens"].items() if qty and mint != WSOL}
    fields_base, sol = _sol_fields(actual["native"], actual.get("decimals") or {}, actual["tokens"])
    non_quote = {mint: qty for mint, qty in tokens.items() if mint not in QUOTE_MINTS}
    quote_tokens = {mint: qty for mint, qty in tokens.items() if mint in QUOTE_MINTS}
    events = []
    if not non_quote:
        extra = dict(fields_base)
        extra.update({
            "classification": "unknown",
            "source": program,
            "venue": program,
            "instruction": instruction,
            "never_a_trade": True,
            "reason": reason or "Plain SOL/ATA/quote movement; no lot effect",
        })
        events.append(_event("non_trade", **extra))
        return events
    for mint, qty in sorted(non_quote.items()):
        dec = (actual.get("decimals") or {}).get(mint, 0)
        common = {
            "mint": mint,
            "quantity_raw": str(abs(qty)),
            "decimals": dec,
            "classification": "unknown",
            "source": program,
            "venue": program,
            "instruction": instruction,
            **fields_base,
        }
        if qty > 0:
            common.update({
                "unknown_basis": True,
                "never_lowers_cost": True,
                "basis_sol": None,
                "reason": reason or "Token transfer-in creates an unknown-basis lot; never lowers cost (DC-9)",
            })
            events.append(_event("transfer_in", **common))
        else:
            common.update({
                "unknown_proceeds": True,
                "never_zero_proceeds": True,
                "never_completed_profitable_episode": True,
                "unknown_quote": True,
                "reason": reason or (
                    "Token transfer-out is a disposal with unknown proceeds; "
                    "never zero-proceeds and never a completed profitable episode"
                ),
            })
            events.append(_event("transfer_out", **common))
    del quote_tokens
    return events


def classify_plain_tx(raw, address):
    """C1: System/Token/ATA/ComputeBudget/Memo only, exact reconcile."""
    if not isinstance(raw, dict) or not address:
        return None
    from scanner.mass_search.fail_closed_preflight import fail_closed_reason
    if fail_closed_reason(raw, address, trade=False):
        return None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return None
    keys = _account_keys(raw)
    if address not in keys:
        return None
    programs = set(_programs_present(raw, keys))
    if not programs or programs - PLAIN_PROGRAMS:
        return None
    if _sponsored_token_account_rent(raw, address, keys):
        return None
    actual = _wallet_actual_deltas(raw, address, keys)
    if actual is None:
        return None
    explained = _plain_explained(raw, address, keys, actual)
    if explained is None:
        return None
    explained_native, explained_tokens = explained
    if not _deltas_match(actual, explained_native, explained_tokens):
        return None
    return _classify_token_effects(
        actual,
        reason="Plain System/Token/ATA/ComputeBudget/Memo; deltas reconcile exactly",
    )


def _outer_programs(raw, keys):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    found = []
    for instruction in message.get("instructions") or []:
        if isinstance(instruction, dict):
            program = _program_of(instruction, keys)
            if program:
                found.append(program)
    return found


def _instruction_has_nonce(instruction, keys):
    program = _program_of(instruction, keys)
    parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
    kind = parsed.get("type") if parsed else None
    if program == SYSTEM_ID and kind in ("advanceNonce", "advanceNonceAccount"):
        return True
    data = _b58decode(instruction.get("data"))
    if program == SYSTEM_ID and len(data) >= 4 and int.from_bytes(data[:4], "little") == 4:
        return True
    return False


def _instruction_allocate_assign(instruction, keys):
    program = _program_of(instruction, keys)
    parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
    kind = parsed.get("type") if parsed else None
    if program == SYSTEM_ID and kind in ("allocate", "assign", "allocateWithSeed", "assignWithSeed"):
        return True
    data = _b58decode(instruction.get("data"))
    if program == SYSTEM_ID and len(data) >= 4 and int.from_bytes(data[:4], "little") in (1, 8):
        return True
    return False


def _mixed_parsed_opaque(instruction):
    parsed = instruction.get("parsed")
    if not isinstance(parsed, dict):
        return False
    # Empty accounts on an already-parsed ix is the compiled-report conflict.
    # Live RPC often carries parsed+data together; that is not a conflict.
    return instruction.get("accounts") == []


def _transfer_identity_mismatch(raw, keys):
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    by_account = {}
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if not isinstance(row, dict):
                continue
            index = row.get("accountIndex")
            if not isinstance(index, int) or not (0 <= index < len(keys)):
                continue
            mint = row.get("mint")
            dec = (row.get("uiTokenAmount") or {}).get("decimals")
            if mint:
                by_account[keys[index]] = (mint, dec)
    for _role, _index, instruction in _iter_instructions(raw):
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        if not parsed:
            continue
        kind = parsed.get("type")
        info = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
        if kind not in ("transfer", "transferChecked", "transferCheckedWithFee"):
            continue
        mint = info.get("mint")
        dec = (info.get("tokenAmount") or {}).get("decimals") if isinstance(info.get("tokenAmount"), dict) else None
        for field in ("source", "destination"):
            account = info.get(field)
            identity = by_account.get(account)
            if not identity:
                continue
            if mint and identity[0] and mint != identity[0]:
                return True
            if dec is not None and identity[1] is not None and dec != identity[1]:
                return True
    return False


def _sponsored_token_account_rent(raw, address, keys):
    """Wallet-owned token-account lamports rose with no matching funding ix."""
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
    for _role, _index, instruction in _iter_instructions(raw):
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        info = parsed.get("info") if parsed and isinstance(parsed.get("info"), dict) else {}
        kind = parsed.get("type") if parsed else None
        program = _program_of(instruction, keys)
        dest = info.get("destination") or info.get("newAccount") or info.get("account")
        if program == SYSTEM_ID and kind in ("transfer", "createAccount", "createAccountWithSeed"):
            if dest in keys and info.get("source") == address:
                funded.add(keys.index(dest))
        if program == ASSOCIATED_ID:
            account = info.get("account")
            source = info.get("source") or info.get("wallet")
            if account in keys and source == address:
                funded.add(keys.index(account))
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


def _c2_fail_closed_preconditions(raw, address, keys):
    """Shared preflight plus C2-only nonce / unknown-outer."""
    if not keys or not address:
        return True
    from scanner.mass_search.fail_closed_preflight import fail_closed_reason
    if fail_closed_reason(raw, address, trade=False):
        return True
    for program in _outer_programs(raw, keys):
        if program not in REVIEWED_OUTER_PROGRAMS:
            return True
    for _role, _index, instruction in _iter_instructions(raw):
        if _instruction_has_nonce(instruction, keys):
            return True
    return False


def _owned_account_set(raw, address, keys):
    owned = {address}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(field) or []:
            if not isinstance(row, dict) or row.get("owner") != address:
                continue
            index = row.get("accountIndex")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
                owned.add(keys[index])
    return owned


def _edge_trade_dirty(raw, address, keys, actual):
    """Refuse C2 trades that look 2-leg but include third-party credits or CPI mismatch.

    Wallet-edge 2-leg alone would lower cost (DC-9) when someone else pays SOL
    or adds inventory. Unknown stays unreadable.
    """
    try:
        if _third_party_pool_leg(raw, address, keys):
            return True
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return True
    owned = _owned_account_set(raw, address, keys)
    for _role, _index, instruction in _iter_instructions(raw):
        program = _program_of(instruction, keys)
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        kind = parsed.get("type") if parsed else None
        info = parsed.get("info") if parsed and isinstance(parsed.get("info"), dict) else {}
        if program == SYSTEM_ID and kind == "transfer":
            dest = info.get("destination")
            source = info.get("source")
            if dest in owned and source not in owned:
                return True
        if program in TOKEN_IDS and kind == "closeAccount":
            dest = info.get("destination")
            owner = info.get("owner")
            account = info.get("account")
            if dest in owned and owner not in (None, "", address):
                return True
            if dest in owned and account and account not in owned:
                return True
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    inners = meta.get("innerInstructions")
    if not isinstance(inners, list) or not inners:
        return True
    assets = {mint: qty for mint, qty in actual["tokens"].items() if qty}
    assets["SOL"] = actual["native"] + actual["tokens"].get(WSOL, 0)
    try:
        if _route_flow_disagrees_with_wallet(raw, address, keys, assets):
            return True
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return True
    return False


def _two_leg_or_conversion(actual, *, program, instruction, reason):
    tokens = {mint: qty for mint, qty in actual["tokens"].items() if qty}
    wsol = tokens.pop(WSOL, 0)
    sol = actual["native"] + wsol
    if abs(sol) <= SOL_DUST_LAMPORTS:
        sol = 0
    non_quote = {mint: qty for mint, qty in tokens.items() if mint not in QUOTE_MINTS}
    quotes = {mint: qty for mint, qty in tokens.items() if mint in QUOTE_MINTS}
    if sol:
        quotes["SOL"] = quotes.get("SOL", 0) + sol
    if len(non_quote) == 1 and len(quotes) == 1:
        mint, qty = next(iter(non_quote.items()))
        quote_mint, quote_qty = next(iter(quotes.items()))
        if (qty > 0) == (quote_qty > 0):
            return None
        dec = (actual.get("decimals") or {}).get(mint, 0)
        fields, _sol_amt = _sol_fields(actual["native"], actual.get("decimals") or {}, actual["tokens"])
        if quote_mint == USDC:
            fields["settlement_mint"] = USDC
            fields["settlement_asset"] = "USDC"
        elif quote_mint == USDT:
            fields["settlement_mint"] = USDT
            fields["settlement_asset"] = "USDT"
        else:
            fields["settlement_mint"] = WSOL
            fields["settlement_asset"] = "SOL"
        kind = "buy" if qty > 0 else "sell"
        fields.update({
            "mint": mint,
            "quantity_raw": str(abs(qty)),
            "decimals": dec,
            "classification": "unknown",
            "source": program,
            "venue": program,
            "instruction": instruction,
            "reason": reason,
        })
        return [_event(kind, **fields)]
    if program == RFQ_FILL and len(non_quote) == 2 and not quotes:
        items = list(non_quote.items())
        downs = [(mint, qty) for mint, qty in items if qty < 0]
        ups = [(mint, qty) for mint, qty in items if qty > 0]
        if len(downs) != 1 or len(ups) != 1:
            return None
        from_mint, from_qty = downs[0]
        to_mint, to_qty = ups[0]
        dec = (actual.get("decimals") or {}).get(from_mint, 0)
        fields, _sol_amt = _sol_fields(actual["native"], actual.get("decimals") or {}, actual["tokens"])
        fields.update({
            "mint": from_mint,
            "quantity_raw": str(abs(from_qty)),
            "decimals": dec,
            "classification": "conversion",
            "from_asset": from_mint,
            "to_asset": to_mint,
            "source": program,
            "venue": program,
            "instruction": instruction,
            "reason": reason or "Wallet-edge token↔token conversion; exact opposing non-quote deltas",
        })
        return [_event("conversion", **fields)]
    if len(non_quote) == 1 and not quotes:
        # Token-only movement on a venue is not a 2-leg trade.
        return None
    return None


def _accepted_edge_trade(raw, address, keys, actual, classified):
    if not classified:
        return None
    if any(item.get("kind") in TRADE_KINDS for item in classified):
        from scanner.mass_search.fail_closed_preflight import fail_closed_reason
        if fail_closed_reason(raw, address, trade=True):
            return None
        if _c2_fail_closed_preconditions(raw, address, keys):
            return None
        if _edge_trade_dirty(raw, address, keys, actual):
            return None
    return classified


def classify_edge_tx(raw, address):
    """C2: wallet-edge reconcile for named programs. Unknown stays unreadable."""
    if not isinstance(raw, dict) or not address:
        return None
    from scanner.mass_search.fail_closed_preflight import fail_closed_reason
    if fail_closed_reason(raw, address, trade=False):
        return None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return None
    keys = _account_keys(raw)
    if address not in keys:
        return None
    if _c2_fail_closed_preconditions(raw, address, keys):
        return None
    programs = set(_programs_present(raw, keys))
    actual = _wallet_actual_deltas(raw, address, keys)
    if actual is None:
        return None
    tokens = {mint: qty for mint, qty in actual["tokens"].items() if qty and mint != WSOL}
    wsol = actual["tokens"].get(WSOL, 0)
    sol = actual["native"] + wsol
    zero_token = not tokens

    outer_programs = {
        _program_of(instruction, keys)
        for instruction in (((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}).get("instructions") or []
        if isinstance(instruction, dict)
    }
    if METEORA_DLMM in outer_programs:
        non_quote = [mint for mint, qty in tokens.items() if mint not in QUOTE_MINTS]
        mint = non_quote[0] if non_quote else None
        fields, _sol_amt = _sol_fields(actual["native"], actual.get("decimals") or {}, actual["tokens"])
        fields.update({
            "mint": mint,
            "quantity_raw": str(abs(tokens[mint])) if mint else "0",
            "classification": "lp",
            "source": METEORA_DLMM,
            "venue": METEORA_DLMM,
            "instruction": "lp",
            "lp_action": True,
            "never_a_trade": True,
            "touches_result_relevant_mint": bool(non_quote),
            "reason": (
                "Meteora DLMM is an LP action, never a trade; "
                "existing LP blocking applies if a result-relevant mint moved"
            ),
        })
        return [_event("lp", **fields)]

    if G2G_SPAM in outer_programs:
        if not zero_token or abs(sol) > G2G_MAX_NATIVE_LAMPORTS:
            return None
        return _classify_token_effects(
            actual, program=G2G_SPAM, instruction="afaf6d1f0d989bed",
            reason="G2GMMDK outer zero-token spam within cap; non-trade",
        )

    if JITO_TIP_ROUTER in outer_programs:
        if not zero_token or abs(sol) > JITO_MAX_NATIVE_LAMPORTS:
            return None
        return _classify_token_effects(
            actual, program=JITO_TIP_ROUTER, instruction="claim",
            reason="Jito Tip Router outer claim within cap; non-trade",
        )

    if OKX_VAULT in outer_programs:
        if not zero_token or abs(sol) > JITO_MAX_NATIVE_LAMPORTS:
            return None
        return _classify_token_effects(
            actual, program=OKX_VAULT, instruction="custody",
            reason="OKX Vault outer SOL-only custody within cap; non-trade",
        )

    if PUMP in programs:
        discs = _outer_discs(raw, keys, PUMP)
        if PUMP_DISTRIBUTE_DISC in discs:
            quote_out = any(qty < 0 and mint in QUOTE_MINTS for mint, qty in tokens.items())
            if quote_out:
                classified = _two_leg_or_conversion(
                    actual, program=PUMP, instruction="623691610246ad2b",
                    reason="Pump disc 62369161 with quote out is a priced buy or unreadable, never transfer-in",
                )
                return _accepted_edge_trade(raw, address, keys, actual, classified)
            if abs(sol) > SOL_DUST_LAMPORTS:
                return None
            outs = [mint for mint, qty in tokens.items() if qty < 0 and mint not in QUOTE_MINTS]
            if outs:
                return None
            return _classify_token_effects(
                actual, program=PUMP, instruction="623691610246ad2b",
                reason="Pump disc 62369161 is a zero-SOL distribution; transfer-in, not a trade",
            )
        if discs.count(PUMP_BUY_DISC) >= 1:
            classified = _two_leg_or_conversion(
                actual, program=PUMP, instruction="66063d1201daebea",
                reason="Pump.fun wallet-edge (including multi-buy in one tx); exact 2-leg",
            )
            return _accepted_edge_trade(raw, address, keys, actual, classified)

    if DFLOW in programs:
        discs = _outer_discs(raw, keys, DFLOW)
        if DFLOW_ORDER_SETUP_DISC in discs and DFLOW_SWAP_DISC not in discs:
            classified = _two_leg_or_conversion(
                actual, program=DFLOW, instruction="414b3f4ceb5b5b88",
                reason="DFlow 414b3f4c wallet-edge swap",
            )
            accepted = _accepted_edge_trade(raw, address, keys, actual, classified)
            if accepted:
                return accepted
            if zero_token or not any(qty and mint not in QUOTE_MINTS for mint, qty in tokens.items()):
                return _classify_token_effects(
                    actual, program=DFLOW, instruction="414b3f4ceb5b5b88",
                    reason="DFlow 414b3f4c order-setup; non-trade when no opposing trade legs",
                )
            return None
        if DFLOW_SWAP_DISC not in discs:
            return None
        classified = _two_leg_or_conversion(
            actual, program=DFLOW, instruction="f8c69e91e17587c8",
            reason="DFlow wallet-edge swap; exact 2-leg",
        )
        return _accepted_edge_trade(raw, address, keys, actual, classified)

    for program, allowed, label in (
        (OKX_DEX_ROUTER, OKX_EDGE_DISCS, "OKX DEX router wallet-edge; exact 2-leg"),
        (JUPITER, JUPITER_EDGE_DISCS, "Jupiter v6 wallet-edge including fee ATAs; exact 2-leg"),
        (RFQ_FILL, RFQ_EDGE_DISCS, "Jupiter Ultra RFQ Fill wallet-edge; conversion or 2-leg"),
        (PUMP_SWAP, PUMPSWAP_EDGE_DISCS, "PumpSwap AMM wallet-edge; exact 2-leg"),
    ):
        if program not in programs:
            continue
        discs = _outer_discs(raw, keys, program)
        if not any(disc in allowed for disc in discs):
            return None
        classified = _two_leg_or_conversion(
            actual, program=program, instruction="wallet_edge", reason=label,
        )
        if program == RFQ_FILL and classified and classified[0].get("kind") != "conversion":
            return None
        return _accepted_edge_trade(raw, address, keys, actual, classified)
    return None


def classify_read_tx(raw, address):
    """Return READ/trade events, or None when the tx stays unreadable."""
    edge = classify_edge_tx(raw, address)
    if edge:
        return edge
    return classify_plain_tx(raw, address)
