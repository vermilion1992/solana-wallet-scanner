#!/usr/bin/env python3
"""Decoder-independent audit of captured research-search B episodes.

Reconstructs qualifying episodes from raw instructions, balances, ownership
and pinned protocol interfaces. Imports no scanner/ code. JSON parsing is
the only shared library used with the application.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/CAPTURE_MANIFEST.json"
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/INDEPENDENT_AUDIT.json"

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTE_MINTS = frozenset({USDC, USDT})
QUOTE_ASSET = {USDC: "USDC", USDT: "USDT"}
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
METEORA_DAMM_V2 = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"
RFQ_FILL = "61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH"
OKX = "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u"
DFLOW = "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH"
FLASHX = "FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9"
DGMG = "DGMgNKpqygARV2pHZfW4kNQSHT9F3Ly2BKWqvpYrAg5C"
PHOTON = "99vQwtBwYtrqqD9YSXbdum3KBdxPAVxYTaQ3cfnJSrN2"
DFLOW_DST = "dst5MGcFPoBeREFAA5E3tU5ij8m5uVYwkzkSAbsLbNo"
PUMP_FEE = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
RAYDIUM_CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
RAYDIUM_AMM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
WHIRLPOOL = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
GMGN = "GMGNreQcJFufBiCTLDBgKhYEfEe9B454UjpDr5CaSLA1"
METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
ASSOCIATED = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
COMPUTE = "ComputeBudget111111111111111111111111111111"
LIGHTHOUSE = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"
SYSTEM = "11111111111111111111111111111111"
LAMPORTS = Decimal(1_000_000_000)
USDC_DECIMALS = Decimal(10) ** 6
REPORT_START = datetime.fromisoformat("2026-09-05T13:29:27+00:00").timestamp()
REPORT_END = datetime.fromisoformat("2026-10-05T13:29:27+00:00").timestamp()
ACQUISITION = datetime.fromisoformat("2026-07-07T13:29:27+00:00").timestamp()

# Bot-rule definition (must match scanner.mass_search.qualification_gates):
# every economic swap is a trade, including token-to-token; dedupe
# (signature, kind, mint); route-leg hops are not trades, so a multi-hop
# route in one tx is one trade, not one per hop.
BOT_RULE_DEFINITION = (
    "economic_swap_including_token_to_token; "
    "dedupe=(signature,kind,mint); "
    "route_legs_are_not_trades; "
    "multi_hop_same_tx_counts_once_per_mint_kind"
)

# Pinned published discriminators (Pump IDL / Jupiter parser / Meteora swap / RFQ Fill).
# Meteora swap = sha256("global:swap")[:8]; RFQ Fill is the published 8-byte disc.
PINNED = {
    (PUMP, "33e685a4017f83ad"): ("buy", 6, (5,)),
    (PUMP, "66063d1201daebea"): ("sell", 6, (5,)),
    (PUMP, "5df6823ce7e940b2"): ("sell_v2", 13, (14,)),
    (PUMP, "c2ab1c46684d5b2f"): ("buy_exact_quote_in_v2", 13, (14,)),
    (PUMP, "b817ee6167c5d33d"): ("buy_v2", 13, (14,)),
    (PUMP_SWAP, "66063d1201daebea"): ("sell", 1, (5, 6)),
    (PUMP_SWAP, "33e685a4017f83ad"): ("buy", 1, (5, 6)),
    (PUMP_SWAP, "c62e1552b4d9e870"): ("buy_exact_quote_in", 1, (5, 6)),
    (JUPITER, "bb64facc31c4af14"): ("route_v2", 0, (1, 2)),
    (JUPITER, "d19853937cfed8e9"): ("shared_accounts_route_v2", 1, (2, 5)),
    (METEORA_DAMM_V2, "f8c69e91e17587c8"): ("swap", 8, (2, 3)),
    (RFQ_FILL, "a860b7a35c0a28a0"): ("Fill", 0, (4,)),
    # Independent OKX DEX v2 SwapTob. Layout taken from the published OKX
    # router accounts (payer 0, source token 1, dest token 2). Written here
    # without importing scanner.investigation.
    (OKX, "aa2955b184501f35"): ("SwapTob", 0, (1, 2)),
    # Independent DFlow Aggregator v4. Wallet at 3 on Swap / Swap2
    # (DKx vYeWFHJd; run-7 4rZp4CN3). Wrap 2f3e9bac, Unwrap 63280e69,
    # TransferFee 81a4c415 and TransferToSponsor 9bb38297 are not swaps.
    (DFLOW, "f8c69e91e17587c8"): ("swap", 3, ()),
    (DFLOW, "a8ac184dc59c8765"): ("swap_with_destination", 3, (4,)),
    (DFLOW, "414b3f4ceb5b5b88"): ("swap2", 3, ()),
    # Independent DGMg PumpSwap router. Same buy/sell discs as Pump; user at 1.
    (DGMG, "66063d1201daebea"): ("buy", 1, (5, 6)),
    (DGMG, "33e685a4017f83ad"): ("sell", 1, (5, 6)),
    (DGMG, "c62e1552b4d9e870"): ("buy_exact_quote_in", 1, (5, 6)),
}
AUDITOR_TIP_LIST = Path(__file__).with_name("published_tip_accounts.json")


def _published_tips():
    """Load the auditor-owned tip list. Fail loudly if the file is missing.

    This copy lives next to the auditor, outside scanner/. A missing file must
    not silently become an empty tip set — that changes episode nets.
    """
    if not AUDITOR_TIP_LIST.is_file():
        raise FileNotFoundError(
            f"Auditor published tip list missing: {AUDITOR_TIP_LIST}. "
            "An empty tip set would change episode nets; refusing to continue."
        )
    payload = json.loads(AUDITOR_TIP_LIST.read_text(encoding="utf-8"))
    accounts = set()
    for body in (payload.get("providers") or {}).values():
        accounts.update(body.get("accounts") or [])
        accounts.update(body.get("programs") or [])
    if not accounts:
        raise ValueError(f"Auditor published tip list is empty: {AUDITOR_TIP_LIST}")
    return accounts


PUBLISHED_TIPS = _published_tips()
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


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
    if not isinstance(value, str):
        return b""
    number = 0
    for char in value:
        if char not in B58:
            return b""
        number = number * 58 + B58.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + body


def _keys(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    meta = raw.get("meta") or {}
    entries = message.get("accountKeys") or []
    keys = [item.get("pubkey") if isinstance(item, dict) else item for item in entries]
    loaded = meta.get("loadedAddresses") or {}
    if all(isinstance(item, str) for item in entries) or (entries and isinstance(entries[0], dict) and "pubkey" in (entries[0] or {})):
        keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    return [key for key in keys if isinstance(key, str)]


def _program(instruction, keys):
    program = instruction.get("programId")
    if isinstance(program, str):
        return program
    index = instruction.get("programIdIndex")
    if isinstance(index, int) and 0 <= index < len(keys):
        return keys[index]
    return None


def _accounts(instruction, keys):
    accounts = instruction.get("accounts") or []
    resolved = []
    for item in accounts:
        if isinstance(item, int) and 0 <= item < len(keys):
            resolved.append(keys[item])
        elif isinstance(item, str):
            resolved.append(item)
    return resolved


def _owned_token_deltas(raw, address):
    meta = raw.get("meta") or {}
    deltas = defaultdict(lambda: Decimal("0"))
    pre = {}
    post = {}
    for field, dest in (("preTokenBalances", pre), ("postTokenBalances", post)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get("owner") != address:
                continue
            mint = balance.get("mint")
            amount = (balance.get("uiTokenAmount") or {}).get("amount")
            if mint and amount not in (None, ""):
                dest[mint] = dest.get(mint, Decimal("0")) + Decimal(str(amount))
    mints = set(pre) | set(post)
    for mint in mints:
        deltas[mint] = post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0"))
    return dict(deltas), pre, post


def _native_delta(raw, address, keys):
    meta = raw.get("meta") or {}
    try:
        index = keys.index(address)
    except ValueError:
        return Decimal("0"), False
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return Decimal("0"), False
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
    paid = keys[0] == address if keys else False
    delta = Decimal(post[index] - pre[index])
    if paid:
        delta += Decimal(fee)
    return delta, paid


def _iter_instructions(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    meta = raw.get("meta") or {}
    for index, instruction in enumerate(message.get("instructions") or []):
        if isinstance(instruction, dict):
            yield index, f"transaction.message.instructions.{index}", instruction, False
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        outer = group.get("index")
        for index, instruction in enumerate(group.get("instructions") or []):
            if isinstance(instruction, dict):
                yield outer, f"meta.innerInstructions.{outer}.{index}", instruction, True


def _system_movements(raw, keys):
    movements = []
    for outer, path, instruction, nested in _iter_instructions(raw):
        if _program(instruction, keys) != SYSTEM:
            continue
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        base = {"outer": outer, "nested": nested, "path": path}
        if isinstance(info, dict) and kind == "transfer":
            lamports = info.get("lamports")
            movements.append({
                **base,
                "kind": "transfer",
                "source": info.get("source"),
                "destination": info.get("destination"),
                "lamports": lamports if isinstance(lamports, int) else 0,
            })
            continue
        if isinstance(info, dict) and kind in ("createAccount", "createAccountWithSeed"):
            lamports = info.get("lamports")
            movements.append({
                **base,
                "kind": "create",
                "source": info.get("source"),
                "destination": info.get("newAccount"),
                "lamports": lamports if isinstance(lamports, int) else 0,
            })
            continue
        payload = _b58decode(instruction.get("data"))
        accounts = _accounts(instruction, keys)
        if len(payload) >= 12 and int.from_bytes(payload[:4], "little") == 2:
            movements.append({
                **base,
                "kind": "transfer",
                "source": accounts[0] if accounts else None,
                "destination": accounts[1] if len(accounts) > 1 else None,
                "lamports": int.from_bytes(payload[4:12], "little"),
            })
        elif len(payload) >= 20 and int.from_bytes(payload[:4], "little") == 0:
            movements.append({
                **base,
                "kind": "create",
                "source": accounts[0] if accounts else None,
                "destination": accounts[1] if len(accounts) > 1 else None,
                "lamports": int.from_bytes(payload[4:12], "little"),
            })
    return movements


def _token_accounts(raw, address, keys):
    meta = raw.get("meta") or {}
    accounts = {}
    for field, side in (("preTokenBalances", "pre"), ("postTokenBalances", "post")):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get("owner") != address:
                continue
            index = balance.get("accountIndex")
            if not isinstance(index, int) or index < 0 or index >= len(keys):
                continue
            account = keys[index]
            amount = (balance.get("uiTokenAmount") or {}).get("amount")
            decimals = (balance.get("uiTokenAmount") or {}).get("decimals")
            record = accounts.setdefault(account, {
                "index": index,
                "mint": balance.get("mint"),
                "decimals": decimals,
                "pre": Decimal("0"),
                "post": Decimal("0"),
            })
            if balance.get("mint"):
                record["mint"] = balance.get("mint")
            if decimals is not None:
                record["decimals"] = decimals
            if amount not in (None, ""):
                record[side] = Decimal(str(amount))
    return accounts


def _rent_correction(raw, accounts):
    meta = raw.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    correction = Decimal("0")
    for info in accounts.values():
        index = info["index"]
        if index >= len(pre) or index >= len(post):
            continue
        native = Decimal(post[index] - pre[index])
        token_delta = info["post"] - info["pre"]
        correction += native - token_delta if info.get("mint") == WSOL else native
    return correction


TOKEN_PROGRAMS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}
MEMO_PROGRAMS = {
    "MemoSq4gqABAXKb96QnHLmNbpX6VKFSubuNAgPqAq",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
}
_INNER_INFRA = frozenset({
    SYSTEM, COMPUTE, ASSOCIATED, LIGHTHOUSE, *TOKEN_PROGRAMS, *MEMO_PROGRAMS,
})
WELL_KNOWN_INNER_AMMS = frozenset({
    RAYDIUM_CLMM,
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",
    "SCoRcH8c2dpjvcJD6FiPbCSQyQgu3PcUAWj2Xxx3mqn",
    "ALPHAQmeA7bjrVuccPsYPiCvsi428SNwte66Srvs4pHA",
    "ZERor4xhbUycZ6gb9ntrhqscUcZmAbQDjEAtCf4hbZY",
    "BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi",
    "SoLFiHG9TfgtdUXUjWAxi3LtvYuFyDLVhBWxdMZxyCe",
    "obriQD1zbpyLz95G5n7nJe6a4DPjpFwa5XYPoNm113y",
    "2wT8Yq49kHgDzXuPxZSaeLaH1qJgCwzzjYyvKZlYNVpj",
    "EewxydAPCCVuNEyrVN68XT4NWAI1uCml1p55i1BPVsbJ",
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
    "opnb2LAfJYbRMAHHvqjCwQxanZn7ReEHp1k81EohpZb",
    "FLUXubRmkEi2q6K3Y9kBPg9248ggaZVsoSFhtJHSrm1X",
    "Eo7WjKq67rjJQSZxS6z3YcapmYde3M6t4gadxJtdEJge",
    "6MLxLqiXaaSUpkgMnWDTuejNZEz3kE7k2woyHGVFw319",
    "HyaB3W9q6XdA5xwpU4XnSZV94htfmbmqJXZcEbRaJueZ",
    "SwaPpA9LAaLfeLi3a68M4DjnLqgKzHa7VMEBUNHzMeU",
    "MERLuDFBMmsHnszOkfP1zZuj7bK1uAmo4BqTKKQs",
    "SSwpkEEcbUqx4vtoEByFjSkhKdCT862DNVb52nZg1UZ",
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
    "BSwp6bEBihVLdqJRK3PkMH2nNzQ4K3CwbGoiJ2mr8BEf",
    "TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH",
    "HpNfyc2Saw7RKkQd8nEL4khUcuPhQ7WwY1B2qjx8jxFq",
    "goonuddtQRrWqqn5nFyczVKaie28f3kDkHWkHtURSLE",
    "3TK9D8aoBFYjYZtKCjciPrVrRStsnvo7KmpcJqDavpaU",
    "MNFSTqtC93rEfYHB6hF82sKdZpUDFWkViLByLd1k1Ms",
    "B72M6nyCLFgWiJtAN4naUTminMiTmyGcEqQHXwVeRdht",
    "DRVSpZ2YUYYKgZP8XtLhAGtT1zYSCKzeHfb4DgRnrgqD",
    "riptK81hDxhe5pW5jSzSM9iRA8azgEgLJ4dXkPtBS7j",
    # Eco SDK svm/venues/obsidian OBSIDIAN_PROGRAM_ID (constant-product AMM).
    "HBVw6bZtcCaezhcBrmfyXBSBRWCdv72271xQ4GPvms2z",
    # Eco SDK svm/venues/gatorswap GATORSWAP_PROGRAM_ID (constant-product AMM).
    "gatorLx9aC1e5ZWAXscv5QRKiLXnLPLXjftVc81h1Hr",
    # Aquifer DEX hop AMM. Decode is wallet-delta, not Aquifer internals.
    "AQU1FRd7papthgdrwPTTq5JacJh8YtwEXaBfKU3bTz45",
})
REVIEWED_INNER_PROGRAMS = frozenset({
    *_INNER_INFRA,
    PUMP, PUMP_SWAP, JUPITER, METEORA_DAMM_V2, RFQ_FILL, OKX, DFLOW, FLASHX,
    DGMG, PHOTON, DFLOW_DST, PUMP_FEE, RAYDIUM_CLMM, RAYDIUM_CPMM, RAYDIUM_AMM,
    WHIRLPOOL, GMGN, METEORA_DLMM, *WELL_KNOWN_INNER_AMMS,
})


def _inner_venues(raw, keys, route, address, owned_accounts):
    venues = []
    seen = set()
    wallet_assets = {address, *owned_accounts}
    route_index = route.get("index")
    for outer, _path, instruction, nested in _iter_instructions(raw):
        if not nested or outer != route_index:
            continue
        program = _program(instruction, keys)
        if not program or program in _INNER_INFRA:
            continue
        if program not in seen:
            seen.add(program)
            venues.append({"program": program})
        if program in REVIEWED_INNER_PROGRAMS:
            continue
        touched = set(_accounts(instruction, keys))
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if isinstance(info, dict):
            for field in ("source", "destination", "account", "newAccount", "owner", "authority", "wallet"):
                value = info.get(field)
                if isinstance(value, str) and value:
                    touched.add(value)
        if touched.intersection(wallet_assets):
            return venues, False
    return venues, True


def _closed_to_wallet(raw, keys, address):
    closed = set()
    for _outer, _path, instruction, _nested in _iter_instructions(raw):
        if _program(instruction, keys) not in TOKEN_PROGRAMS:
            continue
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        if isinstance(info, dict) and kind == "closeAccount" and info.get("destination") == address:
            if info.get("account"):
                closed.add(info["account"])
            continue
        payload = _b58decode(instruction.get("data"))
        accounts = _accounts(instruction, keys)
        if payload[:1] == b"\x09" and len(accounts) >= 2 and accounts[1] == address:
            closed.add(accounts[0])
    return closed


def _outside_native(movements, address, wrap_accounts, route_index=None):
    delta = Decimal("0")
    for movement in movements:
        if movement["kind"] != "transfer":
            continue
        source, dest = movement["source"], movement["destination"]
        if address not in (source, dest) or source == dest:
            continue
        other = dest if source == address else source
        if other in wrap_accounts:
            continue
        # Quote legs live under the swap (same outer index, often as CPIs).
        if route_index is not None and movement.get("outer") == route_index:
            continue
        lamports = Decimal(movement["lamports"] or 0)
        delta += -lamports if source == address else lamports
    return delta


WALLET_PAID_RENT_RULE = (
    "Wallet-paid account rent (owned vs not-owned; closed vs still open). "
    "A System/ATA create funded by the investigated wallet is classified by "
    "the SPL token owner (not the program owner). Closed in this transaction "
    "with rent returned to the wallet nets out (remaining native is 0). "
    "Still-open and token owner == wallet is recoverable ATA/wSOL rent and "
    "is excluded from swap consideration. Still-open and not wallet-owned "
    "(venue PDA, other-owner ATA, router-fee account) stays in consideration. "
    "Unproved owner is treated as not wallet-owned (fail closed: keep in cost). "
    "Same-route is not a reason to keep or drop. PumpSwap IDL user-volume "
    "PDA (buy / buy_exact_quote_in ordinal 20, derived from the user) is "
    "isolated from the swap quote — not recoverable rent and not "
    "consideration. Jupiter-inner PumpSwap creates are not IDL-located on "
    "the outer route and stay in consideration."
)


def _token_account_owner(raw, keys, account):
    """SPL token owner of a created account, or None if unproved.

    Independent of scanner.investigation (no shared helper).
    """
    key_list = list(keys or [])
    for _outer, _path, instruction, _nested in _iter_instructions(raw or {}):
        program = _program(instruction, key_list)
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        if not isinstance(info, dict):
            continue
        if program == ASSOCIATED and kind in ("create", "createIdempotent") and info.get("account") == account:
            owner = info.get("wallet") or info.get("owner")
            if owner:
                return owner
        if (
            program in TOKEN_PROGRAMS
            and kind in ("initializeAccount", "initializeAccount2", "initializeAccount3")
            and info.get("account") == account
            and info.get("owner")
        ):
            return info.get("owner")
    return None


def _pubkey32(value):
    body = _b58decode(value)
    return body if len(body) == 32 else None


def _canonical_user_volume_pda(address):
    """Independent of scanner.investigation. PumpSwap user_volume_accumulator."""
    user = _pubkey32(address)
    program = _pubkey32(PUMP_SWAP)
    if user is None or program is None:
        raise ValueError("User-volume PDA requires exact 32-byte public keys")
    prime = 2**255 - 19
    curve_d = -121665 * pow(121666, prime - 2, prime) % prime
    for bump in range(255, -1, -1):
        candidate = hashlib.sha256(
            b"user_volume_accumulator" + user + bytes([bump]) + program + b"ProgramDerivedAddress"
        ).digest()
        y = (int.from_bytes(candidate, "little") & (2**255 - 1)) % prime
        square = (y * y - 1) * pow(curve_d * y * y + 1, prime - 2, prime) % prime
        on_curve = square == 0 or pow(square, (prime - 1) // 2, prime) == 1
        if not on_curve:
            return candidate, bump
    raise ValueError("User-volume PDA has no supported canonical bump")


def _system_create_details(instruction, keys):
    """Parsed createAccount or raw System opcode 0. Independent of scanner."""
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if isinstance(info, dict) and kind in ("createAccount", "createAccountWithSeed"):
        owner = info.get("owner")
        return {
            "kind": kind,
            "source": info.get("source"),
            "new_account": info.get("newAccount"),
            "owner_bytes": _pubkey32(owner) if isinstance(owner, str) else None,
            "lamports": info.get("lamports") if isinstance(info.get("lamports"), int) else None,
            "space": info.get("space") if isinstance(info.get("space"), int) else None,
        }
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if len(payload) >= 52 and int.from_bytes(payload[:4], "little") == 0 and len(accounts) >= 2:
        return {
            "kind": "createAccount",
            "source": accounts[0],
            "new_account": accounts[1],
            "owner_bytes": payload[20:52],
            "lamports": int.from_bytes(payload[4:12], "little"),
            "space": int.from_bytes(payload[12:20], "little"),
        }
    return None


def _isolated_pumpswap_user_volume(raw, keys, address, route):
    """Isolate IDL-located PumpSwap user-volume from the swap quote.

    Independent of scanner.investigation. Ordinal 20, derived from the user,
    wallet-paid, still open, program-owned. Not recoverable rent; not swap
    consideration. Returns (lamports, ok). ok is False when the create is
    present but disagrees with the pinned IDL location (fail closed).
    """
    if route.get("program") != PUMP_SWAP:
        return Decimal("0"), True
    accounts = route.get("accounts") or []
    if len(accounts) <= 20:
        return Decimal("0"), True
    account = accounts[20]
    creates = []
    for outer, path, instruction, nested in _iter_instructions(raw):
        if _program(instruction, keys) != SYSTEM:
            continue
        details = _system_create_details(instruction, keys)
        if details and details.get("new_account") == account:
            creates.append((outer, path, nested, details))
    if not creates:
        return Decimal("0"), True
    try:
        derived, _bump = _canonical_user_volume_pda(address)
    except ValueError:
        return Decimal("0"), False
    if len(creates) != 1 or _pubkey32(account) != derived or keys.count(account) != 1:
        return Decimal("0"), False
    outer, create_path, nested, details = creates[0]
    if account not in keys:
        return Decimal("0"), False
    index = keys.index(account)
    meta = raw.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    lamports = details.get("lamports")
    space = details.get("space")
    if (
        outer != route.get("index")
        or not nested
        or details.get("kind") != "createAccount"
        or details.get("source") != address
        or details.get("owner_bytes") != _pubkey32(PUMP_SWAP)
        or not isinstance(space, int)
        or not 0 < space <= 2**64 - 1
        or not isinstance(lamports, int)
        or not 0 < lamports <= 2**64 - 1
        or index >= len(pre)
        or index >= len(post)
        or pre[index] != 0
        or post[index] != lamports
        or account in (route.get("owned") or [])
    ):
        return Decimal("0"), False
    for movement in _system_movements(raw, keys):
        if movement.get("path") == create_path:
            continue
        if account in (movement.get("source"), movement.get("destination")):
            return Decimal("0"), False
    return Decimal(lamports), True


def _non_token_creates(movements, address, skip_accounts, raw=None, keys=None, route_index=None):
    """Exclude still-open wallet-owned token-account rent only.

    Independent of scanner.investigation. See WALLET_PAID_RENT_RULE.
    skip_accounts are wallet-owned token accounts already rent-corrected.
    Not-owned still-open funding is left in consideration (do not add back).
    """
    del route_index
    extra = Decimal("0")
    meta = (raw or {}).get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    key_list = list(keys or [])
    for movement in movements:
        if movement["kind"] != "create" or movement.get("source") != address:
            continue
        dest = movement.get("destination")
        if dest in skip_accounts:
            continue
        if _token_account_owner(raw, key_list, dest) != address:
            continue
        if dest in key_list:
            index = key_list.index(dest)
            if index < len(pre) and index < len(post):
                net = Decimal(post[index] - pre[index])
                if net > 0:
                    extra += net
                continue
        extra += Decimal(movement["lamports"] or 0)
    return extra


def _verified_tips(raw, keys, address):
    tips = Decimal("0")
    for movement in _system_movements(raw, keys):
        if movement["kind"] != "transfer":
            continue
        if movement.get("source") != address:
            continue
        if movement.get("destination") in PUBLISHED_TIPS:
            tips += Decimal(movement["lamports"] or 0)
    return tips


def _route(raw, address, keys):
    message = (raw.get("transaction") or {}).get("message") or {}
    for index, instruction in enumerate(message.get("instructions") or []):
        if not isinstance(instruction, dict):
            continue
        program = _program(instruction, keys)
        payload = _b58decode(instruction.get("data"))
        accounts = _accounts(instruction, keys)
        # Independent FLASHX swap: observed 0x00 payload, wallet at 1.
        # Wraps (0x01) and other short opcodes are not swaps.
        if (
            program == FLASHX
            and payload
            and payload[0] == 0
            and len(payload) >= 16
            and len(accounts) >= 20
            and accounts[1] == address
        ):
            return {
                "program": program,
                "instruction": "flashx_swap",
                "discriminator": payload[:8].hex(),
                "authority": accounts[1],
                "owned": [],
                "accounts": accounts,
                "index": index,
                "path": f"transaction.message.instructions.{index}",
            }
        if len(payload) < 8:
            continue
        disc = payload[:8].hex()
        layout = PINNED.get((program, disc))
        if not layout:
            continue
        name, authority_idx, owned_idx = layout
        if authority_idx >= len(accounts) or accounts[authority_idx] != address:
            continue
        owned = [accounts[i] for i in owned_idx if i < len(accounts)]
        return {
            "program": program,
            "instruction": name,
            "discriminator": disc,
            "authority": accounts[authority_idx],
            "owned": owned,
            "accounts": accounts,
            "index": index,
            "path": f"transaction.message.instructions.{index}",
        }
    return None


def _unwrap(record):
    if not isinstance(record, dict):
        return record
    if "transaction" in record:
        return record
    raw = record.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and "transaction" in result:
            return result
        if "transaction" in raw:
            return raw
    result = record.get("result")
    if isinstance(result, dict) and "transaction" in result:
        return result
    return record


def reconstruct_record(record, address):
    raw = _unwrap(record)
    if not isinstance(raw, dict):
        return None
    meta = raw.get("meta") or {}
    if meta.get("err") is not None:
        return None
    keys = _keys(raw)
    if address not in keys:
        return None
    route = _route(raw, address, keys)
    if not route:
        return None
    token_deltas, pre, post = _owned_token_deltas(raw, address)
    accounts = _token_accounts(raw, address, keys)
    native, paid = _native_delta(raw, address, keys)
    wsol = token_deltas.pop(WSOL, Decimal("0"))
    movements = _system_movements(raw, keys)
    wsol_accounts = {account for account, info in accounts.items() if info.get("mint") == WSOL}
    closed = _closed_to_wallet(raw, keys, address)
    wrap_accounts = wsol_accounts | set(route.get("owned") or []) | closed
    rent = _rent_correction(raw, accounts)
    outside = _outside_native(movements, address, wrap_accounts, route.get("index"))
    retained = _non_token_creates(
        movements, address, set(accounts) | wrap_accounts,
        raw=raw, keys=keys, route_index=route.get("index"),
    )
    isolated, isolated_ok = _isolated_pumpswap_user_volume(raw, keys, address, route)
    if not isolated_ok:
        return None
    inner_venues, inner_ok = _inner_venues(raw, keys, route, address, set(accounts))
    if not inner_ok:
        return None
    # Isolate the swap quote: wallet SOL+wSOL minus tips/other transfers, ATA rent,
    # and IDL-located PumpSwap user-volume. Those are costs or residuals, not
    # consideration. Generic not-owned creates stay in native.
    settlement = native + wsol + rent - outside + retained + isolated
    tips = _verified_tips(raw, keys, address)
    fee = Decimal(meta.get("fee") or 0) if paid else Decimal("0")
    quote_mint = None
    quote_delta = Decimal("0")
    for mint in QUOTE_MINTS:
        delta = token_deltas.pop(mint, Decimal("0"))
        if delta == 0:
            continue
        if quote_mint is not None:
            return None
        quote_mint, quote_delta = mint, delta
    assets = [(mint, qty) for mint, qty in token_deltas.items() if qty != 0]
    if quote_mint and not assets:
        return None
    if len(assets) != 1:
        return None
    mint, quantity = assets[0]
    quote_settled = settlement == 0 and quote_delta != 0 and (quantity > 0) != (quote_delta > 0)
    sol_settled = settlement != 0 and quote_delta == 0 and (quantity > 0) != (settlement > 0)
    if not quote_settled and not sol_settled:
        return None
    kind = "buy" if quantity > 0 else "sell"
    signature = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
    timestamp = raw.get("blockTime")
    fees = _canonical((fee + tips) / LAMPORTS)
    if quote_settled:
        quote_decimals = next(
            (info.get("decimals") for info in accounts.values() if info.get("mint") == quote_mint),
            6,
        )
        try:
            quote_scale = Decimal(10) ** int(quote_decimals)
        except (TypeError, ValueError, OverflowError):
            quote_scale = USDC_DECIMALS
        consideration_sol = "0"
        quote_amount = _canonical(abs(quote_delta) / quote_scale)
        settlement_asset = QUOTE_ASSET[quote_mint]
        consideration_usdc = quote_amount if quote_mint == USDC else None
        consideration_usdt = quote_amount if quote_mint == USDT else None
    else:
        consideration_sol = _canonical(abs(settlement) / LAMPORTS)
        consideration_usdc = None
        consideration_usdt = None
        settlement_asset = "SOL"
    return {
        "kind": kind,
        "mint": mint,
        "quantity_raw": str(abs(quantity)),
        "consideration_sol": consideration_sol,
        "consideration_usdc": consideration_usdc,
        "consideration_usdt": consideration_usdt,
        "settlement_asset": settlement_asset,
        "network_fee_sol": _canonical(fee / LAMPORTS),
        "tips_sol": _canonical(tips / LAMPORTS),
        "fees_and_tips_sol": fees,
        "inner_venues": inner_venues,
        "signature": signature,
        "timestamp": timestamp,
        "slot": raw.get("slot") if raw.get("slot") is not None else record.get("slot"),
        "transaction_index": (
            record.get("transaction_index")
            if record.get("transaction_index") is not None
            else raw.get("transactionIndex") if raw.get("transactionIndex") is not None
            else record.get("transactionIndex")
        ),
        "program": route["program"],
        "instruction": route["instruction"],
        "discriminator": route["discriminator"],
        "path": route["path"],
        "observed_pre_quantity_raw": str(pre.get(mint, Decimal("0"))),
        "observed_post_quantity_raw": str(post.get(mint, Decimal("0"))),
        "source": "independent-pinned-interface",
    }


def _gta_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    records = payload.get("records")
    if isinstance(records, list) and records and isinstance(records[0], dict) and "transaction" in records[0]:
        return records
    body = payload.get("cleaned_body") if isinstance(payload.get("cleaned_body"), dict) else payload
    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        return result["data"]
    if isinstance(result, list):
        return result
    if isinstance(records, list):
        return records
    return []


def _load_pages(address, pages):
    records = []
    seen = set()
    for page in pages:
        path = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06" / page["repo_gz_path"]
        raw = gzip.decompress(path.read_bytes())
        if page.get("raw_sha256"):
            assert hashlib.sha256(raw).hexdigest() == page["raw_sha256"]
        for item in _gta_records(json.loads(raw)):
            if not isinstance(item, dict):
                continue
            signature = item.get("signature")
            tx = item.get("transaction") if isinstance(item.get("transaction"), dict) else {}
            sigs = tx.get("signatures") or []
            if not signature and sigs:
                signature = sigs[0]
            if signature and signature in seen:
                continue
            if signature:
                seen.add(signature)
            records.append(item)
    return records


def _fifo(trades):
    by_mint = defaultdict(list)
    for trade in trades:
        by_mint[trade["mint"]].append(trade)
    episodes = []
    unresolved = 0
    known_sales = 0
    omitted_losing = []
    for mint, rows in by_mint.items():
        rows = sorted(rows, key=lambda row: (
            row.get("slot") if isinstance(row.get("slot"), int) else 0,
            row.get("transaction_index") if isinstance(row.get("transaction_index"), int) else 0,
            row.get("timestamp") or 0,
            row.get("signature") or "",
        ))
        first_buy = next((row for row in rows if row["kind"] == "buy"), None)
        opening = Decimal(str(first_buy["observed_pre_quantity_raw"])) if first_buy else Decimal("0")
        lots = []
        inventory = Decimal("0")
        opened = False
        episode_pnl = Decimal("0")
        episode_basis = Decimal("0")
        episode_proceeds = Decimal("0")
        episode_costs = Decimal("0")
        episode_asset = None
        episode_consumed_opening = False
        for row in rows:
            qty = Decimal(row["quantity_raw"])
            asset = row.get("settlement_asset") or "SOL"
            if asset == "USDC" and row.get("consideration_usdc") not in (None, ""):
                consideration = Decimal(row["consideration_usdc"])
                # SOL fees stay on the event (fees_and_tips_sol). Mixing them
                # into a USDC episode net would change the quote unit.
                fees = Decimal("0")
            elif asset == "USDT" and row.get("consideration_usdt") not in (None, ""):
                consideration = Decimal(row["consideration_usdt"])
                fees = Decimal("0")
            else:
                consideration = Decimal(row["consideration_sol"])
                fees = Decimal(row.get("fees_and_tips_sol") or 0)
            if episode_asset is None:
                episode_asset = asset
            elif asset != episode_asset:
                # Mixed quote assets on one mint cannot form a clean independent episode.
                unresolved += 1
                continue
            if row["kind"] == "buy":
                if opening > 0 and not lots and inventory == 0:
                    pass
                lots.append({"qty": qty, "cost": consideration, "fees": fees})
                inventory += qty
                opened = True
                continue
            remaining = qty
            if opening > 0:
                take = opening if opening <= remaining else remaining
                if take > 0:
                    episode_consumed_opening = True
                opening -= take
                remaining -= take
                unresolved += 1
                if remaining <= 0:
                    continue
            basis = Decimal("0")
            buy_fees = Decimal("0")
            matched = Decimal("0")
            while remaining > 0 and lots:
                lot = lots[0]
                take = lot["qty"] if lot["qty"] <= remaining else remaining
                share = lot["cost"] * take / lot["qty"]
                fee_share = lot["fees"] * take / lot["qty"]
                basis += share
                buy_fees += fee_share
                lot["cost"] -= share
                lot["fees"] -= fee_share
                lot["qty"] -= take
                remaining -= take
                matched += take
                inventory -= take
                if lot["qty"] == 0:
                    lots.pop(0)
            if remaining > 0:
                unresolved += 1
            if matched > 0:
                proceeds = consideration * matched / qty
                sale_fees = fees * matched / qty
                pnl = proceeds - basis - buy_fees - sale_fees
                known_sales += 1
                episode_pnl += pnl
                episode_basis += basis
                episode_proceeds += proceeds
                episode_costs += buy_fees + sale_fees
            observed_post = row.get("observed_post_quantity_raw")
            flattened = False
            if observed_post not in (None, ""):
                try:
                    flattened = Decimal(str(observed_post)) == 0
                except (InvalidOperation, ValueError, TypeError):
                    flattened = False
            # Reconstructed buy qty can miss dust transfers. An observed
            # flatten (wallet token balance back to 0) with unmatched sell
            # qty is the app's oversell reset: abandon the lot, do not emit,
            # and do not glue the next flat on (AX5FaYB3 4k3Dyjzv 58590 raw
            # dust used to merge 319/321 into a mint-wide 583/640).
            if opened and flattened and remaining > 0 and opening == 0:
                opened = False
                episode_consumed_opening = False
                episode_pnl = Decimal("0")
                episode_basis = Decimal("0")
                episode_proceeds = Decimal("0")
                episode_costs = Decimal("0")
                episode_asset = None
                lots = []
                inventory = Decimal("0")
                continue
            if opened and inventory == 0 and remaining == 0 and opening == 0:
                timestamp = row.get("timestamp")
                in_window = timestamp is not None and REPORT_START <= timestamp < REPORT_END
                # Opening inventory is unknown cost. A flatten that consumed any
                # of it is not a clean completed episode (same rule as the app).
                if in_window and not episode_consumed_opening:
                    episodes.append({
                        "mint": mint,
                        "close_signature": row["signature"],
                        "venue": row.get("program"),
                        "instruction": row.get("instruction"),
                        "settlement_asset": episode_asset or row.get("settlement_asset") or "SOL",
                        "basis_sol": _canonical(episode_basis),
                        "proceeds_sol": _canonical(episode_proceeds),
                        "verified_costs_sol": _canonical(episode_costs),
                        "net_profit_sol": _canonical(episode_pnl),
                    })
                elif episode_pnl < 0 and matched > 0:
                    omitted_losing.append({
                        "mint": mint,
                        "net_profit_sol": _canonical(episode_pnl),
                        "reason": "opening_inventory" if episode_consumed_opening else "not_in_window_or_unresolved",
                    })
                opened = False
                episode_consumed_opening = False
                episode_pnl = Decimal("0")
                episode_basis = Decimal("0")
                episode_proceeds = Decimal("0")
                episode_costs = Decimal("0")
                episode_asset = None
        if first_buy and Decimal(str(first_buy["observed_pre_quantity_raw"])) > 0:
            # Opening inventory consumed before captured buys; leftover opening is not a clean episode.
            pass
        if episode_pnl < 0 and opened:
            omitted_losing.append({
                "mint": mint,
                "net_profit_sol": _canonical(episode_pnl),
                "reason": "unflattened_losing_inventory",
            })
    return episodes, unresolved, known_sales, omitted_losing


def economic_trade_identity(event):
    """Bot-rule identity. Token-to-token included. Route legs are not trades."""
    if not isinstance(event, dict):
        return None
    if event.get("kind") not in ("buy", "sell"):
        return None
    signature = event.get("signature")
    if not signature:
        return None
    return (signature, event.get("kind"), event.get("mint"))


def independent_economic_trade_keys(events):
    keys = []
    seen = set()
    for event in events or []:
        key = economic_trade_identity(event)
        if key is None or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def economic_trades_by_utc_day(events):
    """Same bot-rule count as the app. Does not import scanner/."""
    counts = Counter()
    seen = set()
    for event in events or []:
        if not isinstance(event, dict):
            continue
        key = economic_trade_identity(event)
        if key is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        stamp = event.get("timestamp") or event.get("block_time") or event.get("blockTime")
        if stamp is None:
            continue
        if isinstance(stamp, str):
            try:
                stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
        try:
            stamp = int(stamp)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        counts[day] += 1
    return dict(counts)


def episode_net_totals(episodes):
    """Sum episode nets per currency. Refuse a mixed-unit total.

    SOL and USDC are not additive. A mixed set returns net=None, unit='mixed',
    and the per-currency map only.
    """
    if not episodes:
        return None, None, None
    by_unit = {}
    for item in episodes:
        unit = item.get("settlement_asset") or "SOL"
        by_unit[unit] = by_unit.get(unit, Decimal("0")) + Decimal(item["net_profit_sol"])
    canonical = {unit: _canonical(value) for unit, value in by_unit.items()}
    if len(canonical) == 1:
        unit = next(iter(canonical))
        return canonical[unit], unit, canonical
    return None, "mixed", canonical


def audit_address(address, pages):
    records = _load_pages(address, pages)
    trades = []
    for record in records:
        event = reconstruct_record(record, address)
        if event:
            trades.append(event)
    episodes, unresolved, known_sales, omitted_losing = _fifo(trades)
    wins = sum(1 for item in episodes if Decimal(item["net_profit_sol"]) > 0)
    episode_mints = {item["mint"] for item in episodes}
    reconstructed_mints = []
    by_mint = defaultdict(list)
    for trade in trades:
        by_mint[trade["mint"]].append(trade)
    for mint, mint_trades in by_mint.items():
        programs = sorted({row.get("program") for row in mint_trades if row.get("program")})
        instructions = sorted({row.get("instruction") for row in mint_trades if row.get("instruction")})
        assets = sorted({row.get("settlement_asset") or "SOL" for row in mint_trades})
        reconstructed_mints.append({
            "mint": mint,
            "programs": programs,
            "instructions": instructions,
            "settlement_assets": assets,
            "trade_count": len(mint_trades),
            "clean_completed_episode": mint in episode_mints,
        })
    reconstructed_mints.sort(key=lambda row: row["mint"])
    episode_net, episode_unit, episode_nets_by_unit = episode_net_totals(episodes)
    by_day = economic_trades_by_utc_day(trades)
    max_day = max(by_day.values()) if by_day else 0
    max_on = max(by_day, key=lambda item: (by_day[item], item)) if by_day else None
    return {
        "address": address,
        "records": len(records),
        "independently_reconstructed_trades": len(trades),
        "bot_rule_definition": BOT_RULE_DEFINITION,
        "economic_trades_by_utc_day": by_day,
        "max_economic_trades_in_one_day": max_day,
        "max_economic_trades_on": max_on,
        "clean_episodes": len(episodes),
        "independently_audited_episode_net": episode_net,
        "independently_audited_episode_net_unit": episode_unit,
        "independently_audited_episode_nets_by_unit": episode_nets_by_unit,
        "episode_win_rate": _canonical(Decimal(wins) / Decimal(len(episodes))) if episodes else None,
        "unresolved_basis_sales": unresolved,
        "dropped_losing_episodes": omitted_losing,
        "dropped_losers": bool(omitted_losing),
        "known_cost_sales": known_sales,
        "episodes": episodes,
        "reconstructed_mints": reconstructed_mints,
        "imports_scanner": False,
        "source": "raw_instructions_balances_ownership_pinned_interfaces",
        "PRODUCT_READY": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_address = defaultdict(list)
    for entry in (manifest.get("pages") or {}).values():
        by_address[entry["address"]].append(entry)
    results = []
    for address, pages in sorted(by_address.items(), key=lambda item: item[0]):
        pages = sorted(pages, key=lambda item: item.get("page_index") or 0)
        results.append(audit_address(address, pages))
    payload = {
        "kind": "independent-episode-audit-v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wallets": results,
        "imports_scanner": False,
        "PRODUCT_READY": False,
    }
    if args.write:
        OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wallets": [{k: row[k] for k in ("address", "clean_episodes", "independently_reconstructed_trades", "unresolved_basis_sales")} for row in results]}, indent=2))
    return payload


if __name__ == "__main__":
    main()
