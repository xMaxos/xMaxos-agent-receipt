# Local fault experiment

Generated: 2026-10-15T12:16:37.116515+00:00

10 trials per case and strategy; 120 executions in total.

Baseline: one blind retry after an ambiguous failure. All effects are local test records.

| Case | Strategy | Extra effects | Missing effects | Final states |
|---|---|---:|---:|---|
| normal_success | naive | 0 | 0 | returned |
| normal_success | guarded | 0 | 0 | returned |
| timeout_after_commit | naive | 10 | 0 | returned |
| timeout_after_commit | guarded | 0 | 0 | verified |
| crash_after_commit | naive | 10 | 0 | returned |
| crash_after_commit | guarded | 0 | 0 | verified |
| crash_before_commit | naive | 0 | 0 | returned |
| crash_before_commit | guarded | 0 | 10 | unknown |
| late_commit_after_empty_read | naive | 10 | 0 | returned |
| late_commit_after_empty_read | guarded | 0 | 0 | verified |
| same_arguments_new_intent | naive | 0 | 0 | returned |
| same_arguments_new_intent | guarded | 0 | 0 | returned |

## Interpretation

The guard suppresses repeat local dispatches in these cases. When the process dies before the effect, it leaves the task incomplete instead of guessing that a retry is safe. This availability cost is part of the result, not excluded from the score.

These measurements do not establish improved LLM reasoning, production reliability, superiority to other libraries, or exactly-once remote execution.

## Limits

- No LLM agents or hosted APIs tested
- No power-loss or distributed-filesystem tests
- Naive baseline intentionally retries ambiguous writes once
- Repeated deterministic cases are regression evidence, not population statistics
- Crash before commit leaves guarded work incomplete by design
