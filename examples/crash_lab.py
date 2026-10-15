"""Repeatable local fault experiment; no models, credentials or network required."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("AGENT_RECEIPT_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(ROOT / "src"))
from agent_receipt import Guard, Observation, Request


class Backend:
    """Separate durable effect store, deliberately without request deduplication."""

    def __init__(self, path):
        self.path = Path(path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS effects (id INTEGER PRIMARY KEY, token TEXT, value TEXT)")
            db.commit()

    def create(self, req):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA synchronous=FULL")
            cursor = db.execute("INSERT INTO effects (token,value) VALUES (?,?)",
                                (req.token, req.arguments["value"]))
            db.commit()
            return {"id": cursor.lastrowid}

    def verify(self, req):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT id,value FROM effects WHERE token=?", (req.token,)).fetchall()
        # A duplicate, partial result or mismatched value is not proof of correctness.
        if len(rows) == 1 and rows[0][1] == req.arguments["value"]:
            return Observation(True, {"id": rows[0][0]}, f"effects:{rows[0][0]}")
        return Observation()

    def count(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT count(*) FROM effects").fetchone()[0]


def operation(key="create-1"):
    return Request(scope="crash-lab:backend-a", key=key, tool="create:v1", arguments={"value": "sample"})


def crash_worker(directory, strategy, scenario):
    root = Path(directory)
    backend = Backend(root / "effects.sqlite")
    def call(req):
        if scenario == "crash_after_commit":
            backend.create(req)
        os._exit(23)  # Real process death, no Python cleanup or exception handler.
    if strategy == "guarded":
        Guard(root / "receipts.sqlite").execute(operation(), call)
    else:
        call(operation())


def run_scenario(directory, strategy, scenario):
    root = Path(directory)
    backend = Backend(root / "effects.sqlite")
    guard = Guard(root / "receipts.sqlite") if strategy == "guarded" else None
    req = operation()
    expected = 2 if scenario == "same_arguments_new_intent" else 1
    unknown_before_release = False

    def execute(callback, request=req):
        if guard:
            return guard.execute(request, callback).state
        try:
            callback(request)
            return "returned"
        except TimeoutError:
            return "unknown"

    if scenario == "normal_success":
        state = execute(backend.create)
    elif scenario == "same_arguments_new_intent":
        execute(backend.create)
        state = execute(backend.create, operation("create-2"))
    elif scenario == "timeout_after_commit":
        def lost_response(request):
            backend.create(request)
            raise TimeoutError("response lost after commit")
        execute(lost_response)
        state = execute(backend.create)
    elif scenario.startswith("crash_"):
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker",
                                str(root), strategy, scenario], capture_output=True, text=True, timeout=20)
        if child.returncode != 23:
            raise RuntimeError(f"Expected injected exit 23; got {child.returncode}: {child.stderr}")
        if guard:
            guard = Guard(root / "receipts.sqlite")
        state = execute(backend.create)
    elif scenario == "late_commit_after_empty_read":
        entered, release = threading.Event(), threading.Event()
        def late_call(request):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Experiment synchronization failed")
            backend.create(request)
            raise TimeoutError("caller lost contact before delayed commit")
        with ThreadPoolExecutor(1) as pool:
            job = pool.submit(execute, late_call)
            try:
                if not entered.wait(10):
                    raise RuntimeError("Experiment synchronization failed")
                if backend.count() != 0:
                    raise AssertionError("Expected empty read before releasing original request")
                if guard:
                    observed = guard.reconcile(req, backend.verify)
                    unknown_before_release = observed.state == "unknown"
                state = execute(backend.create)
            finally:
                release.set()
            job.result(timeout=15)
    else:
        raise ValueError(scenario)

    if guard and scenario not in ("normal_success", "same_arguments_new_intent"):
        state = guard.reconcile(req, backend.verify).state
    effects = backend.count()
    return {
        "scenario": scenario, "strategy": strategy, "expected_effects": expected,
        "observed_effects": effects, "extra_effects": max(0, effects - expected),
        "missing_effects": max(0, expected - effects), "final_state": state,
        "unknown_before_late_commit": unknown_before_release,
    }


SCENARIOS = ("normal_success", "timeout_after_commit", "crash_after_commit",
             "crash_before_commit", "late_commit_after_empty_read", "same_arguments_new_intent")


def experiment(trials):
    runs = []
    with tempfile.TemporaryDirectory(prefix="agent-receipt-lab-") as temp:
        for trial in range(1, trials + 1):
            for scenario in SCENARIOS:
                for strategy in ("naive", "guarded"):
                    directory = Path(temp) / f"{trial}-{scenario}-{strategy}"
                    directory.mkdir()
                    result = run_scenario(directory, strategy, scenario)
                    result["trial"] = trial
                    runs.append(result)
                    expected_effects = (0 if strategy == "guarded" and scenario == "crash_before_commit"
                                        else result["expected_effects"] +
                                        int(strategy == "naive" and scenario in (
                                            "timeout_after_commit", "crash_after_commit", "late_commit_after_empty_read")))
                    if result["observed_effects"] != expected_effects:
                        raise AssertionError(result)
                    if strategy == "guarded":
                        expected_state = ("unknown" if scenario == "crash_before_commit" else
                                          "returned" if scenario in ("normal_success", "same_arguments_new_intent")
                                          else "verified")
                        if result["final_state"] != expected_state:
                            raise AssertionError(result)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "os": platform.system(),
                        "machine": platform.machine(), "sqlite": sqlite3.sqlite_version},
        "trials_per_scenario_and_strategy": trials,
        "method": "Deterministic local fault injection; real subprocess exits and separate SQLite effect store.",
        "limitations": ["No LLM agents or hosted APIs tested", "No power-loss or distributed-filesystem tests",
                        "Naive baseline intentionally retries ambiguous writes once",
                        "Repeated deterministic cases are regression evidence, not population statistics",
                        "Crash before commit leaves guarded work incomplete by design"],
        "runs": runs,
    }


def markdown(report):
    lines = ["# Local fault experiment", "", f"Generated: {report['generated_at_utc']}", "",
             f"{report['trials_per_scenario_and_strategy']} trials per case and strategy; "
             f"{len(report['runs'])} executions in total.", "",
             "Baseline: one blind retry after an ambiguous failure. All effects are local test records.", "",
             "| Case | Strategy | Extra effects | Missing effects | Final states |",
             "|---|---|---:|---:|---|"]
    for scenario in SCENARIOS:
        for strategy in ("naive", "guarded"):
            runs = [r for r in report["runs"] if r["scenario"] == scenario and r["strategy"] == strategy]
            lines.append(f"| {scenario} | {strategy} | {sum(r['extra_effects'] for r in runs)} | "
                         f"{sum(r['missing_effects'] for r in runs)} | "
                         f"{', '.join(sorted(set(r['final_state'] for r in runs)))} |")
    lines += ["", "## Interpretation", "",
              "The guard suppresses repeat local dispatches in these cases. When the process dies before "
              "the effect, it leaves the task incomplete instead of guessing that a retry is safe. "
              "This availability cost is part of the result, not excluded from the score.", "",
              "These measurements do not establish improved LLM reasoning, production reliability, "
              "superiority to other libraries, or exactly-once remote execution.", "",
              "## Limits", ""] + [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=3, metavar=("DIRECTORY", "STRATEGY", "SCENARIO"))
    args = parser.parse_args()
    if args.worker:
        crash_worker(*args.worker)
        return
    if not 1 <= args.trials <= 1000:
        parser.error("--trials must be between 1 and 1000")
    report = experiment(args.trials)
    rendered = markdown(report)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "fault-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.output / "fault-results.md").write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
