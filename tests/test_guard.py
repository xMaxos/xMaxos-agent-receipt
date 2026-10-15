import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("AGENT_RECEIPT_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(ROOT / "src"))

import agent_receipt
from agent_receipt import Guard, Observation, Request, RequestConflict


def request(**overrides):
    values = dict(scope="tenant-a:service-a", key="workflow-17:step-2",
                  tool="create_record:v1", arguments={"value": "example"})
    values.update(overrides)
    return Request(**values)


def process_racer(path, barrier, output):
    guard = Guard(path)
    barrier.wait(timeout=20)
    def call(req):
        output.put("dispatch")
        return {"id": 1}
    output.put(guard.execute(request(), call).state)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.guard = Guard(self.path)
        self.req = request()

    def test_completed_response_replayed_after_restart(self):
        result = self.guard.execute(self.req, lambda r: {"id": 42})
        self.assertEqual(result.state, "returned")
        self.assertFalse(result.replayed)
        second = Guard(self.path).execute(self.req, lambda r: self.fail("re-dispatched"))
        self.assertTrue(second.replayed)
        self.assertEqual(second.result, {"id": 42})

    def test_timeout_after_effect_is_not_retried(self):
        effects = []
        def call(req):
            effects.append(req.token)
            raise TimeoutError("secret should not be stored")
        self.assertEqual(self.guard.execute(self.req, call).state, "unknown")
        self.assertEqual(self.guard.execute(self.req, call).state, "unknown")
        self.assertEqual(len(effects), 1)
        self.assertNotIn(b"secret", self.path.read_bytes())

    def test_unknown_can_be_verified_without_dispatch(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        receipt = self.guard.reconcile(self.req, lambda r: Observation(
            applied=True, result={"id": 7}, evidence="ledger:7"))
        self.assertEqual(receipt.state, "verified")
        self.assertEqual(receipt.evidence, "ledger:7")
        self.assertEqual(self.guard.execute(self.req, lambda r: self.fail()).result, {"id": 7})

    def test_inconclusive_observation_never_releases_reservation(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        for _ in range(3):
            receipt = self.guard.reconcile(self.req, lambda r: Observation())
            self.assertEqual(receipt.state, "unknown")
            self.assertFalse(receipt.to_dict()["may_dispatch_again"])
        self.guard.execute(self.req, lambda r: self.fail("empty read caused retry"))

    def test_inflight_call_is_not_reissued_after_empty_lookup(self):
        entered, release = threading.Event(), threading.Event()
        effects = []
        def slow_call(req):
            entered.set()
            if not release.wait(10):
                raise TimeoutError()
            effects.append(1)
            return "done"
        with ThreadPoolExecutor(1) as executor:
            job = executor.submit(self.guard.execute, self.req, slow_call)
            try:
                self.assertTrue(entered.wait(5))
                receipt = self.guard.reconcile(self.req, lambda r: Observation())
                self.assertEqual(receipt.state, "unknown")
                self.guard.execute(self.req, lambda r: self.fail("inflight duplicate"))
            finally:
                release.set()
            self.assertEqual(job.result(10).state, "returned")
        self.assertEqual(effects, [1])

    def test_conflicting_arguments_and_tools_are_rejected(self):
        self.guard.execute(self.req, lambda r: "ok")
        for different in (request(arguments={"value": "changed"}), request(tool="delete:v1")):
            with self.subTest(tool=different.tool, args=different.arguments):
                with self.assertRaises(RequestConflict):
                    self.guard.execute(different, lambda r: self.fail())
                with self.assertRaises(RequestConflict):
                    self.guard.reconcile(different, lambda r: self.fail())

    def test_dict_order_does_not_change_identity(self):
        first = request(arguments={"a": 1, "b": {"d": 2, "c": 3}})
        second = request(arguments={"b": {"c": 3, "d": 2}, "a": 1})
        self.guard.execute(first, lambda r: "ok")
        self.assertTrue(self.guard.execute(second, lambda r: self.fail()).replayed)

    def test_int_float_bool_are_distinct(self):
        values = [request(arguments={"n": x}).fingerprint for x in [1, 1.0, True]]
        self.assertEqual(len(set(values)), 3)

    def test_inputs_are_snapshotted_before_dispatch(self):
        args = {"nested": [1]}
        req = request(arguments=args)
        args["nested"].append(2)
        req.arguments["nested"].append(3)
        self.assertEqual(self.guard.execute(req, lambda r: r.arguments).result, {"nested": [1]})

    def test_replayed_result_mutation_does_not_change_journal(self):
        receipt = self.guard.execute(self.req, lambda r: {"items": [1]})
        receipt.result["items"].append(2)
        self.assertEqual(self.guard.get(self.req).result, {"items": [1]})

    def test_scope_isolation_and_distinct_intents(self):
        calls = []
        for req in (self.req, request(scope="tenant-b:service-a"), request(key="step-3")):
            self.guard.execute(req, lambda r: calls.append(r.token))
        self.assertEqual(len(set(calls)), 3)

    def test_token_depends_on_explicit_identity_not_argument_hash(self):
        self.assertEqual(self.req.token, request(arguments={"other": 2}).token)
        self.assertNotEqual(self.req.token, request(key="another-intent").token)

    def test_strict_json_and_identity_validation(self):
        for bad in ({1: "x"}, {"x": float("nan")}, {"x": float("inf")},
                    {"x": (1, 2)}, {"x": object()}, []):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(TypeError):
                    request(arguments=bad)
        for field in ("scope", "key", "tool"):
            with self.assertRaises(ValueError):
                request(**{field: " "})

    def test_result_encoding_failure_keeps_unknown(self):
        calls = []
        def call(req):
            calls.append(1)
            return object()
        self.assertEqual(self.guard.execute(self.req, call).state, "unknown")
        self.guard.execute(self.req, call)
        self.assertEqual(calls, [1])

    def test_keyboard_interrupt_and_cancellation_preserve_reservation(self):
        for error in (KeyboardInterrupt, asyncio.CancelledError, SystemExit):
            req = request(key=error.__name__)
            with self.assertRaises(error):
                self.guard.execute(req, lambda r: (_ for _ in ()).throw(error()))
            self.assertEqual(self.guard.get(req).state, "unknown")
            self.guard.execute(req, lambda r: self.fail())

    def test_errors_in_verifier_propagate_without_changing_state(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(ConnectionError):
            self.guard.reconcile(self.req, lambda r: (_ for _ in ()).throw(ConnectionError()))
        self.assertEqual(self.guard.get(self.req).state, "unknown")

    def test_invalid_observation_cannot_resolve_unknown(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TypeError):
            self.guard.reconcile(self.req, lambda r: {"applied": True})
        with self.assertRaises(ValueError):
            Observation(applied=True, result=1)
        with self.assertRaises(TypeError):
            Observation(applied="yes", evidence="x")
        with self.assertRaises(ValueError):
            Observation(result=1)
        self.assertEqual(self.guard.get(self.req).state, "unknown")

    def test_unserializable_verification_result_keeps_unknown(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TypeError):
            self.guard.reconcile(self.req, lambda r: Observation(True, object(), "proof"))
        self.assertEqual(self.guard.get(self.req).state, "unknown")

    def test_verification_requires_existing_reservation(self):
        with self.assertRaises(KeyError):
            self.guard.reconcile(self.req, lambda r: self.fail())
        self.assertIsNone(self.guard.get(self.req))

    def test_tool_error_payload_is_returned_not_claimed_verified(self):
        receipt = self.guard.execute(self.req, lambda r: {"isError": True, "message": "failed"})
        self.assertEqual(receipt.state, "returned")
        self.assertIsNone(receipt.evidence)
        self.assertEqual(receipt.to_dict()["next_action"], "inspect_result")

    def test_returned_payload_can_be_independently_verified(self):
        self.guard.execute(self.req, lambda r: {"isError": True})
        receipt = self.guard.reconcile(self.req, lambda r: Observation(True, 7, "ledger:7"))
        self.assertEqual(receipt.state, "verified")
        self.guard.reconcile(self.req, lambda r: self.fail("verified record was re-observed"))

    def test_concurrent_verification_wins_over_late_tool_response(self):
        entered, release = threading.Event(), threading.Event()
        def call(req):
            entered.set()
            release.wait(10)
            return "late response"
        with ThreadPoolExecutor(1) as pool:
            job = pool.submit(self.guard.execute, self.req, call)
            try:
                self.assertTrue(entered.wait(5))
                self.guard.reconcile(self.req, lambda r: Observation(True, "observed", "ledger:1"))
            finally:
                release.set()
            self.assertEqual(job.result(10).result, "observed")
        self.assertEqual(self.guard.get(self.req).state, "verified")

    def test_inconclusive_verifier_reloads_late_completion(self):
        self.guard.execute(self.req, lambda r: (_ for _ in ()).throw(TimeoutError()))
        def verify(req):
            self.guard.reconcile(req, lambda r: Observation(True, "observed", "ledger:1"))
            return Observation()
        self.assertEqual(self.guard.reconcile(self.req, verify).state, "verified")

    def test_parallel_processes_only_dispatch_once(self):
        ctx = multiprocessing.get_context("spawn")
        barrier, output = ctx.Barrier(5), ctx.Queue()
        workers = [ctx.Process(target=process_racer, args=(str(self.path), barrier, output))
                   for _ in range(4)]
        try:
            for worker in workers:
                worker.start()
            barrier.wait(timeout=20)
            for worker in workers:
                worker.join(20)
                self.assertEqual(worker.exitcode, 0)
            events = [output.get(timeout=5) for _ in range(5)]
            self.assertEqual(events.count("dispatch"), 1)
            self.assertEqual(len(events), 5)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(5)
            output.close()

    def test_process_death_before_and_after_external_commit(self):
        env = dict(os.environ, PYTHONPATH=str(Path(agent_receipt.__file__).resolve().parents[1]))
        for mode in ("before", "after"):
            with self.subTest(mode=mode):
                req = request(key=mode)
                effect = Path(self.temp.name) / f"effect-{mode}.txt"
                script = '''
import os, sys
from pathlib import Path
from agent_receipt import Guard, Request
db, effect, mode = sys.argv[1:]
r = Request(scope="tenant-a:service-a", key=mode, tool="create_record:v1", arguments={"value":"example"})
def call(req):
    if mode == "after":
        with open(effect, "w") as f:
            f.write(req.token)
            f.flush()
            os.fsync(f.fileno())
    os._exit(23)
Guard(db).execute(r, call)
'''
                run = subprocess.run([sys.executable, "-c", script, str(self.path), str(effect), mode],
                                     env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 23, run.stderr)
                receipt = Guard(self.path).execute(req, lambda r: self.fail("crashed call repeated"))
                self.assertEqual(receipt.state, "unknown")
                self.assertEqual(effect.exists(), mode == "after")
                observation = (Observation(True, {"token": effect.read_text()}, str(effect.name))
                               if effect.exists() else Observation())
                receipt = self.guard.reconcile(req, lambda r: observation)
                self.assertEqual(receipt.state, "verified" if mode == "after" else "unknown")

    def test_database_failures_prevent_dispatch(self):
        self.path.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.guard.execute(self.req, lambda r: self.fail())

    def test_unrelated_database_is_not_adopted(self):
        other = Path(self.temp.name) / "other.sqlite"
        with closing(sqlite3.connect(other)) as db:
            db.execute("CREATE TABLE user_data (value TEXT)")
        with self.assertRaises(ValueError):
            Guard(other)

    def test_database_version_mismatch_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            Guard(self.path)

    def test_arguments_not_persisted_in_journal(self):
        req = request(arguments={"password": "private-sentinel-123"})
        self.guard.execute(req, lambda r: "ok")
        self.assertNotIn(b"private-sentinel-123", self.path.read_bytes())

    def test_json_null_return_is_terminal(self):
        receipt = self.guard.execute(self.req, lambda r: None)
        self.assertEqual(receipt.state, "returned")
        self.assertIsNone(self.guard.execute(self.req, lambda r: self.fail()).result)

    def test_bad_callback_does_not_consume_operation(self):
        with self.assertRaises(TypeError):
            self.guard.execute(self.req, None)
        self.assertIsNone(self.guard.get(self.req))

    def test_memory_database_rejected(self):
        with self.assertRaises(ValueError):
            Guard(":memory:")

    def test_async_callback_rejected_before_reservation(self):
        async def call(req):
            return 1
        with self.assertRaises(TypeError):
            self.guard.execute(self.req, call)
        self.assertIsNone(self.guard.get(self.req))


if __name__ == "__main__":
    unittest.main()
