"""Forward mechanics; archived mainnet records are not live copying evidence."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
import pytest

from scanner.observer import ObserverService, PublicRPC, JupiterQuotes, PUBLIC_RPC, PUBLIC_WS, WSOL
from scanner.paper import create_run, get_run, record_signal, pause_run
from scanner.providers import CapturedRPC, ProviderError
from scanner.storage import Store, QuotaExceeded, now

FIXTURES = Path(__file__).parent / "fixtures"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ"


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.close()


def run(coroutine):
    return asyncio.run(coroutine)


def setup_observer(store, *, settings=None, limits=None, native_factory=None, quotes=None):
    paper = create_run(store, WALLET, {"reaction_delay_seconds": 0, **(settings or {})})
    observer = ObserverService(store, native_factory=native_factory, quote_client=quotes)
    observer._update(paper["id"], status="listening", address=WALLET, notifications=0,
        transactions=0, started_at=paper["started_at"],
        limits=limits or {"max_transactions": 10, "max_notifications": 10, "max_minutes": 60})
    return paper["id"], observer


def notification(signature="signature", *, slot=100, err=None):
    return {"jsonrpc": "2.0", "method": "logsNotification", "params": {"subscription": 7,
        "result": {"context": {"slot": slot}, "value": {"signature": signature, "err": err, "logs": []}}}}


class Gateway:
    def __init__(self, result, callback=None):
        self.result, self.callback = result, callback
        self.credits = 0
        self.closed = False

    async def rpc_capture(self, method, params):
        if self.callback:
            self.callback(method, params)
        self.credits += 1
        return CapturedRPC(self.result, json.dumps({"method": method, "params": params}).encode(),
                           json.dumps({"jsonrpc": "2.0", "id": 1, "result": self.result}).encode())

    async def close(self):
        self.closed = True


class Quotes:
    def __init__(self, available=True):
        self.requests = []
        self.available = available

    async def ready(self):
        pass

    async def quote(self, request, settings):
        self.requests.append(deepcopy(request))
        if not self.available:
            return {"status": "unavailable", "reason": "no_route", "received_at": now()}
        return {"status": "available", "in_amount": request["input_amount"], "out_amount": "1000",
            "input_mint": request["input_mint"], "output_mint": request["output_mint"],
            "price_impact_pct": "0.1", "received_at": now()}

    async def close(self):
        pass


def test_public_rpc_fixed_read_only_dispatch_budget(store):
    sent = []

    def response(request):
        sent.append(request)
        payload = json.loads(request.content)
        usage = store.usage("solana-public", "test", 1)
        assert usage["used"] == 1 and usage["reserved"] == 0
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": 42})

    async def scenario():
        async with PublicRPC(store, cycle="test", cap=1, max_requests=1,
                             transport=httpx.MockTransport(response)) as rpc:
            with pytest.raises(ProviderError):
                await rpc.rpc("sendTransaction", ["unsigned"])
            with pytest.raises(ValueError):
                await rpc.rpc("getSignaturesForAddress", [WALLET, {"limit": 101}])
            capture = await rpc.rpc_capture("getSlot")
            assert capture.result == 42
            assert json.loads(capture.request_bytes)["method"] == "getSlot"
            with pytest.raises(QuotaExceeded):
                await rpc.rpc("getSlot")
        assert str(sent[0].url) == PUBLIC_RPC and len(sent) == 1
        assert store.usage("solana-public", "test", 1)["remaining"] == 0

    run(scenario())


def test_public_rpc_redirect_is_not_followed_and_failure_is_charged(store):
    async def scenario():
        async with PublicRPC(store, cap=1, transport=httpx.MockTransport(
                lambda r: httpx.Response(307, headers={"location": "http://127.0.0.1/private"}))) as rpc:
            with pytest.raises(ProviderError):
                await rpc.rpc("getVersion")
        assert store.usage("solana-public", datetime.now(timezone.utc).date().isoformat(), 1)["used"] == 1
    run(scenario())


def quote_payload():
    # Primary API fields, specified independently of the adapter; transaction:null
    # is the valid no-taker path, not proof of a fill or zero execution costs.
    return {"inputMint": WSOL, "outputMint": MINT, "inAmount": "10000000", "outAmount": "1219412",
        "swapMode": "ExactIn", "transaction": None, "taker": None,
        "priceImpact": -0.022674100336355564, "priceImpactPct": "-0.00022674100336355564",
        "feeBps": 2, "platformFee": {"feeBps": 2, "feeMint": WSOL}, "signatureFeeLamports": 0}


def test_quote_only_contract_preserves_expected_output_fees_and_raw_bytes(store):
    seen = []
    payload = quote_payload()
    raw = json.dumps(payload).encode()
    def response(request):
        seen.append(request)
        return httpx.Response(200, content=raw)
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(response))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        await client.close()
        assert quote["status"] == "available" and quote["out_amount"] == "1219412"
        assert quote["price_impact_pct"] == "-0.022674100336355564"
        assert quote["quote_fees_included"] is True
        assert quote["observed_metadata"]["platformFee"]["feeBps"] == 2
        assert "taker" not in seen[0].url.params and seen[0].method == "GET"
        assert seen[0].url.host == "api.jup.ag"
        import base64
        capture = store.evidence(quote["evidence_hash"])
        assert base64.b64decode(capture["response_bytes"]["base64"]) == raw
        assert capture["request_started_at"] <= capture["response_received_at"]
    run(scenario())


@pytest.mark.parametrize("status,reason", [(401, "access_denied"), (429, "rate_limit"),
    (400, "provider_error"), (503, "provider_error")])
def test_quote_unavailability_does_not_imply_token_fraud(store, status, reason):
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "upstream"})))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        assert quote["status"] == "unavailable" and quote["reason"] == reason
        if status == 429:
            with pytest.raises(ProviderError):
                await client.ready()
        await client.close()
    run(scenario())


def test_deprecated_price_impact_ratio_converts_to_percent_points(store):
    payload = quote_payload()
    payload.pop("priceImpact")
    payload["priceImpactPct"] = "0.005"
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        await client.close()
        assert quote["price_impact_pct"] == "0.500"
        with pytest.raises(ValueError):
            JupiterQuotes(store, interval=1)
    run(scenario())


def test_quote_pair_and_signed_transaction_contract_must_match(store):
    payload = quote_payload()
    payload["transaction"] = "should-never-be-built"
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        await client.close()
        assert quote["status"] == "unavailable" and quote["reason"] == "malformed_quote_contract"
    run(scenario())


@pytest.mark.parametrize("expired", [False, True])
def test_quote_expiry_accepts_aware_iso_and_rejects_elapsed_quote(store, expired):
    payload = quote_payload()
    payload["expireAt"] = (datetime.now(timezone.utc) + timedelta(seconds=-30 if expired else 30)).isoformat()
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        await client.close()
        assert quote["status"] == ("unavailable" if expired else "available")
        if expired:
            assert quote["reason"] == "expired_quote"
    run(scenario())


def test_duplicate_notification_preserves_original_detection_and_budget(store):
    identifier, observer = setup_observer(store)
    async def scenario():
        first = await observer.accept_notification(identifier, notification(), subscription=7)
        duplicate = await observer.accept_notification(identifier, notification(), subscription=7)
        assert duplicate == first and observer.snapshot(identifier)["notifications"] == 1
        assert await observer.accept_notification(identifier, notification("wrong-source"), subscription=8) is None
        failed = await observer.accept_notification(identifier, notification("failed", err={"InstructionError": [0, "failure"]}))
        assert failed["status"] == "excluded"
        missing_execution = notification("unproved")
        del missing_execution["params"]["result"]["value"]["err"]
        await observer.accept_notification(identifier, missing_execution)
        assert get_run(store, identifier)["gaps"][-1]["reason"].startswith("Notification omitted execution state")
        await observer.shutdown()
    run(scenario())


def test_archived_genuine_supported_buy_supplies_signal_without_leader_price(store):
    record = json.loads((FIXTURES / "mainnet-pumpswap-buy-exact-quote.json").read_text())
    observed = []
    def factory():
        return Gateway(record["raw"], lambda method, params: observed.append((method, params,
            store.get("observer_runtime", identifier)["transactions"])))
    quotes = Quotes()
    identifier, observer = setup_observer(store, native_factory=factory, quotes=quotes)
    async def scenario():
        event = await observer.accept_notification(identifier, notification(record["signature"], slot=record["raw"]["slot"]))
        await observer.process_event(identifier, event)
        await observer.process_quotes(identifier)
        saved = get_run(store, identifier)
        assert saved["signals"][0]["side"] == "buy" and saved["signals"][0]["eligible"] is True
        assert "leader_price" not in saved["signals"][0]
        assert len(saved["positions"]) == 1 and saved["positions"][0]["raw_units"] == "990"
        assert observed[0][2] == 1
        assert observed[0][1][1] == {"commitment": "confirmed", "encoding": "json", "maxSupportedTransactionVersion": 0}
        assert quotes.requests[0]["request_started_at"] >= saved["signals"][0]["decoded_at"]
        await observer.shutdown()
    run(scenario())


def test_transaction_unavailable_leaves_gap_without_fill(store):
    identifier, observer = setup_observer(store, native_factory=lambda: Gateway(None), quotes=Quotes())
    async def scenario():
        event = await observer.accept_notification(identifier, notification())
        await observer.process_event(identifier, event)
        saved = get_run(store, identifier)
        assert saved["gaps"] and not saved["positions"] and not saved["signals"]
        assert store.get("observer_events", event["id"])["status"] == "missed"
        await observer.shutdown()
    run(scenario())


def test_transaction_budget_is_durable_before_fetch_and_never_extended(store):
    calls = []
    identifier, observer = setup_observer(store, native_factory=lambda: Gateway(None, lambda *p: calls.append(p)),
        limits={"max_transactions": 1, "max_notifications": 5, "max_minutes": 60}, quotes=Quotes())
    async def scenario():
        for signature in ("first", "second"):
            event = await observer.accept_notification(identifier, notification(signature))
            await observer.process_event(identifier, event)
        assert len(calls) == 1 and observer.snapshot(identifier)["transactions"] == 1
        assert observer.snapshot(identifier)["stop_reason"] == "transaction_budget"
        await observer.stop(identifier)
        with pytest.raises(ValueError, match="budget is exhausted"):
            await observer.start(identifier)
        await observer.shutdown()
    run(scenario())


def test_restart_pauses_and_marks_queued_events_missed_without_backfill(store):
    identifier, observer = setup_observer(store, quotes=Quotes())
    async def scenario():
        event = await observer.accept_notification(identifier, notification())
        record_signal(store, identifier, {"signature": "pending", "mint": MINT, "side": "buy", "eligible": True,
            "decimals": 6, "detected_at": now(), "decoded_at": now()}, at=now())
        recovered = ObserverService(store, quote_client=Quotes())
        recovered.recover()
        assert recovered.snapshot(identifier)["status"] == "paused"
        saved = get_run(store, identifier)
        assert saved["status"] == "paused" and saved["gaps"][-1]["backfilled"] is False
        assert store.get("observer_events", event["id"])["status"] == "missed"
        await recovered.process_quotes(identifier)
        assert recovered.quotes.requests == [] and not saved["positions"]
        await observer.shutdown()
        await recovered.shutdown()
    run(scenario())


def test_monitoring_loss_interrupts_pending_signal_quote_without_later_fill(store):
    quotes = Quotes()
    identifier, observer = setup_observer(store, quotes=quotes)
    async def scenario():
        queued = await observer.accept_notification(identifier, notification("queued"))
        record_signal(store, identifier, {"signature": "decoded", "mint": MINT, "side": "buy", "eligible": True,
            "decimals": 6, "detected_at": now(), "decoded_at": now()})
        observer._interrupt_monitoring(identifier, "monitoring_interrupted_no_hindsight_replay")
        observer._update(identifier, status="reconnecting")
        await observer.process_quotes(identifier)
        observer._update(identifier, status="listening")
        await observer.process_quotes(identifier)
        saved = get_run(store, identifier)
        assert not quotes.requests and not saved["positions"]
        assert saved["quote_requests"][0]["status"] == "interrupted"
        assert store.get("observer_events", queued["id"])["status"] == "missed"
        await observer.shutdown()
    run(scenario())


def test_subscription_mentions_exactly_one_address_and_stops_at_notification_budget(store):
    sent, connected = [], []
    identifier, observer = setup_observer(store, quotes=Quotes(),
        limits={"max_transactions": 1, "max_notifications": 1, "max_minutes": 60})
    class Socket:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def send(self, payload):
            sent.append(json.loads(payload))
        async def recv(self):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7})
        async def messages(self):
            yield json.dumps(notification("first"))
            yield json.dumps(notification("exhausted"))
        def __aiter__(self):
            return self.messages()
    def connect(endpoint, **kwargs):
        connected.append((endpoint, kwargs))
        return Socket()
    observer.websocket_connect = connect
    async def scenario():
        await observer._listen(identifier)
        assert sent[0]["method"] == "logsSubscribe" and sent[0]["params"][0] == {"mentions": [WALLET]}
        assert connected[0][0] == PUBLIC_WS
        assert connected[0][1]["max_size"] == 256000
        assert observer.snapshot(identifier)["status"] == "budget_exhausted"
        assert len([e for e in store.list("observer_events") if e["run_id"] == identifier]) == 1
        await observer.shutdown()
    run(scenario())
