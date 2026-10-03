"""Repeatable offline checks for an explicitly enumerated transaction set.

This certificate proves properties of supplied raw records, not a complete
wallet ledger or continuous historical interval. Content hashes detect a changed
record; they do not authenticate an arbitrary import as a mainnet observation.
Only the fingerprint in the independently reviewed fixture manifest is labelled
as a reviewed mainnet record. No import can supply a trusted completeness flag,
token classification, opening cost, or financial qualification.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re

from .accounting import canonical, decimal, raw_quantity, validate_fee_allocations
from .config import validate_address
from .decoder import SYSTEM_ID, TOKEN_IDS
from .investigation import WSOL, decode_supported_swaps

VERSION = "scoped-evidence-audit-v2"
MAX_TRANSACTIONS = 20
MAX_BUNDLE_BYTES = 4 * 1024 * 1024
_HASH = re.compile(r"^[a-f0-9]{64}$")
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_REVIEWED_MAINNET = {
    "9ffe9059c331907e4c8d9835e4c06fd1d258782da7b96c7bb639c00ded5001d0": {
        "signature": "2w3FS5exzzoFkHXCdsfWreHApvEGq7WBfMas9qNBhhmsnLmBPURs2u1nVtTKDM2SQeDNw2rNrLbjMoSLQ3HNuYAo",
        "fixture": "tests/fixtures/mainnet-pumpswap-buy-exact-quote.json",
        "review": "Independent arithmetic and raw-path review; one transaction only",
    },
}


def _encoded(value):
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > 64:
            raise ValueError("Raw evidence JSON nesting exceeds the 64-level local limit")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode()
    except RecursionError as error:
        raise ValueError("Raw evidence JSON nesting exceeds the local parser limit") from error
    except TypeError as error:
        raise ValueError("Raw evidence must contain ordinary JSON values") from error


def _signature(value):
    if not isinstance(value, str) or not 64 <= len(value) <= 88:
        return False
    number = 0
    for character in value:
        if character not in _ALPHABET:
            return False
        number = number * 58 + _ALPHABET.index(character)
    return (len(value) - len(value.lstrip("1")) + (number.bit_length() + 7) // 8) == 64


def _uint(value):
    if type(value) is not int or value < 0 or value > 2**64 - 1:
        raise ValueError("Missing or invalid unsigned RPC integer")
    return value


def _check(state, detail, hashes=(), actual=None, paths=()):
    return {"state": state, "detail": detail, "actual": actual,
            "evidence": sorted(set(hashes)), "paths": sorted(set(paths))}


def _combined(checks, detail, hashes=()):
    states = {check["state"] for check in checks}
    reasons = sorted({check["detail"] for check in checks if check["state"] != "PASS"})
    result = _check("FAIL" if "FAIL" in states else "UNKNOWN" if "UNKNOWN" in states or not states else "PASS",
                    "; ".join(reasons) if reasons else detail, hashes)
    result["record_checks"] = checks
    return result


def _economic_fee_allocation(events, fee_lamports, paid, digest, *, failed=False,
                             native_reconciled=True):
    """Certify actual fee treatment without netting away unresolved movements.

    A native equation establishes quantities, not each movement's economic role.
    The current supported decoder has no provenance-backed outside-cost role
    resolver, so every material outside movement remains a limitation. Only its
    validated display-fee link can prove allocation to a successful trade;
    sponsored costs and committed failed-transaction overhead are separate cases.
    """
    fees = [(index, event) for index, event in enumerate(events) if event.get("kind") == "fee"]
    outside_movements = [event for event in events if event.get("kind") == "capital"
                         and decimal(event.get("amount_sol")) != 0]
    actual = {"outside_movements": [{"path": event.get("path"), "amount_sol": event["amount_sol"],
                                      "direction": event.get("direction"),
                                      "economic_role": event.get("economic_role", "unknown")}
                                     for event in outside_movements],
              "network_fee_treatment": None}
    paths = [event.get("path") for _, event in fees] + [event.get("path") for event in outside_movements]
    paths = [path for path in paths if isinstance(path, str)]

    def result(state, detail):
        return _check(state, detail, [digest], actual, paths)

    if not native_reconciled:
        return result("FAIL", "Fee treatment cannot be certified when native fee charging does not reconcile")
    if len(fees) != 1:
        return result("UNKNOWN", "An exact single decoder fee record is required to certify its economic treatment")
    fee_index, fee = fees[0]
    if (decimal(fee.get("amount_sol")) != Decimal(fee_lamports) / 1_000_000_000
            or fee.get("paid_by_wallet") is not paid or fee.get("failed") is not failed):
        return result("FAIL", "Decoder fee amount, wallet payer or success state disagrees with the raw transaction")
    actual["network_fee_treatment"] = {"allocation": fee.get("allocation"),
                                      "allocated_trade_path": fee.get("allocated_trade_path"),
                                      "paid_by_wallet": paid, "failed": failed}
    try:
        allocations = validate_fee_allocations(events)
    except ValueError as error:
        return result("FAIL", "Decoder fee allocation does not validate: " + str(error))
    if failed:
        if len(events) != 1 or fee.get("allocation") != "unallocated" or allocations:
            return result("FAIL", "Failed transactions must retain one unallocated fee overhead record and no committed economic movement")
        return result("PASS", "Exact failed-transaction fee is retained once as wallet-paid overhead or excluded as sponsored cost")
    # No outside economic role is established by the current raw decoder. Even
    # opposite quantities or a supplied role label cannot prove an all-in cost.
    if outside_movements:
        return result("UNKNOWN", "Individual material outside movements have unresolved economic roles; their signed net delta cannot establish complete trading costs")
    if any(event.get("kind") == "unsupported" for event in events):
        return result("UNKNOWN", "The decoder retains an unsupported economic observation; complete trading costs are unresolved")
    trades = [(index, event) for index, event in enumerate(events) if event.get("kind") in ("buy", "sell")]
    if len(trades) != 1:
        return result("UNKNOWN", "An exact single supported trade is required to certify successful fee treatment")
    trade_index, trade = trades[0]
    if paid:
        if allocations.get(fee_index) != trade_index:
            return result("UNKNOWN", "The actual decoder fee record is not linked to this supported trade's purchase basis or sale proceeds")
        paths.append(trade["path"])
        return result("PASS", "Actual wallet-paid decoder fee allocation validates once against the exact supported trade")
    if allocations or fee.get("allocation") != "unallocated" or decimal(trade.get("fee_sol")) != 0 or trade.get("paid_by_wallet") is not False:
        return result("FAIL", "Sponsored network fees must remain excluded from the scoped wallet's trade cost")
    return result("PASS", "Raw payer evidence and actual decoder records exclude the sponsored network fee from wallet trade cost")


def _keys_and_signers(raw, signature):
    transaction, meta = raw.get("transaction"), raw.get("meta")
    if not isinstance(transaction, dict) or not isinstance(meta, dict):
        raise ValueError("Raw transaction or metadata is missing")
    signatures = transaction.get("signatures")
    if (not isinstance(signatures, list) or not signatures or signatures[0] != signature
            or not all(_signature(value) for value in signatures)):
        raise ValueError("Native signature identity is missing or disagrees")
    message = transaction.get("message")
    entries = message.get("accountKeys") if isinstance(message, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("Transaction account keys are missing")
    if all(isinstance(entry, dict) for entry in entries):
        keys = [validate_address(entry.get("pubkey")) for entry in entries]
        if any(type(entry.get("signer")) is not bool for entry in entries):
            raise ValueError("Native signer flags are missing")
        flags = [entry["signer"] for entry in entries]
        if sum(flags) != len(signatures) or flags != [True] * len(signatures) + [False] * (len(keys) - len(signatures)):
            raise ValueError("Native signer ordering disagrees with transaction signatures")
        signers = keys[:len(signatures)]
    elif all(isinstance(entry, str) for entry in entries):
        keys = [validate_address(entry) for entry in entries]
        header = message.get("header")
        count = header.get("numRequiredSignatures") if isinstance(header, dict) else None
        if type(count) is not int or count != len(signatures) or not 0 < count <= len(keys):
            raise ValueError("Native signer header is missing or disagrees")
        signers = keys[:count]
        loaded = meta.get("loadedAddresses") or {}
        if not isinstance(loaded, dict):
            raise ValueError("Loaded account keys are malformed")
        for side in ("writable", "readonly"):
            if not isinstance(loaded.get(side, []), list):
                raise ValueError("Loaded account keys are malformed")
            keys += [validate_address(value) for value in loaded.get(side, [])]
    else:
        raise ValueError("Mixed or malformed account key encodings")
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate transaction account keys")
    return keys, signers, message, meta


def _instructions(message, meta, keys):
    outer = message.get("instructions")
    if not isinstance(outer, list):
        raise ValueError("Transaction instructions are missing")
    result = []

    def append(instruction, path):
        if not isinstance(instruction, dict):
            raise ValueError("Malformed transaction instruction")
        program = instruction.get("programId")
        if program is None:
            index = _uint(instruction.get("programIdIndex"))
            if index >= len(keys):
                raise ValueError("Program account index exceeds account keys")
            program = keys[index]
        parsed = instruction.get("parsed")
        info = parsed.get("info") if isinstance(parsed, dict) else None
        kind = parsed.get("type") if isinstance(parsed, dict) else None
        info = info if isinstance(info, dict) else {}
        if program in TOKEN_IDS and kind in ("transfer", "transferChecked"):
            token = info.get("tokenAmount") if kind == "transferChecked" else None
            amount = token.get("amount") if isinstance(token, dict) else info.get("amount")
            if raw_quantity(amount) > 2**64 - 1:
                raise ValueError("Parsed SPL transfer amount exceeds protocol u64 units")
        if program == SYSTEM_ID and kind in ("transfer", "createAccount", "createAccountWithSeed"):
            _uint(info.get("lamports"))
        result.append((path, program, kind, info))

    for index, instruction in enumerate(outer):
        append(instruction, f"instructions.{index}")
    groups = meta.get("innerInstructions")
    if not isinstance(groups, list):
        raise ValueError("Inner instruction evidence is missing")
    seen = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Malformed inner instruction group")
        index = _uint(group.get("index"))
        if index >= len(outer) or index in seen or not isinstance(group.get("instructions"), list):
            raise ValueError("Inner instruction group identity is invalid")
        seen.add(index)
        for offset, instruction in enumerate(group["instructions"]):
            append(instruction, f"innerInstructions.{index}.{offset}")
    return result


def _owned_balances(meta, keys, address):
    identities, sides = {}, {"pre": {}, "post": {}}
    for side, field in (("pre", "preTokenBalances"), ("post", "postTokenBalances")):
        rows = meta.get(field)
        if not isinstance(rows, list):
            raise ValueError("Event-time token balances are missing")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Malformed event-time token balance")
            index = _uint(row.get("accountIndex"))
            if index >= len(keys):
                raise ValueError("Token account index exceeds account keys")
            account = keys[index]
            owner, mint = validate_address(row.get("owner")), validate_address(row.get("mint"))
            token_program = row.get("programId")
            if token_program is not None and token_program not in TOKEN_IDS:
                raise ValueError("Event-time token balance names an unsupported token program")
            token = row.get("uiTokenAmount")
            if not isinstance(token, dict):
                raise ValueError("Token integer amount is missing")
            decimals = _uint(token.get("decimals"))
            if decimals > 255:
                raise ValueError("Token decimals exceed supported range")
            identity = (owner, mint, decimals, token_program)
            if account in identities and identities[account] != identity:
                raise ValueError("Token ownership, mint, decimals or token program changed between endpoints")
            if account in sides[side]:
                raise ValueError("Duplicate event-time token balance")
            identities[account] = identity
            quantity = raw_quantity(token.get("amount"))
            if quantity > 2**64 - 1:
                raise ValueError("SPL token balance exceeds protocol u64 units")
            sides[side][account] = quantity
    rows = []
    for account, (owner, mint, decimals, _) in identities.items():
        if owner != address:
            continue
        if account not in sides["pre"] or account not in sides["post"]:
            raise ValueError("Owned token account lacks an endpoint; creation/closure needs separate proof")
        before, after = sides["pre"][account], sides["post"][account]
        rows.append({"account": account, "mint": mint, "decimals": decimals,
                     "pre_quantity_raw": str(before), "post_quantity_raw": str(after),
                     "delta_quantity_raw": str(after - before)})
    return rows


def _temporary_wraps(instructions, keys, before, after, owned, address):
    """Require the actual create/initialise/close paths for endpoint-absent wSOL."""
    endpoint_accounts = {row["account"] for row in owned}
    candidates = set()
    for _, program, kind, info in instructions:
        if program in TOKEN_IDS and kind in ("initializeAccount", "initializeAccount2", "initializeAccount3"):
            if info.get("owner") == address and info.get("mint") == WSOL:
                candidates.add(info.get("account"))
        if kind in ("create", "createIdempotent") and info.get("wallet") == address and info.get("mint") == WSOL:
            candidates.add(info.get("account"))
    result = []
    for account in sorted(candidates - endpoint_accounts):
        if account not in keys:
            raise ValueError("Temporary wrapped account is absent from native endpoints")
        creates, initializations, closures = [], [], []
        for path, program, kind, info in instructions:
            if program == SYSTEM_ID and kind in ("createAccount", "createAccountWithSeed") and info.get("newAccount") == account:
                if info.get("source") != address or info.get("owner") not in TOKEN_IDS:
                    raise ValueError("Temporary wrapped account funding or program ownership is unproven")
                creates.append((path, _uint(info.get("lamports"))))
            if program in TOKEN_IDS and kind in ("initializeAccount", "initializeAccount2", "initializeAccount3") and info.get("account") == account:
                if info.get("owner") != address or info.get("mint") != WSOL:
                    raise ValueError("Temporary wrapped account wallet ownership is unproven")
                initializations.append(path)
            if program in TOKEN_IDS and kind == "closeAccount" and info.get("account") == account:
                if info.get("owner") != address or info.get("destination") != address:
                    raise ValueError("Temporary wrapped account closure does not return to its owner")
                closures.append(path)
        if len(creates) != 1 or len(initializations) != 1 or len(closures) != 1:
            raise ValueError("Temporary wrapped SOL requires exactly one raw create, initialize and wallet closure")
        index = keys.index(account)
        if before[index] != 0 or after[index] != 0:
            raise ValueError("Temporary wrapped SOL native endpoints must both be zero")
        result.append({"account": account, "pre_lamports": "0", "post_lamports": "0",
                       "rent_funded_lamports": str(creates[0][1]), "rent_refunded_lamports": str(creates[0][1]),
                       "paths": [creates[0][0], initializations[0], closures[0]]})
    return result


def _record_audit(record, address, store):
    signature = record.get("signature")
    raw = record.get("raw")
    if isinstance(raw, dict) and "result" in raw:
        raw = raw["result"]
    row = {"signature": signature, "evidence_hash": None, "checks": {}, "events": [],
           "owned_balances": [], "wrap_lifecycle": [], "native_equation": None,
           "unsupported": []}
    checks = row["checks"]
    if not isinstance(raw, dict):
        checks["raw_integrity"] = _check("FAIL", "The claimed signature has no raw transaction result")
        return row
    digest = sha256(_encoded(raw)).hexdigest()
    row["evidence_hash"] = digest
    transaction = raw.get("transaction")
    native_signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
    row["native_signature"] = native_signatures[0] if isinstance(native_signatures, list) and native_signatures and isinstance(native_signatures[0], str) else None
    if store is not None and store.archive(raw) != digest:
        raise ValueError("Evidence archive canonical hash disagrees")
    supplied = record.get("evidence_hash")
    if supplied is not None and (not isinstance(supplied, str) or not _HASH.fullmatch(supplied) or supplied != digest):
        checks["raw_integrity"] = _check("FAIL", "The supplied evidence hash does not match canonical raw content", [digest])
        return row
    checks["raw_integrity"] = _check("PASS", "SHA-256 of canonical raw JSON matches its immutable content identifier", [digest])
    reviewed = _REVIEWED_MAINNET.get(digest)
    checks["chain_provenance"] = _check(
        "PASS" if reviewed and reviewed["signature"] == signature else "UNKNOWN",
        reviewed["review"] if reviewed and reviewed["signature"] == signature else
        "An arbitrary import is not authenticated mainnet evidence by a hash or a supplied source label", [digest])
    try:
        slot, timestamp = _uint(raw.get("slot")), _uint(raw.get("blockTime"))
        row.update(slot=slot, block_time=datetime.fromtimestamp(timestamp, timezone.utc).isoformat())
        version = raw.get("version", "legacy")
        if version != "legacy" and not (type(version) is int and version == 0):
            raise ValueError("Unsupported transaction version")
        keys, signers, message, meta = _keys_and_signers(raw, signature)
        if address not in signers:
            raise ValueError("Investigated wallet is not a native signer")
        if "err" not in meta:
            raise ValueError("Transaction success state is missing")
        checks["identity"] = _check("PASS", "Native signer metadata identifies this wallet; event-time owner checks are separate", [digest], signers)
        fee = _uint(meta.get("fee"))
        paid = keys[0] == address
        row.update(network_fee_lamports=str(fee), wallet_fee_lamports=str(fee if paid else 0))
        checks["network_fees"] = _check("PASS", "Exact meta.fee includes network and priority fees; sponsored fees are excluded", [digest], row["wallet_fee_lamports"], ["meta.fee"])
        before, after = meta.get("preBalances"), meta.get("postBalances")
        if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(keys) or len(after) != len(keys):
            raise ValueError("Native account endpoint balances are incomplete")
        before, after = [_uint(value) for value in before], [_uint(value) for value in after]
        wallet_delta = after[keys.index(address)] - before[keys.index(address)]
        row["native_wallet_delta_lamports"] = str(wallet_delta)
        if meta["err"] is not None:
            # Instructions in a failed transaction were attempted, not committed.
            # Fee charging is the only state change certified here.
            failed_decoded = decode_supported_swaps([{**record, "raw": raw, "evidence_hash": digest}], address)
            row["events"] = failed_decoded["events"]
            only_fee = all(after[index] - before[index] == (-(fee if paid else 0) if key == address else -fee if index == 0 else 0)
                           for index, key in enumerate(keys))
            for key in ("account_ownership", "wrap_lifecycle", "swap_quantity", "swap_consideration"):
                checks[key] = _check("UNKNOWN", "Failed instructions do not prove committed token ownership, account lifecycle or a successful exchange", [digest])
            checks["native_reconciliation"] = _check("PASS" if only_fee else "FAIL", "Failed transaction native endpoints must reflect fee charging alone", [digest], str(wallet_delta))
            if not only_fee:
                checks["network_fees"] = _check("FAIL", "Claimed failed-transaction fee disagrees with its native endpoint changes", [digest])
            checks["fee_allocation"] = _economic_fee_allocation(row["events"], fee, paid, digest,
                                                               failed=True, native_reconciled=only_fee)
            return row
        if sum(before) - sum(after) != fee:
            checks["network_fees"] = _check("FAIL", "Claimed meta.fee does not reconcile to native account conservation", [digest])
            raise ValueError("Native account balances do not conserve the exact transaction network fee")
        row["owned_balances"] = _owned_balances(meta, keys, address)
        instructions = _instructions(message, meta, keys)
        wraps = _temporary_wraps(instructions, keys, before, after, row["owned_balances"], address)
        owned_accounts = {item["account"] for item in row["owned_balances"]} | {item["account"] for item in wraps}
        row["accounts"] = sorted({address} | owned_accounts)
        checks["account_ownership"] = _check("UNKNOWN" if wraps else "PASS", "Temporary account ownership requires a completely evidenced committed lifecycle" if wraps else "Event-time endpoints identify owned accounts involved in these records only", [digest], row["accounts"])
        checks["wrap_lifecycle"] = _check("UNKNOWN", "Temporary wSOL lifecycle needs primary paths and a completely reconciled successful route", [digest])
        decoded = decode_supported_swaps([{**record, "raw": raw, "evidence_hash": digest}], address)
        row["events"], row["unsupported"] = decoded["events"], decoded["unresolved"]
        trades = [event for event in row["events"] if event["kind"] in ("buy", "sell")]
        if len(trades) != 1:
            reason = "; ".join(issue["reason"] for issue in row["unsupported"]) or "No supported single swap was reconstructed"
            for key in ("swap_quantity", "swap_consideration", "native_reconciliation", "fee_allocation"):
                checks[key] = _check("FAIL", reason, [digest])
            checks["wrap_lifecycle"] = _check("UNKNOWN", "No completely reconciled supported route establishes this temporary lifecycle: " + reason, [digest])
            return row
        trade = trades[0]
        checks["swap_quantity"] = _check("PASS", "Reviewed instruction layout, event-time ownership and parsed transfers reconcile exact raw units", [digest], {"mint": trade["mint"], "quantity_raw": trade["quantity_raw"], "decimals": trade["decimals"]}, [trade["path"], "meta.preTokenBalances", "meta.postTokenBalances"])
        checks["swap_consideration"] = _check("PASS", "Native/SOL settlement agrees with parsed owned wrapped-SOL transfer legs", [digest], trade["amount_sol"], [trade["path"]])
        settlement = int(Decimal(trade["amount_sol"]) * 1_000_000_000) * (-1 if trade["kind"] == "buy" else 1)
        outside = sum(int(Decimal(event["amount_sol"]) * 1_000_000_000) * (-1 if event["direction"] == "withdrawal" else 1)
                      for event in row["events"] if event["kind"] == "capital")
        wsol_delta, reserve_delta = 0, 0
        for item in row["owned_balances"]:
            index = keys.index(item["account"])
            delta = int(item["delta_quantity_raw"])
            native_delta = after[index] - before[index]
            if item["mint"] == WSOL:
                wsol_delta += delta
                reserve_delta += native_delta - delta
            else:
                reserve_delta += native_delta
        expected = settlement - (fee if paid else 0) - reserve_delta - wsol_delta + outside
        equation = {"observed_wallet_delta_lamports": str(wallet_delta),
                    "swap_settlement_lamports": str(settlement), "wallet_network_fee_lamports": str(fee if paid else 0),
                    "outside_native_delta_lamports": str(outside), "owned_rent_reserve_delta_lamports": str(reserve_delta),
                    "owned_wsol_endpoint_delta_lamports": str(wsol_delta),
                    "expected_wallet_delta_lamports": str(expected), "residual_lamports": str(wallet_delta - expected)}
        row["native_equation"] = equation
        checks["native_reconciliation"] = _check("PASS" if expected == wallet_delta else "FAIL", "Exact wallet delta = swap settlement - paid fee - owned reserve change - wSOL endpoint change + outside native flows", [digest], equation)
        # The reviewed swap decoder additionally proves primary lifecycle order,
        # native-token program/space, sync-before-debit and nonnegative funded
        # provisional inventory. A partial or failed decoder cannot certify rent.
        if expected == wallet_delta:
            row["wrap_lifecycle"] = wraps
            checks["wrap_lifecycle"] = _check("PASS", "Primary wallet-funded create, initialize and wallet-refund closure reconcile with exact native conservation and the supported route", [digest], wraps, [path for item in wraps for path in item["paths"]])
            checks["account_ownership"] = _check("PASS", "Event-time token endpoints and fully reconciled committed temporary lifecycle identify the involved owned accounts", [digest], row["accounts"])
        checks["fee_allocation"] = _economic_fee_allocation(row["events"], fee, paid, digest,
                                                           native_reconciled=expected == wallet_delta)
    except (ValueError, KeyError, IndexError, TypeError, OverflowError, OSError) as error:
        detail = str(error)
        for key in ("identity", "network_fees", "account_ownership", "wrap_lifecycle", "swap_quantity", "swap_consideration", "native_reconciliation", "fee_allocation"):
            if key not in checks:
                checks[key] = _check("FAIL", detail, [digest])
        row["unsupported"].append({"signature": signature, "reason": detail, "evidence": [digest]})
    return row


def audit_raw_bundle(bundle, store=None):
    """Audit at most 20 imported raw records; optionally archive primary content.

    scope.signatures enumerates the requested records, not an RPC pagination
    proof. Optional scope.accounts must contain exactly the wallet and every
    evidenced owned account involved in the supplied transactions. Omitting an
    account or claimed signature fails that scoped completeness check. Extra
    accounts remain unknown. Every wallet-wide financial metric stays unknown.
    """
    if not isinstance(bundle, dict) or bundle.get("version") != "raw-evidence-v1":
        raise ValueError("Expected a raw-evidence-v1 bundle")
    if len(_encoded(bundle)) > MAX_BUNDLE_BYTES:
        raise ValueError("Raw evidence bundle exceeds the 4 MiB local limit")
    address = validate_address(bundle.get("address"))
    records, scope = bundle.get("transactions"), bundle.get("scope")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_TRANSACTIONS or any(not isinstance(record, dict) for record in records):
        raise ValueError("Supply 1–20 raw transaction records")
    if not all(_signature(record.get("signature")) for record in records):
        raise ValueError("Every raw record must identify a valid transaction signature")
    if not isinstance(scope, dict) or scope.get("kind") != "transaction_set":
        raise ValueError("Only an explicitly enumerated transaction_set boundary is supported")
    signatures = scope.get("signatures")
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= MAX_TRANSACTIONS or not all(_signature(value) for value in signatures):
        raise ValueError("Enumerate 1–20 valid transaction signatures in scope")
    accounts = scope.get("accounts")
    if accounts is not None:
        if not isinstance(accounts, list) or len(accounts) > 1000:
            raise ValueError("Account boundary must contain at most 1000 public addresses")
        accounts = [validate_address(value) for value in accounts]
    rows = [_record_audit(record, address, store) for record in records]
    hashes = sorted({row["evidence_hash"] for row in rows if row["evidence_hash"]})
    checks = {}
    for key in ("raw_integrity", "chain_provenance", "identity", "network_fees", "account_ownership", "wrap_lifecycle", "swap_quantity", "swap_consideration", "native_reconciliation", "fee_allocation"):
        checks[key] = _combined([row["checks"].get(key, _check("UNKNOWN", "Raw prerequisite failed")) for row in rows], "Per-record checks for this explicit transaction set", hashes)
    seen = [row.get("signature") for row in rows]
    complete_set = (len(set(signatures)) == len(signatures) and all(_signature(value) for value in seen)
                    and Counter(signatures) == Counter(seen) and len(set(seen)) == len(seen)
                    and all(row["checks"]["raw_integrity"]["state"] == "PASS" and row.get("native_signature") == row["signature"] for row in rows))
    checks["transaction_set"] = _check("PASS" if complete_set else "FAIL", "Every enumerated signature appears exactly once with no extra record; this does not establish an interval's full history", hashes,
                                       {"claimed": signatures, "supplied": seen})
    involved = sorted({address} | {account for row in rows for account in row.get("accounts", [])})
    if accounts is None:
        checks["account_boundary"] = _check("PASS" if checks["account_ownership"]["state"] == "PASS" else "UNKNOWN", "Boundary derived solely from raw transaction keys and event-time owned accounts; hidden historical accounts remain outside this claim", hashes, involved)
    else:
        missing, extra = sorted(set(involved) - set(accounts)), sorted(set(accounts) - set(involved))
        checks["account_boundary"] = _check("FAIL" if missing or len(accounts) != len(set(accounts)) else "UNKNOWN" if extra or checks["account_ownership"]["state"] != "PASS" else "PASS", "Declared boundary must include every evidenced involved owned account; additional ownership is not assumed", hashes, {"missing": missing, "unproven_extra": extra})
    slots = [row.get("slot") for row in rows]
    checks["transaction_order"] = _check("PASS" if all(type(slot) is int for slot in slots) and len(slots) == len(set(slots)) else "UNKNOWN", "Distinct native slots order this set; same-slot chronology requires independently evidenced block indices", hashes)
    unknown_reasons = {
        "wallet_history": "Enumerated records do not demonstrate complete signatures, closed historical accounts or continuous wallet ownership",
        "opening_basis": "Pre-existing units have no acquisition-cost history or independently proved wallet-wide zero anchor",
        "classification": "Venue, name and supplied classification are not provenance-backed meme lifecycle evidence",
        "closed_positions": "Transaction-level balances do not establish wallet-wide closed-to-zero episodes or known opening basis",
        "boundary_valuation": "Complete opening/closing assets, supported valuations and capital-flow roles are absent",
        "wallet_profit": "Complete wallet history, classified population, known costs and reconciled boundary equity have not been established",
        "four_week_consistency": "The independent 28-day interval has no complete corresponding history certificate",
        "copy_safety": "Financial reconstruction cannot prove legitimacy, historical sellability or intent toward followers",
    }
    for key, reason in unknown_reasons.items():
        checks[key] = _check("UNKNOWN", reason, hashes)
    metrics = {}

    def metric(key, value, unit, dependencies, reason=None):
        ready = all(checks[dependency]["state"] == "PASS" for dependency in dependencies)
        metrics[key] = {"value": value if ready else None, "status": "known" if ready else "unknown",
                        "unit": unit, "population": "Explicit transaction set only",
                        "reason": None if ready else reason or "Required scoped evidence check did not pass",
                        "evidence": hashes, "required_checks": dependencies}

    set_dependencies = ["raw_integrity", "transaction_set"]
    swap_dependencies = set_dependencies + ["identity", "account_boundary", "swap_quantity", "swap_consideration", "wrap_lifecycle", "native_reconciliation"]
    trades = [event for row in rows for event in row["events"] if event["kind"] in ("buy", "sell")]
    metric("transaction_count", str(len(rows)), "transactions", set_dependencies)
    metric("decoded_swap_count", str(len(trades)), "swaps", swap_dependencies)
    metric("gross_buy_consideration_sol", canonical(sum((Decimal(event["amount_sol"]) for event in trades if event["kind"] == "buy"), Decimal(0))), "SOL", swap_dependencies)
    metric("gross_sell_proceeds_sol", canonical(sum((Decimal(event["amount_sol"]) for event in trades if event["kind"] == "sell"), Decimal(0))), "SOL", swap_dependencies)
    metric("wallet_network_fees_sol", canonical(Decimal(sum(int(row.get("wallet_fee_lamports", "0")) for row in rows)) / 1_000_000_000), "SOL", set_dependencies + ["identity", "network_fees"])
    metric("native_wallet_delta_sol", canonical(Decimal(sum(int(row.get("native_wallet_delta_lamports", "0")) for row in rows)) / 1_000_000_000), "SOL", set_dependencies + ["identity", "native_reconciliation"])
    metric("outside_native_delta_sol", canonical(Decimal(sum(int(row["native_equation"]["outside_native_delta_lamports"]) for row in rows if row["native_equation"])) / 1_000_000_000), "SOL", swap_dependencies)
    quantities = defaultdict(int)
    for event in trades:
        quantities[event["mint"]] += int(event["quantity_raw"]) * (1 if event["kind"] == "buy" else -1)
    metric("asset_net_quantities_raw", {mint: str(amount) for mint, amount in sorted(quantities.items())}, "raw token units by mint", swap_dependencies)
    for key, unit, dependency in (("opening_basis_sol", "SOL", "opening_basis"), ("wallet_profit_sol", "SOL", "wallet_profit"), ("realised_roi_pct", "%", "wallet_profit"), ("positive_weeks", "weeks", "four_week_consistency"), ("economic_pnl_sol", "SOL", "boundary_valuation")):
        metric(key, None, unit, [dependency], checks[dependency]["detail"])
    reconstruction_passed = all(checks[key]["state"] == "PASS" for key in swap_dependencies)
    certificate = {"version": VERSION, "status": "SCOPED_RECONSTRUCTION" if reconstruction_passed else "INCOMPLETE",
                   "checks": checks, "wallet_history_complete": False,
                   "financial_qualification": "UNRESOLVED", "scope_kind": "transaction_set"}
    certificate["content_hash"] = sha256(_encoded({"address": address, "scope": scope, "certificate": certificate, "metrics": metrics, "records": hashes})).hexdigest()
    return {"version": VERSION, "source": "raw-mainnet-records" if checks["chain_provenance"]["state"] == "PASS" else "unverified-import",
            "address": address, "scope": {"kind": "transaction_set", "signatures": signatures,
                                            "accounts": involved, "declared_accounts": accounts,
                                            "history_complete": False,
                                            "description": "Explicit records and involved owned accounts; no wallet-wide or continuous-interval completeness claim"},
            "certificate": certificate, "metrics": metrics, "reconstruction": rows,
            "events": [event for row in rows for event in row["events"]],
            "evidence": [{"kind": "getTransaction", "signature": row["signature"], "hash": row["evidence_hash"]} for row in rows if row["evidence_hash"]],
            "findings": [{"key": key, **check} for key, check in checks.items() if check["state"] != "PASS"],
            "unsupported": [issue for row in rows for issue in row["unsupported"]],
            "notes": ["A scoped certificate is an independently repeatable record check, not proof that a wallet is profitable or safe to copy.",
                      "Unknown economic roles, classification and historical ownership are preserved. Supplied completeness or classification labels are ignored."]}
