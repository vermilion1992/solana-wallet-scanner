"""Bounded, evidence-linked spot swap reconstruction and current token checks.

One successful outer instruction from a recognized deployed spot venue is needed.
Its authority must be the investigated wallet. Net balances are then used to
collapse routed legs, never to decide that arbitrary movements constitute a swap.
A signed transaction that contains an instruction from NET_BALANCE_SWAP_PROGRAMS
may also reconstruct as a single swap when, after fee/rent/wSOL/tip
normalisation, the wallet net is exactly one asset out and one asset in (or a
reviewed stable conversion). Ambiguous nets stay unsupported.
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
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import base64

from .accounting import canonical, raw_quantity, decimal
from .decoder import SYSTEM_ID, COMPUTE_ID, ASSOCIATED_ID, TOKEN_IDS, MEMO_IDS

WSOL = 'So11111111111111111111111111111111111111112'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
USDT = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
QUOTE_MINTS = frozenset({USDC, USDT})
QUOTE_ASSET = {USDC: 'USDC', USDT: 'USDT'}
# Reviewed quote stables are USDC and USDT only. SOL↔USDC/USDT is a
# conversion. SOL↔PYUSD (2b1kV6Dk…), USD1 (USD1ttGY…), USDS (USDSwr9…)
# or any other USD-named mint is an ordinary token trade of that mint.
# Token↔an unreviewed stable is unresolved (two non-SOL assets).
# Unknown quote is unresolved, never 0. No unsourced FX into SOL.
REVIEWED_STABLECOIN_RULE = (
    "Reviewed quote stables: USDC and USDT only. SOL↔reviewed stable is a "
    "conversion, not a token position. Token↔reviewed stable is a buy/sell "
    "settled in that stable. PYUSD, USD1, USDS and any other USD-named mint "
    "are not reviewed quotes: SOL↔them is an ordinary token trade; "
    "token↔them is unresolved. Unknown quote is unresolved, never 0."
)
PYUSD = '2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo'
USD1 = 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB'
USDS = 'USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA'
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
DFLOW_DST = 'dst5MGcFPoBeREFAA5E3tU5ij8m5uVYwkzkSAbsLbNo'
FLASHX = 'FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9'
TITAN = 'T1TANpTeScyeqVzzgNViGDNrkQ6qHz9KrSBS4aNXvGT'
TERM9Y = 'term9YPb9mzAsABaqN71A4xdbxHmpBNZavpBiQKZzN3'
ROUTEU = 'routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS'
OKX_DEX_V2 = '6m2CDdhRgxpH4WjvdzxAYbGxwdGUz5MziiL5jek2kBma'
GMGN = 'GMGNreQcJFufBiCTLDBgKhYEfEe9B454UjpDr5CaSLA1'
# Observed PumpSwap buy router (jXt 2EtPn1a61imQ): outer Buy then inner PumpSwap Buy.
DGMG = 'DGMgNKpqygARV2pHZfW4kNQSHT9F3Ly2BKWqvpYrAg5C'
PHOTON = '99vQwtBwYtrqqD9YSXbdum3KBdxPAVxYTaQ3cfnJSrN2'
METEORA_DLMM = 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'
PUMP_FEE_PROGRAM = 'pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ'
RFQ_FILL = '61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH'
TOKEN_2022_ID = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
# Lighthouse assertions. Not a venue. Bundled with swaps; never a trade.
LIGHTHOUSE = 'L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95'
# Exact observed RFQ Fill top-level fee recipient. Not a general fee sink.
RFQ_FEE_FILL_ACCOUNT = '9PnYDCTJ5B4mJJMPvjCZ97L6ZBcti48CYgxv5QU1mV5G'
OKX_SWAPTOC = bytes.fromhex('bbc9d433109bec3c')
OKX_SWAPTOB = bytes.fromhex('aa2955b184501f35')
RFQ_FILL_DISC = bytes.fromhex('a860b7a35c0a28a0')
DFLOW_SWAP = bytes.fromhex('f8c69e91e17587c8')
DFLOW_SWAP_WITH_DESTINATION = bytes.fromhex('a8ac184dc59c8765')
DFLOW_SWAP2 = bytes.fromhex('414b3f4ceb5b5b88')
DFLOW_WRAP = bytes.fromhex('2f3e9bac83cd25c9')
DFLOW_UNWRAP = bytes.fromhex('63280e692d6bacc9')
DFLOW_TRANSFER_FEE = bytes.fromhex('81a4c415b130b4a2')
DFLOW_TRANSFER_TO_SPONSOR = bytes.fromhex('9bb38297c48bfda3')
DFLOW_DST_FULFILL = bytes.fromhex('3dd627f841d49924')
GMGN_SWAP = bytes.fromhex('f8c69e91e17587c8')
PHOTON_SWAP = bytes.fromhex('0b9c60da27a3b413')
PHOTON_SWAP_ALT = bytes.fromhex('0d9e0ddf5fd51c06')
DLMM_SWAP2 = bytes.fromhex('414b3f4ceb5b5b88')
# Photon and DFlow DST layouts are pinned below but stay unsupported: every
# attached real tx fails balance-delta reconciliation (no opposing SOL or
# multi-asset). FLASHX wraps (10-byte 0x01) and other non-0x00 opcodes are
# not swaps; only the later 0x00 swap instruction is routed. B311 is a
# multi-asset wrapper and is deliberately unreviewed.
REVIEWED_OUTER_VENUES = (
    JUPITER, PUMP, PUMP_SWAP, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL,
    METEORA_DAMM_V2, RFQ_FILL, OKX_DEX_ROUTER, DFLOW,
    FLASHX, GMGN, DGMG, METEORA_DLMM,
)
UNSUPPORTED_PINNED_OUTER = (PHOTON, DFLOW_DST)
# Venue-agnostic net-balance path. CLMM is included here even though it is
# not a REVIEWED_OUTER_VENUES layout: direct CLMM outers have no pinned
# discriminator in _route. Jupiter/Whirlpool/AMMv4 stay in both sets so an
# unknown discriminator can still reconstruct when the net is unambiguous.
LAMPORTS = Decimal(1_000_000_000)
DECODER_VERSION = 'spot-v29-jup6-exact-out-v2-v1'
NET_BALANCE_INSTRUCTION = 'net_balance'
NET_BALANCE_SOL_DUST_LAMPORTS = 100_000
# Fee/referral SOL residue that may be peeled as cost, never as a third trade leg.
# FLASHX 0.0587 SOL bundled transfers stay above this bound and fail closed.
NET_BALANCE_COST_SOL_LAMPORTS = 20_000_000
NET_BALANCE_REFERRAL_BPS = 200
SWAPTOB_UNSUPPORTED_REASON = (
    'proVF4p SwapTob is reviewed: discriminator aa2955b184501f35, payer at 0, '
    'source_token_account at 1, destination_token_account at 2 from the '
    'published OKX DEX v2 layout. Remaining accounts are hops, not user legs. '
    'Unknown OKX discriminators stay unsupported. Balance changes alone do '
    'not prove a swap.'
)
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
    (JUPITER, 'exact_out_route_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'discriminator': '9d8ab85215f4f324',
        'scope': 'Official exact_out_route_v2 discriminator; same wallet/user-token indices as route_v2; fail-closed if truncated',
    },
    (JUPITER, 'shared_accounts_exact_out_route_v2'): {
        'state': 'PINNED_OFFICIAL_LAYOUT',
        'discriminator': '3560e5cad8bbfa18',
        'scope': 'Official shared_accounts_exact_out_route_v2 discriminator; authority index 1 and user token accounts 2/5; fail-closed if truncated',
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


def _flashx_is_wrap(instruction):
    """FLASHX 10-byte 0x01 (and other short 0x01) instructions are wraps, not swaps."""
    try:
        payload = _data(instruction.get('data'))
    except (ValueError, TypeError, KeyError):
        return False
    return bool(payload) and payload[0] == 1


def _flashx_is_reviewed_swap(instruction, keys):
    """True only for the observed 0x00 FLASHX swap (wallet at 1, ≥20 accounts)."""
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return False
    return bool(payload) and payload[0] == 0 and len(payload) >= 16 and len(accounts) >= 20


def _dflow_is_reviewed_swap(instruction, keys):
    """True only for pinned DFlow swap discriminators. Wrap/setup siblings are not swaps."""
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return False
    if payload[:8] == DFLOW_SWAP_WITH_DESTINATION and len(payload) >= 16 and len(accounts) >= 9:
        return True
    if payload[:8] == DFLOW_SWAP and len(payload) >= 16 and len(accounts) >= 6:
        return True
    # Swap2: same wallet-at-3 prefix as Swap. Run-7 blocked 654 txs on this disc.
    if payload[:8] == DFLOW_SWAP2 and len(payload) >= 16 and len(accounts) >= 6:
        return True
    return False


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


def token_2022_ceiling_fee(amount, bps):
    """Token-2022 transfer fee: ceil(amount * bps / 10_000), no max-fee cap."""
    if bps <= 0:
        return 0
    return (int(amount) * int(bps) + 9999) // 10000


def infer_token_2022_fee_bps_candidates(gross_amounts, withheld):
    """Every uncapped ceiling-formula bps that fits the observed withheld.

    This is not TransferFeeConfig. The Token-2022 on-chain fee also applies a
    maximum-fee cap and selects configuration by epoch. Those fields are not
    in GTA captures, so a numeric fit is not execution-time mint config.
    """
    withheld = int(withheld)
    if withheld < 0 or not gross_amounts:
        return []
    matches = []
    for bps in range(0, 10001):
        if sum(token_2022_ceiling_fee(amount, bps) for amount in gross_amounts) == withheld:
            matches.append(bps)
    return matches


def infer_token_2022_fee_bps(gross_amounts, withheld):
    """Unique uncapped-ceiling bps, or None if ambiguous / no fit.

    A unique fit is still not TransferFeeConfig or execution-time mint config.
    """
    matches = infer_token_2022_fee_bps_candidates(gross_amounts, withheld)
    if len(matches) == 1:
        return matches[0]
    return None


def _header_counts(header, static_len):
    """Match compiled_instructions.py:150-185 header bounds."""
    if not isinstance(header, dict):
        return None
    required = header.get('numRequiredSignatures')
    readonly_signed = header.get('numReadonlySignedAccounts')
    readonly_unsigned = header.get('numReadonlyUnsignedAccounts')
    if (any(type(value) is not int or isinstance(value, bool)
            for value in (required, readonly_signed, readonly_unsigned)) or
            not 1 <= required <= static_len or not 0 <= readonly_signed < required or
            not 0 <= readonly_unsigned <= static_len - required):
        return None
    return required, readonly_signed, readonly_unsigned


def _message_signers(message, keys):
    """Message signers from parsed flags or header.numRequiredSignatures.

    Cross-checks parsed signer/writable flags against the message header the
    same way compiled_instructions.py:150-185 does. Conflicting flags yield no
    signers. Does not invent signers. Outer ATA still requires the funding
    source to be one of these keys; that check stays in normalize_instruction.
    """
    entries = message.get('accountKeys')
    header = message.get('header') if isinstance(message.get('header'), dict) else {}
    header_present = bool(header)
    if isinstance(entries, list) and entries and all(isinstance(item, dict) for item in entries):
        if header_present:
            counts = _header_counts(header, len(entries))
            if counts is None:
                return set()
            required, readonly_signed, readonly_unsigned = counts
            for index, entry in enumerate(entries):
                writable = (index < required - readonly_signed if index < required else
                            index < len(entries) - readonly_unsigned)
                if entry.get('signer') is not (index < required) or entry.get('writable') is not writable:
                    return set()
            flagged = [entry.get('pubkey') for entry in entries[:required]]
        else:
            flagged = [item.get('pubkey') for item in entries if item.get('signer') is True]
        if flagged and all(isinstance(key, str) and key for key in flagged):
            return set(flagged)
        return set()
    counts = _header_counts(header, len(keys))
    if counts is None:
        return set()
    required, _readonly_signed, _readonly_unsigned = counts
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
        if name is None:
            for candidate, auth_idx, owned, min_accounts in (
                ('route_v2', 0, (1, 2), 10),
                ('exact_out_route_v2', 0, (1, 2), 10),
                ('shared_accounts_route_v2', 1, (2, 5), 12),
                ('shared_accounts_exact_out_route_v2', 1, (2, 5), 12),
            ):
                if payload[:8] == _anchor(candidate):
                    if len(payload) < 28 or len(accounts) < min_accounts:
                        raise ValueError(f'Jupiter {candidate} layout is absent or truncated')
                    name, authority, owned_positions = candidate, auth_idx, owned
                    break
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
    elif program == OKX_DEX_ROUTER:
        # Official OKX DEX v2 SwapTob: payer, source_token_account,
        # destination_token_account, source_mint, destination_mint, …
        if payload[:8] == OKX_SWAPTOB and len(payload) >= 61 and len(accounts) >= 5:
            name, authority, owned_positions = 'SwapTob', 0, (1, 2)
    elif program == DFLOW:
        # Official DFlow Aggregator v4. Wallet is account 3 on the observed swap.
        # Wrap 2f3e9bac / Unwrap 63280e69 / TransferFee / TransferToSponsor are
        # not swaps and are skipped before _route.
        if payload[:8] == DFLOW_SWAP_WITH_DESTINATION and len(payload) >= 16 and len(accounts) >= 9:
            name, authority, owned_positions = 'swap_with_destination', 3, (4,)
        elif payload[:8] == DFLOW_SWAP and len(payload) >= 16 and len(accounts) >= 6:
            name, authority, owned_positions = 'swap', 3, ()
        elif payload[:8] == DFLOW_SWAP2 and len(payload) >= 16 and len(accounts) >= 6:
            name, authority, owned_positions = 'swap2', 3, ()
    elif program == DFLOW_DST:
        # Native Flow FulfillOrder. Wallet at 3 on the attached CfNx page.
        if payload[:8] == DFLOW_DST_FULFILL and len(payload) >= 16 and len(accounts) >= 4:
            name, authority, owned_positions = 'FulfillOrder', 3, ()
    elif program == FLASHX:
        # Observed Axiom FLASHX routed swap: payload starting 0x00 with
        # wallet at index 1. Non-swap opcodes (wraps, 0x05, …) are skipped
        # before _route.
        if len(payload) >= 16 and payload[0] == 0 and len(accounts) >= 20:
            name, authority, owned_positions = 'flashx_swap', 1, ()
    elif program == DGMG:
        # PumpSwap buy/sell router. Same discriminators as Pump; wallet at 1
        # (PumpSwap user). Inner PumpSwap Buy is not a second outer.
        if payload[:8] == _anchor('buy') and len(payload) >= 24 and len(accounts) >= 7:
            name, authority, owned_positions, expected = 'buy', 1, (5, 6), 'buy'
        elif payload[:8] == _anchor('sell') and len(payload) >= 24 and len(accounts) >= 7:
            name, authority, owned_positions, expected = 'sell', 1, (5, 6), 'sell'
        elif payload[:8] == _anchor('buy_exact_quote_in') and len(payload) >= 24 and len(accounts) >= 7:
            name, authority, owned_positions, expected = 'buy_exact_quote_in', 1, (5, 6), 'buy'
    elif program == GMGN:
        if payload[:8] == GMGN_SWAP and len(payload) >= 24 and len(accounts) >= 8:
            name, authority, owned_positions = 'gmgn_swap', 0, ()
    elif program == PHOTON:
        if payload[:8] in (PHOTON_SWAP, PHOTON_SWAP_ALT) and len(payload) >= 16 and len(accounts) >= 5:
            name, authority, owned_positions = 'photon_swap', 1, ()
    elif program == METEORA_DLMM:
        if payload[:8] == DLMM_SWAP2 and len(payload) >= 16 and len(accounts) > 10:
            name, authority, owned_positions = 'swap2', 10, ()
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


def _close_authority(info):
    """Close authority is `owner`, or a sole-signer `multisigOwner`."""
    owner = info.get('owner')
    if owner:
        return owner
    multi = info.get('multisigOwner')
    signers = info.get('signers') or []
    if multi and signers and all(item == multi for item in signers):
        return multi
    return owner


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
        if close_program != token_program or _close_authority(close) != address or close.get('destination') != address:
            raise ValueError('Temporary wrapped SOL closure and rent refund must belong to the investigated wallet')
        if not creation_position < initialization_position < route_position < close_position:
            # DFlow Swap/Swap2 wrap SOL as a CPI inside the swap (create/init
            # after the outer route in the flattened list) and close via an
            # inner close or a sibling UnwrapSol. Still require one wallet-
            # funded create/init and one wallet-refunded close.
            dflow_in_swap_wrap = (
                route.get('program') == DFLOW
                and route_position < creation_position < initialization_position < close_position
            )
            if not dflow_in_swap_wrap:
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


def _episode_rent_exclusion(flat, keys, before, after, address, skip_accounts):
    """Wallet-owned still-open token rent only. See WALLET_PAID_RENT_RULE.

    Independent of tools/independent_episode_audit.py (no shared helper).
    Venue PDAs, other-owner ATAs, and router-fee accounts stay in
    consideration. Closed-in-tx remaining native is 0. skip_accounts are
    already rent-corrected wallet token accounts.
    """
    del flat, keys, before, after, address
    # Wallet-owned still-open token rent is excluded by rent_correction
    # (accounts already in `owned`) and `_verified_new_token_account_rent`.
    # Venue PDAs / other-owner ATAs stay in consideration (WALLET_PAID_RENT_RULE).
    del skip_accounts
    return 0


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
    OKX_DEX_ROUTER, METEORA_DAMM_V2, DFLOW, DFLOW_DST, RFQ_FILL,
    FLASHX, GMGN, DGMG, PHOTON, METEORA_DLMM,
})
_REVIEWED_ALLOCATE_SPACES = frozenset({137, 165, 170})


# Infra + reviewed venues + well-known hop AMMs. An unknown inner program
# that touches a wallet-owned account blocks (D3). P&L stays wallet-delta
# guarded; this is provenance + fail-closed, not a silent allow.
RAYDIUM_CLMM = 'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK'
NET_BALANCE_SWAP_PROGRAMS = frozenset({
    *REVIEWED_OUTER_VENUES,
    RAYDIUM_CLMM,
    TITAN, TERM9Y, ROUTEU, OKX_DEX_V2,
})
# Published hop AMMs seen under Jupiter/DFlow. A random program id still blocks (D3).
WELL_KNOWN_INNER_AMMS = frozenset({
    RAYDIUM_CLMM,
    'PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY',  # Phoenix
    'SCoRcH8c2dpjvcJD6FiPbCSQyQgu3PcUAWj2Xxx3mqn',  # Sanctum Infinity
    'ALPHAQmeA7bjrVuccPsYPiCvsi428SNwte66Srvs4pHA',  # AlphaQ
    'ZERor4xhbUycZ6gb9ntrhqscUcZmAbQDjEAtCf4hbZY',  # ZeroFi
    'BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi',  # BisonFi
    'SoLFiHG9TfgtdUXUjWAxi3LtvYuFyDLVhBWxdMZxyCe',  # SolFi
    'obriQD1zbpyLz95G5n7nJe6a4DPjpFwa5XYPoNm113y',  # Obric
    '2wT8Yq49kHgDzXuPxZSaeLaH1qJgCwzzjYyvKZlYNVpj',  # Lifinity v2
    'EewxydAPCCVuNEyrVN68XT4NWAI1uCml1p55i1BPVsbJ',  # Lifinity
    'srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX',  # OpenBook
    'opnb2LAfJYbRMAHHvqjCwQxanZn7ReEHp1k81EohpZb',  # OpenBook v2
    'FLUXubRmkEi2q6K3Y9kBPg9248ggaZVsoSFhtJHSrm1X',  # FluxBeam
    'Eo7WjKq67rjJQSZxS6z3YcapmYde3M6t4gadxJtdEJge',  # GooseFX
    '6MLxLqiXaaSUpkgMnWDTuejNZEz3kE7k2woyHGVFw319',  # Crema
    'HyaB3W9q6XdA5xwpU4XnSZV94htfmbmqJXZcEbRaJueZ',  # Invariant
    'SwaPpA9LAaLfeLi3a68M4DjnLqgKzHa7VMEBUNHzMeU',  # Token Swap
    'MERLuDFBMmsHnszOkfP1zZuj7bK1uAmo4BqTKKQs',  # Mercurial
    'SSwpkEEcbUqx4vtoEByFjSkhKdCT862DNVb52nZg1UZ',  # Saber
    '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin',  # Serum DEX
    'BSwp6bEBihVLdqJRK3PkMH2nNzQ4K3CwbGoiJ2mr8BEf',  # Bonkswap
    'TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH',  # Tessera
    # Published HumidiFi AMM (swaps crate / orbmarkets / explorer).
    # HpNfyc2… was an earlier mis-pin and is kept so already-reviewed
    # hops do not regress; 9H6tua7 is the live program id.
    '9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp',  # HumidiFi
    'HpNfyc2Saw7RKkQd8nEL4khUcuPhQ7WwY1B2qjx8jxFq',  # legacy HumidiFi pin
    'goonuddtQRrWqqn5nFyczVKaie28f3kDkHWkHtURSLE',  # GoonFi
    '3TK9D8aoBFYjYZtKCjciPrVrRStsnvo7KmpcJqDavpaU',
    'MNFSTqtC93rEfYHB6hF82sKdZpUDFWkViLByLd1k1Ms',  # Manifest
    'B72M6nyCLFgWiJtAN4naUTminMiTmyGcEqQHXwVeRdht',
    'DRVSpZ2YUYYKgZP8XtLhAGtT1zYSCKzeHfb4DgRnrgqD',
    'riptK81hDxhe5pW5jSzSM9iRA8azgEgLJ4dXkPtBS7j',
    # Eco SDK svm/venues/obsidian OBSIDIAN_PROGRAM_ID (constant-product AMM).
    'HBVw6bZtcCaezhcBrmfyXBSBRWCdv72271xQ4GPvms2z',
    # Eco SDK svm/venues/gatorswap GATORSWAP_PROGRAM_ID (constant-product AMM).
    'gatorLx9aC1e5ZWAXscv5QRKiLXnLPLXjftVc81h1Hr',
    # Aquifer DEX hop AMM. Decode is wallet-delta, not Aquifer internals.
    'AQU1FRd7papthgdrwPTTq5JacJh8YtwEXaBfKU3bTz45',
})
REVIEWED_INNER_PROGRAMS = frozenset({
    SYSTEM_ID, COMPUTE_ID, ASSOCIATED_ID, *TOKEN_IDS, *MEMO_IDS, LIGHTHOUSE,
    *REVIEWED_OUTER_VENUES, *UNSUPPORTED_PINNED_OUTER, PUMP_FEE_PROGRAM,
    *WELL_KNOWN_INNER_AMMS,
})
_INNER_INFRA = frozenset({
    SYSTEM_ID, COMPUTE_ID, ASSOCIATED_ID, *TOKEN_IDS, *MEMO_IDS, LIGHTHOUSE,
})


def _instruction_account_keys(instruction, keys):
    try:
        return set(_accounts(instruction, keys))
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    found = set()
    if isinstance(info, dict):
        for field in (
            'source', 'destination', 'account', 'newAccount', 'owner',
            'authority', 'wallet', 'mint', 'payer',
        ):
            value = info.get(field)
            if isinstance(value, str) and value:
                found.add(value)
    return found


def _reviewed_inner_venues(flat, keys, route, owned, address):
    """Record inner program ids; block unknown inners that touch wallet assets."""
    venues = []
    seen = set()
    wallet_assets = {address, *owned}
    route_index = route.get('index')
    for outer, _path, instruction, nested in flat:
        if not nested or outer != route_index:
            continue
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program in _INNER_INFRA:
            continue
        if program not in seen:
            seen.add(program)
            venues.append({'program': program})
        if program in REVIEWED_INNER_PROGRAMS:
            continue
        touched = _instruction_account_keys(instruction, keys)
        if touched.intersection(wallet_assets):
            return venues, (
                'Unknown inner program touches a wallet-owned account; '
                f'inner venue {program} is not on the reviewed inner allowlist'
            )
    return venues, None


WALLET_PAID_RENT_RULE = (
    "Wallet-paid account rent (owned vs not-owned; closed vs still open). "
    "A System/ATA create funded by the investigated wallet is classified by "
    "the SPL token owner (not the program owner). Closed in this transaction "
    "with rent returned to the wallet nets out (remaining native is 0). "
    "Still-open and token owner == wallet is recoverable ATA/wSOL rent and "
    "is excluded from swap consideration. Still-open and not wallet-owned "
    "(venue PDA, other-owner ATA, router-fee account) stays in consideration. "
    "Unproved owner is treated as not wallet-owned (fail closed: keep in cost). "
    "Reviewed venue program-account deposits stay on `_episode_rent_exclusion`. "
    "PumpSwap IDL user-volume PDA (buy / buy_exact_quote_in ordinal 20, "
    "derived from the user) is isolated from the swap quote — not "
    "recoverable rent and not consideration. Jupiter-inner PumpSwap "
    "creates are not IDL-located on the outer route and stay in consideration."
)


def _token_account_owner(flat, keys, account):
    """SPL token owner of a created account, or None if unproved.

    Independent of tools/independent_episode_audit.py.
    """
    for _outer, _path, instruction, _nested in flat:
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else {}
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if program == ASSOCIATED_ID and kind in ('create', 'createIdempotent') and info.get('account') == account:
            owner = info.get('wallet') or info.get('owner')
            if owner:
                return owner
        if (
            program in TOKEN_IDS
            and kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3')
            and info.get('account') == account
            and info.get('owner')
        ):
            return info.get('owner')
    return None


def _b58encode(data):
    number = int.from_bytes(data, 'big')
    out = ''
    while number:
        number, rem = divmod(number, 58)
        out = _B58[rem] + out
    pad = 0
    for byte in data:
        if byte:
            break
        pad += 1
    return ('1' * pad) + (out or '1')


def _system_create_unparsed(instruction, keys):
    """Raw System opcode 0 (createAccount). Same layout as compiled_instructions."""
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if len(payload) < 52 or int.from_bytes(payload[:4], 'little') != 0 or len(accounts) < 2:
        return None
    return {
        'source': accounts[0],
        'newAccount': accounts[1],
        'lamports': int.from_bytes(payload[4:12], 'little'),
        'space': int.from_bytes(payload[12:20], 'little'),
        'owner': _b58encode(payload[20:52]),
    }


def _verified_new_token_account_rent(flat, keys, before, after, address, skip_accounts):
    """Exclude still-open wallet-owned token-account rent only.

    See WALLET_PAID_RENT_RULE. Other-owner ATA/wSOL and venue PDAs stay in
    consideration. Subtracted from native before a USDC/USDT trade is treated
    as having a second SOL settlement leg.
    """
    skip = set(skip_accounts or ())
    extra = 0
    seen = set()
    for _outer, _path, instruction, _nested in flat:
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else {}
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        account = None
        if program == ASSOCIATED_ID and kind in ('create', 'createIdempotent') and info.get('source') == address:
            account = info.get('account')
        elif (
            program == SYSTEM_ID
            and kind in ('createAccount', 'createAccountWithSeed')
            and info.get('source') == address
            and info.get('owner') in TOKEN_IDS
        ):
            account = info.get('newAccount')
        elif program == SYSTEM_ID and not kind:
            created = _system_create_unparsed(instruction, keys)
            if created and created.get('source') == address and created.get('owner') in TOKEN_IDS:
                account = created.get('newAccount')
        if not account or account in skip or account in seen or account not in keys:
            continue
        if _token_account_owner(flat, keys, account) != address:
            continue
        index = keys.index(account)
        if index >= len(before) or index >= len(after) or before[index] != 0:
            continue
        net = after[index] - before[index]
        if net > 0:
            extra += net
            seen.add(account)
    return extra


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
            raise ValueError(
                f'System allocate space {space} is not a reviewed account layout'
            )
        return
    owner = info.get('owner')
    if owner not in _REVIEWED_LIFECYCLE_OWNERS:
        raise ValueError('System assign owner is not a reviewed program')


def _iter_all_instructions(raw):
    message = ((raw.get('transaction') or {}).get('message')
               if isinstance(raw.get('transaction'), dict) else {}) or {}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    for instruction in message.get('instructions') or []:
        if isinstance(instruction, dict):
            yield instruction
    for group in meta.get('innerInstructions') or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get('instructions') or []:
            if isinstance(instruction, dict):
                yield instruction


def _iter_outer_instructions(raw):
    transaction = raw.get('transaction') if isinstance(raw, dict) else None
    message = transaction.get('message') if isinstance(transaction, dict) else None
    if not isinstance(message, dict):
        message = {}
    for instruction in message.get('instructions') or []:
        if isinstance(instruction, dict):
            yield instruction


def _net_balance_skip_outer(instruction, program, keys):
    """Known non-swap siblings stay unresolved.

    DFlow TransferToSponsor / Unwrap look like a clean wallet net (the
    sponsor fixture is one token out and SOL in). Layout owns those.
    FLASHX and OKX go through net-balance; classify plus the fee bound
    keep bundled value from becoming a trade.
    """
    if program == DFLOW:
        try:
            payload = _data(instruction.get('data'))
        except (ValueError, TypeError, KeyError):
            return True
        return payload[:8] not in {
            DFLOW_SWAP, DFLOW_SWAP2, DFLOW_SWAP_WITH_DESTINATION, DFLOW_WRAP,
        }
    if program == PUMP:
        try:
            payload = _data(instruction.get('data'))
        except (ValueError, TypeError, KeyError):
            return False
        return any(payload[:8] == _anchor(name) for name in PUMP_REVIEWED_NON_SWAP)
    return False


def _first_net_balance_program(raw, keys):
    """First OUTER program on the reviewed net-balance list.

    Inners under an unreviewed wrapper (B311, Photon) do not qualify.
    Known non-swap DFlow/FLASHX/Pump siblings do not qualify.
    """
    for instruction in _iter_outer_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program not in NET_BALANCE_SWAP_PROGRAMS:
            continue
        if _net_balance_skip_outer(instruction, program, keys):
            continue
        return program
    return None


def _owned_token_accounts(raw, address, keys):
    owned = set()
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    for field in ('preTokenBalances', 'postTokenBalances'):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get('owner') != address:
                continue
            index = balance.get('accountIndex')
            if type(index) is int and not isinstance(index, bool) and 0 <= index < len(keys):
                owned.add(keys[index])
    return owned


_TOKEN_HOP_OK = frozenset({'transfer', 'transferChecked'})
_TOKEN_HOP_FORBIDDEN = frozenset({
    'approve', 'approveChecked', 'setAuthority', 'closeAccount',
    'burn', 'burnChecked', 'mintTo', 'mintToChecked',
})
_TOKEN_TAG_KIND = {
    3: 'transfer',
    4: 'approve',
    6: 'setAuthority',
    7: 'mintTo',
    8: 'burn',
    9: 'closeAccount',
    12: 'transferChecked',
    13: 'approveChecked',
    14: 'mintToChecked',
    15: 'burnChecked',
}


def _has_unreviewed_outer_program(raw, keys):
    """True when an outer program is outside infra and net-balance outers."""
    for instruction in _iter_outer_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            return True
        if program in _INNER_INFRA or program in NET_BALANCE_SWAP_PROGRAMS:
            continue
        return True
    return False


def _system_transfer_from_wallet(instruction, address, keys):
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind == 'transfer' and isinstance(info, dict) and info.get('source') == address:
        return True
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return False
    if len(payload) >= 4 and int.from_bytes(payload[:4], 'little') == 2:
        return bool(accounts) and accounts[0] == address
    return False


def _system_transfer_to_wallet(instruction, address, keys):
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind == 'transfer' and isinstance(info, dict) and info.get('destination') == address:
        return True
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return False
    if len(payload) >= 4 and int.from_bytes(payload[:4], 'little') == 2:
        return len(accounts) > 1 and accounts[1] == address
    return False


def _token_hop_fields(instruction, keys):
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    if not isinstance(info, dict):
        info = {}
    if kind:
        return kind, info
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return None, {}
    if not payload:
        return None, {}
    kind = _TOKEN_TAG_KIND.get(payload[0])
    if kind == 'transfer' and len(accounts) >= 3:
        return kind, {
            'source': accounts[0],
            'destination': accounts[1],
            'authority': accounts[2],
        }
    if kind == 'transferChecked' and len(accounts) >= 4:
        return kind, {
            'source': accounts[0],
            'destination': accounts[2],
            'authority': accounts[3],
        }
    return kind, {'account': accounts[0]} if accounts else {}


def _hop_token_op_ok(instruction, owned, address, keys, hop_accounts=None):
    kind, info = _token_hop_fields(instruction, keys)
    touched = _instruction_account_keys(instruction, keys)
    for field in ('source', 'destination', 'account', 'authority', 'owner', 'wallet', 'newAccount'):
        value = info.get(field)
        if isinstance(value, str) and value:
            touched.add(value)
    if not touched.intersection(owned):
        return True
    if kind in _TOKEN_HOP_FORBIDDEN or kind not in _TOKEN_HOP_OK:
        return False
    destination = info.get('destination')
    if destination in owned:
        return True
    # Wallet authority alone is not enough: a hop child that sends the
    # wallet's tokens to a third-party ATA is not a documented hop leg.
    return bool(hop_accounts) and destination in hop_accounts


def _jup_hop_children_ok(inners, start, owned, address, keys):
    hop = inners[start - 1] if start else None
    hop_accounts = _instruction_account_keys(hop, keys) if isinstance(hop, dict) else set()
    for instruction in inners[start:]:
        if instruction.get('stackHeight') == 2:
            break
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            return False
        if program in TOKEN_IDS:
            if not _hop_token_op_ok(instruction, owned, address, keys, hop_accounts):
                return False
        elif program == SYSTEM_ID and (
            _system_transfer_from_wallet(instruction, address, keys)
            or _system_transfer_to_wallet(instruction, address, keys)
        ):
            return False
    return True


def _jupiter_hop_inner_ok(raw, address, keys):
    """Allow a direct JUP6 prop-AMM hop that only moves wallet assets as transfers.

    Unknown hop program ids stay off WELL_KNOWN_INNER_AMMS. The wallet net
    still has to pass classify_net_balance_assets on the net-balance path.
    """
    if not isinstance(raw, dict) or not address or not keys:
        return False
    if _has_unreviewed_outer_program(raw, keys):
        return False
    owned = {address, *_owned_token_accounts(raw, address, keys)}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    message = ((raw.get('transaction') or {}).get('message')
               if isinstance(raw.get('transaction'), dict) else {}) or {}
    outers = message.get('instructions') or []
    for group in meta.get('innerInstructions') or []:
        if not isinstance(group, dict):
            continue
        outer_index = group.get('index')
        outer_program = None
        if (type(outer_index) is int and not isinstance(outer_index, bool)
                and 0 <= outer_index < len(outers) and isinstance(outers[outer_index], dict)):
            try:
                outer_program = _program(outers[outer_index], keys)
            except (ValueError, TypeError, KeyError, IndexError):
                outer_program = None
        inners = [ix for ix in (group.get('instructions') or []) if isinstance(ix, dict)]
        for idx, instruction in enumerate(inners):
            try:
                program = _program(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if program in REVIEWED_INNER_PROGRAMS:
                continue
            if not _instruction_account_keys(instruction, keys).intersection(owned):
                continue
            if outer_program not in NET_BALANCE_SWAP_PROGRAMS or instruction.get('stackHeight') != 2:
                return False
            if not _jup_hop_children_ok(inners, idx + 1, owned, address, keys):
                return False
    return True


def _net_balance_unknown_inner_blocks(raw, address, keys):
    """D3: unknown inner that touches a wallet-owned account stays unresolved."""
    owned = {address, *_owned_token_accounts(raw, address, keys)}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    unknown_touch = False
    for group in meta.get('innerInstructions') or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get('instructions') or []:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if program in REVIEWED_INNER_PROGRAMS:
                continue
            if _instruction_account_keys(instruction, keys).intersection(owned):
                unknown_touch = True
                break
        if unknown_touch:
            break
    if not unknown_touch:
        return False
    return not _jupiter_hop_inner_ok(raw, address, keys)


def _parsed_tip_lamports(raw, address, owned_accounts):
    """Add back only verified-tip System transfers, never pool consideration.

    Distinct from the auditor's published-tip list walk: this uses the app
    verified-tip set on parsed transfer infos. Unverified outgoing SOL stays
    in the wallet net so a swap cannot be cancelled by treating the pool
    transfer as a tip.
    """
    from scanner.mass_search.verified_costs import is_verified_tip_account
    tips = 0
    for instruction in _iter_all_instructions(raw):
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else None
        if not isinstance(info, dict) or parsed.get('type') != 'transfer':
            continue
        if info.get('source') != address:
            continue
        dest = info.get('destination')
        if dest == address or dest in owned_accounts:
            continue
        if not is_verified_tip_account(dest):
            continue
        lamports = info.get('lamports')
        if type(lamports) is int and not isinstance(lamports, bool) and lamports > 0:
            tips += lamports
    return tips


def _app_owned_net_assets(raw, address, keys):
    """Wallet net after fee, owned-account rent, wSOL merge and parsed tips.

    App method: owner-tagged token balances plus native wallet delta. This is
    not the auditor's `_owned_token_deltas` + `_rent_correction` + published
    tips path.
    """
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    pre_native = meta.get('preBalances') or []
    post_native = meta.get('postBalances') or []
    fee = meta.get('fee') if type(meta.get('fee')) is int and not isinstance(meta.get('fee'), bool) else 0
    try:
        wallet_index = keys.index(address)
    except ValueError:
        return None
    if wallet_index >= len(pre_native) or wallet_index >= len(post_native):
        return None
    native = Decimal(post_native[wallet_index] - pre_native[wallet_index])
    if keys and keys[0] == address:
        native += Decimal(fee)
    token = {}
    decimals = {}
    owned_accounts = set()
    account_mint = {}
    account_token_delta = {}
    for field, sign in (('preTokenBalances', -1), ('postTokenBalances', 1)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict):
                return None
            if 'owner' not in balance or balance.get('owner') in (None, ''):
                return None
            if balance.get('owner') != address:
                continue
            mint = balance.get('mint')
            amount = (balance.get('uiTokenAmount') or {}).get('amount')
            dec = (balance.get('uiTokenAmount') or {}).get('decimals')
            if not isinstance(mint, str) or amount in (None, ''):
                continue
            try:
                qty = Decimal(str(amount))
            except (ValueError, TypeError, OverflowError):
                return None
            token[mint] = token.get(mint, Decimal(0)) + qty * sign
            if type(dec) is int and not isinstance(dec, bool):
                decimals[mint] = dec
            index = balance.get('accountIndex')
            if type(index) is int and not isinstance(index, bool) and 0 <= index < len(keys):
                account = keys[index]
                owned_accounts.add(account)
                account_mint[account] = mint
                account_token_delta[account] = account_token_delta.get(account, Decimal(0)) + qty * sign
    rent = Decimal(0)
    wsol = token.pop(WSOL, Decimal(0))
    for account, mint in account_mint.items():
        try:
            index = keys.index(account)
        except ValueError:
            continue
        if index >= len(pre_native) or index >= len(post_native):
            continue
        native_change = Decimal(post_native[index] - pre_native[index])
        if mint == WSOL:
            rent += native_change - account_token_delta.get(account, Decimal(0))
        else:
            rent += native_change
    tips = Decimal(_parsed_tip_lamports(raw, address, owned_accounts))
    sol = native + wsol + rent + tips
    if abs(sol) <= Decimal(NET_BALANCE_SOL_DUST_LAMPORTS):
        sol = Decimal(0)
    assets = {mint: qty for mint, qty in token.items() if qty != 0}
    if sol != 0:
        assets['SOL'] = sol
    return assets, decimals, sol


def _peel_fee_sol_residue(assets):
    """Drop a cost-sized SOL third leg. Returns peeled lamports or 0.

    SOL is the quote when it is one of two legs. Peel only when at least two
    other assets already form the trade, so a 0.01 SOL swap stays a swap.
    A two-leg SOL inflow is never a fee (DC9). A third-leg wrap/rent residue
    of either sign under the fee bound is cost, not a third trade asset.
    """
    if not isinstance(assets, dict):
        return Decimal(0)
    sol = assets.get('SOL', Decimal(0))
    others = [qty for mint, qty in assets.items() if mint != 'SOL' and qty != 0]
    if len(others) >= 2 and sol != 0 and abs(sol) <= Decimal(NET_BALANCE_COST_SOL_LAMPORTS):
        assets.pop('SOL', None)
        return sol
    return Decimal(0)


def _ata_create_owner_account(instruction, keys):
    """Wallet and ATA pubkey for a create / createIdempotent, parsed or compiled."""
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind in ('create', 'createIdempotent') and isinstance(info, dict):
        return info.get('wallet') or info.get('owner'), info.get('account')
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return None, None
    if payload not in (b'', b'\0', b'\x01') or len(accounts) < 3:
        return None, None
    return accounts[2], accounts[1]


def _other_wallet_ata_keeps_tokens(raw, address, keys, assets=None):
    """True when a new other-wallet ATA retains more than the referral bound."""
    created = set()
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program != ASSOCIATED_ID:
            continue
        owner, account = _ata_create_owner_account(instruction, keys)
        if owner and owner != address and account:
            created.add(account)
    if not created:
        return False
    assets = assets or {}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    for balance in meta.get('postTokenBalances') or []:
        if not isinstance(balance, dict):
            continue
        index = balance.get('accountIndex')
        if type(index) is not int or isinstance(index, bool) or index < 0 or index >= len(keys):
            continue
        if keys[index] not in created:
            continue
        amount = (balance.get('uiTokenAmount') or {}).get('amount')
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return True
        if qty <= 0:
            continue
        mint = balance.get('mint')
        net = abs(assets.get(mint, Decimal(0))) if mint else Decimal(0)
        if net == 0:
            continue
        cap = max(Decimal(1), net * Decimal(NET_BALANCE_REFERRAL_BPS) / Decimal(10_000))
        if qty > cap:
            return True
    return False


def _lifecycle_owned_accounts(raw, address, keys):
    """Wallet, its token accounts, and ATAs / inits created for it in this tx."""
    owned = {address, *_owned_token_accounts(raw, address, keys)}
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else None
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if program == ASSOCIATED_ID:
            owner, account = _ata_create_owner_account(instruction, keys)
            if owner == address and account:
                owned.add(account)
            continue
        if program in TOKEN_IDS and kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3'):
            if isinstance(info, dict) and info.get('owner') == address and info.get('account'):
                owned.add(info['account'])
    return owned


def _outbound_above_fee_bound(raw, address, keys, assets):
    """True when a top-level transfer to someone else exceeds the fee bound.

    Inner AMM hops are the swap itself and are not scored here. Bundled
    value is a sibling outer System/Token transfer above 0.02 SOL or 2% of
    that mint's wallet net. Wrap funding to a wallet ATA is not outbound.
    """
    owned = _lifecycle_owned_accounts(raw, address, keys)
    for instruction in _iter_outer_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else None
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if program == SYSTEM_ID:
            if kind == 'transfer' and isinstance(info, dict):
                if info.get('source') != address:
                    continue
                dest = info.get('destination')
                if dest in owned:
                    continue
                from scanner.mass_search.verified_costs import is_verified_tip_account
                if is_verified_tip_account(dest):
                    continue
                lamports = info.get('lamports')
                if type(lamports) is int and not isinstance(lamports, bool) and lamports > NET_BALANCE_COST_SOL_LAMPORTS:
                    return True
                continue
            try:
                payload = _data(instruction.get('data'))
                accounts = _accounts(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if len(payload) >= 12 and int.from_bytes(payload[:4], 'little') == 2:
                dest = accounts[1] if len(accounts) > 1 else None
                from scanner.mass_search.verified_costs import is_verified_tip_account
                if accounts and accounts[0] == address and dest not in owned and not is_verified_tip_account(dest):
                    if int.from_bytes(payload[4:12], 'little') > NET_BALANCE_COST_SOL_LAMPORTS:
                        return True
            continue
        if program not in TOKEN_IDS or kind not in ('transfer', 'transferChecked', 'transferCheckedWithFee'):
            continue
        if not isinstance(info, dict):
            continue
        source, dest = info.get('source'), info.get('destination')
        if source not in owned or dest in owned:
            continue
        checked = info.get('tokenAmount') if kind in ('transferChecked', 'transferCheckedWithFee') else None
        amount = (checked or {}).get('amount') if checked else info.get('amount')
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return True
        mint = info.get('mint')
        if not mint:
            continue
        net = abs(assets.get(mint, Decimal(0)))
        if net == 0:
            continue
        cap = max(Decimal(1), net * Decimal(NET_BALANCE_REFERRAL_BPS) / Decimal(10_000))
        if qty > cap:
            return True
    return False


def _account_mint_map(raw, keys):
    """Mint for every token account that appears in pre/post balances."""
    mints = {}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    for field in ('preTokenBalances', 'postTokenBalances'):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict):
                continue
            index = balance.get('accountIndex')
            mint = balance.get('mint')
            if (
                type(index) is int and not isinstance(index, bool)
                and 0 <= index < len(keys) and isinstance(mint, str) and mint
            ):
                mints[keys[index]] = mint
    return mints


def _system_transfer_leg(instruction, keys):
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind == 'transfer' and isinstance(info, dict):
        lamports = info.get('lamports')
        if type(lamports) is int and not isinstance(lamports, bool) and lamports > 0:
            return info.get('source'), info.get('destination'), Decimal(lamports)
        return None
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if len(payload) >= 12 and int.from_bytes(payload[:4], 'little') == 2:
        lamports = int.from_bytes(payload[4:12], 'little')
        if lamports > 0 and len(accounts) >= 2:
            return accounts[0], accounts[1], Decimal(lamports)
    return None


def _token_transfer_qty(instruction, keys):
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind in ('transfer', 'transferChecked', 'transferCheckedWithFee') and isinstance(info, dict):
        checked = info.get('tokenAmount') if kind in ('transferChecked', 'transferCheckedWithFee') else None
        amount = (checked or {}).get('amount') if checked else info.get('amount')
        try:
            qty = Decimal(str(amount or 0))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return None
        if qty <= 0:
            return None
        return qty
    try:
        payload = _data(instruction.get('data'))
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if payload and payload[0] in (3, 12) and len(payload) >= 9:
        qty = int.from_bytes(payload[1:9], 'little')
        return Decimal(qty) if qty > 0 else None
    return None


def _token_transfer_leg(instruction, keys, mints):
    kind, info = _token_hop_fields(instruction, keys)
    if kind not in ('transfer', 'transferChecked', 'transferCheckedWithFee'):
        return None
    source, dest = info.get('source'), info.get('destination')
    if not source or not dest:
        return None
    qty = _token_transfer_qty(instruction, keys)
    if qty is None:
        return None
    mint = info.get('mint') or mints.get(source) or mints.get(dest)
    return source, dest, qty, mint


def _net_balance_route_accounts(raw, keys):
    """Outer net-balance program accounts only.

    Inner CPI counterparties are not swap legs. A co-signed third party that
    appears only on a nested System/Token transfer must fail closed.
    """
    accounts = set()
    message = ((raw.get('transaction') or {}).get('message')
               if isinstance(raw.get('transaction'), dict) else {}) or {}
    outers = message.get('instructions') or []
    for instruction in outers:
        if not isinstance(instruction, dict):
            continue
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program not in NET_BALANCE_SWAP_PROGRAMS:
            continue
        if _net_balance_skip_outer(instruction, program, keys):
            continue
        accounts.add(program)
        accounts.update(_instruction_account_keys(instruction, keys))
    return accounts


def _counterparty_allowed(other, owned, route_accounts, *, tip_ok=False):
    if not other or other in owned or other in route_accounts:
        return True
    if tip_ok:
        from scanner.mass_search.verified_costs import is_verified_tip_account
        if is_verified_tip_account(other):
            return True
    return False


def _non_route_wallet_flow(raw, address, keys):
    """True when a wallet transfer is not a route/pool/wrap/tip beyond the fee bound.

    Third-party System transfers, token transfers from a non-route source, and
    airdrop-style native credits without a parsed transfer fail closed.
    """
    owned = _lifecycle_owned_accounts(raw, address, keys)
    route_accounts = _net_balance_route_accounts(raw, keys)
    mints = _account_mint_map(raw, keys)
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program == SYSTEM_ID:
            leg = _system_transfer_leg(instruction, keys)
            if not leg:
                continue
            source, dest, lamports = leg
            if dest in owned and source not in owned:
                # System inbound is never a swap leg (unwrap is closeAccount).
                return True
            continue
        if program not in TOKEN_IDS:
            continue
        leg = _token_transfer_leg(instruction, keys, mints)
        if not leg:
            continue
        source, dest, qty, mint = leg
        if dest in owned and source not in owned:
            if not _counterparty_allowed(source, owned, route_accounts):
                return True
        elif source in owned and dest not in owned:
            continue
    return False


def _route_wallet_flows(raw, address, keys):
    """Wallet legs that touch a route/pool account (outer or inner)."""
    owned = _lifecycle_owned_accounts(raw, address, keys)
    route_accounts = _net_balance_route_accounts(raw, keys)
    mints = _account_mint_map(raw, keys)
    sol = Decimal(0)
    tokens = {}
    saw = False
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program == SYSTEM_ID:
            leg = _system_transfer_leg(instruction, keys)
            if not leg:
                continue
            source, dest, lamports = leg
            if dest in owned and source not in owned:
                continue
            elif source in owned and dest in route_accounts and dest not in owned:
                sol -= lamports
                saw = True
            continue
        if program not in TOKEN_IDS:
            continue
        leg = _token_transfer_leg(instruction, keys, mints)
        if not leg:
            continue
        source, dest, qty, mint = leg
        if dest in owned and source in route_accounts and source not in owned:
            saw = True
            if mint:
                tokens[mint] = tokens.get(mint, Decimal(0)) + qty
        elif source in owned and dest in route_accounts and dest not in owned:
            saw = True
            if mint:
                tokens[mint] = tokens.get(mint, Decimal(0)) - qty
    return saw, sol, tokens


def _unknown_inner_touches_wallet(raw, address, keys):
    """True when a non-reviewed inner program touches a wallet-owned account."""
    if not isinstance(raw, dict) or not address or not keys:
        return False
    owned = {address, *_owned_token_accounts(raw, address, keys)}
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    for group in meta.get('innerInstructions') or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get('instructions') or []:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if program in REVIEWED_INNER_PROGRAMS:
                continue
            if _instruction_account_keys(instruction, keys).intersection(owned):
                return True
    return False


def _hop_counterparty_sol_gain(raw, address, keys):
    """SOL that landed on a prop-AMM hop program or its non-owned accounts.

    A hop that takes native SOL must show that SOL on a hop counterparty.
    Written as a hop-inner account walk, not the auditor's program-id
    balance-sheet pass.
    """
    if not isinstance(raw, dict) or not address or not keys:
        return Decimal(0)
    owned = {address, *_owned_token_accounts(raw, address, keys)}
    counterparties = set()
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    message = ((raw.get('transaction') or {}).get('message')
               if isinstance(raw.get('transaction'), dict) else {}) or {}
    outers = message.get('instructions') or []
    for group in meta.get('innerInstructions') or []:
        if not isinstance(group, dict):
            continue
        outer_index = group.get('index')
        outer_program = None
        if (type(outer_index) is int and not isinstance(outer_index, bool)
                and 0 <= outer_index < len(outers) and isinstance(outers[outer_index], dict)):
            try:
                outer_program = _program(outers[outer_index], keys)
            except (ValueError, TypeError, KeyError, IndexError):
                outer_program = None
        if outer_program not in NET_BALANCE_SWAP_PROGRAMS:
            continue
        for instruction in group.get('instructions') or []:
            if not isinstance(instruction, dict) or instruction.get('stackHeight') != 2:
                continue
            try:
                program = _program(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if program in _INNER_INFRA:
                continue
            touched = _instruction_account_keys(instruction, keys)
            if not touched.intersection(owned):
                continue
            counterparties.add(program)
            counterparties.update(touched - owned)
    if not counterparties:
        return Decimal(0)
    pre = meta.get('preBalances') or []
    post = meta.get('postBalances') or []
    gained = Decimal(0)
    for account in counterparties:
        try:
            index = keys.index(account)
        except ValueError:
            continue
        if index >= len(pre) or index >= len(post):
            continue
        try:
            delta = Decimal(str(post[index])) - Decimal(str(pre[index]))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            continue
        if delta > 0:
            gained += delta
    return gained


def _close_account_fields(instruction, keys):
    """Parsed or compiled closeAccount (account, destination). Owner is not used.

    closeAccount.owner is the close authority, not the SPL token owner.
    """
    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    kind = parsed.get('type') if isinstance(parsed, dict) else None
    if kind == 'closeAccount' and isinstance(info, dict):
        return info.get('account'), info.get('destination')
    try:
        payload = _data(instruction.get('data'))
        accounts = _accounts(instruction, keys)
    except (ValueError, TypeError, KeyError, IndexError):
        return None, None
    if payload[:1] == b'\x09' and len(accounts) >= 2:
        return accounts[0], accounts[1]
    return None, None


def _own_ata_close_refund_lamports(raw, address, keys):
    """Rent refunded by closing the wallet's own token accounts.

    A leftover is allowed only when the closed account's SPL token owner is
    the wallet (balance row or same-tx initialize) and the refund is no
    more than that account's rent. Unproved owner or a still-open account
    contributes nothing.
    """
    if not isinstance(raw, dict) or not address or not keys:
        return Decimal(0)
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    pre_native = meta.get('preBalances') or []
    post_native = meta.get('postBalances') or []
    owners = {}
    token_pre = {}
    mints = {}
    unproved = set()
    for field, side in (('preTokenBalances', 'pre'), ('postTokenBalances', 'post')):
        for row in meta.get(field) or []:
            if not isinstance(row, dict):
                continue
            index = row.get('accountIndex')
            if type(index) is not int or isinstance(index, bool) or index < 0 or index >= len(keys):
                continue
            account = keys[index]
            if 'owner' not in row or row.get('owner') in (None, ''):
                unproved.add(account)
                continue
            owner = row.get('owner')
            if account in owners and owners[account] != owner:
                unproved.add(account)
            else:
                owners[account] = owner
            mint = row.get('mint')
            if isinstance(mint, str) and mint:
                mints[account] = mint
            amount = (row.get('uiTokenAmount') or {}).get('amount')
            if side == 'pre' and amount not in (None, ''):
                try:
                    token_pre[account] = Decimal(str(amount))
                except (InvalidOperation, ValueError, TypeError, OverflowError):
                    unproved.add(account)
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        info = parsed.get('info') if isinstance(parsed, dict) else None
        kind = parsed.get('type') if isinstance(parsed, dict) else None
        if program in TOKEN_IDS and kind in (
            'initializeAccount', 'initializeAccount2', 'initializeAccount3',
        ) and isinstance(info, dict) and info.get('account') and info.get('owner'):
            owners.setdefault(info['account'], info['owner'])
        if program == ASSOCIATED_ID:
            owner, account = _ata_create_owner_account(instruction, keys)
            if owner and account:
                owners.setdefault(account, owner)
    refund = Decimal(0)
    for instruction in _iter_all_instructions(raw):
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if program not in TOKEN_IDS:
            continue
        account, destination = _close_account_fields(instruction, keys)
        if destination != address or not account or account in unproved:
            continue
        if owners.get(account) != address:
            continue
        try:
            index = keys.index(account)
        except ValueError:
            continue
        if index >= len(pre_native) or index >= len(post_native):
            continue
        try:
            pre_lamports = Decimal(str(pre_native[index]))
            post_lamports = Decimal(str(post_native[index]))
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            continue
        if post_lamports != 0:
            continue
        rent = pre_lamports
        if mints.get(account) == WSOL:
            rent = pre_lamports - token_pre.get(account, Decimal(0))
        if rent <= 0:
            continue
        refund += rent
    return refund


def _documented_route_sol(raw, address, keys):
    """Route-leg SOL (native + wSOL + hop take). None when no route leg exists."""
    saw, route_sol, route_tokens = _route_wallet_flows(raw, address, keys)
    hop_gain = _hop_counterparty_sol_gain(raw, address, keys)
    wsol_flow = Decimal(route_tokens.get(WSOL, 0) or 0)
    # Hop-account SOL is the same wrap/pool take already counted as wSOL or
    # a native route transfer. Stacking it double-counts and refuses a
    # legitimate AMM/Jupiter net (wallet looks more profitable than the
    # inflated-negative route). Apply only when no SOL/wSOL route leg exists.
    if hop_gain and route_sol == 0 and wsol_flow == 0:
        route_sol -= hop_gain
        saw = True
        meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
        fee = meta.get('fee') if type(meta.get('fee')) is int and not isinstance(meta.get('fee'), bool) else 0
        if keys and keys[0] == address and fee:
            route_sol += Decimal(fee)
    if not saw:
        return None, None, hop_gain
    route_sol += route_tokens.pop(WSOL, Decimal(0))
    return route_sol, route_tokens, hop_gain


def _sol_is_third_leg(assets):
    others = [qty for mint, qty in (assets or {}).items() if mint != 'SOL' and qty != 0]
    return len(others) >= 2


def _price_sol_from_route_legs(assets, route_sol, allowed_refund):
    """Book SOL from the route. Extra inbound is only own-ATA rent.

    A two-leg SOL quote uses the route amount. Wallet-favourable leftover
    above the proved own-ATA rent refund fails closed. Extra outbound
    stays on the wallet net (conservative cost). A third-leg SOL residue
    is left for _peel_fee_sol_residue and is not the trade price.
    """
    if not isinstance(assets, dict) or route_sol is None:
        return False
    if _sol_is_third_leg(assets):
        return True
    wallet_sol = Decimal(assets.get('SOL', 0) or 0)
    leftover = wallet_sol - Decimal(route_sol)
    if leftover > Decimal(allowed_refund or 0):
        return True
    if leftover >= 0:
        if Decimal(route_sol) != 0:
            assets['SOL'] = Decimal(route_sol)
        else:
            assets.pop('SOL', None)
    return True


def _route_flow_disagrees_with_wallet(raw, address, keys, assets):
    """Reconcile route transfers against the wallet net. Disagree → fail closed."""
    documented = _documented_route_sol(raw, address, keys)
    route_sol, route_tokens, hop_gain = documented
    if route_sol is None:
        return True
    wallet_sol = Decimal(assets.get('SOL', 0) or 0)
    # An unknown prop-AMM hop that moved native SOL without a visible
    # counterparty take is not a documented swap leg (H5).
    if (
        hop_gain == 0
        and wallet_sol != 0
        and route_sol == 0
        and _net_balance_unknown_inner_blocks(raw, address, keys) is False
        and _unknown_inner_touches_wallet(raw, address, keys)
    ):
        return True
    allowed = _own_ata_close_refund_lamports(raw, address, keys)
    leftover = wallet_sol - route_sol
    # Two-leg SOL quote: wallet-favourable leftover is only own-ATA rent.
    # Third-leg SOL is residue, not the trade price (C7). Extra outbound
    # is conservative. Fees are meta.fee plus a verified tip, already
    # added back into the wallet net.
    if leftover > allowed and not _sol_is_third_leg(assets):
        return True
    for mint in set(route_tokens or ()) | set(assets):
        if mint in (None, WSOL, 'SOL') or mint == 'SOL':
            continue
        wallet_qty = Decimal(assets.get(mint, 0) or 0)
        route_qty = Decimal((route_tokens or {}).get(mint, 0) or 0)
        if wallet_qty > route_qty + Decimal(1):
            return True
    return False


def classify_net_balance_assets(assets, decimals):
    """Accept exactly one in and one out, or a reviewed stable conversion.

    Token-to-token (two non-quotes) stays unresolved. NFT-like +1 of a
    0-decimal mint fails closed (LP position / mint).
    """
    if not assets:
        return None
    for mint, qty in assets.items():
        if mint == 'SOL':
            continue
        if decimals.get(mint) == 0 and abs(qty) <= 1:
            return None
    nonzero = [(mint, qty) for mint, qty in assets.items() if qty != 0]
    if len(nonzero) != 2:
        return None
    (mint_a, qty_a), (mint_b, qty_b) = nonzero
    if (qty_a > 0) == (qty_b > 0):
        return None
    quotes = {'SOL', USDC, USDT}
    if mint_a in quotes and mint_b in quotes:
        incoming = mint_a if qty_a > 0 else mint_b
        outgoing = mint_b if incoming == mint_a else mint_a
        return {
            'kind': 'conversion',
            'from_asset': 'SOL' if outgoing == 'SOL' else QUOTE_ASSET.get(outgoing, outgoing),
            'to_asset': 'SOL' if incoming == 'SOL' else QUOTE_ASSET.get(incoming, incoming),
            'mint': USDC if USDC in (mint_a, mint_b) else (USDT if USDT in (mint_a, mint_b) else incoming),
            'quantity': abs(assets.get(USDC, assets.get(USDT, Decimal(0)))),
            'quote_mint': USDC if USDC in (mint_a, mint_b) else (USDT if USDT in (mint_a, mint_b) else None),
            'settlement': assets.get('SOL', Decimal(0)),
            'quote_delta': assets.get(USDC, assets.get(USDT, Decimal(0))),
        }
    trade_legs = [(mint, qty) for mint, qty in nonzero if mint not in quotes]
    quote_legs = [(mint, qty) for mint, qty in nonzero if mint in quotes]
    if len(trade_legs) != 1 or len(quote_legs) != 1:
        return None
    mint, quantity = trade_legs[0]
    quote_mint, quote_qty = quote_legs[0]
    return {
        'kind': 'buy' if quantity > 0 else 'sell',
        'mint': mint,
        'quantity': abs(quantity),
        'quote_mint': None if quote_mint == 'SOL' else quote_mint,
        'settlement': quote_qty if quote_mint == 'SOL' else Decimal(0),
        'quote_delta': quote_qty if quote_mint != 'SOL' else Decimal(0),
        'from_asset': None,
        'to_asset': None,
    }


def net_balance_reviewed_swap(raw, address):
    """Venue-agnostic reconstruction. None when the net is ambiguous.

    Requires a signer wallet and an instruction from NET_BALANCE_SWAP_PROGRAMS.
    Layout matching is deliberately not used.
    """
    if not isinstance(raw, dict) or not address:
        return None
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    if meta.get('err') is not None:
        return None
    message = ((raw.get('transaction') or {}).get('message')
               if isinstance(raw.get('transaction'), dict) else {}) or {}
    try:
        keys = _keys(message, meta)
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    signers = _message_signers(message, keys)
    if address not in signers:
        return None
    program = _first_net_balance_program(raw, keys)
    if not program:
        return None
    if _net_balance_unknown_inner_blocks(raw, address, keys):
        return None
    owned = _app_owned_net_assets(raw, address, keys)
    if owned is None:
        return None
    assets, decimals, _sol = owned
    if _has_unreviewed_outer_program(raw, keys):
        return None
    if _other_wallet_ata_keeps_tokens(raw, address, keys, assets):
        return None
    if _outbound_above_fee_bound(raw, address, keys, assets):
        return None
    if _non_route_wallet_flow(raw, address, keys):
        return None
    if _route_flow_disagrees_with_wallet(raw, address, keys, assets):
        return None
    documented = _documented_route_sol(raw, address, keys)
    route_sol, _route_tokens, _hop_gain = documented
    allowed = _own_ata_close_refund_lamports(raw, address, keys)
    _price_sol_from_route_legs(assets, route_sol, allowed)
    cost_sol = _peel_fee_sol_residue(assets)
    classified = classify_net_balance_assets(assets, decimals)
    if classified is None:
        return None
    classified['program'] = program
    classified['instruction'] = NET_BALANCE_INSTRUCTION
    classified['decimals'] = decimals.get(classified['mint'])
    classified['path'] = 'meta.net_balance'
    classified['source'] = program
    if cost_sol:
        classified['fee_residue_sol'] = cost_sol
    return classified


def decode_supported_swaps(transactions, address, *, allow_net_balance=True):
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
                program = _program(instruction, keys)
                if program == FLASHX and not _flashx_is_reviewed_swap(instruction, keys):
                    continue
                if program == DFLOW and not _dflow_is_reviewed_swap(instruction, keys):
                    continue
                if program in REVIEWED_OUTER_VENUES:
                    route = _route(instruction, keys)
                    route.update(index=index, path=f'instructions.{index}')
                    routes.append(route)
            if not routes:
                no_swap += 1
                from scanner.mass_search.verified_costs import is_verified_tip_account
                for index, instruction in enumerate(instructions):
                    parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
                    info = parsed.get('info') if isinstance(parsed, dict) else None
                    if not isinstance(info, dict) or parsed.get('type') != 'transfer':
                        continue
                    if info.get('source') != address:
                        continue
                    dest = info.get('destination')
                    lamports = info.get('lamports')
                    if type(lamports) is not int or not is_verified_tip_account(dest):
                        continue
                    emit('tip', f'instructions.{index}',
                         amount_sol=canonical(Decimal(lamports) / LAMPORTS),
                         tips_sol=canonical(Decimal(lamports) / LAMPORTS),
                         paid_by_wallet=paid, destination=dest,
                         economic_role='verified_tip',
                         separate_successful_transaction=True,
                         reason='Tip paid in a separate successful transaction; counted as a cost, not swap volume')
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
            pre, post, identities, token_programs = {}, {}, {}, {}
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
                    if balance.get('programId'):
                        token_programs[account] = balance.get('programId')
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
            rfq_platform_fees = []
            token_2022_inbound = defaultdict(list)
            token_2022_declared_fees = defaultdict(int)
            token_2022_fees = []
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
                if program in (COMPUTE_ID, *MEMO_IDS, LIGHTHOUSE):
                    continue
                if program == FLASHX and not _flashx_is_reviewed_swap(instruction, keys):
                    continue
                if program == DFLOW and not _dflow_is_reviewed_swap(instruction, keys):
                    continue
                if program == ASSOCIATED_ID:
                    if kind not in ('create', 'createIdempotent'):
                        raise ValueError('Unparsed associated account administration')
                    if info.get('wallet') != address:
                        # Nested createIdempotent for a pool/protocol ATA is
                        # swap lifecycle (Jupiter/Pump hop), not a transfer-out.
                        if nested and info.get('source') == address:
                            account = info.get('account')
                            if account:
                                rent_funders[account] = address
                            continue
                        raise ValueError('Associated account creation for another wallet is outside swap scope')
                    account = info.get('account')
                    if info.get('mint') == WSOL:
                        allowed_wrapped.add(account)
                    if info.get('source') == address:
                        rent_funders[account] = address
                    continue
                if program == SYSTEM_ID:
                    if not kind:
                        created = _system_create_unparsed(instruction, keys)
                        if created:
                            kind = 'createAccount'
                            info = created
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
                    if kind is None and route['program'] == JUPITER:
                        # Token-2022 harvest / excess-lamports CPIs on vaults
                        # have no reviewed binary contract. Inside a reviewed
                        # Jupiter route they are non-economic: wallet legs
                        # still have to reconcile below.
                        continue
                    if kind == 'closeAccount':
                        account = info.get('account')
                        if info.get('destination') == address:
                            if owned.get(account, {}).get('mint') == WSOL and _close_authority(info) != address:
                                raise ValueError('Wrapped SOL closure lacks the investigated wallet authority')
                            closures[account] = address
                        elif account in owned or account in allowed_wrapped:
                            raise ValueError('Token account closes to another recipient')
                        continue
                    if kind not in ('transfer', 'transferChecked', 'transferCheckedWithFee'):
                        raise ValueError('Unsupported token permission, extension, mint or burn operation')
                    source, destination = info.get('source'), info.get('destination')
                    checked = info.get('tokenAmount') if kind in ('transferChecked', 'transferCheckedWithFee') else None
                    quantity = raw_quantity(checked['amount'] if checked else info.get('amount'))
                    for account in (source, destination):
                        identity = identities.get(account)
                        if identity and checked and (_integer(checked.get('decimals')) != identity['decimals'] or info.get('mint') != identity['mint']):
                            raise ValueError('Parsed transfer disagrees with token identity')
                    rfq_fee_fill = (
                        kind == 'transferChecked'
                        and route['program'] == RFQ_FILL
                        and not nested
                        and outer != route['index']
                        and destination == RFQ_FEE_FILL_ACCOUNT
                        and source in owned
                    )
                    if outer != route['index'] and any(account in owned for account in (source, destination)):
                        if not rfq_fee_fill:
                            raise ValueError('Unrelated token transfer prevents swap quantity attribution')
                        declared = info.get('fee')
                        rfq_platform_fees.append({
                            'destination': destination,
                            'source': source,
                            'quantity': quantity,
                            'mint': (identities.get(source) or {}).get('mint') or info.get('mint'),
                            'path': path,
                            'declared_fee': raw_quantity(declared) if declared not in (None, '') else quantity,
                        })
                    flow[source] -= quantity
                    flow[destination] += quantity
                    if program == TOKEN_2022_ID and destination in owned:
                        token_2022_inbound[destination].append(quantity)
                        declared = info.get('fee')
                        if declared not in (None, ''):
                            token_2022_declared_fees[destination] += raw_quantity(declared)
                    continue
                if outer != route['index']:
                    raise ValueError('Unreviewed outer program may bundle other economic activity')
                # CPIs are part of a successful, verified route; net owned legs
                # still require exact parsed-transfer reconciliation below.
            _verify_ephemeral_wrapped(flat, allowed_wrapped, owned, keys, pre_lamports,
                                      post_lamports, address, route, fee)
            retained_funding = _retained_user_volume_funding(flat, keys, pre_lamports, post_lamports, address, route)
            rent_skip = set(owned) | set(allowed_wrapped) | {item['account'] for item in retained_funding}
            episode_rent = _episode_rent_exclusion(
                flat, keys, pre_lamports, post_lamports, address, rent_skip,
            )
            new_token_rent = _verified_new_token_account_rent(
                flat, keys, pre_lamports, post_lamports, address, rent_skip,
            )
            inner_venues, inner_block = _reviewed_inner_venues(
                flat, keys, route, owned, address,
            )
            if inner_block:
                raise ValueError(inner_block)
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
            if route['program'] == OKX_DEX_ROUTER:
                if not any(account in owned or account in allowed_wrapped for account in route['owned_accounts']):
                    raise ValueError('OKX SwapTob user token accounts lack event-time wallet ownership')
            elif route['program'] == RFQ_FILL:
                # RFQ Fill account 4 is often the maker/vault ATA, not the
                # investigated wallet. Wallet token and SOL/USDC legs still
                # have to reconcile below.
                pass
            else:
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
                    inbound = token_2022_inbound.get(account) or []
                    withheld = flow[account] - delta
                    declared_fee = token_2022_declared_fees.get(account) or 0
                    token_2022 = token_programs.get(account) == TOKEN_2022_ID and inbound and withheld > 0
                    if not token_2022:
                        raise ValueError('Wallet token delta does not reconcile to parsed swap transfers')
                    proved = declared_fee == withheld
                    candidates = infer_token_2022_fee_bps_candidates(inbound, withheld)
                    unique = candidates[0] if len(candidates) == 1 else None
                    token_2022_fees.append({
                        'account': account,
                        'mint': mint,
                        'gross': flow[account],
                        'inbound_gross_amounts': list(inbound),
                        'net_received': delta,
                        'withheld': withheld,
                        'declared_fee': declared_fee or None,
                        'observed': not proved,
                        'transfer_fee_basis_points': unique,
                        'inferred_bps_unique': unique is not None,
                        'inferred_bps_candidates': candidates if len(candidates) <= 8 else candidates[:8] + ['…'],
                        'source': (
                            'transfer_fee_extension' if proved else 'observed_token_2022_withheld'
                        ),
                        'execution_time_mint_config_established': False,
                        'transfer_fee_config_established': proved,
                        'note': (
                            'Transfer-fee extension amount from transferCheckedWithFee '
                            'reconciles the wallet token delta.'
                            if proved else
                            'Observed gross / net received / withheld only. '
                            'Mint account bytes (max fee, epoch) are absent from GTA. '
                            'A unique uncapped-ceiling bps fit is not TransferFeeConfig.'
                        ),
                    })
                    flow[account] = delta
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
            # PumpSwap user-volume (IDL-located) is documented separately and
            # is isolated from the swap quote. Generic not-owned creates are
            # not in retained_funding and stay in consideration.
            settlement = (post_lamports[wallet_index] - pre_lamports[wallet_index]
                          + (fee if paid else 0) + rent_correction + deltas.pop(WSOL, 0)
                          - outside_native_delta + sum(item['lamports'] for item in retained_funding)
                          + episode_rent + new_token_rent)
            wsol_accounts = allowed_wrapped | {account for account, identity in owned.items() if identity['mint'] == WSOL}
            owned_wsol_accounts = {account for account, identity in owned.items() if identity['mint'] == WSOL}
            if wsol_accounts and settlement != sum(flow[account] for account in wsol_accounts):
                # Jupiter shared-accounts route_v2 often settles native SOL
                # without a wallet-owned wSOL ATA. DGMg PumpSwap-router buys
                # wrap-and-close the quote ATA in the same tx, so post
                # balances also show no leftover WSOL. The wallet's
                # fee-adjusted native delta is the SOL leg.
                if not (route['program'] in (JUPITER, DGMG, DFLOW) and not owned_wsol_accounts):
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
            quote_legs = [(mint, delta) for mint, delta in assets if mint in QUOTE_MINTS]
            other_assets = [(mint, delta) for mint, delta in assets if mint not in QUOTE_MINTS]
            if len(quote_legs) > 1:
                raise ValueError('Multiple quote assets moved; cross-quote settlement remains unresolved')
            quote_mint, quote_delta = quote_legs[0] if quote_legs else (None, 0)
            quote_asset = QUOTE_ASSET.get(quote_mint)
            quote_settled = (
                not settlement
                and quote_delta
                and len(other_assets) == 1
                and (other_assets[0][1] > 0) != (quote_delta > 0)
            )
            if settlement and quote_delta and other_assets:
                raise ValueError(
                    f'SOL and {quote_asset} both moved; cross-settlement remains unresolved and is not converted'
                )
            if quote_settled:
                mint, quantity = other_assets[0]
                if mint == WSOL:
                    quote_decimals = decimals.get(quote_mint)
                    if quote_decimals is None:
                        raise ValueError(f'{quote_asset} settlement is missing event-time decimals')
                    with localcontext() as context:
                        context.prec = 192
                        amount_quote = canonical(Decimal(abs(quote_delta)) / (Decimal(10) ** quote_decimals))
                        amount_sol = canonical(Decimal(abs(quantity)) / LAMPORTS)
                    from_asset = quote_asset if quote_delta < 0 else 'SOL'
                    to_asset = 'SOL' if quote_delta < 0 else quote_asset
                    quote_fields = {'amount_usdc': amount_quote} if quote_mint == USDC else {'amount_usdt': amount_quote}
                    emit('conversion', route['path'], mint=quote_mint, quantity_raw=str(abs(quote_delta)),
                         decimals=quote_decimals, amount_sol=amount_sol, **quote_fields,
                         classification='quote_conversion', from_asset=from_asset, to_asset=to_asset,
                         source=route['program'], venue=route['program'], instruction=route['instruction'],
                         owner=address, fee_sol=fee_sol if paid else '0', paid_by_wallet=paid,
                         settlement_mint=quote_mint, settlement_asset=quote_asset,
                         inner_venues=inner_venues,
                         reason=f'{quote_asset}↔SOL is a quote conversion, not a sale of a {quote_asset} or SOL position')
                    conversions += 1
                    continue
                kind = 'buy' if quantity > 0 else 'sell'
                if route['expected_kind'] and route['expected_kind'] != kind:
                    raise ValueError('Venue instruction direction conflicts with wallet exchange direction')
                quote_decimals = decimals.get(quote_mint)
                if quote_decimals is None:
                    raise ValueError(f'{quote_asset} settlement is missing event-time decimals')
                with localcontext() as context:
                    context.prec = 192
                    amount_quote = canonical(Decimal(abs(quote_delta)) / (Decimal(10) ** quote_decimals))
                allocate_fee = paid and not outside_native and not native_roles
                excluded_funding_lamports = rent_correction + episode_rent + new_token_rent
                excluded_funding_sol = canonical(Decimal(excluded_funding_lamports) / LAMPORTS)
                t22_fee = token_2022_fees[-1] if token_2022_fees else None
                rfq_fee = None
                platform_fee_usdc = None
                if rfq_platform_fees:
                    fee_qty = sum(item['quantity'] for item in rfq_platform_fees)
                    fee_mint = rfq_platform_fees[0].get('mint')
                    rfq_fee = {
                        'recipient': RFQ_FEE_FILL_ACCOUNT,
                        'pattern': 'rfq_fill_separate_top_level_transfer_checked',
                        'quantity_raw': str(fee_qty),
                        'mint': fee_mint,
                        'counted_in_wallet_delta': True,
                        'not_subtracted_again': True,
                    }
                    if fee_mint == quote_mint:
                        platform_fee_usdc = canonical(Decimal(fee_qty) / (Decimal(10) ** quote_decimals))
                quote_amount_fields = (
                    {'amount_usdc': amount_quote} if quote_mint == USDC else {'amount_usdt': amount_quote}
                )
                emit(kind, route['path'], mint=mint, quantity_raw=str(abs(quantity)),
                     decimals=decimals[mint], amount_sol=None, **quote_amount_fields,
                     classification='market',
                     source=route['program'], venue=route['program'], instruction=route['instruction'],
                     owner=address, fee_sol=fee_sol if allocate_fee else '0', paid_by_wallet=paid,
                     settlement_mint=quote_mint, settlement_asset=quote_asset,
                     token_2022_transfer_fee=t22_fee,
                     rfq_platform_fee=rfq_fee,
                     platform_fee_usdc=platform_fee_usdc,
                     excluded_funding_sol=excluded_funding_sol,
                     inner_venues=inner_venues,
                     native_cash_role_state='UNKNOWN' if native_roles or outside_native else 'PASS',
                     unresolved_native_roles=native_roles,
                     retained_account_funding=[{**item, 'evidence': hashes} for item in retained_funding],
                     observed_pre_quantity_raw=str(sum(pre.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                     observed_post_quantity_raw=str(sum(post.get(account, 0) for account, identity in owned.items() if identity['mint'] == mint)),
                     observation_scope='Transaction account keys only; no proof of wallet-wide zero inventory',
                     reason=f'Verified route and reconciled wallet {quote_asset}/token deltas; SOL fee stays SOL and is not {quote_asset} P&L')
                if allocate_fee:
                    fee_event['allocation'] = 'buy_basis' if kind == 'buy' else 'sell_exit'
                    fee_event['allocated_trade_path'] = route['path']
                    fee_event['settlement_note'] = f'Network fee is SOL; not converted into {quote_asset} consideration'
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
            from scanner.mass_search.verified_costs import classify_cost_role
            platform_accounts = set()
            if route.get('program') == JUPITER:
                accounts = route.get('accounts') or []
                # Official Jupiter route / exact_out_route platform_fee_account is index 6.
                if route.get('instruction') in (
                    'route', 'route_with_token_ledger', 'exact_out_route',
                ) and len(accounts) > 6:
                    platform_accounts.add(accounts[6])
            verified_tip_lamports = 0
            platform_fee_lamports = 0
            unverified_debit_lamports = 0
            for item in outside_native:
                if item.get('direction') != 'withdrawal':
                    continue
                role = classify_cost_role(
                    item.get('destination'),
                    proven_from_layout=item.get('destination') in platform_accounts,
                    transfer=True,
                )
                item['cost_role'] = role
                if role == 'verified_tip':
                    verified_tip_lamports += item['lamports']
                elif role == 'proven_router_or_platform_fee':
                    platform_fee_lamports += item['lamports']
                    item['counted_as_fee'] = True
                else:
                    unverified_debit_lamports += item['lamports']
                    item['counted_as_fee'] = False
            tips_lamports = verified_tip_lamports
            tips_sol = canonical(Decimal(tips_lamports) / LAMPORTS) if tips_lamports else '0'
            platform_fee_sol = canonical(Decimal(platform_fee_lamports) / LAMPORTS) if platform_fee_lamports else '0'
            unverified_debits_sol = canonical(Decimal(unverified_debit_lamports) / LAMPORTS) if unverified_debit_lamports else '0'
            network_fee_sol = fee_sol if paid else '0'
            fees_and_tips_sol = canonical(
                Decimal(str(network_fee_sol)) + Decimal(str(tips_sol)) + Decimal(str(platform_fee_sol))
            )
            allocate_fee = paid and not outside_native and not native_roles
            if mint in QUOTE_MINTS:
                quote_decimals = decimals.get(mint)
                quote_name = QUOTE_ASSET[mint]
                if quote_decimals is None:
                    raise ValueError(f'{quote_name} settlement is missing event-time decimals')
                with localcontext() as context:
                    context.prec = 192
                    amount_quote = canonical(Decimal(abs(quantity)) / (Decimal(10) ** quote_decimals))
                    amount = canonical(Decimal(abs(settlement)) / LAMPORTS)
                from_asset = quote_name if quantity < 0 else 'SOL'
                to_asset = 'SOL' if quantity < 0 else quote_name
                quote_fields = {'amount_usdc': amount_quote} if mint == USDC else {'amount_usdt': amount_quote}
                emit('conversion', route['path'], mint=mint, quantity_raw=str(abs(quantity)),
                     decimals=quote_decimals, amount_sol=amount, **quote_fields,
                     classification='quote_conversion', from_asset=from_asset, to_asset=to_asset,
                     source=route['program'], venue=route['program'], instruction=route['instruction'],
                     owner=address, fee_sol=fees_and_tips_sol, network_fee_sol=network_fee_sol,
                     tips_sol=tips_sol, paid_by_wallet=paid, settlement_mint=WSOL,
                     settlement_asset=quote_name, inner_venues=inner_venues,
                     reason=f'{quote_name}↔SOL is a quote conversion, not a sale of a {quote_name} or SOL position')
                conversions += 1
                continue
            kind = 'buy' if quantity > 0 else 'sell'
            if route['expected_kind'] and route['expected_kind'] != kind:
                raise ValueError('Venue instruction direction conflicts with wallet exchange direction')
            with localcontext() as context:
                context.prec = 192
                amount = canonical(Decimal(abs(settlement)) / LAMPORTS)
            excluded_funding_lamports = rent_correction + episode_rent + new_token_rent
            excluded_funding_sol = canonical(Decimal(excluded_funding_lamports) / LAMPORTS)
            emit(kind, route['path'], mint=mint, quantity_raw=str(abs(quantity)),
                 decimals=decimals[mint], amount_sol=amount, classification='unknown',
                 source=route['program'], venue=route['program'], instruction=route['instruction'],
                 owner=address, fee_sol=fees_and_tips_sol if allocate_fee else '0',
                 network_fee_sol=network_fee_sol, tips_sol=tips_sol,
                 platform_fee_sol=platform_fee_sol,
                 fees_and_tips_sol=fees_and_tips_sol,
                 inner_venues=inner_venues,
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
        except (ValueError, KeyError, IndexError, TypeError, OverflowError, AttributeError) as exc:
            net = None
            reason = str(exc)
            # Net-balance recovers venues with no pinned layout, not txs whose
            # layout already failed closed on wrap/nonce/funding proofs.
            first_nb = None
            try:
                meta_nb = raw.get('meta') if isinstance(raw, dict) and isinstance(raw.get('meta'), dict) else {}
                tx_nb = raw.get('transaction') if isinstance(raw, dict) else None
                message_nb = tx_nb.get('message') if isinstance(tx_nb, dict) else {}
                if not isinstance(message_nb, dict):
                    message_nb = {}
                first_nb = _first_net_balance_program(raw, _keys(message_nb, meta_nb))
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                first_nb = None
            coverage_gap = (
                reason.startswith('No reviewed outer spot swap')
                or reason.startswith('Jupiter route')
                or reason.startswith('Unrelated token transfer')
                or reason.startswith('Transaction version has no reviewed')
                or (
                    reason.startswith('No reviewed spot swap instruction for this program')
                    and first_nb == JUPITER
                )
            )
            if allow_net_balance and coverage_gap:
                try:
                    net = net_balance_reviewed_swap(raw, address)
                except (ValueError, KeyError, IndexError, TypeError, OverflowError, AttributeError):
                    net = None
            if net and reason.startswith('Unrelated token transfer'):
                unknown(reason)
            if net:
                quote_mint = net.get('quote_mint')
                mint = net['mint']
                quantity = net['quantity']
                dec = net.get('decimals')
                if dec is None and mint != 'SOL':
                    unknown(str(exc))
                    continue
                paid = False
                try:
                    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
                    message = ((raw.get('transaction') or {}).get('message')
                               if isinstance(raw.get('transaction'), dict) else {}) or {}
                    keys = _keys(message, meta)
                    paid = bool(keys) and keys[0] == address
                    fee = _integer(meta.get('fee')) if isinstance(meta.get('fee'), int) else 0
                    fee_sol = canonical(Decimal(fee) / LAMPORTS)
                except (ValueError, KeyError, IndexError, TypeError, OverflowError):
                    fee_sol = '0'
                residue = net.get('fee_residue_sol')
                if residue:
                    fee_sol = canonical(Decimal(str(fee_sol)) + abs(Decimal(residue)) / LAMPORTS)
                if net['kind'] == 'conversion':
                    quote_name = QUOTE_ASSET.get(quote_mint) or net.get('to_asset') or 'USDC'
                    quote_decimals = dec if dec is not None else 6
                    with localcontext() as context:
                        context.prec = 192
                        amount_quote = canonical(Decimal(abs(quantity)) / (Decimal(10) ** quote_decimals))
                        amount = canonical(Decimal(abs(net.get('settlement') or 0)) / LAMPORTS)
                    quote_fields = {'amount_usdc': amount_quote} if quote_mint == USDC or quote_name == 'USDC' else {'amount_usdt': amount_quote}
                    emit('conversion', net['path'], mint=mint, quantity_raw=str(abs(quantity)),
                         decimals=quote_decimals, amount_sol=amount, **quote_fields,
                         classification='quote_conversion',
                         from_asset=net.get('from_asset'), to_asset=net.get('to_asset'),
                         source=net['program'], venue=net['program'],
                         instruction=net['instruction'], owner=address, fee_sol=fee_sol,
                         paid_by_wallet=paid, settlement_asset=quote_name,
                         reason='Reviewed swap-program instruction and unambiguous wallet net (quote conversion)')
                    conversions += 1
                    used_routes.add((net['program'], net['instruction']))
                    continue
                kind = net['kind']
                if quote_mint:
                    quote_decimals = 6 if net.get('decimals') is None else dec
                    # trade mint decimals vs quote decimals: quantity is the token
                    token_decimals = dec if dec is not None else 0
                    with localcontext() as context:
                        context.prec = 192
                        amount_quote = canonical(Decimal(abs(net.get('quote_delta') or 0)) / (Decimal(10) ** (6 if quote_mint in QUOTE_MINTS else token_decimals)))
                    quote_fields = {'amount_usdc': amount_quote} if quote_mint == USDC else {'amount_usdt': amount_quote}
                    emit(kind, net['path'], mint=mint, quantity_raw=str(abs(quantity)),
                         decimals=token_decimals, amount_sol=None, **quote_fields,
                         classification='market',
                         source=net['program'], venue=net['program'],
                         instruction=net['instruction'], owner=address, fee_sol=fee_sol,
                         paid_by_wallet=paid, settlement_mint=quote_mint,
                         settlement_asset=QUOTE_ASSET.get(quote_mint),
                         reason='Reviewed swap-program instruction and unambiguous wallet net (USDC/USDT settlement)')
                else:
                    with localcontext() as context:
                        context.prec = 192
                        amount = canonical(Decimal(abs(net.get('settlement') or 0)) / LAMPORTS)
                    emit(kind, net['path'], mint=mint, quantity_raw=str(abs(quantity)),
                         decimals=dec if dec is not None else 0, amount_sol=amount,
                         classification='unknown',
                         source=net['program'], venue=net['program'],
                         instruction=net['instruction'], owner=address, fee_sol=fee_sol,
                         paid_by_wallet=paid, settlement_mint=WSOL,
                         reason='Reviewed swap-program instruction and unambiguous wallet net (SOL settlement)')
                supported += 1
                used_routes.add((net['program'], net['instruction']))
                continue
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
