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
PUMP_DISTRIBUTE_DISC = bytes.fromhex("623691610246ad2b")
PUMP_BUY_DISC = bytes.fromhex("66063d1201daebea")
DFLOW_ORDER_SETUP_DISC = bytes.fromhex("414b3f4ceb5b5b88")
DFLOW_SWAP_DISC = bytes.fromhex("f8c69e91e17587c8")
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


def _plain_explained(raw, address, keys, actual):
    """Explain wallet deltas from System/Token/ATA/ComputeBudget/Memo only.

    Returns (explained_native, explained_tokens) or None when an instruction
    cannot be parsed or a non-plain program is present.
    """
    owned, _decimals = _wallet_owned_accounts(raw, address, keys)
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_native = meta.get("preBalances") or []
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
            "classification": "read_non_trade",
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
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return None
    keys = _account_keys(raw)
    if address not in keys:
        return None
    programs = set(_programs_present(raw, keys))
    if not programs or programs - PLAIN_PROGRAMS:
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
            "classification": "market",
            "source": program,
            "venue": program,
            "instruction": instruction,
            "reason": reason,
        })
        return [_event(kind, **fields)]
    if len(non_quote) == 2 and not quotes:
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


def classify_edge_tx(raw, address):
    """C2: wallet-edge reconcile for named programs. Unknown stays unreadable."""
    if not isinstance(raw, dict) or not address:
        return None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return None
    keys = _account_keys(raw)
    if address not in keys:
        return None
    programs = set(_programs_present(raw, keys))
    actual = _wallet_actual_deltas(raw, address, keys)
    if actual is None:
        return None
    tokens = {mint: qty for mint, qty in actual["tokens"].items() if qty and mint != WSOL}
    wsol = actual["tokens"].get(WSOL, 0)
    sol = actual["native"] + wsol
    zero_token = not tokens

    if METEORA_DLMM in programs:
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

    if G2G_SPAM in programs:
        if not zero_token:
            return None
        return _classify_token_effects(
            actual, program=G2G_SPAM, instruction="afaf6d1f0d989bed",
            reason="G2GMMDK zero-token (or SOL-only) verified; non-trade",
        )

    if JITO_TIP_ROUTER in programs:
        if not zero_token:
            return None
        return _classify_token_effects(
            actual, program=JITO_TIP_ROUTER, instruction="claim",
            reason="Jito Tip Router claim; zero token delta verified; non-trade",
        )

    if OKX_VAULT in programs:
        if zero_token:
            return _classify_token_effects(
                actual, program=OKX_VAULT, instruction="custody",
                reason="OKX Vault SOL-only custody move; non-trade",
            )
        return _classify_token_effects(
            actual, program=OKX_VAULT, instruction="custody",
            reason="OKX Vault with token deltas uses transfer semantics",
        )

    if PUMP in programs:
        discs = _outer_discs(raw, keys, PUMP)
        if PUMP_DISTRIBUTE_DISC in discs:
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
            if classified:
                return classified
            return None

    if DFLOW in programs:
        discs = _outer_discs(raw, keys, DFLOW)
        if DFLOW_ORDER_SETUP_DISC in discs and DFLOW_SWAP_DISC not in discs:
            classified = _two_leg_or_conversion(
                actual, program=DFLOW, instruction="414b3f4ceb5b5b88",
                reason="DFlow 414b3f4c wallet-edge swap",
            )
            if classified:
                return classified
            if zero_token or not any(qty and mint not in QUOTE_MINTS for mint, qty in tokens.items()):
                return _classify_token_effects(
                    actual, program=DFLOW, instruction="414b3f4ceb5b5b88",
                    reason="DFlow 414b3f4c order-setup; non-trade when no opposing trade legs",
                )
            return None
        classified = _two_leg_or_conversion(
            actual, program=DFLOW, instruction="f8c69e91e17587c8",
            reason="DFlow wallet-edge swap; exact 2-leg",
        )
        if classified:
            return classified
        return None

    for program, label in (
        (OKX_DEX_ROUTER, "OKX DEX router wallet-edge; exact 2-leg"),
        (JUPITER, "Jupiter v6 wallet-edge including fee ATAs; exact 2-leg"),
        (RFQ_FILL, "Jupiter Ultra RFQ Fill wallet-edge; conversion or 2-leg"),
        (PUMP_SWAP, "PumpSwap AMM wallet-edge; exact 2-leg"),
    ):
        if program not in programs:
            continue
        classified = _two_leg_or_conversion(
            actual, program=program, instruction="wallet_edge", reason=label,
        )
        if classified:
            return classified
        return None
    return None


def classify_read_tx(raw, address):
    """Return READ/trade events, or None when the tx stays unreadable."""
    edge = classify_edge_tx(raw, address)
    if edge:
        return edge
    return classify_plain_tx(raw, address)
