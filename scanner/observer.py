"""Bounded read-only forward observation and quote-only research adapters.

Notifications establish detection times, not complete beneficial wallet activity.
There is deliberately no signature-history replay: missing monitoring intervals
stay gaps, and interrupted delayed requests are never filled using later prices.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import time

import httpx
from websockets.asyncio.client import connect

from .config import validate_address
from .investigation import WSOL, decode_supported_swaps
from .providers import CapturedRPC, ProviderError, _rate_gate, _wait_for_rate
from .storage import QuotaExceeded, now

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
PUBLIC_WS = "wss://api.mainnet-beta.solana.com"
JUPITER_ORDER = "https://api.jup.ag/swap/v2/order"
OBSERVER_VERSION = "forward-observer-v1"


def _stamp():
    return now()


def _bytes(raw):
    return {"base64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest()}


def _unsigned(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 20:
        raise ValueError("Quote amounts must be bounded integer strings")
    parsed = int(value)
    if not 0 < parsed <= 2**64 - 1:
        raise ValueError("Quote amount is outside positive unsigned 64-bit units")
    return str(parsed)


def _expiry_seconds(value):
    if isinstance(value, str):
        try:
            seconds = float(value)
        except ValueError:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Expiry timestamp lacks timezone")
            return timestamp.timestamp()
    elif type(value) in (int, float):
        seconds = value
    else:
        raise ValueError("Unsupported expiry timestamp format")
    if not 0 < seconds <= 9_999_999_999:
        raise ValueError("Unsupported numeric expiry format")
    return seconds


async def _body(response, limit):
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise ProviderError("Provider response exceeded the bounded capture limit", "oversized")
        chunks.append(chunk)
    return b"".join(chunks)


class PublicRPC:
    """Fixed public native RPC; durable request accounting, no retries or keys.

    The default shared daily application cap does not assert an upstream service
    allowance. ``max_requests`` bounds this particular caller independently.
    """

    METHODS = frozenset({"getAccountInfo", "getSignaturesForAddress", "getTransaction",
                         "getSlot", "getVersion"})

    def __init__(self, store, cycle=None, cap=1000, max_requests=100, transport=None, rate=2):
        if type(cap) is not int or not 1 <= cap <= 100_000:
            raise ValueError("Public request cap must be between 1 and 100000")
        if type(max_requests) is not int or not 1 <= max_requests <= 1000:
            raise ValueError("Caller request limit must be between 1 and 1000")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= 2:
            raise ValueError("Public RPC permits at most two requests per second")
        self.store, self.cap = store, cap
        self.cycle = cycle or datetime.now(timezone.utc).date().isoformat()
        self.max_requests = max_requests
        self.requests = self.credits = 0
        self._pending_requests = 0
        self.credit_ceiling = None
        self._interval = 1 / rate
        self._gate = _rate_gate(store, "solana-public")
        self._client = httpx.AsyncClient(transport=transport, follow_redirects=False,
                                       timeout=httpx.Timeout(20, connect=10), trust_env=True)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def rpc(self, method, params=None):
        return (await self.rpc_capture(method, params)).result

    async def rpc_capture(self, method, params=None):
        if method not in self.METHODS:
            raise ProviderError("Method is outside the public native read allowlist", "method_denied")
        params = [] if params is None else params
        if not isinstance(params, list):
            raise ValueError("RPC parameters must be a list")
        if method == "getSignaturesForAddress":
            if len(params) != 2 or not isinstance(params[1], dict):
                raise ValueError("Public signature requests require an explicit bounded limit")
            limit = params[1].get("limit")
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("Public signature requests permit at most 100 references")
        if self.requests + self._pending_requests >= self.max_requests or (
                self.credit_ceiling is not None and self.credits + self._pending_requests >= self.credit_ceiling):
            raise QuotaExceeded("Public caller request budget exhausted")
        self._pending_requests += 1
        try:
            reservation = self.store.reserve("solana-public", method, 1, self.cycle, self.cap)
        except BaseException:
            self._pending_requests -= 1
            raise
        dispatched = False
        pending = True
        try:
            await _wait_for_rate(self._gate, self._interval)
            self.store.dispatch(reservation)
            dispatched = True
            self._pending_requests -= 1
            pending = False
            self.requests += 1
            self.credits += 1
            request_id = self.requests
            request = self._client.build_request("POST", PUBLIC_RPC, json={
                "jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            async with self._client.stream(request.method, request.url, content=request.content,
                                           headers={"content-type": "application/json"}) as response:
                content = await _body(response, 2_000_000)
                if response.status_code != 200:
                    raise ProviderError("Public RPC request unavailable", response.status_code)
            try:
                payload = json.loads(content)
            except ValueError:
                raise ProviderError("Public RPC response is malformed", "malformed") from None
            if (not isinstance(payload, dict) or payload.get("id") != request_id
                    or payload.get("jsonrpc") != "2.0"):
                raise ProviderError("Public RPC response identity disagrees", "malformed")
            if "error" in payload:
                error = payload["error"]
                raise ProviderError("Public RPC rejected the bounded read",
                                    error.get("code") if isinstance(error, dict) else "rpc_error")
            if "result" not in payload:
                raise ProviderError("Public RPC omitted its result", "malformed")
            return CapturedRPC(payload["result"], request.content, content)
        except httpx.TransportError:
            raise ProviderError("Public RPC connection failed; dispatched attempt was charged", "transport") from None
        finally:
            if pending:
                self._pending_requests -= 1
            if dispatched:
                self.store.settle(reservation, charge=True)
            else:
                self.store.release(reservation)


class JupiterQuotes:
    """Quote-only Swap V2 GET, omitting taker, with shared keyless rate control.

    Expected output already includes venue/provider quote fees. The paper engine
    alone applies its additional modeled costs and adverse output haircut.
    """

    def __init__(self, store, transport=None, interval=2.05):
        self.store = store
        if interval < 2:
            raise ValueError("Keyless Jupiter requests must respect 30 requests/minute")
        self.interval = interval
        self._gate = _rate_gate(store, "jupiter-keyless")
        self._backoff_until = 0.0
        self._client = httpx.AsyncClient(transport=transport, follow_redirects=False,
                                       timeout=httpx.Timeout(15, connect=8), trust_env=True)

    async def close(self):
        await self._client.aclose()

    async def ready(self):
        """Wait before begin_quote so its timestamp is the actual dispatch time."""
        if self._backoff_until > time.time():
            raise ProviderError("Jupiter rate-limit backoff is active", "rate_limit")
        await _wait_for_rate(self._gate, self.interval)

    async def quote(self, request, settings=None):
        params = {"inputMint": validate_address(request["input_mint"]),
                  "outputMint": validate_address(request["output_mint"]),
                  "amount": _unsigned(request["input_amount"])}
        settings = settings or {}
        if settings.get("slippage_bps") is not None:
            value = settings["slippage_bps"]
            if type(value) is not int or not 0 <= value <= 10000:
                raise ValueError("Slippage must be an integer from 0 to 10000 bps")
            params["slippageBps"] = value
        started = _stamp()
        raw, status, payload = b"", None, None
        unavailable = None
        try:
            async with self._client.stream("GET", JUPITER_ORDER, params=params) as response:
                status = response.status_code
                raw = await _body(response, 1_000_000)
                if status == 429:
                    try:
                        reset = float(response.headers.get("x-ratelimit-reset", "0"))
                        self._backoff_until = max(time.time() + 60, min(reset, time.time() + 3600))
                    except ValueError:
                        self._backoff_until = time.time() + 60
                try:
                    payload = json.loads(raw)
                except ValueError:
                    unavailable = "malformed_response"
                if status in (401, 403):
                    unavailable = "access_denied"
                elif status == 429:
                    unavailable = "rate_limit"
                elif status != 200:
                    error = payload.get("errorCode", "") if isinstance(payload, dict) else ""
                    unavailable = "no_route" if error in ("COULD_NOT_FIND_ANY_ROUTE", "NO_ROUTE_FOUND") else "provider_error"
        except (httpx.TransportError, ProviderError):
            unavailable = "transport_or_capture_failure"
        received = _stamp()
        digest = self.store.archive({"version": "jupiter-quote-only-v1", "provider": "Jupiter Swap V2",
            "endpoint": JUPITER_ORDER, "request": params, "request_started_at": started,
            "response_received_at": received, "http_status": status, "response_bytes": _bytes(raw)})
        common = {"provider": "Jupiter Swap V2 (quote only)", "evidence_hash": digest,
                  "request_started_at": started, "received_at": received,
                  "input_mint": params["inputMint"], "output_mint": params["outputMint"]}
        if unavailable:
            return {**common, "status": "unavailable", "reason": unavailable}
        try:
            if (not isinstance(payload, dict) or payload.get("inputMint") != params["inputMint"]
                    or payload.get("outputMint") != params["outputMint"]
                    or payload.get("swapMode") != "ExactIn"
                    or _unsigned(payload.get("inAmount")) != params["amount"]
                    or payload.get("taker") is not None or payload.get("transaction") is not None):
                raise ValueError("Quote-only pair/input/response contract disagrees")
            output = _unsigned(payload.get("outAmount"))
            impact_value = payload.get("priceImpact")
            if impact_value is None:
                impact = Decimal(str(payload["priceImpactPct"])) * 100
            else:
                impact = Decimal(str(impact_value))
            if not impact.is_finite():
                raise ValueError("Quote price impact is unknown")
            quote = {**common, "status": "available", "in_amount": params["amount"],
                     "out_amount": output, "price_impact_pct": str(impact),
                     "quote_fees_included": True,
                     "observed_metadata": {key: payload.get(key) for key in (
                         "feeBps", "feeMint", "platformFee", "signatureFeeLamports",
                         "prioritizationFeeLamports", "rentFeeLamports", "slippageBps",
                         "otherAmountThreshold", "router", "expireAt", "requestId")}}
            expiry = payload.get("expireAt")
            if expiry is not None:
                # The API calls this an RFQ timestamp without pinning one wire
                # format. Admit explicit UTC-aware ISO or bounded numeric seconds;
                # unsupported forms remain unavailable. Missing expiry is unknown.
                expiry_seconds = _expiry_seconds(expiry)
                if expiry_seconds <= datetime.fromisoformat(received).timestamp():
                    return {**common, "status": "unavailable", "reason": "expired_quote"}
            return quote
        except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
            return {**common, "status": "unavailable", "reason": "malformed_quote_contract"}


class ObserverService:
    """Run-local bounded notification reader, durable queue and delayed quote pump."""

    def __init__(self, store, native_factory=None, quote_client=None, websocket_connect=None):
        self.store = store
        self.native_factory = native_factory or (lambda: PublicRPC(store))
        self.quotes = quote_client or JupiterQuotes(store)
        self.websocket_connect = websocket_connect or connect
        self.tasks = {}
        self._locks = {}

    def snapshot(self, run_id):
        return self.store.get("observer_runtime", run_id, {"run_id": run_id, "status": "not_started",
            "scope": "Address mentions only; beneficial-wallet activity completeness is not established"})

    def _update(self, run_id, **values):
        with self.store.lock:
            state = self.snapshot(run_id)
            state.update(values, updated_at=_stamp())
            self.store.put("observer_runtime", run_id, state)
        return state

    def _gap(self, run_id, reason, started=None):
        from .paper import record_gap
        record_gap(self.store, run_id, reason, start_at=started or _stamp(), end_at=_stamp())

    def _close_subscription_gap(self, run_id, reason):
        started = self.snapshot(run_id).get("monitoring_gap_started_at")
        if started:
            self._gap(run_id, reason, started)
            self._update(run_id, monitoring_gap_started_at=None)

    def _interrupt_monitoring(self, run_id, reason):
        from .paper import interrupt_requests
        interrupt_requests(self.store, run_id, reason)
        for event in self.store.list("observer_events"):
            if event.get("run_id") == run_id and event.get("status") in ("queued", "retrieving"):
                event.update(status="missed", reason=reason, updated_at=_stamp())
                self.store.put("observer_events", event["id"], event)

    def recover(self):
        """Expose unobserved downtime and abandon interrupted signals on startup."""
        from .paper import get_run, pause_run
        for state in self.store.list("observer_runtime"):
            if state.get("status") in ("connecting", "listening", "reconnecting"):
                run_id = state["run_id"]
                self._gap(run_id, "Application restarted; missed activity was not replayed",
                          state.get("monitoring_gap_started_at") or state.get("updated_at"))
                if get_run(self.store, run_id)["status"] == "running":
                    pause_run(self.store, run_id, reason="observer_restart")
                self._update(run_id, status="paused", stop_reason="observer_restart", monitoring_gap_started_at=None)
        for event in self.store.list("observer_events"):
            if event.get("status") in ("queued", "retrieving"):
                event.update(status="missed", reason="Restart interrupted detection/retrieval; no hindsight fill",
                             updated_at=_stamp())
                self.store.put("observer_events", event["id"], event)

    async def start(self, run_id, limits=None):
        from .paper import get_run
        run = get_run(self.store, run_id)
        if run["status"] != "running":
            raise ValueError("Resume the paper run before starting observation")
        if run_id in self.tasks and not self.tasks[run_id].done():
            return self.snapshot(run_id)
        if sum(not task.done() for task in self.tasks.values()) >= 5:
            raise ValueError("At most five wallets can be observed concurrently")
        previous = self.snapshot(run_id)
        if previous.get("status") == "budget_exhausted" or previous.get("stop_reason") in (
                "notification_budget", "transaction_budget", "duration_budget"):
            raise ValueError("The immutable observer budget is exhausted; create a new run")
        if previous.get("limits") and (
                previous.get("transactions", 0) >= previous["limits"]["max_transactions"]
                or previous.get("notifications", 0) >= previous["limits"]["max_notifications"]):
            raise ValueError("The immutable observer budget is exhausted; create a new run")
        selected = previous.get("limits") or {"max_transactions": 100, "max_notifications": 1000,
            "max_minutes": run["settings"].get("max_duration_minutes", 60)}
        if limits is not None and previous.get("limits") and limits != previous["limits"]:
            raise ValueError("Existing observation budget cannot be changed; create a new run")
        selected = limits or selected
        ceilings = {"max_transactions": 500, "max_notifications": 5000, "max_minutes": 10080}
        if set(selected) != set(ceilings) or any(type(selected[k]) is not int or not 1 <= selected[k] <= ceilings[k] for k in ceilings):
            raise ValueError("Observer limits are invalid or exceed the bounded maximum")
        state = self._update(run_id, status="connecting", address=run["address"], limits=selected,
            version=OBSERVER_VERSION, started_at=previous.get("started_at") or _stamp(),
            notifications=previous.get("notifications", 0), transactions=previous.get("transactions", 0),
            stop_reason=None, completeness=False,
            monitoring_gap_started_at=_stamp() if previous.get("started_at") else run["started_at"])
        self.tasks[run_id] = asyncio.create_task(self._run(run_id), name="paper-observer-" + run_id)
        return state

    async def stop(self, run_id, reason="operator_stop"):
        task = self.tasks.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._update(run_id, status="stopped", stop_reason=reason, stopped_at=_stamp())

    async def shutdown(self):
        for run_id in list(self.tasks):
            await self.stop(run_id, "application_shutdown")
        await self.quotes.close()

    async def close(self):
        await self.shutdown()

    async def mark(self, run_id):
        from .paper import request_marks, get_run
        request_marks(self.store, run_id)
        await self.process_quotes(run_id)
        return get_run(self.store, run_id)

    async def accept_notification(self, run_id, message, detected_at=None, subscription=None):
        """Persist before RPC dispatch; duplicates retain their original timestamp."""
        if not isinstance(message, dict) or message.get("method") != "logsNotification":
            return None
        params = message.get("params")
        if not isinstance(params, dict) or (subscription is not None and params.get("subscription") != subscription):
            return None
        result = params.get("result")
        value = result.get("value") if isinstance(result, dict) else None
        slot = result.get("context", {}).get("slot") if isinstance(result, dict) and isinstance(result.get("context"), dict) else None
        if not isinstance(value, dict) or not isinstance(value.get("signature"), str) or not 1 <= len(value["signature"]) <= 128:
            self._gap(run_id, "Malformed notification; activity may have been missed")
            return None
        event_id = run_id + ":" + value["signature"]
        with self.store.lock:
            if self.store.get("observer_events", event_id) is not None:
                return self.store.get("observer_events", event_id)
            state = self.snapshot(run_id)
            limits = state["limits"]
            if state["notifications"] >= limits["max_notifications"]:
                self._update(run_id, status="budget_exhausted", stop_reason="notification_budget")
                self._gap(run_id, "Notification budget exhausted; further activity is unobserved")
                return None
            captured = detected_at or _stamp()
            # Reserve the notification/checkpoint before evidence I/O. A crash
            # may consume an unused budget unit, but can never reset this bound.
            self._update(run_id, notifications=state["notifications"] + 1,
                         last_detection_at=captured, last_signature=value["signature"], last_slot=slot)
            digest = self.store.archive({"version": OBSERVER_VERSION, "run_id": run_id,
                "detected_at": captured, "notification": message})
            failed = "err" not in value or value["err"] is not None
            if "err" not in value:
                self._gap(run_id, "Notification omitted execution state; activity may have been missed", captured)
            event = {"id": event_id, "run_id": run_id, "signature": value["signature"],
                     "detected_at": captured, "notification_slot": slot, "notification_hash": digest,
                     "status": "excluded" if failed else "queued", "updated_at": captured,
                     "reason": "Failed or unproved transaction execution in notification" if failed else None}
            self.store.put("observer_events", event_id, event)
        return event

    async def process_event(self, run_id, event):
        from .paper import record_signal
        if event["status"] != "queued":
            return
        with self.store.lock:
            persisted = self.store.get("observer_events", event["id"])
            if persisted is None or persisted.get("status") != "queued":
                return
            state = self.snapshot(run_id)
            if state["transactions"] >= state["limits"]["max_transactions"]:
                event.update(status="missed", reason="Transaction request budget exhausted")
                self.store.put("observer_events", event["id"], event)
                self._update(run_id, status="budget_exhausted", stop_reason="transaction_budget")
                self._gap(run_id, "Transaction request budget exhausted; open exposure remains unresolved")
                return
            event.update(status="retrieving", retrieval_started_at=_stamp())
            self.store.put("observer_events", event["id"], event)
            # Persist the attempt before creating or dispatching a provider request.
            self._update(run_id, transactions=state["transactions"] + 1)
        gateway = self.native_factory()
        try:
            # Existing gateways retry by default: a forward event permits one
            # charged attempt only; unavailable records remain explicit gaps.
            gateway.credit_ceiling = gateway.credits + 1
            captured = await gateway.rpc_capture("getTransaction", [event["signature"], {
                "commitment": "confirmed", "encoding": "json", "maxSupportedTransactionVersion": 0}])
            digest = self.store.archive({"version": "forward-transaction-capture-v1",
                "method": "getTransaction", "signature": event["signature"],
                "request_bytes": _bytes(captured.request_bytes), "response_bytes": _bytes(captured.response_bytes),
                "retrieval_started_at": event["retrieval_started_at"], "retrieved_at": _stamp(),
                "result": captured.result})
            if captured.result is None:
                raise ProviderError("Detected transaction unavailable at requested commitment", "transaction_unavailable")
            if self.store.get("observer_events", event["id"], {}).get("status") != "retrieving":
                raise ProviderError("Monitoring interrupted retrieval; no later replacement fill", "monitoring_interrupted")
            if (type(event.get("notification_slot")) is not int
                    or not isinstance(captured.result, dict)
                    or captured.result.get("slot") != event["notification_slot"]):
                raise ProviderError("Notification and transaction slots disagree or are missing", "slot_disagreement")
            decoded = decode_supported_swaps([{"signature": event["signature"],
                "raw": captured.result, "evidence_hash": digest}], self.snapshot(run_id)["address"])
            stamp = _stamp()
            trades = [row for row in decoded["events"] if row["kind"] in ("buy", "sell")]
            if trades:
                trade = trades[0]
                # A proved swap side/quantity can supply a forward signal even
                # when unrelated leader cash roles prevent historical P&L.
                # This known-cash paper strategy never consumes leader prices.
                eligible = len(trades) == 1 and trade.get("settlement_mint") == WSOL
                reason = None if eligible else "Swap has an ambiguous trade scope or unsupported settlement"
                signal = {"signature": event["signature"], "mint": trade["mint"], "side": trade["kind"],
                    "eligible": eligible and type(trade.get("decimals")) is int and 0 <= trade["decimals"] <= 18,
                    "decimals": trade["decimals"], "raw_quantity": trade["quantity_raw"],
                    "detected_at": event["detected_at"], "decoded_at": stamp, "block_time": trade["timestamp"],
                    "evidence_hash": digest, "reason": reason,
                    "notification_evidence_hash": event["notification_hash"],
                    "leader_cash_role_state": trade.get("native_cash_role_state", "UNKNOWN")}
                record_signal(self.store, run_id, signal)
                event.update(status="decoded", decoded_at=stamp, signal=signal)
            else:
                event.update(status="excluded", decoded_at=stamp,
                    reason="No supported successful SOL/wSOL spot buy or sell", findings=decoded["findings"])
            event["transaction_hash"] = digest
        except asyncio.CancelledError:
            event.update(status="missed", reason="Retrieval interrupted; no hindsight reconstruction")
            raise
        except (ProviderError, QuotaExceeded, ValueError) as error:
            event.update(status="missed", reason=str(error), error_code=getattr(error, "code", None))
            self._gap(run_id, "Detected transaction could not be retrieved/decoded; no hindsight fill", event["detected_at"])
        finally:
            event["updated_at"] = _stamp()
            self.store.put("observer_events", event["id"], event)
            await gateway.close()

    async def process_quotes(self, run_id):
        from .paper import due_quotes, begin_quote, apply_quote, get_run
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            for pending in due_quotes(self.store, run_id):
                if pending["action"] != "mark" and self.snapshot(run_id)["status"] != "listening":
                    continue
                try:
                    await self.quotes.ready()
                except ProviderError:
                    # No dispatch and no quote reservation during active backoff.
                    return
                try:
                    request = begin_quote(self.store, run_id, pending["id"])
                except (ValueError, QuotaExceeded):
                    return
                if request is None:
                    continue
                try:
                    quote = await self.quotes.quote(request, get_run(self.store, run_id)["settings"])
                except asyncio.CancelledError:
                    apply_quote(self.store, run_id, request["id"], {"status": "unavailable",
                        "reason": "Quote request interrupted; no later replacement fill", "received_at": _stamp()})
                    raise
                except (ProviderError, ValueError):
                    quote = {"status": "unavailable", "reason": "Quote adapter unavailable", "received_at": _stamp()}
                apply_quote(self.store, run_id, request["id"], quote)

    async def _listen(self, run_id):
        state = self.snapshot(run_id)
        if not state.get("monitoring_gap_started_at"):
            self._update(run_id, monitoring_gap_started_at=_stamp())
        for attempt in range(4):
            try:
                if attempt:
                    self._update(run_id, status="reconnecting")
                    await asyncio.sleep(min(2**attempt, 4))
                async with self.websocket_connect(PUBLIC_WS, open_timeout=10, close_timeout=3,
                        ping_interval=20, ping_timeout=20, max_size=256_000, max_queue=32) as socket:
                    await socket.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                        "params": [{"mentions": [state["address"]]}, {"commitment": "confirmed"}]}))
                    answer = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
                    subscription = answer.get("result") if isinstance(answer, dict) else None
                    if (not isinstance(answer, dict) or answer.get("id") != 1
                            or type(subscription) is not int or subscription < 0):
                        raise ProviderError("Address subscription was rejected", "subscription_rejected")
                    self._close_subscription_gap(run_id, "Connecting/reconnecting interval; activity was not replayed")
                    self._update(run_id, status="listening", connected_at=_stamp(), subscription=subscription)
                    async for raw in socket:
                        detected = _stamp()
                        try:
                            message = json.loads(raw)
                        except (ValueError, TypeError):
                            self._gap(run_id, "Malformed subscription response; activity may have been missed")
                            continue
                        if isinstance(message, dict) and "error" in message:
                            raise ProviderError("Subscription emitted an error", "subscription_error")
                        await self.accept_notification(run_id, message, detected, subscription)
                        if self.snapshot(run_id)["status"] == "budget_exhausted":
                            return
                    raise ProviderError("Subscription connection ended", "disconnected")
            except asyncio.CancelledError:
                self._close_subscription_gap(run_id, "Connection attempt stopped; activity was not replayed")
                raise
            except Exception:
                # Never store exception text: websocket failures can contain proxy
                # credentials or connection URLs. A gap is evidence, not an error dump.
                existing = self.snapshot(run_id).get("monitoring_gap_started_at")
                self._interrupt_monitoring(run_id, "monitoring_interrupted_no_hindsight_replay")
                self._update(run_id, status="reconnecting", monitoring_gap_started_at=existing or _stamp())
        self._close_subscription_gap(run_id, "Subscription unavailable; all reconnect attempts were unobserved")
        self._update(run_id, status="paused", stop_reason="subscription_unavailable")

    async def _run(self, run_id):
        from .paper import get_run, pause_run
        listener = asyncio.create_task(self._listen(run_id))
        try:
            while get_run(self.store, run_id)["status"] == "running":
                state = self.snapshot(run_id)
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state["started_at"])).total_seconds()
                if elapsed >= state["limits"]["max_minutes"] * 60:
                    state = self._update(run_id, status="budget_exhausted", stop_reason="duration_budget")
                if state["status"] in ("paused", "budget_exhausted") or listener.done():
                    break
                events = [event for event in self.store.list("observer_events")
                          if event["run_id"] == run_id and event["status"] == "queued"]
                for event in sorted(events, key=lambda row: (row["detected_at"], row["id"])):
                    await self.process_event(run_id, event)
                    if self.snapshot(run_id)["status"] == "budget_exhausted":
                        break
                if self.snapshot(run_id)["status"] == "budget_exhausted":
                    break
                await self.process_quotes(run_id)
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            self._interrupt_monitoring(run_id, "observation_stopped_no_hindsight_replay")
            self._gap(run_id, "Observation stopped; future/missed activity is not replayed")
            raise
        except Exception:
            self._gap(run_id, "Observation worker stopped unexpectedly; unresolved exposure remains")
            self._update(run_id, status="paused", stop_reason="worker_failure")
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            self._interrupt_monitoring(run_id, "observer_stopped_no_hindsight_replay")
            if get_run(self.store, run_id)["status"] == "running":
                pause_run(self.store, run_id, reason=self.snapshot(run_id).get("stop_reason") or "observer_stopped")
            final = get_run(self.store, run_id)
            if self.snapshot(run_id)["status"] in ("connecting", "listening", "reconnecting"):
                self._update(run_id, status=final["status"], stop_reason=final.get("stop_reason"))
