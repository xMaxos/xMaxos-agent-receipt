"""Runnable agent-host adapter example, entirely local."""

import json
from pathlib import Path
import tempfile

from crash_lab import Backend, Guard, operation


def main():
    with tempfile.TemporaryDirectory(prefix="agent-receipt-example-") as directory:
        root = Path(directory)
        backend = Backend(root / "external-effects.sqlite")
        guard = Guard(root / "receipts.sqlite")
        request = operation()

        def create_with_lost_response(req):
            backend.create(req)
            raise TimeoutError("The response was lost after the write committed")

        first = guard.execute(request, create_with_lost_response)
        restarted = Guard(root / "receipts.sqlite")
        second = restarted.execute(request, backend.create)
        final = restarted.reconcile(request, backend.verify)
        assert first.state == second.state == "unknown"
        assert second.replayed and final.state == "verified" and backend.count() == 1
        print(json.dumps({"first_call": first.to_dict(), "retry": second.to_dict(),
                          "after_verification": final.to_dict(),
                          "actual_external_effects": backend.count()}, indent=2))


if __name__ == "__main__":
    main()
