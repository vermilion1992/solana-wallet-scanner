"""Semantic consistency of collector-linked native facts, without provider IO.

Callers authenticate archive links. Agreement is not mainnet authentication,
wallet-history completeness, or route validity. Each metric receives only its
own dependency checks; optional logs and JSON/array order are not facts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re

from .providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from .transaction_format import supported_transaction_format

VERSION = "source-consistency-v5"
SOURCE_HASH_LIMIT = 40_000
_U64 = 2**64 - 1
_TOKEN_IDS = {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}
_QUANTITY = re.compile(r"[0-9]+")
_HASH = re.compile(r"[a-f0-9]{64}")
_ROLES = {"transaction", "signature-page", "block-order", "snapshot-slot", "owned-accounts", "native-balance",
          "indexed-page", "indexed-native-source", "indexed-input-manifest"}


def _indexed_payload(payload, digest):
    """Typed indexed wrappers require their canonical archive and original bytes.

    An annotated role, a cached producer receipt or a supplied PASS is never
    sufficient. Byte decoding/response checks belong to indexed_input.
    """
    if not isinstance(payload, dict) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
        return False
    try:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest() == digest
    except (ValueError, TypeError, OverflowError):
        return False


def _link(reference):
    if not isinstance(reference, dict):
        return None
    kind, digest, signature = reference.get("kind"), reference.get("hash"), reference.get("signature")
    if (not isinstance(kind, str) or kind not in _ROLES or not isinstance(digest, str) or not _HASH.fullmatch(digest)
        or signature is not None and (not isinstance(signature, str) or not signature)
        or kind == "transaction" and signature is None):
        return None
    return kind, digest, signature


def merge_source_manifests(*manifests):
    """Union mirrored saved lists without hiding links or doubling repeats.

    A role/hash/signature link retains the greatest multiplicity in any one
    manifest. Invalid entries remain explicit dependencies; optional envelope
    annotations do not make a second link. The original saved lists stay intact.
    """
    counts, values = Counter(), {}
    for manifest in manifests:
        manifest = manifest if isinstance(manifest, list) else [None]
        current = Counter()
        for reference in manifest:
            link = _link(reference)
            if link is not None:
                key = ("link", *link)
                values[key] = {"kind": link[0], "hash": link[1], **({"signature": link[2]} if link[2] is not None else {})}
            else:
                encoded = json.dumps(reference, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                key = ("invalid", encoded)
                values[key] = reference
            current[key] += 1
        for key, count in current.items():
            counts[key] = max(counts[key], count)
    return [values[key] for key in sorted(counts, key=repr) for _ in range(counts[key])]


def index_source_links(references, *, authenticated_references, max_unique_hashes=SOURCE_HASH_LIMIT):
    """Index the whole authenticated multiset before admitting archive IO.

    Link equality is (kind, hash, signature); optional envelope metadata does
    not create another source. Overflow admits no arbitrary prefix. Callers
    derive authentication from persisted/frozen collector context, never PASS
    flags, and report actual read attempts via ``source_index_receipt``.
    """
    if type(max_unique_hashes) is not int or not 1 <= max_unique_hashes <= SOURCE_HASH_LIMIT:
        raise ValueError("The source hash budget must stay within the fixed inspection limit.")
    references = references if isinstance(references, list) else [None]
    authenticated_references = list(authenticated_references)
    authorized = {link for item in authenticated_references if (link := _link(item)) is not None}
    invalid_authorized = sum(_link(item) is None for item in authenticated_references)
    valid, invalid, unauthenticated = set(), 0, set()
    for item in references:
        link = _link(item)
        if link is None:
            invalid += 1
        elif link not in authorized:
            unauthenticated.add(link)
        else:
            valid.add(link)
    omitted_links = authorized - valid
    # The authenticated universe remains visible even if a caller declares a
    # smaller convenient subset. This omission still cannot certify its input.
    hashes = sorted({digest for _, digest, _ in authorized})
    budget_exceeded = len(hashes) > max_unique_hashes
    links = [{"kind": kind, "hash": digest, **({"signature": signature} if signature is not None else {})}
             for kind, digest, signature in sorted(authorized, key=lambda value: (value[0], value[1], value[2] or ""))]
    unresolved_links = {json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':')): item
                        for item in authenticated_references if _link(item) is None}
    return {"links": links, 'unresolved_links': list(unresolved_links.values()), "hashes": hashes, "hashes_to_inspect": [] if budget_exceeded else hashes,
            "raw_reference_count": len(references), "authenticated_reference_count": len(authenticated_references),
            "unique_link_count": len(authorized), "unique_hash_count": len(hashes), "omitted_link_count": len(omitted_links),
            "invalid_authenticated_link_count": invalid_authorized,
            "invalid_link_count": invalid, "unauthenticated_link_count": len(unauthenticated),
            "max_unique_hashes": max_unique_hashes, "budget_exceeded": budget_exceeded}


def source_index_receipt(index, inspected_hashes):
    """Counts are recomputed from the index and actual attempted archive hashes.

    An attempted missing/corrupt archive is inspected, not silently omitted;
    its dependent semantic facts remain unavailable. This certifies indexing,
    not source contents, account ownership or wallet financial completeness.
    """
    admitted = set(index["hashes_to_inspect"])
    inspected = admitted & set(inspected_hashes)
    omitted = len(index["hashes"]) - len(inspected)
    reasons = []
    if index["invalid_link_count"]:
        reasons.append("Malformed source links leave their relevance unresolved.")
    if index["invalid_authenticated_link_count"]:
        reasons.append("The authenticated universe contains an unassignable source link.")
    if index["omitted_link_count"]:
        reasons.append("The declared references omit authenticated links; the complete source universe was not declared.")
    if index["unauthenticated_link_count"]:
        reasons.append("Some frozen links are absent from the authenticated collector reference set.")
    if index["budget_exceeded"]:
        reasons.append("The distinct archive set exceeds the fixed inspection budget; no prefix certifies the source set.")
    if omitted:
        reasons.append("Required distinct archive links were not inspected; omitted relevance is unproven.")
    complete = not reasons
    return {"state": "PASS" if complete else "UNKNOWN", "complete": complete,
            **{name: index[name] for name in ("raw_reference_count", "authenticated_reference_count", "unique_link_count", "unique_hash_count", "invalid_link_count", "unauthenticated_link_count", "omitted_link_count", "invalid_authenticated_link_count")},
            "inspected_hash_count": len(inspected), "omitted_hash_count": omitted,
            "budget": {"max_unique_hashes": index["max_unique_hashes"]},
            "omitted_scope": None if complete else "entire-source-set",
            "reason": "; ".join(reasons) if reasons else "The authenticated link set is fully enumerated and every distinct archive had an inspection attempt within the fixed budget. Usable contents and metric dependencies are assessed separately.",
            "evidence": sorted(inspected)}


def _integer(value, maximum=_U64):
    return type(value) is int and 0 <= value <= maximum


def source_archive_receipts(index, payloads, read_outcomes, *, snapshot_slot=None, wallet=None):
    """Retain every typed link, separately from attempted-index completeness.

    Scope comes from checksum-checked role/request/response facts, never optional
    manifest annotations. An unavailable page has no scope unless an independent checksum-matching
    wallet-request preimage establishes duplicated available claims. These receipts describe local contents, not mainnet.
    Monetary fields are deliberately not required for token quantity timing.
    """
    from .collector import _valid_account
    from .indexed_input import IndexedResolver, RECORD_VERSION
    indexed_resolver = IndexedResolver(lambda digest, _kind: payloads.get(digest), address=wallet)
    rows = []
    for link in index['links']:
        kind, digest = link['kind'], link['hash']
        raw = payloads.get(digest)
        outcome = read_outcomes.get(digest, 'not-inspected')
        scope = {'signatures': None, 'account': None, 'slot': None}
        if kind == 'transaction':
            scope['signatures'] = [link['signature']]
        valid, reason = False, 'Archive contents are unavailable; no semantic exclusion is established.'
        if outcome == 'readable' and isinstance(raw, dict):
            method, result = raw.get('method'), raw.get('result')
            if kind in ('indexed-page', 'indexed-native-source', 'indexed-input-manifest'):
                from .indexed_input import (PAGE_VERSION, NATIVE_VERSION, manifest_bytes,
                                            validate_page_envelope, source_records)
                if _indexed_payload(raw, digest):
                    try:
                        if kind == 'indexed-page' and raw.get('version') == PAGE_VERSION:
                            page = validate_page_envelope(raw, wallet)
                            valid = page['state'] == 'PASS'
                            scope['signatures'] = sorted(set(page['signatures'])) if not page['unassignable_records'] else None
                            if isinstance(page['request_scope'], dict):
                                scope['account'] = page['request_scope']['address']
                            reason = page['reason'] or 'Exact indexed page bytes validate local response and cursor shape; historical population remains unproved.'
                        elif kind == 'indexed-native-source' and raw.get('version') == NATIVE_VERSION:
                            native = source_records(raw, address=wallet)
                            valid = native['state'] == 'PASS'
                            scope['signatures'] = native['signatures'] or None
                            reason = '; '.join(native['gaps']) or 'Exact native request/response bytes validate their signature association.'
                        elif kind == 'indexed-input-manifest':
                            manifest = json.loads(manifest_bytes(raw))
                            valid = wallet is None or manifest['address'] == wallet
                            reason = 'Frozen original manifest bytes validate input links; they establish no native observation or historical completion.'
                        else:
                            reason = 'Indexed wrapper version disagrees with its declared source role.'
                    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
                        reason = str(exc)
                else:
                    reason = 'Indexed source canonical archive checksum disagrees.'
            elif kind == 'transaction':
                native_raw = raw
                if raw.get('version') == RECORD_VERSION:
                    resolved = indexed_resolver.resolve(raw)
                    native_raw = resolved['raw'] if resolved['state'] == 'PASS' and raw.get('signature') == link['signature'] else None
                transaction = native_raw.get('transaction') if isinstance(native_raw, dict) else None
                meta = native_raw.get('meta') if isinstance(native_raw, dict) else None
                signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
                valid = (isinstance(signatures, list) and bool(signatures) and signatures[0] == link['signature']
                         and _keys(native_raw) is not None and isinstance(meta, dict) and 'err' in meta
                         and _integer(native_raw.get('slot')) and _integer(native_raw.get('blockTime'))
                         and supported_transaction_format(native_raw))
            elif kind == 'signature-page':
                params = raw.get('params')
                params = params if isinstance(params, dict) else {}
                header = (method == 'getSignaturesForAddress' and _valid_account(raw.get('address'))
                          and params.get('commitment') == 'finalized' and _integer(params.get('minContextSlot'))
                          and params['minContextSlot'] == snapshot_slot and type(params.get('limit')) is int
                          and 1 <= params['limit'] <= 1000 and 'until' not in params
                          and ('before' not in params or isinstance(params['before'], str) and bool(params['before'])))
                entries = (header and isinstance(result, list) and len(result) <= params['limit']
                           and all(isinstance(item, dict) and isinstance(item.get('signature'), str) and bool(item['signature'])
                                   and _integer(item.get('slot')) for item in result))
                if header:
                    scope['account'] = raw['address']
                if entries and len({item['signature'] for item in result}) == len(result):
                    # Membership/slot scope can survive a missing err/time fact.
                    scope['signatures'] = sorted(item['signature'] for item in result)
                    valid = all(_integer(item.get('blockTime')) and 'err' in item
                                and item.get('confirmationStatus') == 'finalized' for item in result)
                reason = 'The linked signature-page request, entries or explicit execution/time facts are malformed.'
            elif kind == 'block-order':
                header = method == 'getBlock' and _integer(raw.get('slot'))
                if header:
                    scope['slot'] = raw['slot']
                signatures = result.get('signatures') if isinstance(result, dict) else None
                valid = (header and isinstance(signatures, list)
                         and all(isinstance(value, str) and value for value in signatures)
                         and len(set(signatures)) == len(signatures)
                         and (result.get('blockTime') is None or _integer(result['blockTime'])))
            elif kind == 'snapshot-slot':
                valid = (method == 'getSlot' and raw.get('commitment') == 'finalized'
                         and _integer(result) and result == snapshot_slot)
            elif kind in ('owned-accounts', 'native-balance'):
                context = result.get('context') if isinstance(result, dict) else None
                header = isinstance(context, dict) and _integer(context.get('slot')) and _integer(snapshot_slot) and context['slot'] >= snapshot_slot
                if kind == 'owned-accounts':
                    valid = (header and method == 'getTokenAccountsByOwner' and _valid_account(raw.get('owner'))
                             and (wallet is None or raw['owner'] == wallet)
                             and raw.get('program') in _TOKEN_IDS and isinstance(result.get('value'), list)
                             and all(isinstance(item, dict) for item in result['value']))
                else:
                    valid = (header and method == 'getBalance' and _valid_account(raw.get('address'))
                             and (wallet is None or raw['address'] == wallet) and _integer(result.get('value')))
            if valid and kind not in ('indexed-page', 'indexed-native-source', 'indexed-input-manifest'):
                reason = 'Checksum-checked contents have a supported declared source role; metric facts are assessed separately.'
            elif not valid and kind not in ('signature-page', 'indexed-page', 'indexed-native-source', 'indexed-input-manifest'):
                reason = 'Checksum-checked contents do not validate the declared source role or its required identity/shape.'
            if kind == 'transaction' and raw.get('version') != RECORD_VERSION and not supported_transaction_format(raw):
                reason = 'The declared transaction format is unsupported by this application; its parsed facts cannot certify dependent metrics.'
        validation = 'supported' if valid else 'malformed' if outcome == 'readable' else 'unavailable'
        recovery = 'Restore the checksum-matching archived source with its supported role, then rebuild the saved report.'
        if (kind == 'transaction' and outcome == 'readable' and isinstance(raw, dict)
            and raw.get('version') != RECORD_VERSION and not supported_transaction_format(raw)):
            recovery = 'Resolve the linked format with a reviewed parser/schema contract, then rebuild. Restoring identical bytes alone cannot resolve format support.'
        rows.append({**link, 'state': 'PASS' if valid else 'UNKNOWN', 'read_state': outcome,
                     'validation_state': validation, 'scope': scope, 'reason': reason,
                     'evidence': [digest], 'recovery': None if valid else
                     {'action': recovery, 'provider_requests': 0}})
    # A native wallet page can sometimes be independently scoped even after
    # loss: reconstruct only the wallet-address substitution of an available
    # supported page, and require its complete canonical preimage to match the
    # missing digest. This duplicates already available execution/time claims;
    # it does not repair the file or certify its unavailable wallet cursor chain.
    wallet_page_proofs = {}
    if wallet is not None:
        for row in rows:
            if row['kind'] != 'signature-page' or row['state'] != 'PASS':
                continue
            candidate = {**payloads[row['hash']], 'address': wallet}
            encoded = json.dumps(candidate, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            wallet_page_proofs[hashlib.sha256(encoded).hexdigest()] = row
        for row in rows:
            proof = wallet_page_proofs.get(row['hash'])
            if row['kind'] != 'signature-page' or row['read_state'] in ('readable', 'not-inspected') or proof is None:
                continue
            row['scope'] = {**proof['scope'], 'account': wallet}
            row['scope_proof'] = {'kind': 'checksum-matched-wallet-request-reconstruction',
                'source_hash': proof['hash'], 'substitution': {'address': wallet}, 'evidence': [proof['hash']]}
            row['reason'] = 'The archive remains unavailable. A checksum-matching wallet-request reconstruction duplicates the available page execution/time claims; the wallet cursor chain itself remains unavailable.'
            row['evidence'] = sorted({row['hash'], proof['hash']})
    for link in index.get('unresolved_links', []):
        link = link if isinstance(link, dict) else {}
        digest = link.get('hash')
        rows.append({'kind': link.get('kind') if isinstance(link.get('kind'), str) else 'unassignable',
            'hash': digest if isinstance(digest, str) and _HASH.fullmatch(digest) else None, 'signature': link.get('signature'),
            'state': 'UNKNOWN', 'read_state': 'not-inspected', 'validation_state': 'unsupported',
            'scope': {'signatures': None, 'account': None, 'slot': None},
            'evidence': [digest] if isinstance(digest, str) and _HASH.fullmatch(digest) else [],
            'reason': 'The authenticated link has an unsupported or malformed declared role; its relevance remains unresolved.',
            'recovery': {'action': 'Recover a supported collector source declaration and rebuild; do not relabel this archive as proof.', 'provider_requests': 0}})
    return {'state': 'PASS' if rows and all(row['state'] == 'PASS' for row in rows) else 'UNKNOWN',
            'counts': {'links': len(rows), 'usable': sum(row['state'] == 'PASS' for row in rows),
                       'unresolved': sum(row['state'] != 'PASS' for row in rows)}, 'receipts': rows}


def unresolved_source_dependencies(receipts, signature, raws, *, purpose):
    """Resolve metric dependencies only from validated signature/slot scope.

    Current ownership/balance snapshots are population/valuation inputs, not
    selected token timing or native transaction endpoints. A missing block does
    not erase a network fee or endpoint observation. Unreadable pages cannot be
    excluded using a convenient surviving version or unvalidated address hint.
    """
    roles = ({'signature-page', 'indexed-page', 'indexed-native-source'} if purpose == 'execution' else
             {'signature-page', 'block-order', 'snapshot-slot', 'indexed-page', 'indexed-native-source'})
    result = []
    for row in receipts:
        if row['state'] == 'PASS' or row['kind'] not in roles:
            continue
        # An unassignable digest cannot supply a per-archive fact/path. The
        # authenticated-index invalid-link gate already vetoes certification;
        # retain its typed receipt without inventing a usable hash dependency.
        if not isinstance(row['hash'], str) or not _HASH.fullmatch(row['hash']):
            continue
        if row.get('scope_proof', {}).get('kind') == 'checksum-matched-wallet-request-reconstruction':
            continue
        scope = row['scope']
        signatures = scope['signatures']
        if signatures is not None and signature not in signatures:
            continue
        if row['kind'] == 'block-order' and scope['slot'] is not None:
            slots = [raw.get('slot') for raw in raws if isinstance(raw, dict)]
            if slots and len(slots) == len(raws) and all(_integer(slot) and slot != scope['slot'] for slot in slots):
                continue
        result.append(row)
    return result


def apply_unresolved_chronology(chronology, records, archive_contents):
    """Apply the same availability rule in direct history and frozen loading."""
    unresolved = [row for row in archive_contents['receipts'] if row['state'] != 'PASS']
    raw_versions = defaultdict(list)
    for record in records:
        raw_versions[record['signature']].append(record['raw'])
    for signature, raws in raw_versions.items():
        if signature not in chronology.get('transactions', {}):
            # Unassignable negative sources revoke source-set certification;
            # they are not invented transactions with a None identity.
            continue
        dependencies = unresolved_source_dependencies(unresolved, signature, raws, purpose='chronology')
        if not dependencies:
            continue
        hashes = sorted({row['hash'] for row in dependencies})
        reason = 'A linked source remains unreadable or role-invalid; its chronology/population relevance is not excluded.'
        row = chronology['transactions'][signature]
        row.update(state='UNKNOWN', time_state='UNKNOWN', order_state='UNKNOWN', canonical_time=None,
                   transaction_index=None, reason=reason, evidence=sorted(set(row['evidence']) | set(hashes)))
        placement = chronology['placements'][signature]
        placement.update(state='UNKNOWN', slot_state='UNKNOWN', slot=None, unbounded=True,
                         slot_bounds={'bounded': False, 'min': None, 'max': None}, reason=reason,
                         evidence=sorted(set(placement['evidence']) | set(hashes)))
        chronology['conflicts'].append({'signature': signature, 'slot': None, 'kind': 'unresolved-source',
            'field': 'archive_contents', 'reason': reason, 'evidence': hashes})
        chronology['state'] = 'UNKNOWN'
    return chronology


def _keys(raw):
    transaction, meta = raw.get("transaction"), raw.get("meta")
    message = transaction.get("message") if isinstance(transaction, dict) else None
    entries = message.get("accountKeys") if isinstance(message, dict) else None
    if not isinstance(entries, list) or not entries or not isinstance(meta, dict):
        return None
    keys = [value.get("pubkey") if isinstance(value, dict) else value for value in entries]
    loaded = meta.get("loadedAddresses", {})
    if not isinstance(loaded, dict):
        return None
    for name in ("writable", "readonly"):
        values = loaded.get(name, [])
        if not isinstance(values, list):
            return None
        for key in values:
            if key not in keys:
                keys.append(key)
    return keys if all(isinstance(key, str) and key for key in keys) else None


def _fact(digest, path, value=None, status="known"):
    return {"hash": digest, "path": path, "value": value, "status": status}


def _format_fact(raw, digest):
    # Compare parser support, not the version labels: supported legacy and v0
    # sources may establish the same normalized operation. Unsupported labels
    # must leave an explicit rejecting dependency on their own archive hash.
    supported = supported_transaction_format(raw)
    return _fact(digest, 'version', True if supported else raw.get('version') if isinstance(raw, dict) else None,
                 'known' if supported else 'invalid' if isinstance(raw, dict) else 'missing')


def _check(facts, field, *, signature, account=None):
    known = {json.dumps(fact["value"], sort_keys=True, separators=(",", ":")) for fact in facts if fact["status"] == "known"}
    absent = any(fact["status"] not in ("known", "not_applicable") for fact in facts)
    mixed = bool(known) and any(fact["status"] == "not_applicable" for fact in facts)
    status = "conflict" if len(known) > 1 else "missing" if not facts or absent or mixed else "consistent"
    reason = (f"Linked sources disagree on {field}." if status == "conflict" else
              f"A linked source lacks a valid required {field} fact." if status == "missing" else
              f"All linked sources agree on {field}.")
    return {"state": "PASS" if status == "consistent" else "UNKNOWN", "status": status,
            "field": field, "signature": signature, "account": account, "reason": reason,
            "evidence": sorted({fact["hash"] for fact in facts if fact["hash"]}), "facts": facts}


def _group(checks, *, hashes, signature, account=None):
    rows = list(checks.values())
    conflicts = [row for row in rows if row["status"] == "conflict"]
    missing = [row for row in rows if row["status"] == "missing"]
    paths = defaultdict(set)
    for row in rows:
        for fact in row["facts"]:
            if fact["hash"]:
                paths[fact["hash"]].add(fact["path"])
    evidence = sorted(set(hashes) | set(paths))
    return {"state": "PASS" if rows and all(row["state"] == "PASS" for row in rows) else "UNKNOWN",
            "signature": signature, "account": account, "checks": checks,
            "conflicts": conflicts, "missing": missing, "native_hashes": hashes,
            "evidence": evidence, "source_paths": [{"hash": digest, "paths": sorted(paths[digest])} for digest in evidence],
            "reason": "; ".join(row["reason"] for row in conflicts + missing) if conflicts or missing else
                      "Every linked archive agrees on the metric's normalized native facts."}


def _program_facts(raw, keys, account, digest):
    """Missing balance annotations can use explicit relevant parsed SPL facts."""
    from .transaction_format import _needs_instruction_view, original_instruction_paths
    original = raw
    normalized = None
    if _needs_instruction_view(raw):
        from .compiled_instructions import normalize_transaction
        normalized = normalize_transaction(raw)
        raw = normalized['raw']
    message = raw.get("transaction", {}).get("message", {})
    meta = raw.get("meta", {})
    instructions = message.get("instructions") if isinstance(message, dict) else None
    flat = [(f"transaction.message.instructions.{index}", item) for index, item in enumerate(instructions or [])] if isinstance(instructions, list) else []
    nested = meta.get("innerInstructions") if isinstance(meta, dict) else None
    for group_index, group in enumerate(nested if isinstance(nested, list) else []):
        if isinstance(group, dict) and isinstance(group.get("instructions"), list):
            flat += [(f"meta.innerInstructions.{group_index}.instructions.{index}", item) for index, item in enumerate(group["instructions"])]
    result = []
    for path, instruction in flat:
        if not isinstance(instruction, dict):
            continue
        index = instruction.get("programIdIndex")
        program = instruction.get("programId") or (keys[index] if _integer(index) and index < len(keys) else None)
        parsed = instruction.get("parsed")
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if isinstance(program, str) and program in _TOKEN_IDS and isinstance(info, dict) and account in (info.get("source"), info.get("destination"), info.get("account")):
            result.extend(_fact(digest, source_path, program) for source_path in
                          original_instruction_paths(original, [path + ".programId"], normalized=normalized))
    return result


def _account_facts(raw, digest, signature, account, identity):
    fields = defaultdict(list)
    fields["native_identity"].append(identity)
    fields["transaction_format"].append(_format_fact(raw, digest))
    if not isinstance(raw, dict):
        for field in ("account_membership", "execution", "pre_quantity", "post_quantity", "owner", "mint", "decimals", "program"):
            fields[field].append(_fact(digest, "$", status="missing"))
        return fields
    keys, meta = _keys(raw), raw.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    fields["account_membership"].append(_fact(digest, "transaction.message.accountKeys", bool(keys and keys.count(account) == 1),
                                                   "known" if keys and keys.count(account) == 1 else "invalid"))
    fields["execution"].append(_fact(digest, "meta.err", meta.get("err"), "known" if "err" in meta else "missing"))
    failed_empty = ("err" in meta and meta["err"] is not None and meta.get("preTokenBalances") == [] and meta.get("postTokenBalances") == [])
    programs = []
    for phase, name in (("pre", "preTokenBalances"), ("post", "postTokenBalances")):
        rows = meta.get(name)
        found, invalid = [], False
        if isinstance(rows, list) and keys:
            for index, row in enumerate(rows):
                account_index = row.get("accountIndex") if isinstance(row, dict) else None
                if not _integer(account_index) or account_index >= len(keys):
                    invalid = True
                elif keys[account_index] == account:
                    found.append((index, row))
        if len(found) != 1 or invalid:
            status = "not_applicable" if failed_empty else "missing"
            for field in (phase + "_quantity", "owner", "mint", "decimals"):
                fields[field].append(_fact(digest, "meta." + name, status=status))
            continue
        index, row = found[0]
        path = f"meta.{name}.{index}"
        token = row.get("uiTokenAmount")
        token = token if isinstance(token, dict) else {}
        amount = token.get("amount")
        valid_amount = isinstance(amount, str) and len(amount) <= 20 and bool(_QUANTITY.fullmatch(amount)) and int(amount) <= _U64
        fields[phase + "_quantity"].append(_fact(digest, path + ".uiTokenAmount.amount", str(int(amount)) if valid_amount else amount,
                                                      "known" if valid_amount else "invalid"))
        for field in ("owner", "mint"):
            value = row.get(field)
            fields[field].append(_fact(digest, path + "." + field, value, "known" if isinstance(value, str) and value else "missing"))
        value = token.get("decimals")
        fields["decimals"].append(_fact(digest, path + ".uiTokenAmount.decimals", value, "known" if _integer(value, 255) else "invalid"))
        if row.get("programId") is not None:
            programs.append(_fact(digest, path + ".programId", row["programId"], "known" if isinstance(row["programId"], str) and row["programId"] in _TOKEN_IDS else "invalid"))
    if keys:
        programs += _program_facts(raw, keys, account, digest)
    fields["program"] += programs or [_fact(digest, "meta.*TokenBalances.programId", status="not_applicable" if failed_empty else "missing")]
    return fields


def _native_facts(raw, digest, wallet, identity):
    fields = {"native_identity": [identity], "transaction_format": [_format_fact(raw, digest)]}
    keys = _keys(raw) if isinstance(raw, dict) else None
    meta = raw.get("meta") if isinstance(raw, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    before, after, fee = meta.get("preBalances"), meta.get("postBalances"), meta.get("fee")
    valid = (keys and "err" in meta and _integer(fee) and isinstance(before, list) and isinstance(after, list)
             and len(before) == len(after) == len(keys) and all(_integer(value) for value in before + after)
             and sum(before) - sum(after) == fee and keys.count(wallet) <= 1)
    if valid and meta["err"] is not None:
        valid = all(after[index] - value == (-fee if index == 0 else 0) for index, value in enumerate(before))
    fields["native_validation"] = [_fact(digest, "meta.{err,fee,preBalances,postBalances}", True if valid else None, "known" if valid else "invalid")]
    compatible = bool(valid) and all(after[index] - value == (-fee if index == 0 else 0) for index, value in enumerate(before))
    fields["failed_execution_compatible"] = [_fact(digest, "meta.{fee,preBalances,postBalances}", compatible if valid else None,
                                                          "known" if valid else "missing")]
    wallet_index = keys.index(wallet) if keys and wallet in keys else None
    wallet_change = after[wallet_index] - before[wallet_index] if valid and wallet_index is not None else 0
    projection_compatible = bool(valid) and wallet_change == (-fee if keys[0] == wallet else 0)
    fields["failed_wallet_projection_compatible"] = [_fact(digest, "meta.{fee,preBalances,postBalances};transaction.message.accountKeys",
        projection_compatible if valid else None, "known" if valid else "missing")]
    fields["fee"] = [_fact(digest, "meta.fee", str(fee) if _integer(fee) else fee, "known" if _integer(fee) else "missing")]
    fields["payer"] = [_fact(digest, "transaction.message.accountKeys.0", keys[0] if keys else None, "known" if keys else "missing")]
    for name, values in (("wallet_pre", before), ("wallet_post", after)):
        index = keys.index(wallet) if keys and wallet in keys else None
        present = index is not None and isinstance(values, list) and index < len(values) and _integer(values[index])
        absent = bool(keys) and wallet not in keys
        path = (f"meta.{'preBalances' if name == 'wallet_pre' else 'postBalances'}.{index}"
                if index is not None else "transaction.message.accountKeys")
        # Absence proves zero change in this transaction, never zero wallet
        # inventory/equity or a native balance endpoint at the report boundary.
        fields[name] = [_fact(digest, path, str(values[index]) if present else None,
                                    "known" if present else "not_applicable" if absent else "missing")]
    return fields


def assess_source_consistency(records, *, accounts=(), wallet=None, source_index=None, inspected_hashes=None,
                              page_receipts=(), indexed_receipts=(), archive_contents=None):
    """Compare all linked alternatives, never caller PASS flags or hash equality.

    Records are {signature, evidence_hash, raw}; unavailable links use raw=None.
    Token facts are scoped by account identity, native projections by wallet.
    Route/instruction validity remains a separate per-archive decoder check.
    """
    records = list(records)
    if source_index is None:
        references = [{"kind": "transaction", "signature": record.get("signature"), "hash": record.get("evidence_hash")}
                      for record in records if isinstance(record, dict)]
        source_index = index_source_links(references, authenticated_references=references)
        inspected_hashes = [record.get("evidence_hash") for record in records if isinstance(record, dict)]
    source_set = source_index_receipt(source_index, inspected_hashes or ())
    archive_contents = archive_contents if isinstance(archive_contents, dict) else {'state': 'PASS', 'receipts': []}
    unresolved = [row for row in archive_contents['receipts'] if row['state'] != 'PASS']
    page_execution = defaultdict(list)
    for receipt in page_receipts:
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        entries = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or payload.get("method") != "getSignaturesForAddress":
            continue
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and isinstance(entry.get("signature"), str):
                page_execution[entry["signature"]].append(_fact(receipt.get("hash"), f"result.{index}.err", entry.get("err"),
                                                                 "known" if "err" in entry else "missing"))
    for receipt in indexed_receipts:
        digest = receipt.get('hash') if isinstance(receipt, dict) else None
        payload = receipt.get('payload') if isinstance(receipt, dict) else None
        if not _indexed_payload(payload, digest):
            continue
        from .indexed_input import validate_page_envelope
        page = validate_page_envelope(payload, wallet)
        # Verified byte leads remain negative execution dependencies when a
        # page's cursor/filter/placement metadata rejects it. They never supply
        # a provider population certificate or a caller-supplied receipt state.
        for index, raw in enumerate(page['records']):
            transaction = raw.get('transaction') if isinstance(raw, dict) else None
            signatures = transaction.get('signatures') if isinstance(transaction, dict) else None
            signature = signatures[0] if isinstance(signatures, list) and signatures else None
            meta = raw.get('meta') if isinstance(raw, dict) else None
            if isinstance(signature, str) and signature and isinstance(meta, dict):
                page_execution[signature].append(_fact(digest, f'result.data.{index}.meta.err', meta.get('err'),
                    'known' if 'err' in meta else 'missing'))
    linked = defaultdict(dict)
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("signature"), str):
            linked[record["signature"]][record.get("evidence_hash")] = record.get("raw")
    transactions = {}
    for signature, sources in sorted(linked.items()):
        sources = dict(sorted(sources.items(), key=lambda item: str(item[0])))
        hashes = sorted(digest for digest in sources if isinstance(digest, str) and digest)
        dependency_rows = unresolved_source_dependencies(unresolved, signature, list(sources.values()), purpose='chronology')
        execution_rows = unresolved_source_dependencies(unresolved, signature, list(sources.values()), purpose='execution')
        unavailable_execution = [_fact(row['hash'], '$.unresolved_signature_page', status='missing') for row in execution_rows]
        targets = set(accounts.get(signature, ())) if isinstance(accounts, dict) else set(accounts)
        scoped_accounts, identities = (set(targets) if isinstance(accounts, dict) else set()), {}
        for digest, raw in sources.items():
            transaction = raw.get("transaction") if isinstance(raw, dict) else None
            signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
            known = isinstance(signatures, list) and signatures and signatures[0] == signature
            identities[digest] = _fact(digest, "transaction.signatures.0", signatures[0] if isinstance(signatures, list) and signatures else None,
                                      "known" if known else "invalid" if isinstance(raw, dict) else "missing")
            keys = _keys(raw) if isinstance(raw, dict) else None
            if keys:
                scoped_accounts.update(targets & set(keys))
                meta = raw["meta"]
                for name in ("preTokenBalances", "postTokenBalances"):
                    for row in meta.get(name, []) if isinstance(meta.get(name), list) else []:
                        index = row.get("accountIndex") if isinstance(row, dict) else None
                        if _integer(index) and index < len(keys):
                            scoped_accounts.add(keys[index])
        account_checks = {}
        for account in sorted(scoped_accounts):
            facts = defaultdict(list)
            for digest, raw in sources.items():
                for field, values in _account_facts(raw, digest, signature, account, identities[digest]).items():
                    facts[field] += values
            facts["execution"] += page_execution[signature] + unavailable_execution
            checks = {field: _check(values, field, signature=signature, account=account) for field, values in sorted(facts.items())}
            checks['archive_dependencies'] = {'state': 'UNKNOWN' if dependency_rows else 'PASS',
                'status': 'missing' if dependency_rows else 'consistent', 'field': 'archive_dependencies',
                'signature': signature, 'account': account,
                'reason': '; '.join(row['reason'] for row in dependency_rows) if dependency_rows else 'No unresolved linked role remains potentially relevant to this account record.',
                'evidence': sorted({row['hash'] for row in dependency_rows}),
                'facts': [_fact(row['hash'], '$.unresolved_' + row['kind'], status='missing') for row in dependency_rows]}
            scoped_set = {**source_set, "evidence": hashes}
            checks["source_set"] = {"state": source_set["state"], "status": "consistent" if source_set["complete"] else "missing",
                                    "field": "source_set", "signature": signature, "account": account,
                                    "reason": source_set["reason"], "evidence": hashes, "facts": []}
            account_checks[account] = _group(checks, hashes=hashes, signature=signature, account=account)
            account_checks[account]["source_set"] = scoped_set
        native = {}
        if isinstance(wallet, str) and wallet:
            facts = defaultdict(list)
            for digest, raw in sources.items():
                for field, values in _native_facts(raw, digest, wallet, identities[digest]).items():
                    facts[field] += values
            facts["execution"] = [_fact(digest, "meta.err", raw["meta"].get("err"), "known" if "err" in raw["meta"] else "missing")
                                  if isinstance(raw, dict) and isinstance(raw.get("meta"), dict) else _fact(digest, "meta.err", status="missing")
                                  for digest, raw in sources.items()] + page_execution[signature] + unavailable_execution
            checks = {field: _check(values, field, signature=signature, account=wallet) for field, values in sorted(facts.items())}
            if checks["execution"]["state"] != "PASS" and all(fact["status"] == "known" and fact["value"] is True
                                                               for fact in checks["failed_wallet_projection_compatible"]["facts"]):
                checks["execution_invariance"] = {**checks["failed_wallet_projection_compatible"], "field": "execution_invariance",
                    "reason": "Every validated wallet endpoint change equals its wallet-paid payer fee debit; success or failure leaves this wallet projection identical. Other account changes are not certified by this projection."}
            checks["source_set"] = {"state": source_set["state"], "status": "consistent" if source_set["complete"] else "missing",
                                    "field": "source_set", "signature": signature, "account": wallet,
                                    "reason": source_set["reason"], "evidence": hashes, "facts": []}
            for metric, needs in (("wallet_network_fees_sol", ("native_identity", "native_validation", "fee", "payer")),
                                  ("native_wallet_delta_sol", ("native_identity", "native_validation", "wallet_pre", "wallet_post", "execution_invariance" if "execution_invariance" in checks else "execution"))):
                native[metric] = _group({field: checks[field] for field in needs + ("transaction_format", "source_set")}, hashes=hashes, signature=signature, account=wallet)
                native[metric]["source_set"] = {**source_set, "evidence": hashes}
            native["checks"] = checks
        identity = _check(list(identities.values()), "native_identity", signature=signature)
        semantic_checks = [identity] + list(account_checks.values()) + [row for name, row in native.items() if name != "checks"]
        metric_evidence = sorted(set(hashes) | {digest for row in account_checks.values() for digest in row['evidence']}
                                 | {digest for name, row in native.items() if name != 'checks' for digest in row['evidence']})
        transactions[signature] = {"state": "PASS" if all(row["state"] == "PASS" for row in semantic_checks) else "UNKNOWN",
                                   "native_hashes": hashes, "evidence": metric_evidence,
                                   "accounts": account_checks, "native": native, "identity": identity,
                                   "source_set": {**source_set, "evidence": hashes}}
    return {"version": VERSION, "transactions": transactions, "source_set": source_set, 'archive_contents': archive_contents,
            "state": "PASS" if source_set["complete"] and archive_contents['state'] == 'PASS' and transactions and all(row["state"] == "PASS" for row in transactions.values()) else "UNKNOWN"}
