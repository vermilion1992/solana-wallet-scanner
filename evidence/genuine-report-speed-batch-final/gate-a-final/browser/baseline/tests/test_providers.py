import asyncio
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

import httpx

from scanner.providers import Gateway, METHOD_COSTS, MethodDenied, ProviderError


CALIBRATION_ADDRESS = "11111111111111111111111111111111"
CALIBRATION_SIGNATURE = "1" * 64


def calibration_results():
    return {
        "getVersion": {"solana-core": "2.0"}, "getSlot": 100,
        "getTokenAccountsByOwner": {"context": {"slot": 100}, "value": []},
        "getBalance": {"context": {"slot": 100}, "value": 1000},
        "getSignaturesForAddress": [{"signature": CALIBRATION_SIGNATURE, "slot": 99, "blockTime": 1000}],
        "getTransaction": {"meta": {}, "slot": 99, "blockTime": 1000, "version": 0,
                           "transaction": {"signatures": [CALIBRATION_SIGNATURE], "message": {"accountKeys": [], "instructions": []}}},
        "getBlock": {"signatures": [CALIBRATION_SIGNATURE]},
    }


class MemoryStore:
    def __init__(self, cap=800000):
        self.records = {}
        self.files = {}
        self.reservations = {}
        self.used = 0

    def get(self, kind, identifier, default=None):
        return self.records.get((kind, identifier), default)

    def put(self, kind, identifier, payload):
        self.records[(kind, identifier)] = json.loads(json.dumps(payload))

    def archive(self, payload):
        encoded = json.dumps(payload, sort_keys=True).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        self.files[digest] = json.loads(encoded)
        return digest

    def evidence(self, digest):
        return self.files[digest]

    def reserve(self, provider, method, cost, cycle, cap):
        outstanding = sum(r["cost"] for r in self.reservations.values() if r["state"] in ("reserved", "dispatched"))
        if self.used + outstanding + cost > cap:
            raise RuntimeError("quota")
        identifier = str(len(self.reservations))
        self.reservations[identifier] = {"cost": cost, "state": "reserved"}
        return identifier

    def dispatch(self, identifier):
        self.reservations[identifier]["state"] = "dispatched"

    def settle(self, identifier, charge=True):
        row = self.reservations[identifier]
        row["state"] = "settled"
        if charge:
            self.used += row["cost"]

    def release(self, identifier):
        self.reservations[identifier]["state"] = "released"


async def no_sleep(_):
    return None


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_and_transactional_methods_never_dispatch(self):
        store = MemoryStore()
        async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(lambda _: self.fail("network"))) as gateway:
            for method in ("sendTransaction", "simulateTransaction", "getTransactionsForAddress", "getTransfersByAddress", "requestAirdrop", "unknown"):
                with self.assertRaises(MethodDenied):
                    await gateway.rpc(method)
        self.assertEqual(store.reservations, {})

    async def test_rate_limit_retry_reserves_and_charges_each_attempt(self):
        store = MemoryStore()
        seen = []
        def handler(request):
            seen.append(request)
            self.assertEqual(request.url.host, "mainnet.helius-rpc.com")
            self.assertEqual(request.url.path, "/")
            self.assertTrue(any(row["state"] == "dispatched" for row in store.reservations.values()))
            if len(seen) == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
            body = json.loads(request.content)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": 123})
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep) as sleep:
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                self.assertEqual(await gateway.rpc("getSlot"), 123)
            self.assertTrue(any(call.args == (7.0,) for call in sleep.call_args_list))
        self.assertEqual(store.used, 2)
        self.assertEqual(len(store.reservations), 2)

    async def test_dispatched_timeout_charged_and_key_sanitized(self):
        store = MemoryStore()
        def handler(request):
            raise httpx.ReadTimeout("secret-key " + str(request.url), request=request)
        async with Gateway(store, "secret-key", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
            with self.assertRaises(ProviderError) as error:
                await gateway.rpc("getSlot")
            self.assertNotIn("secret-key", str(error.exception))
            self.assertNotIn("api-key", str(error.exception))
        self.assertEqual(store.used, 1)

    async def test_redirect_and_upstream_key_echo_do_not_escape(self):
        for status, payload in ((302, None), (200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "leaked-secret"}})):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, headers={"Location": "https://attacker.example"}, json=payload)
            async with Gateway(MemoryStore(), "leaked-secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                with self.assertRaises(ProviderError) as error:
                    await gateway.rpc("getSlot")
                self.assertNotIn("leaked-secret", str(error.exception))
                self.assertEqual(len(calls), 1)

    async def test_capability_reports_observed_methods_and_archived_evidence(self):
        store = MemoryStore()
        def handler(request):
            body = json.loads(request.content)
            result = {"solana-core": "2.0.0"} if body["method"] == "getVersion" else 123
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                result = await gateway.capability_test()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["credits"], 2)
        self.assertEqual(result["methods"], ["getVersion", "getSlot"])
        self.assertFalse(result["wallet_methods_verified"])
        self.assertIn("not provider billing entitlement", result["notes"][0])
        self.assertIn(result["evidence"][0]["hash"], store.files)
        self.assertNotIn("secret", json.dumps(store.records))

    async def test_wallet_credit_ceiling_includes_retries(self):
        store = MemoryStore()
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(lambda _: httpx.Response(429))) as gateway:
                gateway.credit_ceiling = 1
                with self.assertRaises(ProviderError) as error:
                    await gateway.rpc("getSlot")
        self.assertEqual(error.exception.code, "wallet_quota")
        self.assertEqual(store.used, 1)

    async def test_global_quota_blocks_dispatch(self):
        store = MemoryStore()
        store.used = 1
        async with Gateway(store, "secret", "2026-10-01", cap=1, transport=httpx.MockTransport(lambda _: self.fail("network"))) as gateway:
            with self.assertRaises(RuntimeError):
                await gateway.rpc("getSlot")
        self.assertEqual(store.reservations, {})

    async def test_malformed_id_and_unknown_cost_are_denied(self):
        async with Gateway(MemoryStore(), "secret", "2026-10-01", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"jsonrpc": "2.0", "id": "wrong", "result": 1}))) as gateway:
            with self.assertRaises(ProviderError):
                await gateway.rpc("getSlot")
        with self.assertRaises(ValueError):
            Gateway(MemoryStore(), "secret", "2026-10-01", rate=4)


class AdditionalGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_calibration_does_not_pass_transaction_access(self):
        store = MemoryStore()
        def handler(request):
            body = json.loads(request.content)
            method = body["method"]
            results = {"getVersion": {"solana-core": "2.0"}, "getSlot": 100,
                       "getTokenAccountsByOwner": {"context": {"slot": 100}, "value": []},
                       "getBalance": {"context": {"slot": 100}, "value": 1000},
                       "getSignaturesForAddress": []}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": results[method]})
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                result = await gateway.capability_test("11111111111111111111111111111111")
        self.assertEqual(result["status"], "failed")
        self.assertIn("no transaction", result["reason"])
        self.assertTrue(result["evidence"])

    async def test_calibration_covers_native_balance_transaction_and_block(self):
        results = calibration_results()
        seen = []
        def handler(request):
            body = json.loads(request.content)
            seen.append(body)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": results[body["method"]]})
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            async with Gateway(MemoryStore(), "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                result = await gateway.capability_test(CALIBRATION_ADDRESS)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["wallet_methods_verified"])
        self.assertEqual(result["credits"], 8)
        self.assertIn("getTransaction", result["methods"])
        self.assertIn("getBlock", result["methods"])
        self.assertEqual(result["methods"].count("getTokenAccountsByOwner"), 2)
        self.assertEqual(result["methods"].count("getBlock"), 1)
        block_request = next(body for body in seen if body["method"] == "getBlock")
        self.assertEqual(block_request["params"][0], 99)
        self.assertEqual(block_request["params"][1]["transactionDetails"], "signatures")
        self.assertEqual(block_request["params"][1]["maxSupportedTransactionVersion"], 0)

    async def test_calibration_rejects_unanchored_token_and_balance_snapshots(self):
        for method in ("getTokenAccountsByOwner", "getBalance"):
            for context in ({"slot": 99}, {"slot": True}, {}, None):
                with self.subTest(method=method, context=context):
                    results = calibration_results()
                    results[method]["context"] = context
                    result, store, seen = await self.calibrate_mock(results)
                    self.assertEqual(result["status"], "failed")
                    self.assertIn("finalized anchor", result["reason"])
                    self.assertNotIn("getTransaction", seen)
                    self.assertTrue(result["evidence"])
                    archived = store.files[result["evidence"][0]["hash"]]
                    self.assertEqual(archived["status"], "failed")

    async def test_calibration_rejects_unverified_token_account_ownership(self):
        valid_item = {"pubkey": "So11111111111111111111111111111111111111112",
                      "account": {"data": {"parsed": {"info": {"owner": CALIBRATION_ADDRESS}}}}}
        wrong_owner = deepcopy(valid_item)
        wrong_owner["account"]["data"]["parsed"]["info"]["owner"] = "So11111111111111111111111111111111111111112"
        invalid_pubkey = deepcopy(valid_item)
        invalid_pubkey["pubkey"] = "2" * 32  # Base58 text of the right length, but fewer than 32 decoded bytes.
        for item in (wrong_owner, invalid_pubkey, {"pubkey": valid_item["pubkey"], "account": {"data": ["unparsed", "base64"]}}, None):
            with self.subTest(item=item):
                results = calibration_results()
                results["getTokenAccountsByOwner"]["value"] = [item]
                result, _, seen = await self.calibrate_mock(results)
                self.assertEqual(result["status"], "failed")
                self.assertIn("ownership", result["reason"])
                self.assertNotIn("getTransaction", seen)
        results = calibration_results()
        results["getTokenAccountsByOwner"]["value"] = [valid_item]
        result, _, _ = await self.calibrate_mock(results)
        self.assertEqual(result["status"], "passed")

    async def test_calibration_rejects_transaction_identity_and_metadata_mismatches(self):
        for field, value, reason in (
            ("meta", [], "metadata"),
            ("transaction", {"signatures": ["different"]}, "signature did not match"),
            ("transaction", {"signatures": []}, "signature did not match"),
            ("slot", 98, "time or slot disagree"),
            ("blockTime", 1001, "time or slot disagree"),
            ("slot", True, "unsupported"),
            ("blockTime", -1, "unsupported"),
        ):
            with self.subTest(field=field, value=value):
                results = calibration_results()
                results["getTransaction"][field] = value
                result, store, seen = await self.calibrate_mock(results)
                self.assertEqual(result["status"], "failed")
                self.assertIn(reason, result["reason"])
                self.assertNotIn("getBlock", seen)
                archived = store.files[result["evidence"][0]["hash"]]
                self.assertEqual(archived["observations"]["transaction"][field], value)

    async def test_calibration_requires_block_signature_list_and_preserves_null_page_time(self):
        results = calibration_results()
        results["getBlock"]["signatures"] = CALIBRATION_SIGNATURE
        result, _, seen = await self.calibrate_mock(results)
        self.assertEqual(result["status"], "failed")
        self.assertIn("order", result["reason"])
        self.assertEqual(seen.count("getBlock"), 1)
        self.assertEqual(result["credits"], 8)
        results = calibration_results()
        results["getSignaturesForAddress"][0]["blockTime"] = None
        result, _, _ = await self.calibrate_mock(results)
        self.assertEqual(result["status"], "passed")

    async def calibrate_mock(self, results):
        store = MemoryStore()
        seen = []
        def handler(request):
            body = json.loads(request.content)
            seen.append(body["method"])
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": results[body["method"]]})
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                result = await gateway.capability_test(CALIBRATION_ADDRESS)
        return result, store, seen

    async def test_http_diagnostics_redact_api_key(self):
        import logging
        def handler(request):
            body = json.loads(request.content)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": 100})
        with self.assertLogs("httpx", level=logging.INFO) as logs:
            async with Gateway(MemoryStore(), "sensitive-secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                await gateway.rpc("getSlot")
        self.assertNotIn("sensitive-secret", " ".join(logs.output))
        self.assertIn("REDACTED", " ".join(logs.output))

    async def test_methods_and_cost_manifest_cannot_be_mutated(self):
        from scanner.providers import COST_MANIFEST
        with self.assertRaises(TypeError):
            METHOD_COSTS["sendTransaction"] = 1
        with self.assertRaises(TypeError):
            COST_MANIFEST["endpoint"] = "http://attacker.example/"


class GeckoTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_route_decimal_observation_archived_and_cached(self):
        from scanner.providers import GeckoTerminal
        address = "So11111111111111111111111111111111111111112"
        store = MemoryStore()
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.host, "api.geckoterminal.com")
            self.assertEqual(request.url.path, "/api/v2/networks/solana/tokens/" + address)
            return httpx.Response(200, json={"data": {"attributes": {"address": address, "name": "<script>untrusted</script>", "symbol": "SOL", "price_usd": "1.23", "fdv_usd": "1e9999999", "market_cap_usd": "NaN"}}})
        async with GeckoTerminal(store, transport=httpx.MockTransport(handler)) as provider:
            first = await provider.get_token(address)
            second = await provider.get_token(address)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["price_usd"], "1.23")
        self.assertIsNone(first["fdv_usd"])
        self.assertIsNone(first["market_cap_usd"])
        self.assertTrue(second["cached"])
        self.assertIn(first["evidence_hash"], store.files)
        self.assertEqual(store.used, 1)
        self.assertIn("not historical", first["notes"][0])

    async def test_redirect_and_address_injection_blocked(self):
        from scanner.providers import GeckoTerminal
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": "https://attacker.example"})
        async with GeckoTerminal(MemoryStore(), transport=httpx.MockTransport(handler)) as provider:
            with self.assertRaises(ValueError):
                await provider.get_token("../wallet?api-key=secret")
            with self.assertRaises(ProviderError):
                await provider.get_token("So11111111111111111111111111111111111111112")
        self.assertEqual(len(calls), 1)


class DurableGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatched_timeout_usage_survives_real_store_reopen(self):
        import tempfile
        from scanner.storage import Store
        def handler(request):
            raise httpx.ReadTimeout("secret", request=request)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
                with self.assertRaises(ProviderError):
                    await gateway.rpc("getSlot")
            store.close()
            reopened = Store(folder)
            try:
                self.assertEqual(reopened.usage("helius", "2026-10-01", 10)["used"], 1)
                self.assertEqual(reopened.usage("helius", "2026-10-01", 10)["remaining"], 9)
            finally:
                reopened.close()


class CancellationGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_after_dispatch_stays_charged(self):
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            await asyncio.Event().wait()
        store = MemoryStore()
        async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(handler)) as gateway:
            task = asyncio.create_task(gateway.rpc("getSlot"))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(store.used, 1)
        self.assertEqual(store.reservations["0"]["state"], "settled")

    async def test_cancel_before_dispatch_releases_reservation(self):
        waiting = asyncio.Event()
        async def throttle():
            waiting.set()
            await asyncio.Event().wait()
        store = MemoryStore()
        async with Gateway(store, "secret", "2026-10-01", transport=httpx.MockTransport(lambda _: self.fail("network"))) as gateway:
            gateway._throttle = throttle
            task = asyncio.create_task(gateway.rpc("getSlot"))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(store.used, 0)
        self.assertEqual(store.reservations["0"]["state"], "released")
