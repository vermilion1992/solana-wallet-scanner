"""Offline current-account and selected economic-signer identity receipts.

This is not a historical ownership/population certificate. Transaction wrappers
are supplied by the ordinary checksum-validating archive reader. Account sources
are independently checksum checked here; labels and imported PASS declarations
never replace the retained account response or native signer fields.
"""
from __future__ import annotations

import base64
import binascii
from collections import defaultdict
import hashlib
import re

from .collector import _valid_account
from .compiled_instructions import CompiledInstructionError, resolve_account_keys
from .decoder import SYSTEM_ID
from .discovery import _signature
from .investigation import decode_supported_swaps
from .json_boundary import canonical_bytes, parse_json

VERSION = 'wallet-identity-evidence-v1'
ACCOUNT_SOURCE_VERSION = 'wallet-account-info-source-v1'
MAX_RECORDS = 10_000
MAX_ACCOUNT_BYTES = 4 * 1024 * 1024
MAX_NODES = 1_000_000
HASH = re.compile(r'^[a-f0-9]{64}$')
SCOPE = 'Current archived system-account identity and selected supported economic signers only'
_BYTE_FIELDS = {'version', 'request_hash', 'response_hash', 'request_base64', 'response_base64'}


def _hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _bytes(payload, name):
    digest, encoded = payload.get(name + '_hash'), payload.get(name + '_base64')
    if (not _hash(digest) or not isinstance(encoded, str)
            or len(encoded) > ((MAX_ACCOUNT_BYTES + 2) // 3) * 4):
        raise ValueError('Original account request/response bytes are unavailable or oversized')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Original account bytes have invalid base64') from exc
    if (len(raw) > MAX_ACCOUNT_BYTES or hashlib.sha256(raw).hexdigest() != digest
            or base64.b64encode(raw).decode('ascii') != encoded):
        raise ValueError('Original account bytes disagree with their retained checksum')
    return raw


def account_info_source(request_bytes, response_bytes):
    """Freeze original RPC bytes without relabelling an indexed native source.

    The returned envelope contains byte links, not a trusted identity decision.
    Semantic admission happens again whenever the saved report is rebuilt.
    """
    if any(not isinstance(raw, bytes) or len(raw) > MAX_ACCOUNT_BYTES
           for raw in (request_bytes, response_bytes)):
        raise ValueError('Account request/response must be bounded original bytes')
    return {'version': ACCOUNT_SOURCE_VERSION,
            **{key: value for name, raw in (('request', request_bytes), ('response', response_bytes))
               for key, value in ((name + '_hash', hashlib.sha256(raw).hexdigest()),
                                  (name + '_base64', base64.b64encode(raw).decode('ascii')))}}


def account_source_bytes(payload):
    """Recover exact bounded bytes without granting method or identity trust.

    The ordinary native adapter can inspect rejecting alternative claims even
    when an account-labelled envelope actually contains a transaction response.
    Byte compatibility alone is deliberately separate from account admission.
    """
    if (not isinstance(payload, dict) or set(payload) != _BYTE_FIELDS
            or payload.get('version') != ACCOUNT_SOURCE_VERSION):
        raise ValueError('Original account byte envelope has an unsupported shape')
    return {name: _bytes(payload, name) for name in ('request', 'response')}


def _request_address(payload):
    """Negative affinity only; malformed account envelopes cannot prove exclusion."""
    if not isinstance(payload, dict):
        return None, False
    if payload.get('version') == ACCOUNT_SOURCE_VERSION or 'request_base64' in payload:
        try:
            request = parse_json(_bytes(payload, 'request'), max_nodes=MAX_NODES)
        except (ValueError, TypeError):
            return None, True
        if not isinstance(request, dict) or request.get('method') != 'getAccountInfo':
            return None, payload.get('version') == ACCOUNT_SOURCE_VERSION
        params = request.get('params')
        if not isinstance(params, list) or not params or not _valid_account(params[0]):
            return None, True
        return params[0], False
    if payload.get('method') == 'getAccountInfo':
        address = payload.get('address')
        return (address, False) if _valid_account(address) else (None, True)
    return None, False


def wallet_identity_dependencies(raw_sources, *, wallet):
    """Select negative links to freeze before a required identity body is lost.

    Role affinity can retain an UNKNOWN dependency, never establish PASS. A
    provably different account's metadata is disjoint from this identity check.
    """
    dependencies = set()
    for index, source in enumerate(raw_sources):
        if not isinstance(source, dict) or not _hash(source.get('hash')):
            continue
        if (index >= MAX_RECORDS or source.get('kind') == 'wallet-identity-affinity'
                or source.get('kind') in ('wallet-account-info', 'wallet-account-source')
                and source.get('payload') is None):
            dependencies.add(source['hash'])
            continue
        if source.get('kind') in ('wallet-account-info', 'wallet-account-source'):
            address, _ambiguous = _request_address(source.get('payload'))
            if address is None or address == wallet:
                dependencies.add(source['hash'])
                continue
        nodes, seen, inspected = [source.get('payload')], set(), 0
        while nodes:
            payload = nodes.pop()
            if not isinstance(payload, (dict, list)) or id(payload) in seen:
                continue
            seen.add(id(payload))
            inspected += 1
            if inspected > MAX_NODES:
                dependencies.add(source['hash'])
                break
            if isinstance(payload, dict):
                address, ambiguous = _request_address(payload)
                if address == wallet or ambiguous:
                    dependencies.add(source['hash'])
                    break
                nodes.extend(value for value in payload.values() if isinstance(value, (dict, list)))
            else:
                nodes.extend(value for value in payload if isinstance(value, (dict, list)))
    return sorted(dependencies)


def _check(known, reason, evidence=(), *, dependencies=(), **details):
    hashes = sorted({value for value in evidence if _hash(value)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'scope': SCOPE,
            'reason': reason, 'evidence': hashes,
            'dependencies': sorted({value for value in dependencies if _hash(value)}), **details}


def _account(payload, wallet):
    """Admit only the existing Store wrapper or exact paired RPC bytes."""
    if not isinstance(payload, dict):
        raise ValueError('Current account body is unavailable')
    if payload.get('version') == ACCOUNT_SOURCE_VERSION:
        original = account_source_bytes(payload)
        request = parse_json(original['request'], max_nodes=MAX_NODES)
        response = parse_json(original['response'], max_nodes=MAX_NODES)
        if (not isinstance(request, dict) or set(request) != {'jsonrpc', 'id', 'method', 'params'}
                or request.get('jsonrpc') != '2.0' or request.get('method') != 'getAccountInfo'
                or not (type(request.get('id')) is int or isinstance(request.get('id'), str))
                or not isinstance(response, dict) or set(response) != {'jsonrpc', 'id', 'result'}
                or response.get('jsonrpc') != '2.0' or type(response.get('id')) is not type(request['id'])
                or response.get('id') != request['id']):
            raise ValueError('Account request/response method, ID or outcome is incompatible')
        params = request.get('params')
        if (not isinstance(params, list) or len(params) != 2 or params[0] != wallet
                or not isinstance(params[1], dict)
                or set(params[1]) - {'encoding', 'commitment', 'minContextSlot'}
                or params[1].get('commitment') != 'finalized'
                or params[1].get('encoding') not in ('base64', 'jsonParsed')
                or 'minContextSlot' in params[1] and
                (type(params[1]['minContextSlot']) is not int or params[1]['minContextSlot'] < 0)):
            raise ValueError('Account request must bind the exact wallet and finalized commitment')
        result, minimum = response['result'], params[1].get('minContextSlot', 0)
        paths = ['request.params', 'response.result.context.slot', 'response.result.value']
    else:
        if (set(payload) - {'method', 'address', 'commitment', 'observed_at', 'result'}
                or payload.get('method') != 'getAccountInfo' or payload.get('address') != wallet
                or payload.get('commitment') != 'finalized'):
            raise ValueError('Account wrapper must retain the exact wallet and finalized commitment')
        result, minimum = payload.get('result'), 0
        paths = ['address', 'commitment', 'result.context.slot', 'result.value']
    context = result.get('context') if isinstance(result, dict) else None
    slot = context.get('slot') if isinstance(context, dict) else None
    value = result.get('value') if isinstance(result, dict) else None
    if (type(slot) is not int or slot < minimum or not isinstance(value, dict)
            or value.get('owner') != SYSTEM_ID or value.get('executable') is not False
            or type(value.get('lamports')) is not int or not 0 <= value['lamports'] <= 2**64 - 1
            or not isinstance(value.get('data'), (dict, list, str))):
        raise ValueError('Finalized current account must be present, system-owned and nonexecutable')
    return {'slot': slot, 'owner': value['owner'], 'executable': False, 'raw_paths': paths}


def _economic(record, wallet):
    """Derive supported economic operations with the existing spot decoder."""
    try:
        events = decode_supported_swaps([record], wallet)['events']
        return sorted((event['kind'], event.get('mint'), event.get('quantity_raw'))
                      for event in events if event.get('kind') in ('buy', 'sell'))
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        return None


def _signer(record, wallet, expected):
    raw, signature, digest = record.get('raw'), record.get('signature'), record.get('evidence_hash')
    if isinstance(raw, dict) and 'result' in raw:
        raw = raw['result']
    try:
        if not _hash(digest) or not isinstance(raw, dict):
            raise ValueError('Native economic body or checksum reference is missing')
        transaction, meta = raw.get('transaction'), raw.get('meta')
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        if (not isinstance(signatures, list) or not signatures or signatures[0] != signature
                or any(not _signature(item) for item in signatures)
                or not isinstance(meta, dict) or 'err' not in meta or meta['err'] is not None):
            raise ValueError('Native successful transaction/signature identity is unresolved')
        context = resolve_account_keys(raw)
        if wallet not in context['signers'] or len(context['signers']) != len(signatures):
            raise ValueError('The economic wallet is not a consistent outer transaction signer')
        if _economic(record, wallet) != expected:
            raise ValueError('Linked version does not support the same selected economic operation')
        return _check(True, 'Selected economic wallet is an outer signer in this native version.',
                      [digest], dependencies=[digest], raw_paths=context['raw_paths'])
    except (ValueError, TypeError, KeyError, CompiledInstructionError, RecursionError) as exc:
        return _check(False, str(exc), [digest], dependencies=[digest])


def derive_wallet_identity(records, *, all_records, raw_sources, wallet, identity_dependencies=()):
    """Recompute current identity separately from historical wallet completeness."""
    records, all_records, raw_sources = list(records), list(all_records), list(raw_sources)
    supplied = list(identity_dependencies)
    invalid_dependencies = any(not _hash(value) for value in supplied)
    deps = set(value for value in supplied if _hash(value))
    deps.update(wallet_identity_dependencies(raw_sources, wallet=wallet))
    account_rows = defaultdict(list)
    for source in raw_sources[:MAX_RECORDS]:
        if isinstance(source, dict) and source.get('hash') in deps:
            account_rows[source['hash']].append(source.get('payload'))
    current_versions = []
    for digest in sorted(deps):
        payloads = [value for value in account_rows[digest] if value is not None]
        try:
            if not payloads:
                raise ValueError('Still-linked current account source is unavailable')
            facts = []
            for payload in payloads:
                encoded = canonical_bytes(payload, max_nodes=MAX_NODES, string_keys=True)
                if hashlib.sha256(encoded).hexdigest() != digest:
                    raise ValueError('Current account source checksum disagrees')
                facts.append(_account(payload, wallet))
            current_versions.append(_check(True, 'Archived finalized current system-account identity is supported.',
                [digest], dependencies=[digest], observations=facts))
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            current_versions.append(_check(False, str(exc), [digest], dependencies=[digest]))
    budget = max(len(records), len(all_records), len(raw_sources)) > MAX_RECORDS
    current = _check(not budget and not invalid_dependencies and _valid_account(wallet)
        and bool(current_versions) and all(row['state'] == 'PASS' for row in current_versions),
        'All linked current-account observations must independently support identity; this says nothing about earlier owners.',
        deps, dependencies=deps, versions=current_versions)
    linked = defaultdict(list)
    for row in all_records[:MAX_RECORDS] + records[:MAX_RECORDS]:
        if isinstance(row, dict) and isinstance(row.get('signature'), str):
            if row not in linked[row['signature']]:
                linked[row['signature']].append(row)
    selected, unavailable = {}, False
    for row in records[:MAX_RECORDS]:
        if not isinstance(row, dict) or not isinstance(row.get('raw'), dict):
            unavailable = True
            continue
        economics = _economic(row, wallet)
        if economics is None:
            unavailable = True
        elif economics:
            signature = row.get('signature')
            if not isinstance(signature, str) or signature in selected and selected[signature] != economics:
                unavailable = True
            else:
                selected[signature] = economics
    transactions, hashes = {}, set()
    for signature, expected in sorted(selected.items()):
        versions = [_signer(row, wallet, expected) for row in linked[signature]]
        evidence = [h for row in versions for h in row['evidence']]
        hashes.update(h for row in versions for h in row['dependencies'])
        transactions[signature] = _check(bool(versions) and all(row['state'] == 'PASS' for row in versions),
            'Every selected and linked native version must support the same wallet economic signer.',
            evidence, dependencies=evidence, versions=versions)
    signer = _check(not budget and not unavailable and bool(transactions)
        and all(row['state'] == 'PASS' for row in transactions.values()),
        'Selected supported economic signer only; payer identity and current owner alone are insufficient.',
        hashes, dependencies=hashes)
    dependencies = sorted(deps | hashes)
    return _check(current['state'] == signer['state'] == 'PASS',
        'Current account and every linked selected economic signer must both be supported; historical population remains unproved.',
        dependencies, dependencies=dependencies, version=VERSION, current_account=current,
        economic_signer=signer, transactions=transactions, historical_population_state='UNKNOWN',
        provider_requests=0, credential_lookups=0)
