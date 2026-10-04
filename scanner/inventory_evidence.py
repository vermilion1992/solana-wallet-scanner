"""Original-byte, offline current inventory observations.

RPC context slots locate observations, not reporting timestamps or historical
ownership. Token account lamports are retained separately from token units;
these receipts neither value assets nor certify wallet-wide financial results.
Imported integrity also does not establish network authenticity.
"""
from __future__ import annotations

from collections import defaultdict
import base64
import binascii
import hashlib
import re

from .collector import _valid_account
from .decoder import SYSTEM_ID
from .json_boundary import canonical_bytes, parse_json
from .providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from .wallet_identity import ACCOUNT_SOURCE_VERSION, account_info_source, account_source_bytes

VERSION = 'current-inventory-evidence-v1'
SOURCE_VERSION = 'inventory-rpc-source-v1'
AFFINITY_VERSION = 'inventory-request-affinity-v1'
MAX_SOURCES = 10_000
MAX_ACCOUNTS = 100_000
MAX_NODES = 1_000_000
MAX_PREIMAGE_BYTES = 12 * 1024 * 1024
U64 = 2**64 - 1
HASH = re.compile(r'^[a-f0-9]{64}$')
AMOUNT = re.compile(r'^[0-9]{1,20}$')
PROGRAMS = (TOKEN_PROGRAM, TOKEN_2022_PROGRAM)
WSOL = 'So11111111111111111111111111111111111111112'
SCOPE = 'Archived finalized current RPC observations; no historical/report-boundary or valuation proof'
_FIELDS = {'version', 'request_hash', 'response_hash', 'request_base64', 'response_base64'}
_AFFINITY_FIELDS = {'version', 'source_hash', 'source_preimage_base64'}
_INVENTORY_ROLES = {'owned-accounts', 'native-balance', 'wallet-account-info', 'wallet-account-source',
                    'inventory-source', 'inventory-affinity', 'boundary-inventory'}
_METHODS = {'getBalance', 'getAccountInfo', 'getTokenAccountsByOwner'}
_COMPONENTS = ('native_account', 'native_balance', TOKEN_PROGRAM, TOKEN_2022_PROGRAM)


def _hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _u64(value):
    return type(value) is int and 0 <= value <= U64


def _amount(value):
    if not isinstance(value, str) or not AMOUNT.fullmatch(value) or int(value) > U64:
        raise ValueError('Token units must be a bounded unsigned raw integer string')
    return str(int(value))


def _check(known, reason, hashes=(), **fields):
    evidence = sorted({h for h in hashes if _hash(h)})
    return {'state': 'PASS' if known and evidence else 'UNKNOWN', 'scope': SCOPE,
            'reason': reason, 'evidence': evidence, **fields}


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key != 'raw_paths'}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def inventory_source(request_bytes, response_bytes):
    """Retain exact bytes, without producing any trusted inventory declaration."""
    value = account_info_source(request_bytes, response_bytes)
    try:
        request = parse_json(request_bytes, max_nodes=MAX_NODES)
    except (ValueError, TypeError):
        request = None
    if not isinstance(request, dict) or request.get('method') != 'getAccountInfo':
        value['version'] = SOURCE_VERSION
    return value


def inventory_source_bytes(payload):
    if (not isinstance(payload, dict) or set(payload) != _FIELDS
            or payload.get('version') not in (SOURCE_VERSION, ACCOUNT_SOURCE_VERSION)):
        raise ValueError('Inventory requires an exact supported original-byte envelope')
    return account_source_bytes({**payload, 'version': ACCOUNT_SOURCE_VERSION})


def _request_bytes(payload):
    """Verify a request separately for negative routing after response loss."""
    from .wallet_identity import _bytes
    return _bytes(payload, 'request')


def _lead(request, wallet):
    """Negative scope only; no response or completeness decision is admitted."""
    if not isinstance(request, dict) or request.get('method') not in _METHODS:
        return None
    method, params = request['method'], request.get('params')
    if not isinstance(params, list) or not params or not _valid_account(params[0]):
        return set(_COMPONENTS)
    if params[0] != wallet:
        return set()
    if method == 'getAccountInfo':
        return {'native_account'}
    if method == 'getBalance':
        return {'native_balance'}
    selector = params[1] if len(params) > 1 else None
    program = selector.get('programId') if isinstance(selector, dict) else None
    return {program} if program in PROGRAMS else set(PROGRAMS)


def _role_scope(kind):
    if kind in ('wallet-account-info', 'wallet-account-source'):
        return {'native_account'}
    if kind == 'native-balance':
        return {'native_balance'}
    if kind == 'owned-accounts':
        return set(PROGRAMS)
    return set(_COMPONENTS)


def _direct_request_lead(payload, wallet):
    if not isinstance(payload, dict):
        return None, None
    if 'request_base64' in payload:
        try:
            raw = _request_bytes(payload)
            return _lead(parse_json(raw, max_nodes=MAX_NODES), wallet), raw
        except (ValueError, TypeError, KeyError):
            return set(_COMPONENTS), None
    if payload.get('method') in _METHODS:
        # Existing collector bodies do not preserve complete original RPC bytes.
        address = payload.get('address', payload.get('owner'))
        if _valid_account(address) and address != wallet:
            return set(), None
        method = payload['method']
        return ({'native_account'} if method == 'getAccountInfo' else {'native_balance'}
                if method == 'getBalance' else {payload['program']} if payload.get('program') in PROGRAMS
                else set(PROGRAMS)), None
    return None, None


def _request_lead(payload, wallet):
    # A surrounding advisory object cannot hide a relevant original request.
    # Nested bodies remain rejecting dependencies: only the exact top-level
    # source envelope is admissible for a positive component observation.
    nodes, seen, inspected, scopes, requests = [payload], set(), 0, [], []
    while nodes:
        node = nodes.pop()
        if not isinstance(node, (dict, list)) or id(node) in seen:
            continue
        seen.add(id(node))
        inspected += 1
        if inspected > MAX_NODES:
            return set(_COMPONENTS), None
        if isinstance(node, dict):
            scope, raw = _direct_request_lead(node, wallet)
            if scope is not None:
                scopes.append(scope)
                if raw is not None:
                    requests.append(raw)
                elif scope:
                    requests.append(None)
            nodes.extend(value for value in node.values() if isinstance(value, (dict, list)))
        else:
            nodes.extend(value for value in node if isinstance(value, (dict, list)))
    if not scopes:
        return None, None
    union = set().union(*scopes)
    unique = set(requests)
    return union, next(iter(unique)) if len(unique) == 1 else None


def inventory_request_affinities(raw_sources, *, wallet):
    """Freeze negative request selectors, never a response/completion receipt.

    Import/save callers bind these internally archived records to their immutable
    input inventory. Public manifests cannot supply this internal record type.
    """
    rows = {}
    for source in raw_sources:
        if not isinstance(source, dict) or not _hash(source.get('hash')):
            continue
        digest, payload = source['hash'], source.get('payload')
        try:
            preimage = canonical_bytes(payload, max_nodes=MAX_NODES, string_keys=True) if payload is not None else None
            checksum_valid = preimage is not None and len(preimage) <= MAX_PREIMAGE_BYTES and hashlib.sha256(preimage).hexdigest() == digest
        except (ValueError, TypeError):
            checksum_valid = False
        scope, raw = _request_lead(payload, wallet) if checksum_valid else (set(_COMPONENTS), None)
        if scope == set():
            continue
        if scope is None and source.get('kind') not in _INVENTORY_ROLES:
            continue
        # The source preimage binds the original request cryptographically.
        # Do not expose another request/response envelope at the affinity root:
        # other metadata interpreters must not mistake it for a second account
        # response or an independently admissible identity observation.
        affinity = {'version': AFFINITY_VERSION, 'source_hash': digest,
                    'source_preimage_base64': base64.b64encode(preimage).decode('ascii') if checksum_valid else None}
        if digest in rows and rows[digest] != affinity:
            affinity['source_preimage_base64'] = None
        rows[digest] = affinity
    return [rows[digest] for digest in sorted(rows)]


def _affinity(payload, wallet):
    if (not isinstance(payload, dict) or set(payload) != _AFFINITY_FIELDS
            or payload.get('version') != AFFINITY_VERSION or not _hash(payload.get('source_hash'))):
        raise ValueError('Frozen inventory request affinity is malformed')
    encoded = payload['source_preimage_base64']
    if encoded is None:
        return payload['source_hash'], set(_COMPONENTS)
    if not isinstance(encoded, str) or len(encoded) > ((MAX_PREIMAGE_BYTES + 2) // 3) * 4:
        raise ValueError('Frozen inventory canonical preimage is missing or oversized')
    try:
        original = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Frozen inventory canonical preimage has malformed encoding') from exc
    if (len(original) > MAX_PREIMAGE_BYTES or base64.b64encode(original).decode('ascii') != encoded
            or hashlib.sha256(original).hexdigest() != payload['source_hash']):
        raise ValueError('Frozen inventory source/request routing disagrees with the original source hash')
    source = parse_json(original, max_nodes=MAX_NODES)
    if canonical_bytes(source, max_nodes=MAX_NODES, string_keys=True) != original:
        raise ValueError('Frozen inventory source preimage must be canonical')
    scope, _request = _request_lead(source, wallet)
    return payload['source_hash'], set(_COMPONENTS) if scope is None else scope


def _rpc(payload, wallet):
    original = inventory_source_bytes(payload)
    request, response = (parse_json(original[name], max_nodes=MAX_NODES) for name in ('request', 'response'))
    if (not isinstance(request, dict) or set(request) != {'jsonrpc', 'id', 'method', 'params'}
            or request.get('jsonrpc') != '2.0' or request.get('method') not in _METHODS
            or not (type(request.get('id')) is int or isinstance(request.get('id'), str))
            or not isinstance(response, dict) or set(response) != {'jsonrpc', 'id', 'result'}
            or response.get('jsonrpc') != '2.0' or type(response.get('id')) is not type(request['id'])
            or response.get('id') != request['id']):
        raise ValueError('Inventory RPC method, matching ID or successful response is unsupported')
    method, params = request['method'], request['params']
    if (payload['version'] == ACCOUNT_SOURCE_VERSION) != (method == 'getAccountInfo'):
        raise ValueError('Inventory source version disagrees with its account method')
    expected = 3 if method == 'getTokenAccountsByOwner' else 2
    if not isinstance(params, list) or len(params) != expected or params[0] != wallet:
        raise ValueError('Inventory request must bind the exact wallet and method arguments')
    options = params[-1]
    allowed = {'commitment', 'minContextSlot'} | ({'encoding'} if method != 'getBalance' else set())
    if (not isinstance(options, dict) or set(options) - allowed or options.get('commitment') != 'finalized'
            or 'minContextSlot' in options and not _u64(options['minContextSlot'])
            or method == 'getAccountInfo' and options.get('encoding') not in ('base64', 'jsonParsed')
            or method == 'getTokenAccountsByOwner' and options.get('encoding') != 'jsonParsed'):
        raise ValueError('Inventory request requires supported finalized options; minContextSlot is only a floor')
    program = None
    if method == 'getTokenAccountsByOwner':
        selector = params[1]
        if not isinstance(selector, dict) or set(selector) != {'programId'} or selector['programId'] not in PROGRAMS:
            raise ValueError('Token inventory requires one exact program query, not a mint filter')
        program = selector['programId']
    result = response['result']
    context = result.get('context') if isinstance(result, dict) else None
    slot = context.get('slot') if isinstance(context, dict) else None
    if (not isinstance(result, dict) or set(result) != {'context', 'value'}
            or not _u64(slot) or slot < options.get('minContextSlot', 0)):
        raise ValueError('Inventory response requires a bounded exact context slot satisfying the request floor')
    return method, program, slot, result['value']


def _token(row, wallet, program, index):
    if not isinstance(row, dict) or set(row) != {'pubkey', 'account'} or not _valid_account(row.get('pubkey')):
        raise ValueError('Token query row requires an exact valid account pubkey and body')
    account = row['account']
    data = account.get('data') if isinstance(account, dict) else None
    parsed = data.get('parsed') if isinstance(data, dict) else None
    info = parsed.get('info') if isinstance(parsed, dict) else None
    amount = info.get('tokenAmount') if isinstance(info, dict) else None
    if (not isinstance(account, dict) or account.get('owner') != program or account.get('executable') is not False
            or not _u64(account.get('lamports')) or not isinstance(parsed, dict) or parsed.get('type') != 'account'
            or not isinstance(info, dict) or info.get('owner') != wallet or not _valid_account(info.get('mint'))
            or not isinstance(amount, dict) or type(amount.get('decimals')) is not int or not 0 <= amount['decimals'] <= 255
            or type(info.get('isNative')) is not bool or info.get('state') not in ('initialized', 'frozen')):
        raise ValueError('Token query row program, event owner, raw units, native mode or initialized state is malformed')
    units = _amount(amount.get('amount'))
    reserve = None
    if info['isNative']:
        native = info.get('rentExemptReserve')
        if info['mint'] != WSOL or amount['decimals'] != 9 or not isinstance(native, dict):
            raise ValueError('Native token representation requires WSOL, nine decimals and an explicit reserve')
        reserve = _amount(native.get('amount'))
        if int(reserve) + int(units) > account['lamports']:
            raise ValueError('Native token units/reserve exceed the separately observed account lamports')
    close = info.get('closeAuthority', wallet)
    if not _valid_account(close):
        raise ValueError('Token account close authority is malformed')
    return {'account': row['pubkey'], 'program': program, 'owner': wallet, 'mint': info['mint'],
            'quantity_raw': units, 'decimals': amount['decimals'], 'account_lamports': str(account['lamports']),
            'is_native': info['isNative'], 'native_reserve_raw': reserve, 'state': info['state'],
            'close_authority': close, 'raw_paths': [f'response.result.value[{index}].pubkey',
                f'response.result.value[{index}].account.owner', f'response.result.value[{index}].account.lamports',
                f'response.result.value[{index}].account.data.parsed.info']}


def _observation(payload, wallet):
    method, program, slot, value = _rpc(payload, wallet)
    if method == 'getBalance':
        if not _u64(value):
            raise ValueError('Native balance must be exact unsigned integer lamports')
        return 'native_balance', {'slot': slot, 'lamports': str(value), 'raw_paths': ['response.result.value']}
    if method == 'getAccountInfo':
        if (not isinstance(value, dict) or value.get('owner') != SYSTEM_ID or value.get('executable') is not False
                or not _u64(value.get('lamports')) or not isinstance(value.get('data'), (dict, list, str))):
            raise ValueError('Current wallet account must be present, system-owned and nonexecutable')
        return 'native_account', {'slot': slot, 'lamports': str(value['lamports']), 'owner': SYSTEM_ID,
                                 'executable': False, 'raw_paths': ['response.result.value.lamports',
                                     'response.result.value.owner', 'response.result.value.executable']}
    if not isinstance(value, list) or len(value) > MAX_ACCOUNTS:
        raise ValueError('Token query account population is malformed or exceeds its bounded budget')
    accounts = []
    for index, row in enumerate(value):
        accounts.append(_token(row, wallet, program, index))
    if len({row['account'] for row in accounts}) != len(accounts):
        raise ValueError('Duplicate account pubkeys cannot certify a token-program enumeration')
    amounts = {}
    for row in accounts:
        prior = amounts.get(row['mint'])
        if prior and prior['decimals'] != row['decimals']:
            raise ValueError('A mint has contradictory decimal precision in the same token-program query')
        if prior is None:
            prior = amounts[row['mint']] = {'mint': row['mint'], 'program': program,
                                           'decimals': row['decimals'], 'quantity_raw': '0'}
        prior['quantity_raw'] = str(int(prior['quantity_raw']) + int(row['quantity_raw']))
    return program, {'slot': slot, 'accounts': sorted(accounts, key=lambda r: r['account']),
                     'mint_totals': [amounts[mint] for mint in sorted(amounts)],
                     'account_count': len(accounts), 'raw_paths': ['response.result.value']}


def derive_inventory_evidence(raw_sources, *, wallet, window=None, source_receipts=()):
    """Replay component facts, rejecting every linked relevant alternative.

    Affinities may retain a negative dependency after loss. They never replace
    the original response; caller PASS/completion/event declarations are not
    inputs to this admission path. Sparse/current inventories remain distinct
    from historical owner populations and exact report-boundary inventories.
    """
    if not _valid_account(wallet):
        raise ValueError('Inventory requires a valid public wallet')
    sources = list(raw_sources)
    supplied_hashes = {row.get('hash') for row in sources if isinstance(row, dict)}
    for receipt in source_receipts:
        if isinstance(receipt, dict) and _hash(receipt.get('hash')) and receipt['hash'] not in supplied_hashes:
            sources.append({'hash': receipt['hash'], 'kind': receipt.get('kind', receipt.get('role')), 'payload': None})
            supplied_hashes.add(receipt['hash'])
    bodies, affinities, invalid_affinities = defaultdict(list), defaultdict(set), []
    for source in sources:
        if not isinstance(source, dict) or not _hash(source.get('hash')):
            continue
        digest, payload = source['hash'], source.get('payload')
        if source.get('kind') == 'inventory-affinity' or isinstance(payload, dict) and payload.get('version') == AFFINITY_VERSION:
            try:
                if hashlib.sha256(canonical_bytes(payload, max_nodes=MAX_NODES, string_keys=True)).hexdigest() != digest:
                    raise ValueError('Frozen inventory affinity checksum disagrees')
                target, scope = _affinity(payload, wallet)
                affinities[target].update(scope)
            except (ValueError, TypeError, KeyError):
                invalid_affinities.append(digest)
        else:
            bodies[digest].append(source)
    rows = {key: [] for key in _COMPONENTS}
    budget = len(bodies) > MAX_SOURCES
    for digest in sorted(set(bodies) | set(affinities)):
        supplied = bodies.get(digest, [])
        frozen_scope = affinities.get(digest, set())
        relevant = set(frozen_scope)
        missing = not supplied
        observed = []
        reason = 'Original current inventory source is unavailable'
        for source in supplied:
            payload = source.get('payload')
            try:
                body_valid = payload is not None and hashlib.sha256(
                    canonical_bytes(payload, max_nodes=MAX_NODES, string_keys=True)).hexdigest() == digest
            except (ValueError, TypeError):
                body_valid = False
            if payload is not None and not body_valid:
                # A previously frozen original request may narrow only the
                # negative dependency. The changed body's own foreign scope
                # never supplies a convenient exclusion or a positive fact.
                relevant.update(frozen_scope if digest in affinities else _COMPONENTS)
                missing = True
                reason = 'Inventory containing source checksum disagrees; its convenient disjoint scope is not trusted'
                continue
            scope, _request = _request_lead(payload, wallet)
            if scope is None:
                if payload is None and digest in affinities:
                    scope = set(frozen_scope)
                elif source.get('kind') in _INVENTORY_ROLES:
                    scope = _role_scope(source['kind'])
                elif payload is None:
                    # An opaque unavailable source without frozen routing cannot
                    # be proved irrelevant by its caller-supplied role label.
                    scope = set(_COMPONENTS)
                else:
                    continue
            relevant.update(scope)
            if not scope:
                continue
            try:
                if not body_valid:
                    raise ValueError('Inventory original body is missing or disagrees with its canonical checksum')
                component, fact = _observation(payload, wallet)
                observed.append((component, fact))
            except (ValueError, TypeError, KeyError, OverflowError):
                missing = True
                reason = 'Still-linked original inventory source is unavailable, malformed or unsupported; no completion flags are accepted'
        if not relevant:
            continue
        for component in relevant:
            facts = [fact for key, fact in observed if key == component]
            valid = not missing and bool(facts)
            unique = {canonical_bytes(_semantic(fact)) for fact in facts}
            if len(unique) > 1:
                valid, reason = False, 'Repeated source hash has conflicting inventory interpretations'
            rows[component].append(_check(valid, 'Original finalized component observations validate independently' if valid else reason,
                [digest], observations=facts if valid else []))
    components = {}
    for component in _COMPONENTS:
        versions = rows[component]
        points = defaultdict(list)
        for row in versions:
            for fact in row['observations']:
                points[fact['slot']].append((row['evidence'][0], fact))
        conflicts = []
        observations = []
        for slot, facts in sorted(points.items()):
            comparable = [_semantic(fact) for _digest, fact in facts]
            if len({canonical_bytes(fact) for fact in comparable}) > 1:
                conflicts.append(slot)
            else:
                observations.append({**facts[0][1], 'evidence': sorted({h for h, _fact in facts})})
        evidence = [h for row in versions for h in row['evidence']] + invalid_affinities
        components[component] = _check(not budget and not invalid_affinities and bool(versions)
            and all(row['state'] == 'PASS' for row in versions) and not conflicts,
            'All linked finalized observations agree at each exact context slot' if not conflicts else
            'Linked observations conflict at the same exact context slot', evidence,
            observations=observations, versions=versions, conflicting_slots=conflicts)
    native_points = defaultdict(list)
    for component in ('native_account', 'native_balance'):
        for fact in components[component]['observations']:
            native_points[fact['slot']].append(fact)
    native_conflicts = [slot for slot, facts in native_points.items() if len({fact['lamports'] for fact in facts}) > 1]
    native_known = any(components[key]['state'] == 'PASS' for key in ('native_account', 'native_balance'))
    native_required_ok = all(not rows[key] or components[key]['state'] == 'PASS' for key in ('native_account', 'native_balance'))
    native = _check(native_known and native_required_ok and not native_conflicts,
        'Wallet SOL lamports remain separate from token account lamports and token units',
        [h for key in ('native_account', 'native_balance') for h in components[key]['evidence']],
        observations=[{'slot': slot, 'lamports': facts[0]['lamports'],
                       'evidence': sorted({h for fact in facts for h in fact['evidence']})}
                      for slot, facts in sorted(native_points.items()) if slot not in native_conflicts],
        conflicting_slots=sorted(native_conflicts))
    by_program = {program: {fact['slot']: fact for fact in components[program]['observations']} for program in PROGRAMS}
    shared_slots = set(native_points).difference(native_conflicts)
    for program in PROGRAMS:
        shared_slots.intersection_update(by_program[program])
    combined, aggregate_gaps = [], []
    for slot in sorted(shared_slots):
        accounts = [row for program in PROGRAMS for row in by_program[program][slot]['accounts']]
        totals = {}
        if len({row['account'] for row in accounts}) != len(accounts):
            aggregate_gaps.append('The same account pubkey appears in both token-program queries')
            continue
        for row in accounts:
            prior = totals.get(row['mint'])
            if prior and (prior['decimals'], prior['program']) != (row['decimals'], row['program']):
                aggregate_gaps.append('A mint has conflicting program/decimal identity across the same-slot account population')
                break
            if prior is None:
                prior = totals[row['mint']] = {'mint': row['mint'], 'program': row['program'],
                                               'decimals': row['decimals'], 'quantity_raw': '0'}
            prior['quantity_raw'] = str(int(prior['quantity_raw']) + int(row['quantity_raw']))
        else:
            combined.append({'slot': slot, 'native_lamports': native_points[slot][0]['lamports'],
                'accounts': accounts, 'mint_totals': [totals[mint] for mint in sorted(totals)],
                'account_count': len(accounts), 'evidence': sorted({h for key in _COMPONENTS
                    for fact in components[key]['observations'] if fact['slot'] == slot for h in fact['evidence']})})
    evidence = sorted({h for row in components.values() for h in row['evidence']})
    aggregate = _check(native['state'] == 'PASS' and all(components[program]['state'] == 'PASS' for program in PROGRAMS)
        and bool(combined) and not aggregate_gaps,
        '; '.join(aggregate_gaps) or 'Exact matching finalized context slots are required across native SOL and BOTH current token-program queries; minContextSlot is only a floor',
        evidence, observations=combined)
    boundary = _check(False, 'Current context slots have no admitted exact reporting-time boundary mapping or historical state/bridging contract',
        evidence, dependencies=['exact_opening_inventory', 'exact_closing_inventory', 'exact_boundary_time_state_contract'],
        window=dict(window) if isinstance(window, dict) else None)
    return {'version': VERSION, 'scope': SCOPE, 'components': {'native_account': components['native_account'],
        'native_balance': components['native_balance'], 'native_lamports': native,
        'token_programs': {program: components[program] for program in PROGRAMS},
        'same_slot_inventory': aggregate, 'report_boundaries': boundary},
        'source_dependencies': evidence, 'inspection_budget': {'max_sources': MAX_SOURCES, 'sources': len(bodies),
            'state': 'UNKNOWN' if budget else 'PASS'}, 'historical_population_state': 'UNKNOWN',
        'valuation_state': 'UNKNOWN', 'external_flow_state': 'UNKNOWN', 'qualification': False,
        'provider_requests': 0, 'credential_lookups': 0}
