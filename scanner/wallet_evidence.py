"""Offline raw-fact adapter for the existing wallet accounting path.

The archive loader authenticates immutable links and verifies their bytes before
calling this module. These functions recompute semantic facts; supplied PASS
receipts, normalized events and selected-record inventories are never historical
population certificates. Observed account facts remain useful while B1 is open.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re

from .accounting import analyze, canonical, decimal, raw_quantity, utc, validate_fee_allocations
from .collector import _valid_account
from .decoder import TOKEN_IDS, SYSTEM_ID, ASSOCIATED_ID, decode_transactions
from .instruction_scope import inspect_instruction
from .investigation import _keys, _route, decode_supported_swaps, WSOL
from .position_evidence import _balance, _quantity_point, VENUES
from .source_consistency import (assess_source_consistency, source_archive_receipts,
                                 apply_unresolved_chronology)
from .chronology_evidence import assess_chronology, assess_interval_membership
from .transaction_format import supported_transaction_format

VERSION = 'wallet-raw-evidence-v1'
HASH = re.compile(r'^[a-f0-9]{64}$')
MAX_RECORDS = 10_000
MAX_ACCOUNT_STEPS = 100_000
OBSERVED_SCOPE = 'Selected archived records only; hidden accounts and intervening records are unproved'
_NONTRANSACTION_ROLES = {'signature-page', 'block-order', 'snapshot-slot', 'owned-accounts', 'native-balance',
                        'classification', 'valuation', 'boundary-inventory', 'historical-mark', 'capital-flow',
                        'synthetic-population', 'population-inventory'}


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
    result = {'signature': signature, 'hash': digest, 'boundaries': {}, 'lifecycle': [],
              'transfers': [], 'gaps': [], 'failed': None, 'trades': [], 'disjoint_operations': []}
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
                    if (account not in observed_owned and info.get('owner') != wallet and info.get('newAuthority') != wallet
                        and not view['references'] & observed_owned):
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
        return result
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result['gaps'].append(str(exc))
        return result


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
                                                     'signature_hints': set(), 'invalid_body': False})
        signature = declaration.get('signature')
        if isinstance(signature, str) and signature:
            source['signature_hints'].add(signature)
        source['signature_hints'].update(s for s in declaration.get('signature_hints', []) if isinstance(s, str))
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
    result = []
    for key in sorted(resolved, key=repr):
        source = resolved[key]
        if source['invalid_body']:
            source['payload'] = None
        source['signature_hints'] = sorted(source['signature_hints'])
        result.append(source)
    return result


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
    pages, blocks, typed = [], [], []
    for (_, digest), row in sorted(supplied.items(), key=lambda item: repr(item[0])):
        kind, payload = row.get('kind'), row.get('payload')
        if payload is not None:
            try:
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
                if hashlib.sha256(encoded).hexdigest() != digest:
                    payload = None
            except (ValueError, TypeError):
                payload = None
        if kind not in ('signature-page', 'block-order', 'snapshot-slot', 'owned-accounts', 'native-balance'):
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
    return pages, blocks, {'state': 'PASS' if typed and all(r['state'] == 'PASS' for r in typed) else 'UNKNOWN', 'receipts': typed}


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
    selected, linked = {}, {}
    selected_rows = list(records)
    for row in sorted(selected_rows, key=lambda row: str(row.get('evidence_hash')) if isinstance(row, dict) else ''):
        if not isinstance(row, dict) or not isinstance(row.get('signature'), str) or not row['signature']:
            raise ValueError('Selected raw records require explicit signature identities')
        selected.setdefault(row['signature'], row)
    source_rows = _resolved_sources(raw_sources, source_receipts)
    negative_links = []
    for source in source_rows:
        if not isinstance(source, dict):
            continue
        kind = source.get('kind', source.get('role'))
        if kind in ('transaction', 'getTransaction'):
            continue  # These are explicitly represented by all_records.
        payload = source.get('payload')
        payload = payload.get('result') if isinstance(payload, dict) and isinstance(payload.get('result'), dict) and 'transaction' in payload['result'] else payload
        transaction = payload.get('transaction') if isinstance(payload, dict) else None
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        native_signature = signatures[0] if isinstance(signatures, list) and signatures and isinstance(signatures[0], str) else None
        claims = source['signature_hints'] if kind not in _NONTRANSACTION_ROLES else []
        affected = {s for s in [native_signature] + claims if isinstance(s, str) and s in selected}
        if affected:
            # An unsupported role cannot hide a selected transaction version.
            # Its original body remains retained in the source dependency receipt.
            negative_links += [{'signature': s, 'evidence_hash': source.get('hash'), 'raw': None} for s in sorted(affected)]
        elif kind not in _NONTRANSACTION_ROLES:
            # A raw native identity can prove disjointness. An arbitrary role or
            # missing body cannot supply an exclusion by caller annotations.
            if native_signature is None or native_signature in selected:
                negative_links.append({'signature': None, 'evidence_hash': source.get('hash'), 'raw': None})
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
    if account_steps > MAX_ACCOUNT_STEPS:
        raise ValueError('Wallet account-version inspection budget exceeded')
    selected = {key: selected[key] for key in sorted(selected, key=str) if isinstance(key, str) and key}
    pages, blocks, contents = _clock_inputs(source_rows, (), wallet)
    # Unsafe container shapes remain explicit unavailable records to shared checks.
    safe_linked = [{key: value for key, value in row.items() if key != 'transaction_index'} |
                   {'raw': row.get('raw') if _safe_raw(row.get('raw')) else None} for row in linked]
    consistency = assess_source_consistency(safe_linked, wallet=wallet, page_receipts=pages, archive_contents=contents)
    clocks = apply_unresolved_chronology(assess_chronology(safe_linked, page_receipts=pages, block_receipts=blocks), safe_linked, contents)
    def derived_record(row):
        return with_derived_order([row], clocks)[0]
    versions = defaultdict(list)
    for row in linked:
        versions[row.get('signature')].append(_observe(derived_record(row), wallet))
    transactions, accounts, acquisitions, fee_checks, identity_checks = {}, defaultdict(list), [], [], []
    quantity_checks, owner_checks, lifecycle_checks, cost_checks = [], [], [], []
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
        if len(relevant_accounts) * len(variants) > MAX_ACCOUNT_STEPS:
            raise ValueError('Wallet account-version inspection budget exceeded')
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
            ('kind', 'mint', 'quantity_raw', 'decimals', 'amount_sol', 'fee_sol', 'paid_by_wallet', 'venue'))
            for a, b in zip(r['trades'], native_trades)) for r in variants)
        decoded_events = decode_supported_swaps([derived_record(primary)], wallet)['events'] if _safe_raw(primary.get('raw')) else []
        try:
            validate_fee_allocations(decoded_events)
            allocation_valid = True
        except (ValueError, TypeError, KeyError):
            allocation_valid = False
        for trade in native_trades:
            known = identity.get('state') == 'PASS' and trades_agree and allocation_valid and fee_check['state'] == 'PASS' and trade.get('amount_sol') is not None and trade.get('fee_sol') is not None
            check = _check(known, 'Supported raw swap consideration and unique raw network fee allocation agree across every linked version.', evidence,
                           paths=[trade.get('path', 'transaction')], scope='Observed supported trade only; disposed-lot population is separate')
            cost_checks.append(check)
            if trade['kind'] == 'buy':
                paid_fee = decimal(trade['fee_sol']) if trade.get('paid_by_wallet') is True else Decimal(0)
                acquisitions.append({'signature': signature, 'mint': trade['mint'], 'quantity_raw': trade['quantity_raw'],
                    'basis_sol': canonical(decimal(trade['amount_sol']) + paid_fee) if known else None,
                    'classification': 'settlement' if trade['mint'] == WSOL else 'unknown', 'check': check})
        observed['checks']['identity'] = identity
        observed['checks']['clock'] = clocks['transactions'].get(signature, _check(False, 'Clock unavailable', evidence))
        transactions[signature] = observed
    all_hashes = [row.get('evidence_hash') for row in linked]
    unresolved = _check(False, 'Current raw/address/page/snapshot source types do not prove hidden or formerly owned account population.', all_hashes,
                        scope='Wallet-wide historical population', dependencies=['accepted_historical_owner_source_contract'])
    intervals, memberships = {}, {}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)), ('verification_90d', end - timedelta(days=90))):
        memberships[name] = {signature: assess_interval_membership(clocks, signature, begin, end) for signature in selected}
        intervals[name] = _check(False, 'Selected record clocks do not establish terminal page bounds or complete historical wallet population.',
            (h for row in memberships[name].values() for h in row['evidence']), scope=f'Wallet-wide [{begin.isoformat()},{end.isoformat()})',
            dependencies=['historical_population', f'{name}_terminal_paging'])
        intervals[name].update(start=begin.isoformat(), end=end.isoformat(), selected_record_membership=memberships[name])
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
    generic = decode_transactions([row for row in safe_selected if row['signature'] not in supported_signatures], wallet)
    ledger_events = generic['events'] + [e for e in native_events if e.get('signature') in supported_signatures]
    fifo_positions, fifo_gap = [], None
    try:
        fifo_positions = analyze(ledger_events, start.isoformat(), end.isoformat(), history_complete=False)['positions']
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        fifo_gap = str(exc)
    observed_disposed_basis = _check(not fifo_gap and bool(fifo_positions) and all(p['basis_sol'] is not None and
        p['matched_basis_sol'] is not None and p['status'] != 'interrupted' for p in fifo_positions)
        and all(c['state'] == 'PASS' for c in identity_checks + cost_checks + owner_checks + quantity_checks),
        fifo_gap or 'The existing FIFO engine resolves basis for selected observed units; unobserved inventory remains separately unproved.',
        (h for p in fifo_positions for h in p['evidence']), dependencies=['observed_raw_trade_costs', 'observed_incoming_origins'])
    raw_roles = _check(bool(ledger_events) and all(e['kind'] in ('buy', 'sell', 'fee', 'internal_transfer') for e in ledger_events)
        and all(c['state'] == 'PASS' for c in cost_checks + fee_checks),
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
    from .metric_evidence import compose_metric_decisions
    return {'version': VERSION, 'scope': OBSERVED_SCOPE, 'components': components,
        'accounts': dict(sorted(accounts.items())), 'transactions': transactions, 'acquisitions': acquisitions,
        'observed_fifo_positions': fifo_positions,
        'interval_checks': intervals, 'intervals': intervals, 'metric_dependencies': compose_metric_decisions(components, intervals),
        'fee_projection_checks': fee_projection_checks,
        'source_dependencies': contents['receipts'], 'source_consistency': consistency, 'chronology': clocks,
        'gaps': sorted({gap for row in transactions.values() for gap in row['gaps']} | {unresolved['reason']}),
        'provider_requests': 0, 'credential_lookups': 0}
