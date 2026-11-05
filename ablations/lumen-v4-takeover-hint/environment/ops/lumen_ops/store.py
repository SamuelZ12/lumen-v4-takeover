"""SQLite storage: current state map, immutable baseline, append-only event log.

State is a flat map ``key -> JSON value``; a missing key and ``None`` are the
same thing. Domain code only touches state through :class:`Tx`, which records
before/after deltas and attaches them to the next emitted event, so every
accepted transition is replayable from the evidence bundle alone.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import CLOCK_KEY, SCHEMA_VERSION
from .canonical import canonical_json
from .timeutil import format_ts, parse_ts

ACTORS = ("agent", "scheduler")
OUTCOMES = ("accepted", "rejected", "noop")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baseline (id INTEGER PRIMARY KEY CHECK (id = 0), snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, envelope TEXT NOT NULL);
"""


def _copy(value: Any) -> Any:
    return None if value is None else json.loads(canonical_json(value))


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def last_seq(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]


def read_state(conn: sqlite3.Connection) -> dict[str, Any]:
    return {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM state ORDER BY key")}


class Tx:
    """One command's view of state. Writes are buffered until :meth:`flush`.

    ``registry`` gives handlers access to cross-domain services such as the
    scheduler's boundary sources.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        registry: Any = None,
        readonly: bool = False,
        request_id: str | None = None,
        seeding: bool = False,
    ):
        self._conn = conn
        self.run_id = run_id
        self.registry = registry
        self.readonly = readonly
        self.request_id = request_id
        self._seeding = seeding
        self._writes: dict[str, Any] = {}
        self._pending: dict[str, tuple[Any, Any]] = {}  # key -> (before, after) since last emit
        self._next_seq = last_seq(conn) + 1
        self.events: list[dict[str, Any]] = []

    # -- reads -----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._writes:
            value = self._writes[key]
        else:
            row = self._conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            value = None if row is None else json.loads(row[0])
        return default if value is None else _copy(value)

    def keys(self, prefix: str = "") -> list[str]:
        stored = {
            row[0]
            for row in self._conn.execute(
                "SELECT key FROM state WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
            )
        }
        for key, value in self._writes.items():
            if key.startswith(prefix):
                (stored.add if value is not None else stored.discard)(key)
        return sorted(stored)

    def now(self) -> datetime:
        return parse_ts(self.get(CLOCK_KEY)["now"])

    @property
    def next_seq(self) -> int:
        """Sequence ID the next :meth:`emit` gets (lets history records cite their event)."""
        return self._next_seq

    # -- writes ----------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        if self.readonly:
            raise RuntimeError(f"read-only command attempted to write {key!r}")
        before = self.get(key)
        after = _copy(value)
        self._writes[key] = after
        if self._seeding:
            return
        original = self._pending[key][0] if key in self._pending else before
        if original == after:
            self._pending.pop(key, None)
        else:
            self._pending[key] = (original, after)

    def delete(self, key: str) -> None:
        self.set(key, None)

    def emit(
        self,
        type: str,
        *,
        resource: str,
        payload: dict[str, Any] | None = None,
        outcome: str = "accepted",
        actor: str = "agent",
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Append an event carrying every state change made since the previous emit."""
        if self.readonly or self._seeding:
            raise RuntimeError("events cannot be emitted from read-only commands or seeders")
        if actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        delta = [
            {"key": key, "before": before, "after": after}
            for key, (before, after) in self._pending.items()
        ]
        if outcome != "accepted" and delta:
            raise RuntimeError(f"{outcome} event {type!r} must not carry a state delta")
        event = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "seq": self._next_seq,
            "ts": format_ts(self.now()),
            "type": type,
            "actor": actor,
            "request_id": self.request_id,
            "job_id": job_id,
            "resource": resource,
            "outcome": outcome,
            "payload": _copy(payload or {}),
            "delta": delta,
        }
        self._next_seq += 1
        self._pending = {}
        self.events.append(event)
        return _copy(event)

    def flush(self) -> None:
        """Persist buffered writes and events (caller owns the SQL transaction)."""
        if self._pending:
            raise RuntimeError(
                f"state changed without an event: {sorted(self._pending)}"
            )
        for key, value in self._writes.items():
            if value is None:
                self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT INTO state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, canonical_json(value)),
                )
        for event in self.events:
            self._conn.execute(
                "INSERT INTO events (seq, envelope) VALUES (?, ?)",
                (event["seq"], canonical_json(event)),
            )
