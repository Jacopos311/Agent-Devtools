"""SQLite transport for event storage."""

import json
import sqlite3
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .events import Event, EventType


class Transport:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.environ.get(
                "AGENT_DEVTOOLS_DB_PATH",
                str(Path.home() / ".agent-devtools" / "store.db")
            )
        self.db_path = db_path
        Path(os.path.dirname(db_path)).mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id VARCHAR PRIMARY KEY,
                    project_name VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    duration_ms INTEGER
                );

                CREATE TABLE IF NOT EXISTS events (
                    id VARCHAR PRIMARY KEY,
                    run_id VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    event_type VARCHAR NOT NULL,
                    payload JSON NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            """)

    def create_run(self, run_id: str, project_name: str, status: str, created_at: datetime):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, project_name, status, created_at) VALUES (?, ?, ?, ?)",
                (run_id, project_name, status, created_at.isoformat())
            )

    def update_run_status(self, run_id: str, status: str, duration_ms: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE runs SET status = ?, duration_ms = ? WHERE id = ?",
                (status, duration_ms, run_id)
            )

    def write_event(self, event: Event):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (id, run_id, timestamp, event_type, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.run_id,
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    json.dumps(event.payload)
                )
            )

    def get_run(self, run_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_runs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            return [dict(row) for row in rows]

    def count_runs(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def get_events(self, run_id: str, event_type: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM events WHERE run_id = ?"
            params = [run_id]
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY timestamp ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_events_by_type(self, run_id: str, event_type: str) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND event_type = ? ORDER BY timestamp ASC",
                (run_id, event_type)
            ).fetchall()
            return [dict(row) for row in rows]

    def count_events(self, run_id: str, event_type: Optional[str] = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT COUNT(*) FROM events WHERE run_id = ?"
            params = [run_id]
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            return conn.execute(query, params).fetchone()[0]

    def export_run(self, run_id: str) -> Dict:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        events = self.get_events(run_id, limit=10000)
        return {
            "run": run,
            "events": events
        }

    def import_run(self, data: Dict) -> str:
        run_data = data["run"]
        run_id = run_data["id"]
        events = data.get("events", [])

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, project_name, status, created_at, duration_ms) VALUES (?, ?, ?, ?, ?)",
                (run_id, run_data["project_name"], run_data["status"],
                 run_data["created_at"], run_data.get("duration_ms"))
            )
            for evt in events:
                conn.execute(
                    "INSERT OR REPLACE INTO events (id, run_id, timestamp, event_type, payload) VALUES (?, ?, ?, ?, ?)",
                    (evt["id"], evt["run_id"], evt["timestamp"], evt["event_type"], json.dumps(evt["payload"]))
                )
        return run_id