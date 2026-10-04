"""Discovery boundary checks: public leads do not become profit or safety claims."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from scanner.discovery import DiscoveryProvider, SYSTEM_PROGRAM, WRAPPED_SOL, discover_candidates
from scanner.providers import GeckoTerminal
from scanner.storage import Store


def base58(number, size=32):
    data = number.to_bytes(size, "big")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value, result = int.from_bytes(data, "big"), ""
    while value:
        value, remainder = divmod(value, 58)
        result = alphabet[remainder] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


POOL, POOL2, POOL3, WALLET, ROUTER, MINT, TOKEN_ACCOUNT = [base58(i) for i in range(1, 8)]
SIGNATURE = base58(123, 64)
SIGNATURE2 = base58(124, 64)
STAMP = int((datetime.now(timezone.utc) - timedelta(minutes=2)).timestamp())


def pool(address=POOL, quote=WRAPPED_SOL):
    return {"id": "solana_" + address, "type": "pool", "attributes": {"address": address, "name": "TOKEN / SOL", "reserve_in_usd": "125000.50"},
            "relationships": {"base_token": {"data": {"id": "solana_" + MINT}}, "quote_token": {"data": {"id": "solana_" + quote}}}}


def trade(address=WALLET, signature=SIGNATURE, kind="buy", stamp=STAMP):
    return {"type": "trade", "attributes": {"tx_from_address": address, "tx_hash": signature, "kind": kind,
                                             "block_timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(), "block_number": 10}}


def transaction(address=WALLET, signature=SIGNATURE):
    # Canonical jsonParsed signer/writable/source roles from the pinned native
    # RPC schema; the partial fixture retains no claim of signed provenance.
    return {"slot": 10, "blockTime": STAMP, "version": 0,
            "transaction": {"signatures": [signature], "message": {"accountKeys": [{"pubkey": address, "signer": True, "writable": True, "source": "transaction"}, {"pubkey": TOKEN_ACCOUNT, "signer": False, "writable": True, "source": "transaction"}], "instructions": []}},
            "meta": {"err": None, "preTokenBalances": [{"accountIndex": 1, "mint": MINT, "owner": address, "uiTokenAmount": {"amount": "10", "decimals": 6}}],
                     "postTokenBalances": [{"accountIndex": 1, "mint": MINT, "owner": address, "uiTokenAmount": {"amount": "20", "decimals": 6}}]}}


class FakeGateway:
    def __init__(self, raws=None, account=None):
        self.raws = raws or {SIGNATURE: transaction()}
        self.account = account or {"context": {"slot": 11}, "value": {"owner": SYSTEM_PROGRAM, "executable": False}}
        self.calls = []

    async def rpc(self, method, params):
        self.calls.append((method, params))
        if method == "getTransaction":
            return deepcopy(self.raws.get(params[0]))
        if method == "getAccountInfo":
            return deepcopy(self.account)
        raise AssertionError(method)


async def no_sleep(_):
    return None


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(self.folder.name)
        self.calls = []

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def transport(self, trades=None, pools=None):
        trades = trades if trades is not None else [trade()]
        pools = pools if pools is not None else [pool()]
        def handler(request):
            self.calls.append(request)
            self.assertEqual(request.url.host, "api.geckoterminal.com")
            self.assertEqual(request.method, "GET")
            self.assertNotIn("api-key", str(request.url))
            if request.url.path.endswith("/trending_pools"):
                self.assertEqual(dict(request.url.params), {"page": "1"})
                return httpx.Response(200, json={"data": pools})
            self.assertIn(request.url.path, ["/api/v2/networks/solana/pools/" + item["attributes"]["address"] + "/trades" for item in pools])
            self.assertEqual(dict(request.url.params), {})
            return httpx.Response(200, json={"data": trades})
        return httpx.MockTransport(handler)

    async def discover(self, gateway=None, **options):
        transport = options.pop("transport", self.transport())
        with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
            return await discover_candidates(self.store, gateway, transport=transport, **options)

    async def test_public_discovery_is_usable_without_a_wallet_or_key_and_preserves_evidence(self):
        result = await self.discover()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["pools_sampled"], 1)
        self.assertEqual(result["universe"][0]["liquidity_usd"], "125000.50")
        self.assertEqual(result["candidates"][0]["address"], WALLET)
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.assertEqual(result["candidates"][0]["stage"], "observed")
        self.assertEqual(result["candidates"][0]["states"], {"observed": True, "identity_checked": False,
                                                            "sample_audited": False, "history_reconstructed": False})
        self.assertNotIn("profit", result["candidates"][0])
        self.assertNotIn("score", result["candidates"][0])
        self.assertEqual(self.store.get("discovery_cohorts", result["id"]), result)
        self.assertTrue(all(self.store.evidence(item["hash"])["result"]["data"] for item in result["evidence"]))
        self.assertEqual(self.store.usage("geckoterminal", datetime.now(timezone.utc).date().isoformat(), 200)["used"], 2)

    async def test_actual_provider_shape_is_cached_and_static_routes_share_gate(self):
        first = await self.discover()
        second = await self.discover(transport=httpx.MockTransport(lambda _: self.fail("cache should prevent dispatch")))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(first["evidence"], second["evidence"])
        async with DiscoveryProvider(self.store, transport=self.transport()) as discovery:
            async with GeckoTerminal(self.store, transport=self.transport()) as tokens:
                self.assertIs(discovery._gate, tokens._gate)
                for address in ("../bad?foo=secret", "2" * 32, "https://attacker.example"):
                    with self.assertRaises(ValueError):
                        await discovery.pool_trades(address)
                with self.assertRaises(ValueError):
                    await discovery._observe("arbitrary-url")

    async def test_bound_latest_sample_window_and_candidate_caps_are_explicit(self):
        rows = [trade(signature=base58(i + 1000, 64), address=base58(i + 100)) for i in range(305)]
        rows[0] = trade(stamp=STAMP - 2 * 86400)
        rows[1] = trade(address="2" * 32)
        result = await self.discover(candidate_cap=3, transport=self.transport(trades=rows))
        self.assertEqual(result["counts"]["trade_rows"], 305)
        self.assertEqual(result["counts"]["trades_over_cap"], 5)
        self.assertEqual(result["counts"]["outside_window"], 1)
        self.assertEqual(result["counts"]["invalid_trades"], 1)
        self.assertEqual(result["counts"]["sampled_trades"], 298)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["counts"]["leads_deferred"], 295)

    async def test_prioritizes_observed_two_way_activity_without_inventing_profit(self):
        other = base58(99)
        rows = [trade(address=other), trade(signature=SIGNATURE2), trade(signature=base58(125, 64), kind="sell")]
        result = await self.discover(candidate_cap=1, transport=self.transport(trades=rows))
        self.assertEqual(result["candidates"][0]["address"], WALLET)
        self.assertEqual(result["candidates"][0]["observed_buys"], 1)
        self.assertEqual(result["candidates"][0]["observed_sells"], 1)
        self.assertTrue(any("not realized profit" in note for note in result["limitations"]))

    async def test_sol_quote_preference_retains_full_universe(self):
        result = await self.discover(pool_cap=1, transport=self.transport(pools=[pool(POOL, MINT), pool(POOL2), pool(POOL3)]))
        self.assertEqual(len(result["universe"]), 3)
        self.assertEqual([row["pool_address"] for row in result["universe"] if row["selected"]], [POOL2])
        self.assertEqual(result["counts"]["pools_sampled"], 1)

    async def test_native_signer_and_owned_flow_are_confirmed_without_a_profit_claim(self):
        gateway = FakeGateway()
        result = await self.discover(gateway)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(candidate["validation"]["identity_verified"])
        self.assertEqual(candidate["stage"], "identity_checked")
        self.assertEqual(candidate["states"], {"observed": True, "identity_checked": True,
                                               "sample_audited": False, "history_reconstructed": False})
        self.assertEqual(candidate["validation"]["token_flows"], [{"mint": MINT, "raw_delta": "10", "decimals": 6}])
        self.assertEqual([call[0] for call in gateway.calls], ["getTransaction", "getAccountInfo"])
        self.assertIn("profitability", candidate["reason"])
        self.assertEqual(self.store.evidence(candidate["validation"]["transaction_evidence_hash"]), transaction())

    async def test_provider_router_is_rejected_then_actual_economic_signer_resolved(self):
        result = await self.discover(FakeGateway(), transport=self.transport(trades=[trade(address=ROUTER), trade(address=ROUTER, signature=SIGNATURE2, kind="sell")]))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["address"], WALLET)
        self.assertEqual(candidate["provider_leads"], [ROUTER])
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["signatures"], [SIGNATURE])
        self.assertEqual(candidate["observed_sells"], 0)
        self.assertEqual(result["rejected_leads"][0]["address"], ROUTER)
        self.assertEqual(result["rejected_leads"][0]["observed_sells"], 1)

    async def test_program_owned_or_executable_signer_is_excluded(self):
        for owner, executable in ((MINT, False), (SYSTEM_PROGRAM, True)):
            with self.subTest(owner=owner, executable=executable):
                result = await self.discover(FakeGateway(account={"context": {"slot": 11}, "value": {"owner": owner, "executable": executable}}))
                self.assertEqual(result["candidates"][0]["status"], "rejected")
                self.assertFalse(result["candidates"][0]["validation"]["identity_verified"])

    async def test_absent_metadata_signature_mismatch_owner_change_or_failed_tx_stay_unresolved(self):
        variants = [None]
        for path, value in (("meta", None), ("blockTime", STAMP + 1), ("slot", True), ("version", 1)):
            raw = transaction()
            raw[path] = value
            variants.append(raw)
        raw = transaction()
        raw["transaction"]["signatures"] = [SIGNATURE2]
        variants.append(raw)
        raw = transaction()
        raw["meta"]["postTokenBalances"][0]["owner"] = ROUTER
        variants.append(raw)
        raw = transaction()
        raw["meta"]["err"] = {"InstructionError": [0, "failed"]}
        variants.append(raw)
        raw = transaction()
        raw["meta"].pop("err")
        variants.append(raw)
        raw = transaction()
        raw["transaction"]["message"]["accountKeys"][0].pop("signer")
        variants.append(raw)
        for raw in variants:
            with self.subTest(raw=raw):
                self.store.delete("transactions", SIGNATURE)
                result = await self.discover(FakeGateway(raws={SIGNATURE: raw}))
                candidate = result["candidates"][0]
                self.assertEqual(candidate["status"], "unresolved")
                self.assertFalse(candidate["validation"]["identity_verified"])

    async def test_raw_keys_and_v0_loaded_addresses_identify_signer_but_malformed_header_does_not(self):
        raw = transaction()
        raw["transaction"]["message"].update(
            accountKeys=[WALLET],
            header={"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 0},
            addressTableLookups=[{"accountKey": MINT, "writableIndexes": [0], "readonlyIndexes": []}])
        raw["meta"]["loadedAddresses"] = {"writable": [TOKEN_ACCOUNT], "readonly": []}
        result = await self.discover(FakeGateway(raws={SIGNATURE: raw}))
        self.assertEqual(result["candidates"][0]["status"], "candidate")
        for header, loaded in (([], {}), ({"numRequiredSignatures": 1}, {"writable": "bad"}), ({"numRequiredSignatures": 1}, [])):
            with self.subTest(header=header, loaded=loaded):
                variant = deepcopy(raw)
                variant["transaction"]["message"]["header"] = header
                variant["meta"]["loadedAddresses"] = loaded
                self.store.delete("transactions", SIGNATURE)
                result = await self.discover(FakeGateway(raws={SIGNATURE: variant}))
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["candidates"][0]["status"], "unresolved")

    async def test_stale_current_account_context_is_unresolved_and_request_pins_transaction_slot(self):
        gateway = FakeGateway(account={"context": {"slot": 9}, "value": {"owner": SYSTEM_PROGRAM, "executable": False}})
        result = await self.discover(gateway)
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.assertEqual(gateway.calls[-1][1][1]["minContextSlot"], 10)

    async def test_unrelated_token_movement_in_sampled_transaction_does_not_confirm_pool_participant(self):
        raw = transaction()
        for field in ("preTokenBalances", "postTokenBalances"):
            raw["meta"][field][0]["mint"] = ROUTER
        result = await self.discover(FakeGateway(raws={SIGNATURE: raw}))
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.assertIn("sampled pool assets", result["candidates"][0]["reason"])

    async def test_sol_funding_alone_or_unknown_pool_mints_do_not_link_a_wallet_to_trade(self):
        raw = transaction()
        for field in ("preTokenBalances", "postTokenBalances"):
            raw["meta"][field][0]["mint"] = WRAPPED_SOL
        result = await self.discover(FakeGateway(raws={SIGNATURE: raw}))
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.store.delete("discovery_observations", "trending-pools")
        self.store.delete("transactions", SIGNATURE)
        missing = pool()
        missing.pop("relationships")
        result = await self.discover(FakeGateway(), transport=self.transport(pools=[missing]))
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.assertIn("pool token identities are unavailable", result["candidates"][0]["reason"])

    async def test_native_cache_avoids_lookup_and_evidence_is_raw_collector_compatible(self):
        raw = transaction()
        digest = self.store.archive(raw)
        self.store.put("transactions", SIGNATURE, {"signature": SIGNATURE, "evidence_hash": digest})
        gateway = FakeGateway()
        result = await self.discover(gateway)
        self.assertEqual([call[0] for call in gateway.calls], ["getAccountInfo"])
        self.assertEqual(result["counts"]["native_transaction_lookups"], 0)
        self.assertTrue(result["candidates"][0]["validation"]["identity_verified"])

    async def test_incomplete_cached_transaction_is_refetched_with_old_evidence_retained(self):
        digest = self.store.archive({"meta": {}})
        self.store.put("transactions", SIGNATURE, {"evidence_hash": digest})
        gateway = FakeGateway()
        result = await self.discover(gateway)
        self.assertEqual(result["counts"]["native_transaction_lookups"], 1)
        self.assertEqual(result["candidates"][0]["status"], "candidate")
        self.assertEqual(self.store.evidence(digest), {"meta": {}})

    async def test_eight_native_lookups_bound_even_with_twenty_leads(self):
        rows, raws = [], {}
        for number in range(20):
            address, signature = base58(number + 100), base58(number + 1000, 64)
            rows.append(trade(address=address, signature=signature))
            raws[signature] = transaction(address, signature)
        gateway = FakeGateway(raws=raws)
        result = await self.discover(gateway, transport=self.transport(trades=rows))
        self.assertEqual(result["counts"]["native_transaction_lookups"], 8)
        self.assertEqual(result["counts"]["native_account_checks"], 8)
        self.assertEqual(result["counts"]["candidate"], 8)
        self.assertEqual(result["counts"]["unresolved"], 12)

    async def test_pause_keeps_first_pool_results_and_cannot_mark_discovery_complete(self):
        paused = False
        def progress(cohort):
            nonlocal paused
            if cohort["counts"]["pools_sampled"] == 1:
                paused = True
        result = await self.discover(pool_cap=2, transport=self.transport(pools=[pool(), pool(POOL2)]), progress=progress, should_pause=lambda: paused)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(result["evidence"]), 2)
        self.assertEqual(self.store.get("discovery_cohorts", result["id"]), result)

    async def test_shared_daily_quota_persists_across_store_reopen(self):
        cycle = datetime.now(timezone.utc).date().isoformat()
        reservation = self.store.reserve("geckoterminal", "current-token", 200, cycle, 200)
        self.store.dispatch(reservation)
        self.store.settle(reservation)
        self.store.close()
        self.store = Store(self.folder.name)
        result = await self.discover(transport=httpx.MockTransport(lambda _: self.fail("exhausted quota dispatched")))
        self.assertEqual(result["status"], "paused")
        self.assertEqual(self.store.usage("geckoterminal", cycle, 200)["used"], 200)

    async def test_one_unavailable_pool_gives_partial_cohort_and_archived_other_results(self):
        def handler(request):
            if request.url.path.endswith("trending_pools"):
                return httpx.Response(200, json={"data": [pool(), pool(POOL2)]})
            if POOL2 in request.url.path:
                return httpx.Response(404)
            return httpx.Response(200, json={"data": [trade()]})
        result = await self.discover(pool_cap=2, transport=httpx.MockTransport(handler))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["pools_sampled"], 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["misses"][0]["pool_address"], POOL2)

    async def test_redirect_is_blocked_and_malformed_universe_archived(self):
        result = await self.discover(transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"Location": "https://attacker.example"})))
        self.assertEqual(result["status"], "failed")
        self.assertIn("redirects", result["reason"])
        result = await self.discover(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": None})))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(self.store.evidence(result["evidence"][0]["hash"])["result"], {"data": None})

    async def test_cancellation_charges_dispatched_request_and_persists_paused_cohort(self):
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(discover_candidates(self.store, transport=httpx.MockTransport(handler)))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.store.list("discovery_cohorts")[0]["status"], "paused")
        self.assertEqual(self.store.usage("geckoterminal", datetime.now(timezone.utc).date().isoformat(), 200)["used"], 1)

    async def test_public_retries_each_charge_and_oversized_response_is_rejected(self):
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429) if calls == 1 else httpx.Response(200, json={"data": []})
        result = await self.discover(transport=httpx.MockTransport(handler))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(calls, 2)
        self.store.delete("discovery_observations", "trending-pools")
        result = await self.discover(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 2_000_001)))
        self.assertEqual(result["status"], "failed")
        self.assertIn("response-size", result["reason"])

    async def test_cohort_identifier_override_and_bounds_validate_before_network(self):
        for options in ({"candidate_cap": 21}, {"validate_cap": 9}, {"pool_cap": False}, {"cohort_id": "../path"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                await self.discover(**options)
        identifier = "a" * 32
        result = await self.discover(cohort_id=identifier)
        self.assertEqual(result["id"], identifier)

    async def test_low_disk_reserve_blocks_public_dispatch_and_honors_configured_limit(self):
        self.store.put("configuration", "settings", {"limits": {"min_free_disk_mb": 512}})
        with patch("scanner.discovery.shutil.disk_usage", return_value=SimpleNamespace(free=511 * 1024 ** 2)):
            result = await self.discover(transport=httpx.MockTransport(lambda _: self.fail("low disk dispatched public request")))
        self.assertEqual(result["status"], "paused")
        self.assertIn("512 MB reserve", result["reason"])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(self.store.usage("geckoterminal", datetime.now(timezone.utc).date().isoformat(), 200)["used"], 0)

    async def test_disk_drop_after_first_pool_preserves_candidates_and_pauses_remaining_ingestion(self):
        low = False
        def progress(cohort):
            nonlocal low
            low = low or cohort["counts"]["pools_sampled"] == 1
        with patch("scanner.discovery.shutil.disk_usage", side_effect=lambda _: SimpleNamespace(free=0 if low else 10 * 1024 ** 3)):
            result = await self.discover(pool_cap=2, transport=self.transport(pools=[pool(), pool(POOL2)]), progress=progress)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["counts"]["pools_sampled"], 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(result["evidence"]), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.get("discovery_cohorts", result["id"]), result)

    async def test_disk_drop_before_native_validation_preserves_lead_without_native_dispatch(self):
        low = False
        def progress(cohort):
            nonlocal low
            low = low or cohort["stage"] == "Checking sampled native wallet identities"
        gateway = FakeGateway()
        with patch("scanner.discovery.shutil.disk_usage", side_effect=lambda _: SimpleNamespace(free=0 if low else 10 * 1024 ** 3)):
            result = await self.discover(gateway, progress=progress)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["candidates"][0]["address"], WALLET)
        self.assertEqual(result["candidates"][0]["status"], "unresolved")
        self.assertEqual(gateway.calls, [])

    async def test_disk_drop_after_response_blocks_new_archive_but_dispatched_attempt_is_charged(self):
        low = False
        def handler(request):
            nonlocal low
            if request.url.path.endswith("trending_pools"):
                return httpx.Response(200, json={"data": [pool()]})
            low = True
            return httpx.Response(200, json={"data": [trade()]})
        with patch("scanner.discovery.shutil.disk_usage", side_effect=lambda _: SimpleNamespace(free=0 if low else 10 * 1024 ** 3)):
            result = await self.discover(transport=httpx.MockTransport(handler))
        self.assertEqual(result["status"], "paused")
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(len(self.store.list("artifacts")), 1)
        self.assertEqual(self.store.usage("geckoterminal", datetime.now(timezone.utc).date().isoformat(), 200)["used"], 2)
