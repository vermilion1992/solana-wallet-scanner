"""Local HTTP boundary and single durable research worker."""
from __future__ import annotations

import asyncio
import csv
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
import io
import json
from pathlib import Path
import secrets
import re
from contextlib import asynccontextmanager
import uuid
import hashlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import STRICT, LIMITS, Credentials, validate_address, validate_preset, validate_limits, validate_cycle
from .storage import Store, EvidenceError, QuotaExceeded, now


def _secret_equal(candidate, expected):
    return isinstance(candidate, str) and len(candidate) <= 512 and secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def _wallet_adapter_inputs(store, collected, *, address=None, window=None):
    """Read every linked raw alternative; do not trust cached interpreted rows."""
    from .archive_input import archived_record
    from .indexed_input import IndexedResolver
    from .source_consistency import SOURCE_HASH_LIMIT, merge_source_manifests
    selected, refs = set(), []
    rows = collected.get('transactions', [])
    for row in rows if isinstance(rows, list) else [None]:
        if not isinstance(row, dict):
            refs.append(None)
            continue
        signature, digest = row.get('signature'), row.get('evidence_hash')
        if isinstance(signature, str) and isinstance(digest, str):
            selected.add((signature, digest))
        refs.append({'kind': 'transaction', 'signature': signature, 'hash': digest})
    cp = collected.get('checkpoint', {})
    cp = cp if isinstance(cp, dict) else {}
    persisted = {}
    # Rebuild inputs are already frozen by load_report_inputs. Later collector
    # state must not expand their reference universe; this is not a population
    # or authenticity certificate.
    if (address is not None and window is not None
            and not collected.get('frozen_input_hash') and not collected.get('frozen_report_id')):
        from .accounting import utc
        identifier = hashlib.sha256(f"{address}:{int(utc(window['start']).timestamp())}:{int(utc(window['end']).timestamp())}".encode()).hexdigest()
        persisted = store.get('collector_checkpoints', identifier, {})
        persisted = persisted if isinstance(persisted, dict) else {}
    refs += merge_source_manifests(collected.get('evidence', []), cp.get('evidence', []), persisted.get('evidence', []))
    hashes = {ref.get('hash') for ref in refs if isinstance(ref, dict)
              and isinstance(ref.get('hash'), str) and re.fullmatch(r'[a-f0-9]{64}', ref['hash'])}
    if len(hashes) > SOURCE_HASH_LIMIT:
        # No arbitrary prefix may become a supported source set.
        return [], [], [], [{'state': 'UNKNOWN', 'reason': 'Raw adapter source set exceeds the fixed inspection budget.'}]
    cache, records, sources, receipts, seen = {}, [], [], [], set()
    def read(digest, role):
        if digest not in cache:
            try:
                cache[digest] = store.evidence(digest)
            except (EvidenceError, ValueError, OSError):
                cache[digest] = None
            receipts.append({'hash': digest, 'role': role,
                'state': 'PASS' if cache[digest] is not None else 'UNKNOWN',
                'reason': 'Checksum-verified raw bytes; authenticity and population remain separate.'
                    if cache[digest] is not None else 'Still-linked raw source is unavailable.'})
        return cache[digest]
    resolver = IndexedResolver(read, address=address)
    indexed_sources = {}
    for ref in refs:
        if (not isinstance(ref, dict) or not isinstance(ref.get('hash'), str) or ref['hash'] not in hashes
                or not isinstance(ref.get('kind'), str)
                or ref.get('signature') is not None and (not isinstance(ref['signature'], str) or not ref['signature'])
                or ref.get('kind') in ('transaction', 'getTransaction') and not ref.get('signature')):
            signature = ref.get('signature') if isinstance(ref, dict) else None
            signature = signature if isinstance(signature, str) and signature else None
            digest = ref.get('hash') if isinstance(ref, dict) else None
            digest = digest if isinstance(digest, str) else None
            receipts.append({'hash': digest, 'signature': signature, 'state': 'UNKNOWN',
                             'reason': 'Malformed linked raw adapter source leaves its relevance unresolved.'})
            records.append({'signature': signature, 'evidence_hash': digest, 'raw': None})
            continue
        digest = ref['hash']
        read(digest, ref.get('kind'))
        identity = (ref.get('kind'), ref.get('signature'), digest)
        if identity in seen:
            continue
        seen.add(identity)
        payload = cache[digest]
        if ref.get('kind') in ('transaction', 'getTransaction'):
            records.append(archived_record(payload, ref.get('signature'), digest, read,
                                          address=address, resolver=resolver, source_cache=indexed_sources))
        else:
            sources.append({'hash': digest, 'kind': ref.get('kind'),
                            'signature': ref.get('signature'), 'payload': payload})
    # Separately frozen inventory routing is application metadata, never part
    # of the authenticated native collector link universe. Read it only from
    # the exact saved input cited by this report; it carries no positive fact.
    dependencies = collected.get('native_inventory_dependencies')
    if dependencies is not None:
        from .inventory_evidence import NATIVE_DEPENDENCIES_VERSION, MAX_SOURCES
        frozen_hash = collected.get('frozen_input_hash')
        valid = False
        try:
            frozen_input = store.evidence(frozen_hash)
            encoded = json.dumps(frozen_input, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                 separators=(',', ':')).encode()
            bound_report = store.get('reports', collected.get('frozen_report_id'))
            affinity_hashes = dependencies.get('affinity_hashes') if isinstance(dependencies, dict) else None
            valid = (hashlib.sha256(encoded).hexdigest() == frozen_hash
                and isinstance(bound_report, dict) and bound_report.get('source') == 'live'
                and not bound_report.get('preview') and bound_report.get('collection_input_hash') == frozen_hash
                and bound_report.get('address') == address and bound_report.get('window') == window
                and frozen_input.get('version') == 'saved-report-input-v1'
                and frozen_input.get('address') == address and frozen_input.get('window') == window
                and frozen_input.get('native_inventory_dependencies') == dependencies
                and set(dependencies) == {'version', 'affinity_hashes'}
                and dependencies['version'] == NATIVE_DEPENDENCIES_VERSION
                and isinstance(affinity_hashes, list) and len(affinity_hashes) <= MAX_SOURCES
                and all(isinstance(h, str) and re.fullmatch(r'[a-f0-9]{64}', h) for h in affinity_hashes)
                and affinity_hashes == sorted(set(affinity_hashes))
                and len(hashes | {h for h in cache if isinstance(h, str) and re.fullmatch(r'[a-f0-9]{64}', h)}
                        | set(affinity_hashes)) <= SOURCE_HASH_LIMIT)
        except (EvidenceError, TypeError, ValueError, OSError, KeyError):
            valid = False
        if not valid:
            raise EvidenceError('Frozen native inventory routing lacks its exact saved-report binding')
        for digest in affinity_hashes:
            payload = read(digest, 'inventory-affinity')
            # Every frozen selector must still name an original native link.
            if isinstance(payload, dict) and payload.get('source_hash') not in hashes:
                payload = None
            sources.append({'hash': digest, 'kind': 'inventory-affinity', 'payload': payload})
    primary = [row for row in records if (row['signature'], row['evidence_hash']) in selected]
    return primary, records, sources, receipts


def _freeze_native_dependencies(store, collected, *, address, window):
    from .wallet_evidence import raw_native_dependencies
    from .real_coverage import query_source_dependencies
    from .wallet_identity import wallet_identity_dependencies
    primary, linked, raw_sources, raw_receipts = _wallet_adapter_inputs(store, collected, address=address, window=window)
    negatives = raw_native_dependencies(raw_sources, raw_receipts, {r['signature'] for r in primary})
    # These are negative associations, not completion or position certificates.
    frozen = {**collected, 'evidence': deepcopy(collected.get('evidence', [])) + [
        {'kind': 'transaction' if r.get('signature') else 'unresolved-native-source',
         'signature': r.get('signature'), 'hash': r['evidence_hash']} for r in negatives
        if isinstance(r.get('evidence_hash'), str) and re.fullmatch(r'[a-f0-9]{64}', r['evidence_hash'])]}
    frozen['evidence'] += [{'kind': 'query-affinity', 'hash': digest}
                          for digest in query_source_dependencies(raw_sources)]
    frozen['evidence'] += [{'kind': 'wallet-identity-affinity', 'hash': digest}
                          for digest in wallet_identity_dependencies(raw_sources, wallet=address)]
    if not collected.get('frozen_input_hash') and not collected.get('frozen_report_id'):
        from .inventory_evidence import (NATIVE_SOURCE_VERSION, NATIVE_DEPENDENCIES_VERSION, MAX_SOURCES,
                                         inventory_request_affinities)
        from .source_consistency import SOURCE_HASH_LIMIT
        from .json_boundary import canonical_bytes
        captured = [source for source in raw_sources if isinstance(source.get('payload'), dict)
                    and source['payload'].get('version') == NATIVE_SOURCE_VERSION]
        if captured:
            affinities = inventory_request_affinities(captured, wallet=address)
            # Apply the same combined source/selector budget as saved-input
            # consumption before writing any metadata or claiming observations.
            affinity_rows = [{'kind': 'inventory-affinity',
                              'hash': hashlib.sha256(canonical_bytes(value)).hexdigest(), 'payload': value}
                             for value in affinities]
            source_hashes = {row['hash'] for row in raw_receipts if isinstance(row.get('hash'), str)
                             and re.fullmatch(r'[a-f0-9]{64}', row['hash'])}
            affinity_hashes = {row['hash'] for row in affinity_rows}
            if len(affinity_hashes) > MAX_SOURCES or len(source_hashes | affinity_hashes) > SOURCE_HASH_LIMIT:
                raise EvidenceError('Frozen native inventory source/selector set exceeds its fixed inspection budget')
            for row in affinity_rows:
                if store.archive(row['payload']) != row['hash']:
                    raise EvidenceError('Frozen native inventory selector archive checksum disagrees')
            frozen['native_inventory_dependencies'] = {'version': NATIVE_DEPENDENCIES_VERSION,
                'affinity_hashes': sorted({row['hash'] for row in affinity_rows})}
            raw_sources += affinity_rows
            raw_receipts += [{'hash': row['hash'], 'role': 'inventory-affinity', 'state': 'PASS',
                              'reason': 'Internally frozen negative routing; no response/completion fact.'}
                             for row in affinity_rows]
    return frozen, primary, linked, raw_sources, raw_receipts


def allowed_request_host(host, allowed_hosts):
    """Exact hostname allow-list. Rejects rebinding, IPv6, and junk."""
    if not isinstance(host, str) or not host or any(char in host for char in "@?#/\\"):
        return False
    if host.startswith("["):
        return False
    name, sep, port = host.partition(":")
    if sep:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return False
    return name in set(allowed_hosts)


def create_app(data_dir, launch_token=None, *, allowed_hosts=None):
    store = Store(data_dir)
    launch_token = launch_token or secrets.token_urlsafe(32)
    cookie_secret, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    credentials = Credentials(str(store.path))
    wake = asyncio.Event()
    worker_task = None
    schedule_task = None
    closing = False
    network_lock = asyncio.Lock()
    enrichment_lock = asyncio.Lock()
    from .observer import ObserverService
    observer = ObserverService(store)
    active_scan_id = None
    active_discovery_id = None
    pilot_cap = 200

    def research_mode():
        info = provider()
        if info.get("free_plan_confirmed"):
            try:
                validate_cycle(info.get("cycle_start"), info.get("cycle_end"))
                return "monthly"
            except ValueError:
                pass
        return "setup-pilot"

    def settings():
        return store.get("configuration", "settings", {"limits": dict(LIMITS), "refresh_minutes": 0})

    def preset():
        return store.get("configuration", "preset", dict(STRICT))

    def report_inputs(view="full"):
        if view == 'summary':
            from .report_view import summary_inputs
            return summary_inputs(store)
        # Enriching an old snapshot must not make it the latest wallet report.
        return sorted(store.list("reports"), key=lambda report: report["created_at"], reverse=True)

    def reports(view="full"):
        result = [decorate_report(report) for report in report_inputs(view)]
        if view == 'summary':
            from .report_view import summary_view
            return [summary_view(report) for report in result]
        return result

    def decorate_report(report):
        from .copy_review import qualify_report, review_copy_behavior
        from .history_evidence import VERSION as HISTORY_METHODOLOGY
        from .position_evidence import VERSION as POSITION_METHODOLOGY
        from .research import VERSION as RESEARCH_METHODOLOGY
        from .wallet_evidence import VERSION as WALLET_METHODOLOGY
        result = {**report, "qualification": qualify_report(report), "copy_review": review_copy_behavior(report)}
        if not report.get('preview'):
            research = report.get('research')
            saved = research.get('version') if isinstance(research, dict) else None
            state = 'current' if saved == RESEARCH_METHODOLOGY else 'rebuild_required' if saved else 'missing'
            result['research_assessment'] = {'saved_methodology': saved, 'current_methodology': RESEARCH_METHODOLOGY,
                'state': state, 'reason': 'Current scoped research interpretation; inspect each monetary/timing dependency.' if state == 'current' else
                'Rebuild this saved report offline before using its research monetary results. Saved values remain unchanged.'}
            coverage = report.get('coverage') if isinstance(report.get('coverage'), dict) else {}
            wallet_receipt = coverage.get('wallet_evidence')
            wallet_saved = wallet_receipt.get('version') if isinstance(wallet_receipt, dict) else None
            wallet_state = 'current' if wallet_saved == WALLET_METHODOLOGY else 'rebuild_required' if wallet_saved else 'missing'
            result['wallet_assessment'] = {'saved_methodology': wallet_saved, 'current_methodology': WALLET_METHODOLOGY,
                'state': wallet_state, 'reason': 'Current selected-record accounting; historical population and qualification remain separate.' if wallet_state == 'current' else
                'Rebuild this report offline before using the current selected-record observations. Saved values remain unchanged.'}
        if report.get('archive_input_hash') and not report.get('preview'):
            from .archive_input import METHOD as ARCHIVE_METHODOLOGY
            archive = report.get('archive_accounting')
            saved = archive.get('version') if isinstance(archive, dict) else None
            state = 'current' if saved == ARCHIVE_METHODOLOGY else 'rebuild_required' if saved else 'missing'
            result['archive_assessment'] = {'saved_methodology': saved, 'current_methodology': ARCHIVE_METHODOLOGY,
                'state': state, 'reason': 'Current archived-source interpretation; coverage and qualification remain separate.' if state == 'current' else
                'Rebuild this archived report offline to apply current source and fee-window checks. Saved values remain unchanged.'}
        if report.get("source") == "mass-search" and not report.get("preview"):
            result["mass_search_interpretation"] = {
                "kind": "mass-search-export-interpretation-v1",
                "capture_sha256": report.get("capture_sha256"),
                "analysis_cache_key": report.get("analysis_cache_key"),
                "window": report.get("window"),
                "corpus_kind": report.get("corpus_kind"),
                "decoder_version": (report.get("coverage") or {}).get("decoder_version"),
                "visible_report": report.get("visible_report") is True,
                "visible_report_stored": report.get("visible_report") if "visible_report" in report else None,
                "result_scope": report.get("result_scope") or "conditional_on_captured_inventory",
                "evidence_class": (report.get("research_profile") or {}).get("evidence_class"),
                "candidate_assessment": (report.get("research_profile") or {}).get("candidate_assessment"),
                "not_safe_to_copy": True,
                "PRODUCT_READY": False,
                "sol_fees_not_converted": (report.get("worksheet") or {}).get("sol_fees_not_converted"),
                "usdc_excluding_sol_fees_is_never_net": True,
                "unresolved_basis_is_not_zero": True,
                "scoped_pnl_is_not_wallet_wide": True,
                "whole_sale_pnl_resolved": False if (report.get("worksheet") or {}).get("unresolved_basis_sales") else None,
            }
        if report.get("source") == "live" and not report.get("preview"):
            coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
            for name, current, scope in (("history", HISTORY_METHODOLOGY, "account-specific receipt"),
                                         ("position", POSITION_METHODOLOGY, "account-specific position")):
                evidence = coverage.get(name + "_evidence")
                saved = evidence.get("version") if isinstance(evidence, dict) else None
                state = "current" if saved == current else "rebuild_required" if saved else "missing"
                result[name + "_assessment"] = {"saved_methodology": saved, "current_methodology": current,
                                                "state": state,
                                                "reason": f"Current {scope} methodology; inspect each result's scope and evidence state." if state == "current" else
                                                f"Rebuild from saved records before using historical {scope} results as a current assessment. Saved values remain unchanged."}
        return result

    def discovery_cohorts(saved_reports=None):
        from .candidate_import import derive_candidate_progress
        from .discovery import plan_candidate_audits
        saved_reports = reports() if saved_reports is None else saved_reports
        planner_reports = report_inputs('summary')
        saved = {report["id"]: report for report in saved_reports}
        result = store.list("discovery_cohorts")
        for cohort in result:
            for candidate in cohort.get("candidates", []):
                report = saved.get(candidate.get("report_id"))
                if report and report.get("address") == candidate.get("address") and report.get("source") == "live" and not report.get("preview"):
                    candidate.update(qualification=report["qualification"], copy_review=report["copy_review"])
                else:
                    candidate["qualification"] = {"qualified": False, "financial_policy": "NOT_AUDITED", "profit_sol": None,
                                                  "preset_version": None, "evidence_status": "unknown", "failed_checks": [], "unknown_checks": [],
                                                  "reason": "A native identity check is a research lead. Historical accounting and all PDF evidence gates must be audited."}
                candidate.update(derive_candidate_progress(candidate, cohort, saved_reports))
            cohort['audit_plan'] = plan_candidate_audits(
                store, cohort, reports=planner_reports, preset=preset(),
                audit_cap=settings()['limits']['deep_audit_cap'])
        return result

    def checkpoint_reference(checkpoint):
        if checkpoint.get("version") == "native-collector-v1" and all(key in checkpoint for key in ("address", "start", "end")):
            identifier = hashlib.sha256(f"{checkpoint['address']}:{checkpoint['start']}:{checkpoint['end']}".encode()).hexdigest()
            return {"collector_ref": identifier}
        return {"collector": checkpoint}

    def read_checkpoint(checkpoint):
        if checkpoint.get("collector_ref"):
            value = store.get("collector_checkpoints", checkpoint["collector_ref"])
            if value is None:
                raise EvidenceError("The durable collection checkpoint is missing")
            return value
        return checkpoint.get("collector")

    def provider():
        result = store.get("configuration", "provider", {"free_plan_confirmed": False, "capability_status": "untested", "last_test": None,
                                                           "cycle_start": None, "cycle_end": None})
        return {**result, "configured": bool(credentials.key), "storage": credentials.storage}

    def usage():
        info = provider()
        mode = research_mode()
        result = store.usage("helius", info["cycle_start"], settings()["limits"]["helius_cap"]) if mode == "monthly" else store.usage("helius", "setup-pilot", pilot_cap)
        from .providers import COST_MANIFEST
        return {**result, "mode": mode, "billing_cycle_verified": mode == "monthly", "cycle_end": info.get("cycle_end") if mode == "monthly" else None,
                "setup_pilot": store.usage("helius", "setup-pilot", pilot_cap),
                "public_discovery": store.usage("geckoterminal", date.today().isoformat(), 200),
                "manifest_version": COST_MANIFEST.get("version", "native-v1")}

    def require_provider():
        info = provider()
        if not info["configured"] or not info["free_plan_confirmed"]:
            raise HTTPException(409, "Configure a manual Helius Free key and confirm the free-plan cost manifest first")
        try:
            validate_cycle(info["cycle_start"], info["cycle_end"])
        except ValueError as error:
            raise HTTPException(409, "Provider cycle expired; confirm the current billing cycle in Settings") from error
        return info

    def gateway(mode="monthly", *, sample_scan_id=None, sample_address=None):
        if mode == "public-sample":
            from .screening_routes import PublicSampleRPC
            return PublicSampleRPC(store, sample_scan_id, sample_address)
        from .providers import Gateway
        if mode == "setup-pilot":
            if not credentials.key:
                raise HTTPException(409, "A Helius key is required for native wallet investigation")
            return Gateway(store, credentials.key, "setup-pilot", pilot_cap)
        info = require_provider()
        return Gateway(store, credentials.key, info["cycle_start"], settings()["limits"]["helius_cap"])

    async def build_report(scan, address, collected, *, rebuilt_from=None, archive_loaded=None):
        from .indexed_input import validated_page_context
        with validated_page_context():
            return await _build_report(scan, address, collected, rebuilt_from=rebuilt_from,
                                       archive_loaded=archive_loaded)

    async def _build_report(scan, address, collected, *, rebuilt_from=None, archive_loaded=None):
        from .accounting import analyze, evaluate_policy, METHODOLOGY
        from .decoder import decode_transactions
        from .investigation import decode_supported_swaps, inspect_token_risk
        from .research import summarize_research
        from .history_evidence import derive_history_evidence
        from .position_evidence import derive_position_evidence
        from .report_rebuild import freeze_report_inputs
        history_evidence = derive_history_evidence(store, address, scan["window"],
                                                   checkpoint=collected.get("checkpoint"), collected=collected,
                                                   verification_days=scan["preset"]["verification_days"])
        position_evidence = derive_position_evidence(store, address, scan["window"],
                                                     checkpoint=collected.get("checkpoint"), collected=collected,
                                                     history_evidence=history_evidence)
        history_complete = False
        if archive_loaded is None:
            collected, primary, linked, raw_sources, raw_receipts = _freeze_native_dependencies(
                store, collected, address=address, window=scan['window'])
        collection_input_hash = freeze_report_inputs(store, address, scan["window"], collected)
        from .wallet_evidence import with_derived_order
        records = with_derived_order(collected.get("transactions", []),
            archive_loaded['chronology'] if archive_loaded is not None else history_evidence['paging']['chronology'])
        swaps = decode_supported_swaps(records, address)
        supported = {event["signature"] for event in swaps["events"] if event["kind"] in ("buy", "sell")}
        # A supported transaction replaces the entire generic interpretation,
        # including its fee. Unrecognized transactions retain transfers and gaps.
        decoded = decode_transactions([record for record in records if record.get("signature") not in supported], address)
        events = decoded["events"] + [event for event in swaps["events"] if event.get("signature") in supported]
        from .wallet_evidence import derive_wallet_evidence
        from .metric_evidence import (accounting_intervals, compose_metric_decisions,
                                      apply_metric_decisions, compose_production_evidence, selected_fee_checks)
        archive_accounting = None
        if archive_loaded is not None:
            from .archive_input import analyze_archive
            result, events, archive_accounting = analyze_archive(archive_loaded, events)
            wallet_evidence = archive_accounting['wallet_evidence']
            derived_decisions = archive_accounting['metric_requirements']
            production_evidence = archive_accounting['production_evidence']
            history_complete = archive_accounting['quantity_population_state'] == 'PASS'
        else:
            wallet_evidence = derive_wallet_evidence(primary, all_records=linked, wallet=address,
                window=scan['window'], events=events, raw_sources=raw_sources, source_receipts=raw_receipts,
                source_consistency=history_evidence['source_consistency'],
                chronology=history_evidence['paging']['chronology'])
            events = deepcopy(wallet_evidence['accounting_events'])
            # Current raw receipts, including explicit independent bounds,
            # govern FIFO. Old account-page receipts remain visible and cannot
            # veto a future admitted proof or substitute for a missing one.
            derived_intervals = accounting_intervals(wallet_evidence['intervals'], scan['window'])
            history_complete = (wallet_evidence['components']['historical_population']['state'] == 'PASS'
                                and derived_intervals['report_period']['status'] == 'complete')
            result = analyze(events, scan["window"]["start"], scan["window"]["end"], history_complete=history_complete,
                             interval_coverage=derived_intervals,
                             **wallet_evidence['economic_evidence']['economic_inputs'].get('report_period', {}))
            research = summarize_research(events, scan["window"]["start"], scan["window"]["end"],
                                          history_complete=history_complete, wallet_evidence=wallet_evidence)
            # Reuse the existing raw-payer/window projection. This independent
            # observation must also exist on ordinary native reports, not just
            # archives; token/classification gaps do not invent or erase fees.
            observed_fees = research.get('wallet_fees_paid_sol')
            fee_refs = sorted({digest for name in ('native_fee', 'fee_window', 'selected_record_identity')
                               for digest in wallet_evidence['components'][name]['evidence']})
            result['metrics']['observed_network_fees_sol'] = {'value': observed_fees,
                'status': 'known' if observed_fees is not None else 'unknown', 'unit': 'SOL',
                'population': 'Selected native records within the reporting window; wallet completeness is separate',
                'reason': None if observed_fees is not None else 'Selected native payer/fee or interval placement is unresolved.',
                'evidence': fee_refs}
            metric_components = deepcopy(wallet_evidence['components'])
            metric_components.update(selected_fee_checks(wallet_evidence))
            derived_decisions = compose_metric_decisions(metric_components,
                {name: {'state': 'PASS' if row['status'] == 'complete' else 'UNKNOWN',
                        'interval': name, 'reason': row['reason'], 'evidence': row['evidence'], 'scope': row.get('scope')}
                 for name, row in derived_intervals.items()}, metric_observations=result['metrics'])
            result = apply_metric_decisions(result, derived_decisions)
            production_evidence = compose_production_evidence(wallet_evidence, result, scan['window'],
                source_input_hash=collection_input_hash, component_checks=metric_components)
        if archive_loaded is not None:
            research = summarize_research(events, scan["window"]["start"], scan["window"]["end"],
                                          history_complete=history_complete, wallet_evidence=wallet_evidence)
        token_risk = deepcopy(rebuilt_from.get("token_risk", [])) if rebuilt_from else []
        mints = [] if rebuilt_from or archive_loaded is not None else list(dict.fromkeys(event["mint"] for event in events if event.get("mint")))[:3]
        mint_refresh_available = scan.get('status') == 'running' and (
            scan.get('budget_mode') == 'public-sample' or bool(credentials.key))
        risk_evidence = []
        from .providers import ProviderError
        for mint in mints:
            cached = store.get("mint_risk_observations", mint)
            minimum_slot = collected.get("snapshot", {}).get("slot", 0)
            minimum_slot = minimum_slot if type(minimum_slot) is int and minimum_slot >= 0 else 0
            try:
                if cached and cached.get("mint") == mint and type(cached.get("context_slot")) is int and cached["context_slot"] >= minimum_slot and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(cached["observed_at"])).total_seconds() < 900:
                    observation = store.evidence(cached["hash"])
                    if not isinstance(observation, dict) or observation.get("address") != mint or observation.get("method") != "getAccountInfo":
                        raise EvidenceError("Current mint observation identity is inconsistent")
                    raw = observation.get("result")
                else:
                    if not mint_refresh_available:
                        raise EvidenceError('Optional current mint controls are unavailable; cached report construction performs no provider or credential lookup.')
                    async with network_lock:
                        async with gateway(scan.get("budget_mode", "monthly"), sample_scan_id=scan['id'], sample_address=address) as native:
                            raw = await native.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "finalized", "minContextSlot": minimum_slot}])
                    observed_at = now()
                    observation = {"method": "getAccountInfo", "address": mint, "commitment": "finalized", "observed_at": observed_at, "result": raw}
                    context_slot = raw.get("context", {}).get("slot", -1) if isinstance(raw, dict) and isinstance(raw.get("context"), dict) else -1
                    context_slot = context_slot if type(context_slot) is int and context_slot >= 0 else -1
                    cached = {"mint": mint, "hash": store.archive(observation), "observed_at": observed_at, "context_slot": context_slot}
                    store.put("mint_risk_observations", mint, cached)
                context = raw.get("context") if isinstance(raw, dict) else None
                if not isinstance(context, dict) or type(context.get("slot")) is not int or context["slot"] < minimum_slot:
                    raise EvidenceError("Current mint observation has no valid finalized context")
                cohort = store.get("discovery_cohorts", scan.get("discovery_cohort_id")) if scan.get("discovery_cohort_id") else None
                pools = [pool for pool in (cohort or {}).get("universe", []) if mint in (pool.get("base_token_address"), pool.get("quote_token_address")) and pool.get("selected")]
                hashes = list(dict.fromkeys([cached["hash"]] + [pool["evidence_hash"] for pool in pools if pool.get("evidence_hash")]))
                inspected = inspect_token_risk(raw, {"pools": pools, "evidence": hashes})
                token_risk.append({"mint": mint, **inspected, "observed_at": cached["observed_at"], "context_slot": context["slot"], "pool_observations": pools, "evidence": hashes})
                risk_evidence.append({"hash": cached["hash"], "kind": "current-mint-controls", "mint": mint})
            except (ProviderError, QuotaExceeded, EvidenceError, HTTPException):
                token_risk.append({"mint": mint, **inspect_token_risk(None), "evidence": []})
        if scan.get('budget_mode') == 'public-sample':
            sample_cp = store.get('public_sample_checkpoints', scan['id'] + ':' + address, {})
            collected.setdefault('coverage', {}).update(
                credits=sample_cp.get('requests_used', 0), requests_used=sample_cp.get('requests_used', 0),
                tranche_request_limit=sample_cp.get('tranche_request_limit', 0))
        evaluated = evaluate_policy(result["metrics"], scan["preset"],
                                    evidence_verified=production_evidence['evidence_gates'])
        report = {"id": uuid.uuid4().hex, "scan_id": scan["id"], "address": address, "label": "", "source": "live", "created_at": now(),
                  "window": scan["window"], "methodology": METHODOLOGY, "preset": scan["preset"], "evidence_status": production_evidence['evidence_status'], **result, **evaluated,
                  "collection_input_hash": collection_input_hash,
                  "events": events, "coverage": {**collected.get("coverage", {}), "history_evidence": history_evidence,
                                                  "position_evidence": position_evidence, "swap_reconstruction": swaps["coverage"],
                                                  "wallet_evidence": wallet_evidence, "metric_dependencies": derived_decisions,
                                                  "production_evidence": production_evidence},
                  "evidence": collected.get("evidence", []) + risk_evidence + [{"hash": collection_input_hash, "kind": "saved-rebuild-inputs"}],
                  "research": research, "token_risk": token_risk,
                  "findings": result.get("findings", []) + decoded.get("findings", []) + swaps.get("findings", []),
                  "notes": ["Native RPC verifies the fetched account scope; it cannot prove discovery of every historical owned account.",
                            "Only recognized spot instructions with reconciled SOL consideration become buys/sells; unsupported wrappers, crossquotes and missing marks remain unresolved.",
                            "No current market price is substituted for historical valuation. No paid data path is enabled."]}
        if archive_loaded is not None:
            manifest = archive_loaded["manifest"]
            report.update(archive_input_hash=archive_loaded["input_hash"], archive_dependency_input_hash=archive_loaded.get('dependency_input_hash'), archive_accounting=archive_accounting,
                          source="demo" if manifest["dataset"] == "synthetic" else "live")
            witness_refs = [{"kind": "archived-wallet-manifest", "hash": archive_loaded["input_hash"]}]
            if archive_loaded.get('dependency_input_hash'):
                witness_refs.append({'kind': 'archive-native-dependencies', 'hash': archive_loaded['dependency_input_hash']})
            witness_refs += [{"kind": "archive-witness", "hash": h} for h in
                            [manifest.get("world_hash"), manifest.get("valuation_hash"), *manifest.get("classification_hashes", [])] if h]
            report["evidence"] += witness_refs
            report["notes"][0] = "Imported archive checks establish byte integrity and selected raw observations; genuine chain authentication and historical wallet completeness require independent evidence."
            report["notes"].append(archive_accounting["scope"] + "; imported records do not establish native collector ancestry or complete real-wallet acceptance.")
            if archive_loaded.get('indexed_pages') is not None:
                report['coverage']['indexed_sources'] = archive_loaded['indexed_pages']
                report['coverage']['indexed_record_sources'] = [
                    {'signature': r['signature'], 'evidence_hash': r['evidence_hash'], **r['indexed_source']}
                    for r in archive_loaded['all_records'] if 'indexed_source' in r]
        if rebuilt_from:
            report.update(rebuilt_from=rebuilt_from["id"], previous_methodology=rebuilt_from.get("methodology"),
                          previous_history_methodology=rebuilt_from.get("coverage", {}).get("history_evidence", {}).get("version"),
                          previous_position_methodology=rebuilt_from.get("coverage", {}).get("position_evidence", {}).get("version"),
                          rebuild={"source": "archived-native-records", "provider_requests": 0,
                                   "retained_window": True, "retained_preset": True, "mint_observations_refreshed": False})
            report["notes"].append("Rebuilt locally from saved primary records. The earlier report is unchanged; missing history and old mint observation dates remain explicit.")
        report = decorate_report(report)
        report['collection'] = {'stop_reason': collected.get('coverage', {}).get('collection_stop_reason') or scan.get('reason'),
                                'scope': collected.get('coverage', {}).get('scope'),
                                'scan_id': scan['id'], 'budget_mode': scan.get('budget_mode'),
                                'limits': deepcopy(scan.get('limits', {}))}
        store.put("reports", report["id"], report)
        if scan.get("discovery_cohort_id"):
            cohort = store.get("discovery_cohorts", scan["discovery_cohort_id"])
            if cohort:
                for candidate in cohort.get("candidates", []):
                    if candidate["address"] == address:
                        candidate.update(report_id=report["id"], research=research, observed_profit_sol=research.get("observed_profit_sol"),
                                         qualification=report["qualification"], copy_review=report["copy_review"],
                                         risk={"findings": [finding for token in token_risk for finding in token.get("findings", [])],
                                               "unresolved": ["Historical ownership, acquisition basis and complete wallet profit remain unverified.",
                                                              "Creator links, liquidity withdrawal rights and copied execution have not been established."]})
                store.put("discovery_cohorts", cohort["id"], cohort)
        return report

    async def run_scan(scan):
        if scan.get('budget_mode') == 'public-sample':
            from .screening_routes import collect_public_sample
            scan.update(status='running', stage='Collecting bounded public wallet-address sample')
            store.put('scans', scan['id'], scan)
            await collect_public_sample(store, scan, build_report,
                lambda: closing or store.get('scans', scan['id'], {}).get('status') == 'paused')
            return
        from .collector import collect_wallet, CollectionPaused
        addresses = scan["audit_addresses"]
        scan["status"] = "running"
        scan["stage"] = "Preparing account scope"
        store.put("scans", scan["id"], scan)
        for index in range(scan.get("checkpoint", {}).get("wallet_index", 0), len(addresses)):
            address = addresses[index]
            checkpoint = read_checkpoint(scan.get("checkpoint", {})) if scan.get("checkpoint", {}).get("wallet_index") == index else None
            completed_totals = scan.get("checkpoint", {}).get("completed_totals", {"pages": 0, "transactions": 0, "credits": 0})

            def should_pause():
                return closing or store.get("scans", scan["id"], {}).get("status") == "paused"

            def progress(update):
                latest = store.get("scans", scan["id"], scan)
                latest["stage"] = update.get("stage", "Collecting evidence")
                for key in ("pages", "transactions", "credits"):
                    if key in update:
                        latest["progress"][key] = completed_totals.get(key, 0) + update[key]
                latest["checkpoint"] = {"wallet_index": index, **checkpoint_reference(update.get("checkpoint", {})), "completed_totals": completed_totals}
                store.put("scans", scan["id"], latest)

            try:
                async with network_lock:
                    async with gateway(scan.get("budget_mode", "monthly")) as rpc_gateway:
                        collected = await collect_wallet(rpc_gateway, store, address, scan["window"]["start"], scan["window"]["end"],
                                                         {**scan["limits"], "basis_lookback_days": scan["preset"]["verification_days"]},
                                                         checkpoint=checkpoint, progress=progress, should_pause=should_pause)
                report = await build_report(scan, address, collected)
                scan = store.get("scans", scan["id"], scan)
                scan["progress"]["wallets_completed"] = index + 1
                scan["progress"]["unresolved"] += int(report["policy"] == "UNRESOLVED")
                scan["checkpoint"] = {"wallet_index": index + 1, "completed_totals": {key: scan["progress"].get(key, 0) for key in ("pages", "transactions", "credits")}}
                store.put("scans", scan["id"], scan)
                if should_pause():
                    return
            except CollectionPaused as error:
                scan = store.get("scans", scan["id"], scan)
                if getattr(error, 'partial', None):
                    error.partial.setdefault('coverage', {})['collection_stop_reason'] = error.reason
                # A setup pilot deliberately samples every selected wallet. Its
                # per-wallet history remains partial and every cursor is retained.
                bounded_stop = error.reason.startswith(("Transaction limit reached", "Wallet credit limit reached", "Unsupported transaction version"))
                if scan.get("budget_mode") == "setup-pilot" and bounded_stop and not should_pause():
                    if getattr(error, "partial", None):
                        await build_report(scan, address, error.partial)
                    reference = checkpoint_reference(error.checkpoint)
                    scan.setdefault("pilot_wallet_checkpoints", {})[address] = reference if "collector_ref" in reference else error.checkpoint
                    scan.setdefault("pilot_scope_notes", {})[address] = error.reason
                    scan["progress"]["wallets_completed"] = index + 1
                    scan["progress"]["unresolved"] += 1
                    scan["checkpoint"] = {"wallet_index": index + 1, "completed_totals": {key: scan["progress"].get(key, 0) for key in ("pages", "transactions", "credits")}}
                    store.put("scans", scan["id"], scan)
                    continue
                scan.update(status="paused", stage="Evidence collection paused", reason=error.reason,
                            checkpoint={"wallet_index": index, **checkpoint_reference(error.checkpoint), "completed_totals": completed_totals})
                if getattr(error, "partial", None) and error.partial.get("transactions"):
                    await build_report(scan, address, error.partial)
                store.put("scans", scan["id"], scan)
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                scan = store.get("scans", scan["id"], scan)
                from .providers import ProviderError
                reason = str(error) if isinstance(error, (ProviderError, QuotaExceeded)) else f"Research paused after {type(error).__name__}; retained evidence and checkpoint can be inspected."
                scan.update(status="paused", stage="Action required", reason=reason)
                store.put("scans", scan["id"], scan)
                return
        scan = store.get("scans", scan["id"], scan)
        scan.update(status="completed", stage="Reports ready", reason="Collection finished for the bounded audit scope. Report evidence status is assessed separately.")
        store.put("scans", scan["id"], scan)

    async def worker():
        nonlocal active_scan_id, active_discovery_id
        while True:
            await wake.wait()
            wake.clear()
            for cohort in reversed(store.list("discovery_cohorts")):
                if closing:
                    return
                cohort = store.get("discovery_cohorts", cohort["id"], cohort)
                if cohort["status"] == "queued":
                    active_discovery_id = cohort["id"]
                    try:
                        await run_discovery(cohort)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        latest = store.get("discovery_cohorts", cohort["id"], cohort)
                        reason = str(error) if isinstance(error, (HTTPException, QuotaExceeded)) else "Discovery stopped; retained evidence can be inspected."
                        latest.update(status="failed", stage="Discovery stopped", reason=reason)
                        store.put("discovery_cohorts", latest["id"], latest)
                    finally:
                        active_discovery_id = None
            pending = [s for s in reversed(store.list("scans")) if s["status"] == "queued"]
            for scan in pending:
                if closing:
                    return
                latest = store.get("scans", scan["id"], scan)
                if latest["status"] == "queued":
                    active_scan_id = latest["id"]
                    try:
                        await run_scan(latest)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        failed = store.get("scans", latest["id"], latest)
                        failed.update(status="paused", stage="Action required", reason="Research paused after a checkpoint or local processing error; retained evidence can be inspected.")
                        store.put("scans", failed["id"], failed)
                    finally:
                        active_scan_id = None

    def queue_scan(addresses, days, discovery_source="manual", budget_mode="monthly", cohort_id=None):
        end = datetime.now(timezone.utc).replace(microsecond=0)
        identifier = uuid.uuid4().hex
        limits = dict(settings()["limits"])
        if budget_mode == "setup-pilot":
            limits.update(transaction_limit=min(limits["transaction_limit"], 20), wallet_credit_limit=min(limits["wallet_credit_limit"], 30), page_size=25, account_limit=200)
        audit = addresses[:limits["deep_audit_cap"]]
        scan = {"id": identifier, "source": "live", "discovery_source": discovery_source, "status": "queued", "stage": "Awaiting collector", "created_at": now(),
                "window": {"start": (end - timedelta(days=days)).isoformat(), "end": end.isoformat()}, "addresses": addresses,
                "audit_addresses": audit, "deferred_addresses": addresses[len(audit):], "preset": preset(), "limits": limits,
                "budget_mode": budget_mode, "discovery_cohort_id": cohort_id,
                "progress": {"wallets_completed": 0, "wallets_total": len(audit), "pages": 0, "transactions": 0, "credits": 0, "unresolved": 0},
                "checkpoint": {"wallet_index": 0}, "reason": f"Up to {len(audit)} deep audits; {len(addresses) - len(audit)} candidates retained for a later batch."}
        store.put("scans", identifier, scan)
        wake.set()
        return identifier

    async def run_discovery(queued):
        from .discovery import discover_candidates
        def should_pause():
            return closing or store.get("discovery_cohorts", queued["id"], {}).get("status") == "paused"
        async with network_lock:
            if credentials.key:
                async with gateway(queued["budget_mode"]) as native:
                    await discover_candidates(store, native, **queued["options"], cohort_id=queued["id"], should_pause=should_pause)
            else:
                await discover_candidates(store, **queued["options"], cohort_id=queued["id"], should_pause=should_pause)

    async def scheduler():
        """Only runs while this local process lives; never refresh synthetic controls."""
        while True:
            await asyncio.sleep(15)
            interval = settings().get("refresh_minutes", 0)
            if not interval or closing:
                continue
            info = provider()
            status = store.get("configuration", "schedule", {"last_run": now(), "offset": 0})
            if (datetime.now(timezone.utc) - datetime.fromisoformat(status["last_run"])).total_seconds() < interval * 60:
                continue
            if not info.get("configured") or info.get("capability_status") != "passed" or not info.get("calibration_address"):
                continue
            if any(s["status"] in ("queued", "running", "paused") and s["source"] == "live" for s in store.list("scans")) or any(c["status"] in ("queued", "running") for c in store.list("discovery_cohorts")):
                continue
            if usage()["used"] + usage()["reserved"] >= settings()["limits"]["discovery_pause"]:
                continue
            addresses = [w["address"] for w in store.list("watchlist") if w.get("source") not in ("demo", "mass-search")]
            if not addresses:
                continue
            try:
                require_provider()
            except HTTPException:
                continue
            offset = status.get("offset", 0) % len(addresses)
            rotated = addresses[offset:] + addresses[:offset]
            batch = rotated[:settings()["limits"]["deep_audit_cap"]]
            queue_scan(batch, preset()["window_days"], "watchlist-schedule")
            store.put("configuration", "schedule", {"last_run": now(), "offset": (offset + len(batch)) % len(addresses)})

    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker_task, schedule_task, closing
        observer.recover()
        for scan in store.list("scans"):
            changed = False
            if scan.get("budget_mode") == "setup-pilot":
                if scan["limits"].get("account_limit") != 200:
                    scan["limits"]["account_limit"] = 200
                    changed = True
            checkpoint = scan.get("checkpoint", {})
            if checkpoint.get("collector", {}).get("version") == "native-collector-v1":
                scan["checkpoint"] = {key: value for key, value in checkpoint.items() if key != "collector"}
                scan["checkpoint"].update(checkpoint_reference(checkpoint["collector"]))
                changed = True
            for address, saved in scan.get("pilot_wallet_checkpoints", {}).items():
                if saved.get("version") == "native-collector-v1":
                    scan["pilot_wallet_checkpoints"][address] = checkpoint_reference(saved)
                    changed = True
            if scan["status"] == "running":
                scan.update(status="paused", reason="The local app restarted. Resume from the durable checkpoint.", stage="Paused after restart")
                changed = True
            if changed:
                store.put("scans", scan["id"], scan)
        for cohort in store.list("discovery_cohorts"):
            if cohort["status"] == "running":
                cohort.update(status="paused", reason="The local app restarted; archived discovery evidence is retained.")
                store.put("discovery_cohorts", cohort["id"], cohort)
        worker_task = asyncio.create_task(worker())
        schedule_task = asyncio.create_task(scheduler())
        if any(s["status"] == "queued" for s in store.list("scans") + store.list("discovery_cohorts")):
            wake.set()
        yield
        closing = True
        await observer.shutdown()
        worker_task.cancel()
        schedule_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        try:
            await schedule_task
        except asyncio.CancelledError:
            pass
        store.close()

    app = FastAPI(title="Solana Wallet Scanner", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.launch_token, app.state.csrf = store, launch_token, csrf
    app.state.allowed_hosts = tuple(allowed_hosts) if allowed_hosts else ("127.0.0.1", "localhost")

    @app.middleware("http")
    async def local_boundary(request, call_next):
        host = request.headers.get("host", "")
        valid_host = allowed_request_host(host, app.state.allowed_hosts)
        if not valid_host:
            loopback_only = set(app.state.allowed_hosts) <= {"127.0.0.1", "localhost"}
            return JSONResponse({"detail": "Loopback Host required" if loopback_only else "Bound Host required"}, 403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":
            return JSONResponse({"detail": "Same-origin local access required"}, 403)
        if request.method == "OPTIONS":
            return JSONResponse({"detail": "Cross-origin access is disabled"}, 403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/bootstrap":
            cookie = request.cookies.get("scanner_session", "")
            if not _secret_equal(cookie, cookie_secret):
                return JSONResponse({"detail": "Open the launch URL to establish a local session"}, 401)
            if request.method not in ("GET", "HEAD") and not _secret_equal(request.headers.get("x-csrf-token", ""), csrf):
                return JSONResponse({"detail": "CSRF token required"}, 403)
        if request.method in ("POST", "PUT", "PATCH"):
            length = request.headers.get("content-length", "0")
            limit = 20 * 1024 * 1024 if request.url.path == "/api/archives/import" else 4 * 1024 * 1024 if request.url.path == "/api/evidence/audit" else 65536
            if not length.isdigit() or int(length) > limit:
                return JSONResponse({"detail": "Request body exceeds local pilot limit"}, 413)
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > limit:
                    return JSONResponse({"detail": "Request body exceeds local pilot limit"}, 413)
                content.extend(chunk)
            request._body = bytes(content)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, 422)

    @app.exception_handler(EvidenceError)
    async def evidence_error(request, error):
        return JSONResponse({"detail": str(error)}, 409)

    async def body(request):
        try:
            result = await request.json()
        except (ValueError, UnicodeDecodeError, RecursionError) as error:
            raise HTTPException(422, "Valid JSON required") from error
        if not isinstance(result, dict):
            raise HTTPException(422, "JSON object required")
        return result

    @app.get("/api/evidence/example")
    async def evidence_example():
        path = Path(__file__).resolve().parent / "examples" / "real-transaction-audit-mainnet.json"
        return JSONResponse(json.loads(path.read_text()), headers={"Content-Disposition": "attachment; filename=real-transaction-audit-mainnet.json"})

    @app.post("/api/evidence/audit")
    async def create_evidence_audit(request: Request):
        import shutil
        from .evidence_audit import audit_raw_bundle
        bundle = await body(request)
        if shutil.disk_usage(store.path).free < settings()["limits"]["min_free_disk_mb"] * 1024 ** 2:
            raise HTTPException(409, "Below the configured free-disk reserve; free space before archiving new evidence")
        result = audit_raw_bundle(bundle, store)
        identifier = uuid.uuid4().hex
        result.update(id=identifier, created_at=now(), bundle_hash=store.archive(bundle))
        store.put("evidence_audits", identifier, result)
        return {"audit_id": identifier, **result}

    @app.get("/api/evidence/audits/{identifier}")
    async def get_evidence_audit(identifier):
        result = store.get("evidence_audits", identifier)
        if result is None:
            raise HTTPException(404, "Scoped evidence audit not found")
        return result

    @app.get("/api/evidence/audits/{identifier}/export")
    async def export_evidence_audit(identifier):
        result = await get_evidence_audit(identifier)
        return JSONResponse(result, headers={"Content-Disposition": f"attachment; filename=scoped-evidence-audit-{identifier}.json"})

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request):
        token = request.headers.get("x-launch-token", "")
        if not _secret_equal(token, launch_token) and not _secret_equal(request.cookies.get("scanner_session", ""), cookie_secret):
            raise HTTPException(401, "Use the private launch URL printed by the local app")
        response = JSONResponse({"csrf": csrf, "version": __version__, "PRODUCT_READY": False})
        response.set_cookie("scanner_session", cookie_secret, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/health")
    async def health():
        return {"kind": "local-scanner-health-v1", "version": __version__, "PRODUCT_READY": False}

    @app.get("/api/state")
    async def state(report_view: str = "full"):
        from .report_view import validate_view
        validate_view(report_view, ('full', 'summary'))
        from .accounting import METHODOLOGY
        from .evidence_audit import VERSION as EVIDENCE_AUDIT_METHODOLOGY
        from .history_evidence import VERSION as HISTORY_METHODOLOGY
        from .position_evidence import VERSION as POSITION_METHODOLOGY
        from .source_consistency import VERSION as SOURCE_CONSISTENCY_METHODOLOGY
        from .wallet_evidence import VERSION as WALLET_METHODOLOGY
        from .candidate_import import aggregate_candidate_universe
        from .real_coverage import historical_source_decision
        from .paper import list_runs
        from .screening_routes import observation_view, screening_views
        from .mass_search.routes import mass_search_state as _mass_search_state
        disk = store.stats()
        disk["warnings"] = []
        if disk["evidence_bytes"] >= 10 * 1024 ** 3:
            disk["warnings"].append("Evidence exceeds 10 GiB; review storage and backup space before further ingestion.")
        if disk["free_disk_bytes"] < settings()["limits"]["min_free_disk_mb"] * 1024 ** 2:
            disk["warnings"].append("Low free disk space; ingestion pauses before further requests or evidence writes.")
        saved_reports = reports(report_view)
        cohorts = discovery_cohorts(saved_reports)
        # Saved rows and their derived projections are JSON-native already.
        # Avoid FastAPI's second recursive copy of large archived proof trees.
        return JSONResponse({"version": __version__, "methodology": METHODOLOGY, "evidence_audit_methodology": EVIDENCE_AUDIT_METHODOLOGY,
                "history_evidence_methodology": HISTORY_METHODOLOGY,
                "position_evidence_methodology": POSITION_METHODOLOGY,
                "source_consistency_methodology": SOURCE_CONSISTENCY_METHODOLOGY,
                "wallet_evidence_methodology": WALLET_METHODOLOGY,
                "historical_source_decision": historical_source_decision(),
                "settings": settings(), "preset": preset(), "provider": provider(), "usage": usage(),
                "scans": store.list("scans"), "discovery_cohorts": cohorts, "reports": saved_reports,
                "screenings": screening_views(store), "observations": [observation_view(store, run) for run in list_runs(store)],
                "candidate_universe": aggregate_candidate_universe(cohorts, saved_reports, candidate_cap=settings()["limits"]["candidate_cap"]),
                "evidence_audits": store.list("evidence_audits"), "watchlist": store.list("watchlist"), "storage": disk,
                "mass_search": _mass_search_state(store)})

    @app.get("/api/usage")
    async def get_usage():
        return usage()

    @app.get("/api/provider/manifest")
    async def cost_manifest():
        from .providers import COST_MANIFEST
        return {**dict(COST_MANIFEST), "methods": dict(COST_MANIFEST["methods"])}

    @app.post("/api/demo")
    async def demo():
        from .demo import create_demo_reports
        return {"scan_id": create_demo_reports(store, preset())}

    @app.put("/api/settings")
    async def save_settings(request: Request):
        data = await body(request)
        if set(data) - {"preset", "limits", "refresh_minutes"}:
            raise ValueError("Unknown settings field")
        current = settings()
        new_preset = validate_preset(data["preset"], preset()) if "preset" in data else None
        new_limits = validate_limits(data.get("limits", {}), current["limits"])
        if "refresh_minutes" in data:
            interval = data["refresh_minutes"]
            if type(interval) is not int or (interval != 0 and not 15 <= interval <= 1440):
                raise ValueError("Refresh interval must be 0 (disabled) or 15–1440 minutes")
            current["refresh_minutes"] = interval
            store.put("configuration", "schedule", {"last_run": now(), "offset": 0})
        if new_preset:
            new_preset["version"] = "preset-" + uuid.uuid4().hex[:12]
            store.put("presets", new_preset["version"], new_preset)
            store.put("configuration", "preset", new_preset)
        current["limits"] = new_limits
        store.put("configuration", "settings", current)
        return {"ok": True}

    @app.post("/api/presets/preview")
    async def preview(request: Request, view: str = "full"):
        from .accounting import evaluate_policy
        from .report_view import summary_view, validate_view
        validate_view(view, ('full', 'summary'))
        new_preset = validate_preset((await body(request)).get("preset", {}), preset())
        results = []
        for report in report_inputs(view):
            report = decorate_report(report)
            duration = datetime.fromisoformat(report["window"]["end"]) - datetime.fromisoformat(report["window"]["start"])
            same_period = duration == timedelta(days=new_preset["window_days"])
            same_history = report.get("preset", {}).get("verification_days", 90) == new_preset["verification_days"]
            metrics = report["metrics"]
            reason = None
            if not same_period or not same_history:
                reason = "Reporting or verification period changed. Collect/rebuild this scope before evaluating it; cached metrics belong to the displayed saved window."
                metrics = {key: {**metric, "value": None, "status": "unknown", "reason": reason} for key, metric in metrics.items()}
            projected = decorate_report({**report, "preview": True, "preview_reason": reason, "metrics": metrics,
                            **evaluate_policy(metrics, new_preset, evidence_verified=report["evidence_status"] == "verified" and same_period and same_history)})
            results.append(summary_view(projected) if view == 'summary' else projected)
        return JSONResponse({"reports": results})

    @app.post("/api/provider")
    async def configure_provider(request: Request):
        data = await body(request)
        if set(data) - {"api_key", "free_plan_confirmed", "cycle_start", "cycle_end"}:
            raise ValueError("Unknown provider field")
        if data.get("free_plan_confirmed") is not True:
            raise ValueError("Confirm manual Helius Free entitlement and the dated native-method cost manifest")
        start, end = validate_cycle(data.get("cycle_start"), data.get("cycle_end"))
        old = provider()
        anchor = store.get("configuration", "billing-cycle-anchor", old)
        if anchor.get("cycle_end") and date.fromisoformat(anchor["cycle_end"]) > date.today() and (start, end) != (anchor["cycle_start"], anchor["cycle_end"]):
            raise ValueError("An active provider cycle cannot be changed to reset application usage")
        if data.get("api_key"):
            credentials.set(data["api_key"])
        if not credentials.key:
            raise ValueError("Enter your manually obtained Helius Free API key")
        result = {"free_plan_confirmed": True, "cycle_start": start, "cycle_end": end,
                  "capability_status": "untested", "last_test": None}
        store.put("configuration", "provider", result)
        store.put("configuration", "billing-cycle-anchor", {"cycle_start": start, "cycle_end": end})
        return {"ok": True, "provider": provider()}

    @app.post("/api/provider/key")
    async def configure_pilot_key(request: Request):
        data = await body(request)
        if set(data) != {"api_key"} or not isinstance(data["api_key"], str) or not data["api_key"]:
            raise ValueError("Enter a Helius API key for the bounded setup pilot")
        credentials.set(data["api_key"])
        store.put("configuration", "provider", {"free_plan_confirmed": False, "capability_status": "untested", "last_test": None,
                                                 "cycle_start": None, "cycle_end": None})
        return {"ok": True, "provider": provider(), "usage": usage()}

    def research_busy():
        return any(item["status"] in ("queued", "running") for item in store.list("scans") + store.list("discovery_cohorts"))

    @app.post("/api/discovery")
    async def create_discovery(request: Request):
        data = await body(request)
        if set(data) - {"pool_cap", "candidate_cap", "validate_cap"}:
            raise ValueError("Unknown discovery setting")
        options = {"pool_cap": data.get("pool_cap", 3), "candidate_cap": data.get("candidate_cap", settings()["limits"]["candidate_cap"]),
                   "validate_cap": data.get("validate_cap", 8)}
        for field, maximum in (("pool_cap", 3), ("candidate_cap", settings()["limits"]["candidate_cap"]), ("validate_cap", 8)):
            if type(options[field]) is not int or not 1 <= options[field] <= maximum:
                raise ValueError(f"{field} must be between 1 and {maximum}")
        if research_busy():
            raise HTTPException(409, "One research batch runs at a time")
        if usage()["mode"] == "monthly" and usage()["used"] + usage()["reserved"] >= settings()["limits"]["discovery_pause"]:
            raise HTTPException(409, "New discovery paused at the free-mode headroom threshold")
        identifier = uuid.uuid4().hex
        store.put("discovery_cohorts", identifier, {"id": identifier, "created_at": now(), "status": "queued", "stage": "Awaiting public pool sample",
                                                   "candidates": [], "counts": {}, "evidence": [], "limitations": [], "options": options, "budget_mode": research_mode()})
        wake.set()
        return {"cohort_id": identifier}

    @app.post("/api/discovery/import")
    async def import_discovery(request: Request):
        from .candidate_import import import_candidate_cohort
        data = await body(request)
        if set(data) != {"addresses"}:
            raise ValueError("Import requires public addresses only")
        cohort = import_candidate_cohort(data["addresses"], candidate_cap=settings()["limits"]["candidate_cap"])
        store.put("discovery_cohorts", cohort["id"], cohort)
        return {"cohort_id": cohort["id"], "counts": cohort["counts"]}

    @app.get("/api/discovery/universe")
    async def get_saved_universe():
        from .candidate_import import aggregate_candidate_universe
        saved_reports = reports()
        return aggregate_candidate_universe(discovery_cohorts(saved_reports), saved_reports, candidate_cap=settings()["limits"]["candidate_cap"])

    @app.get("/api/discovery/{identifier}")
    async def get_discovery(identifier):
        cohort = store.get("discovery_cohorts", identifier)
        if not cohort:
            raise HTTPException(404, "Discovery cohort not found")
        return next(item for item in discovery_cohorts() if item["id"] == identifier)

    @app.post("/api/discovery/{identifier}/audit")
    async def audit_discovery(identifier, request: Request):
        from .discovery import plan_candidate_audits
        data = await body(request)
        if set(data) - {"addresses"}:
            raise ValueError("Unknown discovery audit setting")
        cohort = store.get("discovery_cohorts", identifier)
        if not cohort:
            raise HTTPException(404, "Discovery cohort not found")
        if cohort["status"] in ("queued", "running") or research_busy():
            raise HTTPException(409, "Wait for the active research batch to finish")
        eligible = [candidate["address"] for candidate in cohort.get("candidates", []) if candidate.get("status") == "candidate"
                    and candidate.get("validation", {}).get("identity_verified") is True
                    and candidate.get("validation", {}).get("account_type") == "system-owned signer"
                    and candidate["address"] in candidate.get("validation", {}).get("economic_signers", [])]
        audit_plan = plan_candidate_audits(
            store, cohort, reports=report_inputs('summary'), preset=preset(),
            audit_cap=settings()['limits']['deep_audit_cap'])
        planned_eligible = set(audit_plan['selected_addresses']) | {
            row['address'] for row in audit_plan['deferred']}
        eligible = [address for address in eligible if address in planned_eligible]
        addresses = data.get("addresses", audit_plan['selected_addresses'])
        if not isinstance(addresses, list) or not addresses or len(addresses) > settings()["limits"]["deep_audit_cap"]:
            raise ValueError("Select 1–5 verified candidate wallets within the configured audit cap")
        addresses = list(dict.fromkeys(validate_address(address) for address in addresses))
        if any(address not in eligible for address in addresses):
            raise ValueError("Every audited address must have a verified native signer identity in this cohort")
        mode = research_mode() if credentials.key else 'public-sample'
        if mode != 'public-sample' and usage()["remaining"] < 1:
            raise HTTPException(409, "The research credit cap has been reached; saved evidence remains available")
        scan_id = queue_scan(addresses, preset()["window_days"], "automatic-discovery", mode, identifier)
        if mode == 'public-sample':
            sample_scan = store.get('scans', scan_id)
            sample_scan['limits'].update(transaction_limit=20, wallet_credit_limit=50)
            sample_scan['reason'] = 'Initial 20-transaction public wallet-address sample; native ownership completeness remains unknown.'
            store.put('scans', scan_id, sample_scan)
        cohort.setdefault("audit_scan_ids", []).append(scan_id)
        cohort['last_queued_audit_plan'] = {**audit_plan, 'queued_addresses': addresses,
                                          'explicit_selection': 'addresses' in data,
                                          'scan_id': scan_id}
        store.put("discovery_cohorts", identifier, cohort)
        return {"scan_id": scan_id, "budget_mode": mode}

    @app.post("/api/provider/test")
    async def test_provider(request: Request):
        data = await body(request)
        address = data.get("address") or None
        if address:
            validate_address(address)
        async with network_lock:
            async with gateway() as rpc_gateway:
                result = await rpc_gateway.capability_test(address)
        current = store.get("configuration", "provider")
        current.update(capability_status=result.get("capability_status", result.get("status", "failed")), last_test=now(), capability=result)
        # Full account-specific proof is required before scans can start.
        current["calibration_address"] = address
        store.put("configuration", "provider", current)
        return result

    @app.post("/api/scans")
    async def create_scan(request: Request):
        data = await body(request)
        if set(data) - {"addresses", "window_days", "source"}:
            raise ValueError("Unknown scan setting")
        addresses = data.get("addresses")
        if not isinstance(addresses, list) or not addresses or len(addresses) > settings()["limits"]["candidate_cap"]:
            raise ValueError("Enter 1–20 addresses within the configured batch cap")
        addresses = list(dict.fromkeys(validate_address(a) for a in addresses))
        info = provider()
        require_provider()
        if info["capability_status"] != "passed" or not info.get("calibration_address"):
            raise HTTPException(409, "Run an authenticated capability test with a calibration address in Settings first")
        if research_busy():
            raise HTTPException(409, "One bounded batch runs at a time; pause or finish the current batch first")
        if usage()["used"] + usage()["reserved"] >= settings()["limits"]["discovery_pause"]:
            raise HTTPException(409, "New discovery paused at the free-mode headroom threshold")
        days = data.get("window_days", preset()["window_days"])
        if type(days) is not int or not 1 <= days <= 365:
            raise ValueError("Window must be 1–365 days")
        return {"scan_id": queue_scan(addresses, days, "manual")}

    @app.post("/api/scans/{identifier}/pause")
    async def pause(identifier):
        scan = store.get("scans", identifier)
        if not scan:
            raise HTTPException(404, "Scan not found")
        if scan["status"] not in ("queued", "running"):
            raise HTTPException(409, "Only an active scan can be paused")
        scan.update(status="paused", reason="Paused by owner; archived records and checkpoints are retained.")
        store.put("scans", identifier, scan)
        return {"ok": True}

    @app.post("/api/scans/{identifier}/resume")
    async def resume(identifier):
        scan = store.get("scans", identifier)
        if not scan:
            raise HTTPException(404, "Scan not found")
        if scan["status"] != "paused":
            raise HTTPException(409, "Only a paused scan can resume")
        if active_scan_id == identifier:
            raise HTTPException(409, "The last request is still settling. Resume once its checkpoint has been saved.")
        mode = scan.get("budget_mode", "monthly")
        if mode == "setup-pilot":
            if not credentials.key:
                raise HTTPException(409, "Connect a Helius key before resuming the setup pilot")
            if store.usage("helius", "setup-pilot", pilot_cap)["remaining"] < 1:
                raise HTTPException(409, "The 200-credit setup pilot is exhausted; saved evidence remains available")
        elif mode == 'public-sample':
            from .screening_routes import saved_identity
            if any(saved_identity(store, address)['state'] != 'PASS' for address in scan['audit_addresses']):
                raise HTTPException(409, 'Restore native identity evidence before continuing the sample')
            if research_busy():
                raise HTTPException(409, 'Another batch is active')
            scan['limits']['transaction_limit'] = min(settings()['limits']['transaction_limit'], scan['limits']['transaction_limit'] + 20)
            scan.update(status='queued', reason='Continue another bounded public sample tranche; original report window is retained.')
            store.put('scans', identifier, scan)
            wake.set()
            return {'ok': True}
        else:
            require_provider()
        if research_busy():
            raise HTTPException(409, "Another batch is active")
        # A deliberate resume permits another bounded tranche; hard monthly cap is unchanged.
        checkpoint = read_checkpoint(scan.get("checkpoint", {})) or {}
        transaction_tranche = min(settings()["limits"]["transaction_limit"], 20) if mode == "setup-pilot" else settings()["limits"]["transaction_limit"]
        credit_tranche = min(settings()["limits"]["wallet_credit_limit"], 30) if mode == "setup-pilot" else settings()["limits"]["wallet_credit_limit"]
        scan["limits"]["transaction_limit"] = max(scan["limits"]["transaction_limit"], len(checkpoint.get("transactions", {})) + transaction_tranche)
        scan["limits"]["wallet_credit_limit"] = max(scan["limits"]["wallet_credit_limit"], checkpoint.get("credits", 0) + credit_tranche)
        scan.update(status="queued", reason="Continuation approved within the same free cap.")
        store.put("scans", identifier, scan)
        wake.set()
        return {"ok": True}

    @app.get("/api/archives/example.zip")
    async def archive_example():
        from .archive_input import pack_bytes
        example = json.loads((Path(__file__).parent / "examples/archive-wallet-synthetic.json").read_text())
        return Response(pack_bytes(example), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="synthetic-wallet-accounting.zip"'})

    @app.post("/api/archives/import")
    async def archive_import(request: Request):
        from .indexed_input import validated_page_context
        with validated_page_context():
            return await _archive_import(request)

    async def _archive_import(request: Request):
        from .archive_input import import_archive, load_archive, collected_archive
        content = await request.body()
        from .indexed_input import convert_indexed_archive, archive_version, VERSION as INDEXED_VERSION
        if archive_version(content) == INDEXED_VERSION:
            content = convert_indexed_archive(content)
        digest = import_archive(store, content,
                                reserve_bytes=settings()["limits"]["min_free_disk_mb"] * 1024 ** 2)
        loaded = load_archive(store, digest)
        manifest = loaded["manifest"]
        scan = {"id": uuid.uuid4().hex, "audit_addresses": [manifest["address"]], "window": deepcopy(manifest["window"]),
                "preset": deepcopy(preset()), "source": "archive", "status": "completed", "created_at": now(),
                "stage": "Offline archived accounting", "progress": {"wallets_completed": 1, "transactions": len(loaded["records"]), "credits": 0}}
        store.put("scans", scan["id"], scan)
        result = await build_report(scan, manifest["address"], collected_archive(loaded), archive_loaded=loaded)
        return {"report_id": result["id"], "input_hash": digest, "dataset": manifest["dataset"], "provider_requests": 0}

    @app.get("/api/reports/{identifier}")
    async def report(identifier, view: str = "full"):
        from .report_view import display_view, validate_view
        validate_view(view, ('full', 'display'))
        result = store.get("reports", identifier)
        if not result:
            raise HTTPException(404, "Report not found")
        decorated = decorate_report(result)
        return JSONResponse(display_view(decorated) if view == 'display' else decorated)

    @app.post("/api/reports/{identifier}/rebuild")
    async def rebuild_report(identifier):
        from .indexed_input import validated_page_context
        with validated_page_context():
            return await _rebuild_report(identifier)

    async def _rebuild_report(identifier):
        from .report_rebuild import load_report_inputs
        import shutil
        previous = store.get("reports", identifier)
        if not previous:
            raise HTTPException(404, "Report not found")
        if (previous.get("source") != "live" and not previous.get("archive_input_hash")) or previous.get("preview"):
            raise HTTPException(409, "Only a saved live report can be rebuilt from archived native records")
        if shutil.disk_usage(store.path).free < settings()["limits"]["min_free_disk_mb"] * 1024 ** 2:
            raise HTTPException(409, "Free disk space is below the configured reserve; free space before saving a rebuilt report")
        archive_loaded = None
        if previous.get("archive_input_hash"):
            from .archive_input import load_archive, collected_archive
            archive_loaded = load_archive(store, previous["archive_input_hash"], dependency_input_hash=previous.get('archive_dependency_input_hash'))
            manifest = archive_loaded["manifest"]
            if manifest["address"] != previous["address"] or manifest["window"] != previous["window"] or (manifest["dataset"] == "synthetic") != (previous["source"] == "demo"):
                raise EvidenceError("Frozen archive identity/window/dataset disagrees with the original report")
            collected = collected_archive(archive_loaded)
        else:
            collected = load_report_inputs(store, previous)
        original_scan = store.get("scans", previous.get("scan_id"))
        if not original_scan or previous["address"] not in original_scan.get("audit_addresses", []):
            raise HTTPException(409, "The original native collection job is missing; its source context cannot be rebuilt")
        scan = {**deepcopy(original_scan), "window": deepcopy(previous["window"]), "preset": deepcopy(previous["preset"])}
        result = await build_report(scan, previous["address"], collected, rebuilt_from=previous, archive_loaded=archive_loaded)
        return {"report_id": result["id"]}

    @app.get("/api/evidence/{digest}")
    async def evidence(digest):
        return store.evidence(digest)

    @app.post("/api/watchlist")
    async def watch(request: Request):
        data = await body(request)
        address = validate_address(data.get("address"))
        label = data.get("label", "")
        if not isinstance(label, str) or len(label) > 100:
            raise ValueError("Label must be at most 100 characters")
        reports = [row for row in store.list("reports") if row.get("address") == address]
        if any(row.get("source") == "mass-search" for row in reports):
            source = "mass-search"
        elif any(row.get("source") == "demo" or row.get("preview") is True for row in reports):
            source = "demo"
        else:
            source = "live"
        store.put("watchlist", address, {"address": address, "label": label, "added_at": now(), "source": source})
        return {"ok": True}

    @app.delete("/api/watchlist/{address}")
    async def unwatch(address):
        store.delete("watchlist", validate_address(address))
        return {"ok": True}

    @app.post("/api/backup")
    async def backup():
        return store.backup()

    @app.post("/api/reports/{identifier}/enrich")
    async def enrich(identifier, view: str = "full"):
        from .providers import GeckoTerminal, ProviderError
        from .report_view import display_view, validate_view
        validate_view(view, ('full', 'display'))
        report = store.get("reports", identifier)
        if not report:
            raise HTTPException(404, "Report not found")
        if report["source"] != "live":
            raise HTTPException(409, "Synthetic controls do not request market data")
        mints = list(dict.fromkeys(p["mint"] for p in report.get("positions", []) if p.get("mint")))[:5]
        if not mints:
            raise HTTPException(409, "No mint identities available to enrich in this report")
        async with enrichment_lock:
            async with GeckoTerminal(store) as market:
                observations = []
                for mint in mints:
                    try:
                        observations.append(await market.get_token(mint))
                    except (ProviderError, QuotaExceeded) as error:
                        report["market_observation_note"] = str(error)
                        break
        report["market_observations"] = observations
        report["market_observation_scope"] = "Up to five current token observations. Indicative only; no historical ledger or screening metric is changed."
        store.put("reports", identifier, report)
        return JSONResponse(display_view(decorate_report(report)) if view == 'display' else report)

    @app.get("/api/export/reports/{filename}")
    async def export(filename):
        identifier, dot, extension = filename.rpartition(".")
        result = store.get("reports", identifier)
        if not result or extension not in ("json", "csv"):
            raise HTTPException(404, "Report export not found")
        result = decorate_report(result)
        if extension == "json":
            content, media = json.dumps(result, ensure_ascii=False, indent=2), "application/json"
        else:
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(["metric", "value", "unit", "status", "population", "reason"])
            for key, metric in result["metrics"].items():
                fields = [key, metric.get("value"), metric.get("unit"), metric.get("status"), metric.get("population"), metric.get("reason")]
                # All externally derived strings are spreadsheet-safe.
                writer.writerow(["'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@")) else str(v or "") for v in fields])
            content, media = stream.getvalue(), "text/csv"
        dest = store.path / "exports" / f"{identifier}.{extension}"
        dest.write_text(content, encoding="utf-8")
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="wallet-report-{identifier[:12]}.{extension}"'})

    from .screening_routes import install_research_routes
    install_research_routes(app, store, body, observer, build_report=build_report, queue_scan=queue_scan,
                            wake=wake, research_busy=research_busy, settings=settings, preset=preset)
    from .mass_search.routes import install_mass_search_routes
    install_mass_search_routes(app, store)
    app.state.observer = observer

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    async def index(path):
        if path.startswith("api/"):
            raise HTTPException(404, "Research route not found")
        if path == "favicon.svg" and (dist / path).exists():
            return FileResponse(dist / path)
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return Response("Frontend not built. Run the setup script or npm ci && npm run build in frontend/.", media_type="text/plain", status_code=503)

    return app
