"""Offline receipts and bounded paging checks for a frozen wallet report.

Checksums authenticate the local archive, not the RPC provider or mainnet. A
collector request/response chain is useful primary collection evidence, but
exhausting known accounts cannot establish global historical ownership, opening
inventory, acquisition cost, classification, or boundary equity. No imported
completeness flag is consumed by this module.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re

from .collector import VERSION as COLLECTOR_VERSION, _timestamp, _valid_account
from .providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from .storage import EvidenceError
from .chronology_evidence import assess_chronology
from .transaction_format import supported_transaction_format
from .source_consistency import (assess_source_consistency, index_source_links, merge_source_manifests,
                                 source_archive_receipts, apply_unresolved_chronology)

VERSION = "history-evidence-v10"
MAX_ACCOUNTS = 1000
MAX_RECORDS = 10_000
MAX_REFERENCES = 40_000
_HASH = re.compile(r"[a-f0-9]{64}")
_U64_MAX = 2**64 - 1


def _integer(value):
    return type(value) is int and value >= 0


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _check(state, reason, evidence=(), **details):
    return {"state": state, "reason": reason, "evidence": sorted(set(evidence)), **details}


def _keys(raw):
    transaction = raw.get("transaction")
    message = transaction.get("message") if isinstance(transaction, dict) else None
    keys = message.get("accountKeys") if isinstance(message, dict) else None
    meta = raw.get("meta")
    if not isinstance(keys, list) or not isinstance(meta, dict):
        return None
    result = [entry.get("pubkey") if isinstance(entry, dict) else entry for entry in keys]
    loaded = meta.get("loadedAddresses", {})
    if not isinstance(loaded, dict):
        return None
    for name in ("writable", "readonly"):
        extra = loaded.get(name, [])
        if not isinstance(extra, list):
            return None
        # jsonParsed accountKeys already include lookup-table keys.
        for key in extra:
            if key not in result:
                result.append(key)
    return result if all(isinstance(key, str) and key for key in result) else None


def _native_amounts(raw, wallet):
    """Wallet-address endpoints and payer fee, without economic attribution."""
    keys, meta = _keys(raw), raw.get("meta")
    if (not keys or not isinstance(meta, dict) or not _integer(meta.get("fee"))
        or meta["fee"] > _U64_MAX):
        return None
    before, after = meta.get("preBalances"), meta.get("postBalances")
    if (not isinstance(before, list) or not isinstance(after, list)
        or len(before) != len(keys) or len(after) != len(keys)
        or not all(_integer(value) and value <= _U64_MAX for value in before + after) or keys.count(wallet) > 1):
        return None
    if sum(before) - sum(after) != meta["fee"]:
        return None
    if meta.get("err") is not None and any(after[index] - value != (-meta["fee"] if index == 0 else 0) for index, value in enumerate(before)):
        return None
    index = keys.index(wallet) if wallet in keys else None
    return (meta["fee"] if keys[0] == wallet else 0,
            after[index] - before[index] if index is not None else 0)


def _native_metric(value, state, reason, hashes, record_count, scope):
    with localcontext() as context:
        context.prec = 192
        rendered = format(Decimal(value) / Decimal(1_000_000_000), "f") if value is not None else None
    return {"status": "known" if state == "PASS" else "unknown", "value": rendered,
            "unit": "SOL", "reason": reason, "evidence": sorted(set(hashes)),
            "record_count": record_count, "scope": scope}


def derive_history_evidence(store, address, window, checkpoint=None, collected=None,
                            *, verification_days=90):
    """Derive receipts from Store.evidence without writes, network, or trust imports.

    ``window`` has whole-second UTC ``start``/``end``. ``checkpoint`` is the
    collector checkpoint, or ``collected['checkpoint']`` supplies it. Caller raw
    transactions and coverage booleans are never proof. The returned intervals
    remain partial for accounting even when ``paging.intervals`` verifies the
    enumerated account scope. All wallet-level evidence gates remain UNKNOWN.
    """
    if not _valid_account(address):
        raise ValueError("A valid public wallet address is required.")
    if not isinstance(window, dict):
        raise ValueError("Frozen report bounds are required.")
    start, end = _timestamp(window.get("start")), _timestamp(window.get("end"))
    if end <= start or type(verification_days) is not int or not 1 <= verification_days <= 3650:
        raise ValueError("Report bounds and verification days are invalid.")
    bounds = {"report_period": (start, end), "four_weeks": (end - 28 * 86400, end),
              "verification_90d": (end - 90 * 86400, end)}
    if verification_days != 90:
        bounds["selected_verification"] = (end - verification_days * 86400, end)
    collected = collected if isinstance(collected, dict) else {}
    cp = checkpoint if isinstance(checkpoint, dict) else collected.get("checkpoint", {})
    cp = cp if isinstance(cp, dict) else {}
    identifier = hashlib.sha256(f"{address}:{start}:{end}".encode()).hexdigest()
    persisted = store.get("collector_checkpoints", identifier)
    # Locally stored collector state is the provenance trust boundary. A caller
    # cannot make an arbitrary imported transaction a native collection receipt
    # by supplying a dictionary that resembles a checkpoint.
    if not cp and isinstance(persisted, dict):
        cp = persisted
    context_fields = ("version", "address", "start", "end", "basis_floor")
    persisted_match = (isinstance(persisted, dict)
                       and all(cp.get(key) == persisted.get(key) for key in context_fields)
                       and isinstance(cp.get("snapshot"), dict) and isinstance(persisted.get("snapshot"), dict)
                       and cp["snapshot"].get("anchor_evidence") == persisted["snapshot"].get("anchor_evidence"))
    persisted_refs = persisted.get("evidence", []) if isinstance(persisted, dict) else []
    persisted_refs = persisted_refs if isinstance(persisted_refs, list) else []
    compatible = (persisted_match and cp.get("version") == COLLECTOR_VERSION and cp.get("address") == address
                  and cp.get("start") == start and cp.get("end") == end)
    refs = cp.get("evidence", []) if compatible else []
    refs = refs if isinstance(refs, list) else []
    from .report_rebuild import partition_report_metadata
    report_metadata = partition_report_metadata(store, collected.get("evidence", []),
        report_id=collected.get("frozen_report_id"), address=address, window=window, collector_references=refs)
    refs = merge_source_manifests(refs, report_metadata["references"])
    authoritative_refs = persisted_refs
    frozen_hash = collected.get("frozen_input_hash")
    frozen_bound = False
    frozen_report = store.get("reports", collected.get("frozen_report_id")) if isinstance(collected.get("frozen_report_id"), str) else None
    if (compatible and isinstance(frozen_hash, str) and _HASH.fullmatch(frozen_hash) and isinstance(frozen_report, dict)
        and frozen_report.get("source") == "live" and not frozen_report.get("preview")
        and frozen_report.get("collection_input_hash") == frozen_hash and frozen_report.get("address") == address):
        try:
            frozen = store.evidence(frozen_hash)
            encoded = json.dumps(frozen, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            frozen_window = frozen.get("window", {}) if isinstance(frozen, dict) else {}
            frozen_bound = (hashlib.sha256(encoded).hexdigest() == frozen_hash and frozen.get("version") == "saved-report-input-v1"
                            and frozen.get("address") == address and frozen_window == frozen_report.get("window")
                            and _timestamp(frozen_window.get("start")) == start
                            and _timestamp(frozen_window.get("end")) == end and frozen.get("checkpoint") == cp)
            if frozen_bound:
                frozen_native_refs = frozen["checkpoint"].get("evidence", [])
                frozen_metadata = partition_report_metadata(store, frozen.get("evidence", []),
                    report_id=collected.get("frozen_report_id"), address=address, window=window,
                    collector_references=frozen_native_refs)
                authoritative_refs = merge_source_manifests(frozen_native_refs, frozen_metadata["references"])
        except (EvidenceError, OSError, ValueError, TypeError, KeyError, RuntimeError):
            frozen_bound = False
    source_index = index_source_links(refs, authenticated_references=authoritative_refs, max_unique_hashes=MAX_REFERENCES)
    known_refs = {(ref["kind"], ref["hash"], ref.get("signature")) for ref in source_index["links"]}
    admitted_hashes = set(source_index["hashes_to_inspect"])
    issues, cache, used, attempted, read_outcomes = [], {}, set(), set(), {}

    def read(digest):
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            return None
        if digest not in admitted_hashes:
            return None
        if digest not in cache:
            attempted.add(digest)
            try:
                value = store.evidence(digest)
                encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()
                # Also protects test/custom stores that do not verify checksums.
                matches = hashlib.sha256(encoded).hexdigest() == digest
                cache[digest] = value if matches else None
                read_outcomes[digest] = 'readable' if matches else 'checksum-mismatch'
            except (EvidenceError, OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                cache[digest] = None
                cause = error.__cause__ if isinstance(error, EvidenceError) else error
                read_outcomes[digest] = ('missing' if isinstance(cause, FileNotFoundError) else
                                         'checksum-mismatch' if isinstance(error, EvidenceError) and 'checksum' in str(error) else 'unreadable')
        if cache[digest] is not None:
            used.add(digest)
        return cache[digest]

    if not compatible:
        issues.append("No matching persisted native collector checkpoint establishes this frozen wallet/window; caller-supplied completeness or imported raw records are not trusted receipts.")
    snapshot = cp.get("snapshot", {}) if compatible else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    slot = snapshot.get("slot")
    anchor_hash = snapshot.get("anchor_evidence")
    anchor = read(anchor_hash)
    anchored = (isinstance(anchor, dict) and anchor.get("method") == "getSlot"
                and anchor.get("commitment") == "finalized" and _integer(slot)
                and _integer(anchor.get("result")) and anchor.get("result") == slot and snapshot.get("commitment") == "finalized")
    if not anchored:
        issues.append("The finalized native snapshot slot lacks a matching archived getSlot receipt.")
    reference_count = max(len(refs), len(authoritative_refs))
    if reference_count > MAX_REFERENCES:
        issues.append("Raw reference inspection cap exceeded; native/population limits remain unresolved. Distinct-source index completeness is assessed separately.")
    # Deduplicate the complete authenticated multiset before archive IO. A
    # unique-hash overflow refuses certification instead of selecting a prefix.
    refs = source_index["links"]
    for digest in source_index["hashes_to_inspect"]:
        read(digest)
    archive_contents = source_archive_receipts(source_index, cache, read_outcomes, snapshot_slot=slot, wallet=address)
    unresolved_archives = [row for row in archive_contents['receipts'] if row['state'] != 'PASS']
    archive_rows = {(row['kind'], row['hash'], row.get('signature')): row for row in archive_contents['receipts']}
    if unresolved_archives:
        issues.append(f"{len(unresolved_archives)} linked source roles remain unresolved; typed archive receipts retain their hashes, validation outcomes and recovery requirements.")
    pages, page_receipts, block_receipts, transaction_links = defaultdict(list), [], [], defaultdict(set)
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        digest, kind = ref.get("hash"), ref.get("kind")
        signature = ref.get("signature")
        if (not isinstance(kind, str) or not isinstance(digest, str)
            or (signature is not None and not isinstance(signature, str))
            or (kind, digest, signature) not in known_refs):
            issues.append("A frozen source reference is absent from the persisted native collector receipt chain.")
            continue
        if kind == "transaction" and isinstance(ref.get("signature"), str):
            transaction_links[ref["signature"]].add(digest)
        if kind not in ("signature-page", "block-order"):
            continue
        raw = read(digest)
        if kind == "signature-page":
            source = archive_rows[(kind, digest, signature)]
            usable = (isinstance(raw, dict) and raw.get('method') == 'getSignaturesForAddress'
                      and _valid_account(raw.get('address')))
            if usable:
                pages[raw['address']].append((digest, raw))
            page_receipts.append({"hash": digest, "payload": raw if usable else None, 'source': source})
        elif kind == "block-order":
            block_receipts.append({"hash": digest, "payload": raw})
    tx_map = cp.get("transactions", {}) if compatible else {}
    tx_map = tx_map if isinstance(tx_map, dict) else {}
    comparison_sources = dict(list(tx_map.items())[:MAX_RECORDS])
    selected_index_claims = {}
    if "transactions" in collected:
        selected = collected["transactions"]
        if not isinstance(selected, list):
            issues.append("The exact report transaction population is malformed.")
            tx_map = {}
        else:
            tx_map = {}
            for record in selected[:MAX_RECORDS + 1]:
                signature = record.get("signature") if isinstance(record, dict) else None
                digest = record.get("evidence_hash") if isinstance(record, dict) else None
                if not isinstance(signature, str) or not signature or not isinstance(digest, str) or not _HASH.fullmatch(digest) or signature in tx_map:
                    issues.append("The exact report transaction population contains malformed or duplicate references.")
                    continue
                tx_map[signature] = {"signature": signature, "evidence_hash": digest}
                if record.get("transaction_index") is not None:
                    selected_index_claims[signature] = record["transaction_index"]
            if len(selected) > MAX_RECORDS:
                issues.append("The exact report transaction population exceeds the inspection cap.")
    record_count = len(tx_map)
    if record_count > MAX_RECORDS:
        issues.append("Transaction inspection cap reached; omitted records remain unresolved.")
    tx_map = dict(list(tx_map.items())[:MAX_RECORDS])
    account_map = cp.get("accounts", {}) if compatible else {}
    account_map = account_map if isinstance(account_map, dict) else {}
    if len(account_map) > MAX_ACCOUNTS:
        issues.append("Account inspection cap reached; omitted accounts remain unresolved.")
    inspected_accounts = dict(list(account_map.items())[:MAX_ACCOUNTS])
    memberships, account_results = defaultdict(list), []
    # Metadata contradictions belong to linked signatures, even when the
    # account's full cursor chain is beyond the separate account inspection cap.
    for account_address, candidates in pages.items():
        for digest, page in candidates:
            params, entries = page.get("params"), page.get("result")
            params = params if isinstance(params, dict) else {}
            if (not anchored or params.get("commitment") != "finalized" or params.get("minContextSlot") != slot
                or type(params.get("limit")) is not int or not 1 <= params["limit"] <= 1000
                or not isinstance(entries, list) or len(entries) > params["limit"] or "until" in params):
                continue
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("signature"), str):
                    memberships[entry["signature"]].append((account_address, digest, entry))
    global_upper_anchor = False

    for account_address, account in inspected_accounts.items():
        errors, hashes, entries, chain = [], [], [], []
        account = account if isinstance(account, dict) else {}
        if not _valid_account(account_address) or account.get("address") != account_address:
            errors.append("Checkpoint account identity is malformed.")
        candidates = pages.get(account_address, [])
        by_cursor = defaultdict(list)
        for digest, page in candidates:
            params, result = page.get("params"), page.get("result")
            params = params if isinstance(params, dict) else {}
            valid = (anchored and params.get("commitment") == "finalized"
                     and _integer(params.get("minContextSlot")) and params.get("minContextSlot") == slot and type(params.get("limit")) is int
                     and 1 <= params["limit"] <= 1000 and isinstance(result, list)
                     and len(result) <= params["limit"] and "until" not in params)
            if not valid:
                errors.append("Archived signature-page request or response is incomplete.")
                continue
            before = params.get("before")
            if before is not None and (not isinstance(before, str) or not before):
                errors.append("Archived pagination cursor is malformed.")
                continue
            by_cursor[before].append((digest, result))
        cursor, seen_signatures, previous_slot = None, set(), None
        for _ in range(len(candidates) + 1):
            choices = by_cursor.get(cursor, [])
            if not choices:
                break
            # Repeated requests after a mid-page pause are harmless only when
            # the immutable response is identical. Divergent branches are gaps.
            unique = {digest: result for digest, result in choices}
            if len(unique) != 1:
                errors.append("Archived pagination has conflicting responses for one cursor.")
                break
            digest, result = next(iter(unique.items()))
            if digest in hashes:
                errors.append("Archived pagination repeats a page or cursor.")
                break
            hashes.append(digest)
            chain.append((digest, result))
            if not result:
                break
            valid_page = True
            for entry in result:
                signature = entry.get("signature") if isinstance(entry, dict) else None
                entry_slot = entry.get("slot") if isinstance(entry, dict) else None
                if not isinstance(signature, str) or not signature or signature in seen_signatures or not _integer(entry_slot) or (previous_slot is not None and entry_slot > previous_slot):
                    valid_page = False
                    break
                seen_signatures.add(signature)
                previous_slot = entry_slot
                entries.append(entry)
            if not valid_page:
                errors.append("Archived page signatures or descending slot order are invalid.")
                break
            cursor = result[-1]["signature"]
        if not chain:
            errors.append("No initial archived signature page starts the cursor chain.")
        connected = set(hashes)
        if any(digest not in connected for digest, _ in candidates):
            errors.append("A signature page is disconnected from the initial cursor chain.")
        terminal_hash = account.get("terminal_evidence")
        terminal_page = chain[-1][1] if chain else None
        terminal_verified = bool(chain and terminal_hash == chain[-1][0] and account.get("terminal"))
        if not terminal_verified:
            errors.append("No archived terminal page matches the checkpoint terminal receipt.")
        if account.get("cursor") != cursor:
            errors.append("Checkpoint cursor differs from the archived page chain.")
        # A short/full page is never completion evidence on its own.
        terminal_kind = "empty" if terminal_verified and terminal_page == [] else "bounded" if terminal_verified else None
        ownership_hash = account.get("ownership_evidence")
        owner_raw = read(ownership_hash)
        owner_verified = account_address == address and anchored and ownership_hash == anchor_hash
        if isinstance(owner_raw, dict) and owner_raw.get("method") == "getTokenAccountsByOwner" and owner_raw.get("owner") == address and owner_raw.get("program") in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            result = owner_raw.get("result")
            context = result.get("context") if isinstance(result, dict) else None
            values = result.get("value") if isinstance(result, dict) else None
            if isinstance(context, dict) and _integer(context.get("slot")) and anchored and context["slot"] >= slot and isinstance(values, list):
                for entry in values:
                    if not isinstance(entry, dict) or entry.get("pubkey") != account_address:
                        continue
                    info = entry
                    for key in ("account", "data", "parsed", "info"):
                        info = info.get(key) if isinstance(info, dict) else None
                    if isinstance(info, dict) and info.get("owner") == address:
                        owner_verified = True
        # Event-time token owner proves a specific observed boundary only.
        if isinstance(owner_raw, dict) and isinstance(owner_raw.get("meta"), dict):
            owner_keys = _keys(owner_raw)
            for name in ("preTokenBalances", "postTokenBalances"):
                balances = owner_raw["meta"].get(name, [])
                if not isinstance(balances, list):
                    continue
                for balance in balances:
                    index = balance.get("accountIndex") if isinstance(balance, dict) else None
                    if owner_keys and _integer(index) and index < len(owner_keys) and owner_keys[index] == account_address and balance.get("owner") == address:
                        owner_verified = True
        if not owner_verified:
            errors.append("Included account lacks an archived wallet or token-owner boundary proof.")
        account_results.append({"address": account_address, "origin": account.get("origin"),
                                "ownership": _check("PASS" if owner_verified else "UNKNOWN", "Observed ownership boundary only; historical ownership completeness is not established.", [ownership_hash] if owner_verified else []),
                                "chain": _check("PASS" if not errors else "UNKNOWN", "; ".join(errors) if errors else "Archived cursor chain and terminal receipt agree.", hashes),
                                "terminal_kind": terminal_kind, "entries": entries,
                                "errors": errors, "page_count": len(chain)})

    receipts, valid_raw = [], {}
    for signature, item in tx_map.items():
        item = item if isinstance(item, dict) else {}
        digest = item.get("evidence_hash")
        raw = read(digest)
        reasons, matches, matched_accounts = [], [], []
        if item.get("signature") != signature:
            reasons.append("Checkpoint transaction identity differs from its requested signature.")
        if digest not in transaction_links.get(signature, set()):
            reasons.append("Transaction archive is not linked by the collector transaction receipt.")
        if not isinstance(raw, dict):
            reasons.append("Archived native transaction is missing or fails checksum validation.")
        else:
            transaction, meta = raw.get("transaction"), raw.get("meta")
            signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
            keys = _keys(raw)
            if not isinstance(signatures, list) or not signatures or signatures[0] != signature:
                reasons.append("Requested and archived transaction signatures differ.")
            if not isinstance(meta, dict) or "err" not in meta:
                reasons.append("Explicit native execution status is missing.")
            if not _integer(raw.get("slot")) or not _integer(raw.get("blockTime")) or not anchored or raw.get("slot", slot + 1) > slot:
                reasons.append("Native slot/time do not meet the frozen finalized snapshot.")
            if not supported_transaction_format(raw):
                reasons.append("Native transaction format is unsupported by this application.")
            for account_address, page_hash, entry in memberships.get(signature, []):
                if (keys is not None and account_address in keys and _integer(entry.get("slot")) and entry.get("slot") == raw.get("slot")
                    and _integer(entry.get("blockTime")) and entry["blockTime"] == raw.get("blockTime")
                    and "err" in entry and isinstance(meta, dict) and "err" in meta and entry["err"] == meta["err"]
                    and entry.get("confirmationStatus") == "finalized"):
                    matches.append(page_hash)
                    matched_accounts.append(account_address)
            if not matches:
                reasons.append("No finalized archived signature page matches identity, slot, time, status and native account membership.")
        state = "UNKNOWN" if reasons else "PASS"
        if state == "PASS":
            valid_raw[signature] = raw
        receipts.append({"signature": signature, "hash": digest, "state": state,
                         "source": "local-native-collector" if state == "PASS" else "unverified-local-record",
                         "reason": "; ".join(reasons) if reasons else "Checksum-verified collector transaction and finalized native signature-page receipt agree.",
                         "accounts": sorted(set(matched_accounts)), "evidence": sorted(set(matches + ([digest, anchor_hash] if state == "PASS" else []))),
                         "slot": raw.get("slot") if isinstance(raw, dict) else None,
                         "block_time": raw.get("blockTime") if isinstance(raw, dict) else None})

    # A matching account receipt preserves an independent observed record. It
    # cannot resolve contradictory metadata in another account's paging chain.
    # Archived checkpoint records outside the selected report population may
    # reconcile boundary entries, but never enlarge observed arithmetic.
    canonical = {}
    for signature, item in {**comparison_sources, **tx_map}.items():
        item = item if isinstance(item, dict) else {}
        digest = item.get("evidence_hash")
        raw = read(digest)
        transaction = raw.get("transaction") if isinstance(raw, dict) else None
        meta = raw.get("meta") if isinstance(raw, dict) else None
        signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
        if (item.get("signature") == signature and digest in transaction_links.get(signature, set()) and isinstance(signatures, list)
            and signatures and signatures[0] == signature and isinstance(meta, dict) and "err" in meta
            and anchored and _integer(raw.get("slot")) and raw["slot"] <= slot and _integer(raw.get("blockTime"))
            and supported_transaction_format(raw) and _keys(raw) is not None):
            canonical[signature] = (digest, raw)
    conflicts, conflict_signatures = [], set()
    fields = ("slot", "blockTime", "err", "confirmationStatus")
    for signature, linked_entries in memberships.items():
        native = canonical.get(signature)
        observed_values = {field: {json.dumps(entry.get(field), sort_keys=True): entry.get(field)
                                  for _, _, entry in linked_entries} for field in fields}
        for account_address, page_hash, entry in linked_entries:
            mismatches = {}
            if native:
                digest, raw = native
                expected = {"slot": raw["slot"], "blockTime": raw["blockTime"],
                            "err": raw["meta"]["err"], "confirmationStatus": "finalized"}
                for field in fields:
                    typed = field not in ("slot", "blockTime") or _integer(entry.get(field))
                    if field not in entry or not typed or entry[field] != expected[field]:
                        mismatches[field] = expected[field]
                if account_address not in _keys(raw):
                    mismatches["account_membership"] = True
            else:
                digest = None
                for field in fields:
                    structurally_valid = (field in entry and
                                          (_integer(entry[field]) if field in ("slot", "blockTime") else
                                           entry[field] == "finalized" if field == "confirmationStatus" else True))
                    if not structurally_valid:
                        mismatches[field] = "finalized" if field == "confirmationStatus" else "explicit valid native metadata"
                    elif len(observed_values[field]) > 1:
                        mismatches[field] = "unresolved: linked account pages disagree"
            for field, expected_value in mismatches.items():
                conflict_signatures.add(signature)
                conflicts.append({"account": account_address, "signature": signature, "field": field,
                                  "page_hash": page_hash, "page_value": entry.get(field) if field != "account_membership" else False,
                                  "canonical_value": expected_value, "canonical_hash": digest,
                                  "reason": f"{account_address}: {signature} {field} conflicts with archived native metadata or linked account pages."})
    for account in account_results:
        own_conflicts = [conflict for conflict in conflicts if conflict["account"] == account["address"]]
        account["reconciliation"] = _check("UNKNOWN" if own_conflicts else "PASS", "; ".join(conflict["reason"] for conflict in own_conflicts) if own_conflicts else "Specific account-page metadata agrees with archived raw or consistent finalized boundary receipts.",
                                           [conflict["page_hash"] for conflict in own_conflicts],
                                           conflicting_signatures=sorted({conflict["signature"] for conflict in own_conflicts}))
    for receipt in receipts:
        own_conflicts = [conflict for conflict in conflicts if conflict["signature"] == receipt["signature"]]
        receipt["page_consistency"] = _check("UNKNOWN" if own_conflicts else "PASS", "; ".join(conflict["reason"] for conflict in own_conflicts) if own_conflicts else "No linked account-page metadata contradiction was found.",
                                             [conflict["page_hash"] for conflict in own_conflicts])

    def canonical_time(entry):
        native = canonical.get(entry.get("signature"))
        return native[1]["blockTime"] if native else entry.get("blockTime")

    def canonical_slot(entry):
        return chronology["placements"].get(entry.get("signature"), {}).get("slot")

    ordering = cp.get("ordering", {})
    ordering = ordering if isinstance(ordering, dict) else {}
    # Placement consumes every collector-linked raw archive, including missing
    # or malformed records and alternate hashes. The canonical comparison map
    # alone would erase exactly the contradictory source that may intersect an
    # account episode. This does not expand the selected arithmetic population.
    inspected_links = transaction_links if not source_index["budget_exceeded"] else {
        signature: {item["evidence_hash"]} for signature, item in tx_map.items()}
    placement_records = [{"signature": signature, "raw": read(digest), "evidence_hash": digest,
                          "transaction_index": selected_index_claims.get(signature)}
                         for signature, digests in inspected_links.items() for digest in sorted(digests)]
    chronology = assess_chronology(placement_records,
                                   page_receipts=page_receipts, block_receipts=block_receipts,
                                   checkpoint_indices=ordering, require_checkpoint_indices=True)
    apply_unresolved_chronology(chronology, placement_records, archive_contents)
    semantic_accounts = {signature: {account for account, _, _ in entries if account != address}
                         for signature, entries in memberships.items()}
    named_accounts = {account for account in account_map if _valid_account(account) and account != address}
    # Account-key membership is relevant even when an opaque operation has no
    # token-balance rows or the account's signature page omitted that record.
    # This scans the admitted dependency universe, not the selected arithmetic
    # prefix, and preserves page claims when native membership is unavailable.
    for record in placement_records:
        raw = record.get("raw")
        keys = _keys(raw) if isinstance(raw, dict) else None
        if keys:
            semantic_accounts.setdefault(record["signature"], set()).update(named_accounts.intersection(keys))
    source_consistency = assess_source_consistency(placement_records, wallet=address, source_index=source_index,
        inspected_hashes=attempted, page_receipts=page_receipts, archive_contents=archive_contents,
        accounts={signature: sorted(accounts) for signature, accounts in semantic_accounts.items()})
    source_consistency["source_set"]["universe"] = "frozen-manifest" if frozen_bound else "persisted-native-checkpoint"
    source_consistency["report_metadata"] = {key: value for key, value in report_metadata.items() if key != "references"}

    def possibly_anchored(entry):
        placement = chronology["placements"].get(entry.get("signature"), {})
        lower = placement.get("slot_bounds", {}).get("min")
        return anchored and (not _integer(lower) or lower <= slot)

    order_gaps = {signature for signature, check in chronology["transactions"].items() if check["state"] != "PASS"}
    # Connected boundary pages must also agree with all clocks for their slot.
    global_upper_anchor = any(entry.get("signature") not in conflict_signatures and anchored
                              and _integer(canonical_slot(entry)) and canonical_slot(entry) <= slot
                              and chronology["slots"].get(str(canonical_slot(entry)), {}).get("time_state") == "PASS"
                              and _integer(canonical_time(entry)) and canonical_time(entry) >= end
                              for account in account_results if account["chain"]["state"] == "PASS"
                              for entry in account["entries"])
    for receipt in receipts:
        check = chronology["transactions"].get(receipt["signature"], {})
        receipt["placement"] = chronology["placements"].get(receipt["signature"], {})
        receipt["source_consistency"] = source_consistency["transactions"].get(receipt["signature"], {})
        receipt["ordering"] = _check(check.get("state", "UNKNOWN") if receipt["state"] == "PASS" else "UNKNOWN",
                                     check.get("reason", "Native slot chronology is unresolved."), check.get("evidence", []),
                                     transaction_index=check.get("transaction_index"))
        receipt["time"] = _check(check.get("time_state", "UNKNOWN"), check.get("reason", "Native slot time is unresolved."),
                                 check.get("evidence", []), canonical_time=check.get("canonical_time"))
    for account in account_results:
        account_receipts = []
        for entry in account["entries"]:
            signature = entry["signature"]
            native = canonical.get(signature)
            hashes = {page_hash for account_address, page_hash, candidate in memberships.get(signature, [])
                      if account_address == account["address"] and candidate == entry}
            hashes.update([native[0], anchor_hash] if native else [])
            state = ("PASS" if native and signature in valid_raw and signature not in conflict_signatures
                     and account["chain"]["state"] == "PASS" else "UNKNOWN")
            check = chronology["transactions"].get(signature, {})
            account_receipts.append({"signature": signature, "state": state, "evidence": sorted(hashes),
                                     "hash": native[0] if native else None, "canonical_time": canonical_time(entry),
                                     "slot": canonical_slot(entry), "err": native[1]["meta"]["err"] if native else entry.get("err"),
                                     "confirmation_status": entry.get("confirmationStatus"),
                                     "placement": chronology["placements"].get(signature, {}),
                                     "source_consistency": source_consistency["transactions"].get(signature, {}).get("accounts", {}).get(account["address"], {}),
                                     "time": _check(check.get("time_state", "UNKNOWN"), check.get("reason", "Native slot time is unresolved."),
                                                    check.get("evidence", []), canonical_time=check.get("canonical_time")),
                                     "ordering": _check(check.get("state", "UNKNOWN") if state == "PASS" else "UNKNOWN",
                                                         check.get("reason", "Native slot chronology is unresolved."), check.get("evidence", []),
                                                         transaction_index=check.get("transaction_index"))})
        account["receipts"] = account_receipts
        seen = {receipt["signature"] for receipt in account_receipts}
        # The selected arithmetic population is not the dependency universe.
        # Every admitted native archive may reveal a missing account-page row.
        for signature, transaction in source_consistency["transactions"].items():
            if signature in seen or account["address"] not in transaction["accounts"]:
                continue
            candidate = next(((digest, read(digest)) for digest in transaction["native_hashes"]
                              if isinstance(read(digest), dict) and account["address"] in (_keys(read(digest)) or [])), None)
            if candidate is None:
                continue
            digest, raw = candidate
            check = chronology["transactions"].get(signature, {})
            account_receipts.append({"signature": signature, "state": "UNKNOWN", "hash": digest,
                "evidence": transaction["evidence"], "canonical_time": check.get("canonical_time"), "slot": check.get("slot"),
                "err": raw.get("meta", {}).get("err"), "confirmation_status": None,
                "source_consistency": transaction["accounts"][account["address"]],
                "placement": chronology["placements"].get(signature, {}),
                "time": _check(check.get("time_state", "UNKNOWN"), "Native account membership lacks a matching account-page receipt.", check.get("evidence", []), canonical_time=check.get("canonical_time")),
                "ordering": _check("UNKNOWN", "An admitted native archive mentions this account without its required page receipt.", check.get("evidence", []), transaction_index=check.get("transaction_index"))})

    scope = cp.get("account_scope", {})
    scope = scope if isinstance(scope, dict) else {}
    omitted = scope.get("omitted_account_count")
    scope_known = (compatible and _integer(omitted) and _integer(scope.get("included_account_count"))
                   and scope.get("included_account_count") == len(account_map))
    bounded_out = len(account_map) > MAX_ACCOUNTS or reference_count > MAX_REFERENCES or record_count > MAX_RECORDS
    native_bounded_out = reference_count > MAX_REFERENCES or record_count > MAX_RECORDS
    if not global_upper_anchor:
        issues.append("The archived snapshot has no chain timestamp at or after report end; minContextSlot alone does not prove the UTC upper boundary.")
    interval_results, paging_intervals = {}, {}
    for name, (lower, upper) in bounds.items():
        reasons = list(issues)
        reasons.extend(conflict["reason"] for conflict in conflicts)
        reasons.extend(conflict["reason"] for conflict in chronology["conflicts"])
        if not inspected_accounts or address not in inspected_accounts:
            reasons.append("The wallet account is absent from the enumerated paging scope.")
        if not scope_known or omitted != 0 or bounded_out:
            reasons.append("The declared enumerated account set is incomplete or exceeds the inspection bounds.")
        required, missing = set(), set()
        for account in account_results:
            reasons.extend(f"{account['address']}: {reason}" for reason in account["errors"])
            entries = [entry for entry in account["entries"] if possibly_anchored(entry)]
            lower_crossed = any(entry.get("signature") not in conflict_signatures and _integer(canonical_time(entry)) and canonical_time(entry) < lower for entry in entries)
            if account["terminal_kind"] != "empty" and not (account["terminal_kind"] == "bounded" and lower_crossed):
                reasons.append(f"{account['address']}: Archived terminal page does not reach this interval's lower boundary.")
            for entry in entries:
                timestamp = canonical_time(entry)
                signature = entry.get("signature")
                if not _integer(timestamp):
                    reasons.append(f"{account['address']}: A page entry has unknown time; interval membership is unresolved.")
                    continue
                if lower <= timestamp < upper:
                    required.add(signature)
                    if signature not in valid_raw or signature in order_gaps:
                        missing.add(signature)
        if missing:
            reasons.append("Required interval transaction receipts or chronology are missing: " + ", ".join(sorted(missing)))
        reasons = list(dict.fromkeys(reasons))
        state = "PASS" if not reasons else "UNKNOWN"
        paging_intervals[name] = _check(state, "; ".join(reasons) if reasons else "Archived requests, cursor chains, terminal pages, interval records and order verify the enumerated account scope.", used,
                                       required_transactions=len(required), missing_signatures=sorted(missing), scope="enumerated-accounts")
        interval_results[name] = {"start": _iso(lower), "end": _iso(upper), "status": "partial" if used else "unknown",
                                  "enumerated_scope_status": "complete" if state == "PASS" else "partial",
                                  "reason": "Global historical account ownership and economic completeness remain unproven; enumerated paging alone cannot certify wallet metrics.", "evidence": sorted(used)}
    requirements = {
        "history": ["global_historical_account_ownership", "report_period_records", "independent_four_week_records", "verification_interval_records"],
        "basis": ["opening_inventory_provenance", "earlier_acquisition_costs_for_disposed_units", "incoming_movement_acquisition_provenance"],
        "positions": ["historical_owned_balance_boundaries", "strict_zero_episode_reconstruction", "supported_economic_routes", "chronology"],
        "fees": ["all_wallet_paid_costs", "individual_native_movement_roles", "supported_fee_to_trade_allocations"],
        "classification": ["historical_asset_classification_with_primary_evidence"],
        "valuation": ["exact_report_boundary_inventory", "historical_boundary_marks", "valued_external_flows"],
        "identity": ["wallet_signer_and_system_owned_identity", "historical_token_account_ownership"],
        "findings": ["review_of_unsupported_routes_and_unexplained_movements", "primary_evidence_for_risk_decisions"],
    }
    decisions = {name: _check("UNKNOWN", "Current archived source types do not establish all required wallet-level evidence.", (), requirements=needed) for name, needed in requirements.items()}
    metric_needs = {
        "profit_sol": ["history", "basis", "fees", "classification"],
        "realised_roi_pct": ["history", "basis", "fees", "classification"],
        "median_roi_pct": ["history", "basis", "positions", "fees", "classification"],
        "win_rate_pct": ["history", "basis", "positions", "fees", "classification"],
        "median_hold_hours": ["history", "positions", "classification"],
        "completed_positions": ["history", "positions", "classification"],
        "completed_positions_90d": ["history", "positions", "classification"],
        "traded_mints": ["history", "classification"],
        "rapid_sale_pct": ["history", "positions", "classification"],
        "avg_buys": ["history", "positions", "classification"],
        "avg_sells": ["history", "positions", "classification"],
        "positive_weeks": ["history", "basis", "fees", "classification"],
        "largest_contribution_pct": ["history", "basis", "fees", "classification"],
        "economic_pnl_sol": ["history", "valuation"],
    }
    for metric, gates in metric_needs.items():
        name = "four_weeks" if metric == "positive_weeks" else "verification_90d" if metric == "completed_positions_90d" else "report_period"
        history_requirement = {"report_period": "report_period_records", "four_weeks": "independent_four_week_records",
                               "verification_90d": "verification_interval_records"}[name]
        needed = ["global_historical_account_ownership", history_requirement]
        needed += [item for gate in gates if gate != "history" for item in requirements[gate]]
        decisions[metric] = _check("UNKNOWN", "Required wallet evidence is unresolved; observed record arithmetic cannot substitute for the metric's supported population.", paging_intervals[name]["evidence"],
                                  interval=name, requirements=list(dict.fromkeys(needed)),
                                  enumerated_paging_state=paging_intervals[name]["state"])
    native_values = {signature: _native_amounts(raw, address) for signature, raw in valid_raw.items()}
    observed_known = bool(receipts) and len(valid_raw) == len(receipts) and all(value is not None for value in native_values.values()) and not native_bounded_out and not any("exact report transaction population" in issue for issue in issues)
    observed_hashes = [receipt["hash"] for receipt in receipts if receipt["state"] == "PASS"]
    observed_reason = ("Arithmetic for the explicitly observed archived record set; native delta is not profit and fees have no inferred trade allocation."
                       if observed_known else "The observed set contains missing primary receipts, omitted selected records, or native payer/balance endpoints that are missing or fail exact fee conservation.")
    native_observed = {}
    for index, name in enumerate(("wallet_network_fees_sol", "native_wallet_delta_sol")):
        checks = [source_consistency["transactions"].get(signature, {}).get("native", {}).get(name, {}) for signature in tx_map]
        consistent = observed_known and all(check.get("state") == "PASS" for check in checks)
        reason = observed_reason if consistent else "; ".join(dict.fromkeys(
            ([observed_reason] if not observed_known else []) +
            [check.get("reason", "A linked native metric source is unavailable.") for check in checks if check.get("state") != "PASS"]))
        hashes = observed_hashes + [digest for check in checks for digest in check.get("evidence", [])]
        native_observed[name] = _native_metric(sum(value[index] for value in native_values.values()) if consistent else None,
                                               "PASS" if consistent else "UNKNOWN", reason, hashes, len(receipts), "observed-record-set")
    wallet_checks, native_period = {}, {}
    wallet_account = next((account for account in account_results if account["address"] == address), None)
    for name, (lower, upper) in bounds.items():
        reasons = []
        reasons.extend(conflict["reason"] for conflict in conflicts)
        reasons.extend(conflict["reason"] for conflict in chronology["conflicts"])
        required = set()
        if not compatible or not anchored or not global_upper_anchor or wallet_account is None:
            reasons.append("A matching anchored wallet-address page chain and frozen UTC upper boundary are required.")
        reasons.extend(issue for issue in issues if "exact report transaction population" in issue or "absent from the persisted" in issue)
        if wallet_account:
            reasons.extend(wallet_account["errors"])
            entries = wallet_account["entries"]
            if wallet_account["terminal_kind"] != "empty" and not (wallet_account["terminal_kind"] == "bounded" and any(entry.get("signature") not in conflict_signatures and _integer(canonical_time(entry)) and canonical_time(entry) < lower for entry in entries)):
                reasons.append("Wallet-address terminal page does not reach this interval's lower boundary.")
            for entry in entries:
                timestamp = canonical_time(entry)
                if not _integer(timestamp):
                    reasons.append("Wallet-address page has an entry with unknown interval membership.")
                elif possibly_anchored(entry) and lower <= timestamp < upper:
                    required.add(entry["signature"])
        missing = sorted(signature for signature in required if signature not in valid_raw or native_values.get(signature) is None
                         or chronology["transactions"].get(signature, {}).get("time_state") != "PASS")
        if missing:
            reasons.append("Required native payer/balance records are missing or fail exact fee conservation: " + ", ".join(missing))
        if native_bounded_out:
            reasons.append("Inspection cap prevents complete wallet-address interval certification.")
        state = "UNKNOWN" if reasons else "PASS"
        wallet_checks[name] = _check(state, "; ".join(dict.fromkeys(reasons)) if reasons else "Wallet-address page chain and native endpoints cover the frozen interval; historical token ownership is outside this native-address total.", used,
                                    required_transactions=len(required), missing_signatures=missing, scope="wallet-address")
        hashes = [tx_map[signature]["evidence_hash"] for signature in sorted(required) if signature in valid_raw]
        hashes += wallet_checks[name]["evidence"]
        native_period[name] = {}
        for index, metric in enumerate(("wallet_network_fees_sol", "native_wallet_delta_sol")):
            checks = [source_consistency["transactions"].get(signature, {}).get("native", {}).get(metric, {}) for signature in required]
            consistent = state == "PASS" and all(check.get("state") == "PASS" for check in checks)
            reason = ("Sum of transaction endpoint changes for the wallet-address interval; rewards and other nontransaction changes are outside this total, and it is not economic P&L."
                      if consistent else "; ".join(dict.fromkeys(([wallet_checks[name]["reason"]] if state != "PASS" else []) +
                      [check.get("reason", "A linked native metric source is unavailable.") for check in checks if check.get("state") != "PASS"])))
            metric_hashes = hashes + [digest for check in checks for digest in check.get("evidence", [])]
            native_period[name][metric] = _native_metric(sum(native_values[signature][index] for signature in required) if consistent else None,
                                                       "PASS" if consistent else "UNKNOWN", reason, metric_hashes, len(required), "wallet-address-interval")
    limitations = list(dict.fromkeys(issues + ["Global historical ownership is not established by wallet pages, current token-account enumeration or event-time owner observations.",
        "An empty or bounded page never supplies zero opening inventory or earlier acquisition cost.",
        "Current account snapshots with minContextSlot are not exact report boundary equity or historical valuation.",
        "Local native collection receipts depend on the archived collector/provider trust boundary; hashes do not independently authenticate mainnet."]))
    recovery = [{"key": name, "state": "UNKNOWN", "requirements": needed} for name, needed in requirements.items()]
    recovery.insert(0, {"key": "enumerated_paging", "state": "PASS" if all(check["state"] == "PASS" for check in paging_intervals.values()) else "UNKNOWN",
                        "requirements": ["Resume the same frozen checkpoint and account scope until every required cursor chain, terminal page, native record and same-slot order receipt exists.", "Archive a finalized chain timestamp establishing the report upper boundary."],
                        "missing_signatures": sorted({sig for check in paging_intervals.values() for sig in check["missing_signatures"]})})
    # Do not leak bulky native page entries into the durable certificate.
    for account in account_results:
        account.pop("entries")
        account.pop("errors")
    return {"version": VERSION, "window": {"start": _iso(start), "end": _iso(end)},
            "verification_days": verification_days, "intervals": interval_results,
            "account_scope": {"kind": "enumerated-accounts", "included_account_count": len(inspected_accounts),
                              "omitted_account_count": omitted if _integer(omitted) else None,
                              "global_historical_ownership": "UNKNOWN", "wallet_history_complete": False},
            "paging": {"state": "PASS" if all(check["state"] == "PASS" for check in paging_intervals.values()) else "UNKNOWN",
                       "intervals": paging_intervals, "wallet_address_intervals": wallet_checks, "accounts": account_results,
                       "conflicts": conflicts, "chronology": chronology},
            "source_consistency": source_consistency,
            "source_set": source_consistency["source_set"],
            "record_provenance": {"trust_boundary": "local-native-collector receipts; no independent mainnet authentication",
                                  "state": "PASS" if receipts and all(receipt["state"] == "PASS" for receipt in receipts) else "UNKNOWN",
                                  "records": receipts, "counts": {"inspected": len(receipts), "local_native_receipts": sum(receipt["state"] == "PASS" for receipt in receipts),
                                                                      "unresolved": sum(receipt["state"] != "PASS" for receipt in receipts)}},
            "metric_decisions": decisions, "evidence_gates": {name: decisions[name]["state"] for name in requirements},
            "native_address_metrics": {"observed": native_observed, "periods": native_period,
                                       "notes": ["Native-address totals do not require global historical token ownership.", "Native wallet delta is the sum of selected transaction endpoint changes, including swaps, rent, transfers and fees; rewards and other nontransaction changes are outside this total, and it is not wallet profit.", "Exact network fee payment does not establish economic fee allocation."]},
            "limitations": limitations, "recovery_requirements": recovery, "evidence": sorted(used)}
