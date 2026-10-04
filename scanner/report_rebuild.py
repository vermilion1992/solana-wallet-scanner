"""Frozen inputs for local reconstruction; saved sources never become complete by reuse."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from .collector import _timestamp
from .config import validate_address
from .storage import EvidenceError
from .chronology_evidence import assess_chronology
from .source_consistency import (assess_source_consistency, index_source_links, merge_source_manifests,
                                 source_archive_receipts, apply_unresolved_chronology, SOURCE_HASH_LIMIT)


VERSION = "saved-report-input-v1"
MAX_RECORDS = 10_000
MAX_METADATA_LINKS = 64
MAX_REPORT_LINEAGE = 32
_HASH = re.compile(r"[a-f0-9]{64}")
_REPORT_METADATA = {"current-mint-controls", "saved-rebuild-inputs"}


def partition_report_metadata(store, references, *, report_id, address, window, collector_references=()):
    """Separate proved application metadata, preserving every original list.

    Unknown roles and metadata in the collector manifest stay unresolved.
    Stored context, exact citations and archived semantics authorize exclusions;
    caller labels/receipts do not. Validation shares the fixed distinct-hash
    budget and refuses oversized metadata sets instead of inspecting a prefix.
    """
    references = references if isinstance(references, list) else [None]
    collector_references = list(collector_references)
    candidates = {}
    for ref in references:
        if isinstance(ref, dict) and isinstance(ref.get("kind"), str) and ref["kind"] in _REPORT_METADATA:
            key = json.dumps(ref, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            candidates[key] = ref
    all_hashes = {ref["hash"] for ref in references + collector_references if isinstance(ref, dict)
                  and isinstance(ref.get("hash"), str) and _HASH.fullmatch(ref["hash"])}
    bound, seen = [], set()
    current = report_id
    for _ in range(MAX_REPORT_LINEAGE):
        if not isinstance(current, str) or current in seen:
            break
        seen.add(current)
        report = store.get("reports", current)
        if (not isinstance(report, dict) or report.get("id") != current or report.get("source") != "live" or report.get("preview")
            or report.get("address") != address or report.get("window") != window):
            break
        bound.append(report)
        current = report.get("rebuilt_from")
    allowed = bool(bound) and len(candidates) <= MAX_METADATA_LINKS and len(all_hashes) <= SOURCE_HASH_LIMIT
    cache, inspected, receipts, excluded = {}, set(), [], set()
    for key, ref in sorted(candidates.items()):
        digest, kind = ref.get("hash"), ref["kind"]
        valid = False
        source_report = None
        reason = "Application metadata lacks a bounded stored-report citation and matching archived semantics."
        if allowed and ref not in collector_references and isinstance(digest, str) and _HASH.fullmatch(digest):
            matching = [report for report in bound if isinstance(report.get("evidence"), list) and ref in report["evidence"]]
            if matching:
                if digest not in cache:
                    inspected.add(digest)
                    try:
                        raw = store.evidence(digest)
                        encoded = json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
                        cache[digest] = raw if hashlib.sha256(encoded).hexdigest() == digest else None
                    except (EvidenceError, OSError, ValueError, TypeError, KeyError):
                        cache[digest] = None
                raw = cache[digest]
                if isinstance(raw, dict):
                    for report in matching:
                        if kind == "current-mint-controls":
                            mint = ref.get("mint")
                            result = raw.get("result")
                            context = result.get("context") if isinstance(result, dict) else None
                            context_slot = context.get("slot") if isinstance(context, dict) else None
                            risk = report.get("token_risk", [])
                            risk = risk if isinstance(risk, list) else []
                            cited = any(isinstance(item, dict) and item.get("mint") == mint and isinstance(item.get("evidence"), list)
                                        and digest in item["evidence"] and item.get("context_slot") == context_slot for item in risk)
                            try:
                                mint_valid = validate_address(mint) == mint
                            except (ValueError, TypeError):
                                mint_valid = False
                            valid = (mint_valid and cited and raw.get("method") == "getAccountInfo" and raw.get("address") == mint
                                     and raw.get("commitment") == "finalized" and type(context_slot) is int and context_slot >= 0
                                     and "value" in result and (result["value"] is None or isinstance(result["value"], dict))
                                     and not {"transaction", "meta"}.intersection(raw)
                                     and not {"transaction", "meta"}.intersection(result))
                        else:
                            valid = (report.get("collection_input_hash") == digest and raw.get("version") == VERSION
                                     and raw.get("address") == address and raw.get("window") == window)
                        if valid:
                            source_report = report["id"]
                            break
        if valid:
            excluded.add(key)
            reason = "Stored report context and checksum-checked archive establish application metadata outside the native collector universe."
        receipts.append({"kind": kind, "hash": digest, "state": "PASS" if valid else "UNKNOWN",
                         "classification": "report-metadata" if valid else "unresolved-role", "report_id": source_report,
                         "evidence": [digest] if isinstance(digest, str) else [],
                         "source_paths": [{"hash": digest, "paths": ["method", "address", "commitment", "result.context.slot"]
                                          if kind == "current-mint-controls" else ["version", "address", "window"]}] if isinstance(digest, str) else [],
                         "reason": reason})
    retained = [ref for ref in references if json.dumps(ref, sort_keys=True, ensure_ascii=False, separators=(",", ":")) not in excluded]
    return {"references": retained, "excluded_reference_count": len(references) - len(retained),
            "excluded_unique_link_count": len(excluded), "inspected_hashes": sorted(inspected), "receipts": receipts}


def freeze_report_inputs(store, address, window, collected):
    """Archive links and the observed collection state, rather than copied raw transactions."""
    payload = {"version": VERSION, "address": validate_address(address), "window": deepcopy(window),
               "snapshot": deepcopy(collected.get("snapshot", {})),
               "checkpoint": deepcopy(collected.get("checkpoint", {})),
               "coverage": deepcopy(collected.get("coverage", {})),
               "evidence": deepcopy(collected.get("evidence", [])),
               "transactions": [{key: record.get(key) for key in
                                  ("signature", "evidence_hash", "transaction_index", "in_window")}
                                 for record in collected.get("transactions", [])]}
    if 'native_inventory_dependencies' in collected:
        payload['native_inventory_dependencies'] = deepcopy(collected['native_inventory_dependencies'])
    return store.archive(payload)


def load_report_inputs(store, report):
    """Read a saved live report's exact records without requesting missing sources.

    Legacy reports did not freeze their checkpoint. Their current matching
    checkpoint may explain the observed collection but cannot authenticate an
    earlier completion claim. The legacy boundary remains explicit.
    """
    if report.get("source") != "live" or report.get("preview"):
        raise ValueError("Only a saved live report can be rebuilt from archived native records")
    address = validate_address(report.get("address"))
    window = report.get("window", {})
    start, end = _timestamp(window.get("start")), _timestamp(window.get("end"))
    if end <= start:
        raise ValueError("The saved report window is invalid")
    frozen = report.get("collection_input_hash")
    if frozen:
        inputs = store.evidence(frozen)
        if (not isinstance(inputs, dict) or inputs.get("version") != VERSION or
                inputs.get("address") != address or inputs.get("window") != window):
            raise EvidenceError("Saved collection inputs disagree with this report")
        links = inputs.get("transactions", [])
        checkpoint = inputs.get("checkpoint", {})
        coverage = inputs.get("coverage", {})
        snapshot = inputs.get("snapshot", {})
        evidence = inputs.get("evidence", [])
    else:
        identifier = hashlib.sha256(f"{address}:{start}:{end}".encode()).hexdigest()
        checkpoint = store.get("collector_checkpoints", identifier, {})
        links = [{"signature": item.get("signature"), "evidence_hash": item.get("hash")}
                 for item in report.get("evidence", []) if item.get("kind") == "transaction"]
        coverage = {**deepcopy(report.get("coverage", {})), "legacy_checkpoint_not_frozen": True}
        snapshot = deepcopy(checkpoint.get("snapshot", {}))
        evidence = deepcopy(report.get("evidence", []))
    if not isinstance(links, list) or not links:
        raise ValueError("This report has no archived native transaction records to rebuild")
    if len(links) > MAX_RECORDS:
        raise EvidenceError("The exact saved transaction population exceeds the fixed record inspection limit")
    if checkpoint and (checkpoint.get("address") != address or checkpoint.get("start") != start or checkpoint.get("end") != end):
        raise EvidenceError("The collection checkpoint belongs to a different wallet or window")
    native_refs = checkpoint.get("evidence", []) if isinstance(checkpoint, dict) else []
    native_refs = native_refs if isinstance(native_refs, list) else []
    metadata = partition_report_metadata(store, evidence, report_id=report.get("id"), address=address,
                                         window=window, collector_references=native_refs)
    references = merge_source_manifests(native_refs, metadata["references"])
    authenticated_refs = references
    if not frozen:
        authenticated_refs = native_refs
    source_index = index_source_links(references, authenticated_references=authenticated_refs)
    admitted = set(source_index["hashes_to_inspect"])
    attempted, cache, read_outcomes = set(), {}, {}

    def read(digest):
        if digest not in admitted:
            return None
        if digest not in cache:
            attempted.add(digest)
            try:
                cache[digest] = store.evidence(digest)
                read_outcomes[digest] = 'readable'
            except EvidenceError as error:
                cache[digest] = None
                read_outcomes[digest] = ('missing' if isinstance(error.__cause__, FileNotFoundError) else
                                         'checksum-mismatch' if 'checksum' in str(error) else 'unreadable')
        return cache[digest]

    for digest in source_index["hashes_to_inspect"]:
        read(digest)
    archive_contents = source_archive_receipts(source_index, cache, read_outcomes,
                                              snapshot_slot=snapshot.get('slot') if isinstance(snapshot, dict) else None, wallet=address)
    page_receipts, block_receipts = [], []
    for item in source_index["links"]:
        if not isinstance(item, dict):
            raise EvidenceError("Saved evidence links are malformed")
        if item.get("kind") not in ("block-order", "signature-page"):
            continue
        if item.get("hash") not in admitted:
            continue
        receipt = {"hash": item.get("hash"), "payload": read(item.get("hash"))}
        (block_receipts if item["kind"] == "block-order" else page_receipts).append(receipt)
    records, seen = [], set()
    for link in links:
        if not isinstance(link, dict):
            raise EvidenceError("Saved transaction links are malformed")
        signature = link.get("signature")
        if not isinstance(signature, str) or not signature or signature in seen:
            raise EvidenceError("Saved transaction identity is missing or duplicated")
        seen.add(signature)
        raw = store.evidence(link.get("evidence_hash"))
        signatures = raw.get("transaction", {}).get("signatures") if isinstance(raw, dict) else None
        if not isinstance(signatures, list) or not signatures or signatures[0] != signature:
            raise EvidenceError("Archived transaction identity disagrees with the saved report")
        records.append({"signature": signature, "raw": raw, "evidence_hash": link["evidence_hash"],
                        "transaction_index": link.get("transaction_index"),
                        "in_window": type(raw.get("blockTime")) is int and start <= raw["blockTime"] < end})
    # Boundary/earlier checkpoint records inform slot consistency without being
    # promoted into the report's exact selected source population.
    comparison = []
    linked = {(row["signature"], row["evidence_hash"]) for row in records}
    checkpoint_records = checkpoint.get("transactions", {}) if isinstance(checkpoint, dict) else {}
    checkpoint_records = checkpoint_records if isinstance(checkpoint_records, dict) else {}
    for signature, item in list(checkpoint_records.items())[:MAX_RECORDS]:
        if not isinstance(item, dict) or (signature, item.get("evidence_hash")) in linked:
            continue
        raw = read(item.get("evidence_hash"))
        transaction = raw.get("transaction") if isinstance(raw, dict) else None
        signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
        comparison.append({"signature": signature, "raw": raw, "evidence_hash": item.get("evidence_hash")})
        linked.add((signature, item.get("evidence_hash")))
    # Every frozen collector-linked alternative is a placement fact, even when
    # it was not selected as an arithmetic input or its archive is unavailable.
    # Dropping these links would let one preferred raw slot prove exclusion.
    for item in source_index["links"]:
        if not isinstance(item, dict) or item.get("kind") != "transaction":
            continue
        signature, digest = item.get("signature"), item.get("hash")
        if not isinstance(signature, str) or not isinstance(digest, str) or (signature, digest) in linked:
            continue
        if digest not in admitted:
            continue
        raw = read(digest)
        comparison.append({"signature": signature, "raw": raw, "evidence_hash": digest})
        linked.add((signature, digest))
    chronology = assess_chronology(records + comparison, page_receipts=page_receipts,
                                   block_receipts=block_receipts,
                                   checkpoint_indices=checkpoint.get("ordering", {}) if isinstance(checkpoint, dict) else {})
    apply_unresolved_chronology(chronology, records + comparison, archive_contents)
    source_consistency = assess_source_consistency(records + comparison, wallet=address, source_index=source_index,
                                                    inspected_hashes=attempted, page_receipts=page_receipts, archive_contents=archive_contents)
    if chronology["invalid_block_receipts"]:
        raise EvidenceError("Archived block ordering is invalid")
    if any(conflict["kind"] == "order" for conflict in chronology["conflicts"]):
        raise EvidenceError("Archived block ordering conflicts")
    for record in records:
        check = chronology["transactions"].get(record["signature"], {})
        record["transaction_index"] = check.get("transaction_index") if check.get("order_state") == "PASS" else None
    # Time and slot-placement contradictions remain reviewable; only proven
    # contradictory block/index ordering retains the loader rejection policy.
    # The shared history/position
    # checks revoke their dependent metrics in the newly reconstructed report.
    coverage = {**deepcopy(coverage), "chronology_evidence": chronology, "source_consistency": source_consistency,
                "report_metadata": {key: value for key, value in metadata.items() if key != "references"}}
    # Missing ordering is a gap; signature text never supplies a tie breaker.
    records.sort(key=lambda item: (item["raw"]["slot"] if type(item["raw"].get("slot")) is int else -1,
                                   item["transaction_index"] if item["transaction_index"] is not None else -1))
    result = {"transactions": records, "checkpoint": deepcopy(checkpoint), "snapshot": deepcopy(snapshot),
            "coverage": coverage, "evidence": deepcopy(evidence), "frozen_input_hash": frozen,
            "frozen_report_id": report.get("id")}
    if frozen and 'native_inventory_dependencies' in inputs:
        result['native_inventory_dependencies'] = deepcopy(inputs['native_inventory_dependencies'])
    return result
