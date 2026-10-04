"""Pure slot chronology checks; callers establish archived-source provenance.

Every transaction in one native slot has one block timestamp. Signature order
cannot reconcile different timestamps, and conflicting block receipts cannot
be resolved by choosing their arrival order. Missing optional blockTime supplies
no time fact. Quantities, native fees and source identity are separate checks.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re

VERSION = "slot-chronology-evidence-v3"


def _integer(value):
    return type(value) is int and value >= 0


def _hash(value):
    return value if isinstance(value, str) and value else None


def _indexed_claims(receipts, records):
    """Validate byte envelopes and retain scoped rejecting placement claims.

    Frozen pointer associations can only add negative dependencies. A page's
    parsed native transactionIndex is order proof only after exact-byte/page
    validation; standalone raw indices and caller PASS flags are never proof.
    """
    from .indexed_input import validate_page_envelope, MAX_PAGES, MAX_LINKS
    associations, native_slots, signatures = defaultdict(set), defaultdict(set), set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('signature'), str):
            continue
        signature = record['signature']
        signatures.add(signature)
        if isinstance(record.get('indexed_source_hash'), str):
            associations[record['indexed_source_hash']].add(signature)
        raw = record.get('raw')
        if isinstance(raw, dict) and _integer(raw.get('slot')):
            native_slots[signature].add(raw['slot'])
    receipts, facts, audit, fact_keys = list(receipts), [], [], set()

    def add(signature, digest, *, slot=None, timestamp=None, index=None, accepted=False,
            bounded=False, path=None, reason=None):
        if not isinstance(signature, str) or not signature:
            return
        fact = {'signature': signature, 'hash': _hash(digest), 'slot': slot if _integer(slot) else None,
                'timestamp': timestamp, 'index': index, 'accepted': accepted,
                'bounded': bounded, 'raw_path': path, 'reason': reason}
        key = json.dumps(fact, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if key not in fact_keys:
            fact_keys.add(key)
            facts.append(fact)

    if len(receipts) > MAX_PAGES:
        for signature in signatures:
            add(signature, None, reason='Indexed source inspection budget exceeded')
        return facts, [{'hash': None, 'state': 'UNKNOWN', 'reason': 'Indexed source inspection budget exceeded'}]
    seen, indexed_count = set(), 0
    for receipt in receipts:
        digest = _hash(receipt.get('hash')) if isinstance(receipt, dict) else None
        payload = receipt.get('payload') if isinstance(receipt, dict) else None
        # The same frozen source is one claim. A substituted payload does not
        # win by arrival order: process its rejection as an additional claim.
        try:
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            verified = (isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest)
                        and hashlib.sha256(encoded).hexdigest() == digest)
        except (ValueError, TypeError, UnicodeError):
            encoded, verified = b'', False
        key = digest, hashlib.sha256(encoded).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        if not verified:
            reason = 'Still-linked indexed source is missing, corrupt or checksum-mismatched.'
            affected = associations[digest] or signatures
            for signature in affected:
                add(signature, digest, reason=reason)
            audit.append({'hash': _hash(digest), 'state': 'UNKNOWN', 'reason': reason, 'signatures': sorted(affected)})
            continue
        page = validate_page_envelope(payload)
        indexed_count += len(page['records'])
        if indexed_count > MAX_LINKS:
            facts, fact_keys = [], set()
            for signature in signatures:
                add(signature, None, reason='Indexed native record inspection budget exceeded')
            return facts, [{'hash': None, 'state': 'UNKNOWN', 'reason': 'Indexed native record inspection budget exceeded'}]
        reason = page['reason']
        header = page.get('request_scope') is not None
        bad_ordinals = set(page['unassignable_records']) | {row['ordinal'] for row in page['record_gaps']}

        def accepted_row(ordinal, slot):
            if page['state'] == 'PASS':
                return True
            # Only a known disjoint malformed sibling may be excluded. Bad
            # header/cursor/global order metadata cannot become index proof.
            if (not header or reason != 'Indexed page contains unassignable, duplicate or incomplete native entries'
                or ordinal in bad_ordinals or None in bad_ordinals or not bad_ordinals or not _integer(slot)):
                return False
            for bad in bad_ordinals:
                source = page['records'][bad]
                bad_slot = source.get('slot') if isinstance(source, dict) else None
                if not _integer(bad_slot) or bad_slot == slot:
                    return False
            return True
        scoped, unassignable = set(), []
        for ordinal, raw in enumerate(page['records']):
            tx = raw.get('transaction') if isinstance(raw, dict) else None
            identity = tx.get('signatures') if isinstance(tx, dict) else None
            signature = identity[0] if (isinstance(identity, list) and identity and isinstance(identity[0], str)
                and 1 <= len(identity[0]) <= 128) else None
            slot = raw.get('slot') if isinstance(raw, dict) else None
            timestamp = raw.get('blockTime') if isinstance(raw, dict) else None
            index = raw.get('transactionIndex') if isinstance(raw, dict) else None
            bounded = header and _integer(slot)
            path = f'result.data.{ordinal}'
            if signature is None:
                unassignable.append((slot if bounded else None, timestamp, path))
                continue
            scoped.add(signature)
            valid_clock = _integer(timestamp)
            if valid_clock:
                try:
                    datetime.fromtimestamp(timestamp, timezone.utc)
                except (ValueError, OverflowError, OSError):
                    valid_clock = False
            add(signature, digest, slot=slot, timestamp=timestamp if header and valid_clock else None, index=index,
                accepted=accepted_row(ordinal, slot) and valid_clock, bounded=bounded, path=path, reason=reason)
        # Every known pointer remains dependent on its page even if malformed
        # contents lost the linked record entirely.
        for signature in associations[digest] - scoped:
            add(signature, digest, reason='Frozen indexed pointer signature is absent from its source page.')
        for slot, timestamp, path in unassignable:
            for signature in signatures:
                if slot is not None and native_slots[signature] and slot not in native_slots[signature]:
                    continue  # Exact readable raw placement proves this gap disjoint.
                add(signature, digest, slot=slot, timestamp=timestamp if header else None,
                    bounded=slot is not None, path=path, reason='An indexed entry has no assignable native signature.')
        if not page['records'] and page['state'] != 'PASS':
            for signature in associations[digest] or signatures:
                add(signature, digest, reason=reason)
        audit.append({'hash': _hash(digest), 'state': page['state'], 'reason': reason,
                      'signatures': sorted(scoped), 'unassignable_record_count': len(unassignable)})
    return facts, audit


def reconcile_placements(records, *, page_receipts=(), block_receipts=(), indexed_receipts=(), checkpoint_indices=None):
    """Keep the envelope of every linked location claim, never a preferred slot.

    A coherent page can bound a missing native record, but cannot authenticate
    its quantities. Contradictory finite claims retain their entire slot/index
    envelope: an episode may exclude it only if that envelope is disjoint.
    """
    records = list(records)
    indexed_facts, _ = _indexed_claims(indexed_receipts, records)
    claims, block_sources = defaultdict(list), defaultdict(list)
    checkpoint_indices = checkpoint_indices if isinstance(checkpoint_indices, dict) else {}

    def add(signature, kind, slot, digest, *, index=None, account=None, invalid=False, unbounded=False, raw_path=None):
        if not isinstance(signature, str) or not signature:
            return
        fact = {"kind": kind, "slot": slot if _integer(slot) else None,
                "hash": _hash(digest)}
        if index is not None:
            fact["index"] = index if _integer(index) else None
        if account is not None:
            fact["account"] = account
        if raw_path is not None:
            fact['raw_path'] = raw_path
        if invalid:
            fact["incomplete"] = True
        if unbounded:
            fact["unbounded"] = True
        if fact not in claims[signature]:
            claims[signature].append(fact)

    for record in records:
        if not isinstance(record, dict):
            continue
        supplied_raw = record.get("raw")
        raw = supplied_raw if isinstance(supplied_raw, dict) else {}
        signature = record.get("signature")
        transaction = raw.get("transaction")
        signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
        identity = isinstance(signatures, list) and bool(signatures) and signatures[0] == signature
        add(signature, "transaction", raw.get("slot") if identity else None, record.get("evidence_hash"),
            invalid=not identity or not _integer(raw.get("slot")),
            unbounded=supplied_raw is not None and (not identity or not _integer(raw.get("slot"))))
        if record.get("transaction_index") is not None:
            add(signature, "saved-index", None, record.get("evidence_hash"), index=record["transaction_index"],
                invalid=not _integer(record["transaction_index"]))
    for receipt in page_receipts:
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        entries = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                add(entry.get("signature"), "signature-page", entry.get("slot"), receipt.get("hash"),
                    account=payload.get("address"), invalid=not _integer(entry.get("slot")),
                    unbounded=not _integer(entry.get("slot")))
    for fact in indexed_facts:
        add(fact['signature'], 'indexed-page', fact['slot'], fact['hash'], index=fact['index'],
            invalid=not fact['accepted'], unbounded=not fact['bounded'], raw_path=fact['raw_path'])
    for receipt in block_receipts:
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        result = payload.get("result") if isinstance(payload, dict) else None
        signatures = result.get("signatures") if isinstance(result, dict) else None
        if not isinstance(signatures, list):
            continue
        valid = (payload.get("method") == "getBlock" and _integer(payload.get("slot"))
                 and all(isinstance(value, str) and value for value in signatures)
                 and len(set(value for value in signatures if isinstance(value, str))) == len(signatures))
        if _integer(payload.get("slot")):
            block_sources[payload["slot"]].append((signatures, valid))
        for index, signature in enumerate(signatures):
            # Whole block lists are order proof, not an additional wallet
            # observation population. Retain facts for linked raw/page leads.
            if not isinstance(signature, str) or signature not in claims:
                continue
            add(signature, "block-order", payload.get("slot"), receipt.get("hash"),
                index=index, invalid=not valid, unbounded=not _integer(payload.get("slot")))

    result = {}
    for signature, facts in claims.items():
        if signature in checkpoint_indices:
            add(signature, "checkpoint-index", None, None, index=checkpoint_indices[signature],
                invalid=not _integer(checkpoint_indices[signature]))
        candidates = sorted({fact["slot"] for fact in facts if _integer(fact["slot"])})
        issues = []
        if len(candidates) > 1:
            issues.append("Linked native, account-page or block receipts disagree on transaction slot.")
        if any(fact.get("incomplete") for fact in facts):
            issues.append("A linked placement source is missing or has invalid slot/index metadata.")
        if not candidates:
            issues.append("No linked source bounds this transaction's possible slot.")
        native_facts = [fact for fact in facts if fact["kind"] == "transaction"]
        missing_alternative = (len({fact.get("hash") for fact in native_facts}) > 1
                               and any(fact["slot"] is None for fact in native_facts))
        if missing_alternative:
            issues.append("An unavailable distinct native archive leaves an alternative transaction placement unbounded.")
        indices = {}
        for slot in candidates:
            blocks = [fact for fact in facts if fact["kind"] == "block-order" and fact["slot"] == slot]
            indexed = [fact for fact in facts if fact['kind'] == 'indexed-page' and fact['slot'] == slot]
            values = sorted({fact["index"] for fact in facts
                             if fact["kind"] in ("saved-index", "checkpoint-index") or fact in blocks + indexed
                             if _integer(fact.get("index"))})
            bounded = bool(blocks or indexed) and all(not fact.get("incomplete") for fact in blocks + indexed +
                                          [fact for fact in facts if fact["kind"] in ("saved-index", "checkpoint-index")])
            bounded = bounded and all(valid and signature in signatures for signatures, valid in block_sources[slot])
            if len(values) > 1:
                issues.append(f"Linked block/indexed/saved order claims disagree for slot {slot}.")
            indices[str(slot)] = {"bounded": bounded, "min": min(values) if bounded else None,
                                  "max": max(values) if bounded else None, "possible_indices": values}
        slot_state = "PASS" if len(candidates) == 1 and not any(
            fact.get("incomplete") and fact["kind"] == "transaction" or
            fact["kind"] in ("signature-page", "block-order", "indexed-page") and fact["slot"] is None
            for fact in facts) else "UNKNOWN"
        state = "PASS" if candidates and not issues else "UNKNOWN"
        evidence = sorted({fact["hash"] for fact in facts if fact.get("hash")})
        unbounded = not candidates or missing_alternative or any(fact.get("unbounded") for fact in facts)
        result[signature] = {"state": state, "slot_state": slot_state,
                             "slot": candidates[0] if slot_state == "PASS" else None,
                             "possible_slots": candidates,
                             "slot_bounds": {"bounded": not unbounded, "min": min(candidates) if candidates else None,
                                             "max": max(candidates) if candidates else None},
                             "indices_by_slot": indices, "unbounded": unbounded,
                             "evidence": evidence, "facts": facts, "conflicts": list(dict.fromkeys(issues)),
                             "reason": "; ".join(dict.fromkeys(issues)) if issues else "All linked slot placement claims agree; absent block order spans the entire slot."}
    return result


def assess_chronology(records, *, page_receipts=(), block_receipts=(), indexed_receipts=(),
                      checkpoint_indices=None, require_checkpoint_indices=False):
    """Assess native records and all linked page/block facts for their slots.

    Records are {signature, raw, evidence_hash, transaction_index?}; archived
    receipt wrappers are {hash, payload}. Inputs are facts, never PASS flags.
    Explicit contradictions appear in conflicts. Missing proof is UNKNOWN.
    A contradictory time never invalidates independently checked quantities.
    """
    records, page_receipts, block_receipts, indexed_receipts = list(records), list(page_receipts), list(block_receipts), list(indexed_receipts)
    indexed_facts, indexed_audit = _indexed_claims(indexed_receipts, records)
    placements = reconcile_placements(records, page_receipts=page_receipts, block_receipts=block_receipts,
                                      indexed_receipts=indexed_receipts, checkpoint_indices=checkpoint_indices)
    slots = defaultdict(lambda: {"records": {}, "times": [], "blocks": [], "evidence": set(),
                                 "saved_indices": defaultdict(list), 'indexed_indices': defaultdict(list)})
    transactions, conflicts, invalid_blocks = {}, [], False
    checkpoint_indices = checkpoint_indices if isinstance(checkpoint_indices, dict) else {}

    def conflict(slot, kind, field, reason, evidence=()):
        item = {"slot": slot, "kind": kind, "field": field, "reason": reason,
                "evidence": sorted({value for value in evidence if _hash(value)})}
        if item not in conflicts:
            conflicts.append(item)

    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("signature"), str):
            continue
        signature, raw = record["signature"], record.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        slot, timestamp, digest = raw.get("slot"), raw.get("blockTime"), _hash(record.get("evidence_hash"))
        if not _integer(slot):
            transactions[signature] = {"state": "UNKNOWN", "time_state": "UNKNOWN", "order_state": "UNKNOWN",
                                       "slot": slot, "canonical_time": None, "transaction_index": None,
                                       "evidence": [digest] if digest else [], "reason": "Native slot is missing or invalid.", "conflicts": []}
            continue
        group = slots[slot]
        if signature in group["records"] and group["records"][signature].get("raw", {}).get("blockTime") != timestamp:
            conflict(slot, "time", "transaction", "Different archived native records claim the same transaction.", [digest])
        group["records"][signature] = record
        if record.get("transaction_index") is not None:
            group["saved_indices"][signature].append(record["transaction_index"])
        group["times"].append((timestamp, digest, "transaction", signature))
        if digest:
            group["evidence"].add(digest)
    for receipt in page_receipts:
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        entries = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            continue
        digest = _hash(receipt.get("hash"))
        for entry in entries:
            if not isinstance(entry, dict) or not _integer(entry.get("slot")):
                continue
            group = slots[entry["slot"]]
            group["times"].append((entry.get("blockTime"), digest, "signature-page", entry.get("signature")))
            if digest:
                group["evidence"].add(digest)
    for fact in indexed_facts:
        slot = fact['slot']
        if not _integer(slot):
            continue
        group = slots[slot]
        group['times'].append((fact['timestamp'], fact['hash'], 'indexed-page', fact['signature']))
        group['indexed_indices'][fact['signature']].append((fact['index'], fact['accepted']))
        if fact['hash']:
            group['evidence'].add(fact['hash'])
    for receipt in block_receipts:
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        digest = _hash(receipt.get("hash")) if isinstance(receipt, dict) else None
        slot = payload.get("slot") if isinstance(payload, dict) else None
        result = payload.get("result") if isinstance(payload, dict) else None
        signatures = result.get("signatures") if isinstance(result, dict) else None
        valid = (isinstance(payload, dict) and payload.get("method") == "getBlock" and _integer(slot)
                 and isinstance(signatures, list) and all(isinstance(signature, str) and signature for signature in signatures)
                 and len(set(signatures)) == len(signatures))
        if not valid:
            invalid_blocks = True
            conflict(slot if _integer(slot) else None, "order", "block_receipt", "Archived block ordering is invalid.", [digest])
            if _integer(slot) and digest:
                slots[slot]["evidence"].add(digest)
            continue
        group = slots[slot]
        group["blocks"].append((tuple(signatures), digest))
        if digest:
            group["evidence"].add(digest)
        # null/absent is an unavailable optional fact, never a contradictory
        # replacement for known native/page timestamps.
        if result.get("blockTime") is not None:
            group["times"].append((result["blockTime"], digest, "block", None))

    assessed_slots = {}
    for slot, group in slots.items():
        rows, facts, block_rows = group["records"], group["times"], group["blocks"]
        known_times = {timestamp for timestamp, _, _, _ in facts if _integer(timestamp)}
        missing_time = any(not _integer(timestamp) for timestamp, _, _, _ in facts)
        if len(known_times) > 1:
            conflict(slot, "time", "blockTime", "Transactions, signature pages or block receipts in one slot disagree on blockTime.", group["evidence"])
        if any(origin == "block" and not _integer(timestamp) for timestamp, _, origin, _ in facts):
            conflict(slot, "time", "blockTime", "An explicit archived blockTime is invalid.", group["evidence"])
        orders = {signatures for signatures, _ in block_rows}
        if len(orders) > 1:
            conflict(slot, "order", "signatures", "Archived block ordering conflicts; different signature lists cannot be reconciled by receipt order.", [digest for _, digest in block_rows])
        block_order = next(iter(orders)) if len(orders) == 1 else None
        claimed_indices = defaultdict(set)
        for signature, record in rows.items():
            indexed = group['indexed_indices'][signature]
            claims = [checkpoint_indices.get(signature)] + group["saved_indices"][signature] + [value for value, _ in indexed]
            supplied = [value for value in claims if value is not None]
            if any(not _integer(value) for value in supplied):
                conflict(slot, "order", "transaction_index", "Saved transaction/checkpoint index is invalid.", group["evidence"])
            known_claims = {value for value in supplied if _integer(value)}
            if any(not accepted for _, accepted in indexed):
                conflict(slot, 'order', 'indexed_page', 'A linked indexed order source is malformed or incomplete.', group['evidence'])
            if len(known_claims) > 1:
                conflict(slot, "order", "transaction_index", "Saved transaction and checkpoint indices conflict.", group["evidence"])
            for index in known_claims:
                claimed_indices[index].add(signature)
        if any(len(signatures) > 1 for signatures in claimed_indices.values()):
            conflict(slot, "order", "transaction_index", "Different transactions in one slot claim the same saved index.", group["evidence"])
        if block_order is not None:
            for signature, record in rows.items():
                if signature not in block_order:
                    conflict(slot, "order", "signature_membership", "Archived block ordering omits a native transaction claiming this slot.", group["evidence"])
                    continue
                index = block_order.index(signature)
                claims = [checkpoint_indices.get(signature)] + group["saved_indices"][signature] + [value for value, _ in group['indexed_indices'][signature]]
                if any(value is not None and (not _integer(value) or value != index) for value in claims):
                    conflict(slot, "order", "transaction_index", "Saved transaction/checkpoint index conflicts with archived block ordering.", group["evidence"])
        # An unassignable malformed source remains an audit/interval issue. It
        # cannot silently invalidate a separate slot's independent chronology.
        slot_conflicts = [item for item in conflicts if item["slot"] == slot]
        time_state = "PASS" if len(known_times) == 1 and not missing_time and not any(item["kind"] == "time" for item in slot_conflicts) else "UNKNOWN"
        indexed_complete = bool(rows) and all(group['indexed_indices'][signature]
            and all(accepted and _integer(value) for value, accepted in group['indexed_indices'][signature])
            for signature in rows)
        order_complete = (not any(item["kind"] == "order" for item in slot_conflicts)
                          and (len(rows) < 2 or block_order is not None or indexed_complete)
                          and (not require_checkpoint_indices or len(rows) < 2 or indexed_complete or all(_integer(checkpoint_indices.get(signature)) for signature in rows)))
        order_state = "PASS" if order_complete else "UNKNOWN"
        state = "PASS" if time_state == order_state == "PASS" else "UNKNOWN"
        reason = "; ".join(item["reason"] for item in slot_conflicts)
        if not reason and state != "PASS":
            reason = "Native slot timestamp or archived same-slot ordering proof is incomplete."
        if not reason:
            reason = "Native/page slot timestamps and all supplied block/index receipts agree."
        evidence = sorted(group["evidence"])
        canonical_time = next(iter(known_times)) if time_state == "PASS" else None
        assessed_slots[str(slot)] = {"state": state, "time_state": time_state, "order_state": order_state,
                                    "canonical_time": canonical_time, "signatures": sorted(rows),
                                    "time_facts": sorted([
                                        {"timestamp": timestamp, "hash": digest, "kind": origin, "signature": signature}
                                        for timestamp, digest, origin, signature in facts],
                                        key=lambda fact: (fact['kind'], json.dumps(fact['signature'], sort_keys=True), fact['hash'] or '', repr(fact['timestamp']))),
                                    "evidence": evidence, "reason": reason, "conflicts": slot_conflicts}
        for signature in rows:
            index = block_order.index(signature) if order_state == "PASS" and block_order is not None and signature in block_order else None
            if index is None and order_state == 'PASS' and group['indexed_indices'][signature]:
                accepted_indices = {value for value, accepted in group['indexed_indices'][signature] if accepted and _integer(value)}
                if len(accepted_indices) == 1:
                    index = next(iter(accepted_indices))
            transactions[signature] = {"state": state, "time_state": time_state, "order_state": order_state,
                                       "slot": slot, "canonical_time": canonical_time, "transaction_index": index,
                                       "evidence": evidence, "reason": reason, "conflicts": slot_conflicts}
    for signature, placement in placements.items():
        row = transactions.setdefault(signature, {"state": "UNKNOWN", "time_state": "UNKNOWN", "order_state": "UNKNOWN",
                                                  "slot": placement["slot"], "canonical_time": None, "transaction_index": None,
                                                  "evidence": placement["evidence"], "reason": "Native source chronology is unavailable.", "conflicts": []})
        row["placement"] = placement
        if placement["state"] != "PASS":
            row.update(state="UNKNOWN", order_state="UNKNOWN", transaction_index=None)
            if placement["slot_state"] != "PASS":
                row.update(time_state="UNKNOWN", slot=None, canonical_time=None)
            row["reason"] = placement["reason"]
            for reason in placement["conflicts"]:
                item = {"slot": None, "signature": signature, "kind": "placement", "field": "slot_or_index",
                        "reason": reason, "evidence": placement["evidence"]}
                conflicts.append(item)
                row["conflicts"] = row["conflicts"] + [item]
    return {"version": VERSION, "state": "PASS" if transactions and not conflicts and all(row['state'] == 'PASS' for row in indexed_audit) and all(row["state"] == "PASS" for row in transactions.values()) else "UNKNOWN",
            "transactions": transactions, "slots": assessed_slots, "conflicts": conflicts,
            "placements": placements, "invalid_block_receipts": invalid_blocks, 'indexed_sources': indexed_audit}


def assess_interval_membership(chronology, signature, start, end):
    """Project every bounded clock possibility onto one half-open interval.

    Fee addition needs interval membership, not exact time or same-slot order.
    Disagreeing clocks all inside (or all outside) may support this narrower
    fact. Missing/unbounded clocks and a boundary-crossing disagreement may not.
    Callers derive chronology from raw sources; client declarations are not
    accepted as chronology certificates by the application.
    """
    placement = chronology['placements'].get(signature, {})
    evidence = set(placement.get('evidence', []))
    memberships = set()
    reason = None
    if placement.get('unbounded', True) or not placement.get('possible_slots'):
        reason = 'A linked transaction has unbounded or unavailable clock placement.'
    for slot in placement.get('possible_slots', []):
        facts = chronology['slots'].get(str(slot), {}).get('time_facts', [])
        if not facts:
            reason = 'A possible transaction slot lacks a supported time fact.'
        for fact in facts:
            if fact.get('hash'):
                evidence.add(fact['hash'])
            timestamp = fact.get('timestamp')
            try:
                if not _integer(timestamp):
                    raise ValueError('Invalid clock')
                when = datetime.fromtimestamp(timestamp, timezone.utc)
                memberships.add(start <= when < end)
            except (ValueError, OverflowError, OSError):
                reason = 'A linked required timestamp is missing, malformed or outside the supported UTC range.'
    if len(memberships) != 1:
        reason = reason or 'Linked clock possibilities disagree about reporting-window membership.'
    return {'state': 'UNKNOWN' if reason else 'PASS', 'member': None if reason else next(iter(memberships)),
            'reason': reason or 'All bounded clock possibilities agree on this half-open interval; exact time/order is a separate fact.',
            'evidence': sorted(evidence)}
