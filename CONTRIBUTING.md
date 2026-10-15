# Contributing

Agent Receipt is a small MIT-licensed library for agent hosts. Independent reproductions,
useful adapter examples and counterexamples are especially welcome. Development of
the initial implementation and the async extension used AI assistance; passing tests
are evidence for the documented scenarios, not independent review.

## Start small

Pick one of these, or open an issue describing the integration you actually need:

1. **An adapter example with authoritative lookup.** Keep credentials optional and
   out of the repo. Explain how the host persists operation identity and checks the
   complete intended effect. Include offline tests for timeout-after-commit and an
   inconclusive lookup. External SDKs belong in optional examples, not runtime dependencies.
2. **Independent reproduction.** Run the offline suite and demos; report OS, Python,
   SQLite version and the exact commit. Distinguish simulation from real hosted effects.
3. **A minimal failure case.** Add a deterministic test for a duplicate dispatch,
   false verification, cancellation race or identity collision. Use events/barriers
   rather than timing assumptions where possible.

These are suggestions, not claims that maintainers have reserved work or opened issues.

## Local checks

Python 3.11+; the tests and demos need no credentials or model access:

```sh
python -m unittest discover -s tests -v
python examples/crash_lab.py
python examples/quickstart.py
python examples/async_quickstart.py
python -m pip wheel . --no-deps --wheel-dir dist
python scripts/verify_wheel.py
```

The wheel check selects the version declared in `pyproject.toml`; keep only one wheel
for that version in `dist/`. Build tooling may need network access to install its build
dependencies. The separate live-agent runner is opt-in and uses account/model quota.

## Pull requests

State the concrete failure or use case, behavior after the change and checks run.
Keep runtime dependencies empty. Preserve the current journal schema unless a
migration has been designed and tested. Sync and async callers must share one
reservation even when they overlap.

Never make an uncertain operation retryable because of a timeout, cancellation,
lease expiry, missing lookup result or model assertion. A returned tool payload is
not independently verified success. Do not claim exactly-once remote effects.

Please inspect AI-assisted contributions and disclose the assistance in the PR.
Do not include credentials, customer data, private logs or local session transcripts.
