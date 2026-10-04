"""Resumable native account-history collector; scope limitations stay explicit.

A native account crawl cannot prove global historical token-account ownership.
Transactions before the reporting window are retained for bounded basis recovery.
There is no inferred zero opening inventory at the backfill boundary.
"""
from __future__ import annotations

from collections import defaultdict
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import shutil
from typing import Any

from .providers import METHOD_COSTS, TOKEN_PROGRAM, TOKEN_2022_PROGRAM, ProviderError
from .storage import QuotaExceeded, EvidenceError

VERSION = "native-collector-v1"


class CollectionPaused(RuntimeError):
    def __init__(self, reason: str, checkpoint: dict, partial: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.checkpoint = checkpoint
        self.partial = partial


def _timestamp(value) -> int:
    if isinstance(value, bool):
        raise ValueError("Window bounds must be UTC timestamps.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Window bounds must be ISO UTC timestamps.") from None
    elif isinstance(value, datetime):
        date = value
    else:
        raise ValueError("Window bounds must be UTC timestamps.")
    if date.tzinfo is None or date.utcoffset() != timedelta(0):
        raise ValueError("Window bounds must explicitly use UTC.")
    if date.microsecond:
        raise ValueError("Window bounds must use whole seconds.")
    return int(date.timestamp())


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_account(address) -> bool:
    if not isinstance(address, str) or not 32 <= len(address) <= 44:
        return False
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    try:
        for char in address:
            number = number * 58 + alphabet.index(char)
    except ValueError:
        return False
    prefix = len(address) - len(address.lstrip("1"))
    return prefix + (number.bit_length() + 7) // 8 == 32


def _account_keys(raw: dict) -> list[str]:
    keys = raw.get("transaction", {}).get("message", {}).get("accountKeys", [])
    return [entry.get("pubkey", "") if isinstance(entry, dict) else entry for entry in keys]


def _discover_accounts(raw: dict, wallet: str) -> dict[str, str]:
    """Only event-time owner metadata or supported explicit ownership instructions."""
    discovered = {}
    meta = raw.get("meta") or {}
    keys = _account_keys(raw)
    for balance in meta.get("preTokenBalances", []) + meta.get("postTokenBalances", []):
        index = balance.get("accountIndex")
        if balance.get("owner") == wallet and _integer(index) and index < len(keys) and _valid_account(keys[index]):
            discovered[keys[index]] = "event-time token-balance owner"
    if meta.get("err") is not None:
        return discovered
    instructions = list(raw.get("transaction", {}).get("message", {}).get("instructions", []))
    for group in meta.get("innerInstructions") or []:
        instructions.extend(group.get("instructions", []))
    for instruction in instructions:
        if instruction.get("programId") not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            continue
        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict) or not isinstance(parsed.get("info"), dict):
            continue
        kind, info = parsed.get("type"), parsed["info"]
        account = info.get("account")
        if not _valid_account(account):
            continue
        if kind in ("initializeAccount", "initializeAccount2", "initializeAccount3") and info.get("owner") == wallet:
            discovered[account] = "parsed token-account initialization owner"
        elif kind == "setAuthority" and info.get("authorityType") == "accountOwner" and (info.get("authority") == wallet or info.get("newAuthority") == wallet):
            discovered[account] = "parsed token-account ownership change"
        # closeAccount.owner denotes close authority, not necessarily token owner.
        # A closure alone must not broaden wallet ownership scope.
    return discovered


async def collect_wallet(gateway, store, address, start, end, limits,
                         checkpoint=None, progress=None, should_pause=None) -> dict:
    start_ts, end_ts = _timestamp(start), _timestamp(end)
    if end_ts <= start_ts:
        raise ValueError("Reporting window end must be after start.")
    if not _valid_account(address):
        raise ValueError("Wallet address must be a 32-byte base58 public address.")
    lookback = limits.get("basis_lookback_days", 90)
    transaction_limit = limits.get("transaction_limit", 10_000)
    credit_limit = limits.get("wallet_credit_limit", 20_000)
    page_size = limits.get("page_size", 100)
    min_free_disk_mb = limits.get("min_free_disk_mb", 2048)
    account_limit = limits.get("account_limit", 1000)
    for value in (lookback, transaction_limit, credit_limit, page_size, min_free_disk_mb, account_limit):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("Collector limits must be positive integers.")
    page_size = min(page_size, 1000)
    floor = start_ts - lookback * 86400
    identifier = hashlib.sha256(f"{address}:{start_ts}:{end_ts}".encode()).hexdigest()
    # Trim before deepcopy: legacy checkpoints can contain tens of thousands of
    # account records and complete parsed enumeration arrays. Raw records remain
    # in the immutable archive, never in repeatedly serialized progress payloads.
    resume_enumerations = {}
    seen_accounts = set()
    if checkpoint:
        source_accounts = checkpoint.get("accounts", {})
        seen_accounts.update(source_accounts)
        seen_accounts.add(address)
        included_keys = [address] + [key for key in source_accounts if key != address]
        snapshot = checkpoint.get("snapshot", {})
        wallet_record = source_accounts.get(address, {"address": address, "origin": "wallet", "ownership_evidence": snapshot.get("anchor_evidence"), "cursor": None, "pages": 0, "terminal": None, "page_hashes": [], "last_slot": None})
        resume_enumerations = dict(snapshot.get("accounts", {}))
        compact_snapshot = {**snapshot, "accounts": {program: entry if "value" not in entry else {"migration_pending": True} for program, entry in resume_enumerations.items()}}
        cp = deepcopy({**checkpoint, "accounts": {key: source_accounts[key] if key != address else wallet_record for key in included_keys[:account_limit]}, "snapshot": compact_snapshot})
    else:
        cp = {
            "version": VERSION, "address": address, "start": start_ts, "end": end_ts,
            "basis_floor": floor, "accounts": {}, "transactions": {}, "evidence": [],
            "pages": 0, "credits": 0, "snapshot": {}, "gaps": [], "ordering": {},
        }
    prior_omitted = cp.get("account_scope", {}).get("omitted_account_count", 0)
    prior_included = len(checkpoint.get("accounts", {})) if checkpoint else 0
    if cp.get("version") != VERSION or (cp.get("address"), cp.get("start"), cp.get("end")) != (address, start_ts, end_ts):
        raise ValueError("Checkpoint belongs to a different collector, wallet or window.")
    if cp.get("basis_floor") != floor:
        raise ValueError("A resumed collection must retain its original basis lookback.")
    initial_credits = getattr(gateway, "credits", 0)
    prior_credits = cp.get("credits", 0)
    old_ceiling = getattr(gateway, "credit_ceiling", None)
    if hasattr(gateway, "credit_ceiling"):
        ceiling = initial_credits + max(credit_limit - prior_credits, 0)
        gateway.credit_ceiling = min(old_ceiling, ceiling) if old_ceiling is not None else ceiling
    stage = "snapshot"

    def update_scope():
        count = len(cp["accounts"])
        omitted = max(len(seen_accounts) - count, prior_omitted + prior_included - count, 0)
        cp["account_scope"] = {
            "account_limit": account_limit, "included_account_count": count,
            "omitted_account_count": omitted, "account_limit_reached": omitted > 0,
            "reason": f"Account collection is capped at {account_limit} including the wallet; {omitted} evidenced accounts are omitted from paging." if omitted else None,
        }

    def persist():
        update_scope()
        cp["transactions_collected"] = len(cp["transactions"])
        cp["credits"] = prior_credits + getattr(gateway, "credits", initial_credits) - initial_credits
        store.put("collector_checkpoints", identifier, cp)

    def check_disk():
        if hasattr(store, "path") and shutil.disk_usage(store.path).free < min_free_disk_mb * 1024 * 1024:
            raise CollectionPaused(f"Free disk space is below the configured {min_free_disk_mb} MB reserve. Free space or choose a data folder with more capacity before resuming; evidence is never silently pruned.", cp)

    def evidence(payload: dict, kind: str, signature=None):
        check_disk()
        digest = store.archive(payload)
        item = {"hash": digest, "kind": kind}
        if signature:
            item["signature"] = signature
        if item not in cp["evidence"]:
            cp["evidence"].append(item)
        return digest

    def add_account(account: str, origin: str, evidence_hash: str | None = None):
        seen_accounts.add(account)
        if account not in cp["accounts"] and len(cp["accounts"]) < account_limit:
            cp["accounts"][account] = {"address": account, "origin": origin, "ownership_evidence": evidence_hash, "cursor": None, "pages": 0, "terminal": None, "page_hashes": [], "last_slot": None}

    def result() -> dict:
        update_scope()
        records = []
        for signature, item in cp["transactions"].items():
            raw = store.evidence(item["evidence_hash"])
            if not isinstance(raw, dict):
                continue
            records.append({"signature": signature, "raw": raw, "evidence_hash": item["evidence_hash"], "in_window": _integer(raw.get("blockTime")) and start_ts <= raw["blockTime"] < end_ts, "transaction_index": cp["ordering"].get(signature)})
        # Signature text is never used as a chronology tie-breaker.
        records.sort(key=lambda r: (r["raw"]["slot"] if _integer(r["raw"].get("slot")) else -1, r["transaction_index"] if r["transaction_index"] is not None else -1))
        accounts = list(cp["accounts"].values())
        terminals = [{"address": a["address"], "reason": a["terminal"], "cursor": a["cursor"]} for a in accounts if a["terminal"]]
        times = [r["raw"]["blockTime"] for r in records if _integer(r["raw"].get("blockTime"))]
        return {"transactions": records, "checkpoint": deepcopy(cp), "snapshot": cp["snapshot"], "evidence": cp["evidence"], "coverage": {
            "status": "partial", "requested_range": {"start": _iso(start_ts), "end": _iso(end_ts), "boundary": "[start,end)"},
            "fetched_range": {"start": _iso(min(times)) if times else None, "end": _iso(max(times)) if times else None},
            "pages": cp["pages"], "transactions": len(records), "credits": cp["credits"],
            "account_set": [{"address": a["address"], "discovery": a["origin"], "evidence": a["ownership_evidence"]} for a in accounts],
            "terminal_evidence": terminals, "included_account_paging_finished": bool(accounts) and all(a["terminal"] for a in accounts),
            "account_paging_finished": bool(accounts) and all(a["terminal"] for a in accounts) and cp["account_scope"]["omitted_account_count"] == 0,
            "account_scope": deepcopy(cp["account_scope"]), "account_limit": account_limit,
            "omitted_account_count": cp["account_scope"]["omitted_account_count"],
            "scope_limit_reason": cp["account_scope"]["reason"],
            "history_scope_complete": False, "historical_ownership_verified": False,
            "ownership_scope": "Wallet plus current SPL/Token-2022 accounts and event-time ownership evidenced in retrieved records. Previously closed or changed accounts may remain entirely hidden.",
            "basis_lookback_days": lookback, "basis_boundary": _iso(floor), "opening_inventory_assumed_zero": False,
            "missing_records": cp["gaps"], "unsupported_routes": [],
            "reconciliation": "not established by collection alone", "methodology": VERSION,
            "notes": ["Exhausting discovered account pages cannot prove global historical ownership completeness.", "A bounded backfill or quota boundary does not establish acquisition basis or zero opening inventory.", "Finalized minContextSlot pins a minimum anchor; current account state is not an exact historical end-window valuation."] + ([cp["account_scope"]["reason"]] if cp["account_scope"]["reason"] else []),
        }}

    async def notify():
        persist()
        if progress:
            value = progress({"stage": stage, "pages": cp["pages"], "transactions": len(cp["transactions"]), "credits": cp["credits"], "checkpoint": deepcopy(cp)})
            if inspect.isawaitable(value):
                await value

    async def check_pause():
        if should_pause:
            value = should_pause()
            if inspect.isawaitable(value):
                value = await value
            if value:
                raise CollectionPaused("Paused by user; archived work is retained.", cp)

    async def rpc(method, params):
        await check_pause()
        check_disk()
        current = prior_credits + getattr(gateway, "credits", initial_credits) - initial_credits
        if current + METHOD_COSTS[method] > credit_limit:
            raise CollectionPaused("Wallet credit limit reached; reduce workload or resume with a higher bounded limit.", cp)
        return await gateway.rpc(method, params)

    def gap(reason, signature=None, account=None):
        entry = {"reason": reason}
        if signature:
            entry["signature"] = signature
        if account:
            entry["account"] = account
        if entry not in cp["gaps"]:
            cp["gaps"].append(entry)
        raise CollectionPaused(reason, cp)

    async def transaction(signature):
        item = cp["transactions"].get(signature)
        raw = store.evidence(item["evidence_hash"]) if item else None
        if not item:
            cached = store.get("transactions", signature)
            if cached and cached.get("evidence_hash"):
                raw = store.evidence(cached["evidence_hash"])
                item = {"signature": signature, "evidence_hash": cached["evidence_hash"]}
        complete = isinstance(raw, dict) and isinstance(raw.get("meta"), dict) and _integer(raw.get("blockTime")) and _integer(raw.get("slot"))
        if signature not in cp["transactions"] or not complete:
            if signature not in cp["transactions"] and len(cp["transactions"]) >= transaction_limit:
                raise CollectionPaused("Transaction limit reached; the remaining history is not complete.", cp)
            if complete:
                digest = item["evidence_hash"]
            else:
                # Missing metadata/time/null may be transient. A deliberate resume
                # retries the record while retaining every earlier observation.
                raw = await rpc("getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
                digest = evidence(raw, "transaction", signature)
                store.put("transactions", signature, {"signature": signature, "raw": raw, "evidence_hash": digest})
            item = {"signature": signature, "evidence_hash": digest}
            cp["transactions"][signature] = item
            link = {"hash": digest, "kind": "transaction", "signature": signature}
            if link not in cp["evidence"]:
                cp["evidence"].append(link)
            persist()
        if not isinstance(raw, dict):
            gap("Transaction is missing from native history.", signature)
        if not isinstance(raw.get("meta"), dict):
            gap("Transaction metadata is missing; no successful exchange is inferred.", signature)
        tx_version = raw.get("version", "legacy")
        if not (tx_version == "legacy" or (type(tx_version) is int and tx_version == 0)):
            gap("Unsupported transaction version is archived but cannot be decoded.", signature)
        if not _integer(raw.get("blockTime")) or not _integer(raw.get("slot")):
            gap("Transaction time or slot is missing; exact window/order is unresolved.", signature)
        signatures = raw.get("transaction", {}).get("signatures")
        if not isinstance(signatures, list) or not signatures or signatures[0] != signature:
            gap("Transaction signature does not match the requested evidence.", signature)
        recovered = {"Transaction is missing from native history.", "Transaction metadata is missing; no successful exchange is inferred.", "Transaction time or slot is missing; exact window/order is unresolved."}
        cp["gaps"] = [entry for entry in cp["gaps"] if not (entry.get("signature") == signature and entry.get("reason") in recovered)]
        for account, origin in _discover_accounts(raw, address).items():
            add_account(account, origin, item["evidence_hash"])
        return raw

    def inspect_enumeration(program, response, digest):
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            gap("Current token-account enumeration is incomplete.")
        context = response.get("context", {}).get("slot")
        if not _integer(context) or context < cp["snapshot"]["slot"]:
            gap("Token-account snapshot did not meet its finalized anchor.")
        unique = set()
        for item in response["value"]:
            account = item.get("pubkey")
            parsed = item.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            if not _valid_account(account) or parsed.get("owner") != address:
                gap("Current token-account ownership could not be verified.")
            unique.add(account)
            add_account(account, "current owner enumeration", digest)
        cp["snapshot"]["accounts"][program] = {
            "evidence_hash": digest, "count": len(unique), "context_slot": context,
            "included_count": len(unique.intersection(cp["accounts"])),
            "omitted_count": len(unique.difference(cp["accounts"])),
        }
        cp["snapshot"]["context_slots"][program] = context

    try:
        await check_pause()
        if cp["snapshot"]:
            # Rebuild a transient deduplication set from archived ownership proof.
            # Only compact counts/references are persisted, including on resume.
            for program, entry in resume_enumerations.items():
                if "value" in entry:
                    response = entry
                    digest = evidence({"method": "getTokenAccountsByOwner", "owner": address, "program": program, "result": response}, "owned-accounts")
                else:
                    digest = entry.get("evidence_hash")
                    response = store.evidence(digest)["result"]
                inspect_enumeration(program, response, digest)
            for signature, item in cp["transactions"].items():
                raw = store.evidence(item["evidence_hash"])
                if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
                    for account, origin in _discover_accounts(raw, address).items():
                        add_account(account, origin, item["evidence_hash"])
            persist()
        if not cp["snapshot"]:
            slot = await rpc("getSlot", [{"commitment": "finalized"}])
            if not _integer(slot):
                gap("Finalized snapshot slot is missing.")
            digest = evidence({"method": "getSlot", "commitment": "finalized", "result": slot}, "snapshot-slot")
            cp["snapshot"] = {"network": "mainnet-beta", "commitment": "finalized", "slot": slot, "anchor_evidence": digest, "accounts": {}, "context_slots": {}}
            add_account(address, "wallet", digest)
            persist()
        slot = cp["snapshot"]["slot"]
        # Individually persist enumeration so a mid-snapshot pause remains resumable.
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            if program in cp["snapshot"]["accounts"]:
                continue
            response = await rpc("getTokenAccountsByOwner", [address, {"programId": program}, {"encoding": "jsonParsed", "commitment": "finalized", "minContextSlot": slot}])
            digest = evidence({"method": "getTokenAccountsByOwner", "owner": address, "program": program, "result": response}, "owned-accounts")
            inspect_enumeration(program, response, digest)
            await notify()
        if "native_balance" not in cp["snapshot"]:
            balance = await rpc("getBalance", [address, {"commitment": "finalized", "minContextSlot": slot}])
            digest = evidence({"method": "getBalance", "address": address, "result": balance}, "native-balance")
            if not isinstance(balance, dict) or not _integer(balance.get("value")) or not _integer(balance.get("context", {}).get("slot")) or balance["context"]["slot"] < slot:
                gap("Finalized native balance snapshot is incomplete.")
            cp["snapshot"]["native_balance"] = str(balance["value"])
            cp["snapshot"]["native_balance_evidence"] = digest
            cp["snapshot"]["context_slots"]["native_balance"] = balance["context"]["slot"]
            await notify()
        stage = "history"
        while True:
            account = next((a for a in cp["accounts"].values() if not a["terminal"]), None)
            if account is None:
                break
            await check_pause()
            params = {"limit": page_size, "commitment": "finalized", "minContextSlot": slot}
            if account["cursor"]:
                params["before"] = account["cursor"]
            page = await rpc("getSignaturesForAddress", [account["address"], params])
            page_hash = evidence({"method": "getSignaturesForAddress", "address": account["address"], "params": params, "result": page}, "signature-page")
            if not isinstance(page, list):
                gap("Signature page is missing or malformed.", account=account["address"])
            # Hash only page content: a server repeating a page with a new cursor is detected.
            content_hash = hashlib.sha256(json.dumps(page, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if content_hash in account["page_hashes"]:
                gap("Provider repeated a signature page; pagination is not terminal evidence.", account=account["address"])
            if not page:
                account["terminal"] = "empty native signature page"
                account["terminal_evidence"] = page_hash
            else:
                signatures = [entry.get("signature") if isinstance(entry, dict) else None for entry in page]
                if not all(isinstance(s, str) and s for s in signatures) or len(set(signatures)) != len(signatures):
                    gap("Signature page has missing or repeated signatures.", account=account["address"])
                if account["cursor"] in signatures:
                    gap("Provider repeated a pagination cursor.", account=account["address"])
                previous = account["last_slot"]
                crossed_floor = False
                for entry in page:
                    entry_slot = entry.get("slot")
                    if not _integer(entry_slot) or (previous is not None and entry_slot > previous):
                        gap("Signature page is missing slot order or is out of order.", entry["signature"], account["address"])
                    previous = entry_slot
                    if entry_slot > slot:
                        # Newer finalized activity may appear after our anchor.
                        continue
                    timestamp = entry.get("blockTime")
                    if timestamp is not None and not _integer(timestamp):
                        gap("Signature time is malformed.", entry["signature"], account["address"])
                    if timestamp is not None and timestamp >= end_ts:
                        continue
                    if timestamp is not None and timestamp < floor:
                        crossed_floor = True
                        continue
                    raw = await transaction(entry["signature"])
                    if raw["slot"] != entry_slot:
                        gap("Signature and transaction slot disagree.", entry["signature"], account["address"])
                    if timestamp is not None and raw["blockTime"] != timestamp:
                        gap("Signature and transaction time disagree.", entry["signature"], account["address"])
                    if raw["blockTime"] < floor:
                        crossed_floor = True
                    await notify()
                account["cursor"] = signatures[-1]
                account["last_slot"] = previous
                if crossed_floor:
                    account["terminal"] = "bounded acquisition lookback reached; older basis remains unknown"
                    account["terminal_evidence"] = page_hash
            account["pages"] += 1
            account["page_hashes"].append(content_hash)
            cp["pages"] += 1
            await notify()
        stage = "ordering"
        slots = defaultdict(list)
        for signature, item in cp["transactions"].items():
            raw = store.evidence(item["evidence_hash"])
            if isinstance(raw, dict) and _integer(raw.get("slot")):
                slots[raw["slot"]].append(signature)
        for block_slot, signatures in slots.items():
            if len(signatures) < 2 or all(signature in cp["ordering"] for signature in signatures):
                continue
            block = await rpc("getBlock", [block_slot, {"transactionDetails": "signatures", "rewards": False, "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
            evidence({"method": "getBlock", "slot": block_slot, "result": block}, "block-order")
            if not isinstance(block, dict) or not isinstance(block.get("signatures"), list) or not all(signature in block["signatures"] for signature in signatures):
                gap("Same-slot transaction order cannot be established from block evidence.")
            for signature in signatures:
                cp["ordering"][signature] = block["signatures"].index(signature)
            await notify()
        stage = "collected"
        await notify()
        return result()
    except asyncio.CancelledError:
        # Persist both our collector record and the owning job progress callback.
        # The cancelled HTTP attempt may already have consumed a durable credit.
        try:
            await notify()
        except Exception:
            pass
        raise
    except CollectionPaused as exc:
        persist()
        raise CollectionPaused(exc.reason, deepcopy(cp), result()) from None
    except (QuotaExceeded, EvidenceError) as exc:
        persist()
        if isinstance(exc, QuotaExceeded):
            reason = "Free application credit cap reached, including pending requests; collection is incomplete. Resume only within the confirmed provider cycle and budget."
        else:
            reason = "Archived evidence is missing or failed its checksum; restore a verified local backup before relying on this report."
        try:
            partial = result()
        except Exception:
            partial = None
        raise CollectionPaused(reason, deepcopy(cp), partial) from None
    except ProviderError as exc:
        persist()
        reason = str(exc)
        raise CollectionPaused(reason, deepcopy(cp), result()) from None
    except Exception as exc:
        # Upstream errors and credential URLs never enter persisted progress.
        persist()
        reason = "Collection paused by a local quota, evidence integrity, storage or provider error."
        try:
            partial = result()
        except Exception:
            partial = None
        raise CollectionPaused(reason, deepcopy(cp), partial) from None
    finally:
        # Cancellation also preserves credits charged since the last page callback.
        try:
            persist()
        except Exception:
            pass
        if hasattr(gateway, "credit_ceiling"):
            gateway.credit_ceiling = old_ceiling
