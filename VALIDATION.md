# Validation record

Date: 2026-10-15. Initial local release, version 0.1.0.

## Environment actually exercised

- Windows, AMD64
- CPython 3.12.14
- SQLite 3.53.1
- Offline suite: no model API calls, credentials or external services
- Separate opt-in live suite: authenticated Codex CLI, requested model `gpt-6-astra`

Python 3.11+ is the declared package compatibility range. Other Python versions
and operating systems have not been executed in this validation.

## Behavioral checks

Command: `python -m unittest discover -s tests -v`

Result: 39 tests passed against the source checkout (33 core, six MCP adapter tests). Covered:

- Durable replay after restart; strict request identity and changed-input rejection
- Explicit scopes and legitimate repeated intents; immutable input snapshots
- Timeout after effect, result encoding failure, cancellation and process interrupts
- Four simultaneous processes contending for one operation: one callback dispatch
- Actual subprocess death before and after an external file commit
- In-flight writes, empty reads, late responses and concurrent reconciliation
- Verification evidence and return-value validation
- Distinction between returned error payloads and independently verified effects
- Corrupt/unrelated/wrong-version databases; nonpersistent database rejection
- No plaintext request arguments or exception messages in the journal
- MCP stdio initialization and tool invocation; host-owned operation slots;
  parameter drift and invented retry slots rejected before another dispatch

The source test run initially found two Windows cleanup errors in test fixtures:
SQLite connection context managers commit/rollback but do not close the connection.
The fixtures now close them explicitly. The subsequent 33-test run passed.

Command: `python examples/quickstart.py`

Result: lost response -> unknown -> replay blocked -> independently verified;
exactly one external test record was present.

## Fault experiment

Command: `python examples/crash_lab.py --trials 10 --output evidence`

Result: 120 executions; raw data in `evidence/fault-results.json` and readable
results in `evidence/fault-results.md`. Assertions checked all observed effect
counts and all guarded final states.

- Naive policy: 30 extra effects, no missing effects.
- Guarded policy: no extra effects, 10 missing effects explicitly left unknown.
- The missing effects all arise from a crash before the external write.

Ten repetitions exercise deterministic execution paths; they are not independent
samples of production conditions. The naive baseline is intentionally vulnerable
and is not a competing recovery framework.

## Not established

No claims of improved model intelligence, statistically measured production
reliability, superiority to other libraries, independent review, or exactly-once
remote effects. No hosted side-effect API, HTTP service, power-loss, multi-host
or network-filesystem testing. Verifier truthfulness and host-assigned operation
identity remain integration responsibilities. Live model/MCP testing is detailed below.

## Package verification

Built `agent_receipt-0.1.0-py3-none-any.whl` with the bundled setuptools build backend.
Ran `python scripts/verify_wheel.py`: installed the wheel offline into a fresh temporary
directory, asserted imports came from that installed directory, and passed all 39
behavioral tests against it (including child processes).

Artifact size and SHA-256 are recorded in `evidence/wheel-check.json`; test output is
in `evidence/wheel-tests.txt`. This confirms the built wheel, not just the source files.

## Live agent checks

Commands: `python scripts/live_agent_eval.py --model gpt-6-astra --case 0 --output evidence/live-pilot.json`
and `python scripts/live_agent_eval.py --model gpt-6-astra`.

Result: one pilot plus six main runs passed. Seven real model sessions made 16 MCP
tool calls. Five guarded scenarios covered normal success, a lost response after
commit, uncertainty before commit, replay after restarting the adapter, and two
intentional identical actions. A sixth main run used the same model and task without
the guard. The comparison agent also inspected the outcome and avoided duplication.

The model's final answers were reviewed against the recorded effects and receipts;
the unresolved case was explicitly reported as unconfirmed. Tool sequences were
chosen by the model. No instruction required retrying or inspecting in a fixed order.
The host restricted writable operations to specified synthetic ticket slots.

The preflight connectivity check initially failed inside the network-restricted shell.
The live runs used an approved network-enabled launcher while the nested agent kept
its read-only shell sandbox and disabled shell tools. Only the two local ticket MCP
tools were requested by the test. Raw runtime logs are excluded from publication.

The repository includes an offline CI matrix for Linux/Windows and Python 3.11/3.12;
its run status is available on GitHub. Live model tests are never started by CI.

The GitHub source repository is `https://github.com/xMaxos/xMaxos-agent-receipt`.
No PyPI publication or social-media post is part of this release.
