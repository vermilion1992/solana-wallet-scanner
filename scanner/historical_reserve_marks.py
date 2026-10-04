"""Exact contemporaneous PumpSwap reserve marks from original transactions.

The numerical method is the quote/base token reserve ratio at the transaction's
pre or post phase.  It is a spot observation, not an execution quote or a claim
about a reporting boundary.  No stale mark, token label, caller price or receipt
is admitted.  The ordinary report owns the freshly derived consistency/clock
inputs to this private projection; uploaded certificates never reach it.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
import re

from .accounting import canonical, raw_quantity
from .collector import _valid_account
from .investigation import PUMP_SWAP, WSOL, _keys, _program, _route
from .providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from .transaction_format import _needs_instruction_view, supported_transaction_format

VERSION = 'historical-pumpswap-reserve-marks-v1'
METHOD = 'pumpswap-exact-phase-quote-base-reserve-ratio-sol-v1'
MAX_LINKED_RECORDS = 40_000
MAX_BALANCES = 200_000
HASH = re.compile(r'^[a-f0-9]{64}$')
IDL = {'commit': 'cb188ce08b5069196eef1f3e4a0c43b70099793b',
       'path': 'tests/fixtures/retained_protocol_funding/pump_amm.json',
       'sha256': '2091433899b07d003d98118ae6cd3c628960fd393b40710b6e15bce6d0e7f2d1'}
SCOPE = 'Original transaction phase pool-reserve spot mark; no report-boundary or executable liquidation assertion'


def _check(known, reason, evidence=(), *, paths=()):
    refs = sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and refs else 'UNKNOWN', 'reason': reason,
            'scope': SCOPE, 'evidence': refs, 'raw_paths': sorted(set(paths)),
            'dependencies': ['original_pool_vault_identity', 'linked_pool_phase_reserves', 'exact_phase_chronology']}


def _phase_balances(raw, keys, field):
    rows = raw['meta'].get(field)
    if not isinstance(rows, list) or len(rows) > MAX_BALANCES:
        raise ValueError('Pool phase token-balance population is missing or exceeds the inspection budget')
    by_account = {}
    for ordinal, row in enumerate(rows):
        index = row.get('accountIndex') if isinstance(row, dict) else None
        if type(index) is not int or not 0 <= index < len(keys):
            raise ValueError('A malformed phase balance cannot establish disjointness from the pool vaults')
        account = keys[index]
        if account in by_account:
            raise ValueError('Duplicate phase account balances cannot establish a unique reserve')
        by_account[account] = (row, f'meta.{field}.{ordinal}')
    return by_account


def _reserve(balance, *, mint, owner, program, quote=False):
    row, path = balance
    units = row.get('uiTokenAmount')
    if (row.get('mint') != mint or row.get('owner') != owner or row.get('programId') != program
        or not isinstance(units, dict) or type(units.get('decimals')) is not int
        or not 0 <= units['decimals'] <= 255 or quote and units['decimals'] != 9):
        raise ValueError('Pool vault owner, mint, token program or decimal identity does not match its fixed route role')
    amount = units.get('amount')
    if not isinstance(amount, str) or re.fullmatch(r'[0-9]{1,20}', amount) is None:
        raise ValueError('Pool reserve units require the original RPC unsigned raw integer string')
    quantity = raw_quantity(amount)
    if quantity <= 0 or quantity > 2**64 - 1:
        raise ValueError('Zero or malformed pool reserve cannot establish a finite positive spot mark')
    return quantity, units['decimals'], [path + '.' + suffix for suffix in
        ('owner', 'mint', 'programId', 'uiTokenAmount.amount', 'uiTokenAmount.decimals')]


def _points(raw):
    if not isinstance(raw, dict) or not supported_transaction_format(raw):
        raise ValueError('Original pool transaction format is missing or unsupported')
    if raw.get('meta', {}).get('err') is not None:
        return []  # A failed call is not evidence of an executed pool state transition.
    from .compiled_instructions import normalize_transaction
    semantic = normalize_transaction(raw)['raw'] if _needs_instruction_view(raw) else raw
    message, meta = semantic['transaction']['message'], semantic['meta']
    keys = _keys(message, meta)
    if len(keys) != len(set(keys)) or any(not _valid_account(key) for key in keys):
        raise ValueError('Pool identities require unique public account keys')
    instructions = message.get('instructions')
    if not isinstance(instructions, list):
        raise ValueError('Original outer instruction population is absent')
    routes = []
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict):
            raise ValueError('Malformed outer instruction has unresolved pool relevance')
        if 'programIdIndex' in instruction:
            ordinal = instruction['programIdIndex']
            if (type(ordinal) is not int or not 0 <= ordinal < len(keys)
                or 'programId' in instruction and instruction['programId'] != keys[ordinal]):
                raise ValueError('Conflicting or malformed instruction program references cannot hide pool activity')
        if _program(instruction, keys) != PUMP_SWAP:
            continue
        from .instruction_scope import inspect_instruction
        inspect_instruction(instruction, keys, path=f'transaction.message.instructions.{index}')
        route = _route(instruction, keys)
        accounts = route['accounts']
        if (route['instruction'] not in ('buy', 'buy_exact_quote_in', 'sell') or len(accounts) < 17
            or accounts[16] != PUMP_SWAP or accounts[4] != WSOL
            or accounts[11] not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM) or accounts[12] != TOKEN_PROGRAM
            or accounts[3] == WSOL or len({accounts[n] for n in (0, 3, 4, 7, 8)}) != 5
            or any(not _valid_account(account) for account in accounts)):
            raise ValueError('PumpSwap route does not have the pinned base/legacy-WSOL quote vault contract')
        routes.append((index, route))
    if not routes:
        return []
    phases = {phase: _phase_balances(semantic, keys, field) for phase, field in
              (('pre', 'preTokenBalances'), ('post', 'postTokenBalances'))}
    points = []
    for index, route in routes:
        accounts = route['accounts']
        decimals = None
        for phase, balances in phases.items():
            if accounts[7] not in balances or accounts[8] not in balances:
                raise ValueError('Both exact pool vault reserves are required at each original transaction phase')
            base, precision, base_paths = _reserve(balances[accounts[7]], mint=accounts[3], owner=accounts[0], program=accounts[11])
            quote, _, quote_paths = _reserve(balances[accounts[8]], mint=WSOL, owner=accounts[0], program=TOKEN_PROGRAM, quote=True)
            if decimals is not None and precision != decimals:
                raise ValueError('Base precision changes across original pool phases')
            decimals = precision
            with localcontext() as context:
                context.prec = 100
                # Retain exact integer ratio alongside the decimal display.
                numerator, denominator = quote * 10**precision, base * 10**9
                price = canonical(Decimal(numerator) / Decimal(denominator))
            points.append({'phase': phase, 'pool': accounts[0], 'mint': accounts[3],
                'base_vault': accounts[7], 'quote_vault': accounts[8], 'base_program': accounts[11],
                'base_decimals': precision, 'base_reserve_raw': str(base), 'quote_reserve_raw': str(quote),
                'quote_mint': WSOL, 'mark_sol_per_token': price,
                'price_ratio_numerator': str(numerator), 'price_ratio_denominator': str(denominator),
                'raw_paths': [f'transaction.message.instructions.{index}.accounts.{n}' for n in (0, 3, 4, 7, 8, 11, 12)]
                    + base_paths + quote_paths})
    # Repeated calls to the same pool share the whole transaction phase; they
    # must not become several independent observations or intermediate prices.
    output = {}
    for point in points:
        key = point['pool'], point['mint'], point['phase']
        old = output.get(key)
        if old is not None:
            old['raw_paths'] = sorted(set(old['raw_paths'] + point['raw_paths']))
        else:
            output[key] = point
    return [output[key] for key in sorted(output)]


def project_historical_reserve_marks(records, *, all_records, raw_sources, consistency, chronology):
    """Private projection from checksum-bound records and fresh normal receipts."""
    from .wallet_positions import _verified_records
    records, all_records, raw_sources = list(records), list(all_records), list(raw_sources)
    if len(records) + len(all_records) > 2 * MAX_LINKED_RECORDS:
        raise ValueError('Historical reserve mark linked-record budget exceeded')
    selected = {r.get('signature') for r in records if isinstance(r, dict) and isinstance(r.get('signature'), str)}
    grouped = defaultdict(dict)
    for row in _verified_records(all_records + records, raw_sources):
        if row.get('signature') not in selected:
            continue
        signature, digest = row.get('signature'), row.get('evidence_hash')
        previous = grouped[signature].get(digest)
        if previous is not None and previous.get('raw') != row.get('raw'):
            row = {**row, 'raw': None}
        grouped[signature][digest] = row
    if sum(len(v) for v in grouped.values()) > MAX_LINKED_RECORDS:
        raise ValueError('Historical reserve mark distinct linked-record budget exceeded')
    balance_count = 0
    for variants in grouped.values():
        for row in variants.values():
            raw = row.get('raw')
            meta = raw.get('meta') if isinstance(raw, dict) else None
            if isinstance(meta, dict):
                balance_count += sum(len(meta[field]) for field in ('preTokenBalances', 'postTokenBalances')
                                     if isinstance(meta.get(field), list))
    if balance_count > MAX_BALANCES:
        raise ValueError('Historical reserve mark phase-balance inspection budget exceeded')
    marks, receipts = [], {}
    for signature, variants in sorted(grouped.items()):
        hashes, parsed, gaps = sorted(h for h in variants if isinstance(h, str) and HASH.fullmatch(h)), [], []
        for row in variants.values():
            try:
                parsed.append(_points(row.get('raw')))
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
                gaps.append(str(exc))
        semantic = lambda rows: [{k: v for k, v in point.items() if k != 'raw_paths'} for point in rows]
        agreed = bool(parsed) and not gaps and all(semantic(points) == semantic(parsed[0]) for points in parsed[1:])
        group = consistency.get('transactions', {}).get(signature, {})
        clock = chronology.get('transactions', {}).get(signature, {})
        native = group.get('native', {}).get('checks', {})
        required = [group.get('identity', {})] + [native.get(key, {}) for key in
            ('transaction_format', 'execution', 'source_set')]
        valid_clock = (clock.get('state') == clock.get('time_state') == 'PASS'
            and type(clock.get('slot')) is int and clock['slot'] >= 0 and type(clock.get('canonical_time')) is int)
        known = agreed and valid_clock and all(row.get('state') == 'PASS' for row in required)
        receipt = _check(known, '; '.join(sorted(set(gaps))) if gaps else
            'Every linked original agrees on exact contemporaneous pool phase reserves and shared chronology.' if known else
            'A linked original, reserve identity, source inventory or exact clock is missing/conflicting/unsupported.',
            hashes + clock.get('evidence', []) + [h for row in required for h in row.get('evidence', [])])
        receipts[signature] = receipt
        if not known:
            continue
        for index, point in enumerate(parsed[0]):
            paths = sorted({p for points in parsed for p in points[index]['raw_paths']})
            marks.append({**point, 'raw_paths': paths, 'signature': signature, 'slot': clock['slot'],
                'block_time': clock['canonical_time'], 'transaction_index': clock.get('transaction_index'),
                'method': METHOD, 'check': _check(True, receipt['reason'], receipt['evidence'], paths=paths),
                'boundary_eligibility': 'EXACT_SIGNATURE_PHASE_ONLY', 'executable_liquidation_state': 'UNKNOWN'})
    return {'version': VERSION, 'method': METHOD, 'scope': SCOPE, 'schema': IDL,
        'marks': marks, 'records': receipts,
        'historical_boundary_completeness': 'UNKNOWN', 'qualification': False,
        'provider_requests': 0, 'credential_lookups': 0,
        'limitations': ['Observed reserve ratio is a spot marking method, not executable proceeds, liquidity depth or token eligibility.',
            'A mark cannot be carried to another signature, transaction phase, slot or report boundary.',
            'All boundary assets and external flows still require their independent accepted evidence.']}
