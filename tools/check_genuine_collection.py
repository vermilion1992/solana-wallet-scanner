#!/usr/bin/env python3
"""Replay acquired raw inputs through the normal app, with a frozen raw oracle.

Offline only. Indexed query completeness, observed arithmetic and genuine
whole-wallet acceptance are separate conclusions. Selected records cannot close
B3; a future accepted population contract and independently worked expectations
are required for that conclusion.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key in oracle input')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def _utc(value):
    if type(value) is int:
        return datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, str):
        raise ValueError('Oracle timestamp is not an exact integer or ISO time')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Oracle timestamp is missing timezone')
    return result.astimezone(timezone.utc)


def _sol(lamports):
    value = format(Decimal(lamports) / Decimal(10**9), 'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def pack_collection(directories, address, window):
    """Checksum raw collection bytes and pack them without a provider dispatch."""
    from scanner.indexed_input import pack_indexed_bytes
    manifest = {'version': 'indexed-wallet-input-v1', 'address': address,
                'window': window, 'pages': [], 'transactions': []}
    payloads, acquisition = {}, []
    for directory in directories:
        directory = Path(directory).resolve(strict=True)
        receipt_bytes = (directory / 'result.json').read_bytes()
        receipt = _json(receipt_bytes)
        if receipt.get('kind') != 'authorised-bounded-native-collection':
            raise ValueError('Unsupported acquisition receipt')
        rows = receipt.get('requests')
        if not isinstance(rows, list):
            raise ValueError('Acquisition request list is missing')
        included_sources, auxiliary_sources = [], []
        for row in rows:
            if not isinstance(row, dict) or row.get('state') != 'OBSERVED':
                continue
            request_path, response_path = row.get('request_path'), row.get('response_path')
            pair = []
            for name in (request_path, response_path):
                if not isinstance(name, str) or Path(name).name != name:
                    raise ValueError('Acquisition artifact must be a confined filename')
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError('Acquisition artifact must be a regular local file')
                raw = path.read_bytes()
                artifact = receipt.get('artifacts', {}).get(name)
                if not isinstance(artifact, dict) or artifact.get('sha256') != digest(raw) or artifact.get('bytes') != len(raw):
                    raise ValueError('Acquisition artifact receipt disagrees with exact bytes')
                pair.append(raw)
            request_raw, compressed = pair
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                response_raw = stream.read(32 * 1024 * 1024 + 1)
            if (len(response_raw) > 32 * 1024 * 1024 or digest(request_raw) != row.get('request_sha256')
                    or digest(response_raw) != row.get('response_sha256')):
                raise ValueError('Raw acquisition request/response checksum disagrees')
            if row.get('credential_redaction_applied') is True:
                raise ValueError('Modified reflected-credential bytes are not original acquisition evidence')
            request = _json(request_raw)
            if row.get('method') in ('publicTrendingPools', 'publicPoolTrades'):
                _validate_public_descriptor(request, row)
                auxiliary_sources.append({'method': row['method'], 'request_hash': digest(request_raw),
                    'response_hash': digest(response_raw), 'source_url': request['url'],
                    'scope': 'Exact public acquisition bytes remain in the original collection directory; not financial or population evidence.'})
                continue
            if request.get('method') != row.get('method'):
                raise ValueError('Acquisition method disagrees with frozen request')
            link = {'request_hash': digest(request_raw), 'response_hash': digest(response_raw)}
            method = request['method']
            if method == 'getTransactionsForAddress' and request['params'][1].get('transactionDetails') == 'full':
                if request['params'][0] != address:
                    raise ValueError('Indexed collection wallet disagrees with requested report')
                manifest['pages'].append(link)
            elif method == 'getTransaction':
                manifest['transactions'].append({'signature': request['params'][0], **link})
            else:
                # Other acquired observations remain preserved in the collection
                # directory; this indexed input schema cannot reinterpret them.
                continue
            payloads[link['request_hash']] = request_raw
            payloads[link['response_hash']] = response_raw
            included_sources.append(link)
        acquisition.append({'receipt_sha256': digest(receipt_bytes), 'kind': receipt['kind'],
                            'state': receipt.get('state'), 'plan_sha256': receipt.get('plan_sha256'),
                            'provider_requests': receipt.get('provider_requests'),
                            'included_raw_sources': included_sources,
                            'auxiliary_raw_sources': auxiliary_sources,
                            'scope': 'Acquisition provenance; does not prove historical population.'})
    return pack_indexed_bytes(manifest, payloads), acquisition


def _validate_public_descriptor(request, receipt):
    """Validate exact read-only public descriptors without financial admission."""
    if (not isinstance(request, dict) or set(request) != {'method', 'url', 'query'}
            or request['method'] != 'GET' or not isinstance(request['url'], str)
            or request['url'] != receipt.get('source_url')
            or not isinstance(request['query'], dict)):
        raise ValueError('Public acquisition request descriptor disagrees with exact read-only receipt')
    prefix = 'https://api.geckoterminal.com/api/v2/networks/solana/'
    if receipt['method'] == 'publicTrendingPools':
        if (request['url'] != prefix + 'trending_pools' or request['query'] != {'page': 1}
                or type(request['query'].get('page')) is not int):
            raise ValueError('Public trending acquisition is outside the fixed Solana route')
    elif (not re.fullmatch(re.escape(prefix) + r'pools/[1-9A-HJ-NP-Za-km-z]{32,44}/trades', request['url'])
            or request['query'] != {}):
        raise ValueError('Public trade acquisition is outside the fixed Solana route')


def freeze_expectations(content):
    """Work selected fee arithmetic directly from raw integers before app use.

This function deliberately imports no scanner decoder/accounting/metric helper.
Conflicting alternatives, unavailable links and uncertain nonzero fee placement
remain unknown. Token endpoints are recorded as observations, never free basis.
"""
    if not isinstance(content, bytes) or len(content) > 20 * 1024 * 1024:
        raise ValueError('Oracle input exceeds the application upload bound')
    records, gaps, raw_hashes, total = [], [], {}, 0
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) > 20513 or len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Duplicate ZIP entries or missing manifest')
        for entry in archive.infolist():
            if entry.flag_bits & 1 or entry.file_size > 24 * 1024 * 1024:
                raise ValueError('Encrypted or oversized oracle ZIP input')
        if archive.getinfo('manifest.json').file_size > 4 * 1024 * 1024:
            raise ValueError('Oversized oracle manifest')
        manifest_raw = archive.read('manifest.json')
        manifest = _json(manifest_raw)
        if manifest.get('version') != 'indexed-wallet-input-v1':
            raise ValueError('This oracle requires exact indexed raw input bytes')
        wallet = manifest['address']
        start, end = _utc(manifest['window']['start']), _utc(manifest['window']['end'])
        for row in manifest['pages'] + manifest.get('transactions', []):
            request_hash, response_hash = row['request_hash'], row['response_hash']
            try:
                request_raw = archive.read(f'raw/{request_hash}.json')
                response_raw = archive.read(f'raw/{response_hash}.json')
            except KeyError:
                gaps.append('Required linked raw request/response bytes missing')
                continue
            if digest(request_raw) != request_hash or digest(response_raw) != response_hash:
                raise ValueError('Oracle raw input checksum disagreement')
            total += len(request_raw) + len(response_raw)
            if total > 256 * 1024 * 1024:
                raise ValueError('Expanded oracle input exceeds the application bound')
            raw_hashes[request_hash] = len(request_raw)
            raw_hashes[response_hash] = len(response_raw)
            request, response = _json(request_raw), _json(response_raw)
            if request.get('id') != response.get('id') or type(request.get('id')) is not type(response.get('id')) or 'error' in response:
                gaps.append('Raw RPC response identity/outcome disagreement')
                continue
            if request.get('method') == 'getTransactionsForAddress':
                rows = response.get('result', {}).get('data')
                if not isinstance(rows, list):
                    gaps.append('Raw indexed record population is malformed')
                    continue
            elif request.get('method') == 'getTransaction':
                rows = [response.get('result')]
            else:
                gaps.append('Raw response method is not an indexed/native record source')
                continue
            records += [{'raw': raw, 'response_hash': response_hash, 'ordinal': ordinal}
                        for ordinal, raw in enumerate(rows)]
    groups = defaultdict(list)
    for item in records:
        raw = item['raw']
        try:
            signature = raw['transaction']['signatures'][0]
            if not isinstance(signature, str) or not signature:
                raise ValueError('Missing signature')
            groups[signature].append(item)
        except (TypeError, KeyError, IndexError, ValueError):
            gaps.append('A raw record lacks identifiable transaction identity')
    observations, fees = [], 0
    for signature, sources in sorted(groups.items()):
        facts = []
        for item in sources:
            raw = item['raw']
            try:
                keys = raw['transaction']['message']['accountKeys']
                payer = keys[0]['pubkey'] if isinstance(keys[0], dict) else keys[0]
                fee = raw['meta']['fee']
                if not isinstance(payer, str) or type(fee) is not int or fee < 0:
                    raise ValueError('Malformed fee/payer')
                if raw.get('version', 'legacy') not in ('legacy', 0) or type(raw.get('version', 'legacy')) is bool:
                    raise ValueError('Record format lacks the current reviewed fee interpretation')
                wallet_fee = fee if payer == wallet else 0
                when = _utc(raw.get('blockTime')) if wallet_fee else None
                member = start <= when < end if when is not None else None
                facts.append((wallet_fee, member))
                observations.append({'signature': signature, 'response_hash': item['response_hash'],
                    'ordinal': item['ordinal'], 'payer': payer, 'fee_lamports': fee,
                    'wallet_paid_fee_lamports': wallet_fee, 'in_report_window': member,
                    'failed': raw['meta'].get('err') is not None,
                    'pre_token_balances': deepcopy(raw['meta'].get('preTokenBalances')),
                    'post_token_balances': deepcopy(raw['meta'].get('postTokenBalances')),
                    'scope': 'Raw endpoint observation; token quantities do not establish cost basis.'})
            except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError):
                gaps.append(f'{signature}: raw selected fee facts/placement unsupported or unavailable')
        if len(facts) != len(sources) or len(set(facts)) != 1:
            gaps.append(f'{signature}: linked fee/payer/window facts unresolved or conflicting')
        elif facts[0][1] is True:
            fees += facts[0][0]
    expected = {'value': None if gaps else _sol(fees), 'status': 'unknown' if gaps else 'known',
                'lamports': fees if not gaps else None,
                'scope': 'Explicit selected raw record set in the half-open report window; not wallet profit',
                'reason': '; '.join(sorted(set(gaps))) if gaps else None}
    return {'version': 'genuine-collection-raw-expectations-v1', 'archive_sha256': digest(content),
            'manifest_sha256': digest(manifest_raw), 'address': wallet, 'window': manifest['window'],
            'raw_input_hashes': raw_hashes, 'unique_signatures': len(groups), 'raw_records': len(records),
            'observed_network_fees_sol': expected, 'raw_observations': observations,
            'oracle': 'Direct raw integer meta.fee addition, payer equality and independently parsed UTC bounds; no production metric calls.',
            'wallet_profit_expectation': 'Not inferred from selected records or endpoint balance changes.'}


def load_input_freeze(path, content):
    """Recover provenance for an existing frozen ZIP without repacking bytes."""
    value = _json(Path(path).read_bytes())
    if (not isinstance(value, dict) or value.get('kind') != 'offline-genuine-checker-input-freeze'
            or value.get('archive_sha256') != digest(content) or value.get('bytes') != len(content)
            or not isinstance(value.get('acquisition'), list) or not value['acquisition']):
        raise ValueError('Frozen acquisition identity disagrees with existing indexed input')
    available = set(freeze_expectations(content)['raw_input_hashes'])
    covered = set()
    for receipt in value['acquisition']:
        if not isinstance(receipt, dict) or receipt.get('kind') != 'authorised-bounded-native-collection':
            raise ValueError('Frozen acquisition receipt kind is unsupported')
        links = receipt.get('included_raw_sources')
        if not isinstance(links, list):
            raise ValueError('Frozen acquisition raw links are absent')
        for link in links:
            if not isinstance(link, dict) or set(link) != {'request_hash', 'response_hash'}:
                raise ValueError('Frozen acquisition raw link is malformed')
            for identifier in link.values():
                if not isinstance(identifier, str) or identifier not in available:
                    raise ValueError('Frozen acquisition references absent raw input')
                covered.add(identifier)
    if covered != available:
        raise ValueError('Frozen acquisition does not bind every exact indexed raw input')
    return deepcopy(value['acquisition'])


def _canonical_number(value):
    if (not isinstance(value, str) or len(value) > 512 or value == '-0'
            or not re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d*[1-9])?', value)):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() else None
    except ArithmeticError:
        return None


def _known_number(report, name):
    observation = report.get('metrics', {}).get(name)
    if not isinstance(observation, dict) or observation.get('status') != 'known':
        return None
    return _canonical_number(observation.get('value'))


def _mathematically_inapplicable(report, name, decision):
    """Recognize proved undefined formulas without relaxing source requirements.

    These receipts are engineering acceptance only. The saved metric remains
    UNKNOWN and policy retains its actual MISS/UNRESOLVED result.
    """
    from scanner.metric_evidence import _passing_decision, _passing_dependencies
    observation = report.get('metrics', {}).get(name, {})
    if (not isinstance(decision, dict) or decision.get('state') != 'UNKNOWN'
            or decision.get('unresolved_dependencies') != ['metric_observation']
            or not _passing_dependencies(name, decision)
            or not isinstance(observation, dict) or observation.get('status') != 'unknown'
            or observation.get('value') is not None):
        return None
    decisions = report.get('coverage', {}).get('metric_dependencies', {})
    def supported(other):
        return _passing_decision(other, decisions.get(other))
    formula = observation.get('population')
    if name == 'largest_contribution_pct':
        profit = _known_number(report, 'profit_sol')
        if (formula == 'Highest positive aggregate realised P&L for one mint / positive net period P&L'
                and supported('profit_sol') and profit is not None and profit <= 0):
            return 'Complete supported period net realised profit is nonpositive; the formula requires a positive denominator.'
        return None
    count = _known_number(report, 'completed_positions')
    completed_supported = supported('completed_positions') and count is not None and count >= 0 and count == count.to_integral_value()
    empty_formulas = {
        'median_roi_pct': 'Whole-episode net ROI; strict-zero completed cohort',
        'win_rate_pct': 'Net-positive strict-zero completed episodes / all completed episodes (breakeven included)',
        'median_hold_hours': 'First acquisition to final sale; strict-zero closes inside reporting window',
        'rapid_sale_pct': 'Completed episodes with first positive economic sale within five minutes',
        'avg_buys': 'Buy events per strict-zero completed episode',
        'avg_sells': 'Sale events per strict-zero completed episode',
    }
    if name in empty_formulas and completed_supported and count == 0 and formula == empty_formulas[name]:
        return 'Complete supported strict-zero completed cohort is empty; this mean, median or population ratio is undefined.'
    positions = report.get('positions')
    if not isinstance(positions, list):
        return None
    try:
        basis = [_canonical_number(position['matched_basis_sol']) for position in positions]
        if any(value is None or value < 0 for value in basis):
            return None
    except (ArithmeticError, KeyError, TypeError):
        return None
    if name == 'realised_roi_pct' and formula == 'Period net realised profit / disposed acquisition cost':
        # All rendered cumulative disposed costs being zero proves the bounded
        # subset denominator is zero. Positive out-of-window cost is not used
        # to infer an in-window denominator.
        if (completed_supported and len(positions) >= count and supported('profit_sol')
                and _known_number(report, 'profit_sol') is not None and all(value == 0 for value in basis)):
            return 'Complete supported disposed acquisition costs are zero; the realised ROI denominator is zero.'
    if name == 'median_roi_pct' and formula == empty_formulas[name] and completed_supported and count > 0:
        try:
            start, end = _utc(report['window']['start']), _utc(report['window']['end'])
            cohort = [position for position in positions if position.get('status') == 'closed'
                      and position.get('classification') == 'meme' and position.get('quantity_raw') == '0'
                      and position.get('end') is not None and start <= _utc(position['end']) < end]
        except (KeyError, ValueError, TypeError):
            return None
        if len(cohort) == count and any(_canonical_number(position['matched_basis_sol']) == 0 for position in cohort):
            return 'Complete supported completed cohort contains a zero-cost episode; its required whole-episode ROI is undefined.'
    return None


def real_acceptance(report, acquisition, worked, archive_hash):
    """Inspect actual derived proof, never a blanket real-dataset prohibition."""
    coverage = report.get('coverage', {})
    wallet = coverage.get('wallet_evidence', {})
    population = wallet.get('components', {}).get('historical_population', {})
    decisions = coverage.get('metric_dependencies', {})
    missing = []
    if report.get('source') == 'demo' or not acquisition:
        missing.append('Genuine acquisition provenance is unavailable or dataset is development-only.')
    if population.get('state') != 'PASS':
        missing.append('Accepted historical owned-account/population proof is unresolved.')
    if _known_number(report, 'profit_sol') is None:
        missing.append('A supported realised wallet calculation is not yet known; selected arithmetic is insufficient.')
    required = ('profit_sol', 'realised_roi_pct', 'median_roi_pct', 'win_rate_pct',
                'median_hold_hours', 'completed_positions', 'completed_positions_90d',
                'traded_mints', 'rapid_sale_pct', 'avg_buys', 'avg_sells', 'positive_weeks',
                'largest_contribution_pct', 'economic_pnl_sol')
    inapplicable = []
    from scanner.metric_evidence import _passing_decision
    for metric in required:
        decision = decisions.get(metric)
        if _passing_decision(metric, decision) and _known_number(report, metric) is not None:
            continue
        explanation = _mathematically_inapplicable(report, metric, decision)
        if explanation is not None:
            inapplicable.append({'metric': metric, 'state': 'NOT_APPLICABLE', 'reason': explanation,
                                 'source_dependencies': 'PASS', 'saved_metric_status': 'unknown'})
        else:
            missing.append(f'{metric}: required source dependencies remain unresolved.')
    if (not isinstance(worked, dict) or worked.get('version') != 'genuine-wallet-worked-expectations-v1'
            or worked.get('archive_sha256') != archive_hash or not isinstance(worked.get('calculations'), list)
            or not worked['calculations'] or not isinstance(worked.get('metrics'), dict)):
        missing.append('Separately worked genuine wallet calculations bound to these exact raw inputs are absent.')
    else:
        for metric in required:
            expected = worked['metrics'].get(metric)
            actual = report.get('metrics', {}).get(metric)
            if not isinstance(expected, dict) or not isinstance(actual, dict) or any(actual.get(k) != expected.get(k) for k in ('status', 'value')):
                missing.append(f'{metric}: independently worked expected result does not match the saved report.')
    return {'state': 'BLOCKED' if missing else 'PASS', 'missing': missing, 'mathematically_inapplicable': inapplicable,
            'scope': 'Original wallet-wide evidence requirements; a losing/policy-MISS report is acceptable.'}


def verify_worked_expectations(report, worked, oracle):
    """Compare separately worked scoped results, without upgrading wallet scope."""
    if (not isinstance(worked, dict) or worked.get('version') != 'genuine-wallet-worked-expectations-v1'
            or worked.get('archive_sha256') != oracle['archive_sha256']):
        raise AssertionError('Separately worked expectation identity disagrees with exact raw inputs')
    metrics, query = worked.get('metrics', {}), worked.get('query_accounting', {})
    if not isinstance(metrics, dict) or not isinstance(query, dict) or not (metrics or query):
        raise AssertionError('Separately worked expectations must include supported metric or scoped query results')
    calculations = worked.get('calculations')
    if not isinstance(calculations, list) or not calculations:
        raise AssertionError('Separately worked calculation steps are missing')
    for step in calculations:
        if (not isinstance(step, dict) or not isinstance(step.get('description'), str)
                or not isinstance(step.get('source_hashes'), list) or not step['source_hashes']
                or any(source not in oracle['raw_input_hashes'] for source in step['source_hashes'])):
            raise AssertionError('Worked calculations must retain descriptions and exact available raw source references')
    for name, expected in metrics.items():
        actual = report.get('metrics', {}).get(name)
        if (not isinstance(actual, dict) or not isinstance(expected, dict)
                or any(actual.get(field) != expected.get(field) for field in ('value', 'status'))):
            raise AssertionError('Separately worked metric differs: ' + name)
    actual_query = report.get('coverage', {}).get('wallet_evidence', {}).get('query_accounting', {})
    for name, expected in query.items():
        if not isinstance(actual_query, dict) or actual_query.get(name) != expected:
            raise AssertionError('Separately worked conditional query result differs: ' + name)
    lots = worked.get('supported_selected_lots', [])
    if not isinstance(lots, list):
        raise AssertionError('Worked selected lot expectations are malformed')
    checked_lots = verify_selected_lots(report, lots, oracle)
    return {'case': 'separately-worked-supported-results', 'state': 'PASS',
            'metric_keys': sorted(metrics), 'conditional_query_keys': sorted(query),
            'supported_selected_lots': checked_lots,
            'scope': 'Compared results retain their actual population; query arithmetic cannot certify whole-wallet results.'}


def _fraction(value):
    try:
        if not isinstance(value, dict) or set(value) != {'numerator', 'denominator'}:
            raise ValueError('Expected explicit fraction')
        if any(not isinstance(value[key], str) for key in ('numerator', 'denominator')):
            raise ValueError('Fraction integers must be strings')
        return Fraction(int(value['numerator']), int(value['denominator']))
    except (ValueError, ZeroDivisionError) as exc:
        raise AssertionError('Worked integer/fraction quantity is malformed') from exc


def verify_selected_lots(report, lots, oracle):
    """Check supported selected FIFO lots while retaining incomplete populations.

Expected amounts come from separately worked raw integer calculations. Matching
is by mint and exact acquired/disposed units; classification/status are not
promoted to eligible completed positions by this conditional observation check.
"""
    adapter = report.get('coverage', {}).get('wallet_evidence', {})
    positions = adapter.get('observed_fifo_positions', [])
    supported = adapter.get('query_accounting', {}).get('supported_selected_lots', [])
    if not isinstance(positions, list) or not isinstance(supported, list):
        raise AssertionError('Observed FIFO position interface is unavailable')
    checked = []
    for expected in lots:
        if not isinstance(expected, dict) or not isinstance(expected.get('mint'), str):
            raise AssertionError('Worked selected lot identity is malformed')
        sources = expected.get('source_hashes')
        if (not isinstance(sources, list) or not sources
                or any(source not in oracle['raw_input_hashes'] for source in sources)):
            raise AssertionError('Worked selected lot lacks available original raw sources')
        matches = [p for p in positions if isinstance(p, dict) and p.get('mint') == expected['mint']
                   and p.get('acquired_raw') == expected.get('quantity_acquired_raw')
                   and p.get('sold_raw') == expected.get('quantity_disposed_raw')]
        if len(matches) != 1:
            raise AssertionError('Worked selected lot has missing or ambiguous FIFO counterpart: ' + expected['mint'])
        position = matches[0]
        proofs = [p for p in supported if isinstance(p, dict) and p.get('mint') == expected['mint']
                  and p.get('acquired_raw') == expected.get('quantity_acquired_raw')
                  and p.get('disposed_raw') == expected.get('quantity_disposed_raw')]
        if len(proofs) != 1:
            raise AssertionError('Worked selected lot has missing or ambiguous supported proof: ' + expected['mint'])
        proof = proofs[0]
        if any(proof.get(field) != 'PASS' for field in ('monetary_state', 'timing_state', 'quantity_state')):
            raise AssertionError('Worked selected lot dependency proof is incomplete: ' + expected['mint'])
        if (proof.get('qualification') is not False or proof.get('wallet_population_state') != 'UNKNOWN'
                or proof.get('classification_state') != 'UNKNOWN'):
            raise AssertionError('Conditional selected lot incorrectly promotes population or classification')
        if expected.get('account') is not None and expected['account'] not in proof.get('accounts', []):
            raise AssertionError('Worked selected lot named account differs')
        counterpart_fields = {'remaining_raw': 'quantity_raw', 'buy_count': 'buy_count', 'sell_count': 'sell_count',
                              'conditional_basis_sol': 'basis_sol', 'conditional_matched_basis_sol': 'matched_basis_sol',
                              'conditional_proceeds_sol': 'proceeds_sol', 'conditional_exit_fees_sol': 'exit_fees_sol',
                              'conditional_lot_profit_sol': 'pnl_sol', 'conditional_lot_roi_pct': 'roi_pct',
                              'observed_start': 'start', 'observed_end': 'end', 'conditional_hold_hours': 'hold_hours'}
        for actual, original in counterpart_fields.items():
            if proof.get(actual) != position.get(original):
                raise AssertionError('Supported selected lot differs from its FIFO counterpart: ' + actual)
        fields = {'remaining_raw': 'quantity_raw', 'decimals': 'decimals',
                  'buy_count': 'buy_count', 'sell_count': 'sell_count'}
        for original, actual in fields.items():
            if original in expected and position.get(actual) != expected[original]:
                raise AssertionError('Worked selected lot field differs: ' + actual)
        money = {'buy_basis_lamports': 'basis_sol',
                 'matched_disposed_basis_lamports': 'matched_basis_sol',
                 'conditional_lot_profit_lamports': 'pnl_sol'}
        for original, actual in money.items():
            if original in expected:
                try:
                    value = Fraction(position[actual]) * 10**9
                except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
                    raise AssertionError('Observed selected lot monetary value unavailable: ' + actual) from exc
                if value != _fraction(expected[original]):
                    raise AssertionError('Worked selected lot monetary value differs: ' + actual)
        for original, actual in (('sell_received_quote_lamports', 'proceeds_sol'),
                                 ('sell_network_fee_lamports', 'exit_fees_sol')):
            if original in expected:
                if type(expected[original]) is not int or Fraction(position.get(actual, 'unavailable')) * 10**9 != expected[original]:
                    raise AssertionError('Worked selected lot exit value differs: ' + actual)
        if 'conditional_lot_profit_sol' in expected and position.get('pnl_sol') != expected['conditional_lot_profit_sol']:
            raise AssertionError('Worked selected lot SOL profit differs')
        if 'sell_net_proceeds_lamports' in expected:
            net = (Fraction(position['proceeds_sol']) - Fraction(position['exit_fees_sol'])) * 10**9
            if net != expected['sell_net_proceeds_lamports']:
                raise AssertionError('Worked selected lot net exit differs')
        if 'hold_seconds' in expected:
            elapsed = _utc(position['end']) - _utc(position['start'])
            seconds = elapsed.days * 86400 + elapsed.seconds
            if elapsed.microseconds or seconds != expected['hold_seconds']:
                raise AssertionError('Worked selected lot hold duration differs')
        if 'hold_hours' in expected:
            from decimal import localcontext
            value = _fraction(expected['hold_hours'])
            with localcontext() as ctx:
                ctx.prec = 192
                hours = Decimal(value.numerator) / Decimal(value.denominator)
            if Decimal(position['hold_hours']) != hours:
                raise AssertionError('Worked selected lot hold hours differ')
        if 'conditional_lot_roi_pct_display_192_digit' in expected:
            if Decimal(position['roi_pct']) != Decimal(expected['conditional_lot_roi_pct_display_192_digit']):
                raise AssertionError('Worked selected lot ROI differs')
        checked.append({'mint': expected['mint'], 'state': 'PASS',
                        'proof_id': proof.get('id'), 'accounts': proof.get('accounts'),
                        'monetary_state': proof['monetary_state'], 'timing_state': proof['timing_state'],
                        'quantity_state': proof['quantity_state'],
                        'position_status': position.get('status'), 'classification': position.get('classification'),
                        'scope': expected.get('scope', 'Supported selected lot; historical population remains separate'),
                        'wallet_population_promoted': False})
    return checked


def selected_lot_controls(lots, oracle, manifest):
    """Bind loss controls to independent raw page positions, never report flags."""
    controls = []
    for index, lot in enumerate(lots):
        for role in ('buy', 'sell'):
            ordinal = lot.get(role + '_record_index')
            if type(ordinal) is not int or ordinal < 0:
                raise AssertionError('Worked selected lot lacks an exact raw ' + role + ' record index')
            matches = {row['signature'] for row in oracle['raw_observations']
                       if row['response_hash'] in lot['source_hashes'] and row['ordinal'] == ordinal}
            if len(matches) != 1:
                raise AssertionError('Worked selected lot raw source identity is missing or ambiguous')
            signature = next(iter(matches))
            selected = [row for row in manifest['transactions'] if row['signature'] == signature]
            if len(selected) != 1:
                raise AssertionError('Worked selected lot requires exactly one selected source pointer')
            controls.append({'lot_index': index, 'mint': lot['mint'], 'account': lot.get('account'),
                             'role': role, 'signature': signature, 'hash': selected[0]['hash'],
                             'raw_record_index': ordinal, 'raw_source_hashes': lot['source_hashes']})
    return controls


def verify_selected_lot_revoked(report, control):
    """A missing required trade cannot retain a supported named-account profit."""
    observed = report.get('coverage', {}).get('wallet_evidence', {}).get('query_accounting', {}).get('supported_selected_lots', [])
    if not isinstance(observed, list):
        raise AssertionError('Selected lot removal receipt is malformed')
    matches = [row for row in observed if isinstance(row, dict) and row.get('mint') == control['mint']
               and (control['account'] is None or control['account'] in row.get('accounts', []))]
    for row in matches:
        if row.get('monetary_state') != 'UNKNOWN':
            raise AssertionError('Missing required ' + control['role'] + ' source retained supported selected lot money')
        if any(row.get(field) is not None for field in ('conditional_basis_sol', 'conditional_matched_basis_sol',
                'conditional_proceeds_sol', 'conditional_exit_fees_sol', 'conditional_lot_profit_sol', 'conditional_lot_roi_pct')):
            raise AssertionError('Revoked selected lot proof retained a known monetary result')
    return {'case': 'selected-lot-required-source-loss-exact-restoration', 'state': 'PASS', **control,
            'missing_monetary_state': 'UNKNOWN' if matches else 'ABSENT',
            'missing_counterparts': len(matches)}


def run(content, output, *, acquisition=(), worked_expectations=None, require_real=False):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    oracle = freeze_expectations(content)
    expected_bytes = (json.dumps(oracle, indent=2) + '\n').encode()
    (output / 'EXPECTED_RAW.json').write_bytes(expected_bytes)
    result = {'kind': 'offline-genuine-collection-workflow', 'state': 'INCOMPLETE',
              'provider_requests': 0, 'credential_lookups': 0,
              'oracle_frozen_before_application': True, 'oracle_sha256': digest(expected_bytes),
              'archive_sha256': digest(content), 'acquisition': list(acquisition), 'cases': []}
    if worked_expectations is not None:
        worked_expectations = deepcopy(worked_expectations)
        worked_bytes = (json.dumps(worked_expectations, indent=2) + '\n').encode()
        (output / 'EXPECTED_WORKED.json').write_bytes(worked_bytes)
        result['worked_expectations_sha256'] = digest(worked_bytes)
    def save():
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    save()
    def denied_provider(*args, **kwargs):
        result['provider_requests'] += 1
        raise AssertionError('Offline workflow attempted provider dispatch')
    def denied_credentials(*args, **kwargs):
        result['credential_lookups'] += 1
        raise AssertionError('Offline workflow attempted credential access')
    import httpx
    from fastapi.testclient import TestClient
    import scanner.app as application
    original_sync_send = httpx.Client.send
    def local_test_send(client, *args, **kwargs):
        if isinstance(client, TestClient):
            return original_sync_send(client, *args, **kwargs)
        return denied_provider(client, *args, **kwargs)
    with patch.object(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None)), \
         patch.dict(sys.modules, {'keyring': SimpleNamespace(get_keyring=denied_credentials, get_password=denied_credentials, set_password=denied_credentials)}), \
         patch.object(httpx.AsyncClient, 'request', denied_provider), \
         patch.object(httpx.AsyncClient, 'send', denied_provider), \
         patch.object(httpx.Client, 'send', local_test_send):
        app = application.create_app(output / 'data', 'genuine-offline-workflow-session')
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            try:
                assert client.get('/api/state').status_code == 401
                csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'genuine-offline-workflow-session'}).json()['csrf']
                client.headers['X-CSRF-Token'] = csrf
                usage = client.get('/api/state').json()['usage']
                response = client.post('/api/archives/import', content=content, headers={'Content-Type': 'application/zip'})
                assert response.status_code == 200, response.text
                identifier = response.json()['report_id']
                parent = client.get('/api/reports/' + identifier).json()
                original = client.get(f'/api/export/reports/{identifier}.json').content
                (output / 'parent-report.json').write_bytes(original)
                csv_response = client.get(f'/api/export/reports/{identifier}.csv')
                assert csv_response.status_code == 200
                csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
                assert {row['metric'] for row in csv_rows} == set(parent['metrics'])
                (output / 'parent-report.csv').write_bytes(csv_response.content)
                (output / 'input.zip').write_bytes(content)
                expected = oracle['observed_network_fees_sol']
                fee = parent['metrics']['observed_network_fees_sol']
                if expected['status'] == 'known':
                    assert fee['status'] == 'known' and fee['value'] == expected['value'], (fee, expected)
                else:
                    assert fee['status'] == 'unknown', (fee, expected)
                if worked_expectations is not None:
                    result['cases'].append({**verify_worked_expectations(parent, worked_expectations, oracle),
                                            'report_role': 'parent'})
                manifest = client.get('/api/evidence/' + parent['archive_input_hash']).json()
                inspected = []
                for row in manifest['transactions']:
                    source = client.get('/api/evidence/' + row['hash'])
                    assert source.status_code == 200
                    inspected.append({'hash': row['hash'], 'payload': source.json()})
                    pointer = source.json()
                    if isinstance(pointer, dict) and pointer.get('source_hash'):
                        envelope_response = client.get('/api/evidence/' + pointer['source_hash'])
                        assert envelope_response.status_code == 200
                        envelope = envelope_response.json()
                        for field in ('request', 'response'):
                            exact = base64.b64decode(envelope[field + '_base64'], validate=True)
                            assert digest(exact) == envelope[field + '_hash']
                            assert envelope[field + '_hash'] in oracle['raw_input_hashes']
                        inspected.append({'hash': pointer['source_hash'], 'payload': envelope})
                (output / 'inspected-selected-sources.json').write_text(json.dumps(inspected, indent=2) + '\n')
                result['cases'].append({'case': 'raw-input-normal-report-source-inspection-json-csv', 'state': 'PASS',
                                       'fee_expected': expected, 'report_id': identifier})
                baseline = client.post(f'/api/reports/{identifier}/rebuild')
                assert baseline.status_code == 200, baseline.text
                rebuilt = client.get('/api/reports/' + baseline.json()['report_id']).json()
                assert rebuilt['metrics'] == parent['metrics']
                assert rebuilt['archive_input_hash'] == parent['archive_input_hash'] and rebuilt['window'] == parent['window'] and rebuilt['preset'] == parent['preset']
                (output / 'baseline-child.json').write_text(json.dumps(rebuilt, indent=2) + '\n')
                if worked_expectations is not None:
                    result['cases'].append({**verify_worked_expectations(rebuilt, worked_expectations, oracle),
                                            'report_role': 'baseline-child'})
                # Remove the primary pointer while preserving all frozen links;
                # a missing primary cannot be erased by a later index or rebuild.
                required_fee_signatures = {row['signature'] for row in oracle['raw_observations']
                                           if row['in_report_window'] is True and row['wallet_paid_fee_lamports'] > 0}
                chosen = next((row for row in manifest['transactions'] if row['signature'] in required_fee_signatures),
                              manifest['transactions'][0])
                path = app.state.store.path / 'evidence' / f"{chosen['hash']}.json.gz"
                original_bytes = path.read_bytes()
                try:
                    path.unlink()
                    missing_response = client.post(f'/api/reports/{identifier}/rebuild')
                    assert missing_response.status_code == 200, missing_response.text
                    missing = client.get('/api/reports/' + missing_response.json()['report_id']).json()
                    if chosen['signature'] in required_fee_signatures:
                        assert missing['metrics']['observed_network_fees_sol']['status'] == 'unknown'
                    for name, metric in parent['metrics'].items():
                        if metric.get('status') == 'unknown':
                            assert missing['metrics'][name].get('status') != 'known'
                    assert missing['window'] == parent['window'] and missing['preset'] == parent['preset']
                    (output / 'source-missing-child.json').write_text(json.dumps(missing, indent=2) + '\n')
                finally:
                    path.write_bytes(original_bytes)
                restored_response = client.post(f'/api/reports/{identifier}/rebuild')
                assert restored_response.status_code == 200, restored_response.text
                restored = client.get('/api/reports/' + restored_response.json()['report_id']).json()
                assert restored['metrics'] == parent['metrics']
                assert restored['archive_input_hash'] == parent['archive_input_hash'] and restored['window'] == parent['window'] and restored['preset'] == parent['preset']
                (output / 'source-restored-child.json').write_text(json.dumps(restored, indent=2) + '\n')
                if worked_expectations is not None:
                    result['cases'].append({**verify_worked_expectations(restored, worked_expectations, oracle),
                                            'report_role': 'fee-source-restored-child'})
                    controls = selected_lot_controls(worked_expectations.get('supported_selected_lots', []), oracle, manifest)
                    for control in controls:
                        lot_path = app.state.store.path / 'evidence' / f"{control['hash']}.json.gz"
                        lot_original = lot_path.read_bytes()
                        artifact = f"lot-{control['lot_index']}-{control['role']}"
                        try:
                            lot_path.unlink()
                            response = client.post(f'/api/reports/{identifier}/rebuild')
                            assert response.status_code == 200, response.text
                            child = client.get('/api/reports/' + response.json()['report_id']).json()
                            removal = verify_selected_lot_revoked(child, control)
                            assert child['archive_input_hash'] == parent['archive_input_hash'] and child['window'] == parent['window'] and child['preset'] == parent['preset']
                            for name, metric in parent['metrics'].items():
                                if metric.get('status') == 'unknown':
                                    assert child['metrics'][name].get('status') != 'known'
                            (output / (artifact + '-missing-child.json')).write_text(json.dumps(child, indent=2) + '\n')
                        finally:
                            lot_path.write_bytes(lot_original)
                        response = client.post(f'/api/reports/{identifier}/rebuild')
                        assert response.status_code == 200, response.text
                        child = client.get('/api/reports/' + response.json()['report_id']).json()
                        assert child['metrics'] == parent['metrics']
                        assert child['archive_input_hash'] == parent['archive_input_hash'] and child['window'] == parent['window'] and child['preset'] == parent['preset']
                        restored_case = verify_worked_expectations(child, worked_expectations, oracle)
                        (output / (artifact + '-restored-child.json')).write_text(json.dumps(child, indent=2) + '\n')
                        assert client.get(f'/api/export/reports/{identifier}.json').content == original
                        result['cases'].append({**removal, 'restored_expectations': restored_case,
                                                'parent_unchanged': True, 'restored_pointer_sha256': digest(lot_original)})
                assert client.get(f'/api/export/reports/{identifier}.json').content == original
                assert client.get('/api/state').json()['usage'] == usage
                assert not app.state.store.list('collector_checkpoints')
                assert result['provider_requests'] == 0 and result['credential_lookups'] == 0, \
                    'Offline workflow acceptance requires zero provider and credential attempts'
                result['cases'].append({'case': 'primary-source-loss-exact-restoration-immutable-parent', 'state': 'PASS',
                                       'removed_signature': chosen['signature'], 'removed_hash': chosen['hash'],
                                       'required_nonzero_fee': chosen['signature'] in required_fee_signatures})
                result['query_coverage'] = parent.get('coverage', {}).get('wallet_evidence', {}).get('query_coverage',
                    {'state': 'UNKNOWN', 'reason': 'No supported raw query-coverage receipt is present.'})
                result['query_accounting'] = parent.get('coverage', {}).get('wallet_evidence', {}).get('query_accounting')
                result['real_acceptance'] = real_acceptance(parent, acquisition, worked_expectations, digest(content))
                result.update(parent_unchanged=True, usage_unchanged=True, collector_ancestry_created=False,
                              PRODUCT_READY=result['real_acceptance']['state'] == 'PASS')
                result['state'] = 'PASS' if result['real_acceptance']['state'] == 'PASS' else 'BLOCKED' if require_real else 'WORKFLOW_PASS_REAL_ACCEPTANCE_BLOCKED'
            except Exception as exc:
                result.update(state='FAILED', error=type(exc).__name__ + ': ' + str(exc), PRODUCT_READY=False)
                save()
                raise
    result['artifacts'] = {p.name: {'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size}
                           for p in output.iterdir() if p.is_file() and p.name != 'result.json'}
    save()
    return 2 if require_real and result['real_acceptance']['state'] != 'PASS' else 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', type=Path)
    group.add_argument('--collection', type=Path, action='append')
    p.add_argument('--address')
    p.add_argument('--start')
    p.add_argument('--end')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--input-freeze', type=Path,
                   help='Frozen acquisition metadata bound to --input; preserves the existing ZIP identity')
    p.add_argument('--worked-expectations', type=Path)
    p.add_argument('--require-real-acceptance', action='store_true')
    args = p.parse_args()
    if args.collection:
        if args.input_freeze:
            p.error('--input-freeze accompanies --input, not a newly packed collection')
        if not all((args.address, args.start, args.end)):
            p.error('--collection requires --address, --start and --end')
        content, acquisition = pack_collection(args.collection, args.address, {'start': args.start, 'end': args.end})
    else:
        content, acquisition = args.input.read_bytes(), []
        if args.input_freeze:
            acquisition = load_input_freeze(args.input_freeze, content)
    worked = _json(args.worked_expectations.read_bytes()) if args.worked_expectations else None
    return run(content, args.output, acquisition=acquisition, worked_expectations=worked, require_real=args.require_real_acceptance)


if __name__ == '__main__':
    raise SystemExit(main())
