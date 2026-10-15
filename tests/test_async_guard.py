import asyncio
from contextlib import closing
import contextvars
from functools import partial
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("AGENT_RECEIPT_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(ROOT / "src"))

from agent_receipt import Guard, Observation, Request, RequestConflict


class AsyncGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.guard = Guard(self.path)
        self.req = Request(scope="demo", key="workflow:step", tool="write:v1", arguments={"n": 1})

    async def no_dispatch(self, req):
        self.fail("Unexpected dispatch or verifier call")

    async def test_replay_across_sync_async_and_restart(self):
        async def call(req):
            return {"id": 7}
        first = await self.guard.aexecute(self.req, call)
        self.assertEqual(first.state, "returned")
        self.assertFalse(first.replayed)
        restarted = Guard(self.path)
        replay = restarted.execute(self.req, lambda r: self.fail("sync redispatch"))
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, {"id": 7})
        self.assertEqual((await restarted.aexecute(self.req, self.no_dispatch)).result, {"id": 7})

    async def test_callback_uses_callers_loop_and_context(self):
        loop = asyncio.get_running_loop()
        tenant = contextvars.ContextVar("tenant")
        tenant.set("tenant-a")
        async def call(req):
            self.assertIs(asyncio.get_running_loop(), loop)
            return tenant.get()
        self.assertEqual((await self.guard.aexecute(self.req, call)).result, "tenant-a")

    async def test_timeout_after_effect_and_authoritative_verification(self):
        effects = {}
        async def call(req):
            effects[req.token] = {"id": 9}
            raise TimeoutError("private-error-sentinel")
        first = await self.guard.aexecute(self.req, call)
        self.assertEqual(first.state, "unknown")
        self.assertFalse(first.replayed)
        self.assertEqual((await self.guard.aexecute(self.req, self.no_dispatch)).state, "unknown")
        async def verify(req):
            return Observation(True, effects[req.token], "ledger:9")
        resolved = await self.guard.areconcile(self.req, verify)
        self.assertEqual(resolved.state, "verified")
        self.assertEqual(resolved.result, {"id": 9})
        await self.guard.areconcile(self.req, self.no_dispatch)
        self.assertEqual(len(effects), 1)
        self.assertNotIn(b"private-error-sentinel", self.path.read_bytes())

    async def test_cancellation_before_and_after_effect_preserves_unknown(self):
        for apply in (False, True):
            req = Request(scope="demo", key=str(apply), tool="write:v1", arguments={})
            entered = asyncio.Event()
            effects = []
            async def call(req):
                if apply:
                    effects.append(req.token)
                entered.set()
                await asyncio.Event().wait()
            job = asyncio.create_task(self.guard.aexecute(req, call))
            try:
                await asyncio.wait_for(entered.wait(), 5)
            finally:
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
            self.assertEqual((await self.guard.aget(req)).state, "unknown")
            await self.guard.aexecute(req, self.no_dispatch)
            self.assertEqual(len(effects), int(apply))

    async def test_outer_timeout_does_not_authorize_retry(self):
        timeout = asyncio.timeout(None)
        async def call(req):
            timeout.reschedule(asyncio.get_running_loop().time() - 1)
            await asyncio.Event().wait()
        with self.assertRaises(TimeoutError):
            async with timeout:
                await self.guard.aexecute(self.req, call)
        self.assertEqual((await self.guard.aexecute(self.req, self.no_dispatch)).state, "unknown")

    async def test_cancelled_reservation_worker_can_still_commit_without_dispatch(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        reserve = self.guard._reserve
        def delayed_reserve(req):
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError("test barrier")
                return reserve(req)
            finally:
                finished.set()
        with patch.object(self.guard, "_reserve", delayed_reserve):
            job = asyncio.create_task(self.guard.aexecute(self.req, self.no_dispatch))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
        self.assertEqual((await self.guard.aget(self.req)).state, "unknown")
        await self.guard.aexecute(self.req, self.no_dispatch)

    async def test_cancelled_result_worker_may_finish_but_never_redispatches(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        finish = self.guard._finish
        def delayed_finish(*args, **kwargs):
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError("test barrier")
                return finish(*args, **kwargs)
            finally:
                finished.set()
        async def call(req):
            return {"id": 1}
        with patch.object(self.guard, "_finish", delayed_finish):
            job = asyncio.create_task(self.guard.aexecute(self.req, call))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
        replay = await self.guard.aexecute(self.req, self.no_dispatch)
        self.assertEqual(replay.state, "returned")
        self.assertTrue(replay.replayed)

    async def test_parallel_sync_and_async_callers_dispatch_once(self):
        effects = []
        def sync_call(req):
            effects.append(req.token)
            return 1
        async def async_call(req):
            effects.append(req.token)
            await asyncio.sleep(0)
            return 1
        results = await asyncio.gather(
            asyncio.to_thread(self.guard.execute, self.req, sync_call),
            *(self.guard.aexecute(self.req, async_call) for _ in range(12)),
        )
        self.assertEqual(len(effects), 1)
        self.assertEqual(sum(not r.replayed for r in results), 1)
        self.assertEqual((await self.guard.aget(self.req)).state, "returned")

    async def test_sqlite_lock_does_not_block_event_loop(self):
        connected = threading.Event()
        connect = sqlite3.connect
        def observed_connect(*args, **kwargs):
            connected.set()
            return connect(*args, **kwargs)
        with closing(connect(self.path, isolation_level=None)) as locker:
            locker.execute("BEGIN IMMEDIATE")
            with patch("agent_receipt.guard.sqlite3.connect", observed_connect):
                job = asyncio.create_task(self.guard.aget(self.req))
                try:
                    self.assertTrue(await asyncio.to_thread(connected.wait, 5))
                    # This coroutine must resume while the SQLite operation waits.
                    self.assertFalse(job.done())
                finally:
                    locker.rollback()
                    self.assertIsNone(await job)

    async def test_verification_wins_over_late_async_return(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(req):
            entered.set()
            await release.wait()
            return "late response"
        async def verify(req):
            return Observation(True, "observed", "ledger:1")
        job = asyncio.create_task(self.guard.aexecute(self.req, call))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await self.guard.areconcile(self.req, verify)
        finally:
            release.set()
            result = await job
        self.assertEqual(result.state, "verified")
        self.assertEqual(result.result, "observed")

    async def test_empty_lookup_reloads_late_completion_and_never_releases(self):
        async def fail(req):
            raise TimeoutError()
        await self.guard.aexecute(self.req, fail)
        async def empty(req):
            return Observation()
        self.assertEqual((await self.guard.areconcile(self.req, empty)).state, "unknown")
        await self.guard.aexecute(self.req, self.no_dispatch)
        async def concurrent_verify(req):
            await asyncio.to_thread(self.guard.reconcile, req,
                                    lambda r: Observation(True, 7, "ledger:7"))
            return Observation()
        self.assertEqual((await self.guard.areconcile(self.req, concurrent_verify)).state, "verified")

    async def test_bad_callback_rejected_before_reservation(self):
        for bad in (None, lambda r: 1):
            with self.assertRaises(TypeError):
                await self.guard.aexecute(self.req, bad)
        self.assertIsNone(await self.guard.aget(self.req))

    async def test_async_callable_and_partial_supported(self):
        class Adapter:
            async def __call__(self, req):
                return req.arguments
        self.assertEqual((await self.guard.aexecute(self.req, Adapter())).result, {"n": 1})
        async def verify(req, *, evidence):
            return Observation(True, 1, evidence)
        self.assertEqual((await self.guard.areconcile(self.req, partial(verify, evidence="ledger:1"))).state,
                         "verified")

    async def test_invalid_result_and_verifier_keep_reservation(self):
        async def bad_result(req):
            return object()
        self.assertEqual((await self.guard.aexecute(self.req, bad_result)).state, "unknown")
        for value in ({"applied": True}, Observation(True, object(), "ledger:1")):
            async def invalid(req):
                return value
            with self.assertRaises(TypeError):
                await self.guard.areconcile(self.req, invalid)
        async def failed_lookup(req):
            raise ConnectionError()
        with self.assertRaises(ConnectionError):
            await self.guard.areconcile(self.req, failed_lookup)
        self.assertEqual((await self.guard.aget(self.req)).state, "unknown")

    async def test_cancelled_verifier_does_not_change_receipt(self):
        self.guard.execute(self.req, lambda r: "returned")
        async def verify(req):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.guard.areconcile(self.req, verify)
        self.assertEqual((await self.guard.aget(self.req)).state, "returned")

    async def test_missing_reservation_and_input_conflicts(self):
        with self.assertRaises(KeyError):
            await self.guard.areconcile(self.req, self.no_dispatch)
        self.guard.execute(self.req, lambda r: None)
        changed = Request(scope="demo", key="workflow:step", tool="write:v1", arguments={"n": 2})
        for operation in (self.guard.aexecute, self.guard.areconcile):
            with self.assertRaises(RequestConflict):
                await operation(changed, self.no_dispatch)

    async def test_database_failure_prevents_async_dispatch(self):
        self.path.write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            await self.guard.aexecute(self.req, self.no_dispatch)


if __name__ == "__main__":
    unittest.main()
