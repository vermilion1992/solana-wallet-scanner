"""Native, read-only Helius gateway with conservative durable credit accounting.

This dated manifest is a planning control, not proof of account entitlement.
The caller must obtain and confirm a Free account and run the capability test.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any
from types import MappingProxyType
import weakref
import logging
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass

import httpx

MANIFEST_VERSION = "helius-native-2026-10-02.v1"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
METHOD_COSTS = MappingProxyType({
    "getVersion": 1,
    "getSlot": 1,
    "getBalance": 1,
    "getAccountInfo": 1,
    "getTokenAccountsByOwner": 1,
    "getSignaturesForAddress": 1,
    "getTransaction": 1,
    "getBlock": 1,
})
COST_MANIFEST = MappingProxyType({
    "version": MANIFEST_VERSION,
    "effective_date": "2026-10-02",
    "provider": "helius",
    "network": "mainnet-beta",
    "endpoint": HELIUS_ENDPOINT,
    "methods": METHOD_COSTS,
    "target_requests_per_second": 3,
    "published_free_credits": 1_000_000,
    "source": "https://www.helius.dev/docs/billing/credits",
    "entitlement": "operator-confirmed; authenticated capability test required",
})
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

_RATE_GATES = weakref.WeakKeyDictionary()


def _rate_gate(store, provider):
    gates = _RATE_GATES.setdefault(store, {})
    return gates.setdefault(provider, {"lock": asyncio.Lock(), "next_request": 0.0})


async def _wait_for_rate(gate, interval):
    async with gate["lock"]:
        delay = gate["next_request"] - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        gate["next_request"] = time.monotonic() + interval


def _public_address(address):
    if not isinstance(address, str) or not 32 <= len(address) <= 44:
        return False
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    try:
        for char in address:
            number = number * 58 + alphabet.index(char)
    except ValueError:
        return False
    return len(address) - len(address.lstrip("1")) + (number.bit_length() + 7) // 8 == 32


class _RedactProviderURL(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        cleaned = re.sub(r"([?&]api-key=)[^&\s\"']+", r"\1REDACTED", message, flags=re.IGNORECASE)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


# httpx emits full request URLs at INFO. Remove provider credentials even when an
# operator enables HTTP diagnostics; errors above also omit exception URL text.
logging.getLogger("httpx").addFilter(_RedactProviderURL())


class ProviderError(RuntimeError):
    """Sanitized provider failure; upstream bodies and credential URLs are omitted."""

    def __init__(self, message: str, code: int | str | None = None):
        super().__init__(message)
        self.code = code


class MethodDenied(ProviderError):
    pass


@dataclass(frozen=True)
class CapturedRPC:
    """Successful RPC payload and exact HTTP body bytes, excluding URLs/headers."""

    result: Any
    request_bytes: bytes
    response_bytes: bytes


class Gateway:
    """Only static native read methods; every dispatched attempt is charged.

    Use ``await gateway.close()`` after use. Inject an httpx transport for offline
    tests; callers cannot change the production destination or enable redirects.
    """

    def __init__(self, store, key: str, cycle: str, cap: int = 800_000,
                 rate: int | float = 3, transport=None):
        if not isinstance(key, str) or not key or any(c.isspace() for c in key):
            raise ValueError("A valid provider API key is required.")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise ValueError("Credit cap must be a positive integer.")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= 3:
            raise ValueError("Free Mode permits at most three requests per second.")
        self.store, self.cycle, self.cap = store, cycle, cap
        self._interval = 1 / rate
        self._rate_gate = _rate_gate(store, "helius")
        self._request_id = 0
        self._key = key
        self._client = httpx.AsyncClient(
            base_url=HELIUS_ENDPOINT, transport=transport,
            follow_redirects=False, verify=True, trust_env=True,
            timeout=httpx.Timeout(25, connect=10),
        )
        self.credits = 0
        self.requests = 0
        self.credit_ceiling: int | None = None

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def _throttle(self):
        await _wait_for_rate(self._rate_gate, self._interval)

    @staticmethod
    def _retry_after(value: str | None, attempt: int) -> float:
        delay = min(2 ** attempt, 30)
        if value:
            try:
                delay = max(delay, float(value))
            except ValueError:
                try:
                    date = parsedate_to_datetime(value)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    delay = max(delay, (date - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        return min(max(delay, 0), 300)

    async def rpc(self, method: str, params: list | None = None) -> Any:
        return (await self._rpc(method, params)).result

    async def rpc_capture(self, method: str, params: list | None = None) -> CapturedRPC:
        """Use the same allowlist, accounting and retries while retaining body bytes."""
        return await self._rpc(method, params)

    async def _rpc(self, method: str, params: list | None = None) -> CapturedRPC:
        if method not in METHOD_COSTS:
            raise MethodDenied("Method is outside the pinned native read-only cost manifest.", "method_denied")
        if params is None:
            params = []
        if not isinstance(params, list):
            raise ValueError("RPC parameters must be a list.")
        cost = METHOD_COSTS[method]
        for attempt in range(3):
            if self.credit_ceiling is not None and self.credits + cost > self.credit_ceiling:
                raise ProviderError("Wallet credit limit reached; collection paused.", "wallet_quota")
            reservation = self.store.reserve("helius", method, cost, self.cycle, self.cap)
            dispatched = False
            response = None
            try:
                await self._throttle()
                self._request_id += 1
                request_id = self._request_id
                self.store.dispatch(reservation)
                dispatched = True
                self.credits += cost
                self.requests += 1
                request = self._client.build_request("POST", "/", params={"api-key": self._key},
                    json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
                request_bytes = request.content
                response = await self._client.send(request)
            except httpx.TransportError as exc:
                # In particular, TLS errors are never retried with verification off.
                raise ProviderError("Provider connection failed; dispatched request was charged.", "transport") from None
            finally:
                if dispatched:
                    self.store.settle(reservation, charge=True)
                else:
                    self.store.release(reservation)
            if response.status_code == 429 or response.status_code in (502, 503, 504):
                if attempt < 2:
                    delay = self._retry_after(response.headers.get("Retry-After"), attempt)
                    if delay > 60:
                        raise ProviderError("Provider requested extended rate-limit backoff; resume later.", "backoff")
                    await asyncio.sleep(delay)
                    continue
                raise ProviderError("Provider rate limit or temporary failure persisted; collection paused.", response.status_code)
            if 300 <= response.status_code < 400:
                raise ProviderError("Provider redirects are blocked.", "redirect")
            if response.status_code in (401, 403):
                raise ProviderError("Provider access denied. Recheck Free account access and API key.", response.status_code)
            if response.status_code >= 400:
                raise ProviderError("Provider HTTP request failed.", response.status_code)
            try:
                payload = response.json()
            except ValueError:
                raise ProviderError("Provider returned malformed JSON.", "malformed") from None
            if not isinstance(payload, dict) or payload.get("id") != request_id or payload.get("jsonrpc") != "2.0":
                raise ProviderError("Provider response did not match the request.", "malformed")
            if "error" in payload:
                error = payload["error"]
                code = error.get("code") if isinstance(error, dict) else None
                if code == -32015:
                    message = "Unsupported transaction version; preserve the gap and update the reviewed decoder."
                elif code == -32601:
                    message = "Required native method is unavailable for this provider account."
                else:
                    message = "Provider rejected the native read request."
                # Deliberately never include upstream error messages, which may echo keys.
                raise ProviderError(message, code)
            if "result" not in payload:
                raise ProviderError("Provider response omitted its result.", "malformed")
            return CapturedRPC(payload["result"], request_bytes, response.content)
        raise ProviderError("Provider retry limit reached.")

    async def capability_test(self, address: str | None = None) -> dict:
        started = datetime.now(timezone.utc).isoformat()
        calls = []
        initial_credits = self.credits
        evidence = []
        observations = {}
        try:
            if address is not None and not _public_address(address):
                raise ProviderError("Calibration address must be a 32-byte public Solana address.")
            version = await self.rpc("getVersion")
            if not isinstance(version, dict) or not version.get("solana-core"):
                raise ProviderError("Version capability response was incomplete.")
            calls.append("getVersion")
            slot = await self.rpc("getSlot", [{"commitment": "finalized"}])
            if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
                raise ProviderError("Finalized slot capability response was incomplete.")
            calls.append("getSlot")
            observations = {"version": version, "slot": slot}
            if address:
                programs = {}
                observations["token_accounts"] = programs
                for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
                    accounts = await self.rpc("getTokenAccountsByOwner", [address, {"programId": program}, {"encoding": "jsonParsed", "commitment": "finalized", "minContextSlot": slot}])
                    programs[program] = accounts
                    calls.append("getTokenAccountsByOwner")
                    if not isinstance(accounts, dict) or not isinstance(accounts.get("value"), list):
                        raise ProviderError("Token-account capability response was incomplete.")
                    context = accounts.get("context")
                    if not isinstance(context, dict) or type(context.get("slot")) is not int or context["slot"] < slot:
                        raise ProviderError("Token-account capability response did not meet its finalized anchor.")
                    for item in accounts["value"]:
                        account = item.get("account") if isinstance(item, dict) else None
                        data = account.get("data") if isinstance(account, dict) else None
                        parsed = data.get("parsed") if isinstance(data, dict) else None
                        info = parsed.get("info") if isinstance(parsed, dict) else None
                        if not isinstance(item, dict) or not _public_address(item.get("pubkey")) or not isinstance(info, dict) or info.get("owner") != address:
                            raise ProviderError("Token-account calibration ownership could not be verified.")
                balance = await self.rpc("getBalance", [address, {"commitment": "finalized", "minContextSlot": slot}])
                calls.append("getBalance")
                observations["native_balance"] = balance
                if not isinstance(balance, dict) or type(balance.get("value")) is not int or balance["value"] < 0:
                    raise ProviderError("Native balance capability response was incomplete.")
                context = balance.get("context")
                if not isinstance(context, dict) or type(context.get("slot")) is not int or context["slot"] < slot:
                    raise ProviderError("Native balance capability response did not meet its finalized anchor.")
                signatures = await self.rpc("getSignaturesForAddress", [address, {"limit": 1, "commitment": "finalized", "minContextSlot": slot}])
                calls.append("getSignaturesForAddress")
                observations["signatures"] = signatures
                if not isinstance(signatures, list):
                    raise ProviderError("Signature capability response was incomplete.")
                if not signatures:
                    raise ProviderError("Calibration address has no transaction evidence. Choose an address with an independently verifiable finalized transaction.")
                if signatures:
                    entry = signatures[0]
                    signature = entry.get("signature") if isinstance(entry, dict) else None
                    entry_slot = entry.get("slot") if isinstance(entry, dict) else None
                    entry_time = entry.get("blockTime") if isinstance(entry, dict) else None
                    if not isinstance(signature, str) or not signature or type(entry_slot) is not int or entry_slot < 0 or (entry_time is not None and (type(entry_time) is not int or entry_time < 0)):
                        raise ProviderError("Signature capability response was incomplete.")
                    transaction = await self.rpc("getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
                    calls.append("getTransaction")
                    observations["transaction"] = transaction
                    if not isinstance(transaction, dict) or not isinstance(transaction.get("meta"), dict):
                        raise ProviderError("Transaction capability returned missing metadata.")
                    tx_slot = transaction.get("slot")
                    tx_time = transaction.get("blockTime")
                    tx_version = transaction.get("version", "legacy")
                    if type(tx_slot) is not int or tx_slot < 0 or type(tx_time) is not int or tx_time < 0 or not (tx_version == "legacy" or (type(tx_version) is int and tx_version == 0)):
                        raise ProviderError("Calibration transaction time, slot or version is unsupported.")
                    body = transaction.get("transaction")
                    tx_signatures = body.get("signatures") if isinstance(body, dict) else None
                    if not isinstance(tx_signatures, list) or not tx_signatures or tx_signatures[0] != signature:
                        raise ProviderError("Calibration transaction signature did not match the requested evidence.")
                    if tx_slot != entry_slot or (entry_time is not None and tx_time != entry_time):
                        raise ProviderError("Calibration signature and transaction time or slot disagree.")
                    block = await self.rpc("getBlock", [tx_slot, {"transactionDetails": "signatures", "rewards": False, "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
                    calls.append("getBlock")
                    observations["block"] = block
                    if not isinstance(block, dict) or not isinstance(block.get("signatures"), list) or signature not in block["signatures"]:
                        raise ProviderError("Calibration transaction order could not be verified in its block.")
            digest = self.store.archive({"kind": "capability-test", "at": started, "address": address, "manifest_version": MANIFEST_VERSION, "observations": observations})
            evidence.append({"hash": digest, "kind": "capability-test"})
            return {"status": "passed", "capability_status": "passed", "tested_at": started, "manifest_version": MANIFEST_VERSION, "methods": calls, "credits": self.credits - initial_credits, "snapshot_slot": slot, "wallet_methods_verified": bool(address), "evidence": evidence, "notes": ["This proves tested method access, not provider billing entitlement or complete historical wallet ownership."]}
        except Exception as exc:
            if observations:
                try:
                    digest = self.store.archive({"kind": "capability-test", "at": started, "address": address, "manifest_version": MANIFEST_VERSION, "observations": observations, "status": "failed"})
                    evidence.append({"hash": digest, "kind": "capability-test"})
                except Exception:
                    pass
            message = str(exc) if isinstance(exc, ProviderError) else "Capability test stopped by a local quota, storage or configuration error."
            return {"status": "failed", "capability_status": "failed", "tested_at": started, "manifest_version": MANIFEST_VERSION, "methods": calls, "credits": self.credits - initial_credits, "reason": message, "evidence": evidence}


class GeckoTerminal:
    """Optional manual current token observations; never historical ledger inputs.

    Public calls use the static Solana token route, eight calls per minute and a
    small durable daily request cap. Cached observations are explicitly dated.
    """

    def __init__(self, store, cap=200, transport=None):
        if type(cap) is not int or cap < 1:
            raise ValueError("Public observation cap must be a positive integer.")
        self.store, self.cap = store, cap
        self._gate = _rate_gate(store, "geckoterminal")
        self._client = httpx.AsyncClient(base_url="https://api.geckoterminal.com/api/v2/", transport=transport,
                                        follow_redirects=False, verify=True, trust_env=True,
                                        timeout=httpx.Timeout(25, connect=10),
                                        headers={"Accept": "application/json;version=20230302"})

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def get_token(self, address: str) -> dict:
        if not _public_address(address):
            raise ValueError("Token mint must be a 32-byte base58 public address.")
        cached = self.store.get("market_observations", address)
        if cached:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["observed_at"])).total_seconds()
                if 0 <= age < 900:
                    self.store.evidence(cached["evidence_hash"])
                    return {**cached, "cached": True}
            except (ValueError, KeyError, TypeError):
                pass
        for attempt in range(3):
            cycle = datetime.now(timezone.utc).date().isoformat()
            reservation = self.store.reserve("geckoterminal", "current-token", 1, cycle, self.cap)
            dispatched = False
            try:
                await _wait_for_rate(self._gate, 60 / 8)
                self.store.dispatch(reservation)
                dispatched = True
                response = await self._client.get(f"networks/solana/tokens/{address}")
            except httpx.TransportError:
                raise ProviderError("Public market observation connection failed.", "transport") from None
            finally:
                if dispatched:
                    self.store.settle(reservation, charge=True)
                else:
                    self.store.release(reservation)
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                delay = Gateway._retry_after(response.headers.get("Retry-After"), attempt)
                if delay > 60:
                    raise ProviderError("Public market provider requested extended backoff; resume later.", "backoff")
                await asyncio.sleep(delay)
                continue
            if 300 <= response.status_code < 400:
                raise ProviderError("Market observation redirects are blocked.", "redirect")
            if response.status_code >= 400:
                raise ProviderError("Public market observation unavailable; historical accounting is unchanged.", response.status_code)
            if len(response.content) > 2_000_000:
                raise ProviderError("Public market observation exceeded the local response-size limit.", "malformed")
            try:
                raw = response.json()
                attributes = raw["data"]["attributes"]
            except (ValueError, KeyError, TypeError):
                raise ProviderError("Public market observation was malformed.", "malformed") from None
            if not isinstance(attributes, dict) or attributes.get("address") != address:
                raise ProviderError("Market observation mint identity did not match.", "identity")
            observed = datetime.now(timezone.utc).isoformat()
            digest = self.store.archive({"provider": "geckoterminal", "kind": "current-token", "token_address": address, "observed_at": observed, "result": raw})
            def decimal_text(key):
                value = attributes.get(key)
                if value is None:
                    return None
                if isinstance(value, bool) or not isinstance(value, str) or len(value) > 128:
                    return None
                try:
                    number = Decimal(value)
                    return format(number, "f") if number.is_finite() and number >= 0 and abs(number.adjusted()) <= 100 and abs(number.as_tuple().exponent) <= 100 else None
                except InvalidOperation:
                    return None
            result = {"provider": "geckoterminal", "network": "solana", "token_address": address,
                      "name": attributes.get("name") if isinstance(attributes.get("name"), str) else "",
                      "symbol": attributes.get("symbol") if isinstance(attributes.get("symbol"), str) else "",
                      "price_usd": decimal_text("price_usd"), "fdv_usd": decimal_text("fdv_usd"),
                      "market_cap_usd": decimal_text("market_cap_usd"), "observed_at": observed,
                      "evidence_hash": digest, "cached": False,
                      "notes": ["Current public market observation only; not historical acquisition basis, executable valuation or proof of legitimacy."]}
            self.store.put("market_observations", address, result)
            return result
        raise ProviderError("Public market observation retry limit reached.")
