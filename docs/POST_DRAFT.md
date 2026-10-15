# Draft for the r/AI_Agents weekly Project Display thread

Not posted. Review and adapt before use; check the current thread and account's
self-promotion eligibility. This draft is not for HN, DEV or r/mcp.

---

**Agent Receipt: what should an agent host do when a write times out?**

I'm sharing a small MIT-licensed Python library developed with AI assistance.
The problem it addresses: a tool may commit a change and then lose its response.
Repeating the call can repeat the change.

Agent Receipt persists a SQLite reservation before dispatch. The same host-assigned
operation key returns a receipt instead of calling the tool again. An uncertain
outcome stays `unknown` until a trusted adapter verifies the complete effect.

The tradeoff matters: a crash before dispatch can leave an action unfinished forever.
An empty lookup does not unlock retries. This is local dispatch protection, not a
remote exactly-once guarantee.

The new 0.2.0 API supports async callbacks and preserves reservations when tasks are
cancelled. There are no runtime dependencies. Try the offline cancellation demo:

```sh
git clone https://github.com/xMaxos/xMaxos-agent-receipt.git
cd xMaxos-agent-receipt
python examples/async_quickstart.py
```

Expected result: `unknown` after cancellation, `verified` after lookup, one actual
record. The suite has 56 tests. Seven earlier live Codex/MCP runs covered the sync
adapter; they do not test the new async API. The unguarded comparison agent also
handled its timeout correctly, so those runs are integration evidence, not proof
that the guard outperforms an agent.

I'd welcome an independent reproduction or an example adapter with authoritative
operation lookup. What would make this useful in your tool dispatcher?

Repository: https://github.com/xMaxos/xMaxos-agent-receipt

Disclosure: the project and this draft used AI assistance. Hosted side-effect APIs
and production conditions remain untested.
