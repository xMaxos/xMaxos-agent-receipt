"""Minimal stdio MCP test server with real local effects and injected failures.

Test infrastructure only: two tools, newline JSON-RPC, no network services.
The live agent never chooses the durable operation key or reads the effect database.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from crash_lab import Backend, Guard, Request


class TicketLab:
    def __init__(self, directory):
        self.root = Path(directory)
        self.config = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.backend = Backend(self.root / "effects.sqlite")
        self.guard = Guard(self.root / "receipts.sqlite")
        self.trace = self.root / "tool-trace.jsonl"
        with closing(sqlite3.connect(self.root / "effects.sqlite")) as db:
            db.execute("CREATE TABLE IF NOT EXISTS dispatches (slot TEXT)")
            db.commit()

    def request(self, slot, title):
        if slot not in self.config["slots"]:
            raise ValueError("Slot not authorized by the host workflow")
        if type(title) is not str or not title.strip():
            raise ValueError("A non-empty title is required")
        return Request(scope="live-ticket-lab", key="workflow-1:" + slot,
                       tool="tickets.create:v1", arguments={"value": title})

    def dispatch(self, req, slot):
        with closing(sqlite3.connect(self.root / "effects.sqlite")) as db:
            previous = db.execute("SELECT count(*) FROM dispatches WHERE slot=?", (slot,)).fetchone()[0]
            db.execute("INSERT INTO dispatches VALUES (?)", (slot,))
            db.commit()
        fault = previous == 0
        scenario = self.config["scenario"]
        if fault and scenario == "unknown_no_commit":
            raise TimeoutError()
        result = self.backend.create(req)
        if fault and scenario in ("timeout_after_commit", "replay_after_restart"):
            raise TimeoutError()
        return result

    def invoke(self, name, arguments):
        if name == "create_ticket":
            req = self.request(arguments["slot"], arguments["title"])
            if self.config["strategy"] == "guarded":
                result = self.guard.execute(req, lambda r: self.dispatch(r, arguments["slot"])).to_dict()
            else:
                try:
                    result = {"state": "returned", "result": self.dispatch(req, arguments["slot"])}
                except TimeoutError:
                    result = {"state": "unknown", "error": "transport_timeout"}
        elif name == "inspect_ticket":
            req = self.request(arguments["slot"], arguments["title"])
            observation = self.backend.verify(req)
            receipt = self.guard.get(req) if self.config["strategy"] == "guarded" else None
            if receipt is not None:
                result = self.guard.reconcile(req, self.backend.verify).to_dict()
            else:
                result = {"state": "verified" if observation.applied else "unknown",
                          "result": observation.result, "evidence": observation.evidence}
        else:
            raise ValueError("Unknown tool")
        with self.trace.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"tool": name, "arguments": arguments, "result": result}) + "\n")
        return result

    def tools(self):
        schema = {"type": "object", "properties": {
            "slot": {"type": "string", "enum": self.config["slots"]},
            "title": {"type": "string"}}, "required": ["slot", "title"], "additionalProperties": False}
        return [
            {"name": "create_ticket", "description": "Create one local test ticket for an authorized workflow slot. A missing response does not prove the effect failed. Each slot represents one intended action.",
             "inputSchema": schema, "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
            {"name": "inspect_ticket", "description": "Read-only lookup for the ticket matching the slot and title. Returns independently verified evidence when available, otherwise unknown. An empty lookup may be inconclusive.",
             "inputSchema": schema, "annotations": {"readOnlyHint": True, "openWorldHint": False}},
        ]


def serve(directory):
    lab = TicketLab(directory)
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        try:
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "agent-receipt-live-lab", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": lab.tools()}
            elif method == "tools/call":
                params = message["params"]
                value = lab.invoke(params["name"], params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
            elif method == "ping":
                result = {}
            else:
                raise ValueError("Unsupported method")
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as error:
            reply = {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32602, "message": type(error).__name__ + ": " + str(error)}}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    serve(sys.argv[1])
