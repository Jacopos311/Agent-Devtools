import json
from typing import Any, Callable, Dict, Union
from agent_devtools.store import TraceStore


def parse_agentshield_event(store: TraceStore, event_data: Union[str, Dict[str, Any]]) -> str:
    """Parsa un evento di spesa emesso da AgentShield e lo registra nel TraceStore.
    
    Mappa il campo `trace_id` di AgentShield al `run_id` nativo di Agent-Devtools.
    """
    if isinstance(event_data, str):
        payload = json.loads(event_data)
    else:
        payload = event_data

    run_id = payload.get("trace_id")
    if not run_id:
        raise ValueError("L'evento AgentShield non contiene un 'trace_id' valido.")
        
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
    """Callback in-process da passare a `SpendEvaluationEmitter(..., on_event=fn)` di AgentShield."""
    def callback(event: Dict[str, Any]) -> None:
        parse_agentshield_event(store, event)
    return callback


def ingest_ndjson_file(store: TraceStore, file_path: str) -> int:
    """Legge un file NDJSON generato da AgentShield e importa tutti gli eventi nel TraceStore."""
    count = 0
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                parse_agentshield_event(store, line)
                count += 1
    return count