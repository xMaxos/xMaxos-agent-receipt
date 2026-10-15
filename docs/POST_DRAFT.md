# A timeout is not proof that an agent's write failed

![Agent Receipt: A timeout isn't a failed write.](assets/agent-receipt-social.jpg)

**An open-source experiment for developers building side-effecting agent tools.**

A tool writes a record. The response disappears. The host sees a timeout.
Should it issue the write again?

Agent Receipt makes that uncertainty explicit. It records a durable SQLite
reservation before dispatch; further calls with the same host-assigned operation
identity return a receipt instead of invoking the tool again. A trusted, read-only
adapter can reconcile the outcome using authoritative evidence.

[Try Agent Receipt](https://github.com/xMaxos/xMaxos-agent-receipt#try-it)
· [Inspect the validation](../VALIDATION.md)
· [Help develop it](../CONTRIBUTING.md)

## Three states, one reservation

![Unknown, returned and verified receipt states. No state authorizes redispatch.](assets/receipt-states.svg)

- **unknown:** the action may be running, complete or never started. Verify it.
- **returned:** a JSON response was recorded. Inspect the payload, including errors.
- **verified:** a trusted adapter observed the complete intended effect.

Returned does not mean verified. An empty read does not authorize a retry; the
original write could still arrive later.

## Try the failure, then inspect the recovery

```sh
git clone https://github.com/xMaxos/xMaxos-agent-receipt.git
cd xMaxos-agent-receipt
python examples/async_quickstart.py
```

The demo cancels an async tool after a committed local record, restarts the guard,
blocks redispatch and verifies the existing effect. It uses no model or external
service. The expected output is:

```json
{
  "after_cancellation": "unknown",
  "after_verification": "verified",
  "actual_external_effects": 1
}
```

## What has actually been checked?

Version 0.2.0 has 56 behavioral tests and passing Windows/Linux CI on Python 3.11
and 3.12, including tests against the installed wheel. The async checks cover
cancellation, concurrent callers and database work off the event loop.

The fault lab includes 120 deterministic executions. A deliberately naive retry
baseline produced 30 extra effects; the guard produced none and left 10 operations
incomplete and explicitly unknown. Those missing effects are part of the tradeoff.
This is not a comparison with competing recovery libraries.

Seven earlier live Codex/MCP runs tested the synchronous integration. The unguarded
comparison agent also handled its timeout safely. Those runs demonstrate limited
integration, not superiority, and do not test the new async API.

## Help make it useful

**Testers:** run the demo or suite, then report your environment, exact commit and
any reproducible failure or integration friction.

**Contributors:** small adapter examples with authoritative lookup, deterministic
failure cases, documentation improvements and code review are welcome.
[Start with the contribution guide](../CONTRIBUTING.md).

Python 3.11+. MIT license. No runtime dependencies. A crash before dispatch can
leave the operation blocked forever. This is local dispatch protection, not a
remote exactly-once guarantee; hosted effect APIs and production conditions remain
untested. The project and this article used AI assistance.

---

**Publication status:** this is a draft, not a submitted community post. The shorter
[weekly-thread comment](REDDIT_COMMENT.md) is the prepared Reddit version. Reddit
comment image support varies; use the text and repository link there. The cover and
state diagram are shown in the GitHub README and can accompany posts where images
are supported. Follow the destination's current rules before publishing.
