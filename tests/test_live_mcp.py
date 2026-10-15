from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from live_mcp_server import TicketLab
from agent_receipt import RequestConflict


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.arguments = {"slot": "primary", "title": "Investigate invoice parser"}

    def lab(self, scenario="timeout_after_commit"):
        (self.directory / "config.json").write_text(json.dumps({
            "scenario": scenario, "strategy": "guarded", "slots": ["primary"]}), encoding="utf-8")
        return TicketLab(self.directory)

    def dispatch_count(self):
        with closing(sqlite3.connect(self.directory / "effects.sqlite")) as db:
            return db.execute("SELECT count(*) FROM dispatches").fetchone()[0]

    def test_lost_response_is_recovered_through_adapter(self):
        lab = self.lab()
        self.assertEqual(lab.invoke("create_ticket", self.arguments)["state"], "unknown")
        self.assertTrue(lab.invoke("create_ticket", self.arguments)["replayed"])
        verified = lab.invoke("inspect_ticket", self.arguments)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(lab.backend.count(), 1)
        self.assertEqual(self.dispatch_count(), 1)

    def test_model_cannot_invent_new_operation_slot(self):
        lab = self.lab()
        with self.assertRaises(ValueError):
            lab.invoke("create_ticket", {"slot": "retry-1", "title": "same"})
        self.assertEqual(self.dispatch_count(), 0)

    def test_model_cannot_change_parameters_to_bypass_guard(self):
        lab = self.lab()
        lab.invoke("create_ticket", self.arguments)
        with self.assertRaises(RequestConflict):
            lab.invoke("create_ticket", {"slot": "primary", "title": "different"})
        self.assertEqual(self.dispatch_count(), 1)

    def test_inconclusive_lookup_does_not_enable_retry(self):
        lab = self.lab("unknown_no_commit")
        lab.invoke("create_ticket", self.arguments)
        self.assertEqual(lab.invoke("inspect_ticket", self.arguments)["state"], "unknown")
        self.assertEqual(lab.invoke("create_ticket", self.arguments)["state"], "unknown")
        self.assertEqual(lab.backend.count(), 0)
        self.assertEqual(self.dispatch_count(), 1)

    def test_new_adapter_process_state_replays_existing_operation(self):
        self.lab().invoke("create_ticket", self.arguments)
        restarted = TicketLab(self.directory)
        self.assertTrue(restarted.invoke("create_ticket", self.arguments)["replayed"])
        self.assertEqual(self.dispatch_count(), 1)

    def test_stdio_protocol_initialization_and_tool_call(self):
        self.lab("normal_success")
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "create_ticket", "arguments": self.arguments}},
        ]
        run = subprocess.run([sys.executable, str(ROOT / "examples/live_mcp_server.py"), str(self.directory)],
                             input="".join(json.dumps(m) + "\n" for m in messages),
                             text=True, capture_output=True, timeout=15, env=os.environ.copy())
        self.assertEqual(run.returncode, 0, run.stderr)
        replies = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        self.assertEqual(len(replies[1]["result"]["tools"]), 2)
        self.assertEqual(json.loads(replies[2]["result"]["content"][0]["text"])["state"], "returned")


if __name__ == "__main__":
    unittest.main()
