"""Bounded, offline archive inputs for the normal report/FIFO path.

Imported bytes establish integrity, not network authenticity or historical scope.
The finite-world witness is an executable synthetic development contract only.
It can never authenticate a real wallet or create native collector ancestry.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
import zlib

from .accounting import analyze, canonical, decimal, raw_quantity, utc
from .config import validate_address
from .decoder import decode_transactions
from .investigation import decode_supported_swaps, _keys, WSOL
from .position_evidence import _balance, _quantity_point
from .source_consistency import assess_source_consistency, source_archive_receipts
from .chronology_evidence import assess_chronology, assess_interval_membership
from .storage import EvidenceError, now
from .json_boundary import canonical_bytes as _bounded_canonical, parse_json

VERSION = 'archived-wallet-input-v1'
METHOD = 'archive-ledger-v6'
_CURRENT_IMPORT = object()
MAX_UPLOAD = 20 * 1024 * 1024
MAX_ENTRY = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_LINKS = 10_000
MAX_QUANTITY_STEPS = 100_000
HASH = re.compile(r'[a-f0-9]{64}')


def canonical_bytes(value):
    return _bounded_canonical(value)


def _json(raw):
    return parse_json(raw)


def validate_manifest(value):
    if not isinstance(value, dict) or value.get('version') != VERSION:
        raise ValueError(f'Expected {VERSION} manifest')
    if set(value) - {'version', 'address', 'window', 'dataset', 'transactions', 'evidence', 'world_hash', 'classification_hashes', 'valuation_hash'}:
        raise ValueError('Unsupported manifest fields; normalized events and completion flags are not accepted')
    validate_address(value.get('address'))
    if value.get('dataset') not in ('real', 'synthetic'):
        raise ValueError('Dataset must be explicitly real or synthetic')
    window = value.get('window')
    if not isinstance(window, dict) or set(window) != {'start', 'end'} or utc(window['end']) <= utc(window['start']):
        raise ValueError('An exact positive UTC window is required')
    rows = value.get('transactions')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LINKS:
        raise ValueError('Provide 1–10,000 selected transaction links')
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'signature', 'hash'} or not isinstance(row.get('signature'), str)
            or not 1 <= len(row['signature']) <= 128 or not isinstance(row.get('hash'), str) or not HASH.fullmatch(row['hash'])):
            raise ValueError('Each transaction needs a bounded signature and primary SHA-256 hash')
    refs = value.get('evidence', [])
    if not isinstance(refs, list) or len(refs) > MAX_LINKS:
        raise ValueError('Evidence link limit exceeded')
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get('hash'), str) or not HASH.fullmatch(ref['hash']) or not isinstance(ref.get('kind'), str):
            raise ValueError('Evidence links need explicit kinds and SHA-256 hashes')
        if ref['kind'] in ('query-affinity', 'archive-native-dependencies'):
            raise ValueError('Frozen dependency roles are derived internally, not accepted as archive evidence declarations')
        if ref['kind'] in ('transaction', 'getTransaction') and (not isinstance(ref.get('signature'), str) or not 1 <= len(ref['signature']) <= 128):
            raise ValueError('Alternative transaction links require an explicit bounded signature')
    for key in ('world_hash', 'valuation_hash'):
        if key in value and (not isinstance(value[key], str) or not HASH.fullmatch(value[key])):
            raise ValueError('Witness links must be SHA-256 hashes')
    hashes = value.get('classification_hashes', [])
    if not isinstance(hashes, list) or len(hashes) > MAX_LINKS or any(not isinstance(h, str) or not HASH.fullmatch(h) for h in hashes):
        raise ValueError('Classification witness limit/shape invalid')
    return value


def pack_bytes(bundle):
    manifest = validate_manifest(bundle['manifest'])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        for digest, payload in bundle['payloads'].items():
            raw = canonical_bytes(payload)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Payload hash disagrees with archive name')
            archive.writestr(f'archives/{digest}.json.gz', gzip.compress(raw, mtime=0))
    return buffer.getvalue()


def import_archive(store, content, *, reserve_bytes=0):
    """Validate everything before mutation; preserve the exact uploaded gzip bytes."""
    if len(content) > MAX_UPLOAD:
        raise ValueError('Archive exceeds 20 MiB upload limit')
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > MAX_LINKS * 2 + 1 or len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Duplicate/oversized archive or missing manifest')
        payloads, total = {}, 0
        manifest = None
        for entry in entries:
            if entry.flag_bits & 1 or entry.file_size > MAX_UPLOAD:
                raise ValueError('Encrypted or oversized ZIP entry')
            if entry.filename != 'manifest.json' and not re.fullmatch(r'archives/[a-f0-9]{64}\.json\.gz', entry.filename):
                raise ValueError('Only manifest.json and hash-named archive files are accepted')
            raw = archive.read(entry)
            if entry.filename == 'manifest.json':
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError('Manifest exceeds 4 MiB')
                manifest = validate_manifest(_json(raw))
                total += len(raw)
                continue
            digest = Path(entry.filename).name.removesuffix('.json.gz')
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(MAX_ENTRY + 1)
            total += len(decoded)
            if len(decoded) > MAX_ENTRY or total > MAX_TOTAL:
                raise ValueError('Expanded archive limit exceeded')
            if hashlib.sha256(decoded).hexdigest() != digest:
                raise ValueError('Archive checksum mismatch')
            payload = _json(decoded)
            if canonical_bytes(payload) != decoded:
                raise ValueError('Archive JSON must use the scanner canonical serialization; retain original provider bytes separately')
            payloads[digest] = (raw, decoded)
        if total > MAX_TOTAL:
            raise ValueError('Expanded archive limit exceeded')
    except (zipfile.BadZipFile, OSError, EOFError, UnicodeError, zlib.error, RuntimeError) as exc:
        raise ValueError(f'Invalid archive: {exc}') from exc
    import shutil
    if shutil.disk_usage(store.path).free < reserve_bytes + len(content) + total:
        raise EvidenceError('Free disk space is below the configured reserve for this archive')
    # Missing links are dependencies, not import errors or silently omitted rows.
    for digest, (compressed, decoded) in payloads.items():
        dest = store.path / 'evidence' / f'{digest}.json.gz'
        if dest.exists():
            store.evidence(digest)
            continue
        fd, temporary = tempfile.mkstemp(prefix='.archive-input-', dir=dest.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(compressed); stream.flush(); os.fsync(stream.fileno())
            with store.lock:
                if not dest.exists():
                    os.replace(temporary, dest)
                else:
                    store.evidence(digest)
            store.put('artifacts', digest, {'hash': digest, 'bytes': len(decoded), 'created_at': now()})
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    digest = store.archive(manifest)
    # Preserve negative native associations observed in the uploaded bytes.
    # Caller role labels cannot make a conflicting source disappear on loss.
    from .wallet_evidence import raw_native_dependencies
    sources = deepcopy(manifest.get('evidence', []))
    sources += [{'kind': 'classification', 'hash': h} for h in manifest.get('classification_hashes', [])]
    sources += [{'kind': 'valuation', 'hash': manifest['valuation_hash']}] if manifest.get('valuation_hash') else []
    sources += [{'kind': 'synthetic-population', 'hash': manifest['world_hash']}] if manifest.get('world_hash') else []
    for source in sources:
        identifier = source['hash']
        try:
            source['payload'] = _json(payloads[identifier][1]) if identifier in payloads else store.evidence(identifier)
        except (EvidenceError, ValueError, OSError):
            source['payload'] = None
    dependencies = raw_native_dependencies(sources, (), {r['signature'] for r in manifest['transactions']})
    from .real_coverage import query_source_dependencies
    query_hashes = query_source_dependencies(sources)
    links = [{'signature': r.get('signature'), 'hash': r['evidence_hash']} for r in dependencies
             if isinstance(r.get('evidence_hash'), str) and HASH.fullmatch(r['evidence_hash'])]
    previous = store.get('archive_dependency_inputs', digest, {})
    previous_hash = previous.get('hash') if isinstance(previous, dict) else None
    if previous_hash:
        try:
            previous_inventory = store.evidence(previous_hash)
            links += _dependency_links(previous_inventory, digest)
            if previous_inventory.get('version') == 'archive-native-dependencies-v2':
                query_hashes += previous_inventory['query_source_hashes']
        except (EvidenceError, ValueError, OSError):
            links.append({'signature': None, 'hash': previous_hash})
            query_hashes.append(previous_hash)
    links = list({(r['signature'], r['hash']): r for r in links}.values())
    inputs = {'version': 'archive-native-dependencies-v2', 'manifest_hash': digest,
              'links': sorted(links, key=lambda r: (r['signature'] or '', r['hash'])),
              'query_source_hashes': sorted(set(query_hashes))}
    _dependency_links(inputs, digest)
    dependency_hash = store.archive(inputs)
    store.put('archive_dependency_inputs', digest, {'hash': dependency_hash})
    return digest


def _dependency_links(value, manifest_hash):
    from .source_consistency import SOURCE_HASH_LIMIT
    version = value.get('version') if isinstance(value, dict) else None
    fields = {'version', 'manifest_hash', 'links'} | ({'query_source_hashes'} if version == 'archive-native-dependencies-v2' else set())
    if (not isinstance(value, dict) or set(value) != fields
        or version not in ('archive-native-dependencies-v1', 'archive-native-dependencies-v2') or value.get('manifest_hash') != manifest_hash
        or not isinstance(value.get('links'), list) or len(value['links']) > SOURCE_HASH_LIMIT):
        raise ValueError('Frozen native dependency inventory disagrees with this manifest')
    if version == 'archive-native-dependencies-v2':
        hashes = value['query_source_hashes']
        if (not isinstance(hashes, list) or len(hashes) > SOURCE_HASH_LIMIT
            or any(not isinstance(h, str) or not HASH.fullmatch(h) for h in hashes)
            or len(set(hashes)) != len(hashes)):
            raise ValueError('Frozen query dependency inventory is malformed or exceeds its bound')
    for row in value['links']:
        if (not isinstance(row, dict) or set(row) != {'signature', 'hash'}
            or not isinstance(row.get('hash'), str) or not HASH.fullmatch(row['hash'])
            or row.get('signature') is not None and (not isinstance(row['signature'], str) or not 1 <= len(row['signature']) <= 128)):
            raise ValueError('Frozen native dependency link is malformed')
    return deepcopy(value['links'])


def load_archive(store, digest, *, dependency_input_hash=_CURRENT_IMPORT):
    manifest = validate_manifest(store.evidence(digest))
    links = deepcopy(manifest['transactions'])
    links += [{'signature': ref.get('signature'), 'hash': ref['hash']} for ref in manifest.get('evidence', [])
              if ref['kind'] in ('transaction', 'getTransaction')]
    cache, receipts = {}, []
    def read(identifier, role):
        if identifier not in cache:
            try:
                cache[identifier] = store.evidence(identifier)
                state, reason = 'PASS', 'Exact checksum-checked archived bytes; network authenticity is separate.'
            except (EvidenceError, ValueError, OSError):
                cache[identifier] = None
                state, reason = 'UNKNOWN', 'Still-linked source is unavailable or unreadable.'
            receipts.append({'hash': identifier, 'state': state, 'reason': reason, 'role': role})
        return cache[identifier]
    world = read(manifest['world_hash'], 'synthetic-population') if manifest.get('world_hash') else None
    if isinstance(world, dict) and isinstance(world.get('transactions'), list) and len(world['transactions']) <= MAX_LINKS:
        for item in world['transactions']:
            if isinstance(item, dict) and isinstance(item.get('hash'), str) and HASH.fullmatch(item['hash']):
                read(item['hash'], 'population-inventory')
    dependency_input, query_affinities = None, []
    if dependency_input_hash is _CURRENT_IMPORT:
        index = store.get('archive_dependency_inputs', digest, {})
        dependency_input_hash = index.get('hash') if isinstance(index, dict) else None
    if dependency_input_hash:
        dependency_input = read(dependency_input_hash, 'archive-native-dependencies')
        try:
            links += _dependency_links(dependency_input, digest)
            if dependency_input.get('version') == 'archive-native-dependencies-v2':
                query_affinities += dependency_input['query_source_hashes']
                for query_hash in query_affinities:
                    read(query_hash, 'query-affinity')
            else:
                # The old inventory froze native associations only.  Keep its
                # absent query-role proof separate from independent fees.
                query_affinities.append(dependency_input_hash)
        except (ValueError, TypeError):
            links.append({'signature': None, 'hash': dependency_input_hash})
            query_affinities.append(dependency_input_hash)
    else:
        # A legacy parent has no frozen role-affinity proof. Never substitute
        # a later mutable import index for that parent's original references.
        links.append({'signature': None, 'hash': None})
        query_affinities.append(digest)
    from .indexed_input import IndexedResolver, describe_pages
    indexed_resolver = IndexedResolver(read, address=manifest['address'])
    indexed_sources = {}
    all_records, seen = [], set()
    for link in links:
        key = (link.get('signature'), link['hash'])
        if key in seen:
            continue
        seen.add(key)
        payload = read(link['hash'], 'transaction')
        record = archived_record(payload, key[0], key[1], read,
                                 address=manifest['address'], resolver=indexed_resolver,
                                 source_cache=indexed_sources)
        all_records.append(record)
    selected = {(r['signature'], r['hash']) for r in manifest['transactions']}
    records = [r for r in all_records if (r['signature'], r['evidence_hash']) in selected]
    # A signature is decoded once; its full linked alternatives remain in consistency.
    unique = {}
    for record in records:
        unique.setdefault(record['signature'], record)
    records = list(unique.values())
    clock_sources, pages, blocks, indexed = [], [], [], []
    for ref in manifest.get('evidence', []):
        payload = read(ref['hash'], ref['kind'])
        if ref['kind'] in ('signature-page', 'block-order', 'indexed-page'):
            params = payload.get('params') if isinstance(payload, dict) else None
            minimum = params.get('minContextSlot') if isinstance(params, dict) else None
            # This only validates the raw clock role/request. A page's own
            # context does not establish a historical population or snapshot.
            typed = source_archive_receipts({'links': [{'kind': ref['kind'], 'hash': ref['hash']}]},
                {ref['hash']: payload}, {ref['hash']: 'readable' if payload is not None else 'unavailable'},
                snapshot_slot=minimum, wallet=manifest['address'])['receipts'][0]
            clock_sources.append(typed)
            target = indexed if ref['kind'] == 'indexed-page' else pages if ref['kind'] == 'signature-page' else blocks
            target.append({'hash': ref['hash'], 'payload': payload})
    classifications = [read(h, 'classification') for h in manifest.get('classification_hashes', [])]
    valuation = read(manifest['valuation_hash'], 'valuation') if manifest.get('valuation_hash') else None
    consistency = assess_source_consistency(all_records, wallet=manifest['address'],
                                            indexed_receipts=indexed)
    chronology = assess_chronology(all_records, page_receipts=pages, block_receipts=blocks,
                                  indexed_receipts=indexed)
    return {'manifest': manifest, 'records': records, 'all_records': all_records, 'world': world,
            'classifications': classifications, 'valuation': valuation, 'receipts': receipts,
            'consistency': consistency, 'chronology': chronology, 'clock_sources': clock_sources,
            'indexed_pages': describe_pages(indexed, manifest['address'], manifest['window']) if indexed else None,
            'clock_payloads': {row['hash']: cache[row['hash']] for row in clock_sources},
            'raw_sources': [{'hash': ref['hash'], 'kind': ref['kind'], 'signature': ref.get('signature'),
                            'payload': cache.get(ref['hash'])}
                            for ref in manifest.get('evidence', [])]
                + [{'hash': h, 'kind': 'classification', 'payload': cache.get(h)}
                   for h in manifest.get('classification_hashes', [])]
                + ([{'hash': manifest['valuation_hash'], 'kind': 'valuation',
                     'payload': valuation}] if manifest.get('valuation_hash') else [])
                + ([{'hash': dependency_input_hash, 'kind': 'archive-native-dependencies',
                     'payload': dependency_input}] if dependency_input_hash else [])
                + [{'hash': h, 'kind': 'query-affinity', 'payload': cache.get(h)} for h in query_affinities],
            'dependency_input_hash': dependency_input_hash,
            'dependency_input': dependency_input, 'input_hash': digest}


def archived_record(payload, signature, digest, read, *, address=None, resolver=None, source_cache=None):
    """Resolve native bytes or frozen indexed pointers through the same loader.

    The pointer is a source reference, never a trusted decoded event or order
    declaration. Resolution receipts expose the original page and raw paths.
    """
    from .indexed_input import (IndexedResolver, RECORD_VERSION, PAGE_VERSION, NATIVE_VERSION,
                                source_records, validate_page_envelope)
    record = {'signature': signature, 'evidence_hash': digest, 'raw': None}
    if isinstance(payload, dict) and payload.get('version') == RECORD_VERSION:
        receipt = (resolver or IndexedResolver(read, address=address)).resolve(payload)
        raw = receipt.get('raw')
        record['indexed_source'] = {k: v for k, v in receipt.items() if k != 'raw'}
        source_hash = payload.get('source_hash')
        if isinstance(source_hash, str) and HASH.fullmatch(source_hash):
            record['indexed_source_hash'] = source_hash
        if receipt.get('state') != 'PASS' or payload.get('signature') != signature:
            return record
    elif isinstance(payload, dict) and payload.get('version') in (PAGE_VERSION, NATIVE_VERSION):
        source_cache = {} if source_cache is None else source_cache
        if digest not in source_cache:
            receipt = source_records(payload, address=address)
            by_signature = defaultdict(list)
            candidates = receipt['records']
            if payload.get('version') == PAGE_VERSION:
                candidates = validate_page_envelope(payload, address)['records']
            for ordinal, item in enumerate(candidates):
                tx = item.get('transaction') if isinstance(item, dict) else None
                signatures = tx.get('signatures') if isinstance(tx, dict) else None
                identity = signatures[0] if isinstance(signatures, list) and signatures else None
                if not isinstance(identity, str) or not identity:
                    continue
                # An unrelated malformed sibling cannot erase a native body.
                # Reuse the pointer resolver to check request/response identity
                # and exact bytes; chronology still rejects unsupported scope.
                pointer = {'version': RECORD_VERSION, 'source_hash': digest, 'ordinal': ordinal,
                           'signature': identity, 'native_hash': hashlib.sha256(canonical_bytes(item)).hexdigest()}
                resolved = (resolver or IndexedResolver(read, address=address)).resolve(pointer)
                if resolved['state'] == 'PASS':
                    by_signature[identity].append(resolved['raw'])
            source_cache[digest] = (receipt, by_signature)
        receipt, by_signature = source_cache[digest]
        matches = by_signature.get(signature, [])
        raw = deepcopy(matches[0]) if len(matches) == 1 else None
        record['indexed_source_hash'] = digest
        record['indexed_source'] = {'state': receipt['state'], 'source_hash': digest,
                                    'reason': '; '.join(receipt['gaps']), 'raw_paths': ['response']}
    else:
        raw = payload.get('result') if isinstance(payload, dict) and 'result' in payload else payload
    record['raw'] = raw if _safe_decoder_container(raw) else None
    return record


def _safe_decoder_container(raw):
    """Reject runtime-unsafe container shapes while retaining the source dependency."""
    if not isinstance(raw, dict):
        return False
    try:
        meta, tx = raw['meta'], raw['transaction']
        message = tx['message']
        if not isinstance(meta, dict) or not isinstance(message, dict) or not isinstance(tx['signatures'], list):
            return False
        if any(type(raw.get(k)) not in (int, type(None)) for k in ('slot', 'blockTime')):
            return False
        if type(raw.get('blockTime')) is int:
            utc(raw['blockTime'])
        keys = message.get('accountKeys')
        if not isinstance(keys, list) or any(not isinstance(k, str) and not (isinstance(k, dict) and isinstance(k.get('pubkey'), str)) for k in keys):
            return False
        loaded = meta.get('loadedAddresses') or {}
        if not isinstance(loaded, dict) or any(not isinstance(loaded.get(k, []), list) or any(not isinstance(v, str) for v in loaded.get(k, [])) for k in ('writable','readonly')):
            return False
        for name in ('preBalances', 'postBalances'):
            if not isinstance(meta.get(name), list) or any(type(v) is not int or v < 0 for v in meta[name]):
                return False
        for name in ('preTokenBalances', 'postTokenBalances'):
            if not isinstance(meta.get(name), list) or any(not isinstance(v, dict) for v in meta[name]):
                return False
        # Instruction failures are handled by both shared decoders after retaining
        # independent native fee facts; they must not erase this raw record.
        return True
    except (ValueError, TypeError, KeyError):
        return False


def decode_archive(loaded):
    from .wallet_evidence import with_derived_order
    records, address = with_derived_order(loaded['records'], loaded['chronology']), loaded['manifest']['address']
    swaps = decode_supported_swaps(records, address)
    supported = {e['signature'] for e in swaps['events'] if e['kind'] in ('buy', 'sell')}
    decoded = decode_transactions([r for r in records if r['signature'] not in supported], address)
    events = decoded['events'] + [e for e in swaps['events'] if e['signature'] in supported]
    return events, swaps


def _world_scope(loaded):
    """Check enumerated development initial conditions and every quantity transition."""
    manifest, world = loaded['manifest'], loaded['world']
    points, boundaries, gaps = [], {}, []
    if manifest['dataset'] != 'synthetic' or not isinstance(world, dict) or world.get('kind') != 'synthetic-world-v1':
        return False, points, boundaries, ['No accepted real historical-owner/population witness is present.']
    try:
        if world['address'] != manifest['address'] or utc(world['end']) != utc(manifest['window']['end']):
            raise ValueError('World wallet/window disagrees')
        beginning = utc(world['start'])
        if beginning > utc(manifest['window']['start']):
            raise ValueError('World does not span the reporting interval')
        inventory = world['transactions']
        expected = {(r['signature'], r['hash']) for r in inventory}
        selected = {(r['signature'], r['hash']) for r in manifest['transactions']}
        if len(inventory) != len(expected) or expected != selected:
            raise ValueError('Independent finite-world inventory and selected transaction population disagree')
        accounts = world['accounts']
        identities = {a['address']: a for a in accounts}
        if not accounts or len(identities) != len(accounts) or len(accounts) * len(loaded['all_records']) > MAX_QUANTITY_STEPS:
            raise ValueError('World account inventory is empty, duplicated or exceeds the quantity inspection budget')
        quantities = {a['address']: raw_quantity(a['opening_quantity_raw']) for a in accounts}
        if any(a['owner'] != manifest['address'] or a['mint'] != WSOL and quantities[a['address']] != 0 for a in accounts):
            raise ValueError('Development nonsettlement inventory must begin at zero under the explicit owner')
        native = raw_quantity(world['opening_native_lamports'])
        boundaries['initial'] = {'quantities': dict(quantities), 'native_lamports': native}
        ordered = sorted(loaded['records'], key=lambda r: (r['raw']['blockTime'], r['raw']['slot']))
        previous_time = None
        for record in ordered:
            raw, digest = record['raw'], record['evidence_hash']
            when = utc(raw['blockTime'])
            if when < beginning or when >= utc(world['end']) or previous_time == when:
                raise ValueError('World chronology needs supported distinct transaction times in the declared interval')
            previous_time = when
            if when >= utc(manifest['window']['start']) and 'opening' not in boundaries:
                boundaries['opening'] = {'quantities': dict(quantities), 'native_lamports': native}
            meta = raw['meta']; keys = _keys(raw['transaction']['message'], meta)
            wi = keys.index(manifest['address'])
            if type(meta['preBalances'][wi]) is not int or meta['preBalances'][wi] != native or type(meta['postBalances'][wi]) is not int:
                raise ValueError('Native absolute balances do not reconcile across the finite world')
            for row in meta['preTokenBalances'] + meta['postTokenBalances']:
                if row.get('owner') == manifest['address'] and keys[row['accountIndex']] not in identities:
                    raise ValueError('An owned token account is omitted from the world inventory')
            for account, identity in identities.items():
                if account not in keys:
                    continue
                before = _balance(raw, keys, account, 'preTokenBalances')
                after = _balance(raw, keys, account, 'postTokenBalances')
                if any(b['owner'] != identity['owner'] or b['mint'] != identity['mint'] or b['decimals'] != identity['decimals'] for b in (before, after)):
                    raise ValueError('Event-time ownership/mint/decimals disagrees with the world lifecycle')
                if before['quantity'] != quantities[account]:
                    raise ValueError('Absolute token balances have a missing or conflicting quantity transition')
                if identity['mint'] != WSOL:
                    point = _quantity_point(raw, manifest['address'], account)
                    points.append({'account': account, 'hash': digest, 'signature': record['signature'],
                                   'timestamp': raw['blockTime'], **point})
                quantities[account] = after['quantity']
            native = meta['postBalances'][wi]
            if native < 0:
                raise ValueError('Negative native balance')
        boundaries.setdefault('opening', {'quantities': dict(quantities), 'native_lamports': native})
        boundaries['closing'] = {'quantities': dict(quantities), 'native_lamports': native}
        rows = loaded['consistency']['transactions'].values()
        if (any(r['identity']['state'] != 'PASS' or any(a['state'] != 'PASS' for a in r['accounts'].values()) for r in rows)
            or loaded['chronology']['state'] != 'PASS'):
            raise ValueError('Linked identity/quantity alternatives or chronology remain unresolved')
        selected_hashes = {r['evidence_hash'] for r in loaded['records']}
        for record in loaded['all_records']:
            if record['evidence_hash'] in selected_hashes:
                continue
            raw = record['raw']
            keys = _keys(raw['transaction']['message'], raw['meta'])
            for account, identity in identities.items():
                if account in keys and identity['mint'] != WSOL:
                    _quantity_point(raw, manifest['address'], account)
        if any(r['state'] != 'PASS' and r['role'] not in ('classification', 'valuation') for r in loaded['receipts']):
            raise ValueError('Required linked population/ownership/transaction source is unavailable')
        if any(ref['kind'] not in ('transaction', 'getTransaction') for ref in manifest.get('evidence', [])):
            raise ValueError('Additional evidence roles need a coverage reconciliation contract')
        return True, points, boundaries, gaps
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return False, points, boundaries, [str(exc)]


def _quantity_episodes(points, *, supported, world_hash):
    """Physical mint-aggregate strict-zero timing, separately from prices/cost basis."""
    quantities, active, completed = defaultdict(int), {}, []
    for point in points:
        if point['kind'] not in ('buy', 'sell'):
            continue
        mint, delta, at = point['mint'], point['post'] - point['pre'], utc(point['timestamp'])
        before = quantities[mint]
        quantities[mint] += delta
        if before == 0 and delta > 0:
            active[mint] = {'mint': mint, 'start': at.isoformat(), 'end': None,
                            'evidence': [world_hash] if world_hash else [], 'scope': 'Synthetic finite-world physical inventory only; economic-sale/basis/classification gates are separate'}
        episode = active.get(mint)
        if episode:
            episode['evidence'] = sorted(set(episode['evidence'] + [point['hash']]))
            if quantities[mint] == 0:
                episode['end'] = at.isoformat()
                hours = Decimal(int((at - utc(episode['start'])).total_seconds())) / Decimal(3600)
                episode['hold_hours'] = {'value': canonical(hours) if supported else None, 'status': 'known' if supported else 'unknown',
                                         'unit': 'hours', 'population': episode['scope'], 'evidence': episode['evidence']}
                completed.append(episode); active.pop(mint)
    return completed


def _valuation_inputs(loaded, boundaries, scope):
    value, world = loaded['valuation'], loaded['world']
    if loaded['manifest']['dataset'] != 'synthetic':
        return {}, 'No accepted genuine boundary inventory, historical mark and valued-flow adapter is present.'
    if not scope or not isinstance(value, dict) or value.get('kind') != 'synthetic-valuation-v1':
        return {}, 'Boundary inventories, marks and valued external flows are not supported.'
    try:
        if value['address'] != loaded['manifest']['address'] or value['window'] != loaded['manifest']['window']:
            raise ValueError('Valuation identity/window mismatch')
        # This narrow development contract admits only reviewed trades/fees, no external flows.
        if value['external_flows'] != []:
            raise ValueError('External flow reconciliation requires a supported valuation adapter')
        events, _ = decode_archive(loaded)
        if any(e['kind'] not in ('buy', 'sell', 'fee', 'internal_transfer') for e in events):
            raise ValueError('Unknown/external economic movements cannot become zero flows')
        equity = {}
        identities = {a['address']: a for a in world['accounts']}
        for boundary, at in (('opening', value['window']['start']), ('closing', value['window']['end'])):
            snapshot = value[boundary]
            if snapshot['at'] != at or raw_quantity(snapshot['native_lamports']) != boundaries[boundary]['native_lamports']:
                raise ValueError('Exact boundary native inventory disagrees')
            amounts = defaultdict(int)
            for account, quantity in boundaries[boundary]['quantities'].items():
                amounts[identities[account]['mint']] += quantity
            rows = {r['mint']: r for r in snapshot['assets']}
            if len(rows) != len(snapshot['assets']) or set(rows) != set(amounts):
                raise ValueError('Boundary token inventory/marks omitted or duplicated')
            total = Decimal(snapshot['native_lamports']) / Decimal(10**9)
            for mint, quantity in amounts.items():
                row = rows[mint]
                ds = {a['decimals'] for a in world['accounts'] if a['mint'] == mint}
                if len(ds) != 1 or type(row['decimals']) is not int or row['decimals'] != next(iter(ds)) or raw_quantity(row['quantity_raw']) != quantity:
                    raise ValueError('Boundary token absolute quantities/decimals disagree')
                price = decimal(row['mark_sol_per_token'])
                if mint == WSOL and price != 1:
                    raise ValueError('Wrapped SOL representation must conserve native value')
                total += Decimal(quantity) / Decimal(10**row['decimals']) * price
            equity[boundary] = canonical(total)
            decimal(equity[boundary])  # Respect the existing FIFO monetary input bounds.
        return {'opening_equity': equity['opening'], 'closing_equity': equity['closing'],
                'external_deposits': '0', 'external_withdrawals': '0'}, None
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return {}, str(exc)


def analyze_archive(loaded, events):
    """Use the shared FIFO and explicit, interval-specific raw evidence gates."""
    from .wallet_evidence import derive_wallet_evidence
    from .metric_evidence import compose_metric_decisions, apply_metric_decisions
    manifest = loaded['manifest']
    scope, points, boundaries, gaps = _world_scope(loaded) if manifest['dataset'] == 'synthetic' else (False, [], {}, [])
    events = deepcopy(events)
    adapter = derive_wallet_evidence(loaded['records'], all_records=loaded['all_records'],
        wallet=manifest['address'], window=manifest['window'], events=events,
        source_consistency=loaded['consistency'], chronology=loaded['chronology'],
        source_receipts=loaded['receipts'], raw_sources=loaded.get('raw_sources', []))
    if manifest['dataset'] == 'real':
        # Genuine inputs use the common raw adapter, not the finite-world
        # witness.  Query termination is separate from wallet membership;
        # neither an uploaded source decision nor a terminal page activates it.
        scope = (adapter['components']['historical_population']['state'] == 'PASS'
                 and adapter['intervals']['report_period']['state'] == 'PASS')
        gaps = [adapter['components']['historical_population']['reason']]
        if adapter['query_coverage']['intervals']['report_period']['state'] != 'PASS':
            gaps += adapter['query_coverage']['intervals']['report_period']['gaps']
        gaps = sorted(set(gaps))
    native_rows = loaded['consistency']['transactions'].values()
    financial_scope = scope and all(all(r['native'].get(k, {}).get('state') == 'PASS'
        for k in ('wallet_network_fees_sol', 'native_wallet_delta_sol')) for r in native_rows)
    selected_hashes = {r['evidence_hash'] for r in loaded['records']}
    primary_trades = {e['signature']: e for e in events if e['kind'] in ('buy','sell')}
    for record in loaded['all_records']:
        if record['evidence_hash'] in selected_hashes or record['signature'] not in primary_trades:
            continue
        alternative = decode_supported_swaps([record], manifest['address'])
        trades = [e for e in alternative['events'] if e['kind'] in ('buy','sell')]
        expected = primary_trades[record['signature']]
        if len(trades) != 1 or any(trades[0].get(k) != expected.get(k) for k in ('kind','mint','quantity_raw','decimals','amount_sol','fee_sol','paid_by_wallet','venue')):
            financial_scope = False
    classes = defaultdict(set)
    if manifest['dataset'] == 'synthetic':
        for witness in loaded['classifications']:
            if (isinstance(witness, dict) and witness.get('kind') == 'synthetic-classification-v1'
                and witness.get('classification') in ('meme', 'settlement') and witness.get('address') == manifest['address']
                and isinstance(witness.get('mint'), str)):
                classes[witness.get('mint')].add(witness['classification'])
        for event in events:
            values = classes[event.get('mint')]
            if len(values) == 1:
                event['classification'] = next(iter(values))
                event['evidence'] = sorted(set(event.get('evidence', []) + manifest.get('classification_hashes', [])))
    intervals = {}
    start, end = utc(manifest['window']['start']), utc(manifest['window']['end'])
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)), ('verification_90d', end - timedelta(days=90))):
        interval_known = (scope and utc(loaded['world']['start']) <= begin) if manifest['dataset'] == 'synthetic' else adapter['intervals'][name]['state'] == 'PASS'
        intervals[name] = {'start': begin.isoformat(), 'end': end.isoformat(), 'status': 'complete' if interval_known else 'unknown',
                           'evidence': ([manifest['world_hash']] if scope else []) if manifest['dataset'] == 'synthetic' else adapter['intervals'][name]['evidence'],
                           'reason': None if interval_known else ('; '.join(gaps) or 'Finite-world evidence does not span this independent interval.')
                               if manifest['dataset'] == 'synthetic' else adapter['intervals'][name]['reason']}
    with localcontext() as ctx:
        ctx.prec = 192
        economic, economic_gap = _valuation_inputs(loaded, boundaries, financial_scope)
        # Acquisition/valuation loss is applied by per-metric dependencies.
        # Complete physical history must not become incomplete solely because
        # an unrelated monetary prerequisite is absent.
        result = analyze(events, start.isoformat(), end.isoformat(),
            history_complete=financial_scope if manifest['dataset'] == 'synthetic' else scope,
            interval_coverage=intervals, **economic)
    if intervals['verification_90d']['status'] != 'complete':
        result['metrics']['completed_positions_90d'].update(value=None, status='unknown', reason=intervals['verification_90d']['reason'])
        result['metric_coverage']['completed_positions_90d']['metric_status'] = 'unknown'
    # Fee observations require only the linked raw payer/fee facts for selected records.
    def within(value):
        try:
            return start <= utc(value) < end
        except (ValueError, TypeError, OverflowError):
            return False
    fee_rows = [e for e in events if e['kind'] == 'fee' and e.get('paid_by_wallet') is True and within(e.get('timestamp'))]
    relevant = [r for r in loaded['records'] if isinstance(r['raw'], dict) and within(r['raw'].get('blockTime'))]
    native_groups = loaded['consistency']['transactions']
    membership = {}
    zero_exclusions = []
    unresolved_clocks = [clock for clock in loaded['clock_sources'] if clock['state'] != 'PASS']
    for record in loaded['records']:
        signature = record['signature']
        receipt = assess_interval_membership(loaded['chronology'], signature, start, end)
        slots = set(loaded['chronology']['placements'].get(signature, {}).get('possible_slots', []))
        for clock in unresolved_clocks:
            clock_scope = clock['scope']
            unrelated = clock_scope.get('slot') is not None and clock_scope['slot'] not in slots
            if clock_scope.get('signatures') is not None and signature not in clock_scope['signatures']:
                # Supported role scope may prove unrelatedness even when a
                # different page entry's timestamp is malformed.
                payload = loaded['clock_payloads'].get(clock['hash'])
                if clock.get('role') == 'indexed-page' or isinstance(payload, dict) and payload.get('version') == 'indexed-page-source-v1':
                    from .indexed_input import validate_page_envelope
                    page = validate_page_envelope(payload, manifest['address'])
                    page_slots = {row.get('slot') for row in page['records']
                                  if isinstance(row, dict) and type(row.get('slot')) is int}
                    unrelated = (not page['unassignable_records'] and not page['record_gaps']
                                 and not bool(page_slots & slots))
                else:
                    page_slots = {row.get('slot') for row in payload.get('result', [])
                                  if isinstance(row, dict) and type(row.get('slot')) is int} if payload else set()
                    unrelated = not bool(page_slots & slots)
            if not unrelated:
                receipt.update(state='UNKNOWN', member=None,
                               reason='A still-linked clock source is missing, malformed or unsupported; its relevance is unresolved.')
                receipt['evidence'] = sorted(set(receipt['evidence'] + clock['evidence']))
        group = native_groups.get(signature, {})
        raw = record['raw']
        if receipt['state'] != 'PASS' and group.get('native', {}).get('wallet_network_fees_sol', {}).get('state') == 'PASS' and isinstance(raw, dict):
            keys = _keys(raw['transaction']['message'], raw['meta'])
            if raw['meta'].get('fee') == 0 or keys and keys[0] != manifest['address']:
                # A independently proved zero wallet-paid fee contributes
                # zero under every possible interval placement.
                zero_exclusions.append(signature)
        membership[signature] = receipt
    # The raw adapter also inspects transaction-shaped linked sources whose
    # caller role label is unsupported. Their contradictions cannot disappear
    # when the ordinary typed fee projection is assembled.
    adapter_membership = adapter['intervals']['report_period'].get('selected_record_membership', {})
    for signature, receipt in adapter_membership.items():
        current = membership.get(signature)
        if current is None:
            continue
        current['evidence'] = sorted(set(current['evidence'] + receipt.get('evidence', [])))
        if receipt.get('state') != 'PASS' or receipt.get('member') != current.get('member'):
            current.update(state='UNKNOWN', member=None,
                reason='A linked raw source leaves reporting-window membership unresolved or conflicting.')
        fee = adapter['transactions'].get(signature, {}).get('network_fee', {})
        if current['state'] != 'PASS' and fee.get('check', {}).get('state') == 'PASS' and fee.get('lamports') == '0':
            zero_exclusions.append(signature)
    zero_exclusions = sorted(set(zero_exclusions))
    window_known = all(row['state'] == 'PASS' or signature in zero_exclusions for signature, row in membership.items())
    projected = [signature for signature, row in membership.items()
                 if not (row['state'] == 'PASS' and row['member'] is False)]
    native_projection = [adapter['transactions'].get(signature, {}).get('network_fee', {}).get('check', {})
                         for signature in projected]
    identity_projection = [adapter['transactions'].get(signature, {}).get('checks', {}).get('identity', {})
                           for signature in projected]
    # Empty projection means every selected record is independently proven
    # outside this window; it is not an unproved empty history declaration.
    projection_known = bool(membership) and all(row.get('state') == 'PASS' for row in native_projection)
    fee_ok = window_known and all(
        native_groups.get(r['signature'], {}).get('native', {}).get('wallet_network_fees_sol', {}).get('state') == 'PASS' for r in relevant)
    fee_ok = fee_ok and projection_known and all(e.get('amount_sol') is not None for e in fee_rows)
    fees = canonical(sum((decimal(e['amount_sol']) for e in fee_rows if e.get('amount_sol') is not None), Decimal(0)))
    result['metrics']['observed_network_fees_sol'] = {'value': fees if fee_ok else None, 'status': 'known' if fee_ok else 'unknown',
        'unit': 'SOL', 'population': 'Selected in-window records with an independently supported wallet fee payer; not all interval costs',
        'reason': None if fee_ok else 'A linked selected fee/payer or reporting-window membership observation remains unavailable or conflicts.',
        'evidence': sorted({h for e in fee_rows for h in e.get('evidence', [])} |
                           {h for receipt in membership.values() for h in receipt['evidence']})}
    result['metrics']['economic_pnl_sol']['reason'] = economic_gap
    for metric in result['metrics'].values():
        if metric['status'] == 'unknown' and not scope and metric['population'] != result['metrics']['observed_network_fees_sol']['population']:
            metric['reason'] = '; '.join(gaps) + ' ' + (metric.get('reason') or '')
        if metric['status'] == 'known' and metric is not result['metrics']['observed_network_fees_sol']:
            metric['evidence'] = sorted(set(metric.get('evidence', []) + ([manifest['world_hash']] if scope and manifest.get('world_hash') else [])
                + ([manifest['valuation_hash']] if metric is result['metrics']['economic_pnl_sol'] and economic else [])))
    components = deepcopy(adapter['components'])
    interval_checks = deepcopy(adapter['intervals'])
    if manifest['dataset'] == 'synthetic':
        # These are outputs of the existing finite-world validator, never
        # imported completion declarations and never accepted for real data.
        def development_check(known, reason, evidence):
            return {'state': 'PASS' if known else 'UNKNOWN', 'scope': 'synthetic finite world; development only',
                    'reason': reason, 'evidence': sorted(set(evidence))}
        world_evidence = [manifest['world_hash']] if manifest.get('world_hash') else []
        for name in ('historical_population', 'event_ownership', 'quantity_continuity', 'positions'):
            components[name] = development_check(scope, '; '.join(gaps) or 'Validated finite-world quantity population.', world_evidence)
        components['chronology'] = development_check(scope and loaded['chronology']['state'] == 'PASS',
            'Shared raw chronology must support the finite-world ordering.', world_evidence)
        classified = bool(classes) and all(len(classes[e.get('mint')]) == 1
            for e in events if e['kind'] in ('buy', 'sell', 'transfer_in', 'transfer_out'))
        components['classification'] = development_check(classified, 'Each traded asset needs one available development classification.',
            manifest.get('classification_hashes', []))
        for name in ('acquisition_basis', 'economic_costs'):
            components[name] = development_check(financial_scope, 'Supported origins and cost roles require the financial source scope.', world_evidence)
        valuation_evidence = [manifest['valuation_hash']] if manifest.get('valuation_hash') else []
        for name in ('boundary_inventory', 'historical_marks', 'valued_external_flows'):
            components[name] = development_check(bool(economic), economic_gap or 'Validated finite-world boundary valuation and flows.', valuation_evidence)
        interval_checks = {name: development_check(row['status'] == 'complete',
            row['reason'] or 'Finite world independently spans this interval.', row['evidence'])
            for name, row in intervals.items()}
    fee_evidence = result['metrics']['observed_network_fees_sol']['evidence']
    for name, checks in (('native_fee', native_projection), ('selected_record_identity', identity_projection)):
        components[name] = {'state': 'PASS' if bool(membership) and all(row.get('state') == 'PASS' for row in checks) else 'UNKNOWN',
            'evidence': sorted(set(fee_evidence + [h for row in checks for h in row.get('evidence', [])])),
            'scope': 'Selected records that may contribute to this reporting window; proved exclusions remain excluded',
            'reason': 'Native fee/identity prerequisites are projected using supported interval membership.'}
    components['fee_window'] = {'state': 'PASS' if window_known else 'UNKNOWN', 'evidence': sorted(set(fee_evidence)),
        'scope': 'selected in-window wallet-paid native fees',
        'reason': None if window_known else 'Shared linked-clock checks leave selected reporting-window membership unresolved.'}
    requirements = compose_metric_decisions(components, interval_checks, metric_observations=result['metrics'])
    result = apply_metric_decisions(result, requirements)
    return result, events, {'version': METHOD, 'dataset': manifest['dataset'],
        'scope': 'Synthetic enumerated finite world; development only' if manifest['dataset'] == 'synthetic' else 'Archived native records with independently derived query and historical-membership scopes',
        'real_acceptance': 'NOT_APPLICABLE_SYNTHETIC' if manifest['dataset'] == 'synthetic' else 'BLOCKED',
        'population_state': 'PASS' if financial_scope else 'UNKNOWN', 'quantity_population_state': 'PASS' if scope else 'UNKNOWN', 'gaps': gaps,
        'source_receipts': loaded['receipts'], 'source_consistency': loaded['consistency'], 'chronology': loaded['chronology'],
        'fee_interval_membership': membership, 'proved_zero_fee_exclusions': zero_exclusions,
        'account_quantity_points': points, 'quantity_episodes': _quantity_episodes(points, supported=scope, world_hash=manifest.get('world_hash')),
        'boundary_inventory': boundaries, 'metric_requirements': requirements,
        'wallet_evidence': adapter, 'component_checks': components, 'interval_checks': interval_checks,
        'query_coverage': adapter['query_coverage'], 'query_accounting': adapter['query_accounting'],
        'input_hash': loaded['input_hash'], 'provider_requests': 0, 'credential_lookups': 0}


def collected_archive(loaded):
    manifest = loaded['manifest']
    refs = [{'kind': 'transaction', 'signature': r['signature'], 'hash': r['hash']} for r in manifest['transactions']]
    return {'transactions': loaded['records'], 'evidence': refs + deepcopy(manifest.get('evidence', [])),
            'checkpoint': {}, 'snapshot': {}, 'coverage': {'source': VERSION, 'complete': False, 'history_complete': False}}
