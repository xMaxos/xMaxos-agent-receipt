"""One durable dispatch reservation per (scope, key), on a local SQLite file."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Iterator, Literal


def _json(value: Any) -> str:
    # Reject coercions such as {1: ...} -> {"1": ...}, tuples and NaN.
    def check(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise TypeError("Expected strict JSON values with string object keys")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _name(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("scope, key and tool must be non-empty strings")
    return value


@dataclass(frozen=True, init=False)
class Request:
    """A host-assigned operation identity and an immutable JSON input snapshot.

    Include the destination/tenant and tool version in scope/tool or arguments.
    Keep the same scope/key across retries, even across model turns and restarts.
    """

    scope: str
    key: str
    tool: str
    _arguments_json: str = field(repr=False)
    fingerprint: str

    def __init__(self, *, scope: str, key: str, tool: str, arguments: dict):
        if type(arguments) is not dict:
            raise TypeError("arguments must be a JSON object")
        for name, value in (("scope", scope), ("key", key), ("tool", tool)):
            object.__setattr__(self, name, _name(value))
        payload = _json(arguments)
        object.__setattr__(self, "_arguments_json", payload)
        digest = hashlib.sha256(_json([tool, json.loads(payload)]).encode()).hexdigest()
        object.__setattr__(self, "fingerprint", digest)

    @property
    def arguments(self) -> dict:
        """Return a fresh copy: callbacks cannot mutate the recorded identity."""
        return json.loads(self._arguments_json)

    @property
    def token(self) -> str:
        """Stable correlation token; pass through to a supporting backend."""
        return "ar1_" + hashlib.sha256(_json([self.scope, self.key]).encode()).hexdigest()


@dataclass(frozen=True)
class Receipt:
    scope: str
    key: str
    tool: str
    fingerprint: str
    state: Literal["unknown", "returned", "verified"]
    result: Any = None
    evidence: str | None = None
    replayed: bool = False

    def to_dict(self) -> dict:
        """Small structured output for an agent's tool dispatcher."""
        return {
            "scope": self.scope, "key": self.key, "tool": self.tool,
            "fingerprint": self.fingerprint, "state": self.state,
            "result": self.result, "evidence": self.evidence,
            "replayed": self.replayed,
            "next_action": "verify_effect" if self.state == "unknown" else "inspect_result",
            "may_dispatch_again": False,
        }


@dataclass(frozen=True)
class Observation:
    """Trusted adapter evidence, never an LLM's assertion of success.

    applied=True means the entire intended effect was authoritatively observed,
    correlated to this exact operation. Missing/partial/stale results are inconclusive.
    """

    applied: bool = False
    result: Any = None
    evidence: str | None = None

    def __post_init__(self):
        if type(self.applied) is not bool:
            raise TypeError("applied must be a bool")
        if self.applied and (type(self.evidence) is not str or not self.evidence.strip()):
            raise ValueError("An applied observation requires an evidence reference")
        if not self.applied and (self.result is not None or self.evidence is not None):
            raise ValueError("An inconclusive observation cannot contain a result or evidence")


class RequestConflict(ValueError):
    """An existing scope/key was reused with a different tool or arguments."""


class Guard:
    """Process-safe sync/async guard sharing one local filesystem database.

    Reservations never expire. A lost process may leave an unknown receipt forever.
    This sacrifices automatic progress to prevent a second local dispatch.
    """

    _APP_ID = 0x41524350

    def __init__(self, path: str | Path):
        if str(path) == ":memory:" or str(path).startswith("file:"):
            raise ValueError("Use a durable local database file, not memory/URI mode")
        self.path = Path(path).resolve()
        with self._transaction() as db:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id not in (0, self._APP_ID) or (app_id == 0 and (tables or version)):
                raise ValueError("Refusing to use a database belonging to another application")
            if app_id == self._APP_ID and version != 1:
                raise ValueError("Unsupported Agent Receipt database version")
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                scope TEXT NOT NULL, action_key TEXT NOT NULL,
                tool TEXT NOT NULL, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('unknown','returned','verified')),
                result_json TEXT, evidence TEXT,
                PRIMARY KEY (scope, action_key)
            )""")
            db.execute(f"PRAGMA application_id={self._APP_ID}")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read(db: sqlite3.Connection, request: Request) -> sqlite3.Row | None:
        row = db.execute("SELECT * FROM receipts WHERE scope=? AND action_key=?",
                         (request.scope, request.key)).fetchone()
        if row is not None and (row["fingerprint"] != request.fingerprint or row["tool"] != request.tool):
            raise RequestConflict("Operation identity already belongs to different inputs")
        return row

    @staticmethod
    def _receipt(row: sqlite3.Row, *, replayed: bool) -> Receipt:
        return Receipt(
            scope=row["scope"], key=row["action_key"], tool=row["tool"],
            fingerprint=row["fingerprint"], state=row["state"],
            result=json.loads(row["result_json"]) if row["result_json"] is not None else None,
            evidence=row["evidence"], replayed=replayed,
        )

    def get(self, request: Request) -> Receipt | None:
        return self._get(request, replayed=True)

    def _get(self, request: Request, *, replayed: bool) -> Receipt | None:
        with self._transaction() as db:
            row = self._read(db, request)
            return None if row is None else self._receipt(row, replayed=replayed)

    def _reserve(self, request: Request) -> Receipt | None:
        with self._transaction() as db:
            row = self._read(db, request)
            if row is not None:
                return self._receipt(row, replayed=True)
            db.execute("INSERT INTO receipts VALUES (?,?,?,?, 'unknown',NULL,NULL)",
                       (request.scope, request.key, request.tool, request.fingerprint))
        return None  # The reservation is durable before any callback can run.

    @staticmethod
    def _is_async(call: Any) -> bool:
        return inspect.iscoroutinefunction(call) or inspect.iscoroutinefunction(getattr(call, "__call__", None))

    def execute(self, request: Request, call: Callable[[Request], Any]) -> Receipt:
        """Reserve durably before dispatch. Never retry an existing reservation.

        A normal JSON return is recorded as 'returned', not proof of business success.
        Callback/serialization errors yield 'unknown'; process-control exceptions
        propagate, with the reservation already durable. Error text is not persisted.
        """
        if not callable(call) or self._is_async(call):
            raise TypeError("call must be synchronous; use aexecute for async callbacks")
        existing = self._reserve(request)
        if existing is not None:
            return existing
        # No DB lock is held during tool execution. The reservation is committed.
        try:
            result_json = _json(call(request))
        except Exception:
            return self._get(request, replayed=False)
        return self._finish(request, result_json, state="returned", evidence=None)

    async def aget(self, request: Request) -> Receipt | None:
        """Read a receipt without blocking the event loop on SQLite."""
        return await asyncio.to_thread(self.get, request)

    async def aexecute(self, request: Request,
                       call: Callable[[Request], Coroutine[Any, Any, Any]]) -> Receipt:
        """Reserve off-loop, then await an async callback on the caller's event loop.

        Cancellation propagates and never releases a reservation. A cancelled
        SQLite worker can still commit: cancellation is not permission to retry.
        Ordinary callback errors yield an unknown (or concurrently verified) receipt.
        """
        if not callable(call) or not self._is_async(call):
            raise TypeError("call must be an async function or async callable object")
        existing = await asyncio.to_thread(self._reserve, request)
        if existing is not None:
            return existing
        try:
            result_json = _json(await call(request))
        except Exception:
            return await asyncio.to_thread(self._get, request, replayed=False)
        return await asyncio.to_thread(self._finish, request, result_json,
                                       state="returned", evidence=None)

    async def areconcile(self, request: Request,
                         verify: Callable[[Request], Coroutine[Any, Any, Observation]]) -> Receipt:
        """Await a trusted read-only verifier; never dispatch or release a reservation."""
        if not callable(verify) or not self._is_async(verify):
            raise TypeError("verify must be an async function or async callable object")
        current = await self.aget(request)
        if current is None:
            raise KeyError("No dispatch reservation exists for this operation")
        if current.state == "verified":
            return current
        observation = await verify(request)
        if not isinstance(observation, Observation):
            raise TypeError("verify must return Observation")
        if not observation.applied:
            return await self.aget(request)
        return await asyncio.to_thread(self._finish, request, _json(observation.result),
                                       state="verified", evidence=observation.evidence)

    def reconcile(self, request: Request, verify: Callable[[Request], Observation]) -> Receipt:
        """Read-only verification; never dispatches or releases a reservation.

        A verifier may also verify a returned payload (including an error payload).
        An authoritative positive observation can resolve an unknown outcome. An
        empty lookup cannot prove the original request will never commit later.
        """
        current = self.get(request)
        if current is None:
            raise KeyError("No dispatch reservation exists for this operation")
        if current.state == "verified":
            return current
        observation = verify(request)
        if not isinstance(observation, Observation):
            raise TypeError("verify must return Observation")
        if not observation.applied:
            # Reload: a live executor may have completed while verification ran.
            return self.get(request)
        return self._finish(request, _json(observation.result), state="verified",
                            evidence=observation.evidence)

    def _finish(self, request: Request, result_json: str, *, state: str,
                evidence: str | None) -> Receipt:
        with self._transaction() as db:
            row = self._read(db, request)
            # Verification outranks a tool return and is immutable once recorded.
            if row["state"] != "verified":
                db.execute("UPDATE receipts SET state=?, result_json=?, evidence=? "
                           "WHERE scope=? AND action_key=?",
                           (state, result_json, evidence, request.scope, request.key))
            return self._receipt(self._read(db, request), replayed=False)
