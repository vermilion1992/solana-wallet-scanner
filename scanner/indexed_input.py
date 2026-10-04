"""Bounded offline ingestion of exact indexed-history response bytes.

This is an input adapter for ``archive_input``, not a second report engine.
Imported request/response bytes establish local integrity, never provider
authenticity, complete historical population, or trusted collector ancestry.
Native records are rederived from their frozen byte source on every rebuild.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import io
import re
import zipfile

from .accounting import utc
from .archive_input import (VERSION as ARCHIVE_VERSION, MAX_UPLOAD, MAX_ENTRY,
                            MAX_TOTAL, MAX_LINKS, pack_bytes)
from .config import validate_address
from .json_boundary import bounded_value, parse_json, canonical_bytes as _shared_canonical_bytes

VERSION = 'indexed-wallet-input-v1'
PAGE_VERSION = 'indexed-page-source-v1'
NATIVE_VERSION = 'indexed-native-source-v1'
RECORD_VERSION = 'indexed-transaction-v1'
MANIFEST_VERSION = 'indexed-input-manifest-v1'
MAX_PAGES = 256
MAX_PAGE_RECORDS = 1000
MAX_RAW = 24 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 1_000_000
HASH = re.compile(r'[a-f0-9]{64}')
_BYTES_FIELDS = {'version', 'request_hash', 'response_hash', 'request_base64', 'response_base64'}
_POINTER_FIELDS = {'version', 'source_hash', 'ordinal', 'signature', 'native_hash'}


def _bounded_json_value(value):
    """Bound JSON interpretation separately from compressed/raw byte limits."""
    bounded_value(value, max_depth=MAX_JSON_DEPTH, max_nodes=MAX_JSON_NODES, string_keys=True)


def _json(raw):
    return parse_json(raw, max_depth=MAX_JSON_DEPTH, max_nodes=MAX_JSON_NODES)


def canonical_bytes(value):
    """Reject recursive/cyclic caller objects before canonical serialization."""
    return _shared_canonical_bytes(value, max_depth=MAX_JSON_DEPTH, max_nodes=MAX_JSON_NODES, string_keys=True)


def _hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _signature(value):
    return isinstance(value, str) and 1 <= len(value) <= 128


def _rpc_id(value):
    return type(value) is int and abs(value) <= 2**63-1 or isinstance(value, str) and 1 <= len(value) <= 128


def _cursor(value):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r'[0-9]+:[0-9]+', value):
        return None
    slot, index = value.split(':')
    if len(slot) > 20 or len(index) > 20:
        return None
    point = int(slot), int(index)
    return point if all(part <= 2**64-1 for part in point) else None


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_manifest(value):
    """Only byte links and report scope are accepted; no imported PASS flags."""
    _bounded_json_value(value)
    if (not isinstance(value, dict) or value.get('version') != VERSION
        or set(value) - {'version', 'address', 'window', 'pages', 'transactions'}):
        raise ValueError(f'Expected strict {VERSION} manifest without completion declarations')
    validate_address(value.get('address'))
    window = value.get('window')
    if (not isinstance(window, dict) or set(window) != {'start', 'end'}
        or utc(window['end']) <= utc(window['start'])):
        raise ValueError('An exact positive UTC window is required')
    pages = value.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError('Indexed input requires 1–256 linked pages')
    transactions = value.get('transactions', [])
    if not isinstance(transactions, list) or len(transactions) > MAX_LINKS:
        raise ValueError('Native alternative link limit exceeded')
    for group, fields in ((pages, {'request_hash', 'response_hash'}),
                          (transactions, {'signature', 'request_hash', 'response_hash'})):
        for item in group:
            if (not isinstance(item, dict) or set(item) != fields
                or not _hash(item.get('request_hash')) or not _hash(item.get('response_hash'))
                or 'signature' in fields and not _signature(item.get('signature'))):
                raise ValueError('Sources require exact byte hashes and bounded native alternative signatures')
    return deepcopy(value)


def pack_indexed_bytes(manifest, raw_inputs):
    """Pack exact raw inputs; missing linked inputs remain deliberately linked."""
    manifest = validate_manifest(manifest)
    if not isinstance(raw_inputs, dict):
        raise ValueError('Raw inputs must be a hash/bytes mapping')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        for digest, raw in sorted(raw_inputs.items()):
            if not _hash(digest) or not isinstance(raw, bytes) or len(raw) > MAX_RAW or _digest(raw) != digest:
                raise ValueError('Raw input hash/size disagrees with its name')
            archive.writestr(f'raw/{digest}.json', raw)
    content = stream.getvalue()
    if len(content) > MAX_UPLOAD:
        raise ValueError('Indexed archive exceeds 20 MiB upload limit')
    return content


def _source(version, row, raw_inputs):
    return {'version': version, 'request_hash': row['request_hash'], 'response_hash': row['response_hash'],
            'request_base64': base64.b64encode(raw_inputs[row['request_hash']]).decode('ascii')
                if row['request_hash'] in raw_inputs else None,
            'response_base64': base64.b64encode(raw_inputs[row['response_hash']]).decode('ascii')
                if row['response_hash'] in raw_inputs else None}


def _exact_bytes(payload, name):
    digest, encoded = payload.get(f'{name}_hash'), payload.get(f'{name}_base64')
    if not _hash(digest) or not isinstance(encoded, str) or len(encoded) > ((MAX_RAW + 2) // 3) * 4:
        raise ValueError(f'Linked {name} bytes are missing or exceed the source bound')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f'Invalid {name} byte encoding') from exc
    if len(raw) > MAX_RAW or _digest(raw) != digest or base64.b64encode(raw).decode('ascii') != encoded:
        raise ValueError(f'Linked {name} byte checksum/encoding disagrees')
    return raw


def source_bytes(payload):
    """Return exact preserved bytes after independently checking both hashes."""
    if (not isinstance(payload, dict) or set(payload) != _BYTES_FIELDS
        or payload.get('version') not in (PAGE_VERSION, NATIVE_VERSION)):
        raise ValueError('Malformed indexed source byte envelope')
    return {name: _exact_bytes(payload, name) for name in ('request', 'response')}


def manifest_bytes(payload):
    """Validate and recover the original uploaded manifest byte-for-byte."""
    if (not isinstance(payload, dict) or set(payload) != {'version', 'sha256', 'bytes_base64'}
        or payload.get('version') != MANIFEST_VERSION or not _hash(payload.get('sha256'))
        or not isinstance(payload.get('bytes_base64'), str) or len(payload['bytes_base64']) > 6 * 1024 * 1024):
        raise ValueError('Malformed frozen indexed manifest')
    try:
        raw = base64.b64decode(payload['bytes_base64'], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Malformed frozen indexed manifest byte encoding') from exc
    if len(raw) > 4 * 1024 * 1024 or _digest(raw) != payload['sha256']:
        raise ValueError('Frozen indexed manifest checksum disagrees')
    validate_manifest(_json(raw))
    return raw


def _request(payload, address):
    raw = source_bytes(payload)
    return _request_values(payload, address, _json(raw['request']), _json(raw['response']))


def _request_values(payload, address, request, response):
    """Validate values parsed from already checksum-verified original bytes.

    This private helper neither replaces nor mutates the parsed response. Public
    entry points still verify both original byte hashes before calling it.
    """
    if (not isinstance(request, dict) or set(request) != {'jsonrpc', 'id', 'method', 'params'}
        or request.get('jsonrpc') != '2.0' or not isinstance(request.get('params'), list)
        or not isinstance(response, dict) or response.get('jsonrpc') != '2.0'
        or not _rpc_id(request.get('id')) or type(response.get('id')) is not type(request['id'])
        or response.get('id') != request.get('id') or 'error' in response or 'result' not in response):
        raise ValueError('Request/response RPC shape, identity or outcome is incompatible')
    params = request['params']
    if payload['version'] == NATIVE_VERSION:
        if (request.get('method') != 'getTransaction' or len(params) != 2 or not _signature(params[0])
            or not isinstance(params[1], dict) or set(params[1]) - {'encoding', 'commitment', 'maxSupportedTransactionVersion'}
            or params[1].get('encoding') not in ('json', 'jsonParsed') or params[1].get('commitment') != 'finalized'
            or type(params[1].get('maxSupportedTransactionVersion')) is not int
            or not 0 <= params[1]['maxSupportedTransactionVersion'] <= 1):
            raise ValueError('Native transaction request is outside the reviewed read-only contract')
        return request, response, None
    if request.get('method') != 'getTransactionsForAddress' or len(params) != 2:
        raise ValueError('Indexed source must be getTransactionsForAddress')
    validate_address(params[0])
    if address is not None and params[0] != address:
        raise ValueError('Indexed request address disagrees with the report wallet')
    options = params[1]
    if (not isinstance(options, dict)
        or set(options) - {'transactionDetails', 'limit', 'sortOrder', 'commitment', 'maxSupportedTransactionVersion', 'filters', 'paginationToken', 'encoding'}
        or options.get('transactionDetails') != 'full' or options.get('commitment') != 'finalized'
        or type(options.get('limit')) is not int or not 1 <= options['limit'] <= MAX_PAGE_RECORDS
        or options.get('sortOrder') not in ('asc', 'desc')
        or type(options.get('maxSupportedTransactionVersion')) is not int
        or not 0 <= options['maxSupportedTransactionVersion'] <= 1
        or 'paginationToken' in options and _cursor(options['paginationToken']) is None):
        raise ValueError('Indexed request options are outside the reviewed source contract')
    encoding = options.get('encoding', 'json')
    if encoding not in ('json', 'jsonParsed'):
        raise ValueError('Indexed full transaction encoding is unsupported; only json and jsonParsed have reviewed native schemas')
    filters = options.get('filters')
    if (not isinstance(filters, dict) or set(filters) - {'status', 'tokenAccounts', 'blockTime'}
        or filters.get('status') not in ('any', 'succeeded', 'failed')
        or filters.get('tokenAccounts') not in ('none', 'balanceChanged', 'all')):
        raise ValueError('Indexed status/token-account filter contract is unsupported')
    block_time = filters.get('blockTime')
    if block_time is not None and (not isinstance(block_time, dict) or set(block_time) != {'gte', 'lt'}
        or any(type(block_time[k]) is not int or block_time[k] < 0 for k in ('gte', 'lt'))
        or block_time['gte'] >= block_time['lt']):
        raise ValueError('Indexed block-time bounds are malformed')
    scope = {'address': params[0], 'status': filters['status'], 'token_accounts': filters['tokenAccounts'],
             'block_time': deepcopy(block_time), 'sort_order': options['sortOrder'], 'limit': options['limit'],
             'max_version': options['maxSupportedTransactionVersion'], 'commitment': options['commitment'],
             'encoding': encoding}
    return request, response, scope


def validate_page_envelope(payload, address=None):
    """Describe facts from bytes, keeping malformed entries and paging gaps.

    ``state`` concerns the indexed page schema only. Even PASS cannot prove a
    complete wallet history, historical ownership or a provider entitlement.
    """
    result = {'state': 'UNKNOWN', 'reason': None, 'request': None, 'response': None,
              'records': [], 'signatures': [], 'cursor_in': None, 'cursor_out': None,
              'request_scope': None, 'unassignable_records': [], 'record_gaps': [], 'record_hashes': [], 'positions': []}
    try:
        if not isinstance(payload, dict) or payload.get('version') != PAGE_VERSION:
            raise ValueError('Expected indexed page source')
        # Retain bounded record leads even when request/cursor metadata is
        # malformed. Their pointers then remain rejecting dependencies rather
        # than disappearing from the alternative-source comparison.
        preserved = source_bytes(payload)
        response_lead = _json(preserved['response'])
        page_lead = response_lead.get('result') if isinstance(response_lead, dict) else None
        data_lead = page_lead.get('data') if isinstance(page_lead, dict) else None
        if isinstance(data_lead, list) and len(data_lead) <= MAX_PAGE_RECORDS:
            result['records'] = data_lead
            result['record_hashes'] = [_digest(canonical_bytes(raw)) for raw in data_lead]
            for index, raw in enumerate(data_lead):
                signature = _record_signature(raw)
                if signature is None:
                    result['unassignable_records'].append(index)
                else:
                    result['signatures'].append(signature)
        request, response, scope = _request_values(payload, address, _json(preserved['request']), response_lead)
        result.update(request=request, response=response, request_scope=scope,
                      cursor_in=request['params'][1].get('paginationToken'))
        page = response['result']
        if (not isinstance(page, dict) or set(page) != {'data', 'paginationToken'}
            or not isinstance(page.get('data'), list) or len(page['data']) > scope['limit']
            or page.get('paginationToken') is not None and _cursor(page['paginationToken']) is None):
            raise ValueError('Indexed page data/cursor shape is malformed')
        result.update(records=page['data'], cursor_out=page['paginationToken'], signatures=[], unassignable_records=[],
                      record_hashes=result['record_hashes'])
        seen, positions, previous = set(), set(), None
        incoming, outgoing = _cursor(result['cursor_in']), _cursor(result['cursor_out'])
        direction = 1 if scope['sort_order'] == 'asc' else -1
        if outgoing is not None and (not page['data'] or incoming is not None and direction * ((outgoing > incoming) - (outgoing < incoming)) <= 0):
            result['record_gaps'].append({'ordinal': None, 'signature': None, 'reason': 'Nonterminal cursor does not advance or belongs to an empty page'})
        for index, raw in enumerate(page['data']):
            signature = _record_signature(raw)
            if signature is None:
                result['unassignable_records'].append(index)
                continue
            result['signatures'].append(signature)
            if signature in seen:
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Duplicate signature in one indexed page'})
            seen.add(signature)
            if (not isinstance(raw.get('meta'), dict) or 'err' not in raw['meta']
                or type(raw.get('slot')) is not int or raw['slot'] < 0
                or type(raw.get('transactionIndex')) is not int or raw['transactionIndex'] < 0
                or type(raw.get('blockTime')) is not int or raw['blockTime'] < 0):
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native execution/placement metadata is incomplete'})
                continue
            point = raw['slot'], raw['transactionIndex']
            if any(value > 2**64-1 for value in point):
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native slot/index exceeds the reviewed bound'})
            if point in positions or previous is not None and direction * ((point > previous) - (point < previous)) <= 0:
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native slot/index repeats or disagrees with requested row ordering'})
            if incoming is not None and direction * ((point > incoming) - (point < incoming)) <= 0:
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native placement does not follow the incoming cursor'})
            positions.add(point)
            previous = point
            result['positions'].append({'signature': signature, 'slot': point[0], 'index': point[1], 'ordinal': index})
            bounds = scope['block_time']
            if bounds is not None and not bounds['gte'] <= raw['blockTime'] < bounds['lt']:
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native time is outside requested half-open bounds'})
            if scope['status'] == 'failed' and raw['meta']['err'] is None or scope['status'] == 'succeeded' and raw['meta']['err'] is not None:
                result['record_gaps'].append({'ordinal': index, 'signature': signature, 'reason': 'Native execution outcome disagrees with requested status filter'})
        if result['unassignable_records'] or result['record_gaps']:
            raise ValueError('Indexed page contains unassignable, duplicate or incomplete native entries')
        result.update(state='PASS', reason='Exact request/response bytes have supported indexed page shape; coverage and native semantics remain separate.')
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        result['reason'] = str(exc)
    return result


def source_records(payload, signature=None, address=None):
    """Derive native associations regardless of a caller's source role label.

    Accepted rows require the supported source schema. Bounded signature leads
    remain visible on rejection so freezing negative dependencies cannot make
    an unreadable/malformed alternative disappear.
    """
    result = {'state': 'UNKNOWN', 'records': [], 'signatures': [], 'gaps': []}
    try:
        if not isinstance(payload, dict):
            raise ValueError('Indexed source is unavailable')
        if payload.get('version') == PAGE_VERSION:
            page = validate_page_envelope(payload, address)
            result['signatures'] = sorted(set(page['signatures']))
            if page['state'] != 'PASS':
                raise ValueError(page['reason'])
            records = page['records']
        elif payload.get('version') == NATIVE_VERSION:
            preserved = source_bytes(payload)
            response_lead = _json(preserved['response'])
            raw_lead = response_lead.get('result') if isinstance(response_lead, dict) else None
            request_lead = _json(preserved['request'])
            params_lead = request_lead.get('params') if isinstance(request_lead, dict) else None
            leads = [_record_signature(raw_lead)]
            if isinstance(params_lead, list) and params_lead and _signature(params_lead[0]):
                leads.append(params_lead[0])
            result['signatures'] = sorted({lead for lead in leads if lead is not None})
            request, response, _ = _request(payload, address)
            raw = response['result']
            lead = _record_signature(raw)
            if lead != request['params'][0]:
                raise ValueError('Native source request and raw signature disagree')
            records = [raw]
        else:
            raise ValueError('Unsupported indexed source version')
        result.update(state='PASS', records=[deepcopy(raw) for raw in records
            if signature is None or _record_signature(raw) == signature])
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        result['gaps'].append(str(exc))
    return result


def _record_signature(raw):
    transaction = raw.get('transaction') if isinstance(raw, dict) else None
    signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
    return signatures[0] if isinstance(signatures, list) and signatures and _signature(signatures[0]) else None


class IndexedResolver:
    """One offline-load snapshot; parse each frozen page once, never globally.

    Construct a fresh resolver for every import/load/rebuild. Cached native
    bodies are private and every returned raw record is a separate copy.
    """
    def __init__(self, read, *, address=None):
        self._read, self._address, self._sources = read, address, {}

    def _source(self, digest):
        if digest not in self._sources:
            try:
                source = self._read(digest, 'indexed-native-source')
                if source is None or _digest(canonical_bytes(source)) != digest:
                    raise ValueError('Frozen indexed byte source is missing or checksum-mismatched')
                source = deepcopy(source)
                request, response, _ = _request(source, self._address)
                page = validate_page_envelope(source, self._address) if source['version'] == PAGE_VERSION else None
                self._sources[digest] = (source['version'], request, response, page)
            except (ValueError, TypeError, KeyError, UnicodeError, OSError, OverflowError) as exc:
                self._sources[digest] = str(exc)
        result = self._sources[digest]
        if isinstance(result, str):
            raise ValueError(result)
        return result

    def resolve(self, payload):
        return _resolve_record(payload, self._source)


def resolve_record(payload, read, *, address=None):
    return IndexedResolver(read, address=address).resolve(payload)


def _resolve_record(payload, source_reader):
    """Rederive one native record from its immutable exact byte source.

    The reader returns checksum-checked archived canonical evidence. Checking it
    here as well makes direct callers unable to substitute another page.
    The receipt never injects indexed transactionIndex as canonical block order.
    """
    receipt = {'state': 'UNKNOWN', 'raw': None, 'source_hash': None, 'reason': None,
               'raw_paths': [], 'page_summary': None}
    try:
        if (not isinstance(payload, dict) or set(payload) != _POINTER_FIELDS
            or payload.get('version') != RECORD_VERSION or not _hash(payload.get('source_hash'))
            or not _hash(payload.get('native_hash')) or not _signature(payload.get('signature'))
            or type(payload.get('ordinal')) is not int or not 0 <= payload['ordinal'] < MAX_PAGE_RECORDS):
            raise ValueError('Malformed indexed native pointer; trusted event/position declarations are not accepted')
        receipt['source_hash'] = payload['source_hash']
        version, request, response, page = source_reader(payload['source_hash'])
        if version == PAGE_VERSION:
            receipt['page_summary'] = {key: page[key] for key in ('state', 'reason', 'cursor_in', 'cursor_out', 'request_scope')}
            receipt['page_summary'].update(record_count=len(page['records']),
                unassignable_record_count=len(page['unassignable_records']), record_gap_count=len(page['record_gaps']))
            records = page['records']
            if payload['ordinal'] >= len(records):
                raise ValueError('Indexed native pointer ordinal is outside the frozen page')
            raw = records[payload['ordinal']]
            path = f'result.data.{payload["ordinal"]}'
        elif version == NATIVE_VERSION:
            if payload['ordinal'] != 0 or request['params'][0] != payload['signature']:
                raise ValueError('Native alternative request/signature pointer disagrees')
            raw = response['result']
            path = 'result'
        else:
            raise ValueError('Unsupported indexed byte source version')
        if _record_signature(raw) != payload['signature'] or _digest(canonical_bytes(raw)) != payload['native_hash']:
            raise ValueError('Frozen record identity/content disagrees with its pointer')
        receipt.update(state='PASS', raw=deepcopy(raw), reason='Native record rederived from exact frozen provider response bytes.', raw_paths=[path])
    except (ValueError, TypeError, KeyError, UnicodeError, OSError, OverflowError) as exc:
        receipt['reason'] = str(exc)
    return receipt


def describe_pages(sources, address, window):
    """Recompute cursor topology without treating a terminal page as coverage."""
    validate_address(address)
    if utc(window['end']) <= utc(window['start']):
        raise ValueError('Invalid report window')
    sources = list(sources)
    if len(sources) > MAX_PAGES:
        return {'state': 'UNKNOWN', 'pages': [], 'gaps': ['Indexed page inspection budget exceeded'], 'historical_population': 'UNKNOWN'}
    rows, gaps, variants = [], [], {}
    for source in sources:
        digest = source.get('hash') if isinstance(source, dict) else None
        digest = digest if isinstance(digest, str) else None
        payload = source.get('payload') if isinstance(source, dict) else None
        page = validate_page_envelope(payload, address)
        try:
            fingerprint = _digest(canonical_bytes(payload))
            verified = _hash(digest) and payload is not None and fingerprint == digest
        except ValueError:
            fingerprint, verified = f'invalid-{type(payload).__name__}', False
        if not verified:
            page.update(state='UNKNOWN', reason='Still-linked indexed source is unavailable or checksum-mismatched')
        row = {'hash': digest, **{key: value for key, value in page.items() if key not in ('request', 'response', 'records')}}
        variants.setdefault(digest, {})[fingerprint] = row
        if page['state'] != 'PASS':
            gaps.append(f'{digest}: {page["reason"]}')
    for digest, alternatives in variants.items():
        ordered = sorted(alternatives.items())
        # Exact duplicate byte bodies are idempotent. A readable body must not
        # hide a missing/substituted declaration of the same linked hash.
        row = deepcopy(next((value for _, value in ordered if value['state'] == 'PASS'), ordered[0][1]))
        if len(ordered) > 1:
            reason = 'Linked indexed source variants disagree or include unavailable contents'
            row.update(state='UNKNOWN', reason=reason, request_scope=None,
                signatures=sorted({signature for _, value in ordered for signature in value['signatures']}),
                source_variants=[{'payload_hash': fingerprint if _hash(fingerprint) else None,
                                  'state': value['state'], 'reason': value['reason']}
                                 for fingerprint, value in ordered])
            gaps.append(f'{digest}: {reason}')
        rows.append(row)
    by_scope = {}
    for row in rows:
        if row['request_scope'] is not None:
            key = canonical_bytes({k: v for k, v in row['request_scope'].items() if k != 'limit'})
            by_scope.setdefault(key, []).append(row)
    for scoped in by_scope.values():
        incoming = {r['cursor_in'] for r in scoped}
        outgoing = {r['cursor_out'] for r in scoped}
        if None not in incoming:
            gaps.append('An indexed cursor chain has no initial request')
        for row in scoped:
            if row['cursor_in'] is not None and row['cursor_in'] not in outgoing:
                gaps.append('A linked continuation has no matching predecessor response')
            if row['cursor_out'] is not None and row['cursor_out'] not in incoming:
                gaps.append('An indexed cursor chain remains nonterminal')
            if row['cursor_out'] is not None and row['cursor_out'] == row['cursor_in']:
                gaps.append('An indexed cursor chain repeats its own cursor')
        for cursor in incoming:
            members = [r for r in scoped if r['cursor_in'] == cursor]
            # Identical native data with a different JSONRPC id is a duplicate
            # observation, but disagreement cannot be resolved by arrival order.
            outputs = {(r['cursor_out'], tuple(r['signatures']), tuple(r['record_hashes'])) for r in members}
            if len(outputs) > 1:
                gaps.append('Alternative indexed pages disagree for the same request cursor')
        reachable, frontier = set(), [None]
        while frontier:
            cursor = frontier.pop()
            for row in scoped:
                if row['cursor_in'] != cursor or row['hash'] in reachable:
                    continue
                reachable.add(row['hash'])
                if row['cursor_out'] is not None:
                    frontier.append(row['cursor_out'])
        if len(reachable) != len(scoped):
            gaps.append('An indexed cursor component is disconnected from its initial request')
        # A rooted cycle with an otherwise terminal sibling is still a gap.
        for start in incoming:
            current, visited = start, set()
            for _ in range(len(scoped) + 1):
                successors = {r['cursor_out'] for r in scoped if r['cursor_in'] == current}
                if len(successors) != 1:
                    break
                successor = next(iter(successors))
                if successor is None:
                    break
                if successor in visited:
                    gaps.append('An indexed cursor chain contains a cycle')
                    break
                visited.add(successor)
                current = successor
    return {'state': 'PASS' if rows and not gaps else 'UNKNOWN',
            'pages': sorted(rows, key=lambda r: r['hash'] or ''), 'gaps': sorted(set(gaps)),
            'historical_population': 'UNKNOWN',
            'coverage_reason': 'Local page shape/cursor topology cannot prove provider historical population, ownership or acquisition coverage.'}


def _read_upload(content):
    if not isinstance(content, bytes) or len(content) > MAX_UPLOAD:
        raise ValueError('Indexed archive exceeds 20 MiB upload limit')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            if len(entries) > MAX_LINKS * 2 + 1 or len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('Duplicate/oversized indexed archive or missing manifest')
            raw_inputs, manifest, manifest_raw, total = {}, None, None, 0
            for entry in entries:
                if entry.flag_bits & 1 or entry.file_size > MAX_RAW:
                    raise ValueError('Encrypted or oversized indexed ZIP entry')
                if entry.filename != 'manifest.json' and not re.fullmatch(r'raw/[a-f0-9]{64}\.json', entry.filename):
                    raise ValueError('Only manifest.json and hash-named raw JSON byte files are accepted')
                raw = archive.read(entry)
                total += len(raw)
                if total > MAX_TOTAL:
                    raise ValueError('Expanded indexed archive limit exceeded')
                if entry.filename == 'manifest.json':
                    if len(raw) > 4 * 1024 * 1024:
                        raise ValueError('Indexed manifest exceeds 4 MiB')
                    manifest = validate_manifest(_json(raw))
                    manifest_raw = raw
                else:
                    digest = entry.filename[4:-5]
                    if _digest(raw) != digest:
                        raise ValueError('Raw indexed input checksum mismatch')
                    raw_inputs[digest] = raw
            links = {r[k] for r in manifest['pages'] + manifest.get('transactions', []) for k in ('request_hash', 'response_hash')}
            if set(raw_inputs) - links:
                raise ValueError('Unlinked raw inputs are not accepted')
            return manifest, raw_inputs, manifest_raw
    except (zipfile.BadZipFile, OSError, EOFError, UnicodeError, RuntimeError) as exc:
        raise ValueError(f'Invalid indexed archive: {exc}') from exc


def archive_version(content):
    """Bounded ZIP manifest dispatch; a printed/path prefix is never trusted."""
    if not isinstance(content, bytes) or len(content) > MAX_UPLOAD:
        raise ValueError('Archive exceeds 20 MiB upload limit')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > MAX_LINKS*2+1 or len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('Duplicate/oversized archive or missing manifest')
            for entry in entries:
                if (entry.flag_bits & 1 or entry.file_size > MAX_RAW
                    or entry.filename != 'manifest.json' and not re.fullmatch(r'(raw/[a-f0-9]{64}\.json|archives/[a-f0-9]{64}\.json\.gz)', entry.filename)):
                    raise ValueError('Unsupported, encrypted or oversized archive entry')
            entry = archive.getinfo('manifest.json')
            if entry.file_size > 4*1024*1024:
                raise ValueError('Manifest exceeds 4 MiB')
            manifest = _json(archive.read(entry))
            if not isinstance(manifest, dict) or not isinstance(manifest.get('version'), str):
                raise ValueError('Archive manifest version is missing')
            return manifest['version']
    except (zipfile.BadZipFile, OSError, EOFError, UnicodeError, RuntimeError) as exc:
        raise ValueError(f'Invalid archive: {exc}') from exc


def convert_indexed_archive(content):
    """Convert to the existing canonical archive format before store mutation."""
    manifest, raw_inputs, manifest_raw = _read_upload(content)
    payloads, links, page_refs, source_refs = {}, [], [], []
    frozen_manifest = {'version': MANIFEST_VERSION, 'sha256': _digest(manifest_raw),
                       'bytes_base64': base64.b64encode(manifest_raw).decode('ascii')}
    manifest_hash = _digest(canonical_bytes(frozen_manifest))
    payloads[manifest_hash] = frozen_manifest
    source_refs.append({'kind': 'indexed-input-manifest', 'hash': manifest_hash})
    for version, sources in ((PAGE_VERSION, manifest['pages']), (NATIVE_VERSION, manifest.get('transactions', []))):
        for row in sources:
            source = _source(version, row, raw_inputs)
            source_hash = _digest(canonical_bytes(source))
            if len(canonical_bytes(source)) > MAX_ENTRY:
                raise ValueError('Indexed source envelope exceeds expanded archive entry limit')
            payloads[source_hash] = source
            ref = {'kind': 'indexed-page' if version == PAGE_VERSION else 'indexed-native-source', 'hash': source_hash}
            (page_refs if version == PAGE_VERSION else source_refs).append(ref)
            if version == PAGE_VERSION:
                page = validate_page_envelope(source, manifest['address'])
                records = page['records']
                signatures = [_record_signature(raw) for raw in records]
            else:
                try:
                    _, response, _ = _request(source, manifest['address'])
                    records, signatures = [response['result']], [row['signature']]
                except (ValueError, TypeError, KeyError, UnicodeError):
                    records, signatures = [None], [row['signature']]
            for ordinal, (raw, signature) in enumerate(zip(records, signatures)):
                if signature is None:
                    continue  # Its ordinal remains explicit in page validation.
                pointer = {'version': RECORD_VERSION, 'source_hash': source_hash, 'ordinal': ordinal,
                           'signature': signature, 'native_hash': _digest(canonical_bytes(raw))}
                digest = _digest(canonical_bytes(pointer))
                payloads[digest] = pointer
                links.append({'signature': signature, 'hash': digest})
                if len(links) > MAX_LINKS:
                    raise ValueError('Indexed native record link budget exceeded')
    if not links:
        raise ValueError('Indexed archive has no identifiable native transaction; no report was created')
    unique = {(row['signature'], row['hash']): row for row in links}
    selected, alternatives = {}, []
    for row in sorted(unique.values(), key=lambda r: (r['signature'], r['hash'])):
        if row['signature'] in selected:
            alternatives.append({'kind': 'transaction', **row})
        else:
            selected[row['signature']] = row
    refs = {(ref['kind'], ref['hash']): ref for ref in page_refs + source_refs}
    ordinary = {'version': ARCHIVE_VERSION, 'address': manifest['address'], 'window': manifest['window'],
                'dataset': 'real', 'transactions': list(selected.values()),
                'evidence': sorted(refs.values(), key=lambda r: (r['kind'], r['hash'])) + alternatives}
    converted = pack_bytes({'manifest': ordinary, 'payloads': payloads})
    if len(converted) > MAX_UPLOAD:
        raise ValueError('Converted indexed archive exceeds 20 MiB upload limit')
    return converted
