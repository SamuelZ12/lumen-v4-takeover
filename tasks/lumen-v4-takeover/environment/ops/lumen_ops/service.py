"""The sidecar service: seeding and atomic dispatch of public commands.

Every public call runs in one SQLite transaction under a process-wide lock.
Success commits state and events together; an :class:`OpsError` rolls back
everything (no state or time change) and, for mutating commands, logs one
``rejected`` event without a delta.
"""

import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from . import CLOCK_KEY, SCHEMA_VERSION
from .canonical import canonical_json
from .errors import OpsError, UsageError
from .registry import Domain, Registry, discover
from .spec import Spec
from .store import (
    Tx,
    connect,
    create_schema,
    read_meta,
    read_state,
    transaction,
    write_meta,
)

RUN_ID_FILENAME = "run_id"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class OpsService:
    def __init__(self, db_path: str | Path, *, registry: Registry | None = None):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"{self.db_path} is not seeded")
        self.registry = registry or discover()
        self._conn = connect(self.db_path)
        self._lock = threading.Lock()
        self.run_id = read_meta(self._conn, "run_id")

    @classmethod
    def seed(
        cls,
        db_path: str | Path,
        spec: Spec,
        *,
        run_dir: str | Path,
        extra_domains: Iterable[Domain] = (),
    ) -> "OpsService":
        """Create and seed a fresh database, then write the run-ID marker."""
        db_path = Path(db_path)
        if db_path.exists():
            raise FileExistsError(f"{db_path} already exists")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        registry = discover(extra_domains)
        run_id = uuid.uuid4().hex
        conn = connect(db_path)
        try:
            create_schema(conn)
            with transaction(conn):
                write_meta(conn, "run_id", run_id)
                write_meta(conn, "schema_version", str(SCHEMA_VERSION))
                write_meta(conn, "spec_sha256", spec.sha256)
                write_meta(conn, "request_counter", "0")
                tx = Tx(conn, run_id=run_id, registry=registry, seeding=True)
                for seeder in registry.seeders:
                    seeder(tx, spec)
                tx.flush()
                state = read_state(conn)
                if CLOCK_KEY not in state:
                    raise RuntimeError("no seeder set the fake clock")
                baseline = {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    "seq": 0,
                    "ts": state[CLOCK_KEY]["now"],
                    "state": state,
                }
                conn.execute(
                    "INSERT INTO baseline (id, snapshot) VALUES (0, ?)", (canonical_json(baseline),)
                )
        finally:
            conn.close()
        _atomic_write(Path(run_dir) / RUN_ID_FILENAME, run_id)
        return cls(db_path, registry=registry)

    def close(self) -> None:
        self._conn.close()

    @property
    def command_names(self) -> list[str]:
        return sorted(self.registry.commands)

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one public command. Returns ``{"ok": True, "result": ...}`` or ``{"ok": False, "error": ...}``."""
        command = self.registry.commands.get(name)
        if command is None:
            return {"ok": False, "error": UsageError(f"unknown command {name!r}").to_dict()}
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return {"ok": False, "error": UsageError("arguments must be an object").to_dict()}
        with self._lock:
            if not command.mutating:
                return self._read(command, args)
            return self._mutate(command, args)

    def _read(self, command, args):
        with transaction(self._conn, immediate=False):
            tx = Tx(self._conn, run_id=self.run_id, registry=self.registry, readonly=True)
            try:
                return {"ok": True, "result": command.handler(tx, args)}
            except OpsError as error:
                return {"ok": False, "error": error.to_dict()}

    def _next_request_id(self) -> str:
        counter = int(read_meta(self._conn, "request_counter")) + 1
        write_meta(self._conn, "request_counter", str(counter))
        return f"REQ-{counter:06d}"

    def _mutate(self, command, args):
        try:
            with transaction(self._conn):
                tx = Tx(
                    self._conn,
                    run_id=self.run_id,
                    registry=self.registry,
                    request_id=self._next_request_id(),
                )
                result = command.handler(tx, args)
                tx.flush()
            return {"ok": True, "result": result}
        except OpsError as error:
            with transaction(self._conn):
                tx = Tx(
                    self._conn,
                    run_id=self.run_id,
                    registry=self.registry,
                    request_id=self._next_request_id(),
                )
                tx.emit(
                    command.name,
                    resource=command.resource,
                    outcome="rejected",
                    payload={"args": args, "error": {"code": error.code, "message": error.message}},
                )
                tx.flush()
            return {"ok": False, "error": error.to_dict()}
