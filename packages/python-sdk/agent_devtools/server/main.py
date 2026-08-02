"""
Local debug server. Not a telemetry backend -- it reads the same SQLite
file the SDK writes to and exposes it as a small REST API for the DevTools
UI (or for curl / your own scripts).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..store import TraceStore, default_db_path
from ..diff import diff_runs

app = FastAPI(title="agent-devtools", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: Optional[TraceStore] = None


def get_store() -> TraceStore:
    global _store
    if _store is None:
        _store = TraceStore(default_db_path())
    return _store


def _event_to_dict(e):
    return {"id": e.id, "run_id": e.run_id, "seq": e.seq, "ts": e.ts, "type": e.type, "payload": e.payload}


@app.get("/api/health")
def health():
    return {"status": "ok", "db": get_store().db_path}


@app.get("/api/runs")
def list_runs():
    return get_store().list_runs()


@app.delete("/api/runs")
def clear_runs():
    """Delete every run and event from the store."""
    deleted = get_store().clear_runs()
    return {"deleted": deleted}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    """Delete a single run and all of its events."""
    store = get_store()
    if not store.delete_run(run_id):
        raise HTTPException(404, f"run '{run_id}' not found")
    return {"deleted": 1, "run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"run '{run_id}' not found")
    events = [_event_to_dict(e) for e in store.get_events(run_id)]
    return {"run": run, "events": events}


@app.get("/api/runs/{run_id}/prompt")
def get_prompt(run_id: str):
    store = get_store()
    events = store.get_events_by_types(run_id, ["prompt.assembled"])
    if not events:
        return {"prompt": None}
    return {"prompt": _event_to_dict(events[-1])}


@app.get("/api/runs/{run_id}/context")
def get_context(run_id: str):
    store = get_store()
    events = store.get_events_by_types(run_id, ["context.block"])
    return {"blocks": [_event_to_dict(e) for e in events]}


@app.get("/api/runs/{run_id}/retrieval")
def get_retrieval(run_id: str):
    store = get_store()
    events = store.get_events_by_types(run_id, ["retrieval.query", "retrieval.result"])
    return {"events": [_event_to_dict(e) for e in events]}


@app.get("/api/runs/{run_id}/memory")
def get_memory(run_id: str):
    store = get_store()
    events = store.get_events_by_types(
        run_id, ["memory.read", "memory.write", "memory.update", "memory.delete"]
    )
    return {"events": [_event_to_dict(e) for e in events]}


@app.get("/api/runs/{run_id}/tools")
def get_tools(run_id: str):
    store = get_store()
    events = store.get_events_by_types(run_id, ["tool.call", "tool.result"])
    return {"events": [_event_to_dict(e) for e in events]}


@app.get("/api/runs/{run_id}/assertions")
def get_assertions(run_id: str):
    store = get_store()
    events = store.get_events_by_types(run_id, ["assertion.passed", "assertion.failed"])
    return {"events": [_event_to_dict(e) for e in events]}


@app.get("/api/runs/{run_id}/fixture")
def export_fixture(run_id: str):
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(404, f"run '{run_id}' not found")
    return JSONResponse(store.export_fixture(run_id))


@app.get("/api/diff")
def get_diff(a: str, b: str):
    store = get_store()
    if store.get_run(a) is None:
        raise HTTPException(404, f"run '{a}' not found")
    if store.get_run(b) is None:
        raise HTTPException(404, f"run '{b}' not found")
    return diff_runs(store, a, b).to_dict()


# Static DevTools UI. Mounted last so /api/* above always wins routing.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
