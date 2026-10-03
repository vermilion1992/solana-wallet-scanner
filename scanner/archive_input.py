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
from .source_consistency import assess_source_consistency
from .chronology_evidence import assess_chronology
from .storage import EvidenceError, now

VERSION = 'archived-wallet-input-v1'
METHOD = 'archive-ledger-v1'
MAX_UPLOAD = 20 * 1024 * 1024
MAX_ENTRY = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_LINKS = 10_000
MAX_QUANTITY_STEPS = 100_000
HASH = re.compile(r'[a-f0-9]{64}')


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON keys are not accepted')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


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
    return store.archive(manifest)


def load_archive(store, digest):
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
    all_records, seen = [], set()
    for link in links:
        key = (link.get('signature'), link['hash'])
        if key in seen:
            continue
        seen.add(key)
        payload = read(link['hash'], 'transaction')
        raw = payload.get('result') if isinstance(payload, dict) and 'result' in payload else payload
        raw = raw if _safe_decoder_container(raw) else None
        all_records.append({'signature': key[0], 'evidence_hash': key[1], 'raw': raw})
    selected = {(r['signature'], r['hash']) for r in manifest['transactions']}
    records = [r for r in all_records if (r['signature'], r['evidence_hash']) in selected]
    # A signature is decoded once; its full linked alternatives remain in consistency.
    unique = {}
    for record in records:
        unique.setdefault(record['signature'], record)
    records = list(unique.values())
    for ref in manifest.get('evidence', []):
        read(ref['hash'], ref['kind'])
    classifications = [read(h, 'classification') for h in manifest.get('classification_hashes', [])]
    valuation = read(manifest['valuation_hash'], 'valuation') if manifest.get('valuation_hash') else None
    consistency = assess_source_consistency(all_records, wallet=manifest['address'])
    chronology = assess_chronology(all_records)
    return {'manifest': manifest, 'records': records, 'all_records': all_records, 'world': world,
            'classifications': classifications, 'valuation': valuation, 'receipts': receipts,
            'consistency': consistency, 'chronology': chronology, 'input_hash': digest}


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
    records, address = loaded['records'], loaded['manifest']['address']
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
    """Use FIFO with derived development scope; real imports remain uncertified."""
    manifest = loaded['manifest']
    scope, points, boundaries, gaps = _world_scope(loaded)
    events = deepcopy(events)
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
        interval_known = scope and utc(loaded['world']['start']) <= begin
        intervals[name] = {'start': begin.isoformat(), 'end': end.isoformat(), 'status': 'complete' if interval_known else 'unknown',
                           'evidence': [manifest['world_hash']] if scope else [],
                           'reason': None if interval_known else '; '.join(gaps) or 'Finite-world evidence does not span this independent interval.'}
    with localcontext() as ctx:
        ctx.prec = 192
        economic, economic_gap = _valuation_inputs(loaded, boundaries, financial_scope)
        result = analyze(events, start.isoformat(), end.isoformat(), history_complete=financial_scope, interval_coverage=intervals, **economic)
    if intervals['verification_90d']['status'] != 'complete':
        result['metrics']['completed_positions_90d'].update(value=None, status='unknown', reason=intervals['verification_90d']['reason'])
        result['metric_coverage']['completed_positions_90d']['metric_status'] = 'unknown'
    # Fee observations require only the linked raw payer/fee facts for selected records.
    def within(value):
        try:
            return start <= utc(value) < end
        except (ValueError, TypeError, OverflowError):
            return False
    def timestamp_available(value):
        try:
            utc(value)
            return type(value) is int
        except (ValueError, TypeError, OverflowError):
            return False
    fee_rows = [e for e in events if e['kind'] == 'fee' and e.get('paid_by_wallet') is True and within(e.get('timestamp'))]
    relevant = [r for r in loaded['records'] if isinstance(r['raw'], dict) and within(r['raw'].get('blockTime'))]
    native_groups = loaded['consistency']['transactions']
    fee_ok = all(isinstance(r['raw'], dict) and timestamp_available(r['raw'].get('blockTime')) for r in loaded['records']) and all(
        native_groups.get(r['signature'], {}).get('native', {}).get('wallet_network_fees_sol', {}).get('state') == 'PASS' for r in relevant)
    fee_ok = fee_ok and all(e.get('amount_sol') is not None for e in fee_rows)
    fees = canonical(sum((decimal(e['amount_sol']) for e in fee_rows if e.get('amount_sol') is not None), Decimal(0)))
    result['metrics']['observed_network_fees_sol'] = {'value': fees if fee_ok else None, 'status': 'known' if fee_ok else 'unknown',
        'unit': 'SOL', 'population': 'Selected in-window records with an independently supported wallet fee payer; not all interval costs',
        'reason': None if fee_ok else 'A linked selected fee/payer observation remains unavailable or conflicts.',
        'evidence': sorted({h for e in fee_rows for h in e.get('evidence', [])})}
    result['metrics']['economic_pnl_sol']['reason'] = economic_gap
    for metric in result['metrics'].values():
        if metric['status'] == 'unknown' and not scope and metric['population'] != result['metrics']['observed_network_fees_sol']['population']:
            metric['reason'] = '; '.join(gaps) + ' ' + (metric.get('reason') or '')
        if metric['status'] == 'known' and metric is not result['metrics']['observed_network_fees_sol']:
            metric['evidence'] = sorted(set(metric.get('evidence', []) + ([manifest['world_hash']] if scope else [])
                + ([manifest['valuation_hash']] if metric is result['metrics']['economic_pnl_sol'] and economic else [])))
    requirements = {}
    for key, metric in result['metrics'].items():
        required = ['historical_population', 'event_ownership', 'quantity_continuity', 'chronology', 'classification']
        if key in ('profit_sol', 'realised_roi_pct', 'median_roi_pct', 'win_rate_pct', 'largest_contribution_pct', 'positive_weeks'):
            required += ['acquisition_basis', 'economic_costs']
        if key == 'economic_pnl_sol':
            required = ['historical_population', 'boundary_inventory', 'historical_marks', 'valued_external_flows']
        if key == 'observed_network_fees_sol':
            required = ['selected_record_identity', 'native_fee', 'wallet_payer', 'linked_fee_alternatives']
        if key == 'positive_weeks':
            required.append('independent_28_days')
        if key == 'completed_positions_90d':
            required.append('independent_90_days')
        requirements[key] = {'state': 'PASS' if metric['status'] == 'known' else 'UNKNOWN', 'dependencies': required,
                             'scope': 'synthetic finite world' if manifest['dataset'] == 'synthetic' else metric.get('population'),
                             'reason': metric.get('reason'), 'evidence': sorted(set(metric.get('evidence', []) +
                                 ([loaded['input_hash']] if metric['status'] == 'known' else [])))}
    return result, events, {'version': METHOD, 'dataset': manifest['dataset'],
        'scope': 'Synthetic enumerated finite world; development only' if manifest['dataset'] == 'synthetic' else 'Imported selected native records; historical wallet completeness unproved',
        'real_acceptance': 'NOT_APPLICABLE_SYNTHETIC' if manifest['dataset'] == 'synthetic' else 'BLOCKED',
        'population_state': 'PASS' if financial_scope else 'UNKNOWN', 'quantity_population_state': 'PASS' if scope else 'UNKNOWN', 'gaps': gaps,
        'source_receipts': loaded['receipts'], 'source_consistency': loaded['consistency'], 'chronology': loaded['chronology'],
        'account_quantity_points': points, 'quantity_episodes': _quantity_episodes(points, supported=scope, world_hash=manifest.get('world_hash')),
        'boundary_inventory': boundaries, 'metric_requirements': requirements,
        'input_hash': loaded['input_hash'], 'provider_requests': 0, 'credential_lookups': 0}


def collected_archive(loaded):
    manifest = loaded['manifest']
    refs = [{'kind': 'transaction', 'signature': r['signature'], 'hash': r['hash']} for r in manifest['transactions']]
    return {'transactions': loaded['records'], 'evidence': refs + deepcopy(manifest.get('evidence', [])),
            'checkpoint': {}, 'snapshot': {}, 'coverage': {'source': VERSION, 'complete': False, 'history_complete': False}}
