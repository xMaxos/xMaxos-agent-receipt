# A timeout is not proof that an agent's write failed

Agent Receipt is a small, dependency-free Python library for agent hosts that need
to avoid blindly repeating side-effecting tool calls.

It commits a SQLite dispatch reservation before calling a tool. Repeated operation
IDs return a recorded response or an explicit `unknown` outcome. A trusted read-only
verifier can resolve uncertainty using an operation-specific backend lookup.

The deliberately conservative bit: reservations never expire, and an empty lookup
does not make a retry safe. The original write may still arrive later.

The repo includes a reproducible local fault lab: lost responses, real subprocess
crashes before/after a commit, delayed writes, and legitimate identical new actions.
Across 120 runs, the naive retry baseline produced 30 extra effects; the guard
produced none. The guard also left 10 crash-before-commit actions incomplete and
explicitly unknown. That tradeoff is included in the published raw results.

Seven real Codex agent runs, including a pilot, also passed with a local MCP adapter.
The model recovered committed writes, left unresolved outcomes unconfirmed, and
respected the distinction between replay and two intentional identical actions.
The unguarded comparison agent also handled its timeout correctly; this small sample
does not demonstrate superiority. Hosted side-effect APIs remain untested.

This is not a new algorithm or an exactly-once guarantee. It is a focused
implementation and regression lab that others can inspect, reproduce and build on.

I would particularly welcome adapter examples with authoritative outcome lookup,
independent reproductions, and counterexamples to the documented guarantees.

Python 3.11+. MIT license. No model API or account required for the offline experiments.
The live integration test is opt-in and uses the tester's own model/account quota.

Repository: https://github.com/xMaxos/xMaxos-agent-receipt

Publication note: this post is a draft; it has not been sent to social media.
Do not describe this initial local release as independently reviewed or production-proven.
