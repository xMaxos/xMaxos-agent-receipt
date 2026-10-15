# Agent Receipt: a lost response should not become a duplicate write

**Looking for independent testers and contributors.** I'm sharing a small,
MIT-licensed Python library for agent hosts with side-effecting tools.

A tool can commit a change and then lose its response. A timeout alone does not
prove the write failed. Retrying may repeat the change.

Agent Receipt saves a SQLite reservation **before dispatch**. Calls with the same
host-assigned operation key return the existing receipt; an uncertain outcome stays
`unknown` until a trusted adapter verifies the complete effect.

- **Sync + async:** includes task-cancellation handling.
- **Small:** Python 3.11+, no runtime dependencies.
- **Checkable:** 56 tests pass on Windows/Linux with Python 3.11/3.12, including
  tests of the installed package. New async checks are offline.

Try the local demo without an API key:

```sh
git clone https://github.com/xMaxos/xMaxos-agent-receipt.git
cd xMaxos-agent-receipt
python examples/async_quickstart.py
```

It cancels a task after a real local write, restarts the guard and verifies one
existing record.

**The tradeoff:** a crash before dispatch can leave the operation blocked even
though no write happened. There is no automatic retry or remote exactly-once
guarantee. Hosted side-effect APIs remain untested.

**Want to test?** Run the demo or suite and open an issue with your environment,
exact commit and reproduction. API friction is useful feedback too.

**Want to contribute?** Adapter examples with authoritative lookup, code review,
failure cases and documentation improvements are welcome. CONTRIBUTING.md has
focused starter tasks.

[Repository & demo](https://github.com/xMaxos/xMaxos-agent-receipt)
· [Contributing](https://github.com/xMaxos/xMaxos-agent-receipt/blob/main/CONTRIBUTING.md)
· [Issues](https://github.com/xMaxos/xMaxos-agent-receipt/issues)

Disclosure: the implementation and this post used AI assistance. This is an early
project; the published checks do not establish production reliability.
