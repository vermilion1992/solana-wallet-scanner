from copy import deepcopy
import asyncio
import unittest

from scanner.collector import CollectionPaused, collect_wallet
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from tests.test_providers import MemoryStore

WALLET = "11111111111111111111111111111111"
ACCOUNT = "So11111111111111111111111111111111111111112"
START = 200_000
END = 300_000
LIMITS = {"basis_lookback_days": 1, "transaction_limit": 100, "wallet_credit_limit": 100}


def raw_tx(signature, timestamp, slot, meta=None, instructions=None, keys=None):
    return {"slot": slot, "blockTime": timestamp, "version": "legacy", "transaction": {"signatures": [signature], "message": {"accountKeys": keys or [WALLET], "instructions": instructions or []}}, "meta": meta if meta is not None else {"err": None, "fee": 5000, "preTokenBalances": [], "postTokenBalances": [], "innerInstructions": []}}


def signature(sig, timestamp, slot):
    return {"signature": sig, "blockTime": timestamp, "slot": slot, "err": None}


class FakeGateway:
    def __init__(self, pages=None, transactions=None, accounts=None, block=None):
        self.pages = pages or {}
        self.transactions = transactions or {}
        self.accounts = accounts or {}
        self.block = block
        self.calls = []
        self.credits = 0
        self.credit_ceiling = None

    async def rpc(self, method, params):
        self.calls.append((method, deepcopy(params)))
        self.credits += 1
        if method == "getSlot":
            return 100
        if method == "getBalance":
            return {"context": {"slot": 100}, "value": 1000000}
        if method == "getTokenAccountsByOwner":
            return {"context": {"slot": 100}, "value": self.accounts.get(params[1]["programId"], [])}
        if method == "getSignaturesForAddress":
            return self.pages.get((params[0], params[1].get("before")), [])
        if method == "getTransaction":
            return deepcopy(self.transactions.get(params[0]))
        if method == "getBlock":
            return deepcopy(self.block)
        raise AssertionError(method)


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_half_open_window_backfill_and_scope(self):
        page = [signature("end", END, 10), signature("inside", START + 5, 9), signature("start", START, 8), signature("basis", START - 10, 7), signature("too-old", 100, 6)]
        gateway = FakeGateway({(WALLET, None): page}, {s: raw_tx(s, t, slot) for s, t, slot in (("inside", START + 5, 9), ("start", START, 8), ("basis", START - 10, 7))})
        result = await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
        self.assertEqual([tx["signature"] for tx in result["transactions"]], ["basis", "start", "inside"])
        self.assertEqual([tx["signature"] for tx in result["transactions"] if tx["in_window"]], ["start", "inside"])
        self.assertFalse(result["coverage"]["history_scope_complete"])
        self.assertFalse(result["coverage"]["opening_inventory_assumed_zero"])
        self.assertEqual(result["coverage"]["status"], "partial")
        programs = [params[1]["programId"] for method, params in gateway.calls if method == "getTokenAccountsByOwner"]
        self.assertEqual(programs, [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])

    async def test_repeated_page_pauses_and_archives_before_checkpoint(self):
        page = [signature("one", START + 5, 9)]
        gateway = FakeGateway({(WALLET, None): page, (WALLET, "one"): page}, {"one": raw_tx("one", START + 5, 9)})
        store = MemoryStore()
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
        self.assertIn("repeated", error.exception.reason)
        cp = error.exception.checkpoint
        self.assertEqual(cp["accounts"][WALLET]["cursor"], "one")
        self.assertIn(cp["transactions"]["one"]["evidence_hash"], store.files)
        self.assertEqual(cp["pages"], 1)

    async def test_resume_reuses_archived_transaction_after_mid_page_pause(self):
        page = [signature("one", START + 5, 9), signature("two", START, 8)]
        gateway = FakeGateway({(WALLET, None): page}, {"one": raw_tx("one", START + 5, 9), "two": raw_tx("two", START, 8)})
        store = MemoryStore()
        stopped = False
        def progress(value):
            nonlocal stopped
            if value["transactions"] == 1:
                stopped = True
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, store, WALLET, START, END, LIMITS, progress=progress, should_pause=lambda: stopped)
        cp = error.exception.checkpoint
        self.assertIsNone(cp["accounts"][WALLET]["cursor"])
        result = await collect_wallet(gateway, store, WALLET, START, END, LIMITS, checkpoint=cp)
        requested = [params[0] for method, params in gateway.calls if method == "getTransaction"]
        self.assertEqual(requested.count("one"), 1)
        self.assertEqual(len(result["transactions"]), 2)

    async def test_null_transaction_is_archived_and_paused(self):
        store = MemoryStore()
        gateway = FakeGateway({(WALLET, None): [signature("gone", START, 9)]})
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
        self.assertIn("missing", error.exception.reason)
        self.assertIsNotNone(error.exception.partial)
        digest = error.exception.checkpoint["transactions"]["gone"]["evidence_hash"]
        self.assertIsNone(store.evidence(digest))
        self.assertIsNone(error.exception.checkpoint["accounts"][WALLET]["cursor"])

    async def test_missing_metadata_time_and_unsupported_version_never_complete(self):
        for field, value in (("meta", None), ("blockTime", None), ("version", 2), ("version", False), ("version", 0.0)):
            raw = raw_tx("bad", START, 9)
            raw[field] = value
            gateway = FakeGateway({(WALLET, None): [signature("bad", None if field == "blockTime" else START, 9)]}, {"bad": raw})
            with self.assertRaises(CollectionPaused) as error:
                await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
            self.assertTrue(error.exception.checkpoint["gaps"])
            self.assertEqual(error.exception.checkpoint["pages"], 0)

    async def test_owned_historical_account_discovered_and_closure_not_assumed(self):
        meta = {"err": None, "preTokenBalances": [{"accountIndex": 1, "owner": WALLET}], "postTokenBalances": [], "innerInstructions": []}
        raw = raw_tx("owned", START, 9, meta=meta, keys=[WALLET, ACCOUNT])
        gateway = FakeGateway({(WALLET, None): [signature("owned", START, 9)]}, {"owned": raw})
        result = await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
        accounts = result["coverage"]["account_set"]
        self.assertTrue(any(a["address"] == ACCOUNT and a["evidence"] for a in accounts))
        queried = [p[0] for m, p in gateway.calls if m == "getSignaturesForAddress"]
        self.assertIn(ACCOUNT, queried)
        close = {"programId": TOKEN_PROGRAM, "parsed": {"type": "closeAccount", "info": {"account": ACCOUNT, "owner": WALLET}}}
        gateway = FakeGateway({(WALLET, None): [signature("closed", START, 9)]}, {"closed": raw_tx("closed", START, 9, instructions=[close])})
        result = await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
        self.assertEqual(len(result["coverage"]["account_set"]), 1)

    async def test_same_slot_order_comes_from_block_not_signature(self):
        gateway = FakeGateway({(WALLET, None): [signature("a", START, 9), signature("z", START, 9)]}, {"a": raw_tx("a", START, 9), "z": raw_tx("z", START, 9)}, block={"signatures": ["z", "a"]})
        result = await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
        self.assertEqual([tx["signature"] for tx in result["transactions"]], ["z", "a"])
        self.assertEqual([tx["transaction_index"] for tx in result["transactions"]], [0, 1])

    async def test_budget_boundary_and_bad_checkpoint(self):
        gateway = FakeGateway()
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, MemoryStore(), WALLET, START, END, {**LIMITS, "wallet_credit_limit": 1})
        self.assertEqual(gateway.credits, 1)
        self.assertFalse(error.exception.partial["coverage"]["account_paging_finished"])
        self.assertIsNone(gateway.credit_ceiling)
        with self.assertRaises(ValueError):
            await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS, checkpoint={"version": "wrong"})

    async def test_missing_same_slot_block_pauses(self):
        gateway = FakeGateway({(WALLET, None): [signature("a", START, 9), signature("z", START, 9)]}, {"a": raw_tx("a", START, 9), "z": raw_tx("z", START, 9)})
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, MemoryStore(), WALLET, START, END, LIMITS)
        self.assertIn("Same-slot", error.exception.reason)


class DurableCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovered_null_record_is_refetched_on_resume(self):
        store = MemoryStore()
        gateway = FakeGateway({(WALLET, None): [signature("gone", START, 9)]})
        with self.assertRaises(CollectionPaused) as error:
            await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
        gateway.transactions["gone"] = raw_tx("gone", START, 9)
        result = await collect_wallet(gateway, store, WALLET, START, END, LIMITS, checkpoint=error.exception.checkpoint)
        self.assertEqual(len(result["transactions"]), 1)
        self.assertEqual(result["coverage"]["missing_records"], [])
        self.assertEqual(sum(method == "getTransaction" for method, _ in gateway.calls), 2)
        hashes = [item["hash"] for item in result["evidence"] if item.get("signature") == "gone"]
        self.assertEqual(len(set(hashes)), 2)

    async def test_archive_and_checkpoint_survive_real_store_reopen(self):
        import tempfile
        from scanner.storage import Store
        page = [signature("one", START + 5, 9), signature("two", START, 8)]
        gateway = FakeGateway({(WALLET, None): page}, {"one": raw_tx("one", START + 5, 9), "two": raw_tx("two", START, 8)})
        stopped = False
        def progress(value):
            nonlocal stopped
            stopped = value["transactions"] == 1
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            with self.assertRaises(CollectionPaused) as error:
                await collect_wallet(gateway, store, WALLET, START, END, LIMITS, progress=progress, should_pause=lambda: stopped)
            checkpoint = error.exception.checkpoint
            store.close()
            reopened = Store(folder)
            try:
                result = await collect_wallet(gateway, reopened, WALLET, START, END, LIMITS, checkpoint=checkpoint)
                self.assertEqual(len(result["transactions"]), 2)
                self.assertEqual(sum(method == "getTransaction" and params[0] == "one" for method, params in gateway.calls), 1)
                for record in result["transactions"]:
                    self.assertEqual(reopened.evidence(record["evidence_hash"]), record["raw"])
            finally:
                reopened.close()


class CancellationCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_updates_owning_job_with_dispatched_credit(self):
        entered = asyncio.Event()
        class WaitingGateway(FakeGateway):
            async def rpc(self, method, params):
                if method == "getTransaction":
                    self.credits += 1
                    entered.set()
                    await asyncio.Event().wait()
                return await super().rpc(method, params)
        gateway = WaitingGateway({(WALLET, None): [signature("pending", START, 9)]})
        store = MemoryStore()
        updates = []
        task = asyncio.create_task(collect_wallet(gateway, store, WALLET, START, END, LIMITS, progress=updates.append))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(updates[-1]["credits"], gateway.credits)
        self.assertEqual(updates[-1]["checkpoint"]["credits"], gateway.credits)
        self.assertIsNone(gateway.credit_ceiling)


class GlobalQuotaCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_quota_is_actionable_pause_not_completed_history(self):
        import json
        import tempfile
        import httpx
        from scanner.providers import Gateway
        from scanner.storage import Store
        from unittest.mock import patch
        from tests.test_providers import no_sleep
        def handler(request):
            body = json.loads(request.content)
            results = {"getSlot": 100, "getTokenAccountsByOwner": {"context": {"slot": 100}, "value": []}, "getBalance": {"context": {"slot": 100}, "value": 0}}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": results[body["method"]]})
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                with patch("scanner.providers.asyncio.sleep", side_effect=no_sleep):
                    async with Gateway(store, "secret", "2026-10-01", cap=4, transport=httpx.MockTransport(handler)) as gateway:
                        with self.assertRaises(CollectionPaused) as error:
                            await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
                self.assertIn("credit cap", error.exception.reason)
                self.assertFalse(error.exception.partial["coverage"]["account_paging_finished"])
                self.assertEqual(store.usage("helius", "2026-10-01", 4)["used"], 4)
            finally:
                store.close()


class DiskGuardCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_disk_pauses_before_network_and_preserves_checkpoint(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from scanner.storage import Store
        gateway = FakeGateway()
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                with patch("scanner.collector.shutil.disk_usage", return_value=SimpleNamespace(free=1024)):
                    with self.assertRaises(CollectionPaused) as error:
                        await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
                self.assertEqual(gateway.calls, [])
                self.assertIn("Free disk space", error.exception.reason)
                self.assertEqual(error.exception.checkpoint["credits"], 0)
                self.assertEqual(store.list("collector_checkpoints")[0]["credits"], 0)
                self.assertFalse(error.exception.partial["coverage"]["account_paging_finished"])
            finally:
                store.close()

    async def test_disk_drop_after_dispatch_prevents_unarchived_checkpoint_advance(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from scanner.storage import Store
        disk_is_low = False
        class FillingGateway(FakeGateway):
            async def rpc(self, method, params):
                nonlocal disk_is_low
                result = await super().rpc(method, params)
                if method == "getTransaction":
                    disk_is_low = True
                return result
        gateway = FillingGateway({(WALLET, None): [signature("one", START, 9)]}, {"one": raw_tx("one", START, 9)})
        def usage(_):
            return SimpleNamespace(free=1024 if disk_is_low else 10 * 1024**3)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                with patch("scanner.collector.shutil.disk_usage", side_effect=usage):
                    with self.assertRaises(CollectionPaused) as error:
                        await collect_wallet(gateway, store, WALLET, START, END, LIMITS)
                self.assertIsNone(error.exception.checkpoint["accounts"][WALLET]["cursor"])
                self.assertEqual(error.exception.checkpoint["transactions"], {})
                self.assertGreater(error.exception.checkpoint["credits"], 0)
                self.assertIsNone(store.get("transactions", "one"))
            finally:
                store.close()


def bounded_account(index):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    raw = index.to_bytes(32, "big")
    number, encoded = index, ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + encoded


def owned_account(index):
    return {"pubkey": bounded_account(index), "account": {"data": {"parsed": {"info": {"owner": WALLET, "mint": ACCOUNT}}}}}


class BoundedScopeCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_many_current_accounts_are_archived_but_checkpoint_is_bounded(self):
        import json
        enumeration = [owned_account(index) for index in range(1, 1501)]
        store = MemoryStore()
        gateway = FakeGateway(accounts={TOKEN_PROGRAM: enumeration, TOKEN_2022_PROGRAM: enumeration[:500]})
        result = await collect_wallet(gateway, store, WALLET, START, END, {**LIMITS, "account_limit": 5})
        self.assertEqual(len(result["checkpoint"]["accounts"]), 5)
        self.assertEqual(result["coverage"]["omitted_account_count"], 1496)
        self.assertFalse(result["coverage"]["account_paging_finished"])
        self.assertTrue(result["coverage"]["included_account_paging_finished"])
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertIn("1496", result["coverage"]["scope_limit_reason"])
        self.assertLess(len(json.dumps(result["checkpoint"])), 15000)
        summary = result["snapshot"]["accounts"][TOKEN_PROGRAM]
        self.assertNotIn("value", summary)
        self.assertEqual(len(store.evidence(summary["evidence_hash"])["result"]["value"]), 1500)
        self.assertEqual(sum(method == "getSignaturesForAddress" for method, _ in gateway.calls), 5)
        # Repeated resume reconstructs deduplication from the archive, not an
        # ever-growing omitted-address list or another ownership API request.
        resumed_gateway = FakeGateway()
        resumed = await collect_wallet(resumed_gateway, store, WALLET, START, END, {**LIMITS, "account_limit": 5}, checkpoint=result["checkpoint"])
        self.assertEqual(resumed["coverage"]["omitted_account_count"], 1496)
        self.assertEqual(resumed_gateway.calls, [])

    async def test_historical_discovery_respects_same_account_limit(self):
        discovered = [bounded_account(index) for index in range(1, 51)]
        meta = {"err": None, "preTokenBalances": [{"accountIndex": index, "owner": WALLET} for index in range(1, 51)], "postTokenBalances": [], "innerInstructions": []}
        gateway = FakeGateway({(WALLET, None): [signature("one", START + 5, 9), signature("two", START, 8)]},
                              {"one": raw_tx("one", START + 5, 9, meta=meta, keys=[WALLET] + discovered), "two": raw_tx("two", START, 8, meta=meta, keys=[WALLET] + discovered)})
        store = MemoryStore()
        result = await collect_wallet(gateway, store, WALLET, START, END, {**LIMITS, "account_limit": 2})
        self.assertEqual(len(result["checkpoint"]["accounts"]), 2)
        self.assertEqual(result["coverage"]["omitted_account_count"], 49)
        self.assertFalse(result["coverage"]["history_scope_complete"])
        self.assertEqual(sum(method == "getSignaturesForAddress" and params[0] != WALLET for method, params in gateway.calls), 1)
        resumed = await collect_wallet(FakeGateway(), store, WALLET, START, END, {**LIMITS, "account_limit": 2}, checkpoint=result["checkpoint"])
        self.assertEqual(resumed["coverage"]["omitted_account_count"], 49)

    async def test_legacy_checkpoint_migrates_before_copy_and_keeps_included_cursors(self):
        import json
        enumeration = [owned_account(index) for index in range(1, 21)]
        store = MemoryStore()
        original = await collect_wallet(FakeGateway(accounts={TOKEN_PROGRAM: enumeration}), store, WALLET, START, END, {**LIMITS, "account_limit": 30})
        checkpoint = original["checkpoint"]
        checkpoint["snapshot"]["accounts"][TOKEN_PROGRAM] = {"context": {"slot": 100}, "value": enumeration}
        checkpoint.pop("account_scope")
        kept = bounded_account(1)
        checkpoint["accounts"][kept]["cursor"] = "durable-cursor"
        checkpoint["accounts"][kept]["terminal"] = None
        checkpoint["accounts"][kept]["page_hashes"] = []
        result = await collect_wallet(FakeGateway(), store, WALLET, START, END, {**LIMITS, "account_limit": 3}, checkpoint=checkpoint)
        self.assertEqual(list(result["checkpoint"]["accounts"]), [WALLET, bounded_account(1), bounded_account(2)])
        self.assertEqual(result["checkpoint"]["accounts"][kept]["cursor"], "durable-cursor")
        self.assertEqual(result["coverage"]["omitted_account_count"], 18)
        self.assertNotIn("value", result["snapshot"]["accounts"][TOKEN_PROGRAM])
        self.assertLess(len(json.dumps(result["checkpoint"])), 10000)
        raw_hash = result["snapshot"]["accounts"][TOKEN_PROGRAM]["evidence_hash"]
        self.assertEqual(len(store.evidence(raw_hash)["result"]["value"]), 20)
        self.assertFalse(result["coverage"]["account_paging_finished"])
