Keep the library small and dependency-free at runtime. Do not claim exactly-once remote effects.
Unknown outcomes must never automatically become retryable, including after a lease or timeout.
Run `python -m unittest discover -s tests -v` and `python examples/crash_lab.py` after behavioral changes.
Preserve the distinction between a returned tool response and independently verified effects.
