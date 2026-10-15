"""Cancel an async tool after a real local commit, then verify without reissuing."""

import asyncio
import json
from pathlib import Path
import tempfile

from crash_lab import Backend, Guard, operation


async def demo(root):
    backend = await asyncio.to_thread(Backend, root / "external-effects.sqlite")
    guard = await asyncio.to_thread(Guard, root / "receipts.sqlite")
    request = operation()
    committed = asyncio.Event()

    async def create_without_response(req):
        await asyncio.to_thread(backend.create, req)
        committed.set()
        await asyncio.Event().wait()  # Simulate a response that never arrives.

    task = asyncio.create_task(guard.aexecute(request, create_without_response))
    try:
        await asyncio.wait_for(committed.wait(), 5)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    restarted = await asyncio.to_thread(Guard, root / "receipts.sqlite")

    async def must_not_run(req):
        raise AssertionError("A cancelled operation was dispatched again")

    replay = await restarted.aexecute(request, must_not_run)

    async def verify(req):
        return await asyncio.to_thread(backend.verify, req)

    final = await restarted.areconcile(request, verify)
    effects = await asyncio.to_thread(backend.count)
    assert replay.state == "unknown" and replay.replayed
    assert final.state == "verified" and effects == 1
    print(json.dumps({"after_cancellation": replay.state,
                      "after_verification": final.state,
                      "actual_external_effects": effects}, indent=2))


def main():
    with tempfile.TemporaryDirectory(prefix="agent-receipt-async-") as directory:
        asyncio.run(demo(Path(directory)))


if __name__ == "__main__":
    main()
