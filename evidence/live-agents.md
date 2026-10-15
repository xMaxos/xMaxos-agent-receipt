# Live AI-agent integration results

Date: 2026-10-15. Runtime: Codex CLI 0.162.0-alpha.17.2. Requested model: `gpt-6-astra`.

These are real model sessions invoking two tools through stdio MCP. The effects are
real writes to an isolated local SQLite ticket store. The transport failures are
injected by the test adapter. This is not a production-cloud reliability study.

| Scenario | Guard | Effects | Backend dispatches | Result |
|---|---|---:|---:|---|
| Normal success (pilot) | on | 1 | 1 | passed |
| Normal success | on | 1 | 1 | passed |
| Response lost after commit | on | 1 | 1 | verified by lookup |
| Unknown outcome before commit | on | 0 | 1 | explicitly left unconfirmed |
| Replay after adapter restart | on | 1 | 1 including setup | existing effect verified |
| Two intentional identical actions | on | 2 | 2 | both verified |
| Response lost after commit | off | 1 | 1 | agent inspected and avoided retry |

All seven runs passed automatic effect/state checks. Final responses were also
reviewed against their tool evidence. Six main runs plus one pilot made 16 model-chosen
MCP tool calls. The model was asked to create one ticket per host-authorized slot and
report only confirmed outcomes. No fixed tool sequence was given.

The baseline agent was also careful. These results validate that this integration
works with this model in these cases; they do **not** establish a comparative gain.
The deterministic crash lab separately exercises unsafe retry policies.

Raw task prompts, assistant messages, usage and controlled tool traces:

- [Main runs](live-agents.json)
- [Pilot](live-pilot.json)

The raw CLI diagnostic/session logs are private and excluded. They may contain local
paths or session identifiers. No provider credentials or real user records are included.

Limits: one model family, one main run per case, constrained host operation slots,
local effects, injected faults, no concurrent live agents, no production backend.
The core offline suite separately covers process crashes and concurrent processes.
