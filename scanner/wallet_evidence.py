"""Offline raw-fact adapter for the existing wallet accounting path.

The archive loader authenticates immutable links and verifies their bytes before
calling this module. These functions recompute semantic facts; supplied PASS
receipts, normalized events and selected-record inventories are never historical
population certificates. Observed account facts remain useful while B1 is open.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
import hashlib
import json
import re

from .accounting import analyze, canonical, decimal, raw_quantity, utc, median, validate_fee_allocations
from .collector import _valid_account
from .decoder import TOKEN_IDS, SYSTEM_ID, ASSOCIATED_ID, decode_transactions
from .instruction_scope import inspect_instruction
from .investigation import _keys, _route, decode_supported_swaps, WSOL
from .position_evidence import _balance, _quantity_point, VENUES
from .source_consistency import (assess_source_consistency, source_archive_receipts,
                                 apply_unresolved_chronology, SOURCE_HASH_LIMIT)
from .chronology_evidence import assess_chronology, assess_interval_membership
from .transaction_format import supported_transaction_format

VERSION = 'wallet-raw-evidence-v8'
HASH = re.compile(r'^[a-f0-9]{64}$')
MAX_RECORDS = SOURCE_HASH_LIMIT
MAX_ACCOUNT_STEPS = 100_000
MAX_INDEXED_RECORDS = 10_000
OBSERVED_SCOPE = 'Selected archived records only; hidden accounts and intervening records are unproved'
_NONTRANSACTION_ROLES = {'signature-page', 'block-order', 'snapshot-slot', 'owned-accounts', 'native-balance',
                        'classification', 'valuation', 'boundary-inventory', 'historical-mark', 'capital-flow',
                        'synthetic-population', 'population-inventory', 'current-mint-controls', 'archive-native-dependencies',
                        'query-affinity', 'wallet-account-info', 'wallet-account-source', 'wallet-identity-affinity'}
_INDEXED_ROLES = {'indexed-page', 'indexed-native-source', 'indexed-input-manifest'}
_NONTRANSACTION_ROLES |= _INDEXED_ROLES


def with_derived_order(records, chronology):
    """Copy wrappers using only indices derived by shared raw chronology.

    This is an internal helper, not an imported certificate interface. Callers
    must pass assess_chronology's current result after checking every linked raw
    clock source. Raw bodies remain untouched; caller/saved indices are removed.
    """
    result = []
    for record in records:
        row = {key: value for key, value in record.items() if key != 'transaction_index'}
        clock = chronology.get('transactions', {}).get(record.get('signature'), {})
        index = clock.get('transaction_index')
        if (clock.get('order_state') == 'PASS' and type(index) is int and index >= 0
            and any(isinstance(h, str) and HASH.fullmatch(h) for h in clock.get('evidence', []))):
            row['transaction_index'] = index
        result.append(row)
    return result


def _check(known, reason, evidence=(), *, scope=OBSERVED_SCOPE, paths=(), dependencies=()):
    evidence = sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)})
    return {'state': 'PASS' if known and evidence else 'UNKNOWN', 'scope': scope, 'reason': reason,
            'evidence': evidence,
            'raw_paths': sorted(set(paths)), 'dependencies': sorted(set(dependencies))}


def _combine(rows, reason, *, scope=OBSERVED_SCOPE):
    rows = list(rows)
    return _check(bool(rows) and all(row['state'] == 'PASS' for row in rows), reason,
                  (h for row in rows for h in row.get('evidence', [])), scope=scope,
                  paths=(p for row in rows for p in row.get('raw_paths', [])),
                  dependencies=(d for row in rows for d in row.get('dependencies', [])))


def _safe_raw(raw):
    if not isinstance(raw, dict) or not supported_transaction_format(raw):
        return False
    meta, tx = raw.get('meta'), raw.get('transaction')
    message = tx.get('message') if isinstance(tx, dict) else None
    if not isinstance(meta, dict) or 'err' not in meta or not isinstance(message, dict):
        return False
    keys = message.get('accountKeys')
    loaded = meta.get('loadedAddresses', {})
    if (not isinstance(keys, list) or not keys or not isinstance(loaded, dict)
        or any(not isinstance(k, str) and not (isinstance(k, dict) and isinstance(k.get('pubkey'), str)) for k in keys)
        or any(not isinstance(loaded.get(k, []), list) or any(not isinstance(v, str) for v in loaded.get(k, []))
               for k in ('writable', 'readonly'))):
        return False
    if not all(isinstance(meta.get(name), list) for name in ('preBalances', 'postBalances', 'preTokenBalances', 'postTokenBalances')):
        return False
    return (all(type(value) is int and value >= 0 for name in ('preBalances', 'postBalances') for value in meta[name])
            and all(isinstance(value, dict) for name in ('preTokenBalances', 'postTokenBalances') for value in meta[name]))


def _flat(raw, keys):
    """Validate association before interpreting executed inner operations."""
    outer = raw['transaction']['message'].get('instructions')
    if not isinstance(outer, list):
        raise ValueError('Successful record has no explicit instruction list')
    inner_by_outer = defaultdict(list)
    nested = raw['meta'].get('innerInstructions')
    if nested is not None and not isinstance(nested, list):
        raise ValueError('Malformed inner instruction list')
    seen = set()
    for group_index, group in enumerate(nested or []):
        index = group.get('index') if isinstance(group, dict) else None
        values = group.get('instructions') if isinstance(group, dict) else None
        if type(index) is not int or not 0 <= index < len(outer) or index in seen or not isinstance(values, list):
            raise ValueError('Malformed or duplicated inner instruction association')
        seen.add(index)
        inner_by_outer[index] += [(index, f'meta.innerInstructions.{group_index}.instructions.{j}', value, True)
                                 for j, value in enumerate(values)]
    rows = []
    for index, value in enumerate(outer):
        rows.append((index, f'transaction.message.instructions.{index}', value, False))
        rows += inner_by_outer[index]
    result = []
    for index, path, value, inner in rows:
        result.append((index, path, value, inner, inspect_instruction(value, keys, path=path)))
    return result


def _amount(info, kind, identity):
    token = info.get('tokenAmount') if kind.endswith('Checked') else None
    quantity = raw_quantity(token.get('amount') if isinstance(token, dict) else info.get('amount'))
    if quantity > 2**64 - 1:
        raise ValueError('Instruction token quantity exceeds u64')
    if kind.endswith('Checked') and (not isinstance(token, dict) or type(token.get('decimals')) is not int
                                    or token['decimals'] != identity['decimals'] or info.get('mint') != identity['mint']):
        raise ValueError('Checked operation disagrees with raw mint/decimals')
    return quantity


def _observe(record, wallet):
    """Derive one raw version; comparisons across versions happen afterwards."""
    signature, digest, raw = record.get('signature'), record.get('evidence_hash'), record.get('raw')
    original_raw, normalization = raw, None
    from .compiled_instructions import normalize_transaction
    from .transaction_format import _needs_instruction_view, original_instruction_paths
    if _needs_instruction_view(raw):
        normalization = normalize_transaction(raw)
        raw = normalization['raw']
        normalization_receipt = {key: value for key, value in normalization.items() if key != 'raw'}
    else:
        # Parsed records and failed attempts need no copied instruction tree.
        # Their existing semantic validators retain all rejection diagnostics.
        normalization_receipt = {'state': 'NOT_REQUIRED', 'normalizations': [], 'gaps': []}
    result = {'signature': signature, 'hash': digest, 'boundaries': {}, 'lifecycle': [],
              'transfers': [], 'gaps': [], 'failed': None, 'trades': [], 'disjoint_operations': [],
              'instruction_normalization': normalization_receipt}

    def source_paths(paths):
        mapped = original_instruction_paths(original_raw, paths, normalized=normalization)
        existing = set()
        for path in mapped:
            parts, value, present = path.split('.'), original_raw, []
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                    value = value[int(part)]
                else:
                    break
                present.append(part)
            if present:
                existing.add('.'.join(present))
        return sorted(existing)

    def finish():
        # Values remain the existing derived observations. Source coordinates
        # cite immutable compiled bytes/account references instead of fields
        # introduced only in the normalized semantic view. A missing field is
        # witnessed by its nearest existing container, never an invented path.
        for pair in result['boundaries'].values():
            for check in pair['checks'].values():
                check['raw_paths'] = source_paths(check['raw_paths'])
        for name in ('lifecycle', 'transfers', 'disjoint_operations'):
            for item in result[name]:
                item['raw_paths'] = source_paths(item.get('paths', []) + [item['path']])
                if 'paths' in item:
                    item['paths'] = item['raw_paths']
        if 'error_raw_paths' in result:
            result['error_raw_paths'] = source_paths(result['error_raw_paths'])
        return result
    try:
        if not _safe_raw(raw):
            raise ValueError('Missing, malformed or unsupported raw transaction')
        tx, meta = raw['transaction'], raw['meta']
        if not isinstance(tx.get('signatures'), list) or not tx['signatures'] or tx['signatures'][0] != signature:
            raise ValueError('Native signature identity disagrees')
        keys = _keys(tx['message'], meta)
        if not keys or len(set(keys)) != len(keys):
            raise ValueError('Malformed or duplicate primary account keys')
        result['failed'] = meta['err'] is not None
        accounts = set()
        observed_owned = set()
        for name in ('preTokenBalances', 'postTokenBalances'):
            for row in meta[name]:
                index = row.get('accountIndex') if isinstance(row, dict) else None
                if type(index) is not int or not 0 <= index < len(keys):
                    raise ValueError('Malformed token balance account index')
                accounts.add(keys[index])
                if row.get('owner') == wallet:
                    observed_owned.add(keys[index])
        # Failed instructions are attempts, never committed lifecycle facts.
        if result['failed']:
            flat = []
            instructions = tx['message'].get('instructions')
            for index, value in enumerate(instructions if isinstance(instructions, list) else []):
                parsed = value.get('parsed') if isinstance(value, dict) else None
                if isinstance(parsed, dict) and parsed.get('type') in ('initializeAccount', 'initializeAccount2', 'initializeAccount3', 'closeAccount', 'setAuthority'):
                    result['lifecycle'].append({'kind': parsed['type'], 'account': None, 'applied': False,
                                               'path': f'transaction.message.instructions.{index}', 'facts': {}})
        else:
            flat = _flat(raw, keys)
            # Endpoint ownership alone misses accounts owned only between
            # committed operations. Once a validated owner transition touches
            # this wallet, retain the whole account lifecycle in execution
            # order; its authority/endpoint checks below still decide whether
            # that chain is supported.
            lifecycle_accounts = set(observed_owned)
            for _, _, instruction, _, view in flat:
                parsed = instruction.get('parsed')
                info = parsed.get('info') if isinstance(parsed, dict) else None
                kind = parsed.get('type') if isinstance(parsed, dict) else None
                if view['program'] not in TOKEN_IDS or not isinstance(info, dict):
                    continue
                account = info.get('account')
                if not _valid_account(account):
                    continue
                if (kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3', 'closeAccount')
                    and info.get('owner') == wallet
                    or kind == 'setAuthority' and info.get('authorityType') == 'accountOwner'
                    and wallet in (info.get('authority'), info.get('newAuthority'))):
                    lifecycle_accounts.add(account)
            for _, path, instruction, _, view in flat:
                parsed = instruction.get('parsed')
                info = parsed.get('info') if isinstance(parsed, dict) else None
                kind = parsed.get('type') if isinstance(parsed, dict) else None
                if view['program'] in TOKEN_IDS and kind in ('initializeAccount', 'initializeAccount2', 'initializeAccount3', 'closeAccount', 'setAuthority'):
                    if kind == 'setAuthority' and info.get('authorityType') in ('mintTokens', 'freezeAccount'):
                        result['disjoint_operations'].append({'path': path, 'mint': info['mint'],
                            'authority_type': info['authorityType'], 'paths': view['paths'],
                            'reason': 'Validated mint permission target does not change token-account owners or quantities; asset classification/risk remains separate.'})
                        continue
                    account = info.get('account')
                    if (account not in lifecycle_accounts and info.get('owner') != wallet and info.get('newAuthority') != wallet
                        and not view['references'] & lifecycle_accounts):
                        result['disjoint_operations'].append({'path': path, 'account': account,
                            'reason': 'Validated operation target is disjoint from the observed wallet-owned token accounts.',
                            'paths': view['paths']})
                        continue
                    if not _valid_account(account):
                        raise ValueError('Lifecycle operation lacks a valid account')
                    accounts.add(account)
                    if kind.startswith('initializeAccount') and (not _valid_account(info.get('owner')) or not _valid_account(info.get('mint'))):
                        raise ValueError('Initialization lacks explicit token owner/mint')
                    if kind == 'setAuthority' and info.get('authorityType') == 'accountOwner' and not _valid_account(info.get('newAuthority')):
                        raise ValueError('Account-owner change lacks explicit new authority')
                    result['lifecycle'].append({'kind': kind, 'account': account, 'applied': True, 'path': path,
                        'facts': {'program': view['program'], **{k: info[k] for k in ('owner', 'mint', 'authorityType', 'authority', 'newAuthority', 'destination') if k in info}}})
        trades = decode_supported_swaps([record], wallet)['events']
        result['trades'] = [e for e in trades if e['kind'] in ('buy', 'sell')]
        for account in sorted(accounts):
            pair, errors = {}, []
            for phase, name in (('pre', 'preTokenBalances'), ('post', 'postTokenBalances')):
                try:
                    pair[phase] = _balance(raw, keys, account, name)
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    pair[phase] = None
                    errors.append(str(exc))
            relevant = any(value and value['owner'] == wallet for value in pair.values()) or any(
                row['account'] == account and (row['facts'].get('owner') == wallet or row['facts'].get('newAuthority') == wallet)
                for row in result['lifecycle'])
            if not relevant:
                continue
            lifecycle = [row for row in result['lifecycle'] if row['account'] == account and row['applied']]
            identity = pair['pre'] or pair['post']
            flow, ordered_flows = 0, []
            paths = [value['path'] for value in pair.values() if value]
            programs = {value['program_id'] for value in pair.values() if value and value['program_id'] is not None}
            creates, initializes, closes, owner_changes = [], [], [], []
            operation_errors = []
            operation_positions = {row[1]: index for index, row in enumerate(flat)}
            for outer, path, instruction, inner, view in flat:
                if view['non_economic'] or account not in view['references']:
                    continue
                paths += view['paths']
                program = view['program']
                parsed = instruction.get('parsed')
                info = parsed.get('info', {}) if isinstance(parsed, dict) else {}
                kind = parsed.get('type') if isinstance(parsed, dict) else None
                try:
                    if program in TOKEN_IDS:
                        programs.add(program)
                        if not isinstance(kind, str):
                            raise ValueError('Opaque token operation has no executed semantic contract')
                        if kind in ('transfer', 'transferChecked', 'mintTo', 'mintToChecked', 'burn', 'burnChecked'):
                            if identity is None:
                                raise ValueError('Quantity operation lacks a native mint/decimal boundary')
                            quantity = _amount(info, kind, identity)
                            if kind.startswith('transfer'):
                                source, destination = info['source'], info['destination']
                                movement = quantity * (int(destination == account) - int(source == account))
                                flow += movement
                                ordered_flows.append((operation_positions[path], movement))
                                transfer = {'source': source, 'destination': destination, 'mint': identity['mint'],
                                            'quantity_raw': str(quantity), 'path': path}
                                if transfer not in result['transfers']:
                                    result['transfers'].append(transfer)
                            elif kind.startswith('mintTo'):
                                if info.get('mint') != identity['mint']:
                                    raise ValueError('Mint operation disagrees with native identity')
                                flow += quantity
                                ordered_flows.append((operation_positions[path], quantity))
                            else:
                                if info.get('mint') != identity['mint']:
                                    raise ValueError('Burn operation disagrees with native identity')
                                flow -= quantity
                                ordered_flows.append((operation_positions[path], -quantity))
                        elif kind.startswith('initializeAccount'):
                            initializes.append((path, info, program))
                        elif kind == 'closeAccount':
                            closes.append((path, info))
                        elif kind == 'setAuthority':
                            if info.get('authorityType') == 'accountOwner':
                                owner_changes.append((path, info))
                        elif kind not in ('approve', 'approveChecked', 'revoke', 'freezeAccount', 'thawAccount', 'initializeImmutableOwner', 'getAccountDataSize'):
                            raise ValueError('Relevant token extension/operation needs a reviewed semantic contract')
                    elif program == SYSTEM_ID and kind in ('createAccount', 'createAccountWithSeed') and info.get('newAccount') == account:
                        creates.append((path, info))
                    elif program == SYSTEM_ID and kind == 'transfer':
                        pass  # Lamports do not change this token's raw quantity.
                    elif program == ASSOCIATED_ID and kind in ('create', 'createIdempotent'):
                        pass  # Idempotence is not an opening-zero certificate.
                    elif program in VENUES and not inner:
                        route = _route(instruction, keys)
                        if route['authority'] != wallet or account not in route['owned_accounts']:
                            raise ValueError('Recognized route does not establish this wallet/account authority')
                        if identity and identity['mint'] != WSOL:
                            # Existing quantity validation deliberately does not
                            # depend on monetary fee/consideration reconstruction.
                            _quantity_point(raw, wallet, account)
                    else:
                        raise ValueError('Opaque or unsupported relevant account operation')
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    operation_errors.append(f'{path}: {exc}')
            # Missing endpoints need committed raw lifecycle, not an invented zero.
            if pair['pre'] is None and len(creates) == len(initializes) == 1 and pair['post']:
                create_path, create = creates[0]
                init_path, init, program = initializes[0]
                index = keys.index(account)
                if (type(meta['preBalances'][index]) is int and meta['preBalances'][index] == 0
                    and create.get('owner') == program and type(create.get('space')) is int and create['space'] >= 165
                    and _valid_account(create.get('source')) and type(create.get('lamports')) is int and create['lamports'] > 0
                    and operation_positions[create_path] < operation_positions[init_path]
                    and all(operation_positions[init_path] < position for position, _ in ordered_flows)
                    and init.get('mint') == pair['post']['mint'] and init.get('owner') == pair['post']['owner']):
                    pair['pre'] = {**pair['post'], 'quantity': 0, 'owner': init['owner'], 'path': create_path + '+ ' + init_path}
                    errors = []
            if pair['post'] is None and len(closes) == 1 and pair['pre']:
                index = keys.index(account)
                if (type(meta['postBalances'][index]) is int and meta['postBalances'][index] == 0 and pair['pre']['quantity'] + flow == 0
                    and all(position < operation_positions[closes[0][0]] for position, _ in ordered_flows)):
                    pair['post'] = {**pair['pre'], 'quantity': 0, 'path': closes[0][0]}
                    errors = []
            before, after = pair['pre'], pair['post']
            identity_known = bool(before and after) and (before['mint'], before['decimals']) == (after['mint'], after['decimals']) and len(programs) == 1
            quantity_known = identity_known and not operation_errors and after['quantity'] - before['quantity'] == flow
            running = before['quantity'] if before else None
            for _, movement in ordered_flows:
                if running is not None:
                    running += movement
                    quantity_known = quantity_known and running >= 0
            if result['failed']:
                quantity_known = identity_known and before['quantity'] == after['quantity']
            owner_known = identity_known
            if before and after:
                expected_owner = before['owner']
                for _, info in owner_changes:
                    if info.get('authority') != expected_owner:
                        owner_known = False
                    expected_owner = info['newAuthority']
                owner_known = owner_known and expected_owner == after['owner']
                if result['failed']:
                    owner_known = before['owner'] == after['owner'] and identity_known
            pair['checks'] = {'ownership': _check(owner_known, 'Raw owner endpoints reconcile with executed lifecycle only.', [digest], paths=paths),
                'quantities': _check(quantity_known, '; '.join(errors + operation_errors) or 'Raw endpoint quantities reconcile to executed token operations.', [digest], paths=paths),
                'lifecycle': _check(identity_known and owner_known and not operation_errors, '; '.join(errors + operation_errors) or 'Executed owner/lifecycle operations reconcile with native boundaries.', [digest], paths=paths)}
            pair['program'] = next(iter(programs)) if len(programs) == 1 else None
            pair['flow_raw'] = str(flow)
            result['boundaries'][account] = pair
        return finish()
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result['gaps'].append(str(exc))
        if getattr(exc, 'paths', None):
            result['error_raw_paths'] = list(exc.paths)
        return finish()


def _semantic(pair):
    return {phase: {key: pair[phase][key] for key in ('quantity', 'owner', 'mint', 'decimals')} if pair[phase] else None
            for phase in ('pre', 'post')} | {'program': pair.get('program'), 'flow_raw': pair.get('flow_raw')}


def _resolved_sources(raw_sources, source_receipts):
    """Join declarations with actual bytes before determining relevance.

    A receipt without a body is not a second missing copy of an available hash.
    Neither optional receipt state nor scope can override checked source bytes.
    """
    resolved = {}
    for declaration in list(raw_sources) + list(source_receipts):
        if not isinstance(declaration, dict) or not isinstance(declaration.get('hash'), str):
            continue
        kind = declaration.get('kind', declaration.get('role'))
        kind = kind if isinstance(kind, str) else None
        digest = declaration['hash']
        source = resolved.setdefault((kind, digest), {'kind': kind, 'hash': digest, 'payload': None,
                                                     'signature_hints': set(), 'invalid_body': False, 'invalid_hints': False})
        signature = declaration.get('signature')
        if isinstance(signature, str) and signature:
            source['signature_hints'].add(signature)
        hints = declaration.get('signature_hints', [])
        if not isinstance(hints, list) or any(not isinstance(s, str) or not s for s in hints):
            source['invalid_hints'] = True
            hints = hints if isinstance(hints, list) else []
        source['signature_hints'].update(s for s in hints if isinstance(s, str) and s)
        source['invalid_hints'] = source['invalid_hints'] or declaration.get('invalid_hints') is True
        payload = declaration.get('payload')
        if payload is None:
            continue
        try:
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            valid = HASH.fullmatch(digest) and hashlib.sha256(encoded).hexdigest() == digest
        except (ValueError, TypeError):
            valid = False
        if not valid or source['payload'] is not None and source['payload'] != payload:
            source['invalid_body'] = True
        else:
            source['payload'] = payload
    readable_hashes = {source['hash'] for source in resolved.values()
                       if source['payload'] is not None and not source['invalid_body']}
    result = []
    for key in sorted(resolved, key=repr):
        source = resolved[key]
        if source['payload'] is None and not source['invalid_body'] and source['hash'] in readable_hashes:
            # A reader's role annotation is not another missing archive when
            # the same checksum-checked bytes are already present. Preserve
            # the original declared/body role; do not manufacture an absent
            # native source from IndexedResolver's generic read label.
            continue
        if source['invalid_body']:
            source['payload'] = None
        source['signature_hints'] = sorted(source['signature_hints'])
        result.append(source)
    return result


def _indexed_native_rows(payload):
    """Retain byte-verified native leads separately from page acceptance.

    A malformed cursor does not destroy an independently usable raw fee. An
    unreadable byte envelope cannot supply a convenient exclusion or record.
    Caller role labels are deliberately absent from this interpretation.
    """
    from .indexed_input import (PAGE_VERSION, NATIVE_VERSION, RECORD_VERSION, MANIFEST_VERSION,
                                source_bytes, validate_page_envelope, manifest_bytes, source_records)
    version = payload.get('version') if isinstance(payload, dict) else None
    from .wallet_identity import ACCOUNT_SOURCE_VERSION, account_source_bytes
    if version == ACCOUNT_SOURCE_VERSION:
        # An account-role label cannot hide an original native transaction
        # response. Decode only checksum-verified retained bytes for negative
        # association; this does not admit an account envelope as a historical
        # source or replace its independent identity validator.
        from .json_boundary import parse_json
        try:
            original = account_source_bytes(payload)
            request = parse_json(original['request'], max_nodes=1_000_000)
            response = parse_json(original['response'], max_nodes=1_000_000)
            claims, native, ambiguous, nodes, inspected = set(), [], False, [response], 0
            if isinstance(request, dict) and request.get('method') == 'getTransaction':
                params = request.get('params')
                signature = params[0] if isinstance(params, list) and params else None
                if isinstance(signature, str) and 1 <= len(signature) <= 128:
                    claims.add(signature)
                else:
                    ambiguous = True
            while nodes:
                node = nodes.pop()
                if not isinstance(node, dict):
                    continue
                inspected += 1
                if inspected > 64:
                    ambiguous = True
                    break
                if {'transaction', 'meta'} & node.keys():
                    native.append(node)
                    transaction = node.get('transaction')
                    signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
                    if (isinstance(signatures, list) and signatures and isinstance(signatures[0], str)
                        and 1 <= len(signatures[0]) <= 128):
                        claims.add(signatures[0])
                    else:
                        ambiguous = True
                nodes += [node[key] for key in ('result', 'value') if isinstance(node.get(key), dict)]
            return native, claims, ambiguous, True
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            return [], set(), True, True
    if version not in (PAGE_VERSION, NATIVE_VERSION, RECORD_VERSION, MANIFEST_VERSION):
        return [], set(), False, False
    try:
        if version == MANIFEST_VERSION:
            manifest_bytes(payload)
            return [], set(), False, True
        if version == RECORD_VERSION:
            # An unresolved pointer is a negative association, never a raw
            # transaction or a trusted native content/ordering declaration.
            signature = payload.get('signature')
            valid = isinstance(signature, str) and 1 <= len(signature) <= 128
            return [], {signature} if valid else set(), not valid, True
        source_bytes(payload)  # Strict byte hashes/encoding before any leads.
        if version == PAGE_VERSION:
            page = validate_page_envelope(payload)
            return page['records'], set(page['signatures']), bool(page['unassignable_records']), True
        from .indexed_input import _json
        response = _json(source_bytes(payload)['response'])
        raw = response.get('result') if isinstance(response, dict) else None
        native = source_records(payload)
        transaction = raw.get('transaction') if isinstance(raw, dict) else None
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        unassignable = not (isinstance(signatures, list) and signatures and
                            isinstance(signatures[0], str) and 1 <= len(signatures[0]) <= 128)
        return [raw], set(native['signatures']), unassignable, True
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        return [], set(), True, True


def _native_claims(payload, *, indexed_facts=None):
    """Inspect response/account wrappers without trusting their role label."""
    indexed, leads, ambiguous, is_indexed = indexed_facts if indexed_facts is not None else _indexed_native_rows(payload)
    nodes, claims = [payload] + indexed, set(leads)
    inspection_limit = MAX_RECORDS + 64 if is_indexed else 64
    inspected = 0
    while nodes:
        value = nodes.pop()
        if not isinstance(value, dict):
            continue
        inspected += 1
        if inspected > inspection_limit:
            ambiguous = True
            break
        if {'transaction', 'meta'} & value.keys():
            transaction = value.get('transaction')
            signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
            if (isinstance(signatures, list) and signatures and isinstance(signatures[0], str)
                and 1 <= len(signatures[0]) <= 128):
                claims.add(signatures[0])
            else:
                ambiguous = True
        nodes += [value[k] for k in ('result', 'value') if isinstance(value.get(k), dict)]
    return claims, ambiguous


def _mint_metadata(payload):
    """Current account metadata cannot assert native transaction endpoints.

    This is semantic disjointness only, not trusted collector ancestry, asset
    classification, historical ownership or a historical inventory certificate.
    Match the existing report-metadata body contract; no new provider fields.
    """
    if not isinstance(payload, dict):
        return False
    result = payload.get('result')
    context = result.get('context') if isinstance(result, dict) else None
    slot = context.get('slot') if isinstance(context, dict) else None
    value = result.get('value') if isinstance(result, dict) else None
    account_shape = value is None or (isinstance(value, dict) and _valid_account(value.get('owner'))
        and type(value.get('lamports')) is int and 0 <= value['lamports'] <= 2**64 - 1
        and type(value.get('executable')) is bool and isinstance(value.get('data'), (dict, list, str))
        and not {'transaction', 'meta'}.intersection(value))
    return (payload.get('method') == 'getAccountInfo' and _valid_account(payload.get('address'))
            and payload.get('commitment') == 'finalized' and type(slot) is int and slot >= 0
            and 'value' in result and account_shape
            and not {'transaction', 'meta'}.intersection(payload)
            and not {'transaction', 'meta'}.intersection(result))


def raw_native_dependencies(raw_sources, source_receipts, selected_signatures):
    """Return negative native associations to freeze before raw source loss.

    The helper only derives dependencies from checksum-verified native-shaped
    content, malformed/unassignable source scope or negative selectors. It never
    authenticates completeness. Import/report callers freeze these links beside
    original raw evidence so later loss cannot erase an observed contradiction.
    """
    selected = {s for s in selected_signatures if isinstance(s, str) and s}
    negative, available = set(), {}
    sources = _resolved_sources(raw_sources, source_receipts)
    indexed_rows = {(source['kind'], source['hash']): _indexed_native_rows(source['payload']) for source in sources}
    row_counts = {}
    for (_kind, digest), facts in indexed_rows.items():
        row_counts[digest] = max(row_counts.get(digest, 0), len(facts[0]))
    indexed_budget_exceeded = sum(row_counts.values()) > MAX_INDEXED_RECORDS
    for source in sources:
        kind, digest, payload = source['kind'], source['hash'], source['payload']
        if kind in ('transaction', 'getTransaction'):
            continue  # Explicit native links are checked by the normal loader.
        if source['invalid_body']:
            negative.add((None, digest))
            continue
        indexed_facts = indexed_rows[(kind, digest)]
        if indexed_budget_exceeded and indexed_facts[3]:
            # Never certify a convenient page prefix after whole-input loss.
            negative.add((None, digest))
            continue
        claims, ambiguous = _native_claims(payload, indexed_facts=indexed_facts)
        # Query-role affinity is negative-only. Explicit signature selectors
        # cannot be discarded merely because a caller chose that role label.
        hints = source['signature_hints'] if kind not in _NONTRANSACTION_ROLES or kind == 'query-affinity' else []
        affected = selected & (claims | set(hints))
        negative.update((signature, digest) for signature in affected)
        native_rows, _, _, indexed = indexed_facts
        if indexed:
            for raw in native_rows:
                transaction = raw.get('transaction') if isinstance(raw, dict) else None
                signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
                signature = signatures[0] if isinstance(signatures, list) and signatures else None
                if not isinstance(signature, str) or not 1 <= len(signature) <= 128 or signature not in affected:
                    continue
                key = signature, digest
                if key in available and available[key] != raw:
                    available[key] = None  # Repeated/conflicting alternatives cannot win by arrival order.
                else:
                    available.setdefault(key, raw)
        if ambiguous or source['invalid_hints']:
            negative.add((None, digest))
        elif not affected and not claims:
            if kind not in _NONTRANSACTION_ROLES and not _mint_metadata(payload):
                negative.add((None, digest))
            elif kind == 'current-mint-controls' and payload is not None and not _mint_metadata(payload):
                negative.add((None, digest))
    return [{'signature': signature, 'evidence_hash': digest, 'raw': available.get((signature, digest)),
             **({'indexed_source_hash': digest} if (signature, digest) in available else {})}
            for signature, digest in sorted(negative, key=lambda key: (key[0] or '', key[1]))]


def _native_role_check(record, wallet, expected_lamports):
    """Reconcile decoded roles to raw native wealth movement, not FIFO profits.

    Include lamports held by evidenced wallet token accounts (including wSOL
    reserve/rent). This avoids double counting SOL representation changes. It
    gives no historical inventory/value/population proof or external-flow price.
    """
    digest, raw = record.get('evidence_hash'), record.get('raw')
    paths = ['meta.preBalances', 'meta.postBalances', 'meta.preTokenBalances', 'meta.postTokenBalances']
    try:
        if expected_lamports is None or not _safe_raw(raw):
            raise ValueError('Native economic role or raw endpoint is unavailable')
        keys = _keys(raw['transaction']['message'], raw['meta'])
        if len(set(keys)) != len(keys):
            raise ValueError('Native account membership is ambiguous')
        before, after = (raw['meta'][name] for name in ('preBalances', 'postBalances'))
        if len(before) != len(after) or len(before) != len(keys):
            raise ValueError('Native endpoint population is incomplete')
        owned = {'pre': set(), 'post': set()}
        for phase, name in (('pre', 'preTokenBalances'), ('post', 'postTokenBalances')):
            for row in raw['meta'][name]:
                index = row.get('accountIndex')
                if type(index) is not int or not 0 <= index < len(keys):
                    raise ValueError('Token-account native wealth membership is malformed')
                if row.get('owner') == wallet:
                    if index in owned[phase]:
                        raise ValueError('Duplicate owned native account membership')
                    owned[phase].add(index)
        if wallet in keys:
            for phase in owned:
                owned[phase].add(keys.index(wallet))
        actual = sum(after[i] for i in owned['post']) - sum(before[i] for i in owned['pre'])
        known = actual == expected_lamports
        check = _check(known, 'Decoded supported consideration/network fees reconcile exactly to observed wallet/owned-account native endpoints.' if known else
            'Raw native movement contains an unexplained or conflicting economic role.', [digest], paths=paths,
            dependencies=['supported_native_movement_roles', 'observed_event_ownership'])
        return {**check, 'actual_lamports': str(actual), 'expected_lamports': str(expected_lamports)}
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return _check(False, str(exc), [digest], paths=paths, dependencies=['supported_native_movement_roles'])


def _decoded_native_movement(events):
    """Exact native movement projection of already decoded events, fees once."""
    expected = 0
    try:
        for event in events:
            kind = event['kind']
            if kind == 'internal_transfer':
                continue
            if kind not in ('buy', 'sell', 'fee'):
                return None
            if kind in ('buy', 'sell') and event.get('native_cash_role_state') == 'UNKNOWN':
                return None  # Net endpoints cannot classify cancelling gross cash roles.
            if kind == 'fee' and event.get('paid_by_wallet') is not True:
                continue
            amount = decimal(event.get('amount_sol')) * Decimal(10**9)
            if amount != amount.to_integral_value():
                return None
            # The display fee is counted exactly once; fee_sol embedded in a
            # trade is basis/allocation information, not another native debit.
            expected += int(amount) * (1 if kind == 'sell' else -1)
            for funding in event.get('retained_account_funding', []) if kind in ('buy', 'sell') else []:
                if (not isinstance(funding, dict) or funding.get('role') != 'retained-user-volume-account-funding'
                    or funding.get('payer') != event.get('owner') or type(funding.get('lamports')) is not int
                    or funding['lamports'] <= 0):
                    return None
                # This is a located native outflow, separate from trade quote;
                # refund entitlement and economic valuation remain UNKNOWN.
                expected -= funding['lamports']
        return expected
    except (ValueError, TypeError, KeyError):
        return None


def _clock_inputs(raw_sources, source_receipts, wallet):
    """Role validation ignores caller state/optional scope annotations."""
    supplied = {}
    for row in raw_sources:
        if isinstance(row, dict) and isinstance(row.get('hash'), str):
            key = (row.get('kind'), row['hash'])
            if key in supplied and supplied[key].get('payload') != row.get('payload'):
                supplied[key] = {**row, 'payload': None}
            else:
                supplied.setdefault(key, row)
    for row in source_receipts:
        if not isinstance(row, dict) or not isinstance(row.get('hash'), str):
            continue
        kind = row.get('kind', row.get('role'))
        if kind not in ('transaction', 'getTransaction'):
            supplied.setdefault((kind, row['hash']), {'kind': kind, 'hash': row['hash'], 'payload': None})
    pages, blocks, indexed, typed = [], [], [], []
    for (_, digest), row in sorted(supplied.items(), key=lambda item: repr(item[0])):
        kind, payload = row.get('kind'), row.get('payload')
        if payload is not None:
            try:
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
                if hashlib.sha256(encoded).hexdigest() != digest:
                    payload = None
            except (ValueError, TypeError):
                payload = None
        from .indexed_input import PAGE_VERSION
        if kind == 'indexed-page' or isinstance(payload, dict) and payload.get('version') == PAGE_VERSION:
            indexed.append({'hash': digest, 'payload': payload})
        if kind not in {'signature-page', 'block-order', 'snapshot-slot', 'owned-accounts', 'native-balance'} | _INDEXED_ROLES:
            if kind not in ('transaction', 'getTransaction'):
                typed.append({'kind': kind, 'hash': digest, 'state': 'UNKNOWN', 'read_state': 'readable' if payload is not None else 'unavailable',
                    'scope': {'signatures': None, 'account': None, 'slot': None}, 'evidence': [digest] if HASH.fullmatch(digest) else [],
                    'reason': 'The raw source is retained; its declared role has no accepted historical evidence validator.'})
            continue
        params = payload.get('params') if isinstance(payload, dict) else None
        params = params if isinstance(params, dict) else {}
        minimum = params.get('minContextSlot')
        if kind == 'snapshot-slot' and isinstance(payload, dict):
            minimum = payload.get('result')
        receipt = source_archive_receipts({'links': [{'kind': kind, 'hash': digest}]}, {digest: payload},
            {digest: 'readable' if payload is not None else 'unavailable'}, snapshot_slot=minimum, wallet=wallet)['receipts'][0]
        typed.append(receipt)
        if kind == 'signature-page':
            pages.append({'hash': digest, 'payload': payload})
        elif kind == 'block-order':
            blocks.append({'hash': digest, 'payload': payload})
    return pages, blocks, indexed, {'state': 'PASS' if typed and all(r['state'] == 'PASS' for r in typed) else 'UNKNOWN', 'receipts': typed}


def _quantity_only_trade(record, observed, wallet):
    """Retain an existing raw exchange-quantity witness when its fee is absent.

    The shared quantity interpreter validates the route, direction, ownership,
    balances and recorded instructions. No replacement fee or consideration is
    supplied to the monetary decoder. This deliberately narrow fallback cannot
    turn an unknown route or unknown acquisition basis into financial evidence.
    """
    raw = record.get('raw')
    if not _safe_raw(raw) or raw['meta'].get('err') is not None:
        return None
    fee = raw['meta'].get('fee')
    if type(fee) is int and fee >= 0:
        return None  # Other decoder gaps retain their existing semantics.
    try:
        keys = _keys(raw['transaction']['message'], raw['meta'])
        points = []
        for account, pair in observed['boundaries'].items():
            if any(check['state'] != 'PASS' for check in pair['checks'].values()):
                return None
            if not all(pair[phase] and pair[phase]['owner'] == wallet for phase in ('pre', 'post')):
                continue
            point = _quantity_point(raw, wallet, account)
            if point and point['kind'] in ('buy', 'sell'):
                points.append((account, point))
        if len(points) != 1:
            return None  # Multi-account exchanges need a reviewed allocation.
        account, point = points[0]
        aggregate = observed['mint_aggregates'].get(point['mint'], {})
        if aggregate.get('check', {}).get('state') != 'PASS':
            return None
        event = {'kind': point['kind'], 'signature': record['signature'], 'timestamp': raw['blockTime'],
            'path': 'quantity-only:' + account, 'mint': point['mint'],
            'quantity_raw': str(abs(point['post'] - point['pre'])), 'decimals': point['decimals'],
            'classification': 'unknown', 'owner': wallet, 'amount_sol': None, 'fee_sol': None,
            'paid_by_wallet': keys[0] == wallet, 'native_cash_role_state': 'UNKNOWN',
            'observed_pre_quantity_raw': aggregate['pre_raw'], 'observed_post_quantity_raw': aggregate['post_raw'],
            'evidence': [record['evidence_hash']], 'quantity_only': True,
            'reason': 'Supported raw exchange quantities and direction; network fee and monetary consideration remain unresolved.'}
        slot, index = raw['slot'], record.get('transaction_index')
        if type(slot) is int and slot >= 0:
            event['order'] = slot * 1_000_000 + (index * 1_000 if type(index) is int and index >= 0 else 0)
        return event
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return None


def _selected_lot_observations(positions, selected, raw_versions, transactions, clocks,
                               role_checks, ledger_events, source_rows, wallet, *, window_end=None):
    """Project existing FIFO by named-account dependencies, never wallet scope.

    Unrelated routes cannot erase a supported named lot. A missing source is
    disjoint only when independently present original bytes reproduce its exact
    frozen pointer/body hash. That reconstruction supplies exclusion only; a
    missing required purchase or sale still revokes the lot's result.
    """
    from .indexed_input import PAGE_VERSION, NATIVE_VERSION, RECORD_VERSION, canonical_bytes
    recovered = {}
    for source in source_rows:
        payload = source.get('payload')
        version = payload.get('version') if isinstance(payload, dict) else None
        if version not in (PAGE_VERSION, NATIVE_VERSION):
            continue
        raws, _, ambiguous, _ = _indexed_native_rows(payload)
        if ambiguous:
            continue
        for ordinal, raw in enumerate(raws):
            if not _safe_raw(raw):
                continue
            signatures = raw['transaction'].get('signatures')
            if (not isinstance(signatures, list) or not signatures or not isinstance(signatures[0], str)
                or not 1 <= len(signatures[0]) <= 128):
                continue
            signature = signatures[0]
            try:
                native_hash = hashlib.sha256(canonical_bytes(raw)).hexdigest()
                pointer = {'version': RECORD_VERSION, 'source_hash': source['hash'], 'ordinal': ordinal,
                           'signature': signature, 'native_hash': native_hash}
                pointer_hash = hashlib.sha256(canonical_bytes(pointer)).hexdigest()
            except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
                continue  # No canonical preimage proves an absent link disjoint.
            recovered.setdefault((signature, native_hash), raw)
            recovered.setdefault((signature, pointer_hash), raw)
    by_signature = defaultdict(list)
    for event in ledger_events:
        by_signature[event.get('signature')].append(event)
    roles = defaultdict(list)
    for check in role_checks:
        roles[check['signature']].append(check)
    results = []
    for position in positions:
        mint = position['mint']
        if mint == WSOL:
            continue
        def event_within_lot(event):
            at, order = utc(event['timestamp']), event.get('order')
            start_order, end_order = position.get('start_order'), position.get('end_order')
            if type(order) is int and type(start_order) is int:
                after_start = (at, order) >= (utc(position['start']), start_order)
            else:
                after_start = at >= utc(position['start'])
            if position['end'] is None:
                before_end = window_end is None or at < utc(window_end)
            elif type(order) is int and type(end_order) is int:
                before_end = (at, order) <= (utc(position['end']), end_order)
            else:
                before_end = at <= utc(position['end'])
            return after_start and before_end

        named = {account for observed in transactions.values() for account, pair in observed['boundaries'].items()
                 if any(pair.get(phase) and pair[phase]['owner'] == wallet and pair[phase]['mint'] == mint
                        for phase in ('pre', 'post'))}
        scope_gaps, required, disjoint, physical, money, basis_checks, timing, evidence, retained = [], [], [], [], [], [], [], set(), []
        for signature, versions in raw_versions.items():
            known_clock = clocks['transactions'].get(signature, {})
            lot_trade_events = [event for event in by_signature[signature]
                if event['kind'] in ('buy', 'sell', 'transfer_in', 'transfer_out') and event.get('mint') == mint]
            if (lot_trade_events and known_clock.get('state') == 'PASS' and known_clock.get('time_state') == 'PASS'
                and known_clock.get('order_state') == 'PASS' and all(type(event.get('order')) is int for event in lot_trade_events)
                and all(not event_within_lot(event) for event in lot_trade_events)):
                disjoint.append(signature)
                continue
            observation_start = utc(position['start'])
            prior = assess_interval_membership(clocks, signature, utc(0), observation_start) if observation_start > utc(0) else None
            if prior and prior['state'] == 'PASS' and prior.get('member') is True:
                disjoint.append(signature)
                continue
            observation_end = (utc(position['end']) + timedelta(seconds=1) if position['end'] is not None
                               else utc(window_end) if window_end is not None else None)
            if observation_end is not None:
                future = assess_interval_membership(clocks, signature, utc(0), observation_end)
                if future['state'] == 'PASS' and future.get('member') is False:
                    disjoint.append(signature)
                    continue
            relevant, scope_known = False, bool(versions)
            for row in versions:
                raw = row.get('raw')
                if not _safe_raw(raw):
                    raw = recovered.get((signature, row.get('evidence_hash')))
                if not _safe_raw(raw):
                    scope_known = False
                    continue
                try:
                    keys = _keys(raw['transaction']['message'], raw['meta'])
                    if len(set(keys)) != len(keys):
                        raise ValueError('Duplicate native account keys')
                    touching = named.intersection(keys) or mint in keys
                    for field in ('preTokenBalances', 'postTokenBalances'):
                        for balance in raw['meta'][field]:
                            if balance.get('owner') == wallet and balance.get('mint') == mint:
                                touching = True
                    relevant = relevant or bool(touching)
                except (ValueError, TypeError, KeyError, IndexError):
                    scope_known = False
            relevant = relevant or any(e.get('mint') == mint for e in by_signature[signature])
            if not scope_known:
                scope_gaps.append(f'{signature}: linked source cannot be independently excluded from this named-account population')
            if not relevant:
                if scope_known:
                    disjoint.append(signature)
                continue
            required.append(signature)
            observed = transactions.get(signature)
            if observed is None:
                scope_gaps.append(f'{signature}: required observed transaction is unavailable')
                continue
            identity = observed['checks']['identity']
            clock = clocks['transactions'].get(signature, {})
            timing.append(_check(clock.get('state') == 'PASS' and clock.get('time_state') == 'PASS',
                clock.get('reason', 'Required named-account clock unavailable'), clock.get('evidence', [])))
            for account, pair in observed['boundaries'].items():
                if account in named:
                    physical.extend(pair['checks'][field] for field in ('ownership', 'quantities', 'lifecycle'))
            signature_events = by_signature[signature]
            lot_trades = [event for event in signature_events if event.get('mint') == mint and event['kind'] in ('buy', 'sell')]
            if lot_trades:
                trade_checks = [identity, observed['checks']['cost_roles'], observed['network_fee']['check']] + roles[signature]
                money.extend(trade_checks)
                if any(event['kind'] == 'buy' for event in lot_trades):
                    basis_checks.extend(trade_checks)
                retained.extend(item for event in lot_trades for item in event.get('retained_account_funding', []))
            target_pairs = [pair for account, pair in observed['boundaries'].items() if account in named]
            zero_administration = bool(target_pairs) and all(
                pair['pre'] and pair['post'] and pair['pre']['quantity'] == pair['post']['quantity'] == '0'
                and all(pair['checks'][field]['state'] == 'PASS' for field in ('ownership', 'quantities', 'lifecycle'))
                for pair in target_pairs)
            failed_unchanged = (identity['state'] == 'PASS' and bool(target_pairs) and bool(versions)
                and all(_safe_raw(row.get('raw')) and row['raw']['meta']['err'] is not None for row in versions)
                and all(pair['pre'] and pair['post']
                    and all(pair['pre'][field] == pair['post'][field] for field in ('quantity', 'owner', 'mint', 'decimals'))
                    and all(pair['checks'][field]['state'] == 'PASS' for field in ('ownership', 'quantities', 'lifecycle'))
                    for pair in target_pairs))
            if any(event['kind'] in ('transfer_in', 'transfer_out') and event.get('mint') == mint
                   or event['kind'] == 'unsupported' and not (zero_administration or failed_unchanged)
                   for event in signature_events):
                scope_gaps.append(f'{signature}: required record contains unsupported or transfer-interrupted named-account activity')
            evidence.update(observed['evidence'])
        # Account-continuity checks use only this lot's observed named accounts.
        for account in named:
            boundaries = [(sig, transactions[sig]['boundaries'][account]) for sig in required
                          if account in transactions.get(sig, {}).get('boundaries', {})]
            def boundary_order(row):
                clock = clocks['transactions'].get(row[0], {})
                values = [clock.get(field) for field in ('canonical_time', 'slot', 'transaction_index')]
                return *(value if type(value) is int else -1 for value in values), row[0]
            boundaries.sort(key=boundary_order)
            for (before_sig, before), (after_sig, after) in zip(boundaries, boundaries[1:]):
                a, b = before['post'], after['pre']
                matching = bool(a and b) and all(a[key] == b[key] for key in ('quantity', 'owner', 'mint', 'decimals'))
                physical.append(_check(matching, 'Named-account selected endpoints must agree across required observations.',
                    before['checks']['quantities']['evidence'] + after['checks']['quantities']['evidence']))
        physical_known = bool(named) and bool(physical) and all(check['state'] == 'PASS' for check in physical)
        chronology_known = physical_known and not scope_gaps and bool(timing) and all(check['state'] == 'PASS' for check in timing)
        buys = [event for signature in required for event in by_signature[signature]
                if event['kind'] == 'buy' and event.get('mint') == mint
                and event_within_lot(event)]
        origin_known = bool(buys) and sum(int(event['quantity_raw']) for event in buys) == int(position['acquired_raw'])
        initial_buys = [event for event in buys if utc(event['timestamp']) == utc(position['start'])
            and type(position.get('start_order')) is int and event.get('order') == position['start_order']]
        origin_known = origin_known and len(initial_buys) == 1 and initial_buys[0].get('observed_pre_quantity_raw') == '0'
        timing_known = chronology_known and origin_known and position['end'] is not None and position['quantity_raw'] == '0' and position['status'] != 'interrupted'
        basis_known = (chronology_known and origin_known and bool(basis_checks) and all(check['state'] == 'PASS' for check in basis_checks)
                       and position.get('acquisition_basis_status') == 'known'
                       and position.get('known_basis_sol') is not None and position.get('known_matched_basis_sol') is not None
                       and position['status'] != 'interrupted')
        remaining_acquisition_checks, remaining_acquisition_bindings = [], []
        for surviving in position.get('remaining_lots', []):
            acquisition = surviving.get('acquisition', {})
            signature = acquisition.get('signature')
            matches = [event for event in buys if event.get('signature') == signature
                and event.get('evidence') == acquisition.get('evidence')
                and utc(event['timestamp']) == utc(acquisition.get('timestamp'))
                and event.get('order') == acquisition.get('order')
                and event.get('quantity_raw') == acquisition.get('quantity_raw')]
            original = transactions.get(signature, {})
            binding = (len(matches) == 1 and signature in required and bool(acquisition.get('evidence'))
                and surviving.get('basis_status') == 'known' and surviving.get('basis_sol') is not None
                and 0 < int(surviving['quantity_raw']) <= int(acquisition['quantity_raw']))
            remaining_acquisition_bindings.append(_check(binding,
                'The surviving FIFO quantity and cost bind one exact original raw purchase; consumed origins cannot erase this remainder.',
                acquisition.get('evidence', []), dependencies=['surviving_fifo_acquisition_binding']))
            if binding:
                remaining_acquisition_checks.extend([original['checks']['identity'], original['checks']['cost_roles'],
                    original['network_fee']['check']] + roles[signature])
        remaining_basis_known = (chronology_known and origin_known and bool(remaining_acquisition_bindings)
            and all(check['state'] == 'PASS' for check in remaining_acquisition_bindings + remaining_acquisition_checks)
            and position.get('remaining_basis_status') == 'known' and position.get('remaining_basis_sol') is not None)
        money_known = (basis_known and bool(money) and all(check['state'] == 'PASS' for check in money)
                       and position['sell_count'] > 0 and position['pnl_sol'] is not None)
        disposals = [event for signature in required for event in by_signature[signature]
                     if event['kind'] == 'sell' and event.get('mint') == mint
                     and event_within_lot(event)]
        with localcontext() as context:
            context.prec = 192
            remaining_basis = position.get('remaining_basis_sol') if remaining_basis_known else None
        evidence.update(h for check in physical + money + timing for h in check.get('evidence', []))
        results.append({'id': position['id'], 'mint': mint, 'accounts': sorted(named),
            'scope': 'Conditional selected named-account FIFO lot; hidden same-mint holdings and unobserved intervening activity remain unproved',
            'fifo_bounds': {'start': position['start'], 'end': position['end']},
            'monetary_state': 'PASS' if money_known else 'UNKNOWN', 'timing_state': 'PASS' if timing_known else 'UNKNOWN',
            'cost_basis_state': 'PASS' if basis_known else 'UNKNOWN',
            'remaining_cost_basis_state': 'PASS' if remaining_basis_known else 'UNKNOWN',
            'quantity_state': 'PASS' if physical_known and not scope_gaps else 'UNKNOWN',
            'remaining_quantity_state': 'PASS' if chronology_known and origin_known else 'UNKNOWN',
            'origin_state': 'PASS' if origin_known and physical_known and not scope_gaps else 'UNKNOWN',
            'chronology_state': 'PASS' if chronology_known else 'UNKNOWN',
            'classification_state': 'UNKNOWN', 'wallet_population_state': 'UNKNOWN', 'qualification': False,
            'observed_closed': position['end'] is not None and position['quantity_raw'] == '0' and position['status'] != 'interrupted',
            'observed_open': position['end'] is None and int(position['quantity_raw']) > 0 and position['status'] != 'interrupted',
            'fifo_status': position['status'],
            'acquired_raw': position['acquired_raw'], 'disposed_raw': position['sold_raw'], 'remaining_raw': position['quantity_raw'],
            'buy_count': position['buy_count'], 'sell_count': position['sell_count'],
            'conditional_basis_sol': position['known_basis_sol'] if basis_known else None,
            'conditional_matched_basis_sol': position['known_matched_basis_sol'] if basis_known else None,
            'conditional_proceeds_sol': position['proceeds_sol'] if money_known else None,
            'conditional_exit_fees_sol': position['exit_fees_sol'] if money_known else None,
            'conditional_lot_profit_sol': position['pnl_sol'] if money_known else None,
            'conditional_lot_roi_pct': position['roi_pct'] if money_known else None,
            'conditional_remaining_basis_sol': remaining_basis,
            'remaining_acquisition_checks': remaining_acquisition_bindings + remaining_acquisition_checks,
            'conditional_first_sale_hours': position['first_sale_hours'] if chronology_known and origin_known
                and position.get('first_sale_observation_status') == 'known' else None,
            'conditional_exit_50_hours': position['sold_50_pct_hours'] if chronology_known and origin_known else None,
            'conditional_exit_90_hours': position['sold_90_pct_hours'] if chronology_known and origin_known else None,
            'observed_start': position['start'] if timing_known else None, 'observed_end': position['end'] if timing_known else None,
            'conditional_hold_hours': position['hold_hours'] if timing_known else None,
            'required_signatures': sorted(required), 'disjoint_signatures': sorted(disjoint),
            'disposal_signatures': sorted({event['signature'] for event in disposals}),
            'closing_signatures': sorted({event['signature'] for event in disposals
                if position['end'] is not None and utc(event['timestamp']) == utc(position['end'])}),
            'evidence': sorted(h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)),
            'retained_account_funding': retained, 'gaps': sorted(set(scope_gaps)),
            'assumptions': ['No hidden earlier same-mint holdings or unobserved intervening changes are established.',
                'Separately located protocol-account funding is excluded from the quoted-trade lot; its future refund/economic value remains UNKNOWN.']})
    return results


def _selected_cohort_observations(lots, selected, transactions, raw_versions, clocks,
                                  ledger_events, consistency, inspection, start, end, research):
    """Project existing FIFO facts into explicitly selected, conditional cohorts.

    This is a metric projection, never another ledger or a wallet population
    certificate. Every candidate in the declared selected cohort remains in its
    denominator. An unavailable native record may conceal an additional episode
    and therefore revokes the selected census even if individual lots remain
    useful. Open holdings are not a dependency of completed-lot timing.
    """
    by_signature = defaultdict(list)
    for event in ledger_events:
        by_signature[event.get('signature')].append(event)
    source_set = consistency.get('source_set', {})
    lot_ordinals, lot_index = defaultdict(int), {}
    for lot in lots:
        lot_ordinals[lot['mint']] += 1
        lot_index[(lot['mint'], lot_ordinals[lot['mint']])] = lot
    result = {'version': 'selected-cohort-observations-v2',
        'scope': 'Conditional cohorts of selected named-account FIFO observations; no historical wallet or eligible-asset population is established',
        'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN',
        'valuation_state': 'UNKNOWN', 'qualification': False, 'intervals': {}}

    def census(begin):
        checks, excluded, unresolved = [], [], []
        for signature in selected:
            versions = raw_versions[signature]
            bodies = [row.get('raw') for row in versions]
            failed = bool(bodies) and all(_safe_raw(raw) and raw['meta']['err'] is not None for raw in bodies)
            clock = assess_interval_membership(clocks, signature, begin, end)
            if failed or clock['state'] == 'PASS' and clock.get('member') is False:
                excluded.append(signature)
                continue
            observed = transactions[signature]
            physical = [check for pair in observed['boundaries'].values() for check in pair['checks'].values()]
            identity = consistency.get('transactions', {}).get(signature, {}).get('identity', {})
            known = (clock['state'] == 'PASS' and bool(bodies) and all(_safe_raw(raw) for raw in bodies)
                     and identity.get('state') == 'PASS' and not observed['gaps']
                     and all(check['state'] == 'PASS' for check in physical)
                     and all(event['kind'] != 'unsupported' for event in by_signature[signature]))
            check = _check(known, 'Selected in-scope native activity has supported identity, chronology and physical decoding.' if known else
                'Selected in-scope native activity could conceal or alter a holding episode.',
                observed['evidence'] + clock['evidence'], dependencies=['selected_native_activity', 'selected_interval_membership'])
            checks.append(check)
            if check['state'] != 'PASS':
                unresolved.append(signature)
        known = (inspection['state'] == 'PASS' and source_set.get('state') == 'PASS'
                 and all(check['state'] == 'PASS' for check in checks))
        check = _check(known, 'All selected in-scope native activity is inspected; hidden historical wallet activity remains outside this census.' if known else
            'Selected activity, linked source inventory or named-lot inspection is unresolved; no candidate may disappear from a known denominator.',
            source_set.get('evidence', []) + [h for check in checks for h in check['evidence']]
            + [row.get('evidence_hash') for versions in raw_versions.values() for row in versions],
            scope='Selected native records only', dependencies=['selected_native_activity', 'linked_native_source_inventory', 'named_lot_inspection'])
        return {**check, 'excluded_signatures': sorted(excluded), 'unresolved_signatures': sorted(unresolved)}

    def projection(lot, field):
        return _check(lot.get(field) == 'PASS',
            f"Named-account lot {lot['id']} requires its own {field} proof.", lot['evidence'],
            scope=lot['scope'], dependencies=[field])

    def closure_membership(lot, begin):
        receipts = [assess_interval_membership(clocks, signature, begin, end)
                    for signature in lot.get('closing_signatures', [])]
        supported = bool(receipts) and all(row['state'] == 'PASS' for row in receipts)
        values = {row.get('member') for row in receipts}
        check = _check(supported and len(values) == 1, 'Every raw closing-clock possibility agrees on this half-open interval.',
            [h for row in receipts for h in row['evidence']], dependencies=['closing_record_membership'])
        return {**check, 'member': next(iter(values)) if check['state'] == 'PASS' else None}

    with localcontext() as context:
        context.prec = 192
        for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                            ('verification_90d', end - timedelta(days=90))):
            population = census(begin)
            candidates, membership_checks = [], []
            for lot in lots:
                bounds = lot['fifo_bounds']
                if bounds['end'] is None or lot['remaining_raw'] != '0':
                    continue
                membership = closure_membership(lot, begin)
                membership_checks.append(membership)
                if membership['state'] == 'PASS' and membership['member'] is False:
                    continue
                candidates.append(lot)
            common = [population] + [row for row in membership_checks if row['state'] != 'PASS']
            closure = _combine(common + [projection(lot, 'quantity_state') for lot in candidates]
                + [projection(lot, 'origin_state') for lot in candidates]
                + [projection(lot, 'chronology_state') for lot in candidates],
                'The complete declared selected closing cohort needs every candidate physical/origin/clock proof; open stock is separate.',
                scope='Selected named-account episodes whose strict-zero close is in this interval')
            money = _combine([closure] + [projection(lot, 'monetary_state') for lot in candidates],
                'Every selected closed-cohort candidate needs supported acquisition/disposal costs; losing and breakeven candidates remain included.')
            timing = _combine([closure] + [projection(lot, 'timing_state') for lot in candidates],
                'Every selected closed-cohort candidate needs supported start/closing clocks independently of monetary costs and valuation.')
            money_known = bool(candidates) and money['state'] == 'PASS'
            timing_known = bool(candidates) and timing['state'] == 'PASS'
            profits = [decimal(lot['conditional_lot_profit_sol'], signed=True, max_length=512) for lot in candidates] if money_known else []
            def typical(field):
                if not timing_known or any(lot.get(field) is None for lot in candidates):
                    return None
                return canonical(median([decimal(lot[field], signed=True, max_length=512) for lot in candidates]))
            closed = {'scope': closure['scope'], 'candidate_count': len(candidates),
                'candidate_lot_ids': [lot['id'] for lot in candidates],
                'population_state': closure['state'],
                'monetary_state': 'PASS' if money_known else 'UNKNOWN',
                'timing_state': 'PASS' if timing_known else 'UNKNOWN',
                'conditional_profit_sol': canonical(sum(profits, Decimal(0))) if money_known else None,
                'conditional_win_rate_pct': canonical(Decimal(sum(value > 0 for value in profits)) / Decimal(len(profits)) * 100) if money_known else None,
                'conditional_median_roi_pct': canonical(median([decimal(lot['conditional_lot_roi_pct'], signed=True, max_length=512)
                    for lot in candidates])) if money_known and all(lot['conditional_lot_roi_pct'] is not None for lot in candidates) else None,
                'conditional_median_hold_hours': typical('conditional_hold_hours'),
                'conditional_first_sale_hours': typical('conditional_first_sale_hours'),
                'conditional_exit_50_hours': typical('conditional_exit_50_hours'),
                'conditional_exit_90_hours': typical('conditional_exit_90_hours'),
                'checks': {'population': closure, 'monetary': money, 'timing': timing},
                'evidence': sorted(set(closure['evidence'] + money['evidence'] + timing['evidence'])),
                'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN', 'qualification': False}
            result['intervals'][name] = {'start': begin.isoformat(), 'end': end.isoformat(),
                'selected_record_census': population, 'closed_cohort': closed}
            # Consume the existing research FIFO's exact per-disposal result.
            # Episode bounds, immutable source hashes and the original decoded
            # sale bind each projection; supplied row flags alone grant nothing.
            sales, sale_checks, quantity_sale_checks, basis_sale_checks = [], [], [], []
            for row in research.get('historical_sales_detail', []):
                if row['mint'] == WSOL:
                    continue
                membership = assess_interval_membership(clocks, row.get('signature'), begin, end)
                if membership['state'] == 'PASS' and membership.get('member') is False:
                    continue
                episode = row.get('fifo_episode', {})
                lot = lot_index.get((episode.get('mint'), episode.get('ordinal')))
                row_hashes = row.get('evidence', [])
                decoded = [event for event in by_signature[row.get('signature')] if event['kind'] == 'sell'
                    and event.get('mint') == row['mint'] and event.get('quantity_raw') == row['quantity_raw']
                    and utc(event['timestamp']) == utc(row['timestamp']) and event.get('evidence') == row_hashes]
                bound = (lot is not None and len(decoded) == 1 and bool(row_hashes)
                         and set(row_hashes) <= set(lot['evidence'])
                         and row.get('signature') in lot.get('disposal_signatures', [])
                         and row.get('signature') in lot.get('required_signatures', [])
                         and utc(lot['fifo_bounds']['start']) <= utc(row['timestamp'])
                         and (lot['fifo_bounds']['end'] is None or utc(row['timestamp']) <= utc(lot['fifo_bounds']['end'])))
                evidence = row_hashes + membership['evidence'] + (lot['evidence'] if lot else [])
                quantity_check = _check(bound and membership['state'] == 'PASS' and row.get('quantity_state') == 'PASS'
                    and lot.get('quantity_state') == 'PASS' if bound else False,
                    'Selected disposal quantity must bind its exact raw sale and named-account physical proof.',
                    evidence, dependencies=['disposal_source_binding', 'quantity_state', 'disposal_interval_membership'])
                basis_check = _check(bound and quantity_check['state'] == 'PASS' and lot.get('origin_state') == 'PASS'
                    and lot.get('chronology_state') == 'PASS' and row.get('cost_basis_state') == 'PASS'
                    and row.get('origin_state') == 'PASS' and row.get('clock_state') == 'PASS'
                    and row.get('conditional_matched_basis_sol') is not None if bound else False,
                    'Disposed basis consumes supported acquisition units; unconsumed holdings, proceeds and sale fees have separate dependencies.',
                    evidence, dependencies=['disposal_source_binding', 'disposed_fifo_origins', 'acquisition_cost_roles'])
                monetary_check = _check(bound and quantity_check['state'] == 'PASS' and lot.get('origin_state') == 'PASS'
                    and lot.get('chronology_state') == 'PASS' and row.get('monetary_state') == 'PASS'
                    and row.get('origin_state') == 'PASS' and row.get('clock_state') == 'PASS'
                    and all(row.get(field) is not None for field in ('conditional_matched_basis_sol', 'conditional_profit_sol',
                        'conditional_proceeds_sol', 'conditional_exit_fees_sol')) if bound else False,
                    'Selected disposal profit must consume an exact supported FIFO origin, consideration, cost and raw clock dependency set.',
                    evidence, dependencies=['disposal_source_binding', 'cost_basis_state', 'monetary_state', 'origin_state', 'clock_state'])
                quantity_sale_checks.append(quantity_check); sale_checks.append(monetary_check)
                basis_sale_checks.append(basis_check)
                sales.append({**row, 'quantity_state': quantity_check['state'], 'monetary_state': monetary_check['state'],
                    'cost_basis_state': basis_check['state'],
                    'checks': {'quantity': quantity_check, 'basis': basis_check, 'monetary': monetary_check},
                    'conditional_matched_basis_sol': row['conditional_matched_basis_sol'] if basis_check['state'] == 'PASS' else None,
                    'conditional_profit_sol': row['conditional_profit_sol'] if monetary_check['state'] == 'PASS' else None,
                    'conditional_proceeds_sol': row['conditional_proceeds_sol'] if monetary_check['state'] == 'PASS' else None,
                    'conditional_exit_fees_sol': row['conditional_exit_fees_sol'] if monetary_check['state'] == 'PASS' else None})
            sale_quantity = _combine([population] + quantity_sale_checks,
                'Every declared selected disposal remains in its interval denominator; unmatched origins do not invent monetary basis.')
            sale_money = _combine([population] + sale_checks,
                'Every declared selected disposal needs its own supported FIFO origin and cost proof; unresolved sales remain counted.')
            sale_basis = _combine([population] + basis_sale_checks,
                'Every declared selected disposal needs matched acquisition cost and origin evidence in its own interval.')
            sale_known = bool(sales) and sale_money['state'] == 'PASS'
            basis_known = bool(sales) and sale_basis['state'] == 'PASS'
            quantities_by_mint = defaultdict(int)
            if sale_quantity['state'] == 'PASS':
                for row in sales:
                    quantities_by_mint[row['mint']] += int(row['quantity_raw'])
            result['intervals'][name]['disposed_units'] = {
                'scope': 'Selected named-account disposal units in this interval; excludes unallocated overhead, eligibility and wallet-wide profit',
                'candidate_sale_count': len(sales), 'sales': sales,
                'quantity_state': sale_quantity['state'], 'monetary_state': 'PASS' if sale_known else 'UNKNOWN',
                'cost_basis_state': 'PASS' if basis_known else 'UNKNOWN',
                'disposed_raw_by_mint': {mint: str(quantity) for mint, quantity in sorted(quantities_by_mint.items())}
                    if sale_quantity['state'] == 'PASS' else None,
                'conditional_profit_sol': canonical(sum((decimal(row['conditional_profit_sol'], signed=True, max_length=512) for row in sales), Decimal(0))) if sale_known else None,
                'conditional_matched_basis_sol': canonical(sum((decimal(row['conditional_matched_basis_sol'], max_length=512) for row in sales), Decimal(0))) if basis_known else None,
                'conditional_proceeds_sol': canonical(sum((decimal(row['conditional_proceeds_sol'], max_length=512) for row in sales), Decimal(0))) if sale_known else None,
                'conditional_exit_fees_sol': canonical(sum((decimal(row['conditional_exit_fees_sol'], max_length=512) for row in sales), Decimal(0))) if sale_known else None,
                'checks': {'quantity': sale_quantity, 'basis': sale_basis, 'monetary': sale_money},
                'evidence': sorted(set(sale_quantity['evidence'] + sale_basis['evidence'] + sale_money['evidence'])),
                'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN', 'qualification': False}

        # The boundary is common to all three windows. No per-period flow or
        # valuation completeness is inferred from this remaining-stock view.
        population = census(utc(0))
        open_lots = [lot for lot in lots if lot['fifo_bounds']['end'] is None and int(lot['remaining_raw']) > 0]
        quantities = _combine([population] + [projection(lot, 'quantity_state') for lot in open_lots]
            + [projection(lot, 'origin_state') for lot in open_lots]
            + [projection(lot, 'chronology_state') for lot in open_lots],
            'Remaining quantities describe every declared selected open lot at the report end; hidden accounts remain unproved.',
            scope='Selected named-account FIFO stock at report end')
        basis = _combine([quantities] + [projection(lot, 'remaining_cost_basis_state') for lot in open_lots],
            'Remaining cost is existing FIFO acquisition basis less its matched disposed basis; a historical valuation mark is separate.')
        result['open_stock'] = {'at': end.isoformat(), 'scope': quantities['scope'],
            'candidate_count': len(open_lots), 'candidate_lot_ids': [lot['id'] for lot in open_lots],
            'quantity_state': quantities['state'],
            'cost_basis_state': 'PASS' if open_lots and basis['state'] == 'PASS' else 'UNKNOWN',
            'conditional_remaining_basis_sol': canonical(sum((decimal(lot['conditional_remaining_basis_sol'], max_length=512) for lot in open_lots), Decimal(0)))
                if open_lots and basis['state'] == 'PASS' else None,
            'lots': [{'id': lot['id'], 'mint': lot['mint'], 'remaining_raw': lot['remaining_raw'] if lot['remaining_quantity_state'] == 'PASS' else None,
                'quantity_state': lot['remaining_quantity_state'], 'observed_physical_state': lot['quantity_state'], 'cost_basis_state': lot['remaining_cost_basis_state'],
                'conditional_remaining_basis_sol': lot['conditional_remaining_basis_sol'], 'evidence': lot['evidence']}
                for lot in open_lots],
            'checks': {'quantity': quantities, 'cost_basis': basis},
            'evidence': sorted(set(quantities['evidence'] + basis['evidence'])),
            'valuation_state': 'UNKNOWN', 'closing_value_sol': None,
            'wallet_population_state': 'UNKNOWN', 'classification_state': 'UNKNOWN', 'qualification': False}
    return result


def derive_wallet_evidence(records, *, all_records, wallet, window, source_consistency, chronology,
                           source_receipts=(), history_evidence=None, positions=None, events=(), raw_sources=()):
    """Return source-derived observed facts and honest wallet metric dependencies.

    Input assessments/positions/events are advisory only: raw linked records are
    replayed with shared validators and decoder. Current source types cannot prove
    historical population, even when all supplied flags claim PASS/completeness.
    """
    if not _valid_account(wallet):
        raise ValueError('A valid public wallet is required')
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('A positive report window is required')
    raw_sources, source_receipts = list(raw_sources), list(source_receipts)
    selected, linked = {}, {}
    selected_rows = list(records)
    for row in sorted(selected_rows, key=lambda row: str(row.get('evidence_hash')) if isinstance(row, dict) else ''):
        if not isinstance(row, dict) or not isinstance(row.get('signature'), str) or not row['signature']:
            raise ValueError('Selected raw records require explicit signature identities')
        selected.setdefault(row['signature'], row)
    # A frozen query-role index is negative-only, but its readable bytes must
    # still undergo native association.  A caller label cannot hide a raw
    # alternative; missing query-only bytes do not invent native relevance.
    source_rows = _resolved_sources(raw_sources, source_receipts)
    negative_links = raw_native_dependencies(source_rows, (), selected)
    for row in list(all_records) + selected_rows + negative_links:
        if isinstance(row, dict):
            key = (row.get('signature'), row.get('evidence_hash'))
            if key in linked and linked[key].get('raw') != row.get('raw'):
                linked[key] = {**linked[key], 'raw': None}
            else:
                linked.setdefault(key, row)
    if len(linked) > MAX_RECORDS:
        raise ValueError('Raw wallet evidence exceeds the fixed record inspection limit')
    linked = [linked[key] for key in sorted(linked, key=repr)]
    account_steps = sum(len(raw.get('meta', {}).get(name, [])) for row in linked
        if isinstance(raw := row.get('raw'), dict) and isinstance(raw.get('meta'), dict)
        for name in ('preTokenBalances', 'postTokenBalances') if isinstance(raw['meta'].get(name), list))
    quantity_budget_exceeded = account_steps > MAX_ACCOUNT_STEPS
    selected = {key: selected[key] for key in sorted(selected, key=str) if isinstance(key, str) and key}
    pages, blocks, indexed, contents = _clock_inputs(source_rows, (), wallet)
    # Unsafe container shapes remain explicit unavailable records to shared checks.
    safe_linked = [{key: value for key, value in row.items() if key != 'transaction_index'} |
                   {'raw': row.get('raw') if _safe_raw(row.get('raw')) else None} for row in linked]
    consistency = assess_source_consistency(safe_linked, wallet=wallet, page_receipts=pages,
        indexed_receipts=indexed, archive_contents=contents)
    clocks = apply_unresolved_chronology(assess_chronology(safe_linked, page_receipts=pages,
        block_receipts=blocks, indexed_receipts=indexed), safe_linked, contents)
    def derived_record(row):
        return with_derived_order([row], clocks)[0]
    versions, raw_versions = defaultdict(list), defaultdict(list)
    for row in linked:
        raw_versions[row.get('signature')].append(row)
        if quantity_budget_exceeded:
            # The archive's declared input capacity remains valid. Inspection
            # budget loss revokes physical/ownership observations while native
            # identity, clocks and wallet-paid fees keep their own checks.
            observation = {'signature': row.get('signature'), 'hash': row.get('evidence_hash'),
                'boundaries': {}, 'lifecycle': [], 'transfers': [], 'trades': [], 'failed': None,
                'disjoint_operations': [],
                'gaps': ['Physical account-version inspection budget exceeded; token observations are unsupported.']}
        else:
            observation = _observe(derived_record(row), wallet)
        versions[row.get('signature')].append(observation)
    transactions, accounts, acquisitions, fee_checks, identity_checks = {}, defaultdict(list), [], [], []
    quantity_checks, owner_checks, lifecycle_checks, cost_checks = [], [], [], []
    cartesian_budget_exceeded, account_version_steps = False, 0
    for signature, primary in selected.items():
        variants = versions[signature]
        evidence = [row['hash'] for row in variants]
        group = consistency['transactions'].get(signature, {})
        identity_fact = group.get('identity', _check(False, 'Native identity unavailable', evidence))
        source_set = consistency.get('source_set', {})
        identity = {**identity_fact, **_check(identity_fact.get('state') == 'PASS' and source_set.get('state') == 'PASS',
            identity_fact.get('reason', 'Native identity unavailable') if source_set.get('state') == 'PASS' else source_set.get('reason', 'Linked native source inventory unresolved'),
            identity_fact.get('evidence', evidence) + source_set.get('evidence', []), dependencies=['linked_native_source_inventory'])}
        identity_checks.append(identity)
        selected_observation = next((r for r in variants if r['hash'] == primary.get('evidence_hash')), variants[0])
        observed = {'signature': signature, 'evidence': sorted({h for h in evidence if isinstance(h, str) and HASH.fullmatch(h)}), 'boundaries': {},
                    'lifecycle': [], 'internal_transfers': [], 'mint_aggregates': {}, 'checks': {},
                    'disjoint_operations': selected_observation['disjoint_operations'],
                    'gaps': sorted({gap for row in variants for gap in row['gaps']})}
        relevant_accounts = sorted({account for row in variants for account in row['boundaries']})
        version_steps = len(relevant_accounts) * len(variants)
        account_version_steps += version_steps
        if version_steps > MAX_ACCOUNT_STEPS:
            cartesian_budget_exceeded = True
            observed['gaps'].append('Linked account-union/version inspection budget exceeded; physical/ownership evidence is unresolved.')
            budget_check = _check(False, observed['gaps'][-1], evidence, dependencies=['complete_account_version_inspection'])
            quantity_checks.append(budget_check); owner_checks.append(budget_check); lifecycle_checks.append(budget_check)
            relevant_accounts = []  # No arbitrary inspected prefix certifies this population.
        for account in relevant_accounts:
            pairs = [r['boundaries'].get(account) for r in variants]
            primary_pair = selected_observation['boundaries'].get(account)
            agreement = bool(primary_pair) and all(pair is not None and _semantic(pair) == _semantic(primary_pair) for pair in pairs)
            checks = {}
            for key in ('ownership', 'quantities', 'lifecycle'):
                checks[key] = _check(identity.get('state') == 'PASS' and agreement and all(
                    pair is not None and pair['checks'][key]['state'] == 'PASS' for pair in pairs),
                    'Every linked raw version supports the same phase-specific account facts and executed operations.' if agreement else
                    'A linked account boundary/operation is missing or disagrees; no selected version overrides it.', evidence,
                    paths=(p for pair in pairs if pair for p in pair['checks'][key]['raw_paths']))
            pair = primary_pair or next(pair for pair in pairs if pair)
            serialized = {phase: {**pair[phase], 'quantity': str(pair[phase]['quantity'])} if pair[phase] else None
                          for phase in ('pre', 'post')}
            serialized.update(program=pair['program'], flow_raw=pair['flow_raw'], checks=checks)
            observed['boundaries'][account] = serialized
            accounts[account].append({'signature': signature, **serialized})
            owner_checks.append(checks['ownership']); quantity_checks.append(checks['quantities']); lifecycle_checks.append(checks['lifecycle'])
        semantic_lifecycle = lambda row: [(r['kind'], r['account'], r['applied'], r['facts']) for r in row['lifecycle']]
        lifecycle_agrees = all(semantic_lifecycle(r) == semantic_lifecycle(selected_observation) for r in variants)
        for row in selected_observation['lifecycle']:
            observed['lifecycle'].append({**row, 'check': _check(lifecycle_agrees and not observed['gaps'],
                'Failed operations are retained as attempts only.' if not row['applied'] else 'Linked executed lifecycle facts agree.', evidence, paths=[row['path']])})
        aggregates = defaultdict(lambda: {'pre': 0, 'post': 0, 'decimals': set(), 'accounts': set(), 'checks': []})
        for account, pair in observed['boundaries'].items():
            for phase in ('pre', 'post'):
                value = pair[phase]
                if value and value['owner'] == wallet:
                    entry = aggregates[value['mint']]
                    entry[phase] += int(value['quantity']); entry['decimals'].add(value['decimals']); entry['accounts'].add(account)
                    entry['checks'] += [pair['checks'][key] for key in ('quantities', 'ownership', 'lifecycle')]
        for mint, aggregate in sorted(aggregates.items()):
            observed['mint_aggregates'][mint] = {'pre_raw': str(aggregate['pre']), 'post_raw': str(aggregate['post']),
                'delta_raw': str(aggregate['post'] - aggregate['pre']), 'decimals': next(iter(aggregate['decimals'])) if len(aggregate['decimals']) == 1 else None,
                'accounts': sorted(aggregate['accounts']), 'check': _check(len(aggregate['decimals']) == 1 and all(c['state'] == 'PASS' for c in aggregate['checks']),
                    'Exact sum over observed transaction balance accounts; absent wallet accounts are outside this population.', evidence,
                    scope='Token accounts evidenced in this selected transaction only'), 'wallet_population': 'UNKNOWN'}
        for transfer in selected_observation['transfers']:
            source, destination = (observed['boundaries'].get(transfer[k]) for k in ('source', 'destination'))
            owned = source and destination and all(pair[phase] and pair[phase]['owner'] == wallet
                for pair in (source, destination) for phase in ('pre', 'post'))
            if owned:
                checks = [pair['checks'][key] for pair in (source, destination) for key in ('quantities', 'ownership', 'lifecycle')]
                observed['internal_transfers'].append({**transfer, 'check': _combine(checks,
                    'Both observed endpoints are wallet-owned; this token transfer contributes zero mint-aggregate change.')})
        native = group.get('native', {}).get('wallet_network_fees_sol', {})
        fee_check = _check(native.get('state') == 'PASS', native.get('reason', 'Native fee/payer facts unavailable'), native.get('evidence', evidence))
        fee_checks.append(fee_check)
        native_keys = _keys(primary['raw']['transaction']['message'], primary['raw']['meta']) if _safe_raw(primary.get('raw')) else []
        wallet_fee = primary['raw']['meta'].get('fee') if native_keys and native_keys[0] == wallet else 0 if native_keys else None
        observed['network_fee'] = {'lamports': str(wallet_fee) if fee_check['state'] == 'PASS' and type(wallet_fee) is int else None,
                                   'check': fee_check, 'role': 'Actual selected wallet-paid network fee; economic allocation is separate'}
        native_trades = selected_observation['trades']
        trades_agree = all(len(r['trades']) == len(native_trades) and all(all(a.get(k) == b.get(k) for k in
            ('kind', 'mint', 'quantity_raw', 'decimals', 'amount_sol', 'fee_sol', 'paid_by_wallet', 'venue', 'native_cash_role_state'))
            for a, b in zip(r['trades'], native_trades)) for r in variants)
        decoded_events = decode_supported_swaps([derived_record(primary)], wallet)['events'] if _safe_raw(primary.get('raw')) else []
        try:
            validate_fee_allocations(decoded_events)
            allocation_valid = True
        except (ValueError, TypeError, KeyError):
            allocation_valid = False
        transaction_cost_checks = []
        for trade in native_trades:
            known = identity.get('state') == 'PASS' and trades_agree and allocation_valid and fee_check['state'] == 'PASS' and trade.get('amount_sol') is not None and trade.get('fee_sol') is not None and trade.get('native_cash_role_state') == 'PASS'
            check = _check(known, 'Supported raw swap consideration and unique raw network fee allocation agree across every linked version.', evidence,
                           paths=[trade.get('path', 'transaction')], scope='Observed supported trade only; disposed-lot population is separate')
            cost_checks.append(check)
            transaction_cost_checks.append(check)
            if trade['kind'] == 'buy':
                paid_fee = decimal(trade['fee_sol']) if trade.get('paid_by_wallet') is True else Decimal(0)
                acquisitions.append({'signature': signature, 'mint': trade['mint'], 'quantity_raw': trade['quantity_raw'],
                    'basis_sol': canonical(decimal(trade['amount_sol']) + paid_fee) if known else None,
                    'classification': 'settlement' if trade['mint'] == WSOL else 'unknown', 'check': check})
        observed['checks']['identity'] = identity
        observed['checks']['cost_roles'] = _combine(transaction_cost_checks,
            'Observed supported consideration and one network-fee allocation; retained protocol funding is separate.')
        observed['checks']['clock'] = clocks['transactions'].get(signature, _check(False, 'Clock unavailable', evidence))
        transactions[signature] = observed
    all_hashes = [row.get('evidence_hash') for row in linked]
    from .real_coverage import derive_indexed_coverage
    # Coverage verifies retained original bytes separately from semantic format
    # support. Do not replace an unsupported original with None for this check;
    # shared accounting/chronology still use the rejecting safe_linked view.
    query_coverage = derive_indexed_coverage(selected.values(), all_records=linked,
        raw_sources=source_rows, wallet=wallet, window=window,
        source_consistency=consistency, chronology=clocks)
    unresolved = _combine([query_coverage['historical_population']],
        query_coverage['historical_population']['reason'], scope='Wallet-wide historical population')
    # Preserve selected raw dependencies even when no indexed query exists.
    unresolved['evidence'] = sorted(set(unresolved['evidence'] +
        [h for h in all_hashes if isinstance(h, str) and HASH.fullmatch(h)]))
    intervals, memberships = {}, {}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)), ('verification_90d', end - timedelta(days=90))):
        memberships[name] = {signature: assess_interval_membership(clocks, signature, begin, end) for signature in selected}
        intervals[name] = _check(False, 'Selected record clocks do not establish terminal page bounds or complete historical wallet population.',
            (h for row in memberships[name].values() for h in row['evidence']), scope=f'Wallet-wide [{begin.isoformat()},{end.isoformat()})',
            dependencies=['historical_population', f'{name}_terminal_paging'])
        intervals[name].update(start=begin.isoformat(), end=end.isoformat(), selected_record_membership=memberships[name])
        query = query_coverage['intervals'][name]
        intervals[name].update(query_records_state=query['query_records_state'],
            supported_record_state=query['supported_record_state'],
            query_scope=query['scope'], query_source_hashes=query.get('source_hashes', []))
        intervals[name]['reason'] = ('Terminal documented query membership is supported; historical wallet membership remains unproved.'
            if query['query_records_state'] == 'PASS' else query['reason'] + ' Historical wallet membership remains unproved.')
    fee_projection_checks = []
    for signature, receipt in memberships['report_period'].items():
        network_fee = transactions[signature]['network_fee']
        zero = network_fee['lamports'] == '0' and network_fee['check']['state'] == 'PASS'
        fee_projection_checks.append(_check(receipt['state'] == 'PASS' or zero,
            'Independently proved zero wallet-paid fee contributes zero under every possible interval placement.' if zero else receipt['reason'],
            receipt['evidence'] + network_fee['check']['evidence'], scope='Selected in-window fee projection; exact clock/order remains separate'))
    # The FIFO engine is reused to derive observed disposed-basis/position facts.
    # Raw events are re-decoded here; caller-supplied normalized declarations are ignored.
    safe_selected = [{**derived_record(row), 'raw': row.get('raw') if _safe_raw(row.get('raw')) else None} for row in selected.values()]
    native_events = decode_supported_swaps(safe_selected, wallet)['events']
    supported_signatures = {e['signature'] for e in native_events if e['kind'] in ('buy', 'sell')}
    quantity_only = [event for row in safe_selected if row['signature'] not in supported_signatures
        and (event := _quantity_only_trade(row, transactions[row['signature']], wallet)) is not None]
    quantity_signatures = {event['signature'] for event in quantity_only}
    generic = decode_transactions([row for row in safe_selected if row['signature'] not in supported_signatures | quantity_signatures], wallet)
    ledger_events = generic['events'] + [e for e in native_events if e.get('signature') in supported_signatures] + quantity_only
    native_role_checks = []
    for signature in selected:
        group = consistency['transactions'].get(signature, {})
        native_delta = group.get('native', {}).get('native_wallet_delta_sol', {})
        expected = _decoded_native_movement([e for e in ledger_events if e.get('signature') == signature])
        for row in raw_versions[signature]:
            check = _native_role_check(row, wallet, expected)
            check['signature'] = signature
            if native_delta.get('state') != 'PASS' or quantity_budget_exceeded or cartesian_budget_exceeded:
                check.update(state='UNKNOWN', reason='Linked native endpoint or account/role inspection is unresolved; no role certainty survives its loss.')
            native_role_checks.append(check)
    fifo_positions, fifo_gap = [], None
    try:
        fifo_positions = analyze(ledger_events, start.isoformat(), end.isoformat(), history_complete=False)['positions']
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        fifo_gap = str(exc)
    observed_disposed_basis = _check(not fifo_gap and not quantity_budget_exceeded and not cartesian_budget_exceeded
        and bool(fifo_positions) and all(p['basis_sol'] is not None and
        p['matched_basis_sol'] is not None and p['status'] != 'interrupted' for p in fifo_positions)
        and all(c['state'] == 'PASS' for c in identity_checks + cost_checks + owner_checks + quantity_checks),
        fifo_gap or 'The existing FIFO engine resolves basis for selected observed units; unobserved inventory remains separately unproved.',
        (h for p in fifo_positions for h in p['evidence']), dependencies=['observed_raw_trade_costs', 'observed_incoming_origins'])
    raw_roles = _check(bool(ledger_events) and all(e['kind'] in ('buy', 'sell', 'fee', 'internal_transfer') for e in ledger_events)
        and not quantity_budget_exceeded and not cartesian_budget_exceeded
        and bool(native_role_checks) and all(c['state'] == 'PASS' for c in cost_checks + fee_checks + owner_checks + quantity_checks + native_role_checks),
        'Every selected decoded economic movement has a supported trade/network-fee/internal role; unsupported/external roles remain gaps.', all_hashes,
        paths=(e.get('path', 'meta') for e in ledger_events))
    observed_positions = _check(not fifo_gap and bool(fifo_positions) and all(p['quantity_raw'] == '0' and p['end'] is not None
        and p['status'] != 'interrupted' for p in fifo_positions) and bool(quantity_checks) and all(c['state'] == 'PASS' for c in quantity_checks),
        fifo_gap or 'Selected FIFO episode closure reconciles with observed integer quantity transitions; complete wallet population is separate.', all_hashes,
        dependencies=['observed_quantities', 'observed_fifo_episodes'])
    # Consecutive selected observations cannot silently bridge a contradictory endpoint.
    continuity_checks = list(quantity_checks)
    for account, observations in accounts.items():
        def placement(row):
            clock = clocks['transactions'].get(row['signature'], {})
            at, slot, index = (clock.get(k) for k in ('canonical_time', 'slot', 'transaction_index'))
            return (at if type(at) is int else -1, slot if type(slot) is int else -1,
                    index if type(index) is int and clock.get('order_state') == 'PASS' else -1, row['signature'])
        ordered = sorted(observations, key=placement)
        for previous, following in zip(ordered, ordered[1:]):
            before, after = previous['post'], following['pre']
            previous_place, following_place = placement(previous), placement(following)
            order_known = (previous_place[0] >= 0 and following_place[0] >= 0 and previous_place[1] >= 0 and following_place[1] >= 0
                           and (previous_place[1] != following_place[1] or 0 <= previous_place[2] < following_place[2]))
            continuous = order_known and bool(before and after) and all(before[k] == after[k] for k in ('quantity', 'owner', 'mint', 'decimals'))
            continuity_checks.append(_check(continuous, 'Consecutive selected account boundaries agree; unobserved intervening history remains separately unproved.',
                previous['checks']['quantities']['evidence'] + following['checks']['quantities']['evidence']))
    clock_checks = []
    for signature in selected:
        row = clocks['transactions'].get(signature, {})
        clock_checks.append(_check(row.get('time_state') == 'PASS' and row.get('state') == 'PASS',
            row.get('reason', 'Native chronology unavailable'), row.get('evidence', [])))
    observed_disposed_basis = _combine([observed_disposed_basis] + clock_checks + continuity_checks,
        'Observed FIFO basis requires agreeing raw chronology, selected account continuity and supported acquisition costs.')
    observed_positions = _combine([observed_positions] + clock_checks + continuity_checks,
        'Observed episode reconstruction requires agreeing raw chronology and selected account continuity.')
    components = {'historical_population': unresolved,
        'event_ownership': _combine(owner_checks, 'Observed phase-specific owners/lifecycle, compared across all linked raw versions.'),
        'quantity_continuity': _combine(continuity_checks, 'Observed absolute quantities/selected continuity and operation conservation; hidden history remains separately unproved.'),
        'chronology': _combine(clock_checks, 'Shared raw/page/block clocks and ordering are consistent for selected records.'),
        'lifecycle': _combine(lifecycle_checks, 'Observed lifecycle semantics only; no historical account discovery certificate.'),
        'observed_quantities': _combine(quantity_checks, 'Exact native integer quantities for observed accounts only.'),
        'observed_cost_roles': _combine(cost_checks, 'Observed supported raw trade consideration and network-fee allocation only.'),
        'observed_acquisition_basis': _combine((a['check'] for a in acquisitions), 'Observed supported purchases have derived cost; unobserved/incoming units have no invented basis.'),
        'observed_disposed_basis': observed_disposed_basis,
        'observed_economic_roles': raw_roles,
        'observed_positions': observed_positions,
        'acquisition_basis': _combine([unresolved, observed_disposed_basis], 'Wallet disposed-unit basis requires historical population and supported FIFO origins/opening inventory.', scope='Wallet-wide acquisition basis'),
        'economic_costs': _combine([unresolved, raw_roles], 'Wallet costs require historical population and all decoded native/trade/external movement roles.', scope='Wallet-wide economic cost roles'),
        'classification': _check(False, 'WSOL is settlement; nonsettlement meme eligibility requires an accepted time-relevant source contract.',
            all_hashes + [r['hash'] for r in contents['receipts'] if r['kind'] == 'classification'], dependencies=['accepted_historical_asset_classification']),
        'positions': _combine([unresolved, observed_positions], 'Wallet positions require historical population plus raw-quantity/FIFO episode reconstruction.', scope='Wallet-wide mint aggregate positions'),
        'boundary_inventory': _check(False, 'Transaction endpoints/current snapshots are not exact all-account report-boundary inventories.',
            all_hashes + [r['hash'] for r in contents['receipts'] if r['kind'] in ('valuation', 'boundary-inventory', 'native-balance', 'owned-accounts')],
            dependencies=['exact_opening_inventory', 'exact_closing_inventory']),
        'historical_marks': _check(False, 'No accepted historical-mark adapter/source contract is established.',
            [r['hash'] for r in contents['receipts'] if r['kind'] in ('valuation', 'historical-mark')], dependencies=['accepted_historical_mark_source']),
        'valued_external_flows': _check(False, 'External flow roles/valuations cannot be defaulted to zero from selected trades.',
            all_hashes + [r['hash'] for r in contents['receipts'] if r['kind'] in ('valuation', 'capital-flow')],
            dependencies=['complete_external_flow_roles', 'historical_flow_marks']),
        'selected_record_identity': _combine(identity_checks, 'Every selected identity agrees across linked alternatives.'),
        'native_fee': _combine(fee_checks, 'Actual selected wallet-paid native fees remain independent of token/class/valuation completeness.'),
        'fee_window': _combine(fee_projection_checks, 'Each selected nonzero wallet-paid fee has supported window membership; proved zero projections remain usable.')}
    # Reuse the existing private-copy FIFO research path, not a second monetary
    # engine.  These are conditional selected-lot observations and never feed
    # strict wallet metrics.  Loss of a required raw origin/role revokes the
    # monetary observation while independent timing/fees retain their checks.
    lot_steps = len(fifo_positions) * len(raw_versions)
    lot_inspection = {'state': 'PASS' if lot_steps <= MAX_ACCOUNT_STEPS else 'UNKNOWN',
        'steps': lot_steps, 'max_steps': MAX_ACCOUNT_STEPS,
        'reason': 'Every named-account candidate is inspected.' if lot_steps <= MAX_ACCOUNT_STEPS else
            'Named-account dependency inspection budget exceeded; no prefix certifies supported lots.'}
    supported_lots = _selected_lot_observations(fifo_positions, selected, raw_versions,
        transactions, clocks, native_role_checks, ledger_events, source_rows, wallet, window_end=end.isoformat()) if lot_steps <= MAX_ACCOUNT_STEPS else []
    from .research import summarize_research
    research = summarize_research(ledger_events, start.isoformat(), end.isoformat(), history_complete=False,
        wallet_evidence={'version': VERSION, 'transactions': transactions, 'intervals': intervals,
                         'fee_projection_checks': fee_projection_checks,
                         'query_accounting': {'selected_lot_inspection': lot_inspection, 'supported_selected_lots': supported_lots}})
    conditional_profit = research.get('conditional_observed_lot_profit_sol')
    monetary_supported = observed_disposed_basis['state'] == 'PASS' and raw_roles['state'] == 'PASS'
    timing_supported = observed_positions['state'] == 'PASS'
    query_accounting = {'scope': 'Conditional FIFO over selected raw records; earlier inventory, historical population and eligibility remain separate',
        'conditional_observed_lot_profit_sol': conditional_profit if monetary_supported else None,
        'monetary_state': 'PASS' if monetary_supported and conditional_profit is not None else 'UNKNOWN',
        'reason': 'Existing FIFO matches supported selected purchase/disposal consideration and cost roles; missing historical inventory remains an explicit assumption.'
            if monetary_supported else 'A selected acquisition, chronology, quantity, ownership or economic-role dependency is unresolved.',
        'supported_swaps': research.get('supported_swaps'), 'closed_episodes': research.get('closed_episodes'),
        'unresolved_basis_sales': research.get('unresolved_basis_sales'),
        'timing_state': 'PASS' if timing_supported else 'UNKNOWN',
        'conditional_median_hold_hours': research.get('conditional_median_hold_hours') if timing_supported else None,
        'conditional_first_sale_hours': research.get('conditional_first_sale_hours') if timing_supported else None,
        'conditional_exit_50_hours': research.get('conditional_exit_50_hours') if timing_supported else None,
        'conditional_exit_90_hours': research.get('conditional_exit_90_hours') if timing_supported else None,
        'evidence': sorted({h for row in (observed_disposed_basis, raw_roles) for h in row['evidence']}),
        'query_records_state': query_coverage['intervals']['report_period']['query_records_state'],
        'wallet_population_state': unresolved['state'], 'qualification': False}
    query_accounting['selected_lot_inspection'] = lot_inspection
    query_accounting['supported_selected_lots'] = supported_lots
    cohorts = _selected_cohort_observations(supported_lots, selected, transactions, raw_versions, clocks,
        ledger_events, consistency, lot_inspection, start, end, research)
    query_accounting['selected_cohort_observations'] = cohorts
    components['observed_closed_cohort'] = {name: row['closed_cohort']['checks']['population']
        for name, row in cohorts['intervals'].items()}
    components['observed_closed_cohort_money'] = {name: row['closed_cohort']['checks']['monetary']
        for name, row in cohorts['intervals'].items()}
    components['observed_closed_cohort_timing'] = {name: row['closed_cohort']['checks']['timing']
        for name, row in cohorts['intervals'].items()}
    components['observed_open_stock'] = cohorts['open_stock']['checks']['quantity']
    components['observed_remaining_basis'] = cohorts['open_stock']['checks']['cost_basis']
    components['observed_disposal_units'] = {name: row['disposed_units']['checks']['quantity']
        for name, row in cohorts['intervals'].items()}
    components['observed_disposal_money'] = {name: row['disposed_units']['checks']['monetary']
        for name, row in cohorts['intervals'].items()}
    components['observed_disposed_basis_by_interval'] = {
        name: {**row['disposed_units']['checks']['basis'], 'interval': name}
        for name, row in cohorts['intervals'].items()}
    components['acquisition_basis_by_interval'] = {
        name: {**_combine([unresolved, check],
            'Wallet disposed-unit basis requires historical population and only the acquisition units consumed in this independent interval.',
            scope='Wallet-wide disposed-unit acquisition basis'), 'interval': name}
        for name, check in components['observed_disposed_basis_by_interval'].items()}
    role_groups, decoded_groups = defaultdict(list), defaultdict(list)
    for check in native_role_checks:
        role_groups[check['signature']].append(check)
    for event in ledger_events:
        decoded_groups[event.get('signature')].append(event)
    interval_costs = {}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        checks = []
        for signature in selected:
            membership = assess_interval_membership(clocks, signature, begin, end)
            if membership['state'] == 'PASS' and membership.get('member') is False:
                continue
            observed = transactions[signature]
            group = decoded_groups[signature]
            roles_known = bool(role_groups[signature]) and all(c['state'] == 'PASS' for c in role_groups[signature])
            supported = not any(event['kind'] in ('unsupported', 'capital', 'rent', 'wrap') for event in group)
            trades = any(event['kind'] in ('buy', 'sell') for event in group)
            fee = observed['network_fee']
            fee_known = fee['check']['state'] == 'PASS'
            zero = roles_known and supported and not trades and fee_known and fee['lamports'] == '0'
            known = (membership['state'] == 'PASS' or zero) and roles_known and supported and fee_known
            known = known and observed['checks']['identity']['state'] == 'PASS'
            known = known and (not trades or observed['checks']['cost_roles']['state'] == 'PASS')
            checks.append(_check(known,
                'Every selected in-scope native charge has supported gross roles and fee allocation; pre-window consumed acquisition costs are required separately.',
                membership['evidence'] + observed['evidence']
                    + [h for check in role_groups[signature] for h in check['evidence']],
                dependencies=['selected_interval_membership', 'native_cost_roles', 'network_fee_allocation']))
        interval_costs[name] = {**_combine(checks,
            'All selected economic cost roles in this independent interval are supported; valued external flows remain separate.'),
            'interval': name}
    components['observed_economic_roles_by_interval'] = interval_costs
    components['economic_costs_by_interval'] = {
        name: {**_combine([unresolved, check],
            'Wallet interval costs require historical population and supported period charge roles.',
            scope='Wallet-wide interval economic costs'), 'interval': name}
        for name, check in interval_costs.items()}
    closed = cohorts['intervals']['report_period']['closed_cohort']
    query_accounting['timing_state'] = closed['timing_state']
    for field in ('conditional_median_hold_hours', 'conditional_first_sale_hours',
                  'conditional_exit_50_hours', 'conditional_exit_90_hours'):
        query_accounting[field] = closed[field]
    from .historical_membership import _admit_observations
    membership = _admit_observations(selected, versions, consistency, clocks, wallet,
                                    raw_versions=raw_versions)
    components['observed_historical_membership'] = membership['observed_event_membership']
    query_accounting['historical_membership'] = membership
    from .wallet_positions import project_wallet_positions
    position_population = project_wallet_positions(selected=selected, raw_versions=raw_versions,
        transactions=transactions, clocks=clocks, consistency=consistency, fifo_positions=fifo_positions,
        ledger_events=ledger_events, wallet=wallet, window=window, cohorts=cohorts,
        inspection=lot_inspection, lots=supported_lots)
    observed_positions = position_population['checks']['observed_population']
    components['observed_positions'] = observed_positions
    components['positions'] = _combine([unresolved, observed_positions],
        'Wallet positions require historical population plus supported mint-aggregate closed and open inventory.',
        scope='Wallet-wide mint aggregate positions')
    query_accounting['position_population'] = position_population
    from .wallet_identity import derive_wallet_identity
    wallet_identity = derive_wallet_identity(list(selected.values()), all_records=linked, raw_sources=source_rows, wallet=wallet)
    components['wallet_identity'] = wallet_identity
    from .metric_evidence import compose_metric_decisions
    return {'version': VERSION, 'scope': OBSERVED_SCOPE, 'components': components,
        'inspection_budget': {'max_records': MAX_RECORDS, 'linked_records': len(linked),
            'max_account_steps': MAX_ACCOUNT_STEPS, 'account_steps': account_steps,
            'account_version_steps': account_version_steps,
            'quantity_state': 'UNKNOWN' if quantity_budget_exceeded or cartesian_budget_exceeded else 'PASS'},
        'accounts': dict(sorted(accounts.items())), 'transactions': transactions, 'acquisitions': acquisitions,
        'observed_fifo_positions': fifo_positions,
        'observed_fifo_scope': 'Raw selected-event FIFO observations before linked-source proof gates; financial authority is the typed query_accounting and metric dependencies.',
        'interval_checks': intervals, 'intervals': intervals, 'metric_dependencies': compose_metric_decisions(components, intervals),
        'fee_projection_checks': fee_projection_checks,
        'native_role_checks': native_role_checks,
        'source_dependencies': contents['receipts'], 'source_consistency': consistency, 'chronology': clocks,
        'query_coverage': query_coverage, 'query_accounting': query_accounting, 'wallet_identity': wallet_identity,
        'gaps': sorted({gap for row in transactions.values() for gap in row['gaps']} | {unresolved['reason']}),
        'provider_requests': 0, 'credential_lookups': 0}
