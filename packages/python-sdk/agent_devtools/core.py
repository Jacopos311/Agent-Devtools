"""Context manager and core SDK functionality."""

import contextvars
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable

from .events import Event, EventType
from .transport import Transport
from .redaction import redact_sensitive_keys

_current_run_id = contextvars.ContextVar("current_run_id", default=None)


def get_current_run_id() -> Optional[str]:
    return _current_run_id.get()


class RunContext:
    def __init__(
        self,
        project_name: str,
        db_path: Optional[str] = None,
        redactors: Optional[List[Callable[[Dict], Dict]]] = None,
    ):
        self.project_name = project_name
        self.db_path = db_path
        self.redactors = redactors or [redact_sensitive_keys]
        self.run_id = None
        self.transport = None
        self._start_time = None
        self._token = None

    def __enter__(self):
        self.transport = Transport(self.db_path)
        self.run_id = str(uuid.uuid4())
        self._start_time = datetime.utcnow()

        self.transport.create_run(
            run_id=self.run_id,
            project_name=self.project_name,
            status="running",
            created_at=self._start_time,
        )

        self._token = _current_run_id.set(self.run_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        status = "failed" if exc_type else "completed"
        duration_ms = int((datetime.utcnow() - self._start_time).total_seconds() * 1000)

        self.transport.update_run_status(self.run_id, status, duration_ms)

        if self._token is not None:
            _current_run_id.reset(self._token)

        return False

    def emit(self, event_type: EventType, payload: Dict[str, Any]):
        if self.run_id is None:
            raise RuntimeError("No active run")

        for redactor in self.redactors:
            payload = redactor(payload)

        event = Event(
            run_id=self.run_id,
            event_type=event_type,
            payload=payload,
        )
        self.transport.write_event(event)


def run(
    project_name: str,
    db_path: Optional[str] = None,
    redactors: Optional[List[Callable[[Dict], Dict]]] = None,
) -> RunContext:
    return RunContext(project_name, db_path, redactors)