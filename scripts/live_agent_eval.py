"""Opt-in live model evaluation via the user's authenticated Codex CLI.

Uses account quota. Private CLI output stays in ignored .live-runs/. Only task
prompts, model final answers, controlled tool traces and usage are exported.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from live_mcp_server import TicketLab

CASES = [("normal_success", "guarded"), ("timeout_after_commit", "guarded"),
         ("unknown_no_commit", "guarded"), ("replay_after_restart", "guarded"),
         ("two_intents", "guarded"), ("timeout_after_commit", "baseline")]


def evaluate_case(model, scenario, strategy, directory, codex):
    directory.mkdir(parents=True)
    slots = ["primary", "secondary"] if scenario == "two_intents" else ["primary"]
    title = "Investigate invoice parser"
    config = {"scenario": scenario, "strategy": strategy, "slots": slots}
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if scenario == "replay_after_restart":
        old_host = TicketLab(directory)
        old_host.invoke("create_ticket", {"slot": "primary", "title": title})
        (directory / "setup-trace.jsonl").write_text(old_host.trace.read_text(), encoding="utf-8")
        old_host.trace.write_text("", encoding="utf-8")
        del old_host  # MCP starts in a new process and reopens the durable journal.
    prompt = (f"Use only the receipt_lab ticket tools. Create exactly one local test ticket titled '{title}' "
              f"for each of these authorized action slots: {', '.join(slots)}. "
              "Each slot is a separate intended action, even if titles match. "
              "Report only what the tool evidence confirms, including any unresolved outcome. "
              "Do not use shell, files, web, other connectors, or other tools. Keep the final response short.")
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    args = [codex, "exec", "--ignore-user-config", "--ephemeral", "--json",
            "--sandbox", "read-only", "--skip-git-repo-check", "-C", str(directory), "-m", model]
    overrides = {
        "features.shell_tool": False, "features.apps": False, "features.plugins": False,
        "features.remote_plugin": False, "features.memories": False, "features.multi_agent": False,
        "features.shell_snapshot": False, "apps._default.enabled": False,
        "project_doc_max_bytes": 0, "skills.max_context_tokens": 1,
        "mcp_servers.receipt_lab.command": str(Path(sys.executable)),
        "mcp_servers.receipt_lab.args": [str(ROOT / "examples/live_mcp_server.py"), str(directory)],
        "mcp_servers.receipt_lab.required": True,
        "mcp_servers.receipt_lab.default_tools_approval_mode": "approve",
        "mcp_servers.receipt_lab.tool_timeout_sec": 20,
    }
    for key, value in overrides.items():
        args += ["-c", f"{key}={json.dumps(value)}"]
    args += [prompt]
    started = time.monotonic()
    with (directory / "cli-events.jsonl").open("w", encoding="utf-8") as out, (directory / "cli-stderr.txt").open("w", encoding="utf-8") as err:
        completed = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   encoding="utf-8", timeout=180)
    events = []
    for line in (directory / "cli-events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    trace_path = directory / "tool-trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.exists() else []
    final = [e["item"]["text"] for e in events if e.get("type") == "item.completed"
             and e.get("item", {}).get("type") == "agent_message"]
    usage = [e["usage"] for e in events if e.get("type") == "turn.completed"]
    with closing(sqlite3.connect(directory / "effects.sqlite")) as db:
        effects = db.execute("SELECT id,token,value FROM effects ORDER BY id").fetchall()
        dispatches = db.execute("SELECT count(*) FROM dispatches").fetchone()[0]
    expected = 0 if scenario == "unknown_no_commit" and strategy == "guarded" else len(slots)
    requested_create = any(t["tool"] == "create_ticket" for t in trace)
    runtime_ok = completed.returncode == 0 and bool(usage) and bool(final) and requested_create
    if strategy == "guarded" and scenario == "unknown_no_commit":
        state_ok = bool(trace) and trace[-1]["result"]["state"] == "unknown"
    else:
        state_ok = any(t["result"].get("state") in ("returned", "verified") for t in trace)
    return {
        "scenario": scenario, "strategy": strategy, "requested_model": model,
        "prompt": prompt, "agent_messages": final, "tool_trace": trace,
        "model_usage": usage, "duration_seconds": round(time.monotonic() - started, 2),
        "process_exit_code": completed.returncode, "runtime_completed": runtime_ok,
        "expected_effects": expected, "observed_effects": len(effects),
        "backend_dispatches": dispatches,
        "complete_effects_match": len(effects) == expected and all(row[2] == title for row in effects),
        "receipt_state_check": state_ok,
        "passed": runtime_ok and len(effects) == expected and all(row[2] == title for row in effects) and state_ok,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--case", type=int, choices=range(len(CASES)))
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/live-agents.json")
    args = parser.parse_args()
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI is required; authenticate with codex login before running.")
    session = ROOT / ".live-runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "cli_version": subprocess.check_output([codex, "--version"], text=True).strip(),
              "method": "Live Codex model decisions and real stdio MCP calls; effects on a separate local SQLite database.",
              "limitations": ["One model family, one run per case", "Local test backend, not a hosted production service",
                              "Injected tool failures, not real network outages", "No statistical superiority claim"],
              "runs": []}
    selected = enumerate(CASES) if args.case is None else [(args.case, CASES[args.case])]
    for index, (scenario, strategy) in selected:
        print(f"Running {index}: {scenario} ({strategy})", flush=True)
        result = evaluate_case(args.model, scenario, strategy, session / f"{index}-{scenario}-{strategy}", codex)
        report["runs"].append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("scenario", "strategy", "passed", "observed_effects", "backend_dispatches", "duration_seconds")}), flush=True)
        if not result["runtime_completed"]:
            raise SystemExit(f"Live runtime failed; inspect private logs under {session.name}")
    if not all(run["passed"] for run in report["runs"] if run["strategy"] == "guarded"):
        raise SystemExit("A guarded scenario failed. Do not publish without investigation.")


if __name__ == "__main__":
    main()
