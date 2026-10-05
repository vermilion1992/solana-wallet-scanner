"""Sampled research HTTP routes; strict wallet qualification stays independent."""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import json
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .config import validate_address
from .storage import now, EvidenceError, QuotaExceeded
from .providers import ProviderError


def _provider_stop(error):
    """Retain a bounded failure receipt without treating it as chain activity."""
    code = getattr(error, 'code', None)
    if not (type(code) is int or isinstance(code, str) and len(code) <= 128):
        code = 'budget_exhausted' if isinstance(error, QuotaExceeded) else 'provider_unavailable'
    digest = getattr(error, 'evidence_hash', None)
    if not (isinstance(digest, str) and len(digest) == 64 and all(character in '0123456789abcdef' for character in digest)):
        digest = None
    return {'code': code, 'http_status': code if type(code) is int and 100 <= code <= 599 else None,
            'evidence_hash': digest, 'observed_at': now()}


def observation_view(store, run):
    return {**run, 'observer': store.get('observer_runtime', run['id'], {}),
            'notifications': [event for event in store.list('observer_events') if event.get('run_id') == run['id']]}


def screening_view(store, frozen, *, source_cache=None, identity_cache=None):
    """Recheck cited archives without changing the immutable saved assessment."""
    source_cache = {} if source_cache is None else source_cache
    identity_cache = {} if identity_cache is None else identity_cache
    hashes, malformed, nodes = set(), False, [frozen]
    while nodes:
        item = nodes.pop()
        if isinstance(item, list):
            nodes.extend(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                if key == 'evidence':
                    if not isinstance(value, list):
                        malformed = True
                    else:
                        for citation in value:
                            digest = citation.get('hash') if isinstance(citation, dict) else citation
                            if isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
                                hashes.add(digest)
                            else:
                                malformed = True
                elif key in ('evidence_hash', 'report_input_hash') and value is not None:
                    if isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value):
                        hashes.add(value)
                    else:
                        malformed = True
                if isinstance(value, (dict, list)):
                    nodes.append(value)
    missing = []
    for digest in sorted(hashes):
        if digest not in source_cache:
            try:
                store.evidence(digest)
                source_cache[digest] = True
            except (EvidenceError, ValueError, TypeError):
                source_cache[digest] = False
        if not source_cache[digest]:
            missing.append(digest)
    if malformed:
        missing.append(None)
    address = frozen['address']
    if address not in identity_cache:
        identity_cache[address] = saved_identity(store, address)
    identity = deepcopy(identity_cache[address])
    if missing:
        reason = 'Cited archived sources are unavailable or malformed. The saved assessment is retained; its result cannot establish a supported current conclusion.'
    elif identity['state'] != 'PASS':
        reason = identity['reason']
    else:
        reason = frozen['reason']
    supportable = not missing and identity['state'] == 'PASS'
    eligible = supportable and frozen['result'] != 'excluded_by_preset'
    return {**deepcopy(frozen),
            'current_source_availability': {'state': 'UNKNOWN' if missing else 'PASS', 'missing': missing},
            'current_identity': identity,
            'current_result': frozen['result'] if supportable else 'insufficient_evidence',
            'current_label': frozen['label'] if supportable else 'Insufficient current evidence',
            'current_reason': reason,
            'current_eligibility': {'can_start_observation': eligible,
                'reason': 'Current cited sources and native identity support starting separate forward quote-only research.' if eligible else reason}}


def screening_views(store):
    """One fresh invocation cache for state/list consistency and bounded reads."""
    sources, identities = {}, {}
    return [screening_view(store, frozen, source_cache=sources, identity_cache=identities)
            for frozen in store.list('screenings')]


def saved_identity(store, address):
    """Re-read native identity evidence; import provenance never proves identity."""
    from .discovery import plan_candidate_audits
    cohorts = [cohort for cohort in store.list('discovery_cohorts')
               if any(c.get('address') == address for c in cohort.get('candidates', []))]
    rows, links, account_hashes = [], [], set()
    for cohort in cohorts:
        links.extend(cohort.get('evidence', []))
        for candidate in cohort.get('candidates', []):
            if candidate.get('address') != address:
                continue
            for digest in candidate.get('evidence', []):
                links.append({'kind': 'identity-alternative', 'hash': digest})
            digest = candidate.get('validation', {}).get('account_evidence_hash')
            if isinstance(digest, str):
                account_hashes.add(digest)
    accounts = []
    for link in links:
        if not isinstance(link, dict) or not isinstance(link.get('hash'), str):
            return {'state': 'UNKNOWN', 'reason': 'Malformed linked identity alternatives must be restored.', 'evidence': sorted(account_hashes)}
        try:
            payload = store.evidence(link['hash'])
        except EvidenceError:
            return {'state': 'UNKNOWN', 'reason': 'A still-linked identity alternative is unavailable.', 'evidence': [link['hash']]}
        if isinstance(payload, dict) and payload.get('method') == 'getAccountInfo' and payload.get('address') == address:
            account_hashes.add(link['hash'])
    for digest in sorted(account_hashes):
        try:
            payload = store.evidence(digest)
            result = payload.get('result') if isinstance(payload, dict) else None
            context = result.get('context') if isinstance(result, dict) else None
            value = result.get('value') if isinstance(result, dict) else None
            if (payload.get('method') != 'getAccountInfo' or payload.get('address') != address
                    or not isinstance(context, dict) or type(context.get('slot')) is not int
                    or context['slot'] < 0
                    or not isinstance(value, dict) or type(value.get('executable')) is not bool):
                raise EvidenceError('Identity account alternative is unresolved')
            try:
                validate_address(value.get('owner'))
            except ValueError:
                raise EvidenceError('Identity account owner is malformed') from None
            accounts.append((context['slot'], value.get('owner'), value['executable'], digest))
        except (EvidenceError, AttributeError):
            return {'state': 'UNKNOWN', 'reason': 'A still-linked account identity alternative is unavailable or unresolved.', 'evidence': sorted(account_hashes)}
    if accounts:
        from .discovery import SYSTEM_PROGRAM
        latest_slot = max(row[0] for row in accounts)
        latest = [row for row in accounts if row[0] == latest_slot]
        facts = {(row[1], row[2]) for row in latest}
        if len(facts) != 1:
            return {'state': 'UNKNOWN', 'reason': 'Account identity observations contradict each other at the same slot.', 'evidence': [row[3] for row in latest]}
        if next(iter(facts)) != (SYSTEM_PROGRAM, False):
            return {'state': 'FAIL', 'reason': 'Latest account evidence excludes a non-executable system wallet.', 'evidence': [row[3] for row in latest]}
    for cohort in cohorts:
        combined = deepcopy(cohort)
        combined['evidence'] = links
        if accounts:
            latest_hash = sorted(row[3] for row in latest)[0]
            older = {row[3] for row in accounts if row[0] < latest_slot}
            # All alternatives were read above. A dated older current-account
            # snapshot is disjoint from the latest current-type question; its
            # original hash stays cited in the returned receipt.
            combined['evidence'] = [row for row in links if row.get('hash') not in older]
            combined['evidence'].append({'kind': 'wallet-account-info', 'hash': latest_hash})
            for candidate in combined.get('candidates', []):
                if candidate.get('address') == address:
                    candidate.setdefault('validation', {})['account_evidence_hash'] = latest_hash
                    candidate['evidence'] = list(dict.fromkeys([h for h in candidate.get('evidence', []) if h not in older] + [latest_hash]))
        plan = plan_candidate_audits(store, combined)
        rows.extend(r for r in plan['research_order'] if r.get('address') == address)
    passed = next((r for r in rows if r['identity_state'] == 'PASS'), None)
    if passed:
        return {'state': 'PASS', 'reason': 'Saved native signer, token movement and system account sources agree.',
                'evidence': list(dict.fromkeys(passed['evidence'] + [row[3] for row in accounts]))}
    return {'state': 'UNKNOWN', 'reason': 'Native signer and current system account evidence must be checked.', 'evidence': []}


async def check_cohort_identity(store, cohort, addresses):
    from .observer import PublicRPC
    from .discovery import _native_signers, _public_address, SYSTEM_PROGRAM
    checked = []
    async with PublicRPC(store, max_requests=7 * len(addresses)) as native:
        for address in addresses:
            candidate = next(c for c in cohort['candidates'] if c['address'] == address)
            previous_validation = deepcopy(candidate['validation']) if isinstance(candidate.get('validation'), dict) else {}
            previous_status = candidate.get('status')
            account_observed, attempt_state, provider_stop = False, 'unresolved', None
            candidate['validation'] = {'identity_verified': False}
            candidate.update(status='unresolved', reason='No supported native signer movement has been found in this bounded check.')
            try:
                sampled = [row.get('signature') for row in candidate.get('sampled_activity', []) if isinstance(row, dict) and isinstance(row.get('signature'), str)]
                signatures = ([{'signature': signature} for signature in list(dict.fromkeys(sampled))[:5]]
                              if cohort.get('source') != 'user-list' and sampled else
                              await native.rpc('getSignaturesForAddress', [address, {'limit': 5, 'commitment': 'finalized'}]))
                if not isinstance(signatures, list):
                    raise ProviderError('Malformed public signature sample')
                for row in signatures[:5]:
                    if not isinstance(row, dict) or not isinstance(row.get('signature'), str):
                        continue
                    signature = row['signature']
                    capture = await native.rpc_capture('getTransaction', [signature, {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
                    raw = capture.result
                    flows, reason = _native_signers(raw, signature)
                    # A new body for the previously selected transaction is an
                    # identity dependency even when its new schema/facts reject.
                    # Other unsuccessful samples do not establish activity and
                    # cannot become a historical-population prerequisite.
                    if address in flows or signature == previous_validation.get('signature'):
                        digest = store.archive(raw)
                        candidate['evidence'] = list(dict.fromkeys(candidate.get('evidence', []) + [digest]))
                        link = {'kind': 'transaction', 'signature': signature, 'hash': digest}
                        if link not in cohort.setdefault('evidence', []):
                            cohort['evidence'].append(link)
                    if reason or address not in flows:
                        continue
                    digest = store.archive(raw)
                    store.put('transactions', signature, {'signature': signature, 'raw': raw, 'evidence_hash': digest})
                    account = await native.rpc('getAccountInfo', [address, {'encoding': 'jsonParsed', 'commitment': 'finalized', 'minContextSlot': raw['slot']}])
                    account_hash = store.archive({'method': 'getAccountInfo', 'address': address, 'commitment': 'finalized', 'observed_at': now(), 'result': account})
                    account_observed = True
                    value = account.get('value') if isinstance(account, dict) else None
                    context = account.get('context') if isinstance(account, dict) else None
                    account_known = (isinstance(value, dict) and _public_address(value.get('owner')) and type(value.get('executable')) is bool
                                     and isinstance(context, dict) and type(context.get('slot')) is int and context['slot'] >= raw['slot'])
                    verified = account_known and value['owner'] == SYSTEM_PROGRAM and value['executable'] is False
                    excluded = account_known and not verified
                    attempt_state = 'verified' if verified else 'excluded' if excluded else 'unresolved'
                    candidate.update(status='candidate' if verified else 'rejected' if excluded else 'unresolved',
                                     reason='Native signer with owned token movement and current system account checked.' if verified else
                                            'Observed current account is executable or program-owned and is excluded.' if excluded else
                                            'Current account identity evidence is incomplete or unresolved.',
                                     evidence=list(dict.fromkeys(candidate.get('evidence', []) + [digest, account_hash])))
                    candidate['validation'] = {'identity_verified': verified, 'account_type': 'system-owned signer' if verified else 'unresolved',
                                               'signature': signature, 'economic_signers': list(flows), 'token_flows': flows[address],
                                               'transaction_evidence_hash': digest, 'account_evidence_hash': account_hash}
                    cohort.setdefault('evidence', []).extend([{'kind': 'transaction', 'signature': signature, 'hash': digest},
                                                             {'kind': 'wallet-account-info', 'hash': account_hash}])
                    # Raw HTTP bodies remain independent provenance, not a population certificate.
                    store.archive({'kind': 'identity-rpc-capture', 'request_base64': base64.b64encode(capture.request_bytes).decode(),
                                   'response_base64': base64.b64encode(capture.response_bytes).decode(), 'observed_at': now(), 'transaction_hash': digest})
                    break
            except (ProviderError, QuotaExceeded) as error:
                candidate['reason'] = str(error)
                attempt_state = 'interrupted'
                provider_stop = _provider_stop(error)
            attempt_reason = candidate['reason']
            retained = not account_observed and previous_status == 'candidate' and previous_validation.get('identity_verified') is True
            if retained:
                candidate.update(status=previous_status, validation=previous_validation,
                                 reason=f'Identity recheck did not establish a new result: {attempt_reason}. Prior dated identity evidence is retained.')
            candidate['identity_recheck'] = {'state': attempt_state, 'reason': attempt_reason, 'observed_at': now(),
                                           'prior_evidence_retained': retained, 'provider_stop': provider_stop}
            checked.append({'address': address, 'status': candidate['status'], 'reason': candidate['reason']})
            store.put('discovery_cohorts', cohort['id'], cohort)
    return checked


class PublicSampleRPC:
    """Durable conservative attempts shared by collection and mint-risk reads.

    The frozen wallet allowance never replenishes when this client is recreated.
    An explicit continuation updates the checkpoint allowance. Each attempted
    read is charged before delegation, including failures and interruptions; the
    native client separately enforces the shared 1,000-request daily ceiling.
    """

    def __init__(self, store, scan_id, address, max_requests=50, **kwargs):
        from .observer import PublicRPC
        if type(max_requests) is not int or not 1 <= max_requests <= 20000:
            raise ValueError('Sample request allowance must be between 1 and 20000')
        self.store, self.key = store, scan_id + ':' + address
        self.requests = self.credits = 0
        self._initialize(max_requests)
        self.native = PublicRPC(store, cap=1000, max_requests=1000, **kwargs)

    @staticmethod
    def _empty():
        return {'transactions': [], 'evidence': [], 'pending': [], 'before': None,
                'pages': 0, 'credits': 0, 'terminal': False}

    def _read(self):
        cp = self.store.get('public_sample_checkpoints', self.key, self._empty())
        if not isinstance(cp, dict):
            raise ProviderError('Public sample checkpoint is malformed; restore its original budget')
        for key in ('credits', 'requests_used'):
            if key in cp and (type(cp[key]) is not int or cp[key] < 0):
                raise ProviderError('Public sample request accounting is malformed; restore its original budget')
        return cp

    def _initialize(self, max_requests):
        with self.store.lock:
            cp = self._read()
            limit = cp.setdefault('tranche_request_limit', max_requests)
            if type(limit) is not int or not 1 <= limit <= 20000:
                raise ProviderError('Public sample allowance is malformed; restore its original budget')
            retained = max(cp.get('credits', 0), cp.get('requests_used', 0))
            ledger = self.store.usage('public-wallet-sample', self.key, limit)
            spent = ledger['used'] + ledger['reserved']
            # Older samples recorded successful calls without an independent
            # attempt ledger. Preserve that minimum rather than resetting it.
            if retained > spent and retained <= limit:
                reservation = self.store.reserve('public-wallet-sample', 'retained-attempt-accounting', retained - spent, self.key, limit)
                self.store.dispatch(reservation)
                self.store.settle(reservation, charge=True)
                spent = retained
            cp['requests_used'] = cp['credits'] = max(retained, spent)
            self.requests = self.credits = cp['requests_used']
            self.store.put('public_sample_checkpoints', self.key, cp)

    def _reserve_attempt(self, method):
        with self.store.lock:
            cp = self._read()
            limit = cp['tranche_request_limit']
            ledger = self.store.usage('public-wallet-sample', self.key, limit)
            spent = max(cp.get('requests_used', 0), cp.get('credits', 0), ledger['used'] + ledger['reserved'])
            if spent >= limit:
                raise QuotaExceeded('Public sample request tranche exhausted; explicit budgeted continuation is required')
            reservation = self.store.reserve('public-wallet-sample', method, 1, self.key, limit)
            # This is an application attempt reservation, not a claim that the
            # upstream request executed. Charge before any possible dispatch.
            self.store.dispatch(reservation)
            self.store.settle(reservation, charge=True)
            ledger = self.store.usage('public-wallet-sample', self.key, limit)
            cp['requests_used'] = cp['credits'] = max(spent + 1, ledger['used'] + ledger['reserved'])
            self.requests = self.credits = cp['requests_used']
            self.store.put('public_sample_checkpoints', self.key, cp)

    async def __aenter__(self):
        await self.native.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.native.__aexit__(*args)

    async def close(self):
        await self.native.close()

    async def rpc(self, method, params=None):
        self._reserve_attempt(method)
        return await self.native.rpc(method, params)

    async def rpc_capture(self, method, params=None):
        self._reserve_attempt(method)
        return await self.native.rpc_capture(method, params)


async def collect_public_sample(store, scan, build_report, should_pause):
    """Continue a wallet-address sample without implying complete account ownership."""
    totals = {'transactions': 0, 'pages': 0, 'credits': 0}
    all_terminal, owner_paused, stops, processed = True, False, [], 0
    targets = scan.get('public_sample_targets', scan['audit_addresses'])
    for address in targets:
        if should_pause():
            owner_paused, all_terminal = True, False
            break
        key = scan['id'] + ':' + address
        cp = store.get('public_sample_checkpoints', key, PublicSampleRPC._empty())
        stop = 'Transaction tranche exhausted; more wallet-address history may be collected.'
        provider_stop = None
        try:
            async with PublicSampleRPC(store, scan['id'], address, max_requests=scan['limits']['wallet_credit_limit']) as native:
                cp = store.get('public_sample_checkpoints', key)
                while len(cp['transactions']) < scan['limits']['transaction_limit'] and not cp['terminal']:
                    if should_pause():
                        owner_paused = True
                        stop = 'Paused by owner; durable sample checkpoint retained.'
                        break
                    if not cp['pending']:
                        options = {'limit': min(20, scan['limits']['transaction_limit'] - len(cp['transactions'])), 'commitment': 'finalized'}
                        if cp['before']:
                            options['before'] = cp['before']
                        rows = await native.rpc('getSignaturesForAddress', [address, options])
                        cp = store.get('public_sample_checkpoints', key)
                        if not isinstance(rows, list):
                            raise ProviderError('Malformed public signature page')
                        cp['pages'] += 1
                        digest = store.archive({'method': 'getSignaturesForAddress', 'address': address, 'options': options, 'result': rows, 'observed_at': now()})
                        cp['evidence'].append({'kind': 'signature-page', 'hash': digest})
                        if not rows:
                            cp['terminal'] = True
                            stop = 'Public wallet-address query ended; historical owned-account population remains unknown.'
                        else:
                            cp['pending'] = [r['signature'] for r in rows if isinstance(r, dict) and isinstance(r.get('signature'), str)]
                            if not cp['pending']:
                                raise ProviderError('Public signature page has no usable identities')
                            cp['before'] = cp['pending'][-1]
                        store.put('public_sample_checkpoints', key, cp)
                        continue
                    signature = cp['pending'][0]
                    raw = await native.rpc('getTransaction', [signature, {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
                    cp = store.get('public_sample_checkpoints', key)
                    digest = store.archive(raw)
                    record = {'signature': signature, 'raw': raw, 'evidence_hash': digest}
                    if not any(r['signature'] == signature for r in cp['transactions']):
                        cp['transactions'].append(record)
                        cp['evidence'].append({'kind': 'transaction', 'signature': signature, 'hash': digest})
                        store.put('transactions', signature, record)
                    cp['pending'].pop(0)
                    store.put('public_sample_checkpoints', key, cp)
        except (ProviderError, QuotaExceeded) as error:
            stop = str(error)
            provider_stop = _provider_stop(error)
            cp = store.get('public_sample_checkpoints', key, cp)
        cp['stop_reason'] = stop
        cp['provider_stop'] = provider_stop
        if provider_stop is not None:
            cp.setdefault('interruptions', []).append(deepcopy(provider_stop))
        store.put('public_sample_checkpoints', key, cp)
        collected = {'transactions': cp['transactions'], 'evidence': cp['evidence'], 'checkpoint': {},
                     'coverage': {'collection_stop_reason': stop, 'scope': 'Bounded finalized wallet-address signature sample; no exhaustive token-account history.',
                                  'transactions': len(cp['transactions']), 'pages': cp['pages'], 'credits': cp['credits'],
                                  'requests_used': cp.get('requests_used', cp['credits']), 'tranche_request_limit': cp.get('tranche_request_limit'),
                                  'provider_stop': deepcopy(provider_stop), 'interruptions': deepcopy(cp.get('interruptions', [])),
                                  'history_scope_complete': False, 'historical_ownership_verified': False}}
        if cp['transactions']:
            await build_report(scan, address, collected)
        if should_pause():
            owner_paused = True
        cp = store.get('public_sample_checkpoints', key, cp)
        all_terminal = all_terminal and bool(cp['terminal'])
        stops.append(stop)
        totals['transactions'] += len(cp['transactions'])
        totals['pages'] += cp['pages']
        totals['credits'] += cp['credits']
        processed += 1
        if owner_paused:
            all_terminal = False
            break
    scan.update(status='completed' if all_terminal and not owner_paused else 'paused',
                reason='Paused by owner; durable sample checkpoints retained.' if owner_paused else '; '.join(dict.fromkeys(stops)),
                stage='Sample assessment ready')
    scan['progress'].update(totals)
    scan['progress'].update(wallets_completed=processed, wallets_total=len(scan['audit_addresses']))
    store.put('scans', scan['id'], scan)


def install_research_routes(app, store, body, observer, *, build_report, queue_scan, wake, research_busy, settings, preset):
    def assessment(identifier):
        result = store.get('screenings', identifier)
        if result is None:
            raise HTTPException(404, 'Screening not found')
        return screening_view(store, result)

    @app.post('/api/discovery/{identifier}/identity')
    async def identity(identifier: str, request: Request):
        cohort = store.get('discovery_cohorts', identifier)
        if cohort is None:
            raise HTTPException(404, 'Discovery cohort not found')
        data = await body(request)
        if set(data) - {'addresses'}:
            raise ValueError('Unknown identity option')
        addresses = data.get('addresses', [c['address'] for c in cohort['candidates']][:settings()['limits']['deep_audit_cap']])
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= settings()['limits']['deep_audit_cap']:
            raise ValueError('Choose a bounded set of 1–5 wallets')
        addresses = list(dict.fromkeys(validate_address(a) for a in addresses))
        if any(not any(c['address'] == a for c in cohort['candidates']) for a in addresses):
            raise ValueError('Address is not in this cohort')
        return {'checked': await check_cohort_identity(store, cohort, addresses)}

    @app.post('/api/screenings')
    async def screen(request: Request):
        from .screening import build_screening
        data = await body(request)
        if set(data) - {'report_id', 'preset'} or 'report_id' not in data:
            raise ValueError('Screening requires a saved report and optional screening preset')
        report = store.get('reports', data['report_id'])
        if report is None:
            raise HTTPException(404, 'Report not found')
        frozen = build_screening(report, data.get('preset'), saved_identity(store, report['address']))
        frozen['collection']['provider_stop'] = deepcopy(report.get('coverage', {}).get('provider_stop'))
        frozen['collection']['interruptions'] = deepcopy(report.get('coverage', {}).get('interruptions', []))
        frozen.update(id=uuid.uuid4().hex, created_at=now(), source=report.get('source'), report_input_hash=report.get('collection_input_hash'))
        source_scan = store.get('scans', report.get('scan_id'))
        sample_cp = store.get('public_sample_checkpoints', report.get('scan_id', '') + ':' + report['address'], {})
        if not source_scan or source_scan.get('source') != 'live' or sample_cp.get('terminal'):
            frozen['continuation'].update(recommended=False, action='inspect_scope',
                reason='This wallet-address sample has ended or has no live checkpoint. Missing historical ownership needs different primary evidence; more of this query cannot establish it.')
        missing = []
        for link in report.get('evidence', []):
            try:
                store.evidence(link.get('hash'))
            except (EvidenceError, AttributeError):
                missing.append(link.get('hash') if isinstance(link, dict) else None)
        frozen['source_availability'] = {'state': 'UNKNOWN' if missing else 'PASS', 'missing': missing}
        if missing and frozen['result'] == 'worth_observing':
            frozen.update(result='insufficient_evidence', label='Insufficient evidence', reason='Required archived sources are unavailable.')
        store.put('screenings', frozen['id'], frozen)
        return screening_view(store, frozen)

    @app.get('/api/screenings')
    async def screenings():
        return screening_views(store)

    @app.get('/api/screenings/{identifier}')
    async def screening(identifier: str):
        return assessment(identifier)

    @app.get('/api/screenings/{identifier}/export')
    async def screening_export(identifier: str):
        return Response(json.dumps(assessment(identifier), indent=2), media_type='application/json',
                        headers={'Content-Disposition': f'attachment; filename="screening-{identifier}.json"'})

    @app.post('/api/screenings/{identifier}/continue')
    async def continue_screening(identifier: str, request: Request):
        selected = assessment(identifier)
        data = await body(request)
        if set(data) - {'transaction_limit'}:
            raise ValueError('Unknown continuation budget')
        tranche = data.get('transaction_limit', 20)
        continuation_budget = selected['continuation']['budget']
        maximum = min(100, continuation_budget['max_transactions'])
        if type(tranche) is not int or not 1 <= tranche <= maximum:
            raise ValueError(f'Continuation tranche must be 1–{maximum} transactions under this saved preset')
        report = store.get('reports', selected['report_id'])
        scan = store.get('scans', report.get('scan_id')) if report else None
        if not scan or scan.get('source') != 'live':
            raise HTTPException(409, 'This report has no live collection checkpoint; investigate the checked wallet to collect another sample.')
        if research_busy():
            raise HTTPException(409, 'Wait for the active bounded investigation')
        if scan.get('budget_mode') != 'public-sample':
            raise HTTPException(409, 'Continue this provider investigation using its saved scan Resume action.')
        if saved_identity(store, report['address'])['state'] != 'PASS':
            raise HTTPException(409, 'Restore native identity sources before continuing')
        cp = store.get('public_sample_checkpoints', scan['id'] + ':' + report['address'])
        if not cp or cp.get('terminal'):
            raise HTTPException(409, 'No remaining sample checkpoint is available')
        if len(cp['transactions']) + tranche > settings()['limits']['transaction_limit']:
            raise ValueError('Continuation exceeds the configured transaction cap')
        scan['limits']['transaction_limit'] = len(cp['transactions']) + tranche
        scan['public_sample_targets'] = [report['address']]
        requests = min(100, continuation_budget['max_credits'])
        cp['tranche_request_limit'] = cp.get('tranche_request_limit', scan['limits']['wallet_credit_limit']) + requests
        store.put('public_sample_checkpoints', scan['id'] + ':' + report['address'], cp)
        scan['limits']['wallet_credit_limit'] = cp['tranche_request_limit']
        scan.update(status='queued', reason=f'Continue for at most {tranche} transactions; public request cap remains enforced.')
        store.put('scans', scan['id'], scan)
        wake.set()
        return {'scan_id': scan['id']}

    @app.get('/api/observations')
    async def observations():
        from .paper import list_runs
        return [observation_view(store, run) for run in list_runs(store)]

    @app.post('/api/observations')
    async def start_observation(request: Request):
        from .paper import create_run, stop_run
        data = await body(request)
        if set(data) - {'screening_id', 'settings'} or 'screening_id' not in data:
            raise ValueError('Select a saved screening and paper settings')
        selected = assessment(data['screening_id'])
        if not selected['current_eligibility']['can_start_observation']:
            raise HTTPException(409, selected['current_eligibility']['reason'])
        if saved_identity(store, selected['address'])['state'] != 'PASS':
            raise HTTPException(409, 'Native identity evidence must be checked before forward observation')
        if selected['result'] == 'excluded_by_preset':
            raise HTTPException(409, 'This screening is excluded under its preset; inspect the evidence before starting another assessment.')
        if sum(r.get('status') == 'running' for r in store.list('paper_runs')) >= settings()['limits']['deep_audit_cap']:
            raise HTTPException(409, 'Active observation cap reached')
        if any(r.get('address') == selected['address'] and r.get('status') == 'running' for r in store.list('paper_runs')):
            raise HTTPException(409, 'This wallet already has an active observation')
        run = create_run(store, selected['address'], data.get('settings', {}), screening_id=selected['id'])
        try:
            await observer.start(run['id'])
        except Exception:
            stop_run(store, run['id'], reason='Observer could not start; no copied outcome established.')
            raise HTTPException(409, 'Observer could not start; inspect monitoring availability') from None
        return observation_view(store, run)

    @app.get('/api/observations/{identifier}')
    async def observation(identifier: str):
        from .paper import get_run
        run = get_run(store, identifier)
        if run is None:
            raise HTTPException(404, 'Observation not found')
        return observation_view(store, run)

    @app.post('/api/observations/{identifier}/stop')
    async def stop_observation(identifier: str):
        from .paper import stop_run
        await observer.stop(identifier)
        return observation_view(store, stop_run(store, identifier))

    @app.post('/api/observations/{identifier}/resume')
    async def resume_observation(identifier: str):
        from .paper import get_run, resume_run, pause_run
        previous = get_run(store, identifier)
        if not previous or saved_identity(store, previous['address'])['state'] != 'PASS':
            raise HTTPException(409, 'Restore native identity evidence before resuming')
        if sum(r.get('status') == 'running' for r in store.list('paper_runs')) >= settings()['limits']['deep_audit_cap']:
            raise HTTPException(409, 'Active observation cap reached')
        run = resume_run(store, identifier)
        try:
            await observer.start(identifier)
        except Exception:
            pause_run(store, identifier, reason='Observer could not resume; original budgets and exposure retained.')
            raise HTTPException(409, 'Observation cannot resume under its original monitoring budget; inspect the saved reason.') from None
        return observation_view(store, run)

    @app.post('/api/observations/{identifier}/mark')
    async def mark_observation(identifier: str):
        await observer.mark(identifier)
        from .paper import get_run
        return observation_view(store, get_run(store, identifier))

    @app.get('/api/observations/{identifier}/export')
    async def observation_export(identifier: str):
        from .paper import export_run
        exported = export_run(store, identifier)
        exported['run'] = observation_view(store, exported['run'])
        return Response(json.dumps(exported, indent=2), media_type='application/json',
                        headers={'Content-Disposition': f'attachment; filename="observation-{identifier}.json"'})
