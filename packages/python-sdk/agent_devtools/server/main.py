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
from ..diff import diff_runs, diff_runs_multi
from ..explain import explain_retrieval
from ..replay import ReplayEngine

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


@app.get("/api/runs/{run_id}/retrieval/explain")
def get_retrieval_explain(run_id: str):
    """Structured retrieval explanations: original/rewritten query, filters,
    embedding model, similarity & reranker scores, thresholds, and a
    human-readable reason for each selected/rejected candidate."""
    store = get_store()
    events = store.get_events_by_types(run_id, ["retrieval.query", "retrieval.result"])
    return {"explanations": explain_retrieval(events)}


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


# ---------------------------------------------------------------------------
# Deterministic Replay


@app.post("/api/runs/{run_id}/replay")
def create_replay(run_id: str):
    """Run a deterministic replay of the run and persist the ReplayReport.

    Deterministic replay re-executes the recorded event log in isolation
    (no network, no LLM, no user code) and reports whether the recorded
    behavior is self-consistent (``completed``), internally contradictory
    (``diverged``), or recorded a failure (``failed``).
    """
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(404, f"run '{run_id}' not found")
    report = ReplayEngine(store).replay(run_id)
    store.save_replay(run_id, report)
    return {"replay_id": report.replay_id, "report": report.to_dict()}


@app.get("/api/runs/{run_id}/replays")
def list_replays(run_id: str):
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(404, f"run '{run_id}' not found")
    return {"replays": store.list_replays(run_id)}


@app.get("/api/runs/{run_id}/replay/{replay_id}/report")
def get_replay_report(run_id: str, replay_id: str):
    store = get_store()
    replay = store.get_replay(run_id, replay_id)
    if replay is None:
        raise HTTPException(404, f"replay '{replay_id}' not found for run '{run_id}'")
    return {"replay": replay}


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


@app.get("/api/diff/multi")
def get_diff_multi(baseline: str, candidates: str):
    """Compare a baseline (good) run against multiple candidate (bad) runs.

    ``candidates`` is a comma-separated list of run ids. Returns the
    per-candidate diffs plus the causes that are common to *every*
    candidate -- the strongest signal of a shared root cause.
    """
    store = get_store()
    if store.get_run(baseline) is None:
        raise HTTPException(404, f"run '{baseline}' not found")
    cand_ids = [c.strip() for c in candidates.split(",") if c.strip()]
    missing = [c for c in cand_ids if store.get_run(c) is None]
    if missing:
        raise HTTPException(404, f"run(s) not found: {', '.join(missing)}")
    return diff_runs_multi(store, baseline, cand_ids)


# Static DevTools UI. Mounted last so /api/* above always wins routing.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
