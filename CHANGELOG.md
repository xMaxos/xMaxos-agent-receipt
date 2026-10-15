# Changelog

## 0.2.0 — 2026-10-15

- Add `Guard.aexecute`, `Guard.areconcile` and `Guard.aget` for asyncio callers.
  SQLite operations run off the event loop; callbacks run on the caller's loop.
- Preserve durable reservations through task cancellation, including cancellation
  while a database worker is still running. Sync and async calls share the journal.
- Add 17 async regression tests and a runnable cancellation/recovery demo.
- Add contributor guidance and channel-specific outreach notes.
- Make wheel verification select the current package version.

The existing synchronous API and version-1 SQLite schema remain compatible. No
automatic retry, remote exactly-once guarantee or new runtime dependency is added.

## 0.1.0 — 2026-10-15

- Initial synchronous guard, verifier, local fault lab and opt-in live MCP evaluation.
- 39 offline tests and seven live Codex sessions; limitations and evidence in
  `VALIDATION.md` and `evidence/`.
