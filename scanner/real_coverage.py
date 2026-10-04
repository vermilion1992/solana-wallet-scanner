"""Raw indexed-query coverage, distinct from historical wallet membership.

These receipts describe the provider's documented address query.  They do not
admit caller completion flags, source-decision objects or saved PASS receipts.
The pinned primary wording does not establish closed/reassigned historical owner
coverage, so that separate dependency cannot pass under this contract.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import re

from .accounting import utc
from .indexed_input import (PAGE_VERSION, NATIVE_VERSION, RECORD_VERSION, MAX_PAGES, MAX_PAGE_RECORDS,
                            _exact_bytes, _json, canonical_bytes, describe_pages, source_records,
                            validate_page_envelope)
from .transaction_format import supported_transaction_format

VERSION = 'indexed-query-coverage-v2'
MAX_RECORDS = 10_000
_HASH = re.compile(r'[a-f0-9]{64}')
_SCOPE = 'Complete documented indexed address-query population only; historical wallet membership is separate'
MAX_AFFINITY_NODES = 1_000_000

# This is a software-pinned interpretation of retained primary documentation,
# not an imported provider promise or an authenticity certificate.
_PROVIDER_CONTRACT = {
    'id': 'helius-indexed-address-query-2026-10-03',
    'document': 'evidence/references/product-milestone/helius-index-guide.txt',
    'document_sha256': 'ecb75c9566dfcda8e209ea1b5ed829373749d181a1c9326e363abe8eb346c54c',
    'documented_predicate': 'Transactions referencing the address or any token account owned by the provided address',
    'historical_membership_state': 'UNKNOWN',
    'format_population_state': 'UNKNOWN',
    'reason': 'Pinned wording does not explicitly guarantee closed, reassigned or both-program event-time historical membership.',
}


def _receipt(known, reason, evidence=(), **details):
    hashes = sorted({h for h in evidence if isinstance(h, str) and _HASH.fullmatch(h)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'scope': _SCOPE,
            'reason': reason, 'evidence': hashes, **details}


def _bounds(scope):
    value = scope.get('block_time') if isinstance(scope, dict) else None
    return (value['gte'], value['lt']) if isinstance(value, dict) else None


def _integer_boundary(value):
    """Ceil exact UTC time for integer-second native blockTime membership."""
    offset = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    whole = offset.days * 86400 + offset.seconds
    return whole + bool(offset.microseconds)


def query_source_dependencies(raw_sources):
    """Freeze negative page affinity from bytes, even under misleading roles.

    This is an index of rejecting dependencies, never query/population proof.
    Missing typed pages, recognizable malformed versions and nested byte
    envelopes retain the original containing source hash.  Exhausting the
    bounded inspection cannot certify an uninspected disjoint prefix.
    """
    hashes = set()
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        digest = source.get('hash')
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            continue
        if source.get('kind') in ('indexed-page', 'query-affinity'):
            hashes.add(digest)
            continue
        nodes, seen, inspected = [source.get('payload')], set(), 0
        while nodes:
            value = nodes.pop()
            if not isinstance(value, (dict, list)) or id(value) in seen:
                continue
            seen.add(id(value))
            inspected += 1
            if inspected > MAX_AFFINITY_NODES:
                hashes.add(digest)
                break
            if isinstance(value, dict):
                if value.get('version') == PAGE_VERSION:
                    hashes.add(digest)
                    break
                if 'request_base64' in value:
                    try:
                        request = _json(_exact_bytes(value, 'request'))
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        # An undecodable byte envelope is not proof of a
                        # non-query role; retaining it is negative-only.
                        hashes.add(digest)
                        break
                    if isinstance(request, dict) and request.get('method') == 'getTransactionsForAddress':
                        hashes.add(digest)
                        break
                nodes.extend(child for child in value.values() if isinstance(child, (dict, list)))
            else:
                nodes.extend(child for child in value if isinstance(child, (dict, list)))
    return sorted(hashes)


def derive_indexed_coverage(records, *, all_records, raw_sources, wallet, window,
                            source_consistency, chronology):
    """Recompute terminal query membership and independent interval receipts.

    Every returned original must enter the ordinary linked-record path and have
    a selected counterpart bound to that same checked source family. Native
    parsed/compiled representations need not be byte-identical. A retained page
    subset or caller receipt cannot certify completion. Alternative sources,
    unsupported records and clocks remain ordinary dependencies.
    Neither terminal pages nor successful lifecycle observations supply the
    missing historical-owner predicate.
    """
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('A positive coverage window is required')
    selected = defaultdict(list)
    for row in records:
        if isinstance(row, dict) and isinstance(row.get('signature'), str):
            selected[row['signature']].append(row)
    linked = defaultdict(list)
    for row in all_records:
        if isinstance(row, dict) and isinstance(row.get('signature'), str):
            linked[row['signature']].append(row)
    raw_sources = list(raw_sources)
    affinities = set(query_source_dependencies(raw_sources))
    sources = [row for row in raw_sources if isinstance(row, dict) and row.get('hash') in affinities]
    budget_exceeded = False
    pages, groups, opaque, total = [], defaultdict(list), [], 0
    seen = set()
    for source in sources:
        digest, payload = source.get('hash'), source.get('payload')
        try:
            body_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
            verified = isinstance(digest, str) and _HASH.fullmatch(digest) and body_hash == digest
        except (ValueError, TypeError, RecursionError):
            body_hash, verified = None, False
        key = digest, body_hash
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_PAGES:
            budget_exceeded = True
            break  # Distinct linked variants count; a mirrored role does not.
        page = validate_page_envelope(payload, wallet)
        total += len(page['records'])
        if not verified:
            page.update(state='UNKNOWN', reason='Frozen indexed page is unavailable or checksum-mismatched',
                        request_scope=None)
        row = {'hash': digest, 'payload': payload, 'page': page}
        pages.append(row)
        scope = page.get('request_scope')
        if scope is None:
            opaque.append(row)
        else:
            groups[canonical_bytes({k: v for k, v in scope.items() if k != 'limit'})].append(row)
    budget_exceeded = budget_exceeded or total > MAX_RECORDS
    # Bind bodies to actual frozen preimages, not caller annotations. A direct
    # raw archive uses its body hash; the existing indexed loader instead uses
    # the exact pointer hash or a direct source-wrapper link. Either retains
    # original bytes in the same linked-record assessment as the selected row.
    bindings = defaultdict(set)
    def bind(raw, source_hash, ordinal):
        transaction = raw.get('transaction') if isinstance(raw, dict) else None
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        signature = signatures[0] if isinstance(signatures, list) and signatures else None
        if not isinstance(signature, str):
            return
        try:
            native_hash = hashlib.sha256(canonical_bytes(raw)).hexdigest()
            pointer = {'version': RECORD_VERSION, 'source_hash': source_hash, 'ordinal': ordinal,
                       'signature': signature, 'native_hash': native_hash}
            pointer_hash = hashlib.sha256(canonical_bytes(pointer)).hexdigest()
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            return  # Rejected bytes cannot bind a native body or frozen pointer.
        bindings[signature, native_hash].update((native_hash, source_hash, pointer_hash))
    for row in pages:
        # Invalid pages cannot certify query completion; readable bodies still
        # remain rejection/format dependencies in the ordinary source path.
        for ordinal, raw in enumerate(row['page']['records']):
            bind(raw, row['hash'], ordinal)
    native_sources = set()
    for source in raw_sources:
        payload = source.get('payload') if isinstance(source, dict) else None
        digest = source.get('hash') if isinstance(source, dict) else None
        if not isinstance(payload, dict) or payload.get('version') != NATIVE_VERSION:
            continue
        try:
            body_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
            if digest != body_hash or body_hash in native_sources:
                continue
            native_sources.add(body_hash)
            native = source_records(payload, address=wallet)
            if native['state'] == 'PASS':
                for ordinal, raw in enumerate(native['records']):
                    bind(raw, digest, ordinal)
        except (ValueError, TypeError, RecursionError):
            continue  # Shared linked-record checks retain the rejecting input.
    body_hashes = {}
    def record_bound(row):
        raw, digest = row.get('raw'), row.get('evidence_hash')
        if not isinstance(raw, dict) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
            return False
        transaction = raw.get('transaction')
        signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
        if not isinstance(signatures, list) or not signatures or signatures[0] != row.get('signature'):
            return False
        try:
            if id(raw) not in body_hashes:
                body_hashes[id(raw)] = hashlib.sha256(canonical_bytes(raw)).hexdigest()
            native_hash = body_hashes[id(raw)]
            return digest == native_hash or digest in bindings[row.get('signature'), native_hash]
        except (ValueError, TypeError, RecursionError):
            return False
    interval_results = {}
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        lower, upper = _integer_boundary(begin), _integer_boundary(end)
        attempts = []
        for group in groups.values():
            scope = group[0]['page']['request_scope']
            bounds = _bounds(scope)
            if (scope['status'] != 'any' or scope['token_accounts'] != 'all'
                or bounds is not None and not (bounds[0] <= lower and bounds[1] >= upper)):
                continue
            topology = describe_pages([{'hash': row['hash'], 'payload': row['payload']} for row in group], wallet, window)
            evidence = {row['hash'] for row in group}
            gaps = list(topology['gaps'])
            returned, duplicate, logical = {}, set(), set()
            for row in group:
                page = row['page']
                logical_key = (page['cursor_in'], page['cursor_out'], tuple(page['record_hashes']))
                if logical_key in logical:
                    continue  # Identical native page observed under another RPC id.
                logical.add(logical_key)
                if page['state'] != 'PASS':
                    gaps.append(page['reason'])
                for raw in page['records'][:MAX_PAGE_RECORDS]:
                    transaction = raw.get('transaction') if isinstance(raw, dict) else None
                    signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
                    signature = signatures[0] if isinstance(signatures, list) and signatures else None
                    if not isinstance(signature, str):
                        gaps.append('Returned record has no assignable signature')
                        continue
                    if signature in returned:
                        duplicate.add(signature)
                    returned[signature] = raw
            if duplicate:
                gaps.append('Signatures repeat across distinct cursor pages')
            supported_gaps, selected_gaps, selected_hashes = [], [], set()
            for signature, raw in returned.items():
                choices = selected.get(signature, [])
                alternatives = linked.get(signature, [])
                original_retained = any(row.get('raw') == raw and record_bound(row) for row in alternatives)
                if not original_retained:
                    selected_gaps.append(f'{signature}: returned original bytes have no matching frozen linked accounting record')
                chosen_linked = bool(choices) and all(record_bound(chosen) and any(
                    row.get('evidence_hash') == chosen.get('evidence_hash') and row.get('raw') == chosen.get('raw')
                    for row in alternatives) for chosen in choices)
                if not chosen_linked:
                    selected_gaps.append(f'{signature}: returned record is not selected through a matching frozen linked accounting record')
                elif any(chosen.get('raw') != choices[0].get('raw') for chosen in choices):
                    selected_gaps.append(f'{signature}: conflicting primary selections cannot choose the query representation')
                else:
                    selected_hashes.update(chosen.get('evidence_hash') for chosen in choices)
                selected_hashes.update(row.get('evidence_hash') for row in alternatives
                    if isinstance(row.get('evidence_hash'), str) and _HASH.fullmatch(row['evidence_hash']))
                if not alternatives or any(not isinstance(row.get('raw'), dict) or
                        not supported_transaction_format(row['raw']) for row in alternatives):
                    supported_gaps.append(f'{signature}: a linked record is unavailable or unsupported')
                group_check = source_consistency.get('transactions', {}).get(signature, {})
                if group_check.get('identity', {}).get('state') != 'PASS':
                    supported_gaps.append(f'{signature}: linked raw identity is unresolved')
                clock = chronology.get('transactions', {}).get(signature, {})
                if clock.get('state') != 'PASS' or clock.get('time_state') != 'PASS':
                    supported_gaps.append(f'{signature}: linked chronology is unresolved')
            gaps += selected_gaps
            if opaque:
                gaps.append('A still-linked indexed page has no independently assignable request scope')
            query_known = topology['state'] == 'PASS' and not gaps and not budget_exceeded
            supported_known = query_known and not supported_gaps
            attempts.append(_receipt(query_known, '; '.join(sorted(set(gaps))) or 'Every terminal original and its selected counterpart enter the ordinary linked raw accounting path.',
                evidence | selected_hashes, query_records_state='PASS' if query_known else 'UNKNOWN',
                supported_record_state='PASS' if supported_known else 'UNKNOWN',
                historical_population_state='UNKNOWN', format_population_state='UNKNOWN', signatures=sorted(returned),
                record_count=len(returned), gaps=sorted(set(gaps + supported_gaps)),
                request_scope=scope, source_hashes=sorted(h for h in evidence if isinstance(h, str) and _HASH.fullmatch(h))))
        # A fully supported wider query may serve several independent intervals;
        # a narrower one cannot be substituted for any missing 28/90-day scope.
        supported = [row for row in attempts if row['state'] == 'PASS' and row['supported_record_state'] == 'PASS']
        usable = supported or [row for row in attempts if row['state'] == 'PASS'] or attempts
        if usable:
            result = sorted(usable, key=lambda row: (row['record_count'], row['source_hashes']))[0]
        else:
            result = _receipt(False, 'No complete unfiltered finalized indexed query spans this independent interval.',
                (row['hash'] for row in pages), query_records_state='UNKNOWN', supported_record_state='UNKNOWN',
                historical_population_state='UNKNOWN', format_population_state='UNKNOWN', signatures=[], record_count=0,
                gaps=['No admissible terminal query for this interval'])
        if budget_exceeded:
            result.update(state='UNKNOWN', query_records_state='UNKNOWN', supported_record_state='UNKNOWN',
                          reason='Indexed coverage inspection budget exceeded; no inspected prefix certifies the query.')
            result['gaps'] = sorted(set(result['gaps'] + ['Indexed coverage inspection budget exceeded']))
        result = {**result, 'interval': name, 'start': begin.isoformat(), 'end': end.isoformat()}
        interval_results[name] = result
    evidence = [row['hash'] for row in pages]
    historical = _receipt(False, _PROVIDER_CONTRACT['reason'], evidence,
        dependencies=['accepted_historical_owner_source_contract', 'independent_closed_reassigned_lifecycle_controls'])
    return {'version': VERSION, 'scope': _SCOPE, 'provider_contract': dict(_PROVIDER_CONTRACT),
            'historical_population': historical, 'intervals': interval_results,
            'inspection_budget': {'max_pages': MAX_PAGES, 'max_records': MAX_RECORDS,
                                  'records': total, 'exceeded': budget_exceeded},
            'provider_requests': 0, 'credential_lookups': 0}
