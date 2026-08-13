"""AgentShield (agentshield-spend) spend-evaluation adapter.

Parses AgentShield v1 spend-evaluation events and records them in the
TraceStore so spend policy decisions render alongside the agent's own trace.

Key mapping: AgentShield ``trace_id`` -> agent-devtools native ``run_id``.

Robustness rules (from cross-stack E2E verification):
  - A missing ``trace_id`` never raises: events fall back to the
    ``"unattributed"`` run so a missing correlation id cannot crash the host
    agent runtime through the in-process callback.
  - The run row is auto-created on first event, so ingested events are
    immediately visible in ``list_runs`` instead of being orphaned.
  - NDJSON ingestion skips malformed lines (with a warning) instead of
    aborting the whole import.
"""
import json
import logging
from typing import Any, Callable, Dict, Union

from agent_devtools.store import TraceStore

log = logging.getLogger(__name__)

DEFAULT_RUN_ID = "unattributed"
DEFAULT_AGENT_NAME = "agentshield"


def _ensure_run(store: TraceStore, run_id: str, agent_name: str) -> None:
    """Create the run row if missing.

    Must only create once: ``TraceStore.create_run`` resets the per-run
    sequence counter, so calling it per event would corrupt event ordering.
    """
    if store.get_run(run_id) is None:
        store.create_run(run_id, agent_name, {"source": "agentshield"})


def parse_agentshield_event(store: TraceStore, event_data: Union[str, Dict[str, Any]]) -> str:
    """Parse one AgentShield spend event and log it into the TraceStore.

    Maps the AgentShield ``trace_id`` field to the native ``run_id``.
    Returns the run id the event was logged under.
    """
    if isinstance(event_data, str):
        payload = json.loads(event_data)
    else:
        payload = event_data

    if not isinstance(payload, dict):
        raise ValueError(
            "AgentShield event must be a JSON object, got %s" % type(payload).__name__
        )

    run_id = payload.get("trace_id") or DEFAULT_RUN_ID
    agent_name = payload.get("agent_id") or DEFAULT_AGENT_NAME

    _ensure_run(store, run_id, agent_name)

    store.log_event(
        run_id=run_id,
        event_type="agentshield.spend.evaluation",
        payload={
            "schema_version": payload.get("schema_version"),
            "event_id": payload.get("event_id"),
            "timestamp": payload.get("timestamp"),
            "agent_id": payload.get("agent_id"),
            "session_id": payload.get("session_id"),
            "transaction": payload.get("transaction"),
            "decision": payload.get("decision"),
            "evaluation": payload.get("evaluation", []),
        },
    )
    return run_id


def make_agentshield_callback(store: TraceStore) -> Callable[[Dict[str, Any]], None]:
    """In-process callback to pass to AgentShield's
    ``SpendEvaluationEmitter.emit(..., on_event=fn)``."""
    def callback(event: Dict[str, Any]) -> None:
        parse_agentshield_event(store, event)
    return callback


def ingest_ndjson_file(store: TraceStore, file_path: str) -> int:
    """Read an AgentShield NDJSON file and import all events into the TraceStore.

    Malformed lines are skipped with a warning instead of aborting the import,
    so one bad line cannot drop every event that follows it.
    Returns the number of events successfully imported.
    """
    count = 0
    skipped = 0
    with open(file_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                parse_agentshield_event(store, line)
                count += 1
            except (json.JSONDecodeError, ValueError) as exc:
                skipped += 1
                log.warning(
                    "agentshield ingest: skipping malformed line %d in %s (%s)",
                    lineno, file_path, exc,
                )
    if skipped:
        log.warning(
            "agentshield ingest: imported %d event(s), skipped %d line(s) from %s",
            count, skipped, file_path,
        )
    return count
