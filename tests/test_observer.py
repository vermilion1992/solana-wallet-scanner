"""Forward mechanics; archived mainnet records are not live copying evidence."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import ssl

import httpx
import pytest

from scanner.observer import (ObserverService, PublicRPC, JupiterQuotes, PUBLIC_RPC, PUBLIC_WS,
                              WSOL, StaticWebSocket, _connection_failure)
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


def test_public_rate_limit_preserves_safe_stop_reason_and_original_error_bytes(store):
    raw = b'{"error":"upstream body is evidence, never a UI error message"}'
    async def scenario():
        async with PublicRPC(store, transport=httpx.MockTransport(lambda r: httpx.Response(429, content=raw))) as rpc:
            with pytest.raises(ProviderError, match="rate limit.*HTTP 429") as failure:
                await rpc.rpc("getVersion")
        assert failure.value.code == 429 and "upstream body" not in str(failure.value)
        import base64
        captured = store.evidence(failure.value.evidence_hash)
        assert captured["http_status"] == 429 and captured["response_body_captured"] is True
        assert base64.b64decode(captured["response_bytes"]["base64"]) == raw
        assert json.loads(base64.b64decode(captured["request_bytes"]["base64"]))["method"] == "getVersion"
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


@pytest.mark.parametrize("malformation", ["nan", "overflow", "duplicate"])
def test_malformed_quote_metadata_is_unavailable_and_raw_bytes_survive(store, malformation):
    raw = json.dumps(quote_payload()).encode()
    addition = {"nan": b',"metadata":NaN}', "overflow": b',"metadata":1e999}',
                "duplicate": b',"outAmount":"999999999"}'}[malformation]
    raw = raw[:-1] + addition
    async def scenario():
        client = JupiterQuotes(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw)))
        quote = await client.quote({"input_mint": WSOL, "output_mint": MINT, "input_amount": "10000000"})
        await client.close()
        assert quote["status"] == "unavailable" and quote["reason"] == "malformed_response"
        import base64
        assert base64.b64decode(store.evidence(quote["evidence_hash"])["response_bytes"]["base64"]) == raw
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


@pytest.mark.parametrize("malformation", ["jsonrpc_version", "boolean_subscription", "error_and_result"])
def test_malformed_protocol_notification_retains_rejection_without_blocking_valid_signal(store, malformation):
    identifier, observer = setup_observer(store, quotes=Quotes())
    message = notification("same-signature")
    message["params"]["subscription"] = 1
    if malformation == "jsonrpc_version":
        message["jsonrpc"] = "1.0"
    elif malformation == "boolean_subscription":
        message["params"]["subscription"] = True
    else:
        message["error"] = {"code": -32603, "message": "rejected"}
    async def scenario():
        assert await observer.accept_notification(identifier, message, subscription=1) is None
        rejected = store.list("observer_events")[0]
        assert rejected["status"] == "excluded" and ":rejected:" in rejected["id"]
        assert store.evidence(rejected["notification_hash"])["notification"] == message
        assert observer.snapshot(identifier)["notifications"] == 1
        assert get_run(store, identifier)["gaps"]
        valid = notification("same-signature")
        valid["params"]["subscription"] = 1
        accepted = await observer.accept_notification(identifier, valid, subscription=1)
        assert accepted["status"] == "queued" and accepted["id"] == identifier + ":same-signature"
        assert observer.snapshot(identifier)["notifications"] == 2
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


def test_subscription_ack_cannot_contain_both_success_and_error(store, monkeypatch):
    identifier, observer = setup_observer(store, quotes=Quotes())
    streams = []
    ack = {"jsonrpc": "2.0", "id": 1, "result": 7,
           "error": {"code": -32603, "message": "rejected"}}
    class Socket:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def send(self, payload):
            pass
        async def recv(self):
            return json.dumps(ack)
        async def messages(self):
            streams.append(True)
            yield json.dumps(notification("must-not-be-admitted"))
        def __aiter__(self):
            return self.messages()
    async def no_backoff(seconds):
        pass
    monkeypatch.setattr("scanner.observer.asyncio.sleep", no_backoff)
    observer.websocket_connect = lambda *args, **kwargs: Socket()
    async def scenario():
        await observer._listen(identifier)
        state = observer.snapshot(identifier)
        assert state["status"] == "paused" and state["notifications"] == 0
        assert state.get("connected_at") is None and state.get("subscription") is None
        assert state["last_error"]["code"] == "subscription_rejected"
        assert streams == [] and store.list("observer_events") == []
        import base64
        captured = [store.evidence(a["hash"]) for a in store.list("artifacts")]
        responses = [json.loads(base64.b64decode(a["response_bytes"]["base64"]))
                     for a in captured if a.get("version") == "forward-subscription-capture-v1"]
        assert responses and all(response == ack for response in responses)
        await observer.shutdown()
    run(scenario())


def test_real_websocket_reader_reaches_paper_and_closes_on_stop(store):
    """Real loopback handshake/framing; archived transaction and quotes stay offline."""
    from websockets.asyncio.server import serve
    record = json.loads((FIXTURES / "mainnet-pumpswap-buy-exact-quote.json").read_text())
    requests, gateway_calls = [], []
    filled = asyncio.Event()
    class CapturedQuotes(Quotes):
        async def quote(self, request, settings):
            result = await super().quote(request, settings)
            filled.set()
            return result
    quotes = CapturedQuotes()
    def gateway():
        return Gateway(record["raw"], lambda *call: gateway_calls.append(call))
    paper = create_run(store, WALLET, {"reaction_delay_seconds": 0})
    observer = ObserverService(store, native_factory=gateway, quote_client=quotes)
    async def server(socket):
        requests.append(json.loads(await socket.recv()))
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7}))
        message = json.dumps(notification(record["signature"], slot=record["raw"]["slot"]))
        await socket.send(message)
        await socket.send(message)
        await socket.wait_closed()
    async def scenario():
        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            def local_connector(endpoint, **kwargs):
                assert endpoint == PUBLIC_WS
                # This explicit test adapter never changes a production endpoint.
                return StaticWebSocket(f"ws://127.0.0.1:{port}", proxy=None, **kwargs)
            observer.websocket_connect = local_connector
            try:
                await observer.start(paper["id"])
                await asyncio.wait_for(filled.wait(), timeout=3)
                assert len(get_run(store, paper["id"])["positions"]) == 1
                assert len(gateway_calls) == 1 and len(quotes.requests) == 1
                assert observer.snapshot(paper["id"])["notifications"] == 1
                assert requests[0]["params"][0] == {"mentions": [WALLET]}
                import base64
                subscription = store.evidence(observer.snapshot(paper["id"])["subscription_evidence_hash"])
                assert json.loads(base64.b64decode(subscription["request_bytes"]["base64"])) == requests[0]
                assert json.loads(base64.b64decode(subscription["response_bytes"]["base64"]))["result"] == 7
                assert subscription["request_started_at"] <= subscription["response_received_at"]
                await observer.stop(paper["id"])
                assert get_run(store, paper["id"])["status"] == "paused"
                assert observer.snapshot(paper["id"])["status"] == "stopped"
            finally:
                await observer.shutdown()
    run(scenario())


def test_websocket_redirect_cannot_choose_a_new_notification_source():
    from websockets.asyncio.server import serve
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    received = []
    async def destination(socket):
        received.append(await socket.recv())
    async def scenario():
        async with serve(destination, "127.0.0.1", 0) as target:
            port = target.sockets[0].getsockname()[1]
            def redirect(connection, request):
                return Response(302, "Found", Headers({"Location": f"ws://127.0.0.1:{port}/other"}), b"")
            async with serve(destination, "127.0.0.1", 0, process_request=redirect) as source:
                source_port = source.sockets[0].getsockname()[1]
                with pytest.raises(InvalidStatus) as failure:
                    async with StaticWebSocket(f"ws://127.0.0.1:{source_port}/fixed", proxy=None) as socket:
                        await socket.send("subscription")
                assert _connection_failure(failure.value)["code"] == "redirect_blocked"
                assert received == []
    run(scenario())


def test_connection_diagnostics_do_not_store_exception_text_or_credentials():
    from websockets.exceptions import ProxyError
    errors = [(ssl.SSLCertVerificationError(1, "credential-url-must-not-leak"), "tls_verification_failed"),
              (ProxyError("credential-url-must-not-leak"), "proxy_unavailable"),
              (TimeoutError("credential-url-must-not-leak"), "connection_timeout")]
    for error, expected in errors:
        diagnostic = _connection_failure(error)
        assert diagnostic["code"] == expected and "credential-url-must-not-leak" not in json.dumps(diagnostic)
        assert datetime.fromisoformat(diagnostic["at"]).tzinfo is not None
