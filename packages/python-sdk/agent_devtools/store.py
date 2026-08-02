"""
Local, append-only trace store.

Design principle (from the project vision): store raw debug events
append-only, and derive views (memory, retrieval, prompt, tools,
comparison) on read. This keeps framework-specific detail intact instead
of forcing every event into one rigid shape up front.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL DEFAULT 'running',
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events (run_id);
CREATE INDEX IF NOT EXISTS idx_events_run_type ON events (run_id, type);
"""


def default_db_path() -> str:
    """Where traces live if the caller doesn't specify a path.

    Honors AGENT_DEVTOOLS_DB so the SDK (writer) and `agent-devtools serve`
    (reader) can be pointed at the same file without extra wiring.

    If AGENT_DEVTOOLS_DB is not set, walks up from the current working
    directory looking for an existing ``.agent_devtools/trace.db`` that
    contains at least one run.  If none is found in parent directories,
    also checks subdirectories (up to 2 levels deep).  This ensures that
    scripts and the server find the same database regardless of which
    subdirectory they are run from, and avoids accidentally picking up an
    empty schema-only file that was created by a previous call.  Falls
    back to creating a new database in the current working directory.
    """
    env_path = os.environ.get("AGENT_DEVTOOLS_DB")
    if env_path:
        return env_path

    start = os.getcwd()

    # 1. Walk up the directory tree looking for an existing .agent_devtools/
    #    that has at least one run recorded.
    for parent in _walk_parents(start):
        candidate = os.path.join(parent, ".agent_devtools", "trace.db")
        if os.path.isfile(candidate) and _db_has_runs(candidate):
            return candidate

    # 2. Walk subdirectories (up to 2 levels deep) looking for an existing
    #    database.  This covers the common case where the user ran example
    #    scripts from a subdirectory like examples/stale-memory-bug/ and
    #    then starts the server from the project root.
    try:
        for entry in os.scandir(start):
            if entry.is_dir():
                # Level 1: subdir/.agent_devtools/trace.db
                candidate = os.path.join(entry.path, ".agent_devtools", "trace.db")
                if os.path.isfile(candidate) and _db_has_runs(candidate):
                    return candidate
                # Level 2: subdir/*/.agent_devtools/trace.db
                try:
                    for sub in os.scandir(entry.path):
                        if sub.is_dir():
                            candidate = os.path.join(sub.path, ".agent_devtools", "trace.db")
                            if os.path.isfile(candidate) and _db_has_runs(candidate):
                                return candidate
                except PermissionError:
                    continue
    except PermissionError:
        pass

    # 3. Nothing found – create a fresh one in the CWD
    root = os.path.join(start, ".agent_devtools")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "trace.db")


def _walk_parents(path: str):
    """Yield *path* and every parent directory, stopping at the filesystem
    root (drive letter on Windows, ``/`` on POSIX)."""
    prev = None
    while prev != path:
        yield path
        prev = path
        path = os.path.dirname(path)


def _db_has_runs(path: str) -> bool:
    """Return True if *path* is a SQLite file with at least one row in
    the ``runs`` table."""
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT 1 FROM runs LIMIT 1").fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


@dataclass
class EventRow:
    id: int
    run_id: str
    seq: int
    ts: float
    type: str
    payload: dict


class TraceStore:
    """Thread-safe wrapper around a single SQLite trace database."""

    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or default_db_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._seq_counters: dict[str, int] = {}

    # -- writing -----------------------------------------------------

    def create_run(self, run_id: str, agent_name: str, metadata: Optional[dict] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (id, agent_name, started_at, status, metadata) "
                "VALUES (?, ?, ?, 'running', ?)",
                (run_id, agent_name, time.time(), json.dumps(metadata or {})),
            )
            self._conn.commit()
        self._seq_counters[run_id] = 0

    def finish_run(self, run_id: str, status: str = "ok") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
                (time.time(), status, run_id),
            )
            self._conn.commit()

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run and all of its events. Returns True if the
        run existed and was deleted, False otherwise."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            cur = self._conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            self._conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            self._seq_counters.pop(run_id, None)
        return deleted

    def clear_runs(self) -> int:
        """Delete every run and event in the store. Returns the number of
        runs that were removed."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM events")
            cur = self._conn.execute("DELETE FROM runs")
            self._conn.commit()
            deleted = cur.rowcount
        self._seq_counters.clear()
        return deleted

    def log_event(self, run_id: str, event_type: str, payload: dict) -> int:
        seq = self._seq_counters.get(run_id, 0)
        self._seq_counters[run_id] = seq + 1
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (run_id, seq, ts, type, payload) VALUES (?, ?, ?, ?, ?)",
                (run_id, seq, time.time(), event_type, json.dumps(payload, default=str)),
            )
            self._conn.commit()
            return cur.lastrowid

    # -- reading -------------------------------------------------------

    def list_runs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM events e WHERE e.run_id = r.id) AS event_count "
                "FROM runs r ORDER BY started_at DESC"
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(d["metadata"] or "{}")
            out.append(d)
        return out

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"] or "{}")
        return d

    def get_events(self, run_id: str, event_type: Optional[str] = None) -> list[EventRow]:
        with self._lock:
            if event_type:
                rows = self._conn.execute(
                    "SELECT * FROM events WHERE run_id = ? AND type = ? ORDER BY seq ASC",
                    (run_id, event_type),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY seq ASC", (run_id,)
                ).fetchall()
        return [
            EventRow(
                id=r["id"], run_id=r["run_id"], seq=r["seq"], ts=r["ts"],
                type=r["type"], payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def get_events_by_types(self, run_id: str, types: Iterable[str]) -> list[EventRow]:
        types = list(types)
        placeholders = ",".join("?" for _ in types)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM events WHERE run_id = ? AND type IN ({placeholders}) ORDER BY seq ASC",
                (run_id, *types),
            ).fetchall()
        return [
            EventRow(
                id=r["id"], run_id=r["run_id"], seq=r["seq"], ts=r["ts"],
                type=r["type"], payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def export_fixture(self, run_id: str) -> dict:
        """Portable trace/fixture format -- an escape hatch, not the main path."""
        run = self.get_run(run_id)
        events = self.get_events(run_id)
        return {
            "schema": "agent-devtools/fixture@1",
            "run": run,
            "events": [
                {"seq": e.seq, "ts": e.ts, "type": e.type, "payload": e.payload} for e in events
            ],
        }

    def import_fixture(self, fixture: dict) -> str:
        run = fixture["run"]
        run_id = run["id"]
        self.create_run(run_id, run["agent_name"], run.get("metadata"))
        for e in fixture["events"]:
            self.log_event(run_id, e["type"], e["payload"])
        self.finish_run(run_id, run.get("status", "ok"))
        return run_id
