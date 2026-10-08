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
import math
import re
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
RAW_QUOTE_ASSETS = frozenset({WSOL, USDC, USDT, "SOL"})
QUOTE_ASSET = {USDC: "USDC", USDT: "USDT"}
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
METEORA_DAMM_V2 = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"
RFQ_FILL = "61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH"
OKX = "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u"
DFLOW = "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH"
FLASHX = "FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9"
TITAN = "T1TANpTeScyeqVzzgNViGDNrkQ6qHz9KrSBS4aNXvGT"
TERM9Y = "term9YPb9mzAsABaqN71A4xdbxHmpBNZavpBiQKZzN3"
ROUTEU = "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS"
OKX_V2 = "6m2CDdhRgxpH4WjvdzxAYbGxwdGUz5MziiL5jek2kBma"
DFLOW_TRANSFER_TO_SPONSOR = bytes.fromhex("9bb38297c48bfda3")
DFLOW_UNWRAP = bytes.fromhex("63280e692d6bacc9")
DFLOW_SWAP = bytes.fromhex("f8c69e91e17587c8")
DFLOW_SWAP2 = bytes.fromhex("414b3f4ceb5b5b88")
DFLOW_SWAP_WITH_DESTINATION = bytes.fromhex("a8ac184dc59c8765")
DFLOW_WRAP = bytes.fromhex("2f3e9bac83cd25c9")
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
# Independent copy of the app bot-day cap. Do not import scanner.
MAX_ECONOMIC_TRADES_PER_UTC_DAY = 15
GT_ECONOMIC_TRADES_RULE = "gt_15_economic_trades_in_one_day"

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
    (JUPITER, "9d8ab85215f4f324"): ("exact_out_route_v2", 0, (1, 2)),
    (JUPITER, "3560e5cad8bbfa18"): ("shared_accounts_exact_out_route_v2", 1, (2, 5)),
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
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
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
    # Published HumidiFi AMM. HpNfyc2 is the earlier mis-pin; keep both.
    "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp",
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
REVIEWED_SWAP_PROGRAM_IDS = frozenset({
    PUMP, PUMP_SWAP, JUPITER, METEORA_DAMM_V2, RFQ_FILL, OKX, DFLOW, FLASHX,
    DGMG, PHOTON, DFLOW_DST, RAYDIUM_CLMM, RAYDIUM_CPMM, RAYDIUM_AMM,
    WHIRLPOOL, GMGN, METEORA_DLMM, *WELL_KNOWN_INNER_AMMS,
})
# Independent copy of the app net-balance allowlist. This module does not
# import scanner.investigation. CLMM is included because it has no PINNED layout.
NET_BALANCE_SWAP_PROGRAMS = frozenset({
    PUMP, PUMP_SWAP, JUPITER, METEORA_DAMM_V2, RFQ_FILL, OKX, DFLOW, FLASHX,
    DGMG, RAYDIUM_CLMM, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL, GMGN, METEORA_DLMM,
    TITAN, TERM9Y, ROUTEU, OKX_V2,
})
NET_BALANCE_SOL_DUST_LAMPORTS = Decimal("100000")
NET_BALANCE_COST_SOL_LAMPORTS = Decimal("20000000")
NET_BALANCE_REFERRAL_BPS = Decimal("200")
NET_BALANCE_INSTRUCTION = "net_balance"
# Independent copy of Pump non-swap discs (sha256("global:"+name)[:8]).
# A migrate/create that happens to look one-in/one-out must stay unresolved.
PUMP_NON_SWAP_DISCS = frozenset(
    hashlib.sha256(f"global:{name}".encode()).digest()[:8]
    for name in (
        "distribute_fee_to_holders",
        "claim_cashback",
        "claim_cashback_v2",
        "collect_creator_fee",
        "collect_creator_fee_v2",
        "create",
        "create_v2",
        "migrate",
        "migrate_v2",
        "init_user_volume_accumulator",
        "sync_user_volume_accumulator",
        "close_user_volume_accumulator",
    )
)
# v3 / probe counter: swap-type log or instruction name. Unknown venues that
# log Swap/Buy/Sell/Route still count when the wallet signed and a wallet-owned
# token balance changed.
_AUDITOR_SWAP_LOG_ATOMS = frozenset({
    "swap", "buy", "sell", "route", "fill", "swapevent", "exactin", "exactout",
})


def _auditor_log_looks_like_swap(text):
    """Word-atom scan. Not the app's SWAP_LIKE_LOG_RE."""
    for line in str(text or "").splitlines():
        tail = line.rsplit(":", 1)[-1] if ":" in line else line
        atom = "".join(ch for ch in tail.lower() if ch.isalnum())
        if any(token in atom for token in _AUDITOR_SWAP_LOG_ATOMS):
            return True
    return False
SWAP_IX_NAME_RE = re.compile(
    r"^(?:\w*Swap\w*|Buy\w*|Sell\w*|\w*Route\w*|Fill\w*|\w*Exact\w*In\w*|\w*Exact\w*Out\w*)$",
    re.I,
)
def _auditor_lp_disc(name):
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


# Auditor-owned program-id + discriminator table. Not the app LP word list.
# Includes Meteora DLMM rebalance / claim-fee so those txs are not trades.
AUDITOR_LP_DISCS = {
    METEORA_DLMM: frozenset({
        _auditor_lp_disc("rebalance_liquidity"),
        _auditor_lp_disc("RebalanceLiquidity"),
        _auditor_lp_disc("claim_fee"),
        _auditor_lp_disc("ClaimFee"),
        _auditor_lp_disc("claim_fee2"),
        _auditor_lp_disc("ClaimFee2"),
        _auditor_lp_disc("add_liquidity"),
        _auditor_lp_disc("add_liquidity2"),
        _auditor_lp_disc("AddLiquidity"),
        _auditor_lp_disc("AddLiquidity2"),
        _auditor_lp_disc("add_liquidity_by_strategy"),
        _auditor_lp_disc("add_liquidity_by_strategy2"),
        _auditor_lp_disc("add_liquidity_one_side"),
        _auditor_lp_disc("add_liquidity_one_side2"),
        _auditor_lp_disc("remove_liquidity"),
        _auditor_lp_disc("remove_liquidity2"),
        _auditor_lp_disc("RemoveLiquidity"),
        _auditor_lp_disc("RemoveLiquidity2"),
        _auditor_lp_disc("remove_all_liquidity"),
        _auditor_lp_disc("close_position"),
        _auditor_lp_disc("initialize_position"),
    }),
    WHIRLPOOL: frozenset({
        _auditor_lp_disc("open_position"),
        _auditor_lp_disc("open_position_with_metadata"),
        _auditor_lp_disc("close_position"),
        _auditor_lp_disc("increase_liquidity"),
        _auditor_lp_disc("increase_liquidity_v2"),
        _auditor_lp_disc("decrease_liquidity"),
        _auditor_lp_disc("decrease_liquidity_v2"),
    }),
    RAYDIUM_CLMM: frozenset({
        _auditor_lp_disc("open_position"),
        _auditor_lp_disc("open_position_v2"),
        _auditor_lp_disc("close_position"),
        _auditor_lp_disc("increase_liquidity"),
        _auditor_lp_disc("increase_liquidity_v2"),
        _auditor_lp_disc("decrease_liquidity"),
        _auditor_lp_disc("decrease_liquidity_v2"),
    }),
}
# Per-program instruction names for log-stripped fixtures. Independent of
# the app LP_LOG_RE word list; keyed by the same programs as AUDITOR_LP_DISCS.
AUDITOR_LP_NAMES = {
    METEORA_DLMM: frozenset({
        "rebalance_liquidity", "RebalanceLiquidity",
        "claim_fee", "ClaimFee", "claim_fee2", "ClaimFee2",
        "add_liquidity", "add_liquidity2", "AddLiquidity", "AddLiquidity2",
        "add_liquidity_by_strategy", "addLiquidityByStrategy",
        "add_liquidity_by_strategy2", "addLiquidityByStrategy2",
        "add_liquidity_one_side", "addLiquidityOneSide",
        "remove_liquidity", "remove_liquidity2", "removeLiquidity", "removeLiquidity2",
        "RemoveLiquidity", "RemoveLiquidity2",
        "remove_all_liquidity", "close_position", "initialize_position",
    }),
    WHIRLPOOL: frozenset({
        "open_position", "OpenPosition", "open_position_with_metadata",
        "OpenPositionWithMetadata", "OpenPositionWithTokenExtensions",
        "close_position", "ClosePosition",
        "increase_liquidity", "IncreaseLiquidity", "increase_liquidity_v2",
        "decrease_liquidity", "DecreaseLiquidity", "decrease_liquidity_v2",
    }),
    RAYDIUM_CLMM: frozenset({
        "open_position", "OpenPosition", "open_position_v2",
        "close_position", "ClosePosition",
        "increase_liquidity", "IncreaseLiquidity",
        "decrease_liquidity", "DecreaseLiquidity",
    }),
}


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


def _other_owner_open_funding(raw, address, keys):
    """Lamports the wallet paid to still-open accounts it does not own."""
    owned = _lifecycle_owned_accounts(raw, address, keys)
    meta = raw.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    total = Decimal("0")
    for movement in _system_movements(raw, keys):
        if movement["kind"] != "create" or movement.get("source") != address:
            continue
        dest = movement.get("destination")
        if not dest or dest in owned:
            continue
        if dest in keys:
            index = keys.index(dest)
            if index < len(pre) and index < len(post) and post[index] > 0:
                total += Decimal(post[index] - pre[index])
                continue
        total += Decimal(movement["lamports"] or 0)
    return total


def _net_inner_venues(raw, keys, program):
    """Reviewed inner programs under the first matching net-balance outer."""
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    idx = None
    for index, outer in enumerate(message.get("instructions") or []):
        if not isinstance(outer, dict):
            continue
        if _program(outer, keys) == program:
            idx = index
            break
    if idx is None:
        return []
    venues = []
    seen = set()
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict) or group.get("index") != idx:
            continue
        for instruction in group.get("instructions") or []:
            if not isinstance(instruction, dict):
                continue
            inner = _program(instruction, keys)
            if not inner or inner in _INNER_INFRA or inner in seen:
                continue
            seen.add(inner)
            venues.append({"program": inner})
    return venues


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


def _wallet_is_signer(raw, address, keys):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    header = message.get("header") if isinstance(message.get("header"), dict) else {}
    needed = header.get("numRequiredSignatures")
    if type(needed) is not int or isinstance(needed, bool) or needed < 1:
        needed = 1
    return bool(address) and address in keys[:needed]


def _first_net_balance_program(raw, keys):
    """OUTER reviewed swap program only. Inners under B311/Photon do not qualify."""
    for _outer, _path, instruction, nested in _iter_instructions(raw):
        if nested:
            continue
        program = _program(instruction, keys)
        if program not in NET_BALANCE_SWAP_PROGRAMS:
            continue
        payload = _b58decode(instruction.get("data"))
        if program == DFLOW and payload[:8] not in {
            DFLOW_SWAP, DFLOW_SWAP2, DFLOW_SWAP_WITH_DESTINATION, DFLOW_WRAP,
        }:
            continue
        if program == PUMP and payload[:8] in PUMP_NON_SWAP_DISCS:
            continue
        return program
    return None


_TOKEN_HOP_OK = frozenset({"transfer", "transferChecked"})
_TOKEN_HOP_FORBIDDEN = frozenset({
    "approve", "approveChecked", "setAuthority", "closeAccount",
    "burn", "burnChecked", "mintTo", "mintToChecked",
})
_TOKEN_TAG_KIND = {
    3: "transfer",
    4: "approve",
    6: "setAuthority",
    7: "mintTo",
    8: "burn",
    9: "closeAccount",
    12: "transferChecked",
    13: "approveChecked",
    14: "mintToChecked",
    15: "burnChecked",
}


def _touched_accounts(instruction, keys):
    touched = set(_accounts(instruction, keys))
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    if isinstance(info, dict):
        for field in ("source", "destination", "account", "newAccount", "owner", "authority", "wallet"):
            value = info.get(field)
            if isinstance(value, str) and value:
                touched.add(value)
    return touched


def _has_unreviewed_outer_program(raw, keys):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        program = _program(instruction, keys)
        if not program:
            return True
        if program in _INNER_INFRA or program in NET_BALANCE_SWAP_PROGRAMS:
            continue
        return True
    return False


def _system_transfer_from_wallet(instruction, address, keys):
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind == "transfer" and isinstance(info, dict) and info.get("source") == address:
        return True
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if len(payload) >= 4 and int.from_bytes(payload[:4], "little") == 2:
        return bool(accounts) and accounts[0] == address
    return False


def _token_hop_fields(instruction, keys):
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    if not isinstance(info, dict):
        info = {}
    if kind:
        return kind, info
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if not payload:
        return None, {}
    kind = _TOKEN_TAG_KIND.get(payload[0])
    if kind == "transfer" and len(accounts) >= 3:
        return kind, {
            "source": accounts[0],
            "destination": accounts[1],
            "authority": accounts[2],
        }
    if kind == "transferChecked" and len(accounts) >= 4:
        return kind, {
            "source": accounts[0],
            "destination": accounts[2],
            "authority": accounts[3],
        }
    return kind, {"account": accounts[0]} if accounts else {}


def _hop_token_op_ok(instruction, owned, address, keys):
    kind, info = _token_hop_fields(instruction, keys)
    touched = _touched_accounts(instruction, keys)
    for field in ("source", "destination", "account", "authority", "owner", "wallet", "newAccount"):
        value = info.get(field)
        if isinstance(value, str) and value:
            touched.add(value)
    if not touched.intersection(owned):
        return True
    if kind in _TOKEN_HOP_FORBIDDEN or kind not in _TOKEN_HOP_OK:
        return False
    authority = info.get("authority") or info.get("multisigAuthority")
    destination = info.get("destination")
    return authority == address or destination in owned


def _jup_hop_children_ok(inners, start, owned, address, keys):
    for instruction in inners[start:]:
        if instruction.get("stackHeight") == 2:
            break
        program = _program(instruction, keys)
        if not program:
            return False
        if program in TOKEN_PROGRAMS:
            if not _hop_token_op_ok(instruction, owned, address, keys):
                return False
        elif program == SYSTEM:
            # Hop SOL movement is never a swap leg. Written as a dest/src pair
            # check, not the app's from-wallet helper.
            parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
            info = parsed.get("info") if isinstance(parsed, dict) else None
            if isinstance(info, dict) and (
                info.get("source") == address or info.get("destination") == address
            ):
                return False
            return False if _system_transfer_from_wallet(instruction, address, keys) else True
    return True


def _jupiter_hop_inner_ok(raw, address, keys):
    """Independent JUP6 stackHeight-2 hop predicate. Does not import the app."""
    if not isinstance(raw, dict) or not address or not keys:
        return False
    if _has_unreviewed_outer_program(raw, keys):
        return False
    accounts = _token_accounts(raw, address, keys)
    owned = {address, *accounts}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    outers = message.get("instructions") or []
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        outer_index = group.get("index")
        outer_program = None
        if (type(outer_index) is int and not isinstance(outer_index, bool)
                and 0 <= outer_index < len(outers) and isinstance(outers[outer_index], dict)):
            outer_program = _program(outers[outer_index], keys)
        inners = [ix for ix in (group.get("instructions") or []) if isinstance(ix, dict)]
        for idx, instruction in enumerate(inners):
            program = _program(instruction, keys)
            if not program or program in REVIEWED_INNER_PROGRAMS:
                continue
            if not _touched_accounts(instruction, keys).intersection(owned):
                continue
            if outer_program not in NET_BALANCE_SWAP_PROGRAMS or instruction.get("stackHeight") != 2:
                return False
            if not _jup_hop_children_ok(inners, idx + 1, owned, address, keys):
                return False
    return True


def _auditor_unknown_inner_touches_wallet(raw, address, keys):
    """True when a nested non-reviewed program touches wallet assets.

    Uses `_iter_instructions` (not the app's inner-group loop).
    """
    accounts = _token_accounts(raw, address, keys)
    wallet_assets = {address, *accounts}
    for _outer, _path, instruction, nested in _iter_instructions(raw):
        if not nested:
            continue
        program = _program(instruction, keys)
        if not program or program in REVIEWED_INNER_PROGRAMS:
            continue
        if _touched_accounts(instruction, keys).intersection(wallet_assets):
            return True
    return False


def _net_balance_unknown_inner_blocks(raw, keys, address):
    """Independent D3: unknown inner touching wallet assets fails closed."""
    accounts = _token_accounts(raw, address, keys)
    wallet_assets = {address, *accounts}
    unknown_touch = False
    for _outer, _path, instruction, nested in _iter_instructions(raw):
        if not nested:
            continue
        program = _program(instruction, keys)
        if not program or program in REVIEWED_INNER_PROGRAMS:
            continue
        if _touched_accounts(instruction, keys).intersection(wallet_assets):
            unknown_touch = True
            break
    if not unknown_touch:
        return False
    return not _jupiter_hop_inner_ok(raw, address, keys)


def _ata_create_owner_account(instruction, keys):
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind in ("create", "createIdempotent") and isinstance(info, dict):
        return info.get("wallet") or info.get("owner"), info.get("account")
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if payload not in (b"", b"\0", b"\x01") or len(accounts) < 3:
        return None, None
    return accounts[2], accounts[1]


def _other_wallet_ata_keeps_tokens(raw, address, keys, token_deltas=None):
    """True when a new other-wallet ATA retains more than the referral bound."""
    created = set()
    for _outer, _path, instruction, _nested in _iter_instructions(raw):
        program = _program(instruction, keys)
        if program != ASSOCIATED:
            continue
        owner, account = _ata_create_owner_account(instruction, keys)
        if owner and owner != address and account:
            created.add(account)
    if not created:
        return False
    token_deltas = token_deltas or {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for balance in meta.get("postTokenBalances") or []:
        if not isinstance(balance, dict):
            continue
        index = balance.get("accountIndex")
        if type(index) is not int or isinstance(index, bool) or index < 0 or index >= len(keys):
            continue
        if keys[index] not in created:
            continue
        amount = (balance.get("uiTokenAmount") or {}).get("amount")
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return True
        if qty <= 0:
            continue
        mint = balance.get("mint")
        net = abs(token_deltas.get(mint, Decimal("0"))) if mint else Decimal("0")
        if net == 0:
            continue
        cap = max(Decimal(1), net * NET_BALANCE_REFERRAL_BPS / Decimal(10_000))
        if qty > cap:
            return True
    return False


def _lifecycle_owned_accounts(raw, address, keys):
    owned = {address, *_token_accounts(raw, address, keys)}
    for _outer, _path, instruction, _nested in _iter_instructions(raw):
        program = _program(instruction, keys)
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        if program == ASSOCIATED:
            owner, account = _ata_create_owner_account(instruction, keys)
            if owner == address and account:
                owned.add(account)
            continue
        if program in TOKEN_PROGRAMS and kind in ("initializeAccount", "initializeAccount2", "initializeAccount3"):
            if isinstance(info, dict) and info.get("owner") == address and info.get("account"):
                owned.add(info["account"])
    return owned


def _outbound_above_fee_bound(raw, address, keys, token_deltas):
    """True when a top-level transfer to someone else exceeds the fee bound."""
    owned = _lifecycle_owned_accounts(raw, address, keys)
    for _outer, _path, instruction, nested in _iter_instructions(raw):
        if nested:
            continue
        program = _program(instruction, keys)
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        if program == SYSTEM:
            if kind == "transfer" and isinstance(info, dict):
                if info.get("source") != address:
                    continue
                dest = info.get("destination")
                if dest in owned or dest in PUBLISHED_TIPS:
                    continue
                lamports = info.get("lamports")
                if type(lamports) is int and not isinstance(lamports, bool) and lamports > NET_BALANCE_COST_SOL_LAMPORTS:
                    return True
                continue
            payload = _b58decode(instruction.get("data"))
            accounts = _accounts(instruction, keys)
            if len(payload) >= 12 and int.from_bytes(payload[:4], "little") == 2:
                dest = accounts[1] if len(accounts) > 1 else None
                if accounts and accounts[0] == address and dest not in owned and dest not in PUBLISHED_TIPS:
                    if int.from_bytes(payload[4:12], "little") > int(NET_BALANCE_COST_SOL_LAMPORTS):
                        return True
            continue
        if program not in TOKEN_PROGRAMS or kind not in ("transfer", "transferChecked", "transferCheckedWithFee"):
            continue
        if not isinstance(info, dict):
            continue
        source, dest = info.get("source"), info.get("destination")
        if source not in owned or dest in owned:
            continue
        checked = info.get("tokenAmount") if kind in ("transferChecked", "transferCheckedWithFee") else None
        amount = (checked or {}).get("amount") if checked else info.get("amount")
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return True
        mint = info.get("mint")
        if not mint:
            continue
        net = abs(token_deltas.get(mint, Decimal("0")))
        if net == 0:
            continue
        cap = max(Decimal(1), net * NET_BALANCE_REFERRAL_BPS / Decimal(10_000))
        if qty > cap:
            return True
    return False


def _account_mint_map(raw, keys):
    mints = {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for field in ("preTokenBalances", "postTokenBalances"):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict):
                continue
            index = balance.get("accountIndex")
            mint = balance.get("mint")
            if type(index) is int and not isinstance(index, bool) and 0 <= index < len(keys) and mint:
                mints[keys[index]] = mint
    return mints


def _system_transfer_leg(instruction, keys):
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind == "transfer" and isinstance(info, dict):
        lamports = info.get("lamports")
        if type(lamports) is int and not isinstance(lamports, bool) and lamports > 0:
            return info.get("source"), info.get("destination"), Decimal(lamports)
        return None
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if len(payload) >= 12 and int.from_bytes(payload[:4], "little") == 2:
        lamports = int.from_bytes(payload[4:12], "little")
        if lamports > 0 and len(accounts) >= 2:
            return accounts[0], accounts[1], Decimal(lamports)
    return None


def _token_transfer_leg(instruction, keys, mints):
    kind, info = _token_hop_fields(instruction, keys)
    if kind not in ("transfer", "transferChecked", "transferCheckedWithFee"):
        return None
    source, dest = info.get("source"), info.get("destination")
    if not source or not dest:
        return None
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    parsed_info = parsed.get("info") if isinstance(parsed, dict) else None
    qty = None
    if isinstance(parsed_info, dict):
        checked = parsed_info.get("tokenAmount") if kind in ("transferChecked", "transferCheckedWithFee") else None
        amount = (checked or {}).get("amount") if checked else parsed_info.get("amount")
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            qty = None
    if qty is None:
        payload = _b58decode(instruction.get("data"))
        if payload and payload[0] in (3, 12) and len(payload) >= 9:
            qty = Decimal(int.from_bytes(payload[1:9], "little"))
    if qty is None or qty <= 0:
        return None
    mint = info.get("mint") or mints.get(source) or mints.get(dest)
    return source, dest, qty, mint


def _token_close_to_wallet(instruction, keys, owned):
    """Closed token account whose rent/wSOL native is paid to the wallet."""
    parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind == "closeAccount" and isinstance(info, dict):
        account, dest = info.get("account"), info.get("destination")
        if dest in owned and account:
            return account, dest
        return None
    payload = _b58decode(instruction.get("data"))
    accounts = _accounts(instruction, keys)
    if payload[:1] == b"\x09" and len(accounts) >= 2 and accounts[1] in owned:
        return accounts[0], accounts[1]
    return None


def _route_cpi_wallet_flows(raw, address, keys):
    """Sum inner CPI transfers under net-balance outers that touch the wallet.

    Distinct from the app's all-depth parsed-transfer walk: only inners under
    a reviewed net-balance outer count.
    """
    owned = _lifecycle_owned_accounts(raw, address, keys)
    mints = _account_mint_map(raw, keys)
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    outers = message.get("instructions") or []
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    sol = Decimal("0")
    tokens = {}
    saw = False
    route_accounts = set()
    for idx, outer in enumerate(outers):
        if not isinstance(outer, dict):
            continue
        program = _program(outer, keys)
        if program not in NET_BALANCE_SWAP_PROGRAMS:
            continue
        payload = _b58decode(outer.get("data"))
        if program == DFLOW and payload[:8] not in {
            DFLOW_SWAP, DFLOW_SWAP2, DFLOW_SWAP_WITH_DESTINATION, DFLOW_WRAP,
        }:
            continue
        if program == PUMP and payload[:8] in PUMP_NON_SWAP_DISCS:
            continue
        route_accounts.update(_accounts(outer, keys))
        route_accounts.add(program)
        for group in meta.get("innerInstructions") or []:
            if not isinstance(group, dict) or group.get("index") != idx:
                continue
            for instruction in group.get("instructions") or []:
                if not isinstance(instruction, dict):
                    continue
                route_accounts.update(_accounts(instruction, keys))
                inner_program = _program(instruction, keys)
                if inner_program == SYSTEM:
                    leg = _system_transfer_leg(instruction, keys)
                    if not leg:
                        continue
                    source, dest, lamports = leg
                    if dest in owned and source not in owned:
                        continue
                    elif source in owned and dest not in owned:
                        sol -= lamports
                        saw = True
                    continue
                if inner_program not in TOKEN_PROGRAMS:
                    continue
                closed = _token_close_to_wallet(instruction, keys, owned)
                if closed:
                    account, _dest = closed
                    if account in keys:
                        index = keys.index(account)
                        if index < len(pre) and index < len(post):
                            credit = Decimal(pre[index] - post[index])
                            if credit > 0:
                                sol += credit
                                saw = True
                    continue
                leg = _token_transfer_leg(instruction, keys, mints)
                if not leg:
                    continue
                source, dest, qty, mint = leg
                if dest in owned and source not in owned:
                    saw = True
                    if mint:
                        tokens[mint] = tokens.get(mint, Decimal("0")) + qty
                elif source in owned and dest not in owned:
                    saw = True
                    if mint:
                        tokens[mint] = tokens.get(mint, Decimal("0")) - qty
    # Jupiter wrap/unwrap often closes the temp wSOL ATA as a sibling outer.
    for _outer, _path, instruction, nested in _iter_instructions(raw):
        if nested or _program(instruction, keys) not in TOKEN_PROGRAMS:
            continue
        closed = _token_close_to_wallet(instruction, keys, owned)
        if not closed:
            continue
        account, _dest = closed
        if account not in route_accounts and account not in owned:
            continue
        if account not in keys:
            continue
        index = keys.index(account)
        if index >= len(pre) or index >= len(post):
            continue
        credit = Decimal(pre[index] - post[index])
        if credit > 0:
            sol += credit
            saw = True
    return saw, sol, tokens


def _auditor_prop_amm_native_taken(raw, keys):
    """SOL that appeared on unknown-inner *program* pubkeys.

    Balance-sheet over program ids only — not the app's hop-account walk.
    """
    if not isinstance(raw, dict) or not keys:
        return Decimal("0")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    programs = set()
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get("instructions") or []:
            if not isinstance(instruction, dict) or instruction.get("stackHeight") != 2:
                continue
            program = _program(instruction, keys)
            if program and program not in _INNER_INFRA:
                programs.add(program)
    if not programs:
        return Decimal("0")
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    taken = Decimal("0")
    for index, account in enumerate(keys):
        if account not in programs or index >= len(pre) or index >= len(post):
            continue
        try:
            delta = Decimal(str(post[index])) - Decimal(str(pre[index]))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            continue
        if delta > 0:
            taken += delta
    return taken


def _route_cpi_disagrees_with_wallet(raw, address, keys):
    """Fail closed when route CPI sums disagree with wallet balance deltas."""
    saw, cpi_sol, cpi_tokens = _route_cpi_wallet_flows(raw, address, keys)
    taken = _auditor_prop_amm_native_taken(raw, keys)
    if taken:
        cpi_sol -= taken
        saw = True
        # taken is raw hop-program lamports; `_native_delta` already added fee.
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
        if keys and keys[0] == address and fee:
            cpi_sol += Decimal(fee)
    if not saw:
        return True
    token_deltas, _pre, _post = _owned_token_deltas(raw, address)
    accounts = _token_accounts(raw, address, keys)
    native, paid = _native_delta(raw, address, keys)
    wsol = token_deltas.get(WSOL, Decimal("0"))
    rent = _rent_correction(raw, accounts)
    tips = _verified_tips(raw, keys, address)
    settlement = native + wsol + rent + tips
    if abs(settlement) <= NET_BALANCE_SOL_DUST_LAMPORTS:
        settlement = Decimal("0")
    cpi_sol += cpi_tokens.pop(WSOL, Decimal("0"))
    # Unknown hop with native SOL and no program-account take is not a swap leg.
    if (
        taken == 0
        and settlement != 0
        and cpi_sol == 0
        and _auditor_unknown_inner_touches_wallet(raw, address, keys)
        and _jupiter_hop_inner_ok(raw, address, keys)
    ):
        return True
    # Extra tips make settlement more negative. Fail only when the wallet
    # net is more profitable than the route CPI sum.
    if settlement > cpi_sol:
        return True
    for mint in set(cpi_tokens) | set(token_deltas):
        if mint in (None, WSOL):
            continue
        wallet_qty = token_deltas.get(mint, Decimal("0"))
        route_qty = cpi_tokens.get(mint, Decimal("0"))
        if wallet_qty > route_qty + Decimal("1"):
            return True
    return False


def _auditor_system_credit_to_wallet(raw, address, keys):
    """True when any System transfer credits the wallet.

    Distinct from the app's route-account set: this is a flat scan of every
    parsed/compiled System transfer. Unwrap is closeAccount, not System.
    """
    owned = _lifecycle_owned_accounts(raw, address, keys)
    for _outer, _path, instruction, _nested in _iter_instructions(raw):
        if _program(instruction, keys) != SYSTEM:
            continue
        leg = _system_transfer_leg(instruction, keys)
        if not leg:
            continue
        source, dest, _lamports = leg
        if dest in owned and source not in owned:
            return True
    return False


def _net_balance_reconstruct(raw, address, keys):
    """Independent net-balance path. Uses mint-aggregated deltas + rent + published tips.

    This is not the app's owner-walk + parsed-transfer tip method.
    """
    if not _wallet_is_signer(raw, address, keys):
        return None
    program = _first_net_balance_program(raw, keys)
    if not program:
        return None
    if _net_balance_unknown_inner_blocks(raw, keys, address):
        return None
    if _has_unreviewed_outer_program(raw, keys):
        return None
    token_deltas, pre, post = _owned_token_deltas(raw, address)
    if _other_wallet_ata_keeps_tokens(raw, address, keys, token_deltas):
        return None
    if _outbound_above_fee_bound(raw, address, keys, token_deltas):
        return None
    if _route_cpi_disagrees_with_wallet(raw, address, keys):
        return None
    if _auditor_system_credit_to_wallet(raw, address, keys):
        return None
    inner_venues = _net_inner_venues(raw, keys, program)
    accounts = _token_accounts(raw, address, keys)
    native, paid = _native_delta(raw, address, keys)
    wsol = token_deltas.pop(WSOL, Decimal("0"))
    rent = _rent_correction(raw, accounts)
    tips = _verified_tips(raw, keys, address)
    settlement = native + wsol + rent + tips
    if abs(settlement) <= NET_BALANCE_SOL_DUST_LAMPORTS:
        settlement = Decimal("0")
    others = [qty for qty in token_deltas.values() if qty != 0]
    other_funding = _other_owner_open_funding(raw, address, keys)
    # Other-owner still-open rent stays in settlement (D2p). Peel only a
    # leftover wrap/fee residue when that funding is absent.
    if (
        other_funding <= 0
        and len(others) >= 2
        and settlement < 0
        and abs(settlement) <= NET_BALANCE_COST_SOL_LAMPORTS
    ):
        settlement = Decimal("0")
    for mint, qty in list(token_deltas.items()):
        decimals = next((info.get("decimals") for info in accounts.values() if info.get("mint") == mint), None)
        if decimals == 0 and abs(qty) <= 1:
            return None
    quote_mint = None
    quote_delta = Decimal("0")
    for mint in QUOTE_MINTS:
        delta = token_deltas.pop(mint, Decimal("0"))
        if delta == 0:
            continue
        if quote_mint is not None:
            # Two stables plus optional SOL: conversion only when no other mint.
            if settlement == 0 and not any(qty != 0 for qty in token_deltas.values()):
                return {
                    "kind": "conversion",
                    "mint": mint if mint == USDC else quote_mint,
                    "quantity_raw": str(abs(delta if mint == USDC else quote_delta)),
                    "consideration_sol": "0",
                    "consideration_usdc": _canonical(abs(delta if mint == USDC else quote_delta) / USDC_DECIMALS) if USDC in (mint, quote_mint) else None,
                    "consideration_usdt": None,
                    "settlement_asset": "USDC" if USDC in (mint, quote_mint) else "USDT",
                    "network_fee_sol": _canonical((Decimal((raw.get("meta") or {}).get("fee") or 0) if paid else Decimal("0")) / LAMPORTS),
                    "tips_sol": _canonical(tips / LAMPORTS),
                    "fees_and_tips_sol": _canonical(((Decimal((raw.get("meta") or {}).get("fee") or 0) if paid else Decimal("0")) + tips) / LAMPORTS),
                    "inner_venues": inner_venues,
                    "signature": ((raw.get("transaction") or {}).get("signatures") or [None])[0],
                    "timestamp": raw.get("blockTime"),
                    "slot": raw.get("slot"),
                    "transaction_index": raw.get("transactionIndex"),
                    "program": program,
                    "instruction": NET_BALANCE_INSTRUCTION,
                    "discriminator": None,
                    "path": "meta.net_balance",
                    "observed_pre_quantity_raw": str(pre.get(USDC, Decimal("0"))),
                    "observed_post_quantity_raw": str(post.get(USDC, Decimal("0"))),
                    "source": "independent-net-balance",
                }
            return None
        quote_mint, quote_delta = mint, delta
    assets = [(mint, qty) for mint, qty in token_deltas.items() if qty != 0]
    meta = raw.get("meta") or {}
    fee = Decimal(meta.get("fee") or 0) if paid else Decimal("0")
    if quote_mint and not assets and settlement != 0 and (quote_delta > 0) != (settlement > 0):
        quote_decimals = next(
            (info.get("decimals") for info in accounts.values() if info.get("mint") == quote_mint),
            6,
        )
        try:
            quote_scale = Decimal(10) ** int(quote_decimals)
        except (TypeError, ValueError, OverflowError):
            quote_scale = USDC_DECIMALS
        quote_amount = _canonical(abs(quote_delta) / quote_scale)
        return {
            "kind": "conversion",
            "mint": quote_mint,
            "quantity_raw": str(abs(quote_delta)),
            "consideration_sol": _canonical(abs(settlement) / LAMPORTS),
            "consideration_usdc": quote_amount if quote_mint == USDC else None,
            "consideration_usdt": quote_amount if quote_mint == USDT else None,
            "settlement_asset": QUOTE_ASSET[quote_mint],
            "network_fee_sol": _canonical(fee / LAMPORTS),
            "tips_sol": _canonical(tips / LAMPORTS),
            "fees_and_tips_sol": _canonical((fee + tips) / LAMPORTS),
            "inner_venues": inner_venues,
            "signature": ((raw.get("transaction") or {}).get("signatures") or [None])[0],
            "timestamp": raw.get("blockTime"),
            "slot": raw.get("slot"),
            "transaction_index": raw.get("transactionIndex"),
            "program": program,
            "instruction": NET_BALANCE_INSTRUCTION,
            "discriminator": None,
            "path": "meta.net_balance",
            "observed_pre_quantity_raw": str(pre.get(quote_mint, Decimal("0"))),
            "observed_post_quantity_raw": str(post.get(quote_mint, Decimal("0"))),
            "source": "independent-net-balance",
        }
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
    signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0]
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
        "slot": raw.get("slot"),
        "transaction_index": raw.get("transactionIndex"),
        "program": program,
        "instruction": NET_BALANCE_INSTRUCTION,
        "discriminator": None,
        "path": "meta.net_balance",
        "observed_pre_quantity_raw": str(pre.get(mint, Decimal("0"))),
        "observed_post_quantity_raw": str(post.get(mint, Decimal("0"))),
        "source": "independent-net-balance",
    }


def _layout_reconstruct(record, address):
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


def _same_reconstructed_trade(left, right):
    return (
        left.get("kind") == right.get("kind")
        and left.get("mint") == right.get("mint")
        and str(left.get("quantity_raw")) == str(right.get("quantity_raw"))
    )


def reconstruct_record(record, address):
    """Layout or independent net-balance. Disagreement fails closed."""
    raw = _unwrap(record)
    if not isinstance(raw, dict):
        return None
    meta = raw.get("meta") or {}
    if meta.get("err") is not None:
        return None
    keys = _keys(raw)
    if address not in keys:
        return None
    first_nb = _first_net_balance_program(raw, keys)
    layout = _layout_reconstruct(record, address)
    net = _net_balance_reconstruct(raw, address, keys)
    if layout and net and not _same_reconstructed_trade(layout, net):
        return None
    pinned_programs = {item[0] for item in PINNED}
    # Pinned layout amounts come from the route interface, not wallet net, so
    # a CPI-vs-wallet miss (JUP wrap/unwrap) must not drop them. Net-only
    # venues stay gated inside _net_balance_reconstruct.
    if layout and net:
        chosen = layout
    elif layout and layout.get("program") in pinned_programs:
        chosen = layout
    elif first_nb:
        chosen = net
    else:
        chosen = layout or net
    return chosen


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


def _profit_fields(pnl, asset):
    """Emit settlement-aware profit keys. USDC/USDT are not net_profit_sol."""
    amount = _canonical(pnl)
    unit = asset or "SOL"
    fields = {"settlement_asset": unit, "net_profit": amount}
    if unit == "USDC":
        fields["net_profit_usdc"] = amount
    elif unit == "USDT":
        fields["net_profit_usdt"] = amount
    else:
        fields["net_profit_sol"] = amount
    return fields


def episode_profit_amount(item):
    """Read a FIFO episode/drop net in its settlement unit."""
    if not isinstance(item, dict):
        raise TypeError("episode row must be a dict")
    if item.get("net_profit") not in (None, ""):
        return Decimal(item["net_profit"])
    unit = item.get("settlement_asset") or "SOL"
    keyed = {"USDC": "net_profit_usdc", "USDT": "net_profit_usdt"}.get(unit, "net_profit_sol")
    if item.get(keyed) not in (None, ""):
        return Decimal(item[keyed])
    return Decimal(item["net_profit_sol"])


def _fifo_timestamp_in_window(timestamp):
    return timestamp is not None and REPORT_START <= timestamp < REPORT_END


def _losing_drop(mint, pnl, asset, timestamp, reason):
    # DC-10: a missing timestamp stays fail-closed with the original reason.
    if timestamp is None:
        return {
            "mint": mint,
            "timestamp": timestamp,
            **_profit_fields(pnl, asset),
            "reason": reason,
        }
    in_window = _fifo_timestamp_in_window(timestamp)
    return {
        "mint": mint,
        "timestamp": timestamp,
        **_profit_fields(pnl, asset),
        "reason": reason if in_window else "not_in_window_or_unresolved",
    }


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
            row.get("timestamp") if row.get("timestamp") is not None else 0,
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
        idx = 0
        while idx < len(rows):
            sig = rows[idx].get("signature")
            end = idx + 1
            if sig:
                while end < len(rows) and rows[end].get("signature") == sig:
                    end += 1
            group = rows[idx:end]
            idx = end
            kinds = {row["kind"] for row in group}
            if kinds == {"buy", "sell"}:
                buys = [row for row in group if row["kind"] == "buy"]
                sells = [row for row in group if row["kind"] == "sell"]
                if not opened and inventory == 0 and opening == 0:
                    group = buys + sells
                else:
                    group = sells + buys
            for row in group:
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
                    if episode_pnl < 0:
                        omitted_losing.append(_losing_drop(
                            mint, episode_pnl, episode_asset, row.get("timestamp"),
                            "oversold_flatten_reset",
                        ))
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
                            "timestamp": timestamp,
                            "basis_sol": _canonical(episode_basis),
                            "proceeds_sol": _canonical(episode_proceeds),
                            "verified_costs_sol": _canonical(episode_costs),
                            **_profit_fields(episode_pnl, episode_asset or row.get("settlement_asset") or "SOL"),
                        })
                    elif episode_pnl < 0:
                        omitted_losing.append(_losing_drop(
                            mint, episode_pnl, episode_asset, timestamp,
                            "opening_inventory" if episode_consumed_opening else "not_in_window_or_unresolved",
                        ))
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
            last_ts = rows[-1].get("timestamp") if rows else None
            omitted_losing.append(_losing_drop(
                mint, episode_pnl, episode_asset, last_ts,
                "unflattened_losing_inventory",
            ))
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


def _first_present(*values):
    for value in values:
        if value is None or isinstance(value, bool) or value == "":
            continue
        return value
    return None


def _event_unix(event):
    stamp = _first_present(
        (event or {}).get("block_time"),
        (event or {}).get("blockTime"),
        (event or {}).get("timestamp"),
    )
    if isinstance(stamp, bool):
        return None
    if type(stamp) is int:
        return stamp
    if isinstance(stamp, float):
        if not math.isfinite(stamp):
            return None
        try:
            return int(stamp)
        except (OverflowError, ValueError):
            return None
    if isinstance(stamp, str) and stamp:
        try:
            return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _unwrap_envelope(payload):
    """Walk raw/result wrappers until a transaction+meta body is found."""
    node = payload if isinstance(payload, dict) else {}
    for _ in range(4):
        if not isinstance(node, dict):
            return {}
        if node.get("transaction") is not None or isinstance(node.get("meta"), dict):
            return node
        nxt = node.get("raw") if isinstance(node.get("raw"), dict) else node.get("result")
        if not isinstance(nxt, dict):
            return node
        node = nxt
    return node if isinstance(node, dict) else {}


def _pubkeys_in_order(body):
    tx = body.get("transaction") if isinstance(body.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    ordered = []
    for item in message.get("accountKeys") or ():
        ordered.append(item["pubkey"] if isinstance(item, dict) else item)
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else (
        tx.get("meta") if isinstance(tx.get("meta"), dict) else {}
    )
    extra = meta.get("loadedAddresses") if isinstance(meta.get("loadedAddresses"), dict) else {}
    ordered.extend(extra.get("writable") or ())
    ordered.extend(extra.get("readonly") or ())
    return ordered, meta if isinstance(meta, dict) else {}


def _amt(row):
    try:
        return int(((row or {}).get("uiTokenAmount") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0


def _owned_index(row, pubkeys, wallet):
    if not isinstance(row, dict):
        return None
    idx = row.get("accountIndex")
    if type(idx) is not int:
        return None
    owner = row.get("owner")
    if owner == wallet:
        return idx
    if not owner and 0 <= idx < len(pubkeys) and pubkeys[idx] == wallet:
        return idx
    return None


def _ix_program_id(ix, pubkeys):
    if not isinstance(ix, dict):
        return None
    if ix.get("programId"):
        return ix["programId"]
    idx = ix.get("programIdIndex")
    if type(idx) is int and 0 <= idx < len(pubkeys):
        return pubkeys[idx]
    parsed = ix.get("parsed")
    if isinstance(parsed, dict) and parsed.get("programId"):
        return parsed["programId"]
    return None


def _ix_name_values(ix):
    if not isinstance(ix, dict):
        return []
    parsed = ix.get("parsed") if isinstance(ix.get("parsed"), dict) else {}
    return [
        ix.get("name"),
        ix.get("instruction"),
        ix.get("type"),
        parsed.get("type"),
        parsed.get("instruction"),
        parsed.get("name"),
    ]


def _ix_looks_like_swap(ix):
    return any(value and SWAP_IX_NAME_RE.search(str(value)) for value in _ix_name_values(ix))


def _ix_discriminator(ix):
    data = ix.get("data") if isinstance(ix, dict) else None
    payload = _b58decode(data)
    return payload[:8] if len(payload) >= 8 else b""


def _ix_looks_like_lp(ix, pubkeys=None):
    program = _ix_program_id(ix, pubkeys or [])
    discs = AUDITOR_LP_DISCS.get(program)
    if not discs:
        return False
    return _ix_discriminator(ix) in discs


def _all_instructions(body, meta):
    tx = body.get("transaction") if isinstance(body.get("transaction"), dict) else {}
    msg = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    for ix in msg.get("instructions") or ():
        yield ix
    for group in meta.get("innerInstructions") or ():
        if isinstance(group, dict):
            for ix in group.get("instructions") or ():
                yield ix
        elif isinstance(group, list):
            for ix in group:
                yield ix


def _wallet_owned_token_changed(meta, wallet):
    delta = Counter()
    for row in meta.get("preTokenBalances") or ():
        if isinstance(row, dict) and row.get("owner") == wallet and row.get("mint"):
            delta[row["mint"]] -= _amt(row)
    for row in meta.get("postTokenBalances") or ():
        if isinstance(row, dict) and row.get("owner") == wallet and row.get("mint"):
            delta[row["mint"]] += _amt(row)
    return {mint: qty for mint, qty in delta.items() if qty}


def _auditor_wallet_signed(body, pubkeys, wallet):
    tx = body.get("transaction") if isinstance(body.get("transaction"), dict) else {}
    msg = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    header = msg.get("header") if isinstance(msg.get("header"), dict) else {}
    needed = header.get("numRequiredSignatures")
    if type(needed) is not int or needed < 1:
        needed = 1
    static = []
    for key in msg.get("accountKeys") or ():
        static.append(key["pubkey"] if isinstance(key, dict) else key)
    keys = static or list(pubkeys)
    return bool(wallet) and wallet in keys[:needed]


def _has_lp_signal(body, meta):
    pubkeys, _ = _pubkeys_in_order(body)
    if any(_ix_looks_like_lp(ix, pubkeys) for ix in _all_instructions(body, meta)):
        return True
    programs = {
        _ix_program_id(ix, pubkeys) for ix in _all_instructions(body, meta)
    }
    logs = " ".join(meta.get("logMessages") or [])
    for program, names in AUDITOR_LP_NAMES.items():
        if program not in programs:
            continue
        if any(f"Instruction: {name}" in logs for name in names):
            return True
    return False


def _has_swap_signal(body, pubkeys, meta, changed):
    logs = " ".join(meta.get("logMessages") or [])
    swap_log = _auditor_log_looks_like_swap(logs)
    swap_ix = False
    saw_reviewed = False
    for ix in _all_instructions(body, meta):
        if _ix_looks_like_swap(ix):
            swap_ix = True
        if _ix_program_id(ix, pubkeys) in REVIEWED_SWAP_PROGRAM_IDS:
            saw_reviewed = True
    if _has_lp_signal(body, meta) and not swap_log and not swap_ix:
        return False
    if swap_log or swap_ix:
        return True
    if not (saw_reviewed and changed):
        return False
    # Unknown / log-stripped venue: reviewed swap program plus a material
    # wallet-owned token move. +1-only (LP position NFT / mint) is not a swap.
    # Meteora add/remove-liquidity is excluded above by instruction name.
    if any(abs(qty) > 1 for qty in changed.values()):
        return True
    return any(qty < 0 for qty in changed.values())


def raw_economic_keys_for_tx(record, address):
    """v3: one signed swap-program tx with a wallet-owned token change.

    Orthogonal to the app's rent-aware SOL floor. Unknown venues count when
    logs/instruction names show Swap/Buy/Sell/Route, or a reviewed swap
    program is present with a material wallet-owned token balance change.
    One key per signature.
    """
    if not isinstance(record, dict) or not address:
        return 0
    body = _unwrap_envelope(record)
    pubkeys, meta = _pubkeys_in_order(body)
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return 0
    if not _auditor_wallet_signed(body, pubkeys, address):
        return 0
    changed = _wallet_owned_token_changed(meta, address)
    if not changed:
        return 0
    if not _has_swap_signal(body, pubkeys, meta, changed):
        return 0
    return 1


def _tx_signature(record):
    body = _unwrap_envelope(record)
    if body.get("signature"):
        return body["signature"]
    tx = body.get("transaction") if isinstance(body.get("transaction"), dict) else {}
    sigs = tx.get("signatures") or ()
    return sigs[0] if sigs else None


def _record_unix(record):
    body = _unwrap_envelope(record)
    tx = body.get("transaction") if isinstance(body.get("transaction"), dict) else {}
    stamp = _first_present(
        body.get("blockTime"),
        body.get("block_time"),
        body.get("timestamp"),
        tx.get("blockTime"),
        tx.get("timestamp"),
    )
    return _event_unix({"timestamp": stamp})


def raw_economic_trades_by_utc_day(records, address):
    """One signed swap-program tx per signature, bucketed by UTC day."""
    by_sig = {}
    anonymous = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        sig = _tx_signature(record)
        if sig:
            by_sig.setdefault(sig, record)
        else:
            anonymous.append(record)
    counts = {}
    incomplete = 0
    for record in list(by_sig.values()) + anonymous:
        n_keys = raw_economic_keys_for_tx(record, address)
        if n_keys <= 0:
            continue
        unix = _record_unix(record)
        if unix is None:
            incomplete += n_keys
            continue
        try:
            day = datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            incomplete += n_keys
            continue
        counts[day] = counts.get(day, 0) + n_keys
    return counts, incomplete


def economic_trades_by_utc_day(events):
    """Same decoded bot-rule count as the app. Does not import scanner/."""
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
        stamp = _event_unix(event)
        if stamp is None:
            continue
        seen.add(key)
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        counts[day] += 1
    return dict(counts)


def combined_economic_trades_by_utc_day(events, records, address):
    decoded = economic_trades_by_utc_day(events)
    raw, _incomplete = raw_economic_trades_by_utc_day(records, address)
    days = set(decoded) | set(raw)
    return {day: max(int(decoded.get(day) or 0), int(raw.get(day) or 0)) for day in days}


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
        by_unit[unit] = by_unit.get(unit, Decimal("0")) + episode_profit_amount(item)
    canonical = {unit: _canonical(value) for unit, value in by_unit.items()}
    if len(canonical) == 1:
        unit = next(iter(canonical))
        return canonical[unit], unit, canonical
    return None, "mixed", canonical


AUDITOR_COVERAGE_GATE_VERSION = "result-relevant-v1"
AUDITOR_QUOTE_MINTS = frozenset({WSOL, USDC, USDT, "SOL"})


def _auditor_record_signature(record, raw):
    signature = record.get("signature") if isinstance(record, dict) else None
    if isinstance(raw, dict):
        signature = signature or raw.get("signature")
        tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
        sigs = tx.get("signatures") or []
        if not signature and sigs:
            signature = sigs[0]
    return signature


def _auditor_block_time(record, raw):
    for source in (raw, record):
        if not isinstance(source, dict):
            continue
        stamp = source.get("blockTime")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return int(stamp)
    return None


def _auditor_touched_mints(raw, address):
    """Owner-field mint set. Does not use the app's key-index path.

    Wallet-not-in-keys still reads owner rows. Malformed rows return None.
    """
    if not isinstance(raw, dict) or not address:
        return None
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        return None
    pre_token = meta.get("preTokenBalances")
    post_token = meta.get("postTokenBalances")
    if not isinstance(pre_token, list) or not isinstance(post_token, list):
        return None
    pre, post = {}, {}
    for rows, dest in ((pre_token, pre), (post_token, post)):
        for row in rows:
            if not isinstance(row, dict):
                return None
            amount = (row.get("uiTokenAmount") or {}).get("amount")
            mint = row.get("mint")
            if mint in (None, "") or amount in (None, ""):
                return None
            if row.get("owner") != address:
                continue
            try:
                dest[mint] = dest.get(mint, Decimal("0")) + Decimal(str(amount))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                return None
    touched = {mint for mint in set(pre) | set(post) if pre.get(mint, Decimal("0")) != post.get(mint, Decimal("0"))}
    keys = _keys(raw)
    if address in keys:
        native, _paid = _native_delta(raw, address, keys)
        wsol = Decimal("0")
        token_deltas, _pre, _post = _owned_token_deltas(raw, address)
        wsol = token_deltas.get(WSOL, Decimal("0"))
        if native + wsol != 0:
            touched.add("SOL")
        touched.update(mint for mint, qty in token_deltas.items() if qty != 0)
    return frozenset(touched)


def _auditor_has_non_infra_outer(raw, keys):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        program = _program(instruction, keys)
        if program and program not in _INNER_INFRA:
            return True
    return False


def _auditor_opposite_deltas(raw, address, keys):
    token_deltas, _pre, _post = _owned_token_deltas(raw, address)
    native, _paid = _native_delta(raw, address, keys)
    wsol = token_deltas.pop(WSOL, Decimal("0"))
    sol = native + wsol
    deltas = dict(token_deltas)
    if sol != 0:
        deltas["SOL"] = sol
    positives = [mint for mint, qty in deltas.items() if qty > 0]
    negatives = [mint for mint, qty in deltas.items() if qty < 0]
    return bool(positives and negatives)


def _auditor_swap_like(raw, address, reconstructed):
    if reconstructed:
        return True
    if not isinstance(raw, dict):
        return False
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return False
    keys = _keys(raw)
    return _auditor_has_non_infra_outer(raw, keys) and _auditor_opposite_deltas(raw, address, keys)


def _auditor_lineage_mints(trades, episodes, report_start, report_end):
    lineage = set()
    for trade in trades or []:
        mint = trade.get("mint")
        if not mint or mint in AUDITOR_QUOTE_MINTS:
            continue
        if trade.get("kind") not in ("sell", "flatten"):
            continue
        timestamp = trade.get("timestamp")
        if timestamp is not None and report_start <= timestamp < report_end:
            lineage.add(mint)
    for item in episodes or []:
        mint = item.get("mint")
        if mint and mint not in AUDITOR_QUOTE_MINTS:
            lineage.add(mint)
    return frozenset(lineage)


def result_relevant_coverage(address, records, trades, episodes, report_start=None, report_end=None):
    """Independent R. Sums reconstructed trades vs unreadables; does not import the app."""
    start = REPORT_START if report_start is None else report_start
    end = REPORT_END if report_end is None else report_end
    by_sig = {}
    for trade in trades or []:
        signature = trade.get("signature")
        if signature:
            by_sig.setdefault(signature, []).append(trade)
    lineage = _auditor_lineage_mints(trades, episodes, start, end)
    signatures = []
    decoded_n = 0
    unsupported_n = 0
    decoded_value = {"SOL": Decimal("0"), "USDC": Decimal("0"), "USDT": Decimal("0")}
    unsupported_value = {"SOL": Decimal("0"), "USDC": Decimal("0"), "USDT": Decimal("0")}
    for record in records or []:
        raw = _unwrap(record)
        signature = _auditor_record_signature(record, raw)
        timestamp = _auditor_block_time(record, raw)
        mints = _auditor_touched_mints(raw, address)
        reconstructed = by_sig.get(signature) or []
        swap_like = _auditor_swap_like(raw, address, reconstructed)
        meta = raw.get("meta") if isinstance(raw, dict) else {}
        failed = isinstance(meta, dict) and meta.get("err") is not None
        in_report = timestamp is not None and start <= timestamp < end
        before_end = timestamp is not None and timestamp < end
        # Independent include rule (not the app reason ladder):
        # failed txs are idle; reconstructed always; swap-like only in-window
        # (out-of-window non-lineage swaps stay out); lineage / unknown mints
        # / in-window unexplained native still enter.
        include = False
        if failed:
            include = False
        elif reconstructed:
            include = True
        elif in_report and swap_like:
            include = True
        elif timestamp is None:
            include = True
        elif before_end and mints is not None and (mints - AUDITOR_QUOTE_MINTS) & lineage:
            include = True
        elif mints is None:
            include = True
        elif in_report and mints - AUDITOR_QUOTE_MINTS:
            include = True
        elif in_report and "SOL" in mints:
            keys = _keys(raw) if isinstance(raw, dict) else []
            native, _paid = _native_delta(raw, address, keys) if keys else (Decimal("0"), False)
            try:
                fee = Decimal(str((meta or {}).get("fee") or 0))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                fee = Decimal("0")
            if native + fee != 0:
                include = True
        if not include:
            continue
        signatures.append(signature)
        if reconstructed:
            decoded_n += 1
            for trade in reconstructed[:1]:
                asset = trade.get("settlement_asset") or "SOL"
                if asset == "USDC" and trade.get("consideration_usdc") not in (None, ""):
                    decoded_value["USDC"] += abs(Decimal(str(trade["consideration_usdc"])))
                elif asset == "USDT" and trade.get("consideration_usdt") not in (None, ""):
                    decoded_value["USDT"] += abs(Decimal(str(trade["consideration_usdt"])))
                elif trade.get("consideration_sol") not in (None, ""):
                    decoded_value["SOL"] += abs(Decimal(str(trade["consideration_sol"])))
        else:
            # DC-2: every included row is counted, including lineage-only.
            unsupported_n += 1
            token_deltas, _pre, _post = _owned_token_deltas(raw, address) if isinstance(raw, dict) else ({}, {}, {})
            usdc = abs(token_deltas.get(USDC, Decimal("0")))
            usdt = abs(token_deltas.get(USDT, Decimal("0")))
            native, _paid = _native_delta(raw, address, _keys(raw)) if isinstance(raw, dict) else (Decimal("0"), False)
            wsol = token_deltas.get(WSOL, Decimal("0"))
            sol = abs(native + wsol) / LAMPORTS
            if usdc >= Decimal("1000000"):
                unsupported_value["USDC"] += usdc / Decimal("1000000")
            if usdt >= Decimal("1000000"):
                unsupported_value["USDT"] += usdt / Decimal("1000000")
            if sol > Decimal("0.003"):
                unsupported_value["SOL"] += sol
    denom = decoded_n + unsupported_n
    empty = not signatures or denom == 0
    by_count = None if not denom else _canonical(Decimal(unsupported_n) / Decimal(denom))
    by_consideration = {}
    value_shares = []
    for asset in ("SOL", "USDC", "USDT"):
        total = decoded_value[asset] + unsupported_value[asset]
        if total:
            share = unsupported_value[asset] / total
            by_consideration[asset] = _canonical(share)
            value_shares.append(Decimal("1") - share)
    count_share = None if by_count is None else Decimal("1") - Decimal(str(by_count))
    value_share = min(value_shares) if value_shares else None
    gate_passed = (
        not empty
        and count_share is not None
        and value_share is not None
        and count_share >= Decimal("0.99")
        and value_share >= Decimal("0.99")
    )
    return {
        "version": AUDITOR_COVERAGE_GATE_VERSION,
        "signatures": [item for item in signatures if item],
        "size": len([item for item in signatures if item]),
        "empty": empty,
        "lineage_mints": sorted(lineage),
        "unsupported_swap_share": {"by_count": by_count, "by_consideration": by_consideration},
        "coverage_count_share": None if empty or count_share is None else _canonical(count_share),
        "coverage_value_share": None if empty or value_share is None else _canonical(value_share),
        "count_share": None if empty or count_share is None else _canonical(count_share),
        "value_share": None if empty or value_share is None else _canonical(value_share),
        "gate_passed": gate_passed,
        "decoded_n": decoded_n,
        "unsupported_n": unsupported_n,
        "denominator": denom,
        "method": "reconstructed_trades_vs_unreadables_and_owned_deltas",
        "PRODUCT_READY": False,
    }


def audit_address(address, pages):
    records = _load_pages(address, pages)
    trades = []
    for record in records:
        event = reconstruct_record(record, address)
        if event:
            trades.append(event)
    episodes, unresolved, known_sales, omitted_losing = _fifo(trades)
    wins = sum(1 for item in episodes if episode_profit_amount(item) > 0)
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
    by_day = combined_economic_trades_by_utc_day(trades, records, address)
    max_day = max(by_day.values()) if by_day else 0
    max_on = max(by_day, key=lambda item: (by_day[item], item)) if by_day else None
    relevant = result_relevant_coverage(address, records, trades, episodes)
    return {
        "address": address,
        "records": len(records),
        "independently_reconstructed_trades": len(trades),
        "bot_rule_definition": BOT_RULE_DEFINITION,
        "economic_trades_by_utc_day": by_day,
        "max_economic_trades_in_one_day": max_day,
        "max_economic_trades_on": max_on,
        "max_economic_trades_threshold": MAX_ECONOMIC_TRADES_PER_UTC_DAY,
        "over_max_economic_trades": bool(max_day) and max_day > MAX_ECONOMIC_TRADES_PER_UTC_DAY,
        "bot_rule": GT_ECONOMIC_TRADES_RULE,
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
        "result_relevant": relevant,
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
