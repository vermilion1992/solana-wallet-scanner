"""Source-derived asset identity and deliberately bounded eligibility admission.

The blueprint screens meme assets and excludes settlement assets and spam. Mint
addresses, decimals, authority revocation and current metadata do not prove that
an asset was a nonspam meme at an earlier trade. This module can exclude the
canonical legacy wrapped-native mint and expose exact archived mint controls;
it cannot invent the missing historical meme/nonspam source contract.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
import hashlib
import re

from .accounting import raw_quantity, utc
from .chronology_evidence import assess_interval_membership
from .collector import _valid_account
from .investigation import WSOL
from .json_boundary import canonical_bytes, parse_json
from .providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from .wallet_identity import ACCOUNT_SOURCE_VERSION, account_source_bytes

VERSION = 'asset-classification-evidence-v2'
MAX_SOURCES = 10_000
MAX_NODES = 1_000_000
HASH = re.compile(r'^[a-f0-9]{64}$')
U64 = 2**64 - 1
SCOPE = 'Selected raw asset observations; no exhaustive historical eligible-wallet population'
_CLASS_DEPENDENCIES = ('accepted_time_relevant_meme_identity', 'accepted_time_relevant_spam_exclusion')


def _hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _check(known, reason, evidence=(), *, dependencies=(), raw_paths=()):
    hashes = sorted({value for value in evidence if _hash(value)})
    return {'state': 'PASS' if known and hashes else 'UNKNOWN', 'reason': reason,
            'scope': SCOPE, 'evidence': hashes, 'dependencies': sorted(set(dependencies)),
            'raw_paths': sorted(set(raw_paths))}


def _combine(checks, reason, evidence=(), *, dependencies=()):
    checks = list(checks)
    return _check(bool(checks) and all(check.get('state') == 'PASS' for check in checks), reason,
                  list(evidence) + [h for check in checks for h in check.get('evidence', [])],
                  dependencies=set(dependencies) | {d for check in checks for d in check.get('dependencies', [])})


def _raw_candidates(payload):
    """Use the existing exact-byte indexed decoder, including mislabeled roles."""
    from .wallet_evidence import _indexed_native_rows
    indexed, _, _, recognized = _indexed_native_rows(payload)
    if recognized:
        return indexed
    result, stack, count = [], [payload], 0
    while stack:
        value = stack.pop()
        if not isinstance(value, dict):
            continue
        count += 1
        if count > 64:
            return []
        if isinstance(value.get('transaction'), dict) and isinstance(value.get('meta'), dict):
            result.append(value)
        stack.extend(value.get(key) for key in ('result', 'value') if isinstance(value.get(key), dict))
    return result


def _source_bodies(raw_sources):
    from .wallet_evidence import _resolved_sources
    sources = _resolved_sources(raw_sources, ())
    bodies = defaultdict(list)
    for source in sources:
        bodies[source['hash']].append(source['payload'])
    return bodies


def _raw_bound(record, bodies, resolver, candidates, verified):
    """A supplied raw object must occur in its checksum-verified source body."""
    digest, raw = record.get('evidence_hash'), record.get('raw')
    if not _hash(digest) or not isinstance(raw, dict):
        return False
    if digest in bodies:
        payloads = bodies[digest]
        if not payloads or any(payload is None for payload in payloads):
            return False
        from .indexed_input import RECORD_VERSION
        for payload in payloads:
            if isinstance(payload, dict) and payload.get('version') == RECORD_VERSION:
                receipt = resolver.resolve(payload)
                if receipt.get('state') == 'PASS' and receipt.get('raw') == raw:
                    return True
        if digest not in candidates:
            candidates[digest] = [candidate for payload in payloads for candidate in _raw_candidates(payload)]
        return any(candidate == raw for candidate in candidates[digest])
    # Direct native archives use the raw transaction itself as the preimage.
    # An indexed pointer/page cannot pass this fallback with a detached object.
    try:
        return (hashlib.sha256(canonical_bytes(raw, max_nodes=MAX_NODES, string_keys=True)).hexdigest() == digest
                or verified.get((record.get('signature'), digest)) == raw)
    except (ValueError, TypeError):
        return False


def _record_assets(record, wallet, bodies, resolver, candidates, verified):
    from .wallet_evidence import _observe, _flat
    digest = record.get('evidence_hash')
    if not _raw_bound(record, bodies, resolver, candidates, verified):
        return {}, _check(False, 'Selected/alternative native bytes are missing, corrupt or detached from their source hash.',
                          [digest], dependencies=['original_native_asset_identity'])
    observed = _observe(record, wallet)
    if observed['gaps']:
        return {}, _check(False, '; '.join(observed['gaps']), [digest], dependencies=['supported_native_asset_identity'])
    # Failed execution does not commit attempted asset movements or classes.
    if observed['failed'] is True:
        return {}, _check(True, 'Failed execution has no committed traded-asset population.', [digest])
    # Positive mint/burn operations can cancel just like ordinary transfers.
    # Reuse the validated outer/inner association and compiled semantic view;
    # recognizing quantity activity here does not manufacture a purchase/sale.
    from .compiled_instructions import normalize_transaction
    from .transaction_format import _needs_instruction_view
    from .investigation import _keys
    raw = record['raw']
    semantic_raw = normalize_transaction(raw)['raw'] if _needs_instruction_view(raw) else raw
    gross_mint_accounts = set()
    try:
        keys = _keys(semantic_raw['transaction']['message'], semantic_raw['meta'])
        for _, _, instruction, _, view in _flat(semantic_raw, keys):
            parsed = instruction.get('parsed')
            info = parsed.get('info') if isinstance(parsed, dict) else None
            kind = parsed.get('type') if isinstance(parsed, dict) else None
            if (view['program'] in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM) and isinstance(info, dict)
                and kind in ('mintTo', 'mintToChecked', 'burn', 'burnChecked')):
                quantity = info.get('tokenAmount', {}).get('amount') if kind.endswith('Checked') else info.get('amount')
                if raw_quantity(quantity) > 0:
                    gross_mint_accounts.add(info.get('account'))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {}, _check(False, 'Executed mint/burn activity cannot be inspected under its shared instruction contract.',
                          [digest], dependencies=['supported_asset_activity_population'])
    assets = {}
    for account, pair in observed['boundaries'].items():
        points = [pair.get(phase) for phase in ('pre', 'post')]
        relevant = [point for point in points if isinstance(point, dict) and point.get('owner') == wallet]
        if not relevant:
            continue
        mints = {point['mint'] for point in relevant}
        changed = len(relevant) != 2 or any(points[0].get(key) != points[1].get(key)
                                          for key in ('mint', 'owner', 'quantity', 'decimals'))
        changed = changed or any(item['account'] == account and item.get('applied') is True
                                 for item in observed['lifecycle'])
        changed = changed or any(account in (item['source'], item['destination'])
                                 and int(item['quantity_raw']) > 0 for item in observed['transfers'])
        changed = changed or account in gross_mint_accounts
        identity_known = (len(mints) == 1 and len(points) == 2 and all(isinstance(point, dict) for point in points)
                          and points[0]['mint'] == points[1]['mint']
                          and points[0]['decimals'] == points[1]['decimals']
                          and pair['checks']['ownership']['state'] == 'PASS')
        for mint in sorted(mints):
            decimals = {point['decimals'] for point in relevant if point['mint'] == mint}
            settlement = identity_known and mint == WSOL and decimals == {9} and pair.get('program') == TOKEN_PROGRAM
            row = assets.setdefault(mint, {'mint': mint, 'classification': 'settlement' if settlement else 'unknown',
                'eligibility': 'excluded_settlement' if settlement else 'unknown', 'accounts': [], 'programs': [],
                'decimals': [], 'activity_observed': False, 'checks': []})
            row['accounts'].append(account)
            row['programs'].append(pair.get('program'))
            row['decimals'].extend(decimals)
            row['activity_observed'] = row['activity_observed'] or changed
            row['checks'].append(_check(settlement,
                'Canonical legacy wrapped SOL is a settlement asset; its raw mint/program/9-decimal identity agrees.'
                if settlement else 'Raw mint controls or identity cannot establish historical meme/nonspam eligibility.',
                [digest], dependencies=() if settlement else _CLASS_DEPENDENCIES,
                raw_paths=pair['checks']['ownership'].get('raw_paths', [])))
    checks = []
    for row in assets.values():
        check = _combine(row.pop('checks'), 'Every evidenced account identity agrees for this selected asset.')
        row['check'] = check
        if check['state'] != 'PASS':
            row['classification'] = row['eligibility'] = 'unknown'
        for name in ('accounts', 'programs', 'decimals'):
            row[name] = sorted(set(row[name]), key=str)
        if row['activity_observed']:
            checks.append(check)
    # An unsupported executed route cannot prove that a net-zero balance
    # suppressed all gross asset activity. _observe retains its operation gap.
    unsupported = any(pair['checks']['quantities']['state'] != 'PASS'
                      for pair in observed['boundaries'].values())
    if unsupported:
        checks.append(_check(False, 'An executed account operation has unresolved gross activity.', [digest],
                             dependencies=['supported_asset_activity_population']))
    if not checks:
        checks = [_check(True, 'Supported raw endpoints/operations contain no relevant nonsettlement asset movement.', [digest])]
    return dict(sorted(assets.items())), _combine(checks, 'Classification covers committed selected asset activity only.')


def project_asset_classification(*, selected, raw_versions, transactions, clocks, consistency,
                                 raw_sources, wallet, window):
    """Private normal-report projection over fresh shared source/clock receipts.

    No imported classifications, events, metadata labels or completion flags are
    read. Current mint snapshots are informational and never populate eligibility.
    """
    if not _valid_account(wallet):
        raise ValueError('Classification requires a public wallet address')
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('Classification requires a positive report interval')
    raw_sources = list(raw_sources)
    budget_exceeded = len(raw_sources) > MAX_SOURCES
    source_hashes = [row.get('hash') for row in raw_sources if isinstance(row, dict)]
    declared_sources = {
        row['hash']: _check(False,
            'Declared classification bytes are retained but no accepted historical meme/nonspam source contract exists.',
            [row['hash']], dependencies=['accepted_historical_asset_classification'])
        for row in raw_sources if isinstance(row, dict) and _hash(row.get('hash'))
        and row.get('kind') == 'classification'}
    if not budget_exceeded:
        bodies = _source_bodies(raw_sources)
        from .wallet_positions import _verified_records
        checked = _verified_records([record for versions in raw_versions.values() for record in versions], raw_sources)
        verified = {(row.get('signature'), row.get('evidence_hash')): row.get('raw') for row in checked}
        from .indexed_input import IndexedResolver
        def read(digest, role=None):
            payloads = bodies.get(digest, [])
            return payloads[0] if payloads and all(payload is not None and payload == payloads[0] for payload in payloads) else None
        resolver, candidates = IndexedResolver(read, address=wallet), {}
    records, interval_checks = {}, {}
    for signature in sorted(selected):
        rows, assets = [], []
        versions = raw_versions.get(signature, [])
        if budget_exceeded:
            # Optional classification inspection must not reduce the native
            # archive capacity or erase independently supported fee results.
            records[signature] = {'signature': signature, 'assets': {},
                'check': _check(False, 'Classification source inspection budget exceeded; no convenient prefix is accepted.',
                    [row.get('evidence_hash') for row in versions],
                    dependencies=['complete_classification_source_inspection'])}
            continue
        for record in versions:
            facts, check = _record_assets(record, wallet, bodies, resolver, candidates, verified)
            assets.append(facts)
            rows.append(check)
        identity = transactions.get(signature, {}).get('checks', {}).get('identity', {})
        checks = rows + [_check(identity.get('state') == 'PASS',
            'Shared selected identity and complete linked alternatives must remain supported.',
            identity.get('evidence', []), dependencies=['selected_and_linked_native_identity'])]
        # Each linked source may add an asset, but cannot remove a contrary class.
        semantic = lambda facts: {mint: {key: value for key, value in row.items() if key != 'check'}
                                  for mint, row in facts.items()}
        agreement = bool(assets) and all(semantic(value) == semantic(assets[0]) for value in assets[1:])
        checks.append(_check(agreement, 'Linked raw asset identities and activity agree.',
                             [row.get('evidence_hash') for row in versions],
                             dependencies=['linked_asset_identity_consistency']))
        if agreement:
            for mint, row in assets[0].items():
                row['check'] = _combine([facts[mint]['check'] for facts in assets],
                    'Every linked raw version agrees on this asset identity/classification.')
        records[signature] = {'signature': signature, 'assets': assets[0] if agreement else {},
            'check': _combine(checks, 'Selected asset classifications require every linked raw version.')}
    source_set = consistency.get('source_set', {})
    source_check = _check(source_set.get('state') == 'PASS',
        'The complete frozen native source inventory remains represented.', source_set.get('evidence', []),
        dependencies=['linked_native_source_inventory'])
    source_checks = [source_check]
    if budget_exceeded:
        source_checks.append(_check(False,
            'Classification source inspection budget exceeded; the full retained source set remains a dependency.',
            source_hashes, dependencies=['complete_classification_source_inspection']))
    for name, begin in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                        ('verification_90d', end - timedelta(days=90))):
        checks, memberships = list(source_checks), {}
        for signature, row in records.items():
            membership = assess_interval_membership(clocks, signature, begin, end)
            memberships[signature] = membership
            checks.append(membership)
            if membership.get('state') != 'PASS' or membership.get('member') is not False:
                checks.append(row['check'])
        if not records:
            checks.append(_check(False, 'No raw selected population supports this interval.', source_set.get('evidence', [])))
        interval_checks[name] = {**_combine(checks,
            'Every selected in-scope asset is classified or proved settlement; historical wallet population remains separate.',
            evidence=declared_sources),
            'interval': name, 'start': begin.isoformat(), 'end': end.isoformat(), 'memberships': memberships}
    # Current mint controls have their own source set. Retain every declaration
    # of each candidate hash so filtering cannot hide a corrupt alternative.
    mint_hashes = {row['hash'] for row in raw_sources if isinstance(row, dict) and _hash(row.get('hash'))
        and (row.get('kind') == 'current-mint-controls' or isinstance(row.get('payload'), dict)
             and row['payload'].get('version') == ACCOUNT_SOURCE_VERSION)}
    mint_sources = [row for row in raw_sources if isinstance(row, dict) and _hash(row.get('hash'))
                    and row['hash'] in mint_hashes]
    snapshots = derive_mint_snapshots(mint_sources) if len(mint_sources) <= MAX_SOURCES else []
    snapshot_hashes = {digest for row in snapshots for digest in row['evidence']}
    snapshot_sources = {
        row['hash']: _check(row['hash'] in snapshot_hashes,
            'Exact archived current mint snapshot is present; its individual controls remain independently assessed.'
            if row['hash'] in snapshot_hashes else 'Declared current mint snapshot bytes are missing, corrupt or unsupported.',
            [row['hash']], dependencies=['original_current_mint_snapshot'])
        for row in raw_sources if isinstance(row, dict) and _hash(row.get('hash'))
        and (row.get('kind') == 'current-mint-controls' or row['hash'] in snapshot_hashes)}
    return {'version': VERSION, 'scope': SCOPE, 'records': records,
        'classification_by_interval': interval_checks, 'mint_snapshots': snapshots,
        'declared_classification_sources': dict(sorted(declared_sources.items())),
        'mint_snapshot_sources': dict(sorted(snapshot_sources.items())),
        'inspection_budget': {'max_sources': MAX_SOURCES, 'source_count': len(raw_sources),
            'state': 'UNKNOWN' if budget_exceeded else 'PASS',
            'mint_source_count': len(mint_sources),
            'mint_state': 'UNKNOWN' if len(mint_sources) > MAX_SOURCES else 'PASS'},
        'historical_eligibility_state': 'UNKNOWN', 'wallet_population_state': 'UNKNOWN', 'qualification': False,
        'limitations': ['Canonical wrapped SOL exclusion does not establish a meme cohort.',
            'Current or same-slot account controls are not event-time historical classification.',
            'Missing time-relevant meme identity and spam exclusion remain separate dependencies.'],
        'provider_requests': 0, 'credential_lookups': 0}


def derive_mint_snapshots(raw_sources):
    """Independently usable controls from exact-byte finalized mint RPC sources."""
    from .wallet_evidence import _resolved_sources
    rows = []
    for source in _resolved_sources(raw_sources, ()):
        payload, digest = source['payload'], source['hash']
        if not isinstance(payload, dict) or payload.get('version') != ACCOUNT_SOURCE_VERSION:
            continue
        try:
            original = account_source_bytes(payload)
            request, response = (parse_json(original[name], max_nodes=MAX_NODES) for name in ('request', 'response'))
            if (not isinstance(request, dict) or set(request) != {'jsonrpc', 'id', 'method', 'params'}
                or request.get('jsonrpc') != '2.0' or request.get('method') != 'getAccountInfo'
                or not (type(request.get('id')) is int or isinstance(request.get('id'), str))
                or not isinstance(response, dict) or set(response) != {'jsonrpc', 'id', 'result'}
                or response.get('jsonrpc') != '2.0' or type(response.get('id')) is not type(request['id'])
                or response.get('id') != request['id']):
                continue
            params = request['params']
            if not isinstance(params, list) or len(params) != 2 or not _valid_account(params[0]):
                continue
            mint, options = params
            if (not isinstance(options, dict) or set(options) - {'encoding', 'commitment', 'minContextSlot'}
                or options.get('encoding') != 'jsonParsed' or options.get('commitment') != 'finalized'
                or 'minContextSlot' in options and (type(options['minContextSlot']) is not int or not 0 <= options['minContextSlot'] <= U64)):
                continue
            result = response['result']
            context = result.get('context') if isinstance(result, dict) else None
            slot = context.get('slot') if isinstance(context, dict) else None
            account = result.get('value') if isinstance(result, dict) else None
            if (type(slot) is not int or not 0 <= slot <= U64
                or slot < options.get('minContextSlot', 0) or not isinstance(account, dict)
                or account.get('owner') not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM)
                or account.get('executable') is not False
                or type(account.get('lamports')) is not int or not 0 <= account['lamports'] <= U64):
                continue
            data = account.get('data')
            parsed = data.get('parsed') if isinstance(data, dict) else None
            info = parsed.get('info') if isinstance(parsed, dict) and parsed.get('type') == 'mint' else None
            if not isinstance(info, dict) or info.get('isInitialized') is not True:
                continue
            controls = {}
            for field in ('mintAuthority', 'freezeAuthority'):
                value = info.get(field)
                known = field in info and (value is None or _valid_account(value))
                controls[field] = {**_check(known, 'Exact archived current mint capability; no historical safety/class proof.',
                    [digest], raw_paths=['response.result.value.data.parsed.info.' + field]),
                    'value': value if known else None, 'active': value is not None if known else None}
            decimals = info.get('decimals')
            precision = type(decimals) is int and 0 <= decimals <= 255
            supply = info.get('supply')
            supply_known = isinstance(supply, str) and re.fullmatch(r'[0-9]{1,20}', supply) is not None and int(supply) <= U64
            extensions = info.get('extensions')
            legacy = account['owner'] == TOKEN_PROGRAM
            extensions_known = legacy or isinstance(extensions, list) and all(isinstance(value, dict) for value in extensions)
            controls['extensions'] = {**_check(extensions_known,
                'Archived extension inventory only; listed capability semantics and sellability remain separate.' if not legacy
                else 'Legacy token program has no Token-2022 mint extensions.', [digest]),
                'value': [] if legacy else deepcopy(extensions) if extensions_known else None,
                'safety_state': 'UNKNOWN'}
            rows.append({'mint': mint, 'slot': slot, 'program': account['owner'], 'evidence': [digest],
                'decimals': decimals if precision else None, 'supply_raw': str(int(supply)) if supply_known else None,
                'controls': controls, 'classification': 'unknown', 'eligibility': 'unknown',
                'historical_state': 'UNKNOWN', 'scope': 'Current finalized RPC mint snapshot only'})
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return sorted(rows, key=lambda row: (row['mint'], row['slot'], row['evidence']))
