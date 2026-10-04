"""Bounded public wallet discovery, with native identity checks and dated evidence.

Trending-pool trades are leads, never a profit leaderboard. A pool-trade provider's
``tx_from_address`` can be a router, so only native signers with event-time owned
token movements can become identity-checked candidates. This module does not
infer historical P&L, legitimacy, or whether a trade can be profitably copied.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import inspect
import re
import shutil
import uuid

import httpx

from .providers import GeckoTerminal, Gateway, ProviderError, _public_address, _wait_for_rate
from .storage import EvidenceError, QuotaExceeded, now
from .candidate_import import derive_candidate_progress

VERSION = "public-pool-discovery-v1"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
SAMPLE_LIMIT = 300
PUBLIC_DAILY_CAP = 200
WRAPPED_SOL = "So11111111111111111111111111111111111111112"


def _signature(value):
    if not isinstance(value, str) or not 64 <= len(value) <= 88:
        return False
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    try:
        for char in value:
            number = number * 58 + alphabet.index(char)
    except ValueError:
        return False
    return len(value) - len(value.lstrip("1")) + (number.bit_length() + 7) // 8 == 64


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 128:
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0 and abs(number.adjusted()) <= 100 and abs(number.as_tuple().exponent) <= 100:
            return format(number, "f")
    except InvalidOperation:
        pass
    return None


def _time(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is not None:
            return date.astimezone(timezone.utc)
    except ValueError:
        pass
    return None


def _check_disk(store):
    settings = store.get("configuration", "settings", {})
    limits = settings.get("limits", {}) if isinstance(settings, dict) else {}
    reserve = limits.get("min_free_disk_mb", 2048) if isinstance(limits, dict) else 2048
    if type(reserve) is not int or reserve < 1:
        raise ValueError("Discovery disk reserve must be a positive integer.")
    if hasattr(store, "path") and shutil.disk_usage(store.path).free < reserve * 1024 * 1024:
        raise _DiscoveryPaused(f"Free disk space is below the configured {reserve} MB reserve. Free space or choose a data folder with more capacity before resuming; archived discovery evidence is retained.")


class DiscoveryProvider(GeckoTerminal):
    """The two static Solana public routes share the token-observation quota/gate."""

    async def _observe(self, kind, address=None):
        if kind not in ("trending-pools", "pool-trades"):
            raise ValueError("Unsupported public discovery observation.")
        if kind == "pool-trades" and not _public_address(address):
            raise ValueError("Pool must be a 32-byte base58 public address.")
        _check_disk(self.store)
        identifier = kind if address is None else kind + ":" + address
        cached = self.store.get("discovery_observations", identifier)
        if isinstance(cached, dict):
            observed = _time(cached.get("observed_at"))
            if observed and 0 <= (datetime.now(timezone.utc) - observed).total_seconds() < 900:
                archived = self.store.evidence(cached.get("evidence_hash"))
                if (isinstance(archived, dict) and archived.get("kind") == kind and archived.get("pool_address") == address and
                        archived.get("observed_at") == cached.get("observed_at") and isinstance(archived.get("result"), dict) and
                        isinstance(archived["result"].get("data"), list)):
                    return {**cached, "result": archived["result"], "cached": True}
        route = "networks/solana/trending_pools" if kind == "trending-pools" else f"networks/solana/pools/{address}/trades"
        for attempt in range(3):
            _check_disk(self.store)
            cycle = datetime.now(timezone.utc).date().isoformat()
            reservation = self.store.reserve("geckoterminal", kind, 1, cycle, self.cap)
            dispatched = False
            try:
                await _wait_for_rate(self._gate, 60 / 8)
                _check_disk(self.store)
                self.store.dispatch(reservation)
                dispatched = True
                response = await self._client.get(route, params={"page": 1} if kind == "trending-pools" else None)
            except httpx.TransportError:
                raise ProviderError("Public discovery connection failed; dispatched request was charged.", "transport") from None
            finally:
                if dispatched:
                    self.store.settle(reservation, charge=True)
                else:
                    self.store.release(reservation)
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                delay = Gateway._retry_after(response.headers.get("Retry-After"), attempt)
                if delay > 60:
                    raise ProviderError("Public discovery requested extended backoff; resume later.", "backoff")
                await asyncio.sleep(delay)
                continue
            if 300 <= response.status_code < 400:
                raise ProviderError("Public discovery redirects are blocked.", "redirect")
            if response.status_code >= 400:
                raise ProviderError("Public discovery observation unavailable.", response.status_code)
            if len(response.content) > 2_000_000:
                raise ProviderError("Public discovery exceeded the local response-size limit.", "malformed")
            try:
                raw = response.json()
            except ValueError:
                raise ProviderError("Public discovery returned malformed JSON.", "malformed") from None
            observed_at = now()
            _check_disk(self.store)
            digest = self.store.archive({"provider": "geckoterminal", "network": "solana", "kind": kind,
                                         "pool_address": address, "observed_at": observed_at, "result": raw})
            record = {"provider": "geckoterminal", "kind": kind, "pool_address": address,
                      "observed_at": observed_at, "evidence_hash": digest, "cached": False}
            self.store.put("discovery_observations", identifier, record)
            return {**record, "result": raw}
        raise ProviderError("Public discovery retry limit reached.")

    async def trending_pools(self):
        return await self._observe("trending-pools")

    async def pool_trades(self, address):
        return await self._observe("pool-trades", address)


def _native_signers(raw, signature):
    """Identify signers and explicit token ownership without interpreting a swap."""
    if not isinstance(raw, dict):
        return {}, "Native transaction is missing."
    body, meta = raw.get("transaction"), raw.get("meta")
    if not isinstance(body, dict) or not isinstance(meta, dict):
        return {}, "Native transaction metadata is missing."
    signatures = body.get("signatures")
    if not isinstance(signatures, list) or not signatures or signatures[0] != signature or not all(_signature(item) for item in signatures):
        return {}, "Native transaction signature does not match the sampled signature."
    if "err" not in meta:
        return {}, "Native transaction success status is missing."
    if meta.get("err") is not None:
        return {}, "Native transaction failed; no successful token movement is inferred."
    version = raw.get("version", "legacy")
    if not (version == "legacy" or type(version) is int and version == 0):
        return {}, "Native transaction version is unsupported."
    if type(raw.get("slot")) is not int or raw["slot"] < 0 or type(raw.get("blockTime")) is not int or raw["blockTime"] < 0:
        return {}, "Native transaction slot or time is missing."
    message = body.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("accountKeys"), list):
        return {}, "Native transaction account keys are missing."
    entries = message["accountKeys"]
    if all(isinstance(entry, dict) for entry in entries):
        if not all(_public_address(entry.get("pubkey")) and type(entry.get("signer")) is bool for entry in entries):
            return {}, "Native signer account keys or flags are malformed."
        keys = [entry.get("pubkey") for entry in entries]
        signers = {entry.get("pubkey") for entry in entries if entry.get("signer") is True and _public_address(entry.get("pubkey"))}
        if len(signers) != len(signatures):
            return {}, "Native signer flags disagree with the transaction signatures."
    elif all(isinstance(entry, str) for entry in entries):
        keys = list(entries)
        header = message.get("header")
        count = header.get("numRequiredSignatures") if isinstance(header, dict) else None
        if type(count) is not int or not 0 < count <= len(keys) or count != len(signatures) or not all(_public_address(key) for key in keys):
            return {}, "Native signer flags or signature header are missing."
        signers = {key for key in keys[:count] if _public_address(key)}
        loaded = meta.get("loadedAddresses") or {}
        if not isinstance(loaded, dict) or any(not isinstance(loaded.get(side, []), list) or not all(_public_address(key) for key in loaded.get(side, [])) for side in ("writable", "readonly")):
            return {}, "Native loaded account keys are malformed."
        keys += loaded.get("writable", []) + loaded.get("readonly", [])
    else:
        return {}, "Native signer account keys are malformed."
    balances = {}
    malformed = set()
    for side, field in (("pre", "preTokenBalances"), ("post", "postTokenBalances")):
        rows = meta.get(field)
        if not isinstance(rows, list):
            return {}, "Native event-time token balances are missing."
        for row in rows:
            if not isinstance(row, dict):
                return {}, "Native token-balance metadata is malformed."
            index, owner, mint, token = row.get("accountIndex"), row.get("owner"), row.get("mint"), row.get("uiTokenAmount")
            if type(index) is not int or not 0 <= index < len(keys) or not isinstance(token, dict):
                return {}, "Native token-balance identity is malformed."
            amount, decimals = token.get("amount"), token.get("decimals")
            if not _public_address(mint) or type(decimals) is not int or not 0 <= decimals <= 255 or not isinstance(amount, str) or not amount.isascii() or not amount.isdigit() or len(amount) > 100:
                return {}, "Native token-balance amount or mint is malformed."
            previous = balances.setdefault(index, {"owner": owner, "mint": mint, "decimals": decimals, "pre": 0, "post": 0})
            if (owner, mint, decimals) != (previous["owner"], previous["mint"], previous["decimals"]):
                malformed.add(index)
            if side in previous.get("seen", []):
                malformed.add(index)
            previous.setdefault("seen", []).append(side)
            previous[side] = int(amount)
    flows = {address: {} for address in signers}
    for index, row in balances.items():
        if index in malformed or row["owner"] not in signers:
            continue
        mint = row["mint"]
        target = flows[row["owner"]].setdefault(mint, {"mint": mint, "raw_delta": 0, "decimals": row["decimals"]})
        if target["decimals"] != row["decimals"]:
            malformed.add(mint)
        target["raw_delta"] += row["post"] - row["pre"]
    result = {}
    for address, amounts in flows.items():
        values = [{**flow, "raw_delta": str(flow["raw_delta"])} for mint, flow in amounts.items() if mint not in malformed and flow["raw_delta"]]
        if values:
            result[address] = values
    return result, None if result else "No native signer has verified event-time owned token movements."


async def discover_candidates(store, gateway=None, *, pool_cap=3, candidate_cap=20,
                              validate_cap=8, progress=None, should_pause=None, transport=None, cohort_id=None):
    """Discover a dated bounded cohort; preserve partial evidence on every stop.

    ``progress`` receives the full cohort snapshot. ``should_pause`` may be sync
    or async. Selected transactions share the collector's immutable cache. Up to
    eight transaction lookups and eight current account checks are attempted.
    """
    for name, value, ceiling in (("pool_cap", pool_cap, 10), ("candidate_cap", candidate_cap, 20), ("validate_cap", validate_cap, 8)):
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError(f"{name} must be between 1 and {ceiling}.")
    if cohort_id is not None and (not isinstance(cohort_id, str) or not re.fullmatch(r"[a-f0-9]{32}", cohort_id)):
        raise ValueError("cohort_id must be a 32-character lowercase hexadecimal identifier.")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    cohort = {"id": cohort_id or uuid.uuid4().hex, "version": VERSION, "created_at": end.isoformat(), "cohort_date": end.date().isoformat(),
              "source": "public-pool-discovery", "status": "running", "stage": "Selecting pool universe", "universe": [],
              "candidates": [], "rejected_leads": [], "evidence": [], "misses": [],
              "sample": {"network": "solana", "universe": "GeckoTerminal trending pools, page 1", "pool_cap": pool_cap,
                         "candidate_cap": candidate_cap, "native_validation_cap": validate_cap, "per_pool_trade_cap": SAMPLE_LIMIT,
                         "window_start": start.isoformat(), "window_end": end.isoformat(), "boundary": "[start,end)",
                         "public_daily_request_cap": PUBLIC_DAILY_CAP, "public_requests_per_minute": 8},
              "counts": {"pools_observed": 0, "pools_sampled": 0, "trade_rows": 0, "sampled_trades": 0,
                         "invalid_trades": 0, "outside_window": 0, "trades_over_cap": 0, "leads_observed": 0,
                         "leads_deferred": 0, "native_transaction_lookups": 0, "native_account_checks": 0},
              "limitations": ["A bounded current trending-pool sample misses unlisted pools, older activity, and trades outside the latest 300 per pool.",
                              "Provider buy/sell labels and sender addresses are leads; native token movements do not by themselves prove DEX swaps.",
                              "Observed buying and selling determines research priority only; it is not realized profit, ROI, win rate, or a 30-day record.",
                              "Signer and current system-account checks cannot establish a human operator, legitimacy, absence of insider activity, or future safety.",
                              "Copy execution, liquidity, slippage, token risks and independently reviewed historical accounting remain unaudited."]}
    partial = False

    def persist():
        counts = cohort["counts"]
        counts["candidates"] = len(cohort["candidates"])
        for candidate in cohort["candidates"]:
            progress_state = derive_candidate_progress(candidate, cohort)
            candidate.update(states=progress_state["states"], stage=progress_state["stage"])
        for status in ("candidate", "rejected", "unresolved"):
            counts[status] = sum(row["status"] == status for row in cohort["candidates"])
        store.put("discovery_cohorts", cohort["id"], cohort)

    async def notify():
        persist()
        if progress:
            result = progress(deepcopy(cohort))
            if inspect.isawaitable(result):
                await result

    async def pause_check():
        if should_pause:
            result = should_pause()
            if inspect.isawaitable(result):
                result = await result
            if result:
                raise _DiscoveryPaused("Paused by user; archived discovery evidence is retained.")

    def add_evidence(observation):
        item = {"hash": observation["evidence_hash"], "kind": observation["kind"], "observed_at": observation["observed_at"]}
        if observation.get("pool_address"):
            item["pool_address"] = observation["pool_address"]
        if item not in cohort["evidence"]:
            cohort["evidence"].append(item)
        persist()

    def miss(reason, **fields):
        cohort["misses"].append({"reason": reason, **fields})

    def refresh_candidates(leads):
        ordered = sorted(leads.values(), key=lambda row: (-int(bool(row["observed_buys"] and row["observed_sells"])), -len(row["signatures"]), row["address"]))
        cohort["counts"]["leads_observed"] = len(ordered)
        cohort["counts"]["leads_deferred"] = max(0, len(ordered) - candidate_cap)
        cohort["candidates"] = ordered[:candidate_cap]

    async def native(signature):
        cached = store.get("transactions", signature)
        if isinstance(cached, dict) and cached.get("evidence_hash"):
            raw = store.evidence(cached["evidence_hash"])
            body = raw.get("transaction") if isinstance(raw, dict) else None
            signatures = body.get("signatures") if isinstance(body, dict) else None
            if (isinstance(raw, dict) and isinstance(raw.get("meta"), dict) and "err" in raw["meta"] and
                    type(raw.get("slot")) is int and raw["slot"] >= 0 and type(raw.get("blockTime")) is int and raw["blockTime"] >= 0 and
                    isinstance(signatures, list) and signatures and signatures[0] == signature):
                digest = cached["evidence_hash"]
                return raw, digest
        await pause_check()
        _check_disk(store)
        cohort["counts"]["native_transaction_lookups"] += 1
        raw = await gateway.rpc("getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
        _check_disk(store)
        digest = store.archive(raw)
        store.put("transactions", signature, {"signature": signature, "raw": raw, "evidence_hash": digest})
        persist()
        return raw, digest

    try:
        await notify()
        await pause_check()
        async with DiscoveryProvider(store, cap=PUBLIC_DAILY_CAP, transport=transport) as provider:
            observation = await provider.trending_pools()
            add_evidence(observation)
            data = observation["result"].get("data") if isinstance(observation["result"], dict) else None
            if not isinstance(data, list):
                raise ProviderError("Trending pool universe is malformed.", "malformed")
            seen_pools = set()
            for position, row in enumerate(data):
                attributes = row.get("attributes") if isinstance(row, dict) else None
                address = attributes.get("address") if isinstance(attributes, dict) else None
                if not _public_address(address) or address in seen_pools:
                    miss("Universe row has an invalid or repeated pool address.", universe_position=position)
                    continue
                seen_pools.add(address)
                relationships = row.get("relationships") if isinstance(row.get("relationships"), dict) else {}
                def relationship_address(key):
                    relation = relationships.get(key)
                    data = relation.get("data") if isinstance(relation, dict) else None
                    identifier = data.get("id") if isinstance(data, dict) else None
                    mint = identifier[7:] if isinstance(identifier, str) and identifier.startswith("solana_") else None
                    return mint if _public_address(mint) else None
                base_token, quote_token = relationship_address("base_token"), relationship_address("quote_token")
                pool = {"pool_address": address, "name": str(attributes.get("name", ""))[:160], "universe_position": position,
                        "liquidity_usd": _decimal(attributes.get("reserve_in_usd")), "observed_at": observation["observed_at"],
                        "base_token_address": base_token, "quote_token_address": quote_token,
                        "evidence_hash": observation["evidence_hash"], "selected": False, "sample_status": "outside_pool_cap"}
                cohort["universe"].append(pool)
            # Keep the complete returned page and choose SOL quote pools first.
            # The documented fallback keeps older/incomplete provider fixtures usable.
            selection = sorted(cohort["universe"], key=lambda pool: (pool["quote_token_address"] != WRAPPED_SOL, pool["universe_position"]))[:pool_cap]
            for pool in selection:
                pool.update(selected=True, sample_status="pending")
            cohort["sample"]["pool_selection"] = "SOL quote pools first, then provider page order; no liquidity safety threshold inferred"
            cohort["counts"]["pools_observed"] = len(cohort["universe"])
            leads = {}
            for pool in [p for p in cohort["universe"] if p["selected"]]:
                cohort["stage"] = "Sampling recent pool trades"
                await notify()
                await pause_check()
                try:
                    observation = await provider.pool_trades(pool["pool_address"])
                    add_evidence(observation)
                    rows = observation["result"].get("data") if isinstance(observation["result"], dict) else None
                    if not isinstance(rows, list):
                        raise ProviderError("Pool trade sample is malformed.", "malformed")
                except ProviderError as error:
                    if error.code in (429, "backoff"):
                        raise _DiscoveryPaused(str(error)) from None
                    partial = True
                    pool["sample_status"] = "unavailable"
                    miss(str(error), pool_address=pool["pool_address"])
                    continue
                pool.update(sample_status="sampled", trade_evidence_hash=observation["evidence_hash"], trades_observed_at=observation["observed_at"],
                            raw_trade_rows=len(rows), sampled_trade_rows=0)
                cohort["counts"]["pools_sampled"] += 1
                cohort["counts"]["trade_rows"] += len(rows)
                cohort["counts"]["trades_over_cap"] += max(0, len(rows) - SAMPLE_LIMIT)
                seen_signatures = set()
                for row in rows[:SAMPLE_LIMIT]:
                    attributes = row.get("attributes") if isinstance(row, dict) else None
                    if not isinstance(attributes, dict):
                        cohort["counts"]["invalid_trades"] += 1
                        continue
                    address, signature = attributes.get("tx_from_address"), attributes.get("tx_hash")
                    timestamp, kind = _time(attributes.get("block_timestamp")), attributes.get("kind")
                    if not _public_address(address) or not _signature(signature) or timestamp is None or kind not in ("buy", "sell"):
                        cohort["counts"]["invalid_trades"] += 1
                        continue
                    if not start <= timestamp < end:
                        cohort["counts"]["outside_window"] += 1
                        continue
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    pool["sampled_trade_rows"] += 1
                    cohort["counts"]["sampled_trades"] += 1
                    lead = leads.setdefault(address, {"address": address, "source": "pool-trades", "status": "unresolved", "signatures": [],
                                                      "pools": [], "evidence": [], "observed_buys": 0, "observed_sells": 0,
                                                      "sampled_activity": [],
                                                      "reason": "Provider lead awaits native signer, token ownership, historical profit and risk review."})
                    if signature not in lead["signatures"]:
                        lead["signatures"].append(signature)
                        lead["observed_buys" if kind == "buy" else "observed_sells"] += 1
                        lead["sampled_activity"].append({"signature": signature, "kind": kind, "pool_address": pool["pool_address"], "block_time": int(timestamp.timestamp()), "provider_block_number": attributes.get("block_number")})
                    if pool["pool_address"] not in lead["pools"]:
                        lead["pools"].append(pool["pool_address"])
                    digest = observation["evidence_hash"]
                    if digest not in lead["evidence"]:
                        lead["evidence"].append(digest)
                refresh_candidates(leads)
                await notify()
            refresh_candidates(leads)
            if not cohort["universe"]:
                miss("The public provider returned no valid pools; no wallet universe was established.")
                partial = True
            if gateway is not None:
                cohort["stage"] = "Checking sampled native wallet identities"
                await notify()
                checked_accounts = {}
                for candidate in cohort["candidates"][:validate_cap]:
                    await pause_check()
                    signature = candidate["signatures"][0]
                    try:
                        raw, digest = await native(signature)
                        item = {"hash": digest, "kind": "transaction", "signature": signature}
                        if item not in cohort["evidence"]:
                            cohort["evidence"].append(item)
                        if digest not in candidate["evidence"]:
                            candidate["evidence"].append(digest)
                        economic_signers, reason = _native_signers(raw, signature)
                        activity = next((row for row in candidate["sampled_activity"] if row["signature"] == signature), {})
                        sampled_pool = next((pool for pool in cohort["universe"] if pool["pool_address"] == activity.get("pool_address")), {})
                        pool_mints = {mint for mint in (sampled_pool.get("base_token_address"), sampled_pool.get("quote_token_address")) if mint and mint != WRAPPED_SOL}
                        if economic_signers and not pool_mints:
                            economic_signers, reason = {}, "Sampled pool token identities are unavailable; wallet movement cannot be linked to a non-SOL pool asset."
                        elif economic_signers:
                            economic_signers = {address: flows for address, flows in economic_signers.items() if any(flow["mint"] in pool_mints for flow in flows)}
                            if not economic_signers:
                                reason = "No native signer has owned token movements involving the sampled pool assets."
                        if economic_signers and (raw["blockTime"] != activity.get("block_time") or
                                                  (type(activity.get("provider_block_number")) is int and raw["slot"] != activity["provider_block_number"])):
                            economic_signers, reason = {}, "Native transaction time or slot disagrees with the public trade sample."
                        candidate["validation"] = {"identity_verified": False, "signature": signature, "transaction_evidence_hash": digest,
                                                   "economic_signers": list(economic_signers), "scope": "One sampled transaction and current account state; no historical profit verification."}
                        address = candidate["address"]
                        if address not in economic_signers:
                            candidate.update(status="unresolved" if reason else "rejected", reason=reason or "Provider sender is not a native economic signer with owned token movements.")
                            if reason:
                                await notify()
                                continue
                            cohort["rejected_leads"].append({"address": address, "signature": signature, "reason": candidate["reason"], "evidence_hash": digest,
                                                             "observed_buys": candidate["observed_buys"], "observed_sells": candidate["observed_sells"], "signatures": candidate["signatures"]})
                            if len(economic_signers) != 1:
                                await notify()
                                continue
                            resolved = next(iter(economic_signers))
                            if any(row["address"] == resolved for row in cohort["candidates"] if row is not candidate):
                                candidate["validation"]["resolved_wallet"] = resolved
                                await notify()
                                continue
                            candidate.update(address=resolved, status="unresolved", provider_leads=[address], signatures=[signature],
                                             observed_buys=int(activity.get("kind") == "buy"), observed_sells=int(activity.get("kind") == "sell"),
                                             sampled_activity=[activity], pools=[activity["pool_address"]],
                                             reason="Native evidence resolved the economic signer behind a provider lead.")
                            address = resolved
                        candidate["validation"]["token_flows"] = economic_signers[address]
                        if address not in checked_accounts:
                            await pause_check()
                            _check_disk(store)
                            cohort["counts"]["native_account_checks"] += 1
                            account = await gateway.rpc("getAccountInfo", [address, {"encoding": "jsonParsed", "commitment": "finalized", "minContextSlot": raw["slot"]}])
                            _check_disk(store)
                            account_digest = store.archive({"method": "getAccountInfo", "address": address, "result": account})
                            checked_accounts[address] = (account, account_digest)
                            cohort["evidence"].append({"hash": account_digest, "kind": "wallet-account", "address": address})
                            persist()
                        account, account_digest = checked_accounts[address]
                        candidate["validation"]["account_evidence_hash"] = account_digest
                        candidate["evidence"].append(account_digest)
                        value = account.get("value") if isinstance(account, dict) else None
                        context = account.get("context") if isinstance(account, dict) else None
                        if not isinstance(value, dict) or not isinstance(context, dict) or type(context.get("slot")) is not int or context["slot"] < raw["slot"] or type(value.get("executable")) is not bool or not _public_address(value.get("owner")):
                            candidate.update(status="unresolved", reason="Current wallet account identity or finalized context is unavailable.")
                        elif value["executable"] or value["owner"] != SYSTEM_PROGRAM:
                            candidate.update(status="rejected", reason="Native signer is executable or program-owned; it is excluded from wallet research candidates.")
                            candidate["validation"]["account_owner"] = value["owner"]
                        else:
                            candidate.update(status="candidate", reason="Sampled native signer and owned token movements verified; profitability and copy-trading risks still require review.")
                            candidate["validation"].update(identity_verified=True, account_type="system-owned signer", account_owner=value["owner"], account_context_slot=context["slot"])
                    except ProviderError as error:
                        candidate.update(status="unresolved", reason=str(error))
                        partial = True
                        miss(str(error), address=candidate["address"], signature=signature)
                        if error.code in (429, "backoff", "wallet_quota"):
                            raise _DiscoveryPaused(str(error)) from None
                    await notify()
            else:
                cohort["limitations"].append("Native identity validation was not configured; every provider address remains an unresolved lead.")
        cohort.update(status="partial" if partial else "completed", stage="Bounded discovery finished",
                      reason="Dated research leads are ready. Historical profitability and copy-trading risk have not been verified.")
    except (_DiscoveryPaused, QuotaExceeded) as error:
        cohort.update(status="paused", stage="Discovery paused", reason=str(error))
    except asyncio.CancelledError:
        cohort.update(status="paused", stage="Discovery paused", reason="Discovery interrupted; archived observations are retained.")
        persist()
        raise
    except (ProviderError, EvidenceError) as error:
        cohort.update(status="failed", stage="Discovery stopped", reason=str(error))
        miss(str(error))
    except Exception:
        cohort.update(status="failed", stage="Discovery stopped", reason="Discovery stopped after a local storage, configuration, or response error.")
    await notify()
    return cohort


class _DiscoveryPaused(RuntimeError):
    pass
